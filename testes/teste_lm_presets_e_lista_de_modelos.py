"""Os níveis Econômico, Equilibrado e Qualidade, a conta do custo e a lista de modelos mais informativa (item 4.10, LM14 e LM16; etapa E6).

Nada vai ao OpenRouter: o catálogo é trocado por um de teste (``catalogo_de_texto._buscar_na_rede``).
"""

from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import catalogo_de_texto
from imagineer.ia.catalogo_de_texto import Capacidades, capacidades_de, e_rapido
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.modelos import Configuracao, Usuario
from imagineer.servicos.acesso import definir_usuario
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.estimativa_de_leitura import (
    LEITURAS_DO_CAPITULO_TIPICO,
    SAIDA_POR_LEITURA_TIPICA,
    TOKENS_DO_CAPITULO_TIPICO,
    custo_das_leituras,
    custo_do_capitulo_tipico,
)
from imagineer.servicos.modelos_recomendados import CAMPO_DA_CONFIGURACAO, RECOMENDACOES, Nivel, Papel


def _capacidades(**mudancas) -> Capacidades:
    base = dict(
        id="x/modelo", contexto=100000, saida_maxima=None, estruturado=False, raciocinio_suportado=False, raciocinio_obrigatorio=False,
        esforcos=(), preco_entrada=Decimal("0.000001"), preco_saida=Decimal("0.000002"), preco_cache_leitura=None, preco_cache_escrita=None,
        gratuito=False, moderado=False,
    )
    base.update(mudancas)
    return Capacidades(**base)


def _entrada(id_: str, prompt: str = "0.000001", completion: str = "0.000002", **extras) -> dict:
    """Uma entrada do ``/models`` do OpenRouter."""
    return {
        "id": id_,
        "name": id_,
        "context_length": 1000000,
        "pricing": {"prompt": prompt, "completion": completion},
        "supported_parameters": ["max_tokens"],
        "reasoning": None,
        "top_provider": {"max_completion_tokens": 64000, "is_moderated": False},
        "architecture": {"output_modalities": ["text"]},
        **extras,
    }


def _catalogo(monkeypatch, *entradas: dict) -> None:
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": list(entradas)})


# --------------------------------------------------------------------------- #
# A tabela de recomendações
# --------------------------------------------------------------------------- #


def teste_lm14_ha_tres_niveis_e_sete_papeis_em_cada_um() -> None:
    assert list(RECOMENDACOES) == [Nivel.ECONOMICO, Nivel.EQUILIBRADO, Nivel.QUALIDADE]
    for por_papel in RECOMENDACOES.values():
        assert set(por_papel) == set(Papel)


def teste_lm14_os_modelos_da_tabela_sao_os_da_especificacao() -> None:
    esperado = {
        Nivel.ECONOMICO: {
            Papel.EXTRACAO: "google/gemini-2.5-flash-lite", Papel.LEITURA: "google/gemini-2.5-flash-lite", Papel.PROMPT: "openai/gpt-4o-mini",
            Papel.TRADUCAO: "google/gemini-2.5-flash-lite", Papel.SUAVIZACAO: "google/gemini-2.5-flash-lite",
            Papel.VIDEO: "google/gemini-3.8-flash", Papel.RESERVA: "openai/gpt-4o-mini",
        },
        Nivel.EQUILIBRADO: {
            Papel.EXTRACAO: "openai/gpt-4.1-mini", Papel.LEITURA: "google/gemini-2.5-flash", Papel.PROMPT: "google/gemini-2.5-flash",
            Papel.TRADUCAO: "google/gemini-2.5-flash-lite", Papel.SUAVIZACAO: "google/gemini-2.5-flash-lite",
            Papel.VIDEO: "google/gemini-3.8-flash", Papel.RESERVA: "google/gemini-2.5-flash-lite",
        },
        Nivel.QUALIDADE: {
            Papel.EXTRACAO: "anthropic/claude-haiku-4.5", Papel.LEITURA: "anthropic/claude-haiku-4.5", Papel.PROMPT: "google/gemini-3.8-flash",
            Papel.TRADUCAO: "google/gemini-2.5-flash", Papel.SUAVIZACAO: "google/gemini-2.5-flash",
            Papel.VIDEO: "anthropic/claude-sonnet-5.5", Papel.RESERVA: "google/gemini-3.8-flash",
        },
    }

    assert {n: {p: r.modelo for p, r in por_papel.items()} for n, por_papel in RECOMENDACOES.items()} == esperado


def teste_lm14_nenhum_modelo_gratuito_entra_na_tabela() -> None:
    for por_papel in RECOMENDACOES.values():
        for recomendacao in por_papel.values():
            assert ":free" not in recomendacao.modelo
            assert recomendacao.motivo.strip()  # todo modelo diz por que está ali


def teste_lm14_cada_papel_grava_num_campo_que_existe_na_configuracao() -> None:
    assert set(CAMPO_DA_CONFIGURACAO) == set(Papel)
    for campo in CAMPO_DA_CONFIGURACAO.values():
        assert campo in Configuracao.__table__.columns


def teste_lm14_o_preset_nao_inclui_imagem_narracao_nem_perfil() -> None:
    campos = set(CAMPO_DA_CONFIGURACAO.values())

    assert not {"modelo_imagem", "modelo_perfil", "modelo_narracao", "prioridade_ia"} & campos


# --------------------------------------------------------------------------- #
# "Rápido"
# --------------------------------------------------------------------------- #


def teste_lm14_modelo_sem_raciocinio_e_rapido() -> None:
    assert e_rapido(_capacidades(raciocinio_suportado=False)) is True


def teste_lm14_raciocinio_opcional_sem_lista_de_esforcos_e_rapido() -> None:
    assert e_rapido(_capacidades(raciocinio_suportado=True, esforcos=())) is True


def teste_lm14_raciocinio_opcional_que_aceita_low_e_rapido() -> None:
    assert e_rapido(_capacidades(raciocinio_suportado=True, esforcos=("max", "xhigh", "high", "medium", "low"))) is True


def teste_lm14_deepseek_que_so_aceita_high_e_xhigh_nao_e_rapido() -> None:
    """Não é obrigatório no catálogo, mas não dá para desligá-lo: leva 20 a 33 s (item 4.10, LM24)."""
    assert e_rapido(_capacidades(raciocinio_suportado=True, esforcos=("xhigh", "high"))) is False


def teste_lm14_raciocinio_obrigatorio_com_minimo_low_nao_e_rapido() -> None:
    """``gemini-3.8-flash`` e ``claude-sonnet-5.5`` (LM24.5)."""
    assert e_rapido(_capacidades(raciocinio_suportado=True, raciocinio_obrigatorio=True, esforcos=("high", "medium", "low"))) is False


def teste_lm14_raciocinio_obrigatorio_com_minimo_minimal_e_rapido() -> None:
    assert e_rapido(_capacidades(raciocinio_suportado=True, raciocinio_obrigatorio=True, esforcos=("medium", "low", "minimal"))) is True


# --------------------------------------------------------------------------- #
# A conta do custo (a tabela do item 4.10)
# --------------------------------------------------------------------------- #


def _preco(entrada, saida, leitura=None, escrita=None) -> Capacidades:
    return _capacidades(
        preco_entrada=Decimal(entrada) / 1_000_000,
        preco_saida=Decimal(saida) / 1_000_000,
        preco_cache_leitura=None if leitura is None else Decimal(leitura) / 1_000_000,
        preco_cache_escrita=None if escrita is None else Decimal(escrita) / 1_000_000,
    )


@pytest.mark.parametrize(
    "capacidades, sem_cache, com_cache",
    [
        (_preco("0.10", "0.40", "0.010", "0.083"), "0.015", "0.006"),  # gemini-2.5-flash-lite
        (_preco("0.40", "1.60", "0.10", "0.40"), "0.061", "0.032"),  # gpt-4.1-mini
        (_preco("0.30", "2.50", "0.030", "0.083"), "0.059", "0.031"),  # gemini-2.5-flash
        (_preco("1.00", "5.00", "0.10", "1.25"), "0.162", "0.079"),  # claude-haiku-4.5
        (_preco("2.00", "10.00", "0.20", "2.50"), "0.324", "0.157"),  # claude-sonnet-5.5
    ],
)
def teste_lm14_a_conta_reproduz_a_tabela_da_especificacao(capacidades: Capacidades, sem_cache: str, com_cache: str) -> None:
    sem, com = custo_do_capitulo_tipico(capacidades)

    # A tabela da especificação arredonda de cabeça (0,0605 aparece como 0,061): vale a mesma ordem de grandeza, com meio milésimo de folga.
    assert abs(sem - Decimal(sem_cache)) <= Decimal("0.0006")
    assert abs(com - Decimal(com_cache)) <= Decimal("0.0006")


def teste_lm14_o_capitulo_tipico_e_12_mil_tokens_9_leituras_de_1200() -> None:
    assert (TOKENS_DO_CAPITULO_TIPICO, LEITURAS_DO_CAPITULO_TIPICO, SAIDA_POR_LEITURA_TIPICA) == (12000, 9, 1200)


def teste_lm14_com_cache_a_primeira_leitura_paga_a_escrita_e_as_outras_a_leitura() -> None:
    capacidades = _preco("1", "0", leitura="0.1", escrita="1.25")  # saída grátis, para isolar a entrada

    sem, com = custo_das_leituras(capacidades, 1_000_000, [0, 0, 0])

    assert sem == Decimal("3")  # 3 leituras x 1 milhão x US$ 1
    assert com == Decimal("1.25") + Decimal("0.1") * 2


def teste_lm14_sem_preco_de_cache_o_cache_cai_no_preco_de_entrada() -> None:
    """Nunca um desconto inventado."""
    capacidades = _preco("1", "0")

    sem, com = custo_das_leituras(capacidades, 1_000_000, [0, 0])

    assert sem == com == Decimal("2")


def teste_lm14_sem_preco_de_entrada_ou_de_saida_nao_se_estima() -> None:
    assert custo_das_leituras(_capacidades(preco_entrada=None), 1000, [100]) == (None, None)
    assert custo_das_leituras(_capacidades(preco_saida=None), 1000, [100]) == (None, None)


def teste_lm14_sem_leituras_o_custo_e_zero() -> None:
    assert custo_das_leituras(_preco("1", "1"), 1000, []) == (Decimal(0), Decimal(0))


def teste_lm14_cada_leitura_pode_ter_a_sua_saida() -> None:
    capacidades = _preco("0", "1000")  # só a saída custa

    sem, _ = custo_das_leituras(capacidades, 5000, [100, 300])

    assert sem == Decimal("0.4")  # 400 tokens x US$ 1.000 por milhão


# --------------------------------------------------------------------------- #
# GET /configuracao/modelos-recomendados
# --------------------------------------------------------------------------- #


def _modelos_do_catalogo_de_teste() -> list[dict]:
    return [
        _entrada("google/gemini-2.5-flash-lite", "0.0000001", "0.0000004", pricing={
            "prompt": "0.0000001", "completion": "0.0000004", "input_cache_read": "0.00000001", "input_cache_write": "0.0000000833"}),
        _entrada("openai/gpt-4o-mini", "0.00000015", "0.0000006"),
        _entrada(
            "google/gemini-3.8-flash", "0.00000075", "0.00000375",
            supported_parameters=["reasoning"], reasoning={"mandatory": True, "supported_efforts": ["high", "medium", "low"]},
        ),
    ]


def teste_lm14_a_rota_devolve_tres_niveis_com_os_sete_papeis(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    resposta = cliente.get("/configuracao/modelos-recomendados")

    assert resposta.status_code == 200, resposta.text
    niveis = resposta.json()
    assert [n["nivel"] for n in niveis] == ["ECONOMICO", "EQUILIBRADO", "QUALIDADE"]
    for nivel in niveis:
        assert [p["papel"] for p in nivel["papeis"]] == [p.value for p in Papel]


def teste_lm14_modelo_no_catalogo_vem_disponivel_com_preco_contexto_e_custo(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    economico = cliente.get("/configuracao/modelos-recomendados").json()[0]
    leitura = next(p for p in economico["papeis"] if p["papel"] == "LEITURA")

    assert leitura["modelo"] == "google/gemini-2.5-flash-lite"
    assert leitura["disponivel"] is True
    assert leitura["contexto"] == 1000000
    assert leitura["preco_entrada"] == pytest.approx(0.10)  # US$ por milhão
    assert leitura["preco_saida"] == pytest.approx(0.40)
    assert leitura["raciocinio_obrigatorio"] is False and leitura["rapido"] is True
    # 1ª leitura: 12000 x 0,0833/M (escrita do cache) + 1200 x 0,40/M; as 8 seguintes: 12000 x 0,01/M (leitura) + 1200 x 0,40/M.
    assert leitura["custo_do_capitulo_tipico"] == pytest.approx(0.00628, abs=1e-6)  # com cache
    assert leitura["custo_do_capitulo_tipico_sem_cache"] == pytest.approx(0.01512, abs=1e-6)
    assert leitura["motivo"]


def teste_lm14_modelo_de_raciocinio_obrigatorio_vem_lento(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    economico = cliente.get("/configuracao/modelos-recomendados").json()[0]
    video = next(p for p in economico["papeis"] if p["papel"] == "VIDEO")

    assert video["modelo"] == "google/gemini-3.8-flash"
    assert video["raciocinio_obrigatorio"] is True and video["rapido"] is False


def teste_lm14_modelo_que_nao_esta_no_catalogo_vem_indisponivel_e_com_nulos(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    qualidade = cliente.get("/configuracao/modelos-recomendados").json()[2]
    haiku = next(p for p in qualidade["papeis"] if p["papel"] == "EXTRACAO")

    assert haiku["modelo"] == "anthropic/claude-haiku-4.5"
    assert haiku["disponivel"] is False
    assert haiku["contexto"] is None and haiku["preco_entrada"] is None and haiku["rapido"] is None
    assert haiku["custo_do_capitulo_tipico"] is None and haiku["motivo"]


def teste_lm14_modelo_sem_preco_no_catalogo_nao_tem_custo(cliente: TestClient, monkeypatch) -> None:
    sem_preco = _entrada("openai/gpt-4o-mini")
    sem_preco["pricing"] = {}
    _catalogo(monkeypatch, sem_preco)

    economico = cliente.get("/configuracao/modelos-recomendados").json()[0]
    prompt = next(p for p in economico["papeis"] if p["papel"] == "PROMPT")

    assert prompt["disponivel"] is True and prompt["custo_do_capitulo_tipico"] is None


def teste_lm14_catalogo_que_nao_pode_ser_lido_e_502_e_nao_tudo_indisponivel(cliente: TestClient, monkeypatch) -> None:
    def quebrar() -> dict:
        raise httpx.ConnectError("fora do ar")

    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", quebrar)

    resposta = cliente.get("/configuracao/modelos-recomendados")

    assert resposta.status_code == 502
    assert "catálogo" in resposta.json()["detail"]


def teste_lm14_a_rota_nao_precisa_de_chave(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    assert cliente.get("/configuracao/modelos-recomendados").status_code == 200  # nenhum header de chave


# --------------------------------------------------------------------------- #
# PUT /configuracao/preset
# --------------------------------------------------------------------------- #


def teste_lm14_o_preset_grava_so_os_papeis_disponiveis_e_diz_quais_faltaram(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    resposta = cliente.put("/configuracao/preset", json={"nivel": "ECONOMICO"})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["modelo_extracao"] == "google/gemini-2.5-flash-lite"
    assert corpo["modelo_leitura"] == "google/gemini-2.5-flash-lite"
    assert corpo["modelo_prompt"] == "openai/gpt-4o-mini"
    assert corpo["modelo_traducao"] == "google/gemini-2.5-flash-lite"
    assert corpo["modelo_suavizacao"] == "google/gemini-2.5-flash-lite"
    assert corpo["modelo_video"] == "google/gemini-3.8-flash"
    assert corpo["modelo_reserva"] == "openai/gpt-4o-mini"
    assert corpo["papeis_nao_aplicados"] == []


def teste_lm14_papel_cujo_modelo_nao_existe_fica_como_estava(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())
    cliente.put("/configuracao", json={"modelo_extracao": "meu/modelo", "modelo_leitura": "meu/leitor"})

    resposta = cliente.put("/configuracao/preset", json={"nivel": "QUALIDADE"})

    corpo = resposta.json()
    # QUALIDADE: o haiku (extração e leitura) não está no catálogo de teste; o gemini-3.8-flash (prompt, reserva) está.
    assert corpo["modelo_extracao"] == "meu/modelo" and corpo["modelo_leitura"] == "meu/leitor"
    assert corpo["modelo_prompt"] == "google/gemini-3.8-flash" and corpo["modelo_reserva"] == "google/gemini-3.8-flash"
    assert set(corpo["papeis_nao_aplicados"]) == {"EXTRACAO", "LEITURA", "TRADUCAO", "SUAVIZACAO", "VIDEO"}


def teste_lm14_o_preset_nao_mexe_em_imagem_narracao_perfil_nem_prioridade(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())
    cliente.put(
        "/configuracao",
        json={
            "modelo_imagem": "meu/imagem", "modelo_perfil": "meu/perfil", "modelo_narracao": "meu/voz",
            "narracao_voz": "pt-BR-X", "prioridade_ia": "QUALIDADE", "modelos_de_imagem": ["a/b"],
        },
    )
    antes = cliente.get("/configuracao").json()

    depois = cliente.put("/configuracao/preset", json={"nivel": "EQUILIBRADO"}).json()

    for campo in ("modelo_imagem", "modelo_perfil", "modelo_narracao", "narracao_voz", "prioridade_ia", "modelos_de_imagem"):
        assert depois[campo] == antes[campo], campo


def teste_lm14_o_preset_e_de_cada_pessoa(cliente: TestClient, sessao_com_tabelas: Session, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())
    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    dono_id = sessao_com_tabelas.info["usuario_id"]

    cliente.put("/configuracao/preset", json={"nivel": "ECONOMICO"})

    definir_usuario(sessao_com_tabelas, maria.id)
    assert obter_ou_criar(sessao_com_tabelas).modelo_leitura is None  # a configuração dela não mudou
    definir_usuario(sessao_com_tabelas, dono_id)
    assert obter_ou_criar(sessao_com_tabelas).modelo_leitura == "google/gemini-2.5-flash-lite"


def teste_lm14_nivel_desconhecido_e_campo_extra_dao_422(cliente: TestClient) -> None:
    assert cliente.put("/configuracao/preset", json={"nivel": "LUXO"}).status_code == 422
    assert cliente.put("/configuracao/preset", json={}).status_code == 422
    assert cliente.put("/configuracao/preset", json={"nivel": "ECONOMICO", "modelo_imagem": "x"}).status_code == 422


def teste_lm14_preset_com_o_catalogo_fora_do_ar_nao_grava_nada(cliente: TestClient, monkeypatch) -> None:
    def quebrar() -> dict:
        raise httpx.ConnectError("fora do ar")

    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", quebrar)

    assert cliente.put("/configuracao/preset", json={"nivel": "ECONOMICO"}).status_code == 502
    assert cliente.get("/configuracao").json()["modelo_leitura"] is None


def teste_lm14_o_preset_devolve_toda_a_configuracao_atual(cliente: TestClient, monkeypatch) -> None:
    _catalogo(monkeypatch, *_modelos_do_catalogo_de_teste())

    corpo = cliente.put("/configuracao/preset", json={"nivel": "ECONOMICO"}).json()
    atual = cliente.get("/configuracao").json()

    assert {c: v for c, v in corpo.items() if c != "papeis_nao_aplicados"} == atual


# --------------------------------------------------------------------------- #
# LM16: a lista de modelos mais informativa
# --------------------------------------------------------------------------- #


def _provedor_com_lista(*entradas: dict) -> ProvedorOpenRouter:
    cliente = httpx.Client(
        base_url=ENDERECO_BASE, transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"data": list(entradas)}))
    )
    return ProvedorOpenRouter(cliente=cliente)


def _lista_de_teste() -> list[dict]:
    return [
        _entrada(
            "a/rapido", "0.0000001", "0.0000004",
            pricing={"prompt": "0.0000001", "completion": "0.0000004", "input_cache_read": "0.00000001"},
        ),
        _entrada(
            "b/obrigatorio", supported_parameters=["reasoning"], reasoning={"mandatory": True, "supported_efforts": ["high", "low"]},
        ),
        _entrada(
            "c/so_alto", supported_parameters=["reasoning"], reasoning={"mandatory": False, "supported_efforts": ["xhigh", "high"]},
        ),
        _entrada("d/com_teto", top_provider={"max_completion_tokens": 4096, "is_moderated": True}),
    ]


def teste_lm16_o_provedor_lista_os_campos_novos() -> None:
    modelos = {m.id: m for m in _provedor_com_lista(*_lista_de_teste()).listar_modelos()}

    rapido = modelos["a/rapido"]
    assert rapido.preco_entrada == pytest.approx(0.0000001)
    assert rapido.preco_cache_leitura == pytest.approx(0.00000001)
    assert rapido.raciocinio_obrigatorio is False and rapido.esforcos == [] and rapido.rapido is True

    obrigatorio = modelos["b/obrigatorio"]
    assert obrigatorio.raciocinio_obrigatorio is True and obrigatorio.esforcos == ["high", "low"] and obrigatorio.rapido is False

    assert modelos["c/so_alto"].rapido is False
    assert modelos["d/com_teto"].saida_maxima == 4096
    assert modelos["d/com_teto"].preco_cache_leitura is None


def teste_lm16_a_rota_devolve_os_campos_novos(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(_provedor_com_lista(*_lista_de_teste()))

    modelos = {m["id"]: m for m in cliente.get("/configuracao/modelos").json()}

    assert set(modelos["b/obrigatorio"]) >= {
        "preco_entrada", "preco_cache_leitura", "raciocinio_obrigatorio", "esforcos", "rapido", "saida_maxima",
    }
    assert modelos["b/obrigatorio"]["rapido"] is False and modelos["a/rapido"]["rapido"] is True


def teste_lm16_somente_rapidos_tira_os_lentos(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(_provedor_com_lista(*_lista_de_teste()))

    todos = {m["id"] for m in cliente.get("/configuracao/modelos").json()}
    rapidos = {m["id"] for m in cliente.get("/configuracao/modelos?somente_rapidos=true").json()}

    assert todos == {"a/rapido", "b/obrigatorio", "c/so_alto", "d/com_teto"}
    assert rapidos == {"a/rapido", "d/com_teto"}


def teste_lm16_o_provedor_falso_continua_valendo_com_os_padroes_seguros(cliente: TestClient, usar_provedor_falso) -> None:
    from imagineer.ia.falso import ProvedorFalso

    usar_provedor_falso(ProvedorFalso())

    modelos = cliente.get("/configuracao/modelos").json()

    assert modelos
    assert all(m["rapido"] is True and m["raciocinio_obrigatorio"] is False and m["esforcos"] == [] for m in modelos)


def teste_lm16_a_lista_continua_publica_e_sem_chave(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(_provedor_com_lista(*_lista_de_teste()))  # o provedor de teste não tem chave

    assert cliente.get("/configuracao/modelos").status_code == 200
