"""Posicionar à mão o artefato num parágrafo (item 7.5b, PM1 a PM4): as rotas, a prioridade e a reanálise."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import CenaSugerida, ElementoSugerido, ParticipanteSugerido
from imagineer.modelos import Capitulo, SugestaoDeCena, SugestaoDeElemento, TipoElemento
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

TEXTO = "Abertura calma.\n\nNed ergueu a espada.\nO vento soprou forte.\n\nDepois, no pátio, Jon chorou."
INICIO_DO_VENTO = TEXTO.index("Ned ergueu")
INICIO_DO_FIM = TEXTO.index("Depois")

ARYA = ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Arya")  # o nome não está no texto: nasce sem posição
CENA = CenaSugerida(titulo="A espada", participantes=[ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Arya")], trecho_ancora=None)


def _cenario(cliente: TestClient, usar_provedor_falso, sessao: Session):
    provedor = usar_provedor_falso(ProvedorFalso(elementos=[ARYA], cenas_sugeridas=[CENA]))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, capitulo_id).texto = TEXTO
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{capitulo_id}/sugestoes")
    return provedor, capitulo_id


def _artefatos(cliente: TestClient, capitulo_id: int) -> dict[str, dict]:
    lista = cliente.get(f"/capitulos/{capitulo_id}/artefatos").json()["artefatos"]
    return {a["rotulo"]: a for a in lista}


def _elemento(sessao: Session) -> SugestaoDeElemento:
    return sessao.query(SugestaoDeElemento).one()


def teste_pm1_elemento_sem_posicao_e_posicionado_a_mao(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    assert _artefatos(cliente, capitulo_id)["Arya"]["posicao_no_texto"] is None
    sugestao = _elemento(sessao_com_tabelas)

    resposta = cliente.put(f"/sugestoes-elemento/{sugestao.id}/posicao", json={"posicao_no_texto": INICIO_DO_VENTO})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"sugestao_id": sugestao.id, "posicao_manual": INICIO_DO_VENTO}
    assert _artefatos(cliente, capitulo_id)["Arya"]["posicao_no_texto"] == INICIO_DO_VENTO


def teste_pm3_null_tira_a_posicao_manual(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    sugestao = _elemento(sessao_com_tabelas)
    cliente.put(f"/sugestoes-elemento/{sugestao.id}/posicao", json={"posicao_no_texto": INICIO_DO_VENTO})

    resposta = cliente.put(f"/sugestoes-elemento/{sugestao.id}/posicao", json={"posicao_no_texto": None})

    assert resposta.json()["posicao_manual"] is None
    assert _artefatos(cliente, capitulo_id)["Arya"]["posicao_no_texto"] is None


def teste_pm1_a_cena_tambem_se_posiciona_a_mao_e_ganha_da_citacao(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = sessao_com_tabelas.query(SugestaoDeCena).one()

    resposta = cliente.put(f"/sugestoes-cena/{cena.id}/posicao", json={"posicao_no_texto": INICIO_DO_FIM})

    assert resposta.status_code == 200, resposta.text
    assert _artefatos(cliente, capitulo_id)["A espada"]["posicao_no_texto"] == INICIO_DO_FIM


def teste_pm4_recusas(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    sugestao = _elemento(sessao_com_tabelas)

    assert cliente.put(f"/sugestoes-elemento/{sugestao.id}/posicao", json={"posicao_no_texto": 99999}).status_code == 422  # passa do fim
    assert cliente.put(f"/sugestoes-elemento/{sugestao.id}/posicao", json={"posicao_no_texto": -1}).status_code == 422
    assert cliente.put("/sugestoes-elemento/99999/posicao", json={"posicao_no_texto": 0}).status_code == 404
    assert cliente.put("/sugestoes-cena/99999/posicao", json={"posicao_no_texto": 0}).status_code == 404


def teste_pm2_a_reanalise_nao_desfaz_a_posicao_manual(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cliente.put(f"/sugestoes-elemento/{_elemento(sessao_com_tabelas).id}/posicao", json={"posicao_no_texto": INICIO_DO_VENTO})
    cliente.put(f"/sugestoes-cena/{sessao_com_tabelas.query(SugestaoDeCena).one().id}/posicao", json={"posicao_no_texto": INICIO_DO_FIM})

    cliente.post(f"/capitulos/{capitulo_id}/sugestoes?forcar=true")  # apaga e recria as não confirmadas

    artefatos = _artefatos(cliente, capitulo_id)
    assert artefatos["Arya"]["posicao_no_texto"] == INICIO_DO_VENTO
    assert artefatos["A espada"]["posicao_no_texto"] == INICIO_DO_FIM


def teste_tr3_a_cena_avulsa_de_um_trecho_nasce_sem_elementos_e_vira_artefato_no_paragrafo(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """O app cria a cena de um trecho selecionado por `POST /capitulos/{id}/frames` (tipo CENA): zero elementos é válido, a
    descrição leva o trecho e a posição é a do parágrafo; ela aparece como artefato de cena, sem sugestão por trás (TR3, TR4)."""
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)

    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={
            "tipo": "CENA",
            "titulo": "O vento",
            "descricao": "Em close\n\nTrecho do capítulo: «O vento soprou forte.»",
            "posicao_no_texto": INICIO_DO_VENTO,
            "estados_ids": [],
        },
    )

    assert resposta.status_code == 201, resposta.text
    artefato = _artefatos(cliente, capitulo_id)["O vento"]
    assert artefato["tipo"] == "CENA"
    assert artefato["sugestao_id"] is None and artefato["frame_id"] == resposta.json()["id"]
    assert artefato["posicao_no_texto"] == INICIO_DO_VENTO


def teste_pm3_reposicionar_a_cena_com_frame_posicionado_move_de_verdade(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    """O frame com posição própria manda sobre a manual; ao reposicionar a sugestão, o frame a segue (senão nada mudaria)."""
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = sessao_com_tabelas.query(SugestaoDeCena).one()
    # Uma cena confirmada tem frame; aqui ele é criado à mão e ligado à sugestão.
    criado = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"tipo": "CENA", "titulo": "A espada", "posicao_no_texto": INICIO_DO_VENTO, "estados_ids": []},
    ).json()
    cena.frame_id = criado["id"]
    sessao_com_tabelas.commit()
    assert _artefatos(cliente, capitulo_id)["A espada"]["posicao_no_texto"] == INICIO_DO_VENTO

    cliente.put(f"/sugestoes-cena/{cena.id}/posicao", json={"posicao_no_texto": INICIO_DO_FIM})

    assert _artefatos(cliente, capitulo_id)["A espada"]["posicao_no_texto"] == INICIO_DO_FIM
