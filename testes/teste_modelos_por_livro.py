"""Os modelos de IA por livro (item 7.5g, MV1 a MV3): a coluna, a visão da configuração, as rotas e o efeito na narração.

Nenhum teste fala com o OpenRouter: o provedor é o ``ProvedorFalso``.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from imagineer.modelos import Livro
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.modelos_do_livro import CAMPOS_DE_MODELO_DO_LIVRO, configuracao_do_livro, origem_do_campo, trocas_do_livro
from testes.teste_narracao_por_ia import MODELO, VOZ, _capitulo, _escolher, narrar_com  # noqa: F401  (a fixture e os auxiliares)
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)

RAIZ = Path(__file__).resolve().parent.parent


def _livro_id(cliente: TestClient, sessao) -> int:
    capitulo_id = _capitulo(cliente, sessao, "Um texto curto.")
    return cliente.get(f"/capitulos/{capitulo_id}").json()["livro_id"]


# --------------------------------------------------------------------------- #
# MV1/MV2: a visão da configuração
# --------------------------------------------------------------------------- #


def teste_sem_trocas_vale_a_propria_configuracao_global(cliente: TestClient, sessao_com_tabelas) -> None:
    livro = sessao_com_tabelas.get(Livro, _livro_id(cliente, sessao_com_tabelas))

    assert trocas_do_livro(livro) == {}
    assert configuracao_do_livro(sessao_com_tabelas, livro) is obter_ou_criar(sessao_com_tabelas)


def teste_o_campo_trocado_vale_o_do_livro_e_o_resto_o_global(cliente: TestClient, sessao_com_tabelas) -> None:
    _escolher(cliente, MODELO, VOZ)
    livro = sessao_com_tabelas.get(Livro, _livro_id(cliente, sessao_com_tabelas))
    livro.modelos = {"modelo_narracao": "outro/modelo", "campo_que_nao_existe": "x", "modelo_imagem": "   "}
    sessao_com_tabelas.commit()

    visao = configuracao_do_livro(sessao_com_tabelas, livro)

    assert visao.modelo_narracao == "outro/modelo"
    assert visao.narracao_voz == VOZ  # não trocada: vale a global
    assert trocas_do_livro(livro) == {"modelo_narracao": "outro/modelo"}  # chave desconhecida e valor vazio não contam
    assert origem_do_campo(livro, "modelo_narracao") == "livro" and origem_do_campo(livro, "narracao_voz") == "global"


def teste_a_visao_e_so_de_leitura(cliente: TestClient, sessao_com_tabelas) -> None:
    livro = sessao_com_tabelas.get(Livro, _livro_id(cliente, sessao_com_tabelas))
    livro.modelos = {"modelo_narracao": "outro/modelo"}
    sessao_com_tabelas.commit()

    with pytest.raises(AttributeError):
        configuracao_do_livro(sessao_com_tabelas, livro).modelo_narracao = "x"


# --------------------------------------------------------------------------- #
# MV3: as rotas
# --------------------------------------------------------------------------- #


def teste_sem_trocas_tudo_vale_o_global(cliente: TestClient, sessao_com_tabelas) -> None:
    _escolher(cliente, MODELO, VOZ)
    livro_id = _livro_id(cliente, sessao_com_tabelas)

    corpo = cliente.get(f"/livros/{livro_id}/modelos").json()

    assert corpo["trocas"] == {}
    assert set(corpo["valendo"]) == set(CAMPOS_DE_MODELO_DO_LIVRO)
    assert corpo["valendo"]["modelo_narracao"] == {"modelo": MODELO, "origem": "global"}
    assert corpo["valendo"]["modelo_imagem"] == {"modelo": cliente.get("/configuracao").json()["modelo_imagem"], "origem": "global"}


def teste_trocar_mostra_o_do_livro_e_nao_mexe_no_global(cliente: TestClient, sessao_com_tabelas) -> None:
    _escolher(cliente, MODELO, VOZ)
    livro_id = _livro_id(cliente, sessao_com_tabelas)

    resposta = cliente.put(f"/livros/{livro_id}/modelos", json={"modelo_narracao": "outro/modelo", "modelo_imagem": " img/x "})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["trocas"] == {"modelo_narracao": "outro/modelo", "modelo_imagem": "img/x"}
    assert corpo["valendo"]["modelo_narracao"] == {"modelo": "outro/modelo", "origem": "livro"}
    assert corpo["valendo"]["narracao_voz"] == {"modelo": VOZ, "origem": "global"}
    assert cliente.get("/configuracao").json()["modelo_narracao"] == MODELO
    assert cliente.get(f"/livros/{livro_id}/modelos").json() == corpo


def teste_o_put_substitui_tudo_e_vazio_ou_null_tira_a_troca(cliente: TestClient, sessao_com_tabelas) -> None:
    livro_id = _livro_id(cliente, sessao_com_tabelas)
    cliente.put(f"/livros/{livro_id}/modelos", json={"modelo_narracao": "a/b", "modelo_imagem": "c/d"})

    corpo = cliente.put(f"/livros/{livro_id}/modelos", json={"modelo_imagem": "e/f", "modelo_narracao": None, "modelo_prompt": ""}).json()

    assert corpo["trocas"] == {"modelo_imagem": "e/f"}


def teste_sem_nenhuma_troca_a_coluna_volta_a_ser_nula(cliente: TestClient, sessao_com_tabelas) -> None:
    livro_id = _livro_id(cliente, sessao_com_tabelas)
    cliente.put(f"/livros/{livro_id}/modelos", json={"modelo_narracao": "a/b"})

    cliente.put(f"/livros/{livro_id}/modelos", json={})

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Livro, livro_id).modelos is None


def teste_campo_desconhecido_e_recusado_e_livro_inexistente_e_404(cliente: TestClient, sessao_com_tabelas) -> None:
    livro_id = _livro_id(cliente, sessao_com_tabelas)

    assert cliente.put(f"/livros/{livro_id}/modelos", json={"titulo": "x"}).status_code == 422
    assert cliente.get("/livros/99999/modelos").status_code == 404
    assert cliente.put("/livros/99999/modelos", json={}).status_code == 404


def teste_trocar_o_modelo_nao_sobe_a_revisao_do_livro(cliente: TestClient, sessao_com_tabelas) -> None:
    livro_id = _livro_id(cliente, sessao_com_tabelas)
    antes = sessao_com_tabelas.get(Livro, livro_id).revisao

    cliente.put(f"/livros/{livro_id}/modelos", json={"modelo_narracao": "a/b"})

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Livro, livro_id).revisao == antes


# --------------------------------------------------------------------------- #
# MV2: o efeito de verdade
# --------------------------------------------------------------------------- #


def teste_a_narracao_usa_o_modelo_e_a_voz_do_livro_quando_trocados(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    _escolher(cliente, MODELO, VOZ)
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    livro_id = cliente.get(f"/capitulos/{capitulo_id}").json()["livro_id"]
    cliente.put(f"/livros/{livro_id}/modelos", json={"modelo_narracao": "fish-audio/s2.1-pro-free:free", "narracao_voz": "voz-do-livro"})

    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code in (200, 202)

    assert provedor.chamadas_de_narracao[-1][1:] == ("fish-audio/s2.1-pro-free:free", "voz-do-livro")


def teste_sem_troca_a_narracao_continua_usando_a_global(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    _escolher(cliente, MODELO, VOZ)
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")

    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code in (200, 202)

    assert provedor.chamadas_de_narracao[-1][1:] == (MODELO, VOZ)


# --------------------------------------------------------------------------- #
# MV1: a migração
# --------------------------------------------------------------------------- #


def teste_a_migracao_vem_depois_da_dos_pins_e_e_a_unica_cabeca() -> None:
    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)

    assert diretorio.get_revision("e2f3a4b5c6d8").down_revision == "d1e2f3a4b5c7"
    assert diretorio.get_heads() == ["e2f3a4b5c6d8"]
