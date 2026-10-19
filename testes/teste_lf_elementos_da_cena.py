"""Quem participa de cada cena nos artefatos (item 7.5b, LF4): o que a tela Cenas filtra por elemento."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from testes.teste_posicao_manual import _artefatos, _cenario
from testes.teste_rotas_prompts import _frame


def _livro_id(cliente: TestClient, capitulo_id: int) -> int:
    return cliente.get(f"/capitulos/{capitulo_id}").json()["livro_id"]


def teste_lf4_a_cena_sugerida_traz_os_nomes_dos_participantes_que_a_ia_sugeriu(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)

    artefatos = _artefatos(cliente, capitulo_id)

    assert artefatos["A espada"]["elementos"] == ["Arya"]


def teste_lf4_o_artefato_de_elemento_nao_traz_participantes(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)

    assert _artefatos(cliente, capitulo_id)["Arya"]["elementos"] == []


def teste_lf4_a_lista_de_cenas_do_livro_traz_os_participantes_de_cada_cena(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)

    corpo = cliente.get(f"/livros/{_livro_id(cliente, capitulo_id)}/cenas").json()

    [cena] = [a for g in corpo["capitulos"] for a in g["artefatos"]]
    assert cena["rotulo"] == "A espada" and cena["elementos"] == ["Arya"]


def teste_lf4_a_cena_de_um_trecho_sem_participante_vem_com_a_lista_vazia(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    _frame(cliente, capitulo_id, [], tipo="CENA")  # "No pátio", sem ninguém ligado

    assert _artefatos(cliente, capitulo_id)["No pátio"]["elementos"] == []


def teste_lf4_a_cena_confirmada_mostra_os_elementos_ligados_ao_frame_e_nao_repete_nome(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = _livro_id(cliente, capitulo_id)
    elemento = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Arya Stark", "estado_inicial": {"capitulo_id": capitulo_id, "descricao": "x"}},
    ).json()
    estado_id = cliente.get(f"/elementos/{elemento['id']}").json()["estados"][0]["id"]
    _frame(cliente, capitulo_id, [estado_id, estado_id], tipo="CENA")

    assert _artefatos(cliente, capitulo_id)["No pátio"]["elementos"] == ["Arya Stark"]
