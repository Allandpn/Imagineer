"""A posição do frame — o "Ilustrar aqui" (item 3.4g): o frame manda na posição do artefato."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import CenaSugerida, ElementoSugerido, ParticipanteSugerido
from imagineer.modelos import Capitulo, TipoElemento
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

TEXTO = "Abertura calma.\n\nNed ergueu a espada.\nO vento soprou forte.\n\nDepois, no pátio, Jon chorou."
INICIO_DO_SEGUNDO = TEXTO.index("Ned ergueu")
INICIO_DO_TERCEIRO = TEXTO.index("Depois")

NED = ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned")


def _cenario(cliente: TestClient, usar_provedor_falso, sessao: Session, cenas=None, elementos=None):
    """Um capítulo de texto conhecido; analisado só se houver sugestões."""
    usar_provedor_falso(ProvedorFalso(elementos=elementos or [], cenas_sugeridas=cenas or []))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, capitulo_id).texto = TEXTO
    sessao.commit()
    if cenas or elementos:
        _escolher_modelo_de_extracao(cliente)
        cliente.post(f"/capitulos/{capitulo_id}/sugestoes")
    return livro, capitulo_id


def _criar_cena(cliente: TestClient, capitulo_id: int, **extra):
    return cliente.post(f"/capitulos/{capitulo_id}/frames", json={"tipo": "CENA", "titulo": "No pátio", **extra})


def _artefatos(cliente: TestClient, capitulo_id: int) -> list[dict]:
    return cliente.get(f"/capitulos/{capitulo_id}/artefatos").json()["artefatos"]


def _retrato(cliente: TestClient, livro_id: int, capitulo_id: int, nome: str, **extra) -> dict:
    elemento = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": nome, "estado_inicial": {"capitulo_id": capitulo_id, "descricao": "manto"}},
    ).json()
    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"tipo": "PERSONAGEM", "estados_ids": [elemento["estados"][0]["id"]], **extra},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# --------------------------------------------------------------------------- #
# O campo
# --------------------------------------------------------------------------- #


def teste_frame_guarda_e_devolve_a_posicao_escolhida(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)

    com = _criar_cena(cliente, c1, posicao_no_texto=INICIO_DO_TERCEIRO)
    sem = _criar_cena(cliente, c1)

    assert com.status_code == 201 and sem.status_code == 201
    assert com.json()["posicao_no_texto"] == INICIO_DO_TERCEIRO
    assert sem.json()["posicao_no_texto"] is None
    assert cliente.get(f"/frames/{com.json()['id']}").json()["posicao_no_texto"] == INICIO_DO_TERCEIRO
    listado = {f["id"]: f for f in cliente.get(f"/capitulos/{c1}/frames").json()}
    assert listado[com.json()["id"]]["posicao_no_texto"] == INICIO_DO_TERCEIRO


def teste_posicao_invalida_e_recusada_na_criacao_e_no_ajuste(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    frame = _criar_cena(cliente, c1).json()

    assert _criar_cena(cliente, c1, posicao_no_texto=-1).status_code == 422
    assert _criar_cena(cliente, c1, posicao_no_texto=len(TEXTO) + 1).status_code == 422
    assert _criar_cena(cliente, c1, posicao_no_texto=len(TEXTO)).status_code == 201  # o fim exato vale
    assert cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": -5}).status_code == 422
    assert cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": len(TEXTO) + 1}).status_code == 422


def teste_o_limite_da_posicao_do_frame_e_em_utf16(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """'a😀b' tem 3 caracteres Unicode e 4 unidades UTF-16 (a conta do app)."""
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    sessao_com_tabelas.get(Capitulo, c1).texto = "a\U0001F600b"
    sessao_com_tabelas.commit()

    assert _criar_cena(cliente, c1, posicao_no_texto=4).status_code == 201
    assert _criar_cena(cliente, c1, posicao_no_texto=5).status_code == 422


def teste_ajustar_muda_limpa_e_omitir_nao_mexe(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    frame = _criar_cena(cliente, c1, posicao_no_texto=INICIO_DO_SEGUNDO).json()

    omitido = cliente.patch(f"/frames/{frame['id']}", json={"titulo": "Novo título"}).json()
    movido = cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": INICIO_DO_TERCEIRO}).json()
    limpo = cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": None}).json()

    assert omitido["posicao_no_texto"] == INICIO_DO_SEGUNDO  # não mandar o campo não mexe nele
    assert movido["posicao_no_texto"] == INICIO_DO_TERCEIRO
    assert limpo["posicao_no_texto"] is None


def teste_mover_o_frame_sobe_a_revisao_do_livro(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """O app que guarda a lista do livro precisa saber que o ícone mudou de lugar."""
    livro, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    frame = _criar_cena(cliente, c1).json()
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": INICIO_DO_SEGUNDO})

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] > antes


# --------------------------------------------------------------------------- #
# O frame manda na posição do artefato
# --------------------------------------------------------------------------- #


def teste_confirmar_a_cena_nao_copia_a_posicao_mas_o_artefato_continua_nela(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        cenas=[CenaSugerida(titulo="A espada", participantes=[NED], trecho_ancora="O vento soprou")],
    )
    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["cenas"][0]

    frame = cliente.post(f"/capitulos/{c1}/frames", json={"sugestao_cena_id": sugestao["id"]}).json()

    assert frame["posicao_no_texto"] is None  # nada escolhido pela pessoa, nada gravado
    (artefato,) = _artefatos(cliente, c1)
    assert artefato["posicao_no_texto"] == INICIO_DO_SEGUNDO  # cai para a posição da sugestão


def teste_a_posicao_do_frame_vence_a_da_sugestao_na_cena(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """É assim que a pessoa corrige um lugar que a IA errou."""
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        cenas=[CenaSugerida(titulo="A espada", participantes=[NED], trecho_ancora="O vento soprou")],
    )
    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["cenas"][0]
    frame = cliente.post(f"/capitulos/{c1}/frames", json={"sugestao_cena_id": sugestao["id"]}).json()

    cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": INICIO_DO_TERCEIRO})

    (artefato,) = _artefatos(cliente, c1)  # um só: o frame é da sugestão, não vira artefato repetido
    assert (artefato["sugestao_id"], artefato["frame_id"]) == (sugestao["id"], frame["id"])
    assert artefato["posicao_no_texto"] == INICIO_DO_TERCEIRO

    cliente.patch(f"/frames/{frame['id']}", json={"posicao_no_texto": None})
    assert _artefatos(cliente, c1)[0]["posicao_no_texto"] == INICIO_DO_SEGUNDO  # limpou: volta à da sugestão


def teste_a_posicao_do_retrato_vence_a_do_nome_no_artefato_do_elemento(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    livro, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned")],
    )
    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]
    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Ned", "estado_inicial": {"capitulo_id": c1, "descricao": "manto"}},
    ).json()
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": elemento["id"]})
    assert _artefatos(cliente, c1)[0]["posicao_no_texto"] == INICIO_DO_SEGUNDO  # pelo nome

    frame = cliente.post(
        f"/capitulos/{c1}/frames",
        json={"tipo": "PERSONAGEM", "estados_ids": [elemento["estados"][0]["id"]], "posicao_no_texto": INICIO_DO_TERCEIRO},
    ).json()

    (artefato,) = _artefatos(cliente, c1)  # o retrato é do artefato do elemento, não um segundo
    assert artefato["frame_id"] == frame["id"]
    assert artefato["posicao_no_texto"] == INICIO_DO_TERCEIRO


# --------------------------------------------------------------------------- #
# Frame que nenhuma sugestão representa vira artefato próprio
# --------------------------------------------------------------------------- #


def teste_cena_inventada_a_mao_vira_artefato_com_e_sem_posicao(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    sem_posicao = _criar_cena(cliente, c1, titulo="Sem lugar").json()
    com_posicao = _criar_cena(cliente, c1, titulo="No pátio", posicao_no_texto=INICIO_DO_TERCEIRO).json()

    artefatos = _artefatos(cliente, c1)

    assert [(a["tipo"], a["rotulo"], a["posicao_no_texto"]) for a in artefatos] == [
        ("CENA", "No pátio", INICIO_DO_TERCEIRO),
        ("CENA", "Sem lugar", None),  # sem posição vem depois: a faixa "Sem posição" do item 7.5b
    ]
    assert all(a["sugestao_id"] is None and a["tipo_do_elemento"] is None for a in artefatos)
    assert {a["frame_id"] for a in artefatos} == {sem_posicao["id"], com_posicao["id"]}
    assert all(a["situacao"] == "CONFIRMADO" for a in artefatos)


def teste_retrato_de_elemento_sem_sugestao_vira_artefato_de_elemento(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    livro, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    retrato = _retrato(cliente, livro["id"], c1, "Jon", posicao_no_texto=INICIO_DO_TERCEIRO)

    (artefato,) = _artefatos(cliente, c1)

    assert (artefato["tipo"], artefato["tipo_do_elemento"], artefato["rotulo"]) == ("ELEMENTO", "PERSONAGEM", "Jon")
    assert (artefato["frame_id"], artefato["sugestao_id"]) == (retrato["id"], None)
    assert artefato["posicao_no_texto"] == INICIO_DO_TERCEIRO


def teste_frame_representado_por_sugestao_nao_aparece_duas_vezes(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    livro, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        cenas=[CenaSugerida(titulo="A espada", participantes=[NED], trecho_ancora="O vento soprou")],
        elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
    )
    sugestoes = cliente.get(f"/capitulos/{c1}/sugestoes").json()
    cliente.post(f"/capitulos/{c1}/frames", json={"sugestao_cena_id": sugestoes["cenas"][0]["id"]})
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "estado_inicial": {"capitulo_id": c1, "descricao": "manto"}},
    ).json()
    cliente.patch(f"/sugestoes-elemento/{sugestoes['elementos'][0]['id']}", json={"elemento_id": jon["id"]})
    cliente.post(
        f"/capitulos/{c1}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [jon["estados"][0]["id"]]}
    )

    artefatos = _artefatos(cliente, c1)

    assert sorted((a["tipo"], a["rotulo"]) for a in artefatos) == [("CENA", "A espada"), ("ELEMENTO", "Jon")]


def teste_so_o_retrato_mais_novo_de_cada_elemento_vira_artefato(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """Dois retratos do mesmo elemento no capítulo: o mapa de retratos já guarda o mais novo."""
    livro, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "estado_inicial": {"capitulo_id": c1, "descricao": "manto"}},
    ).json()
    estado = jon["estados"][0]["id"]
    cliente.post(f"/capitulos/{c1}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [estado]})
    segundo = cliente.post(f"/capitulos/{c1}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [estado]}).json()

    (artefato,) = _artefatos(cliente, c1)

    assert artefato["frame_id"] == segundo["id"]
