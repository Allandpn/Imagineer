"""Dicionários StarDict (RL19): leitura do formato, busca binária, idiomas e a rota."""

import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from imagineer.principal import aplicacao
from imagineer.rotas.dicionario import obter_dicionarios
from imagineer.servicos import dicionarios as servico


def _escrever_stardict(
    pasta: Path,
    nome_do_arquivo: str,
    nome: str,
    verbetes: list[tuple[str, str]],
    sinonimos: list[tuple[str, str]] | None = None,
    codificacao: str = "utf-8",
    ordenar: bool = True,
) -> None:
    """Monta um dicionário StarDict de verdade (ifo, idx, dict e, se houver, syn) para os testes lerem."""
    base = pasta / nome_do_arquivo
    if ordenar:
        verbetes = sorted(verbetes, key=lambda v: v[0].encode("utf-8").lower())
    idx = bytearray()
    dicionario = bytearray()
    numero_da_entrada: dict[str, int] = {}
    for k, (palavra, definicao) in enumerate(verbetes):
        dados = definicao.encode(codificacao)
        idx += palavra.encode("utf-8") + b"\0" + struct.pack(">II", len(dicionario), len(dados))
        dicionario += dados
        numero_da_entrada.setdefault(palavra, k)
    base.with_suffix(".idx").write_bytes(bytes(idx))
    base.with_suffix(".dict").write_bytes(bytes(dicionario))
    if sinonimos:
        sinonimos = sorted(sinonimos, key=lambda s: s[0].encode("utf-8").lower())
        syn = bytearray()
        for forma, palavra in sinonimos:
            syn += forma.encode("utf-8") + b"\0" + struct.pack(">I", numero_da_entrada[palavra])
        base.with_suffix(".syn").write_bytes(bytes(syn))
    base.with_suffix(".ifo").write_text(
        f"StarDict's dict ifo file\nversion=2.4.2\nwordcount={len(verbetes)}\nbookname={nome}\nsametypesequence=h\n", encoding="utf-8"
    )


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    _escrever_stardict(
        tmp_path,
        "pt",
        "Michaelis Moderno Dicionário da Língua Portuguesa",
        [
            ("abrir", "<font color=blue>v.</font> <I>vt</I><B> 1</B> Descobrir o que estava fechado.<B> 2</B> Começar."),
            ("casa", "<B>1</B> Moradia.<BR>Residência &amp; lar."),
            ("Casa", "Sobrenome."),
            ("ação", "Ato de agir."),
        ],
        sinonimos=[("abriu", "abrir"), ("abriram", "abrir")],
    )
    _escrever_stardict(
        tmp_path,
        "en",
        "Babylon English-Portuguese",
        [("house", "n. casa; teatro"), ("run", "v. correr"), ("stop", "v. parar"), ("box", "n. caixa")],
    )
    _escrever_stardict(tmp_path, "ptingles", "Babylon Portuguese-English", [("casa", "house")])
    _escrever_stardict(tmp_path, "latin", "Michaelis Dicionário Espanhol-Português", [("cañón", "canhão — é a ação")], codificacao="cp1252")
    return tmp_path


@pytest.fixture
def todos(pasta: Path) -> list[servico.Dicionario]:
    return servico.descobrir_dicionarios(pasta)


def _textos(resultados) -> list[str]:
    return [r.verbete.texto for r in resultados]


# --------------------------------------------------------------------------- #
# Descobrir e ler
# --------------------------------------------------------------------------- #


def teste_descobre_os_dicionarios_da_pasta_com_idioma_e_uso_padrao(todos) -> None:
    por_nome = {d.nome: d for d in todos}

    assert por_nome["Michaelis Moderno Dicionário da Língua Portuguesa"].padrao_para == ["pt"]
    assert por_nome["Babylon English-Portuguese"].padrao_para == ["en"]
    assert por_nome["Babylon English-Portuguese"].idioma_das_entradas == "en"
    assert por_nome["Babylon Portuguese-English"].padrao_para == []  # só em "todos"
    assert por_nome["Michaelis Dicionário Espanhol-Português"].padrao_para == ["es"]
    assert por_nome["Babylon English-Portuguese"].palavras == 4


def teste_pasta_ausente_ou_vazia_nao_e_erro(tmp_path: Path) -> None:
    assert servico.descobrir_dicionarios(tmp_path / "nao-existe") == []
    assert servico.descobrir_dicionarios(tmp_path) == []


def teste_dicionario_sem_o_dict_e_ignorado(tmp_path: Path) -> None:
    _escrever_stardict(tmp_path, "x", "X", [("a", "b")])
    (tmp_path / "x.dict").unlink()

    assert servico.descobrir_dicionarios(tmp_path) == []


def teste_acha_a_palavra_e_converte_o_html_em_texto(todos) -> None:
    _, achados = servico.consultar(todos, "casa", "pt")

    textos = _textos(achados)
    assert "1 Moradia.\nResidência & lar." in textos
    assert all("<" not in t for t in textos)


def teste_numero_dos_sentidos_ganha_linha_propria() -> None:
    assert servico.texto_simples("<I>vt</I><B> 1</B> um.<B> 2</B> dois.") == "vt\n1 um.\n2 dois."


def teste_forma_alternativa_do_syn_leva_ao_verbete_da_palavra(todos) -> None:
    _, achados = servico.consultar(todos, "abriu", "pt")

    assert len(achados) == 1
    assert achados[0].verbete.entrada == "abrir"
    assert "Descobrir" in achados[0].verbete.texto


def teste_maiusculas_e_minusculas_dao_o_mesmo_e_traz_as_duas_entradas(todos) -> None:
    _, achados = servico.consultar(todos, "CASA", "pt")

    assert sorted(a.verbete.entrada for a in achados) == ["Casa", "casa"]


def teste_palavra_com_acento_e_codificacao_latin1_nos_verbetes(todos) -> None:
    _, achados = servico.consultar(todos, "cañón", "es")

    assert _textos(achados) == ["canhão — é a ação"]  # o verbete estava em Windows-1252
    _, achados = servico.consultar(todos, "ação", "pt")
    assert _textos(achados) == ["Ato de agir."]


def teste_palavra_que_nao_existe_devolve_vazio(todos) -> None:
    assert servico.consultar(todos, "xyzzy", "pt")[1] == []


# --------------------------------------------------------------------------- #
# Idiomas e "todos"
# --------------------------------------------------------------------------- #


def teste_livro_em_portugues_so_consulta_os_de_portugues(todos) -> None:
    _, achados = servico.consultar(todos, "casa", "pt-BR")

    assert {a.dicionario.nome for a in achados} == {"Michaelis Moderno Dicionário da Língua Portuguesa"}


def teste_livro_em_ingles_consulta_os_de_ingles_e_nao_os_de_portugues(todos) -> None:
    _, achados = servico.consultar(todos, "house", "en-US")

    assert {a.dicionario.nome for a in achados} == {"Babylon English-Portuguese"}
    assert servico.consultar(todos, "casa", "en")[1] == []


def teste_todos_consulta_todos_ignorando_o_idioma(todos) -> None:
    _, achados = servico.consultar(todos, "casa", "en", todos=True)

    assert {a.dicionario.nome for a in achados} == {
        "Michaelis Moderno Dicionário da Língua Portuguesa",
        "Babylon Portuguese-English",
    }


def teste_sem_idioma_conhecido_vale_os_de_uso_padrao(todos) -> None:
    _, achados = servico.consultar(todos, "house", None)

    assert [a.dicionario.nome for a in achados] == ["Babylon English-Portuguese"]


def teste_idioma_do_livro_reduzido_a_duas_letras() -> None:
    assert servico.idioma_do_livro("pt-BR") == "pt"
    assert servico.idioma_do_livro("en_US") == "en"
    assert servico.idioma_do_livro("por") == "pt"
    assert servico.idioma_do_livro("eng") == "en"
    assert servico.idioma_do_livro(None) is None
    assert servico.idioma_do_livro("  ") is None


# --------------------------------------------------------------------------- #
# A palavra
# --------------------------------------------------------------------------- #


def teste_limpa_a_pontuacao_das_pontas_e_junta_espacos() -> None:
    assert servico.limpar_palavra("«casa»,") == "casa"
    assert servico.limpar_palavra("  “Winter  fell…” ") == "Winter fell"
    assert servico.limpar_palavra("...") == ""
    assert len(servico.limpar_palavra("a" * 500)) == servico.LIMITE_DA_PALAVRA


def teste_em_ingles_tenta_as_formas_simples_quando_nada_e_achado(todos) -> None:
    for flexionada in ("houses", "boxes", "stopped", "running", "House's"):
        palavra = {"houses": "house", "boxes": "box", "stopped": "stop", "running": "run", "House's": "house"}[flexionada]
        _, achados = servico.consultar(todos, flexionada, "en")
        assert [a.verbete.entrada for a in achados] == [palavra], flexionada


def teste_formas_base_em_ingles() -> None:
    assert "stop" in servico.formas_base_em_ingles("stopped")
    assert "run" in servico.formas_base_em_ingles("running")
    assert "city" in servico.formas_base_em_ingles("cities")
    assert "house" in servico.formas_base_em_ingles("house's")
    assert servico.formas_base_em_ingles("is") == []  # curta demais para mexer


# --------------------------------------------------------------------------- #
# Índice fora de ordem e limites
# --------------------------------------------------------------------------- #


def teste_indice_fora_de_ordem_e_recusado_em_vez_de_responder_errado(tmp_path: Path, caplog) -> None:
    _escrever_stardict(tmp_path, "d", "Michaelis Moderno Dicionário da Língua Portuguesa", [("b", "x"), ("a", "y")], ordenar=False)
    dicionarios = servico.descobrir_dicionarios(tmp_path)

    with caplog.at_level("WARNING"):
        achados = servico.consultar(dicionarios, "a", "pt")[1]

    assert achados == []
    assert "ignorado" in caplog.text


def teste_verbete_muito_grande_e_cortado() -> None:
    texto = servico.texto_simples("x" * (servico.LIMITE_DO_TEXTO + 500))

    assert len(texto) == servico.LIMITE_DO_TEXTO + 1 and texto.endswith("…")


def teste_no_maximo_tres_verbetes_por_dicionario(tmp_path: Path) -> None:
    _escrever_stardict(
        tmp_path, "m", "Michaelis Moderno Dicionário da Língua Portuguesa", [("a", f"def{n}") for n in range(6)]
    )

    _, achados = servico.consultar(servico.descobrir_dicionarios(tmp_path), "a", "pt")

    assert len(achados) == servico.LIMITE_DE_VERBETES_POR_DICIONARIO


def teste_o_syn_nao_traz_o_mesmo_verbete_duas_vezes(tmp_path: Path) -> None:
    _escrever_stardict(
        tmp_path, "m", "Michaelis Moderno Dicionário da Língua Portuguesa", [("casa", "moradia")], sinonimos=[("casa", "casa")]
    )

    _, achados = servico.consultar(servico.descobrir_dicionarios(tmp_path), "casa", "pt")

    assert len(achados) == 1


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #


@pytest.fixture
def cliente_com_dicionarios(cliente: TestClient, todos):
    aplicacao.dependency_overrides[obter_dicionarios] = lambda: todos
    yield cliente
    aplicacao.dependency_overrides.pop(obter_dicionarios, None)


def teste_rota_lista_os_dicionarios(cliente_com_dicionarios: TestClient) -> None:
    corpo = cliente_com_dicionarios.get("/dicionario/dicionarios").json()

    assert {d["nome"] for d in corpo} >= {"Babylon English-Portuguese", "Babylon Portuguese-English"}
    assert all({"id", "nome", "idioma_das_entradas", "palavras", "padrao_para"} <= set(d) for d in corpo)


def teste_rota_procura_a_palavra(cliente_com_dicionarios: TestClient) -> None:
    corpo = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "«Abriu»,", "idioma": "pt-BR"}).json()

    assert corpo["palavra"] == "Abriu"
    assert [r["entrada"] for r in corpo["resultados"]] == ["abrir"]
    assert corpo["resultados"][0]["dicionario"].startswith("Michaelis")


def teste_rota_com_todos_traz_mais_dicionarios(cliente_com_dicionarios: TestClient) -> None:
    sem = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "casa", "idioma": "pt"}).json()
    com = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "casa", "idioma": "pt", "todos": True}).json()

    assert len(com["resultados"]) > len(sem["resultados"])


def teste_rota_sem_resultado_devolve_lista_vazia_e_nao_erro(cliente_com_dicionarios: TestClient) -> None:
    resposta = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "xyzzy", "idioma": "pt"})

    assert resposta.status_code == 200
    assert resposta.json() == {"palavra": "xyzzy", "resultados": []}


def teste_rota_sem_pasta_de_dicionarios_devolve_vazio(cliente: TestClient, tmp_path: Path) -> None:
    aplicacao.dependency_overrides[obter_dicionarios] = lambda: servico.descobrir_dicionarios(tmp_path / "nada")
    try:
        assert cliente.get("/dicionario/dicionarios").json() == []
        assert cliente.get("/dicionario/verbete", params={"palavra": "casa"}).json()["resultados"] == []
    finally:
        aplicacao.dependency_overrides.pop(obter_dicionarios, None)


def teste_rota_exige_a_palavra(cliente: TestClient) -> None:
    assert cliente.get("/dicionario/verbete").status_code == 422
    assert cliente.get("/dicionario/verbete", params={"palavra": ""}).status_code == 422
