"""A estimativa de custo antes de analisar (item 4.10, LM15; etapa E7).

A conta é feita com os preços do catálogo (trocado por um de teste) e **nunca chama a IA**: o provedor falso dos testes registra as chamadas, e a
estimativa não pode aumentar nenhuma lista.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import catalogo_de_texto
from imagineer.ia.catalogo_de_texto import Capacidades
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.openrouter import estimar_tokens
from imagineer.ia.provedor import CenaSugerida, ElementoSugerido, ParticipanteSugerido
from imagineer.modelos import TipoElemento, Usuario
from imagineer.servicos.acesso import definir_usuario
from imagineer.servicos.estimativa_de_leitura import (
    AVISO_DA_ESTIMATIVA,
    AVISO_SEM_PRECO,
    SAIDA_DA_EXTRACAO,
    SAIDA_DA_IDENTIDADE,
    SAIDA_DO_DOSSIE,
    SAIDA_DO_ESTADO,
    custo_das_leituras,
    estimar_leitura,
)

from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_importado

MODELO = "x/leitor"
OUTRO = "x/extrator"


def _capacidades(**mudancas) -> Capacidades:
    base = dict(
        id=MODELO, contexto=100000, saida_maxima=None, estruturado=False, raciocinio_suportado=False, raciocinio_obrigatorio=False,
        esforcos=(), preco_entrada=Decimal("0.000001"), preco_saida=Decimal("0.000002"), preco_cache_leitura=Decimal("0.0000001"),
        preco_cache_escrita=Decimal("0.00000125"), gratuito=False, moderado=False,
    )
    base.update(mudancas)
    return Capacidades(**base)


def _entrada(id_: str, prompt: str = "0.000001", completion: str = "0.000002", **pricing) -> dict:
    return {
        "id": id_, "name": id_, "context_length": 100000,
        "pricing": {"prompt": prompt, "completion": completion, **pricing},
        "supported_parameters": [], "reasoning": None, "top_provider": {}, "architecture": {"output_modalities": ["text"]},
    }


# --------------------------------------------------------------------------- #
# A conta
# --------------------------------------------------------------------------- #

TEXTO = "palavra " * 3000  # 24.000 caracteres = 6.000 tokens estimados


def teste_lm15_o_numero_de_leituras_e_estado_e_identidade_por_elemento_mais_dossie_por_cena() -> None:
    estimativa = estimar_leitura(TEXTO, _capacidades(), elementos=6, cenas=3)

    assert estimativa.leituras == 6 * 2 + 3
    assert estimativa.tokens_do_capitulo == estimar_tokens(TEXTO) == 6000


def teste_lm15_a_extracao_soma_uma_leitura_quando_a_analise_ainda_nao_foi_feita() -> None:
    sem = estimar_leitura(TEXTO, _capacidades(), 2, 1)
    com = estimar_leitura(TEXTO, _capacidades(), 2, 1, com_extracao=True)

    assert com.leituras == sem.leituras + 1


def teste_lm15_as_saidas_por_tipo_de_leitura_sao_as_da_especificacao() -> None:
    assert (SAIDA_DO_ESTADO, SAIDA_DA_IDENTIDADE, SAIDA_DO_DOSSIE, SAIDA_DA_EXTRACAO) == (700, 150, 900, 2500)


def teste_lm15_o_custo_sem_cache_e_a_soma_de_entrada_e_saida_de_cada_leitura() -> None:
    estimativa = estimar_leitura(TEXTO, _capacidades(), elementos=1, cenas=1)

    # leituras: estado (700), identidade (150) e dossiê (900); cada uma paga 6000 tokens de entrada.
    esperado = sum(Decimal("0.000001") * 6000 + Decimal("0.000002") * saida for saida in (700, 150, 900))
    assert estimativa.custo_sem_cache == esperado


def teste_lm15_com_cache_a_primeira_leitura_paga_a_escrita_e_as_outras_a_leitura() -> None:
    estimativa = estimar_leitura(TEXTO, _capacidades(), elementos=1, cenas=1)

    saidas = [Decimal("0.000002") * s for s in (700, 150, 900)]
    esperado = (Decimal("0.00000125") * 6000 + saidas[0]) + sum(Decimal("0.0000001") * 6000 + s for s in saidas[1:])
    assert estimativa.custo_com_cache == esperado
    assert estimativa.custo_com_cache < estimativa.custo_sem_cache


def teste_lm15_sem_preco_de_cache_o_cache_cai_no_preco_de_entrada() -> None:
    capacidades = _capacidades(preco_cache_leitura=None, preco_cache_escrita=None)

    estimativa = estimar_leitura(TEXTO, capacidades, elementos=2, cenas=0)

    assert estimativa.custo_com_cache == estimativa.custo_sem_cache


def teste_lm15_sem_leituras_o_custo_e_zero() -> None:
    estimativa = estimar_leitura(TEXTO, _capacidades(), elementos=0, cenas=0)

    assert (estimativa.leituras, estimativa.custo_sem_cache, estimativa.custo_com_cache) == (0, Decimal(0), Decimal(0))


def teste_lm15_a_extracao_entra_nos_dois_custos_pelo_preco_sem_cache() -> None:
    """Uma chamada só: não há com quem dividir o cache, e a tarifa de escrita (mais cara) a encareceria à toa."""
    capacidades = _capacidades()
    sem_extracao = estimar_leitura(TEXTO, capacidades, 1, 0)
    com_extracao = estimar_leitura(TEXTO, capacidades, 1, 0, com_extracao=True)

    da_extracao = Decimal("0.000001") * 6000 + Decimal("0.000002") * 2500
    assert com_extracao.custo_sem_cache - sem_extracao.custo_sem_cache == da_extracao
    assert com_extracao.custo_com_cache - sem_extracao.custo_com_cache == da_extracao


def teste_lm15_a_extracao_usa_o_preco_do_modelo_de_extracao_quando_ele_e_outro() -> None:
    leitor = _capacidades()
    extrator = _capacidades(id=OUTRO, preco_entrada=Decimal("0.00001"), preco_saida=Decimal("0.00002"))

    com_outro = estimar_leitura(TEXTO, leitor, 0, 0, com_extracao=True, capacidades_da_extracao=extrator)
    com_o_mesmo = estimar_leitura(TEXTO, leitor, 0, 0, com_extracao=True)

    assert com_outro.custo_sem_cache == Decimal("0.00001") * 6000 + Decimal("0.00002") * 2500
    assert com_o_mesmo.custo_sem_cache == Decimal("0.000001") * 6000 + Decimal("0.000002") * 2500


def teste_lm15_o_aviso_diz_que_e_estimativa_e_onde_ver_o_real() -> None:
    estimativa = estimar_leitura(TEXTO, _capacidades(), 1, 1)

    assert estimativa.aviso == AVISO_DA_ESTIMATIVA == "Estimativa (pode variar até 50%); o custo real aparece em Custos."


def teste_lm15_modelo_sem_preco_da_custos_nulos_e_o_aviso_diz_isso() -> None:
    for capacidades in (_capacidades(preco_entrada=None), _capacidades(preco_saida=None), None):
        estimativa = estimar_leitura(TEXTO, capacidades, 2, 1)

        assert (estimativa.custo_sem_cache, estimativa.custo_com_cache) == (None, None)
        assert estimativa.aviso == AVISO_SEM_PRECO
        assert estimativa.leituras == 5  # o número de leituras ainda é conhecido


def teste_lm15_extrator_sem_preco_tira_os_custos_mas_nao_as_leituras() -> None:
    extrator = _capacidades(id=OUTRO, preco_entrada=None)

    estimativa = estimar_leitura(TEXTO, _capacidades(), 1, 0, com_extracao=True, capacidades_da_extracao=extrator)

    assert estimativa.custo_sem_cache is None and estimativa.custo_com_cache is None
    assert estimativa.leituras == 3


def teste_lm15_a_soma_das_leituras_coincide_com_custo_das_leituras() -> None:
    capacidades = _capacidades()

    assert estimar_leitura(TEXTO, capacidades, 1, 1).custo_sem_cache == custo_das_leituras(capacidades, 6000, [700, 150, 900])[0]


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #


def _ligar_o_catalogo(monkeypatch, *entradas: dict) -> None:
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": list(entradas)})


def _analisado(cliente: TestClient, usar_provedor_falso, *, elementos=("Jon", "Arya"), cenas=("A partida",)):
    """Um livro com o primeiro capítulo analisado pelo provedor falso: devolve (provedor, id do capítulo)."""
    provedor = usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome=nome) for nome in elementos],
            cenas_sugeridas=[
                CenaSugerida(titulo=titulo, participantes=[ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome=elementos[0])])
                for titulo in cenas
            ],
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]
    assert cliente.post(f"/capitulos/{capitulo_id}/sugestoes").status_code == 200
    return provedor, capitulo_id


def teste_lm15_a_rota_conta_as_sugestoes_nao_descartadas_do_capitulo(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)

    resposta = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert (corpo["elementos"], corpo["cenas"], corpo["leituras"]) == (2, 1, 2 * 2 + 1)
    assert corpo["inclui_extracao"] is False  # a análise já foi feita
    assert corpo["modelo"] == MODELO_FALSO
    assert corpo["aviso"] == AVISO_DA_ESTIMATIVA


def teste_lm15_sugestao_descartada_nao_entra_na_conta(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)
    sugestoes = cliente.get(f"/capitulos/{capitulo_id}/sugestoes").json()
    descartada = cliente.patch(f"/sugestoes-elemento/{sugestoes['elementos'][0]['id']}", json={"descartada": True})
    assert descartada.status_code == 200, descartada.text

    corpo = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura").json()

    assert corpo["elementos"] == 1 and corpo["leituras"] == 1 * 2 + 1


def teste_lm15_elementos_e_cenas_na_consulta_vencem_o_padrao(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)

    corpo = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura?elementos=10&cenas=0").json()

    assert (corpo["elementos"], corpo["cenas"], corpo["leituras"]) == (10, 0, 20)


def teste_lm15_valores_fora_do_limite_dao_422(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)

    assert cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura?elementos=-1").status_code == 422
    assert cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura?cenas=501").status_code == 422


def teste_lm15_capitulo_ainda_nao_analisado_inclui_a_extracao(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    corpo = cliente.get(f"/capitulos/{livro['capitulos'][0]['id']}/estimativa-de-leitura").json()

    assert corpo["inclui_extracao"] is True
    assert (corpo["elementos"], corpo["cenas"], corpo["leituras"]) == (0, 0, 1)  # só a extração
    assert corpo["custo_sem_cache"] > 0


def teste_lm15_a_rota_calcula_com_os_precos_do_catalogo(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(
        monkeypatch,
        _entrada(MODELO_FALSO, "0.000001", "0.000002", input_cache_read="0.0000001", input_cache_write="0.00000125"),
    )
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)
    texto = cliente.get(f"/capitulos/{capitulo_id}").json()["texto"]

    corpo = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura?elementos=1&cenas=0").json()

    tokens = estimar_tokens(texto)
    assert corpo["tokens_do_capitulo"] == tokens
    esperado_sem = 2 * 0.000001 * tokens + 0.000002 * (700 + 150)
    assert corpo["custo_sem_cache"] == pytest.approx(esperado_sem, abs=1e-6)
    assert corpo["custo_com_cache"] < corpo["custo_sem_cache"]


def teste_lm15_modelo_sem_preco_no_catalogo_da_custos_nulos_e_aviso(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, {**_entrada(MODELO_FALSO), "pricing": {}})
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)

    corpo = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura").json()

    assert corpo["custo_sem_cache"] is None and corpo["custo_com_cache"] is None
    assert corpo["aviso"] == AVISO_SEM_PRECO and corpo["leituras"] == 5


def teste_lm15_modelo_fora_do_catalogo_nao_derruba_a_estimativa(cliente: TestClient, usar_provedor_falso) -> None:
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)  # o catálogo de teste está vazio: o modelo "não existe" lá

    resposta = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura")

    assert resposta.status_code == 200
    assert resposta.json()["custo_sem_cache"] is None and resposta.json()["aviso"] == AVISO_SEM_PRECO


def teste_lm15_usa_o_modelo_de_leitura_quando_ha(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO), _entrada(MODELO, "0.00001", "0.00002"))
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)
    barato = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura").json()

    cliente.put("/configuracao", json={"modelo_leitura": MODELO})
    caro = cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura").json()

    assert barato["modelo"] == MODELO_FALSO and caro["modelo"] == MODELO
    assert caro["custo_sem_cache"] == pytest.approx(barato["custo_sem_cache"] * 10, rel=1e-3)


def teste_lm15_sem_nenhum_modelo_escolhido_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)

    resposta = cliente.get(f"/capitulos/{livro['capitulos'][0]['id']}/estimativa-de-leitura")

    assert resposta.status_code == 422
    assert "modelo de leitura" in resposta.json()["detail"]


def teste_lm15_capitulo_que_nao_existe_da_404(cliente: TestClient) -> None:
    assert cliente.get("/capitulos/999999/estimativa-de-leitura").status_code == 404


def teste_lm15_capitulo_de_outra_pessoa_da_404(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    _, capitulo_id = _analisado(cliente, usar_provedor_falso)
    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()

    definir_usuario(sessao_com_tabelas, maria.id)  # o ``cliente`` segue o usuário da sessão: agora quem pede é a Maria

    assert cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura").status_code == 404


def teste_lm15_a_estimativa_nunca_chama_o_provedor_de_texto(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _ligar_o_catalogo(monkeypatch, _entrada(MODELO_FALSO))
    provedor, capitulo_id = _analisado(cliente, usar_provedor_falso)

    def chamadas() -> tuple[int, ...]:
        return (
            len(provedor.chamadas_de_extracao), len(provedor.chamadas_de_estado), len(provedor.chamadas_de_identidade),
            len(provedor.chamadas_de_fundamentacao), len(provedor.chamadas_de_prompt),
        )

    antes = chamadas()
    for _ in range(3):
        assert cliente.get(f"/capitulos/{capitulo_id}/estimativa-de-leitura").status_code == 200

    assert chamadas() == antes
