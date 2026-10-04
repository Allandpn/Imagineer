"""Preferências dos dicionários (RL28 a RL30) e configuração da narração por IA (RL21 a RL27)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from imagineer.principal import aplicacao
from imagineer.rotas.dicionario import obter_dicionarios, ordenar_por_preferencia
from imagineer.servicos import dicionarios as servico
from testes.teste_dicionarios import pasta, todos  # noqa: F401  (as fixtures da pasta de dicionários de teste)


@pytest.fixture
def cliente_com_dicionarios(cliente: TestClient, todos):  # noqa: F811
    aplicacao.dependency_overrides[obter_dicionarios] = lambda: todos
    yield cliente
    aplicacao.dependency_overrides.pop(obter_dicionarios, None)


def _ids(cliente: TestClient) -> list[str]:
    return [d["id"] for d in cliente.get("/dicionario/dicionarios").json()]


# --------------------------------------------------------------------------- #
# A ordem de preferência
# --------------------------------------------------------------------------- #


def teste_ordenar_poe_os_citados_primeiro_e_deixa_o_resto_no_fim_como_estava(todos) -> None:  # noqa: F811
    ids = [d.id for d in todos]
    ultimo = ids[-1]

    ordenados = ordenar_por_preferencia(todos, [ultimo, "que-nao-existe-mais"])

    assert [d.id for d in ordenados] == [ultimo, *ids[:-1]]  # o inexistente é ignorado; o resto mantém a ordem


def teste_sem_preferencia_a_ordem_e_a_de_sempre(cliente_com_dicionarios: TestClient, todos) -> None:  # noqa: F811
    corpo = cliente_com_dicionarios.get("/dicionario/dicionarios").json()

    assert [d["id"] for d in corpo] == [d.id for d in todos]
    assert all(d["ativo"] is True for d in corpo)


def teste_a_ordem_gravada_vale_na_lista(cliente_com_dicionarios: TestClient) -> None:
    ids = _ids(cliente_com_dicionarios)
    nova = list(reversed(ids))

    resposta = cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": nova, "desativados": []})

    assert resposta.status_code == 200
    assert [d["id"] for d in resposta.json()] == nova
    assert _ids(cliente_com_dicionarios) == nova  # ficou gravada


def teste_a_ordem_vale_na_consulta(cliente_com_dicionarios: TestClient) -> None:
    ids = _ids(cliente_com_dicionarios)
    antes = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "casa", "todos": True}).json()["resultados"]
    assert len(antes) >= 2

    cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": list(reversed(ids)), "desativados": []})
    depois = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "casa", "todos": True}).json()["resultados"]

    assert [r["dicionario_id"] for r in depois] != [r["dicionario_id"] for r in antes]
    assert {r["dicionario_id"] for r in depois} == {r["dicionario_id"] for r in antes}  # só mudou a ordem


# --------------------------------------------------------------------------- #
# Ligar e desligar
# --------------------------------------------------------------------------- #


def teste_dicionario_desligado_aparece_como_inativo_e_nunca_e_consultado(cliente_com_dicionarios: TestClient) -> None:
    lista = cliente_com_dicionarios.get("/dicionario/dicionarios").json()
    michaelis = next(d["id"] for d in lista if d["nome"].startswith("Michaelis Moderno"))
    cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": [d["id"] for d in lista], "desativados": [michaelis]})

    depois = cliente_com_dicionarios.get("/dicionario/dicionarios").json()
    com_idioma = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "abrir", "idioma": "pt"}).json()
    com_todos = cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "abrir", "todos": True}).json()

    assert next(d for d in depois if d["id"] == michaelis)["ativo"] is False
    assert com_idioma["resultados"] == []  # era o único de português com "abrir"
    assert michaelis not in {r["dicionario_id"] for r in com_todos["resultados"]}  # nem em "todos"


def teste_ligar_de_novo_devolve_o_dicionario(cliente_com_dicionarios: TestClient) -> None:
    ids = _ids(cliente_com_dicionarios)
    cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": ids, "desativados": ids})
    assert cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "casa", "todos": True}).json()["resultados"] == []

    cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": ids, "desativados": []})

    assert cliente_com_dicionarios.get("/dicionario/verbete", params={"palavra": "casa", "todos": True}).json()["resultados"]


def teste_identificador_desconhecido_e_recusado_e_nada_muda(cliente_com_dicionarios: TestClient) -> None:
    antes = _ids(cliente_com_dicionarios)

    resposta = cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": ["nao-existe"], "desativados": []})
    resposta_dois = cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": [], "desativados": ["tambem-nao"]})

    assert resposta.status_code == 422 and "nao-existe" in resposta.json()["detail"]
    assert resposta_dois.status_code == 422
    assert _ids(cliente_com_dicionarios) == antes


def teste_repeticao_na_lista_e_ignorada(cliente_com_dicionarios: TestClient) -> None:
    ids = _ids(cliente_com_dicionarios)

    corpo = cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": [ids[1], ids[1], ids[0]], "desativados": [ids[0], ids[0]]}).json()

    assert [d["id"] for d in corpo][:2] == [ids[1], ids[0]]
    assert sum(1 for d in corpo if not d["ativo"]) == 1


def teste_corpo_com_campo_a_mais_e_recusado(cliente_com_dicionarios: TestClient) -> None:
    assert cliente_com_dicionarios.put("/dicionario/preferencias", json={"ordem": [], "desativados": [], "x": 1}).status_code == 422


def teste_sem_pasta_a_lista_e_vazia_e_gravar_vazio_funciona(cliente: TestClient, tmp_path: Path) -> None:
    aplicacao.dependency_overrides[obter_dicionarios] = lambda: servico.descobrir_dicionarios(tmp_path / "nada")
    try:
        assert cliente.get("/dicionario/dicionarios").json() == []
        assert cliente.put("/dicionario/preferencias", json={"ordem": [], "desativados": []}).json() == []
    finally:
        aplicacao.dependency_overrides.pop(obter_dicionarios, None)


# --------------------------------------------------------------------------- #
# A configuração da narração
# --------------------------------------------------------------------------- #


def teste_a_narracao_nasce_com_o_aparelho_e_uma_voz(cliente: TestClient) -> None:
    corpo = cliente.get("/configuracao").json()

    assert corpo["narracao_motor"] == "APARELHO"
    assert corpo["narracao_modo"] == "UMA_VOZ"
    assert corpo["narracao_voz"] is None
    assert corpo["narracao_instrucoes"] is None


def teste_grava_e_le_a_configuracao_da_narracao(cliente: TestClient) -> None:
    corpo = cliente.put(
        "/configuracao",
        json={"narracao_motor": "IA", "narracao_modo": "POR_PERSONAGEM", "narracao_voz": "  alloy ", "narracao_instrucoes": "voz grave, com suspense"},
    ).json()

    assert corpo["narracao_motor"] == "IA"
    assert corpo["narracao_modo"] == "POR_PERSONAGEM"
    assert corpo["narracao_voz"] == "alloy"  # sem espaços nas pontas
    assert corpo["narracao_instrucoes"] == "voz grave, com suspense"
    assert cliente.get("/configuracao").json()["narracao_motor"] == "IA"


def teste_limpar_a_voz_e_as_instrucoes_e_so_o_que_veio_muda(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"narracao_motor": "IA", "narracao_voz": "alloy", "narracao_instrucoes": "tom"})

    corpo = cliente.put("/configuracao", json={"narracao_voz": "", "narracao_instrucoes": None}).json()

    assert corpo["narracao_voz"] is None and corpo["narracao_instrucoes"] is None
    assert corpo["narracao_motor"] == "IA"  # não veio, não mudou


def teste_motor_ou_modo_desconhecido_e_recusado(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"narracao_motor": "ROBO"}).status_code == 422
    assert cliente.put("/configuracao", json={"narracao_modo": "TODOS"}).status_code == 422


def teste_instrucoes_longas_demais_sao_recusadas(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"narracao_instrucoes": "x" * 2001}).status_code == 422


def teste_a_migracao_encadeia_depois_dos_perfis_de_fabrica() -> None:
    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "e5f6a7b8c9d0_dicionarios_e_narracao_na_configuracao.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'" in texto
    for coluna in ("ordem_dos_dicionarios", "dicionarios_desativados", "narracao_motor", "narracao_modo", "narracao_voz", "narracao_instrucoes"):
        assert f'"{coluna}"' in texto
