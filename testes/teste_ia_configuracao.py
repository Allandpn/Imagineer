"""Testes da integração com IA e da configuração (Etapas 4.1 a 4.3).

Nenhum teste faz chamada de rede. O provedor OpenRouter é exercitado com um
transporte falso do ``httpx``, que responde o que o teste combinar — é o que
permite testar o tratamento de erro, de resposta malformada e de JSON embrulhado
em markdown, casos que uma chamada real raramente produziria na hora certa.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.openrouter import (
    ENDERECO_BASE,
    ProvedorOpenRouter,
    estimar_tokens,
)
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ElementoSugerido,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    TextoLongoDemais,
)
from imagineer.modelos import TipoElemento


def _provedor(respostas: dict[str, object], chave: str | None = "chave-de-teste"):
    """Monta um ProvedorOpenRouter que responde o que o teste combinar.

    ``respostas`` mapeia o caminho da URL para o que devolver: um dicionário (vira
    JSON com 200), uma ``httpx.Response`` pronta, ou uma exceção a levantar.
    """

    def responder(pedido: httpx.Request) -> httpx.Response:
        combinado = respostas[pedido.url.path.replace("/api/v1", "")]
        if isinstance(combinado, Exception):
            raise combinado
        if isinstance(combinado, httpx.Response):
            return combinado
        return httpx.Response(200, json=combinado)

    cliente = httpx.Client(
        base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
    )
    return ProvedorOpenRouter(chave_api=chave, cliente=cliente)


def _resposta_de_conversa(conteudo: str) -> dict:
    """O formato que o OpenRouter devolve numa conversa."""
    return {"choices": [{"message": {"content": conteudo}}]}


# --------------------------------------------------------------------------- #
# Listagem de modelos
# --------------------------------------------------------------------------- #


def teste_listar_modelos_descarta_os_que_nao_sao_de_texto() -> None:
    """A lista do OpenRouter tem modelos de imagem, áudio e música.

    Nenhum deles serve aqui, e só atrapalhariam a escolha.
    """
    provedor = _provedor(
        {
            "/models": {
                "data": [
                    {
                        "id": "bom/modelo",
                        "name": "Bom",
                        "context_length": 128000,
                        "pricing": {"prompt": "0"},
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                        },
                    },
                    {
                        "id": "musica/modelo",
                        "name": "Música",
                        "context_length": 1000000,
                        "pricing": {"prompt": "0"},
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["audio"],
                        },
                    },
                ]
            }
        }
    )

    modelos = provedor.listar_modelos()

    assert [m.id for m in modelos] == ["bom/modelo"]
    assert modelos[0].contexto == 128000
    assert modelos[0].gratuito is True


def teste_listar_modelos_funciona_sem_chave() -> None:
    """O endpoint de modelos do OpenRouter é público.

    É o que permite ver a lista antes de cadastrar a chave — que é a ordem em que
    o usuário faz as coisas.
    """
    provedor = _provedor({"/models": {"data": []}}, chave=None)

    assert provedor.listar_modelos() == []


def teste_modelo_pago_nao_e_marcado_como_gratuito() -> None:
    provedor = _provedor(
        {
            "/models": {
                "data": [
                    {"id": "pago/modelo", "context_length": 8000, "pricing": {"prompt": "0.0000012"}}
                ]
            }
        }
    )

    assert provedor.listar_modelos()[0].gratuito is False


def teste_gratuitos_vem_antes_na_lista() -> None:
    """A tela mostra primeiro o que não custa nada."""
    provedor = _provedor(
        {
            "/models": {
                "data": [
                    {"id": "z/pago", "name": "Alfa pago", "pricing": {"prompt": "0.001"}},
                    {"id": "a/gratis", "name": "Zeta grátis", "pricing": {"prompt": "0"}},
                ]
            }
        }
    )

    assert [m.id for m in provedor.listar_modelos()] == ["a/gratis", "z/pago"]


# --------------------------------------------------------------------------- #
# Extração de elementos
# --------------------------------------------------------------------------- #


def teste_extrair_elementos_interpreta_o_json() -> None:
    resposta = json.dumps(
        {
            "elementos": [
                {
                    "tipo": "PERSONAGEM",
                    "nome": "Ned Stark",
                    "descricao": "Senhor de Winterfell.",
                    "manter_estado_atual": False,
                },
                {
                    "tipo": "AMBIENTE",
                    "nome": "Winterfell",
                    "manter_estado_atual": True,
                },
            ]
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    extracao = provedor.extrair_elementos("texto do capítulo", [], "algum/modelo")

    assert extracao.modelo == "algum/modelo"
    assert [e.nome for e in extracao.elementos] == ["Ned Stark", "Winterfell"]
    assert extracao.elementos[0].tipo is TipoElemento.PERSONAGEM
    assert extracao.elementos[0].descricao == "Senhor de Winterfell."
    assert extracao.elementos[1].manter_estado_atual is True


def teste_extrair_elementos_aceita_json_embrulhado_em_markdown() -> None:
    """Modelos põem cerca de markdown mesmo quando a instrução pede o contrário.

    Recusar por isso desperdiçaria uma chamada que na verdade deu certo.
    """
    resposta = '```json\n{"elementos": [{"tipo": "OBJETO", "nome": "Gelo"}]}\n```'
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    extracao = provedor.extrair_elementos("texto", [], "algum/modelo")

    assert [e.nome for e in extracao.elementos] == ["Gelo"]


def teste_extrair_elementos_aceita_conversa_antes_do_json() -> None:
    """Alguns modelos escrevem uma frase antes de obedecer."""
    resposta = 'Claro! Aqui está:\n{"elementos": [{"tipo": "CRIATURA", "nome": "Lobo"}]}'
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    assert provedor.extrair_elementos("t", [], "m").elementos[0].nome == "Lobo"


def teste_extrair_elementos_descarta_entradas_malformadas() -> None:
    """Uma entrada ruim não deveria derrubar as outras vinte.

    É sugestão: o usuário confirma tudo de qualquer forma (item 4.4).
    """
    resposta = json.dumps(
        {
            "elementos": [
                {"tipo": "PERSONAGEM", "nome": "Válido"},
                {"tipo": "DRAGAO_VOADOR", "nome": "Tipo inexistente"},
                {"tipo": "PERSONAGEM", "nome": ""},
                {"tipo": "PERSONAGEM"},
                "isto nem é um objeto",
            ]
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    elementos = provedor.extrair_elementos("t", [], "m").elementos

    assert [e.nome for e in elementos] == ["Válido"]


def teste_extrair_elementos_interpreta_cenas_sugeridas() -> None:
    """As cenas combinam elementos já identificados num momento específico."""
    resposta = json.dumps(
        {
            "elementos": [
                {"tipo": "PERSONAGEM", "nome": "Ned Stark"},
                {"tipo": "OBJETO", "nome": "Gelo"},
            ],
            "cenas": [
                {
                    "titulo": "A execução",
                    "descricao": "Ned empunha Gelo antes da sentença.",
                    "horario": "manhã",
                    "clima": "frio",
                    "humor": "solene",
                    "participantes": [
                        {"tipo": "PERSONAGEM", "nome": "Ned Stark"},
                        {"tipo": "OBJETO", "nome": "Gelo"},
                    ],
                }
            ],
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    extracao = provedor.extrair_elementos("t", [], "m")

    assert len(extracao.frames) == 1
    frame = extracao.frames[0]
    assert frame.titulo == "A execução"
    assert frame.horario == "manhã"
    assert [p.nome for p in frame.participantes] == ["Ned Stark", "Gelo"]
    assert frame.participantes[1].tipo is TipoElemento.OBJETO


def teste_extrair_elementos_descarta_cena_sem_titulo_ou_sem_participantes() -> None:
    """Uma cena malformada não deveria derrubar as outras (mesma regra dos elementos)."""
    resposta = json.dumps(
        {
            "elementos": [{"tipo": "PERSONAGEM", "nome": "Ned Stark"}],
            "cenas": [
                {"titulo": "", "participantes": [{"tipo": "PERSONAGEM", "nome": "Ned Stark"}]},
                {"titulo": "Cena vazia", "participantes": []},
                {"titulo": "Cena boa", "participantes": [{"tipo": "PERSONAGEM", "nome": "Ned Stark"}]},
                "isto nem é um objeto",
            ],
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    frames = provedor.extrair_elementos("t", [], "m").frames

    assert [f.titulo for f in frames] == ["Cena boa"]


def teste_resposta_sem_json_da_erro_com_orientacao() -> None:
    """A mensagem precisa dizer o que fazer, não só que falhou."""
    provedor = _provedor({"/chat/completions": _resposta_de_conversa("Desculpe, não posso.")})

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.extrair_elementos("t", [], "m")

    assert "outro modelo" in str(erro.value)


def teste_estados_conhecidos_vao_no_pedido() -> None:
    """É o contexto que permite a IA responder "manter estado atual" (item 4.4).

    Sem ele, a IA inventaria um estado novo a cada capítulo.
    """
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(
            200, json=_resposta_de_conversa('{"elementos": []}')
        )

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.extrair_elementos(
        "o capítulo", ["Ned Stark: capa de pele", "Winterfell: coberto de neve"], "m"
    )

    pedido_do_usuario = capturado["corpo"]["messages"][1]["content"]
    assert "Ned Stark: capa de pele" in pedido_do_usuario
    assert "Winterfell: coberto de neve" in pedido_do_usuario
    assert "o capítulo" in pedido_do_usuario


def teste_sem_estados_conhecidos_o_pedido_diz_isso() -> None:
    """Deixar o campo vazio confundiria o modelo mais que uma frase explícita."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa('{"elementos": []}'))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.extrair_elementos("texto", [], "m")

    assert "nenhum elemento cadastrado" in capturado["corpo"]["messages"][1]["content"]


# --------------------------------------------------------------------------- #
# Montagem de prompt
# --------------------------------------------------------------------------- #


def teste_montar_prompt_devolve_o_texto_limpo() -> None:
    provedor = _provedor(
        {"/chat/completions": _resposta_de_conversa("  watercolor, snowy courtyard  \n")}
    )

    montado = provedor.montar_prompt("A chegada", ["Ned: capa de pele"], "aquarela", "m")

    assert montado.texto == "watercolor, snowy courtyard"
    assert montado.modelo == "m"


def teste_montar_prompt_manda_cena_elementos_e_estilo() -> None:
    """Os três precisam chegar ao modelo, ou o prompt sai incompleto."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa("prompt"))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.montar_prompt(
        "O pátio ao anoitecer", ["Ned Stark: capa de pele"], "aquarela sombria", "m"
    )

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "O pátio ao anoitecer" in enviado
    assert "Ned Stark: capa de pele" in enviado
    assert "aquarela sombria" in enviado


def teste_montar_prompt_inclui_comentario_do_usuario_com_prioridade() -> None:
    """O comentário tem prioridade sobre a leitura automática (item 4.4)."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa("prompt"))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.montar_prompt(
        "O pátio ao anoitecer",
        ["Ned Stark: capa de pele"],
        "aquarela sombria",
        "m",
        comentario_do_usuario="A barba dele é rala, não cheia.",
    )

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "A barba dele é rala, não cheia." in enviado


def teste_montar_prompt_sem_comentario_nao_menciona_prioridade() -> None:
    """Sem comentário, não sobra rastro de um campo vazio na mensagem."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa("prompt"))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.montar_prompt("cena", ["e: x"], "estilo", "m")

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "COMENTÁRIO" not in enviado


def teste_montar_prompt_inclui_contexto_do_livro_como_apoio() -> None:
    """O contexto do livro (item 4.4) vai como apoio, não como prioridade."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa("prompt"))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.montar_prompt(
        "O pátio ao anoitecer",
        ["Ned Stark: capa de pele"],
        "aquarela sombria",
        "m",
        contexto_do_livro="O capítulo confirma que é no pátio principal.",
    )

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "CONTEXTO DO LIVRO" in enviado
    assert "O capítulo confirma que é no pátio principal." in enviado


def teste_montar_prompt_com_frame_vazio_sinaliza_retrato() -> None:
    """Descrição vazia é como o frame do tipo PERSONAGEM pede um retrato solo."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa("prompt"))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.montar_prompt("", ["Ned Stark: capa de pele"], "aquarela", "m")

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "monte um retrato" in enviado


# --------------------------------------------------------------------------- #
# Leitura profunda de um elemento (item 4.4, fase 2)
# --------------------------------------------------------------------------- #


def teste_sugerir_estado_interpreta_o_json() -> None:
    resposta = json.dumps({"descricao": "Capa de pele, barba grisalha."})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_estado(
        texto_capitulo="texto do capítulo",
        tipo=TipoElemento.PERSONAGEM,
        nome="Ned Stark",
        descricao_do_elemento="Senhor de Winterfell.",
        estado_atual=None,
        modelo="algum/modelo",
    )

    assert sugestao.descricao == "Capa de pele, barba grisalha."
    assert sugestao.modelo == "algum/modelo"


def teste_sugerir_estado_manda_so_o_elemento_pedido() -> None:
    """A rota manda o nome do elemento e o texto do capítulo — nada mais."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(
            200, json=_resposta_de_conversa('{"descricao": "x"}')
        )

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.sugerir_estado(
        texto_capitulo="Ned estava ferido. Robb estava são.",
        tipo=TipoElemento.PERSONAGEM,
        nome="Ned Stark",
        descricao_do_elemento="Senhor de Winterfell.",
        estado_atual="Capa de pele.",
        modelo="m",
    )

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "Ned Stark" in enviado
    assert "Senhor de Winterfell." in enviado
    assert "Capa de pele." in enviado
    assert "Ned estava ferido. Robb estava são." in enviado


def teste_sugerir_estado_sem_json_levanta_erro() -> None:
    provedor = _provedor({"/chat/completions": _resposta_de_conversa("não é json")})

    with pytest.raises(ErroDoProvedorIA):
        provedor.sugerir_estado(
            texto_capitulo="t",
            tipo=TipoElemento.PERSONAGEM,
            nome="Ned",
            descricao_do_elemento=None,
            estado_atual=None,
            modelo="m",
        )


# --------------------------------------------------------------------------- #
# Fundamentação de um frame do tipo CENA (item 4.4)
# --------------------------------------------------------------------------- #


def teste_fundamentar_frame_interpreta_o_json() -> None:
    resposta = json.dumps({"contexto": "O capítulo confirma que a cena é na sala da guarda."})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    fundamentado = provedor.fundamentar_frame(
        texto_capitulo="texto do capítulo",
        titulo="A partida de Fundação",
        descricao="Vis e Hrolf jogam.",
        horario="início da noite",
        clima=None,
        humor=None,
        participantes=["Vis Solum: jovem magro"],
        modelo="algum/modelo",
    )

    assert fundamentado.contexto == "O capítulo confirma que a cena é na sala da guarda."
    assert fundamentado.modelo == "algum/modelo"


def teste_fundamentar_frame_manda_o_que_o_usuario_escreveu_e_os_participantes() -> None:
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa('{"contexto": "x"}'))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.fundamentar_frame(
        texto_capitulo="O texto do capítulo em si.",
        titulo="A partida de Fundação",
        descricao="Vis e Hrolf jogam uma partida.",
        horario="início da noite",
        clima="frio",
        humor="tenso",
        participantes=["Vis Solum: jovem magro", "Hrolf: velho grisalho"],
        modelo="m",
    )

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "A partida de Fundação" in enviado
    assert "Vis e Hrolf jogam uma partida." in enviado
    assert "início da noite" in enviado
    assert "Vis Solum: jovem magro" in enviado
    assert "Hrolf: velho grisalho" in enviado
    assert "O texto do capítulo em si." in enviado


def teste_fundamentar_frame_sem_json_levanta_erro() -> None:
    provedor = _provedor({"/chat/completions": _resposta_de_conversa("não é json")})

    with pytest.raises(ErroDoProvedorIA):
        provedor.fundamentar_frame(
            texto_capitulo="t",
            titulo="X",
            descricao=None,
            horario=None,
            clima=None,
            humor=None,
            participantes=[],
            modelo="m",
        )


# --------------------------------------------------------------------------- #
# Erros e pré-checagens
# --------------------------------------------------------------------------- #


def teste_sem_chave_a_conversa_falha_antes_de_chamar() -> None:
    """Gastar uma chamada para descobrir que não há chave seria desperdício."""
    provedor = _provedor({"/chat/completions": {}}, chave=None)

    with pytest.raises(ChaveDeApiAusente):
        provedor.extrair_elementos("t", [], "m")


def teste_sem_modelo_escolhido_a_conversa_falha() -> None:
    provedor = _provedor({"/chat/completions": {}})

    with pytest.raises(ModeloNaoEscolhido):
        provedor.extrair_elementos("t", [], "")


def teste_chave_recusada_pelo_openrouter_da_erro_claro() -> None:
    provedor = _provedor({"/chat/completions": httpx.Response(401, json={})})

    with pytest.raises(ChaveDeApiAusente) as erro:
        provedor.extrair_elementos("t", [], "m")

    assert "recusou a chave" in str(erro.value)


def teste_erro_http_do_openrouter_vira_erro_do_provedor() -> None:
    provedor = _provedor(
        {"/chat/completions": httpx.Response(429, text="rate limit exceeded")}
    )

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.extrair_elementos("t", [], "m")

    assert "429" in str(erro.value)
    assert "rate limit" in str(erro.value)


def teste_timeout_vira_mensagem_sobre_fila() -> None:
    """Modelos gratuitos ficam em fila; a mensagem precisa dizer isso."""
    provedor = _provedor(
        {"/chat/completions": httpx.TimeoutException("demorou")}
    )

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.extrair_elementos("t", [], "m")

    assert "fila" in str(erro.value)


def teste_resposta_em_formato_inesperado_vira_erro_do_provedor() -> None:
    provedor = _provedor({"/chat/completions": {"sem_choices": True}})

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.extrair_elementos("t", [], "m")

    assert "formato inesperado" in str(erro.value)


def teste_conferir_se_cabe_recusa_texto_grande_antes_de_chamar() -> None:
    """A checagem é prévia: descobrir depois seria ter gasto a chamada."""
    provedor = _provedor({})
    texto = "x" * 40_000  # cerca de 10 mil tokens

    with pytest.raises(TextoLongoDemais) as erro:
        provedor.conferir_se_cabe(texto, contexto_do_modelo=8_000)

    assert "32 mil" in str(erro.value)


def teste_conferir_se_cabe_aceita_texto_que_cabe() -> None:
    provedor = _provedor({})

    provedor.conferir_se_cabe("x" * 40_000, contexto_do_modelo=32_000)


def teste_estimativa_de_tokens() -> None:
    """Estimativa e não contagem: a decisão que ela alimenta tem folga."""
    assert estimar_tokens("x" * 4000) == 1000
    assert estimar_tokens("") == 0


# --------------------------------------------------------------------------- #
# Rotas de configuração
# --------------------------------------------------------------------------- #


def teste_configuracao_comeca_vazia(cliente: TestClient) -> None:
    """O sistema sobe sem configuração nenhuma, e a rota diz isso."""
    resposta = cliente.get("/configuracao")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["tem_chave_api"] is False
    assert corpo["origem_da_chave"] == "ausente"
    assert corpo["modelo_extracao"] is None
    assert corpo["prioridade_ia"] == "ECONOMIA"


def teste_gravar_prioridade_ia(cliente: TestClient) -> None:
    """Item 4.3 — controla a releitura da leitura profunda (item 4.4)."""
    resposta = cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    assert resposta.status_code == 200
    assert resposta.json()["prioridade_ia"] == "QUALIDADE"
    assert cliente.get("/configuracao").json()["prioridade_ia"] == "QUALIDADE"


def teste_gravar_chave_e_modelos(cliente: TestClient) -> None:
    resposta = cliente.put(
        "/configuracao",
        json={
            "chave_api_openrouter": "sk-de-teste",
            "modelo_extracao": "algum/modelo",
            "modelo_prompt": "outro/modelo",
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["tem_chave_api"] is True
    assert corpo["origem_da_chave"] == "banco"
    assert corpo["modelo_extracao"] == "algum/modelo"
    assert corpo["modelo_prompt"] == "outro/modelo"


def teste_a_chave_nunca_sai_na_resposta(cliente: TestClient) -> None:
    """Uma chave que sai do servidor vaza em log, em cache ou em captura de tela."""
    cliente.put("/configuracao", json={"chave_api_openrouter": "sk-secreta"})

    for resposta in (cliente.get("/configuracao"), cliente.put("/configuracao", json={})):
        assert "sk-secreta" not in resposta.text
        assert "chave_api_openrouter" not in resposta.json()


def teste_gravar_so_o_modelo_nao_apaga_a_chave(cliente: TestClient) -> None:
    """Só o que vem no corpo é aplicado."""
    cliente.put("/configuracao", json={"chave_api_openrouter": "sk-de-teste"})

    resposta = cliente.put("/configuracao", json={"modelo_extracao": "novo/modelo"})

    assert resposta.json()["tem_chave_api"] is True
    assert resposta.json()["modelo_extracao"] == "novo/modelo"


def teste_chave_vazia_apaga_o_cadastro(cliente: TestClient) -> None:
    """É assim que se desfaz um cadastro e devolve a vez à variável de ambiente."""
    cliente.put("/configuracao", json={"chave_api_openrouter": "sk-de-teste"})

    resposta = cliente.put("/configuracao", json={"chave_api_openrouter": ""})

    assert resposta.json()["tem_chave_api"] is False
    assert resposta.json()["origem_da_chave"] == "ausente"


def teste_chave_do_ambiente_e_usada_quando_o_banco_nao_tem(
    cliente: TestClient, monkeypatch
) -> None:
    """A variável de ambiente faz o sistema subir já configurado."""
    from imagineer import configuracao as modulo_de_configuracao

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-ambiente")
    try:
        resposta = cliente.get("/configuracao")
        assert resposta.json()["tem_chave_api"] is True
        assert resposta.json()["origem_da_chave"] == "ambiente"
        assert "sk-do-ambiente" not in resposta.text
    finally:
        obter.cache_clear()


def teste_chave_do_banco_tem_precedencia_sobre_o_ambiente(
    cliente: TestClient, monkeypatch
) -> None:
    """É a fonte que o usuário acabou de mexer, então é a que ele espera que valha."""
    from imagineer import configuracao as modulo_de_configuracao

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-ambiente")
    try:
        cliente.put("/configuracao", json={"chave_api_openrouter": "sk-do-banco"})
        assert cliente.get("/configuracao").json()["origem_da_chave"] == "banco"
    finally:
        obter.cache_clear()


def teste_chave_aceita_o_nome_alternativo_de_variavel_de_ambiente(
    cliente: TestClient, monkeypatch
) -> None:
    """IMAGINEER_KEY_OPEN_ROUTER também é aceito, além de CHAVE_API_OPENROUTER.

    Divergência registrada na Etapa 5: Allan já mantém uma variável de conta com
    esse nome, fora do projeto, e o sistema aceita as duas em vez de exigir que
    ele renomeie algo que já existe no ambiente dele.
    """
    from imagineer import configuracao as modulo_de_configuracao

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    # O conftest deixa CHAVE_API_OPENROUTER presente (vazia), para isolar os
    # testes do .env real — mas isso faria essa variável "ganhar" da alternativa
    # mesmo vazia, já que as duas passam a existir no ambiente. Removida aqui
    # para simular o caso real: só a variável de conta está definida.
    monkeypatch.delenv("CHAVE_API_OPENROUTER", raising=False)
    monkeypatch.setenv("IMAGINEER_KEY_OPEN_ROUTER", "sk-da-conta")
    try:
        resposta = cliente.get("/configuracao")
        assert resposta.json()["tem_chave_api"] is True
        assert resposta.json()["origem_da_chave"] == "ambiente"
        assert "sk-da-conta" not in resposta.text
    finally:
        obter.cache_clear()


# --------------------------------------------------------------------------- #
# Rota de listagem de modelos
# --------------------------------------------------------------------------- #


def teste_listar_modelos_filtra_gratuitos_e_contexto(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Os dois filtros que a tela de escolha precisa."""
    usar_provedor_falso(ProvedorFalso())

    todos = cliente.get("/configuracao/modelos").json()
    assert len(todos) == 2

    grandes = cliente.get("/configuracao/modelos", params={"contexto_minimo": 32000}).json()
    assert [m["id"] for m in grandes] == [MODELO_FALSO]

    gratuitos = cliente.get(
        "/configuracao/modelos", params={"somente_gratuitos": True}
    ).json()
    assert len(gratuitos) == 2


def teste_falha_do_openrouter_na_listagem_responde_502(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O problema não é do pedido nem nosso: é do serviço de fora."""
    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("o serviço caiu")))

    resposta = cliente.get("/configuracao/modelos")

    assert resposta.status_code == 502
    assert "o serviço caiu" in resposta.json()["detail"]


# --------------------------------------------------------------------------- #
# Provedor falso
# --------------------------------------------------------------------------- #


def teste_provedor_falso_registra_o_que_foi_pedido() -> None:
    """Afirmar **o que** foi mandado ao modelo é metade do que importa."""
    provedor = ProvedorFalso(
        elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
    )

    extracao = provedor.extrair_elementos("o texto", ["Jon: manto"], MODELO_FALSO)

    assert [e.nome for e in extracao.elementos] == ["Jon"]
    assert provedor.chamadas_de_extracao == [
        {
            "texto_capitulo": "o texto",
            "estados_conhecidos": ["Jon: manto"],
            "modelo": MODELO_FALSO,
        }
    ]


def teste_modelo_que_produz_audio_fica_fora_da_lista() -> None:
    """Produzir texto não basta: o modelo tem que produzir SÓ texto.

    Caso real, achado numa chamada de verdade ao OpenRouter:
    ``google/lyria-3-pro-preview`` é um modelo de música que declara
    ``output_modalities: ["text", "audio"]``. Passava pelo filtro antigo, que só
    checava se texto estava entre as saídas.
    """
    provedor = _provedor(
        {
            "/models": {
                "data": [
                    {
                        "id": "google/lyria-3-pro-preview",
                        "pricing": {"prompt": "0"},
                        "architecture": {
                            "input_modalities": ["text", "image"],
                            "output_modalities": ["text", "audio"],
                        },
                    },
                    {
                        "id": "multimodal/que-serve",
                        "pricing": {"prompt": "0"},
                        "architecture": {
                            # Entrada com imagem e vídeo não atrapalha: um modelo
                            # multimodal continua sabendo ler um capítulo.
                            "input_modalities": ["text", "image", "video"],
                            "output_modalities": ["text"],
                        },
                    },
                ]
            }
        }
    )

    assert [m.id for m in provedor.listar_modelos()] == ["multimodal/que-serve"]
