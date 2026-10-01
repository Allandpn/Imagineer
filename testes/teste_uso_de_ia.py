"""O custo de cada chamada à IA (item 4.3, "Custo das chamadas de IA").

O provedor lê o bloco ``usage`` da resposta e avisa por ``ao_usar``; ``gravar_uso`` guarda a linha.
Nenhum teste faz chamada de rede: o OpenRouter é um transporte falso do ``httpx``.
"""

import json
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session, sessionmaker

from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.ia.provedor import UsoDaChamada
from imagineer.modelos import UsoDeIA
from imagineer.servicos.uso_de_ia import gravar_uso

RESPOSTA_DA_EXTRACAO = json.dumps({"elementos": [], "cenas": []})


def _provedor(resposta: dict, avisos: list, pedidos: list | None = None, ao_usar=None):
    """Um provedor ligado a um OpenRouter falso que devolve ``resposta``; guarda o que recebe em ``pedidos``."""

    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedidos is not None:
            pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json=resposta)

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave", cliente=cliente, ao_usar=ao_usar or avisos.append)


def _resposta(usage: dict | None, conteudo: str = RESPOSTA_DA_EXTRACAO, id_: str | None = "gen-abc") -> dict:
    corpo: dict = {"choices": [{"message": {"content": conteudo}}]}
    if usage is not None:
        corpo["usage"] = usage
    if id_ is not None:
        corpo["id"] = id_
    return corpo


def teste_avisa_o_consumo_com_tokens_custo_e_id_da_geracao() -> None:
    avisos: list[UsoDaChamada] = []
    provedor = _provedor(
        _resposta({"prompt_tokens": 1200, "completion_tokens": 340, "cost": 0.00123456}), avisos
    )

    provedor.extrair_elementos("texto", [], "openai/gpt-4o-mini")

    (uso,) = avisos
    assert uso == UsoDaChamada(
        operacao="extracao",
        modelo="openai/gpt-4o-mini",
        tokens_entrada=1200,
        tokens_saida=340,
        custo=Decimal("0.00123456"),
        id_da_geracao="gen-abc",
    )


def teste_pede_o_bloco_de_uso_ao_openrouter() -> None:
    pedidos: list[dict] = []
    provedor = _provedor(_resposta({"cost": 0.1}), [], pedidos)

    provedor.extrair_elementos("texto", [], "m")

    assert pedidos[0]["usage"] == {"include": True}


def teste_custo_ausente_fica_nulo_e_nunca_vira_zero() -> None:
    """Modelo gratuito ou chave própria do provedor: o OpenRouter não informa o custo."""
    avisos: list[UsoDaChamada] = []
    provedor = _provedor(_resposta({"prompt_tokens": 10, "completion_tokens": 5}), avisos)

    provedor.extrair_elementos("texto", [], "m")

    assert avisos[0].custo is None
    assert avisos[0].tokens_entrada == 10


def teste_resposta_sem_usage_ou_com_lixo_nao_quebra_nada() -> None:
    avisos: list[UsoDaChamada] = []

    _provedor(_resposta(None, id_=None), avisos).extrair_elementos("t", [], "m")
    _provedor(
        _resposta({"prompt_tokens": "muitos", "completion_tokens": True, "cost": "caro"}), avisos
    ).extrair_elementos("t", [], "m")

    for uso in avisos:
        assert (uso.tokens_entrada, uso.tokens_saida, uso.custo) == (None, None, None)
    assert avisos[0].id_da_geracao is None


def teste_cada_operacao_tem_o_seu_nome() -> None:
    avisos: list[UsoDaChamada] = []
    provedor = _provedor(_resposta({"cost": 0.1}, conteudo='{"descricao": "x", "contexto": "y", "estilo": "z"}'), avisos)

    provedor.extrair_elementos("t", [], "m")
    provedor.sugerir_estado("t", _tipo(), "Jon", None, None, "m")
    provedor.sugerir_identidade("t", _tipo(), "Jon", None, "m")
    provedor.fundamentar_frame("t", "Cena", None, None, None, None, [], "m")
    provedor.montar_prompt(**_argumentos_do_prompt())
    provedor.sugerir_perfil_renderizacao("Livro", "Autor", "pt", None, "m")

    assert [a.operacao for a in avisos] == [
        "extracao", "estado", "identidade", "fundamentacao", "prompt", "perfil"
    ]


def teste_falha_ao_anotar_o_consumo_nunca_derruba_a_chamada() -> None:
    """A resposta já foi paga: perder a linha de métrica é melhor que perder o capítulo analisado."""

    def quebrado(_: UsoDaChamada) -> None:
        raise RuntimeError("banco fora do ar")

    provedor = _provedor(_resposta({"cost": 0.1}), [], ao_usar=quebrado)

    extracao = provedor.extrair_elementos("texto", [], "m")

    assert extracao.elementos == []  # a chamada deu certo apesar do erro ao anotar


def teste_sem_ao_usar_o_provedor_funciona_como_antes() -> None:
    cliente = httpx.Client(
        base_url=ENDERECO_BASE,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_resposta({"cost": 1}))),
    )

    assert ProvedorOpenRouter(chave_api="c", cliente=cliente).extrair_elementos("t", [], "m").elementos == []


def teste_gravar_uso_guarda_a_linha_com_commit_proprio(sessao_com_tabelas: Session) -> None:
    criador = sessionmaker(bind=sessao_com_tabelas.get_bind())

    gravar_uso(
        UsoDaChamada(
            operacao="extracao", modelo="openai/gpt-4o-mini", tokens_entrada=100, tokens_saida=20,
            custo=Decimal("0.00004200"), id_da_geracao="gen-1",
        ),
        criador,
    )
    gravar_uso(UsoDaChamada(operacao="prompt", modelo="gratis/modelo"), criador)

    linhas = sessao_com_tabelas.query(UsoDeIA).order_by(UsoDeIA.id).all()
    assert [(l.operacao, l.modelo, l.tokens_entrada, l.custo, l.id_da_geracao) for l in linhas] == [
        ("extracao", "openai/gpt-4o-mini", 100, Decimal("0.000042"), "gen-1"),
        ("prompt", "gratis/modelo", None, None, None),
    ]
    assert all(l.criado_em is not None for l in linhas)  # preenchido pelo banco


def teste_construir_provedor_liga_a_gravacao_do_uso() -> None:
    """A fábrica usada pelas rotas entrega o provedor já ligado a ``gravar_uso``."""
    from imagineer.servicos.configuracao_ia import construir_provedor

    assert construir_provedor("chave")._ao_usar is gravar_uso


def _tipo():
    from imagineer.modelos import TipoElemento

    return TipoElemento.PERSONAGEM


def _argumentos_do_prompt() -> dict:
    import inspect

    assinatura = inspect.signature(ProvedorOpenRouter.montar_prompt)
    argumentos: dict = {}
    for nome, parametro in assinatura.parameters.items():
        if nome == "self":
            continue
        argumentos[nome] = {"modelo": "m"}.get(nome, [] if "list" in str(parametro.annotation) else None)
    return argumentos
