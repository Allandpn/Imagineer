"""O modelo de leitura e o modelo reserva (item 4.10, LM12 e LM13; etapa E5).

``modelo_leitura`` lê o capítulo para descrever cada elemento e cada cena; ``modelo_extracao`` fica só com a identificação dos elementos.
``modelo_reserva`` é o modelo a que o OpenRouter recorre quando o principal falha. Ambos são **por pessoa** (a configuração é de cada usuário).
"""

import json

import httpx
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import catalogo_de_texto
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.modelos import Configuracao, Usuario
from imagineer.servicos.acesso import definir_usuario
from imagineer.servicos.configuracao_ia import ler_modelo_reserva, modelo_de_leitura, obter_ou_criar

from testes.teste_rotas_prompts import _montar_frame_completo
from testes.teste_rotas_sugestoes import _livro_importado

OUTRO_MODELO = "outro/modelo-de-leitura"


# --------------------------------------------------------------------------- #
# A configuração
# --------------------------------------------------------------------------- #


def teste_lm12_a_configuracao_nasce_sem_modelo_de_leitura_nem_reserva(cliente: TestClient) -> None:
    corpo = cliente.get("/configuracao").json()

    assert corpo["modelo_leitura"] is None
    assert corpo["modelo_reserva"] is None


def teste_lm12_o_put_grava_e_o_get_devolve_os_dois_campos(cliente: TestClient) -> None:
    resposta = cliente.put("/configuracao", json={"modelo_leitura": "google/gemini-2.5-flash-lite", "modelo_reserva": "openai/gpt-4o-mini"})

    assert resposta.status_code == 200
    assert resposta.json()["modelo_leitura"] == "google/gemini-2.5-flash-lite"
    assert cliente.get("/configuracao").json()["modelo_reserva"] == "openai/gpt-4o-mini"


def teste_lm12_vazio_e_so_espacos_viram_nulo(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelo_leitura": "a/b", "modelo_reserva": "c/d"})

    cliente.put("/configuracao", json={"modelo_leitura": "", "modelo_reserva": "   "})

    corpo = cliente.get("/configuracao").json()
    assert corpo["modelo_leitura"] is None and corpo["modelo_reserva"] is None


def teste_lm12_os_espacos_das_pontas_saem(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelo_leitura": "  a/b  "})

    assert cliente.get("/configuracao").json()["modelo_leitura"] == "a/b"


def teste_lm12_mexer_em_outro_campo_nao_apaga_os_dois(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelo_leitura": "a/b", "modelo_reserva": "c/d"})

    cliente.put("/configuracao", json={"modelo_prompt": "e/f"})

    corpo = cliente.get("/configuracao").json()
    assert (corpo["modelo_leitura"], corpo["modelo_reserva"]) == ("a/b", "c/d")


def teste_lm12_a_configuracao_e_de_cada_pessoa(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    cliente.put("/configuracao", json={"modelo_leitura": "a/b", "modelo_reserva": "c/d"})
    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    dono_id = sessao_com_tabelas.info["usuario_id"]

    definir_usuario(sessao_com_tabelas, maria.id)
    da_maria = obter_ou_criar(sessao_com_tabelas)

    assert (da_maria.modelo_leitura, da_maria.modelo_reserva) == (None, None)
    definir_usuario(sessao_com_tabelas, dono_id)
    assert obter_ou_criar(sessao_com_tabelas).modelo_leitura == "a/b"


def teste_lm12_campo_grande_demais_e_recusado(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"modelo_leitura": "x" * 201}).status_code == 422
    assert cliente.put("/configuracao", json={"modelo_reserva": "x" * 201}).status_code == 422


# --------------------------------------------------------------------------- #
# A cadeia: leitura -> extração -> prompt
# --------------------------------------------------------------------------- #


def _configuracao(**campos) -> Configuracao:
    return Configuracao(id=1, **campos)


def teste_lm12_a_cadeia_comeca_pela_leitura() -> None:
    assert modelo_de_leitura(_configuracao(modelo_leitura="L", modelo_extracao="E", modelo_prompt="P")) == "L"


def teste_lm12_sem_leitura_vale_a_extracao() -> None:
    assert modelo_de_leitura(_configuracao(modelo_extracao="E", modelo_prompt="P")) == "E"


def teste_lm12_sem_leitura_nem_extracao_vale_o_prompt() -> None:
    assert modelo_de_leitura(_configuracao(modelo_prompt="P")) == "P"


def teste_lm12_sem_nenhum_nao_ha_modelo() -> None:
    assert modelo_de_leitura(_configuracao()) is None


def _modelos_usados_na_leitura(provedor: ProvedorFalso) -> dict[str, list[str]]:
    return {
        "estado": [c["modelo"] for c in provedor.chamadas_de_estado],
        "identidade": [c["modelo"] for c in provedor.chamadas_de_identidade],
        "fundamentacao": [c["modelo"] for c in provedor.chamadas_de_fundamentacao],
    }


def teste_lm12_as_tres_leituras_do_frame_usam_o_modelo_de_leitura(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")
    cliente.put("/configuracao", json={"modelo_leitura": OUTRO_MODELO})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    assert _modelos_usados_na_leitura(provedor) == {
        "estado": [OUTRO_MODELO],
        "identidade": [OUTRO_MODELO],
        "fundamentacao": [OUTRO_MODELO],
    }
    # O prompt em si continua com o modelo de prompt: só a leitura mudou de modelo.
    assert provedor.chamadas_de_prompt[0]["modelo"] == MODELO_FALSO


def teste_lm12_sem_modelo_de_leitura_a_leitura_continua_com_o_de_extracao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert set(_modelos_usados_na_leitura(provedor)["estado"]) == {MODELO_FALSO}  # o de extração, como antes da E5


def teste_lm12_so_com_modelo_de_prompt_a_leitura_cai_nele(cliente: TestClient, usar_provedor_falso) -> None:
    """Antes da E5 isto dava 422; pela cadeia, a leitura usa o modelo de prompt na falta dos outros."""
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")
    cliente.put("/configuracao", json={"modelo_extracao": "", "modelo_prompt": "so/prompt"})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    assert _modelos_usados_na_leitura(provedor)["estado"] == ["so/prompt"]


def teste_lm12_a_extracao_de_elementos_continua_exigindo_o_modelo_de_extracao(cliente: TestClient, usar_provedor_falso) -> None:
    """O de leitura não serve à identificação dos elementos: ``modelo_extracao`` continua só para isso."""
    provedor = usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    cliente.put("/configuracao", json={"modelo_leitura": OUTRO_MODELO, "modelo_prompt": MODELO_FALSO})

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 422
    assert "extração" in resposta.json()["detail"]
    assert provedor.chamadas_de_extracao == []


# --------------------------------------------------------------------------- #
# O modelo reserva
# --------------------------------------------------------------------------- #


def _provedor(corpos: list[dict], modelo_reserva: str | None) -> ProvedorOpenRouter:
    def responder(pedido: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "a red door"}, "finish_reason": "stop"}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave", cliente=cliente, dormir=lambda _: None, modelo_reserva=modelo_reserva)


def _com_catalogo(monkeypatch) -> None:
    modelo = {"id": "x/modelo", "context_length": 1000, "pricing": {"prompt": "1"}, "supported_parameters": []}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [modelo]})


def teste_lm13_o_reserva_vai_como_alternativa_em_qualquer_chamada_de_texto(monkeypatch) -> None:
    _com_catalogo(monkeypatch)
    corpos: list[dict] = []
    provedor = _provedor(corpos, "reserva/modelo")

    provedor.traduzir_prompt("uma porta", "en", "x/modelo")
    provedor.corrigir_prompt("a red door", "tire a porta", "x/modelo")

    assert [c["models"] for c in corpos] == [["x/modelo", "reserva/modelo"]] * 2


def teste_lm13_reserva_igual_ao_principal_nao_vai(monkeypatch) -> None:
    _com_catalogo(monkeypatch)
    corpos: list[dict] = []

    _provedor(corpos, "x/modelo").traduzir_prompt("uma porta", "en", "x/modelo")

    assert "models" not in corpos[0]


def teste_lm13_sem_reserva_nada_muda(monkeypatch) -> None:
    _com_catalogo(monkeypatch)
    corpos: list[dict] = []

    _provedor(corpos, None).traduzir_prompt("uma porta", "en", "x/modelo")

    assert "models" not in corpos[0]


def teste_lm13_o_reserva_se_soma_as_alternativas_explicitas_e_o_corpo_tira_repetidos(monkeypatch) -> None:
    _com_catalogo(monkeypatch)
    corpos: list[dict] = []

    _provedor(corpos, "r/um")._conversar("x/modelo", "i", "p", operacao="prompt", alternativos=["r/um", "r/dois"])

    assert corpos[0]["models"] == ["x/modelo", "r/um", "r/dois"]


def teste_lm13_a_resposta_da_alternativa_e_cobrada_no_nome_dela(monkeypatch) -> None:
    """O OpenRouter devolve em ``model`` quem respondeu; o uso anotado leva esse (LM7)."""
    _com_catalogo(monkeypatch)
    avisos = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"model": "reserva/modelo", "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {"cost": 0.01}}
        )

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    provedor = ProvedorOpenRouter(chave_api="c", cliente=cliente, ao_usar=avisos.append, modelo_reserva="reserva/modelo")

    provedor.traduzir_prompt("uma porta", "en", "x/modelo")

    assert avisos[0].modelo == "reserva/modelo"


def teste_lm13_ler_modelo_reserva_le_sem_criar_a_configuracao(sessao_com_tabelas: Session) -> None:
    dono_id = sessao_com_tabelas.info["usuario_id"]

    assert ler_modelo_reserva(sessao_com_tabelas, dono_id) is None
    assert sessao_com_tabelas.get(Configuracao, dono_id) is None  # só leu: não criou a linha

    sessao_com_tabelas.add(Configuracao(id=dono_id, modelo_reserva="r/um"))
    sessao_com_tabelas.commit()
    assert ler_modelo_reserva(sessao_com_tabelas, dono_id) == "r/um"


def teste_lm13_a_rota_entrega_o_reserva_da_pessoa_ao_construir_o_provedor(cliente: TestClient, monkeypatch) -> None:
    """Pelo ``obter_provedor`` de verdade: o reserva gravado em ``PUT /configuracao`` chega ao ``construir_provedor``."""
    from imagineer.rotas import configuracao as rota

    recebidos: list[str | None] = []

    def falso(cabecalho=None, usuario=None, chave_fal=None, chave_replicate=None, modelo_reserva=None):
        recebidos.append(modelo_reserva)
        return ProvedorFalso()

    monkeypatch.setattr(rota, "construir_provedor", falso)
    cliente.get("/configuracao/modelos")
    cliente.put("/configuracao", json={"modelo_reserva": "r/um"})
    cliente.get("/configuracao/modelos")

    assert recebidos == [None, "r/um"]


# --------------------------------------------------------------------------- #
# A migração
# --------------------------------------------------------------------------- #


def _carregar_migracao():
    import importlib.util

    from testes.teste_lm_migracao_do_uso import RAIZ

    arquivo = RAIZ / "migracoes" / "versions" / "f7a8b9c0d1e3_modelo_de_leitura_e_modelo_reserva.py"
    especificacao = importlib.util.spec_from_file_location("migracao_f7a8b9c0d1e3", arquivo)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def teste_lm12_a_migracao_adiciona_e_remove_as_duas_colunas_sem_mexer_nas_linhas() -> None:
    migracao = _carregar_migracao()
    motor = sa.create_engine("sqlite://")
    with motor.begin() as conexao:
        conexao.execute(sa.text("CREATE TABLE configuracao (id INTEGER PRIMARY KEY, modelo_extracao VARCHAR(200))"))
        conexao.execute(sa.text("INSERT INTO configuracao (id, modelo_extracao) VALUES (1, 'a/b')"))

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.aplicar()
    with motor.connect() as conexao:
        linha = conexao.execute(sa.text("SELECT modelo_extracao, modelo_leitura, modelo_reserva FROM configuracao")).one()
    assert tuple(linha) == ("a/b", None, None)

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.reverter()
    assert {c["name"] for c in sa.inspect(motor).get_columns("configuracao")} == {"id", "modelo_extracao"}


def teste_lm12_a_migracao_vem_depois_da_do_uso_de_ia_e_a_corrente_tem_uma_cabeca() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from testes.teste_lm_migracao_do_uso import RAIZ

    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)

    assert diretorio.get_revision("f7a8b9c0d1e3").down_revision == "e6f7a8b9c0d2"
    assert len(diretorio.get_heads()) == 1


def teste_lm12_o_modelo_tem_as_colunas_nulas() -> None:
    for nome in ("modelo_leitura", "modelo_reserva"):
        assert Configuracao.__table__.columns[nome].nullable is True
