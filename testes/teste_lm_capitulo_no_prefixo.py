"""O capítulo primeiro no pedido, com cache e ``session_id`` (item 4.10, LM9 a LM11; etapa E3).

Os provedores guardam em cache o **começo** do pedido. Com o capítulo antes do que varia (o elemento, a cena), as leituras do mesmo capítulo
repetem o mesmo prefixo, byte a byte, e pagam por ele só uma vez. Estes testes conferem o pedido que chega ao OpenRouter falso, sem rede.
"""

import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from imagineer.ia import catalogo_de_texto
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import (
    ENDERECO_BASE,
    RODAPE_DO_CAPITULO,
    PedidoComCapitulo,
    ProvedorOpenRouter,
    _mensagem_do_usuario,
    _sessao_de_cache,
)
from imagineer.modelos import TipoElemento

from testes.teste_rotas_prompts import _montar_frame_completo

CAPITULO = "Ned ergueu a espada diante do portão.\nO vento soprou forte sobre o pátio."
RESPOSTA_DE_ESTADO = json.dumps({"aparencia_fixa": "barba rala", "instante": "de capa", "ambiente": None})


class Servidor:
    """Um OpenRouter falso que guarda cada corpo recebido e responde ``conteudo``."""

    def __init__(self, conteudo: str = RESPOSTA_DE_ESTADO) -> None:
        self.corpos: list[dict] = []
        self._conteudo = conteudo

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.corpos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": self._conteudo}, "finish_reason": "stop"}]})

    def provedor(self) -> ProvedorOpenRouter:
        cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(self))
        return ProvedorOpenRouter(chave_api="chave", cliente=cliente, dormir=lambda _: None)

    def usuario(self, indice: int = 0):
        return self.corpos[indice]["messages"][1]["content"]

    def sistema(self, indice: int = 0) -> str:
        return self.corpos[indice]["messages"][0]["content"]


# --------------------------------------------------------------------------- #
# LM9: a estrutura e a ordem
# --------------------------------------------------------------------------- #


def teste_lm9_modelo_comum_recebe_um_texto_unico_com_o_capitulo_antes() -> None:
    pedido = PedidoComCapitulo(capitulo=CAPITULO, variavel="ELEMENTO: Ned")

    assert _mensagem_do_usuario("openai/gpt-4o-mini", pedido, com_cache=True) == f"TEXTO DO CAPÍTULO:\n{CAPITULO}\n\n---\nELEMENTO: Ned"


def teste_lm9_modelo_anthropic_recebe_dois_blocos_com_um_ponto_de_cache_no_fim_do_capitulo() -> None:
    pedido = PedidoComCapitulo(capitulo=CAPITULO, variavel="ELEMENTO: Ned")

    conteudo = _mensagem_do_usuario("anthropic/claude-haiku-4.5", pedido, com_cache=True)

    assert conteudo == [
        {"type": "text", "text": f"TEXTO DO CAPÍTULO:\n{CAPITULO}\n\n---\n", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "ELEMENTO: Ned"},
    ]


def teste_lm9_o_bloco_do_capitulo_e_o_texto_unico_tem_o_mesmo_prefixo() -> None:
    pedido = PedidoComCapitulo(capitulo=CAPITULO, variavel="x")

    texto = _mensagem_do_usuario("openai/gpt-4o-mini", pedido, com_cache=True)
    blocos = _mensagem_do_usuario("anthropic/x", pedido, com_cache=True)

    assert blocos[0]["text"] == texto[: len(blocos[0]["text"])]
    assert blocos[0]["text"].endswith(RODAPE_DO_CAPITULO)


def teste_lm9_sem_cache_ate_o_anthropic_recebe_texto_unico() -> None:
    pedido = PedidoComCapitulo(capitulo=CAPITULO, variavel="x")

    assert isinstance(_mensagem_do_usuario("anthropic/x", pedido, com_cache=False), str)


def teste_lm9_pedido_em_texto_passa_como_veio() -> None:
    assert _mensagem_do_usuario("anthropic/x", "só texto", com_cache=True) == "só texto"


def teste_lm9_o_pedido_de_leitura_comeca_com_texto_do_capitulo_e_o_prefixo_e_igual_entre_elementos() -> None:
    servidor = Servidor()
    provedor = servidor.provedor()

    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", "o senhor", None, "x/modelo", id_do_capitulo=7)
    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Arya", "a filha", "usa botas", "x/modelo", id_do_capitulo=7)

    ned, arya = servidor.usuario(0), servidor.usuario(1)
    abertura = f"TEXTO DO CAPÍTULO:\n{CAPITULO}{RODAPE_DO_CAPITULO}"
    assert ned.startswith(abertura) and arya.startswith(abertura)
    assert ned != arya
    assert "Ned" not in abertura.replace("Ned ergueu", "")  # nada do que varia entra antes do ``---``
    assert servidor.sistema(0) == servidor.sistema(1)  # e a instrução de sistema também é a mesma


def teste_lm9_quando_o_texto_do_capitulo_muda_o_prefixo_muda() -> None:
    servidor = Servidor()
    provedor = servidor.provedor()

    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")
    provedor.sugerir_estado(CAPITULO + " Fim.", TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")

    assert servidor.usuario(0).split("---")[0] != servidor.usuario(1).split("---")[0]


def teste_lm9_o_capitulo_vai_sem_nenhuma_normalizacao() -> None:
    estranho = "  Texto com espaços no fim   \n\n\ttabulação e linhas em branco\n\n"
    servidor = Servidor()

    servidor.provedor().sugerir_identidade(estranho, TipoElemento.PERSONAGEM, "Ned", None, "x/modelo")

    assert f"TEXTO DO CAPÍTULO:\n{estranho}{RODAPE_DO_CAPITULO}" in servidor.usuario()


def teste_lm9_anthropic_manda_o_cache_control_so_no_primeiro_bloco_pelo_conversar() -> None:
    servidor = Servidor()

    servidor.provedor().sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, None, "anthropic/claude-haiku-4.5")

    primeiro, segundo = servidor.usuario()
    assert primeiro["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in segundo
    assert primeiro["text"].startswith("TEXTO DO CAPÍTULO:")


def teste_lm9_modelo_que_nao_e_anthropic_nunca_leva_cache_control() -> None:
    servidor = Servidor()

    servidor.provedor().sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, None, "google/gemini-2.5-flash-lite")

    assert isinstance(servidor.usuario(), str)
    assert "cache_control" not in json.dumps(servidor.corpos[0])


def teste_lm9_as_tarefas_que_nao_leem_o_capitulo_nao_mudam() -> None:
    """Tradução, correção e a montagem do prompt seguem com o pedido em texto, sem capítulo."""
    servidor = Servidor("a red door")

    servidor.provedor().traduzir_prompt("uma porta vermelha", "en", "anthropic/claude-haiku-4.5")

    assert isinstance(servidor.usuario(), str)
    assert "TEXTO DO CAPÍTULO" not in servidor.usuario()


def teste_lm9_se_o_modelo_recusar_o_cache_control_as_chamadas_seguintes_vao_sem_ele() -> None:
    respostas = [
        httpx.Response(400, text="Unsupported field: cache_control"),
        httpx.Response(200, json={"choices": [{"message": {"content": RESPOSTA_DE_ESTADO}, "finish_reason": "stop"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": RESPOSTA_DE_ESTADO}, "finish_reason": "stop"}]}),
    ]
    corpos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(pedido.content))
        return respostas.pop(0)

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    provedor = ProvedorOpenRouter(chave_api="chave", cliente=cliente, dormir=lambda _: None)

    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, None, "anthropic/x")
    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Arya", None, None, "anthropic/x")

    assert "cache_control" in json.dumps(corpos[0])  # a primeira tentativa levava
    assert "cache_control" not in json.dumps(corpos[1])  # a repetição da mesma chamada, não
    assert "cache_control" not in json.dumps(corpos[2])  # e a seguinte já nasce limpa
    assert corpos[2]["messages"][1]["content"].startswith("TEXTO DO CAPÍTULO:")  # o capítulo continua primeiro


# --------------------------------------------------------------------------- #
# LM10: o que vai em ``variavel`` em cada operação
# --------------------------------------------------------------------------- #


def teste_lm10_extracao_leva_os_cadastrados_e_a_orientacao_depois_do_capitulo() -> None:
    servidor = Servidor(json.dumps({"elementos": [], "cenas": []}))

    servidor.provedor().extrair_elementos(CAPITULO, ["- Ned (PERSONAGEM)"], "x/modelo", orientacao="procure a espada")

    usuario = servidor.usuario()
    assert usuario.startswith(f"TEXTO DO CAPÍTULO:\n{CAPITULO}{RODAPE_DO_CAPITULO}")
    variavel = usuario.split(RODAPE_DO_CAPITULO, 1)[1]
    assert variavel.startswith("ELEMENTOS JÁ CADASTRADOS NESTE LIVRO (nome, tipo e quem são):\n- - Ned (PERSONAGEM)")
    assert "ORIENTAÇÃO DO USUÁRIO" in variavel and variavel.endswith("procure a espada")
    assert variavel.index("ELEMENTOS JÁ CADASTRADOS") < variavel.index("ORIENTAÇÃO DO USUÁRIO")


def teste_lm10_extracao_sem_orientacao_nao_leva_o_bloco() -> None:
    servidor = Servidor(json.dumps({"elementos": [], "cenas": []}))

    servidor.provedor().extrair_elementos(CAPITULO, [], "x/modelo")

    assert "ORIENTAÇÃO DO USUÁRIO" not in servidor.usuario()
    assert "(nenhum elemento cadastrado ainda)" in servidor.usuario()


def teste_lm10_estado_leva_os_quatro_blocos_na_ordem_de_hoje() -> None:
    servidor = Servidor()

    servidor.provedor().sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", "o senhor", "de capa", "x/modelo", aparencia_anterior="barba rala")

    variavel = servidor.usuario().split(RODAPE_DO_CAPITULO, 1)[1]
    assert variavel == (
        "ELEMENTO A DESCREVER: Ned (PERSONAGEM)\n"
        "IDENTIDADE JÁ CONHECIDA: o senhor\n"
        "APARÊNCIA ESTABELECIDA ATÉ AQUI (traços fixos de capítulos anteriores): barba rala\n"
        "ESTADO JÁ REGISTRADO (pode estar desatualizado): de capa"
    )


def teste_lm10_identidade_leva_o_elemento_e_a_identidade_conhecida() -> None:
    servidor = Servidor(json.dumps({"descricao": None}))

    servidor.provedor().sugerir_identidade(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, "x/modelo")

    assert servidor.usuario().split(RODAPE_DO_CAPITULO, 1)[1] == "ELEMENTO: Ned (PERSONAGEM)\nIDENTIDADE JÁ CONHECIDA: (nenhuma ainda)"


def teste_lm10_fundamentacao_leva_a_cena_os_participantes_e_o_trecho() -> None:
    servidor = Servidor(json.dumps({"contexto": "no pátio, de dia"}))

    servidor.provedor().fundamentar_frame(
        CAPITULO, "No pátio", "duelo", "manhã", None, "tenso", ["Ned: de capa"], "x/modelo", trecho="Ned ergueu a espada."
    )

    usuario = servidor.usuario()
    assert usuario.startswith(f"TEXTO DO CAPÍTULO:\n{CAPITULO}{RODAPE_DO_CAPITULO}")
    variavel = usuario.split(RODAPE_DO_CAPITULO, 1)[1]
    assert variavel == (
        "O QUE O USUÁRIO ESCREVEU SOBRE A CENA:\n"
        "Título: No pátio\n"
        "Descrição: duelo\n"
        "Horário: manhã\n"
        "Clima: (não informado)\n"
        "Humor: tenso\n\n"
        "PARTICIPANTES, COM A APARÊNCIA JÁ ESTABELECIDA:\n- Ned: de capa\n\n"
        "TRECHO DO LIVRO EM QUE A CENA ACONTECE (literal, as palavras do autor):\nNed ergueu a espada."
    )


def teste_lm10_fundamentacao_sem_trecho_nao_leva_o_bloco_do_trecho() -> None:
    servidor = Servidor(json.dumps({"contexto": "no pátio"}))

    servidor.provedor().fundamentar_frame(CAPITULO, "No pátio", None, None, None, None, [], "x/modelo")

    assert "TRECHO DO LIVRO" not in servidor.usuario()
    assert servidor.usuario().endswith("PARTICIPANTES, COM A APARÊNCIA JÁ ESTABELECIDA:\n(nenhum)")


# --------------------------------------------------------------------------- #
# LM11: a sessão de cache
# --------------------------------------------------------------------------- #


def teste_lm11_a_sessao_e_o_id_do_capitulo_mais_o_inicio_do_hash_do_texto() -> None:
    esperado = f"cap-12-{hashlib.sha1(CAPITULO.encode()).hexdigest()[:10]}"

    assert _sessao_de_cache(12, CAPITULO) == esperado
    assert len(esperado.split("-")[2]) == 10


def teste_lm11_sem_id_do_capitulo_nao_ha_sessao() -> None:
    assert _sessao_de_cache(None, CAPITULO) is None


def teste_lm11_mudando_o_texto_a_sessao_muda() -> None:
    assert _sessao_de_cache(1, CAPITULO) != _sessao_de_cache(1, CAPITULO + "!")
    assert _sessao_de_cache(1, CAPITULO) != _sessao_de_cache(2, CAPITULO)


def teste_lm11_todas_as_leituras_do_capitulo_levam_o_mesmo_session_id(monkeypatch) -> None:
    modelo = {
        "id": "x/modelo",
        "context_length": 100000,
        "pricing": {"prompt": "0.000001"},
        "supported_parameters": ["max_tokens"],
        "reasoning": None,
        "top_provider": {"max_completion_tokens": 64000},
    }
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [modelo]})
    servidor = Servidor(json.dumps({"descricao": None, "contexto": "ok", "aparencia_fixa": "a", "instante": "i", "ambiente": None}))
    provedor = servidor.provedor()

    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo", id_do_capitulo=7)
    provedor.sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Arya", None, None, "x/modelo", id_do_capitulo=7)
    provedor.sugerir_identidade(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, "x/modelo", id_do_capitulo=7)
    provedor.fundamentar_frame(CAPITULO, "Cena", None, None, None, None, [], "x/modelo", id_do_capitulo=7)

    sessoes = {c.get("session_id") for c in servidor.corpos}
    assert sessoes == {_sessao_de_cache(7, CAPITULO)}


def teste_lm11_sem_id_do_capitulo_o_corpo_nao_leva_session_id(monkeypatch) -> None:
    modelo = {"id": "x/modelo", "context_length": 1000, "pricing": {"prompt": "1"}, "supported_parameters": []}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [modelo]})
    servidor = Servidor()

    servidor.provedor().sugerir_estado(CAPITULO, TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")

    assert "session_id" not in servidor.corpos[0]


def teste_lm11_o_provedor_falso_aceita_o_id_do_capitulo_e_o_registra() -> None:
    falso = ProvedorFalso()

    falso.sugerir_estado("t", TipoElemento.PERSONAGEM, "Ned", None, None, "m", id_do_capitulo=3)
    falso.sugerir_identidade("t", TipoElemento.PERSONAGEM, "Ned", None, "m", id_do_capitulo=3)
    falso.fundamentar_frame("t", "c", None, None, None, None, [], "m", id_do_capitulo=3)
    falso.sugerir_estado("t", TipoElemento.PERSONAGEM, "Ned", None, None, "m")

    assert falso.chamadas_de_estado[0]["id_do_capitulo"] == 3
    assert falso.chamadas_de_identidade[0]["id_do_capitulo"] == 3
    assert falso.chamadas_de_fundamentacao[0]["id_do_capitulo"] == 3
    assert "id_do_capitulo" not in falso.chamadas_de_estado[1]  # quem não passa continua como antes


def teste_lm11_a_rota_passa_o_id_do_capitulo_nas_tres_leituras(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="pintura")
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")
    id_do_capitulo = livro["capitulos"][0]["id"]

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert provedor.chamadas_de_estado[0]["id_do_capitulo"] == id_do_capitulo
    assert provedor.chamadas_de_identidade[0]["id_do_capitulo"] == id_do_capitulo
    assert provedor.chamadas_de_fundamentacao[0]["id_do_capitulo"] == id_do_capitulo


@pytest.mark.parametrize("metodo", ["sugerir_estado", "sugerir_identidade", "fundamentar_frame"])
def teste_lm11_a_interface_do_provedor_declara_o_id_do_capitulo(metodo: str) -> None:
    import inspect

    from imagineer.ia.provedor import ProvedorIA

    parametro = inspect.signature(getattr(ProvedorIA, metodo)).parameters["id_do_capitulo"]
    assert parametro.default is None
