"""VA1 a VA3 (item 4.12): o elemento salvo que o texto cita entra na análise já vinculado, mesmo se a IA esquecer."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import Capitulo, TipoElemento
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

TEXTO = "Caeror entrou na villa.\n\nA cama estava vazia e Lanistia sorriu.\n\nVisão turva."


def _cenario(cliente: TestClient, usar_provedor_falso, sessao: Session, sugeridos):
    usar_provedor_falso(ProvedorFalso(elementos=sugeridos))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, capitulo_id).texto = TEXTO
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    for tipo, nome in [("PERSONAGEM", "Caeror"), ("PERSONAGEM", "Lanistia"), ("OBJETO", "cama"),
                       ("AMBIENTE", "villa"), ("PERSONAGEM", "Vis")]:
        assert cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": tipo, "nome": nome}).status_code == 201
    return capitulo_id


def _por_nome(cliente: TestClient, capitulo_id: int) -> dict:
    return {e["nome"]: e for e in cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()["elementos"]}


def teste_elemento_citado_e_esquecido_pela_ia_entra_vinculado(cliente, usar_provedor_falso, sessao_com_tabelas) -> None:
    c = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Caeror")])

    achados = _por_nome(cliente, c)

    assert achados["Lanistia"]["elemento_id"] is not None  # a IA esqueceu; o servidor achou
    assert achados["Lanistia"]["casamento_automatico"] is True
    assert achados["villa"]["elemento_id"] is not None


def teste_so_tipos_de_nome_proprio_e_palavra_inteira(cliente, usar_provedor_falso, sessao_com_tabelas) -> None:
    c = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [])

    achados = _por_nome(cliente, c)

    assert "cama" not in achados  # objeto fica de fora (VA2)
    assert "Vis" not in achados  # "Visão" não é "Vis"


def teste_nao_repete_o_que_a_ia_listou_nem_o_descartado(cliente, usar_provedor_falso, sessao_com_tabelas) -> None:
    c = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Caeror")])
    primeira = cliente.post(f"/capitulos/{c}/sugestoes").json()["elementos"]
    assert [e["nome"] for e in primeira].count("Caeror") == 1

    lanistia = next(e for e in primeira if e["nome"] == "Lanistia")
    # Lanistia já está vinculada: reanalisar não a duplica.
    segunda = cliente.post(f"/capitulos/{c}/sugestoes", params={"forcar": True}).json()["elementos"]
    assert [e["nome"] for e in segunda].count("Lanistia") == 1
    assert lanistia["elemento_id"] is not None
