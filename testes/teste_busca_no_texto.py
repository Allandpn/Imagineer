"""A pesquisa no texto (item 7.5b, LV5): o serviço de busca e `GET /busca`."""

import unicodedata

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro
from imagineer.servicos.busca_no_texto import normalizar_termo, procurar


# --------------------------------------------------------------------------- #
# O serviço
# --------------------------------------------------------------------------- #


def teste_busca_sem_acento_e_sem_diferenca_de_maiusculas() -> None:
    achados = procurar("Ele viu o Dragão e o dragao fugiu.", "DRAGÃO")

    assert [a.posicao_no_texto for a in achados] == [10, 21]


def teste_busca_trata_aspas_e_quebra_de_linha_como_o_leitor_digita() -> None:
    achados = procurar("Ele disse “vamos embora”\ne saiu.", '"vamos embora"')
    assert len(achados) == 1

    assert len(procurar("a noite\nfria", "noite fria")) == 1


def teste_posicao_e_o_inicio_do_paragrafo_e_o_trecho_marca_o_achado() -> None:
    texto = "Primeiro paragrafo.\n\nO lobo gigante uivou na neve."

    (achado,) = procurar(texto, "lobo")

    assert achado.posicao_no_texto == texto.index("lobo")
    assert achado.inicio_do_paragrafo == texto.index("O lobo")
    assert achado.trecho[achado.inicio_no_trecho : achado.fim_no_trecho] == "lobo"
    assert "\n" not in achado.trecho


def teste_a_posicao_volta_ao_original_quando_o_texto_esta_decomposto() -> None:
    # "é" decomposto (e + acento solto) muda o tamanho do texto normalizado: sem o mapa, a posição sairia errada.
    texto = unicodedata.normalize("NFD", "Está aí o café quente.\n\nO café esfriou.")

    achados = procurar(texto, "cafe")

    assert [texto[a.posicao_no_texto : a.posicao_no_texto + 5] for a in achados] == ["café", "café"]


def teste_a_posicao_conta_em_utf16_depois_de_um_emoji() -> None:
    texto = "Ola \U0001F600 mundo"  # o emoji ocupa 2 unidades UTF-16

    (achado,) = procurar(texto, "mundo")

    assert achado.posicao_no_texto == 7  # e não 6


def teste_termo_vazio_ou_ausente_nao_acha_nada() -> None:
    assert procurar("qualquer texto", "   ") == []
    assert procurar("qualquer texto", "zzz") == []
    assert normalizar_termo("  Dragão   Vermelho ") == "dragao vermelho"


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #


def _livro(sessao: Session, titulo: str, textos: list[str], ignorados: tuple[int, ...] = ()) -> Livro:
    livro = Livro(titulo=titulo, nome_arquivo=f"{titulo}.epub", identificador_epub=titulo)
    sessao.add(livro)
    sessao.flush()
    for ordem, texto in enumerate(textos, start=1):
        sessao.add(Capitulo(livro_id=livro.id, ordem=ordem, titulo=f"Cap {ordem}", texto=texto, ignorado=ordem in ignorados))
    sessao.commit()
    return livro


def teste_busca_na_biblioteca_no_livro_e_no_capitulo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    a = _livro(sessao_com_tabelas, "A Guerra", ["O lobo uivou.", "Nada aqui.", "Outro lobo, e mais um lobo."])
    b = _livro(sessao_com_tabelas, "B Inverno", ["O lobo branco."])
    terceiro_do_a = max(c.id for c in a.capitulos)

    biblioteca = cliente.get("/busca", params={"q": "lobo"}).json()
    assert biblioteca["total"] == 4
    assert [o["livro_titulo"] for o in biblioteca["ocorrencias"]] == ["A Guerra"] * 3 + ["B Inverno"]

    no_livro = cliente.get("/busca", params={"q": "lobo", "livro_id": a.id}).json()
    assert no_livro["total"] == 3
    assert {o["livro_id"] for o in no_livro["ocorrencias"]} == {a.id}

    no_capitulo = cliente.get("/busca", params={"q": "lobo", "capitulo_id": terceiro_do_a}).json()
    assert no_capitulo["total"] == 2
    assert [o["capitulo_ordem"] for o in no_capitulo["ocorrencias"]] == [3, 3]
    assert b.id not in {o["livro_id"] for o in no_capitulo["ocorrencias"]}


def teste_capitulo_arquivado_fica_de_fora(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro(sessao_com_tabelas, "A Guerra", ["O lobo uivou.", "Outro lobo."], ignorados=(2,))

    resposta = cliente.get("/busca", params={"q": "lobo", "livro_id": livro.id}).json()

    assert resposta["total"] == 1


def teste_limite_corta_a_lista_mas_o_total_conta_tudo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    _livro(sessao_com_tabelas, "A Guerra", ["lobo " * 10])

    resposta = cliente.get("/busca", params={"q": "lobo", "limite": 3}).json()

    assert (resposta["total"], len(resposta["ocorrencias"]), resposta["truncado"]) == (10, 3, True)


def teste_busca_recusa_termo_curto_e_escopo_que_nao_existe(cliente: TestClient) -> None:
    assert cliente.get("/busca", params={"q": "a"}).status_code == 422
    assert cliente.get("/busca", params={"q": "lobo", "livro_id": 999}).status_code == 404
    assert cliente.get("/busca", params={"q": "lobo", "capitulo_id": 999}).status_code == 404
