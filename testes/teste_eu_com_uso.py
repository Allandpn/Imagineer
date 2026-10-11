"""O ``GET /eu`` com o uso e a cota, para a tela Perfil (item 7.5g, PF1)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.servicos.acesso import definir_usuario
from imagineer.modelos import DONO_ID, Usuario
from testes.teste_rotas_sugestoes import _livro_com_capitulos


def teste_o_eu_conta_os_livros_da_pessoa(cliente: TestClient) -> None:
    assert cliente.get("/eu").json()["livros"] == 0

    _livro_com_capitulos(cliente, capitulos=1)
    _livro_com_capitulos(cliente, capitulos=1)

    assert cliente.get("/eu").json()["livros"] == 2


def teste_o_dono_nao_tem_cota_e_uma_convidada_tem_a_padrao_ou_a_propria(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    assert cliente.get("/eu").json()["cota_efetiva_em_gb"] is None  # o dono

    maria = Usuario(login="maria@exemplo.com", nome="Maria", dono=False, usa_chaves_do_servidor=False)
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    definir_usuario(sessao_com_tabelas, maria.id)
    padrao = cliente.get("/eu").json()["cota_efetiva_em_gb"]
    assert isinstance(padrao, int) and padrao > 0

    maria.cota_em_gb = 7
    sessao_com_tabelas.commit()
    assert cliente.get("/eu").json()["cota_efetiva_em_gb"] == 7


def teste_o_eu_de_uma_pessoa_nao_conta_os_livros_de_outra(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    _livro_com_capitulos(cliente, capitulos=1)  # do dono
    maria = Usuario(login="maria@exemplo.com", nome="Maria", dono=False, usa_chaves_do_servidor=False)
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    definir_usuario(sessao_com_tabelas, maria.id)

    corpo = cliente.get("/eu").json()

    assert corpo["id"] == maria.id and corpo["livros"] == 0 and corpo["uso_em_bytes"] == 0
    assert DONO_ID != maria.id
