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
from imagineer.modelos import CategoriaEstilo, TipoElemento


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


def teste_listar_modelos_le_suporte_a_json_custo_e_moderacao() -> None:
    """Os três campos do item 4.3, com os nomes confirmados ao vivo contra o
    /models real antes de implementar o filtro: `supported_parameters`,
    `pricing.completion` e `top_provider.is_moderated`."""
    provedor = _provedor(
        {
            "/models": {
                "data": [
                    {
                        "id": "com/tudo",
                        "context_length": 128000,
                        "pricing": {"prompt": "0.000002", "completion": "0.00001"},
                        "supported_parameters": ["response_format", "structured_outputs"],
                        "top_provider": {"is_moderated": True},
                    },
                    {
                        "id": "sem/nada",
                        "context_length": 32000,
                        "pricing": {"prompt": "0", "completion": "0"},
                        "supported_parameters": ["temperature"],
                        "top_provider": {"is_moderated": False},
                    },
                ]
            }
        }
    )

    modelos = {m.id: m for m in provedor.listar_modelos()}

    assert modelos["com/tudo"].suporta_json is True
    assert modelos["com/tudo"].custo_saida == 0.00001
    assert modelos["com/tudo"].moderado is True

    assert modelos["sem/nada"].suporta_json is False
    assert modelos["sem/nada"].custo_saida == 0.0
    assert modelos["sem/nada"].moderado is False


def teste_listar_modelos_sem_os_campos_novos_usa_padroes_seguros() -> None:
    """Um modelo sem esses campos (API mudou, ou faltou na resposta) não
    deveria quebrar a listagem — só ficar com os valores mais conservadores."""
    provedor = _provedor({"/models": {"data": [{"id": "so/o-basico"}]}})

    modelo = provedor.listar_modelos()[0]

    assert modelo.suporta_json is False
    assert modelo.custo_saida == 0.0
    assert modelo.moderado is False


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

    assert len(extracao.cenas) == 1
    cena = extracao.cenas[0]
    assert cena.titulo == "A execução"
    assert cena.horario == "manhã"
    assert [p.nome for p in cena.participantes] == ["Ned Stark", "Gelo"]
    assert cena.participantes[1].tipo is TipoElemento.OBJETO


def teste_extrair_elementos_le_o_trecho_ancora_da_cena_e_trata_o_que_nao_e_texto_como_nulo() -> None:
    """A citação do começo do momento (item 3.4g): presente, ausente, 'null' e não-texto."""
    participantes = [{"tipo": "PERSONAGEM", "nome": "Ned"}]
    resposta = json.dumps(
        {
            "elementos": [{"tipo": "PERSONAGEM", "nome": "Ned"}],
            "cenas": [
                {"titulo": "A", "participantes": participantes, "trecho_ancora": "  Ned ergueu a espada.  "},
                {"titulo": "B", "participantes": participantes},
                {"titulo": "C", "participantes": participantes, "trecho_ancora": "null"},
                {"titulo": "D", "participantes": participantes, "trecho_ancora": 42},
            ],
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    cenas = provedor.extrair_elementos("t", [], "m").cenas

    assert [c.trecho_ancora for c in cenas] == ["Ned ergueu a espada.", None, None, None]


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

    cenas = provedor.extrair_elementos("t", [], "m").cenas

    assert [c.titulo for c in cenas] == ["Cena boa"]


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


def teste_a_instrucao_do_prompt_manda_ser_fiel_ao_autor_inclusive_no_que_e_delicado() -> None:
    """02/10: a IA do prompt omitia "nude" por conta própria (1 de 8 gerações o descrevia, com o estado dizendo
    "Auri está nua"). A suavização é outra etapa, só se o provedor recusar: aqui vale a fidelidade."""
    capturado: dict = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(pedido.content))
        return httpx.Response(200, json=_resposta_de_conversa("close-up, Auri, nude"))

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    ProvedorOpenRouter(chave_api="chave", cliente=cliente).montar_prompt(
        "", ["Auri: Auri está nua."], "estilo: pintura a óleo", "modelo/x"
    )

    instrucao = " ".join(capturado["messages"][0]["content"].split())
    assert "Fidelidade ao autor, inclusive no que é delicado" in instrucao
    assert 'Se a pessoa está nua, escreva que está nua ("nude")' in instrucao
    assert "nunca omita, atenue ou troque por conta própria nudez, violência" in instrucao
    assert "só se o provedor de imagem recusar o prompt" in instrucao  # a suavização é outra etapa
    assert "não invente nenhuma" in instrucao  # fidelidade vale nos dois sentidos: nada a mais


def _instrucao_enviada(chamar) -> str:
    """Roda `chamar(provedor)` contra um transporte falso e devolve a instrução (mensagem de sistema) enviada."""
    capturado: dict = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(pedido.content))
        return httpx.Response(200, json=_resposta_de_conversa('{"descricao": "x"}'))

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    chamar(ProvedorOpenRouter(chave_api="chave", cliente=cliente))
    return " ".join(capturado["messages"][0]["content"].split())


def teste_a_instrucao_do_estado_exige_expressao_e_postura() -> None:
    """02/10 (X1): o estado da Auri saiu sem sorriso nem pose e o retrato perdeu a alegria."""
    instrucao = _instrucao_enviada(
        lambda p: p.sugerir_estado("texto", TipoElemento.PERSONAGEM, "Auri", None, None, "modelo/x")
    )

    assert "Expressão e postura NUNCA ficam de fora" in instrucao
    assert "expressão do rosto (sorriso, olhar, tensão)" in instrucao
    assert "o humor que se vê" in instrucao
    assert "pobre demais para virar imagem" in instrucao


def teste_a_instrucao_do_prompt_poe_o_clima_da_cena_acima_do_do_perfil() -> None:
    """02/10 (X2): o clima "introspectivo" do perfil estava vencendo a alegria da cena."""
    instrucao = _instrucao_enviada(lambda p: p.montar_prompt("", ["Auri: sorri"], "estilo: x", "modelo/x"))

    assert "O clima emocional vem da cena, não do perfil de estilo" in instrucao
    assert "NÃO pode soar contemplativo, triste ou melancólico" in instrucao
    assert "Do perfil use só a técnica" in instrucao
    assert 'só no bloco final de estética, traduzidas literalmente, e nunca na prosa da cena' in instrucao


def teste_a_instrucao_do_estado_manda_descrever_so_o_primeiro_instante() -> None:
    """02/10 (Y1): o estado juntava a Auri vestida e nua; só traços permanentes vêm dos outros momentos."""
    instrucao = _instrucao_enviada(
        lambda p: p.sugerir_estado("texto", TipoElemento.PERSONAGEM, "Auri", None, None, "modelo/x")
    )

    assert "UM SÓ INSTANTE, o PRIMEIRO em que o elemento aparece no capítulo" in instrucao
    assert "sem misturar com os seguintes" in instrucao
    # A1/A2: os traços permanentes têm parte própria, que pode vir de qualquer ponto do capítulo.
    assert "Pode vir de QUALQUER ponto do capítulo" in instrucao
    assert "Nunca roupa, pose, humor" in instrucao


def teste_a_instrucao_do_prompt_manda_escolher_um_instante_e_nao_misturar() -> None:
    """02/10 (Y2): "completely nude... soft dress texture" juntava dois momentos no mesmo prompt."""
    instrucao = _instrucao_enviada(lambda p: p.montar_prompt("", ["Auri: x"], "estilo: x", "modelo/x"))

    assert "Um só instante" in instrucao
    assert "numa cena, o que a descrição da cena indica" in instrucao
    assert 'num retrato (sem cena), a roupa e o penteado do "Neste instante:"' in instrucao  # P2: a pose do retrato é sempre neutra
    assert "NUNCA roupa ou pose que contradigam o instante escolhido" in instrucao
    assert '"nude" com roupa' in instrucao
    assert "comentário do usuário, se houver, pode indicar outro momento e vale mais que esta regra" in instrucao


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


def teste_a_instrucao_do_estado_pede_aparencia_fixa_instante_e_ambiente() -> None:
    """02/10 (A1 a A4): o retrato perdeu a aparência fixa e saía com um fundo qualquer."""
    instrucao = _instrucao_enviada(
        lambda p: p.sugerir_estado("texto", TipoElemento.PERSONAGEM, "Auri", None, None, "modelo/x")
    )

    for campo in ('"aparencia_fixa"', '"instante"', '"ambiente"'):
        assert campo in instrucao
    assert "um sujeito em primeiro plano com um fundo qualquer quebra a imagem" in instrucao
    assert "devolva null em vez de inventar um cenário" in instrucao
    assert 'nada de "depois", "mais tarde", "em seguida", "finalmente"' in instrucao


def teste_a_instrucao_do_prompt_usa_o_ambiente_no_retrato() -> None:
    """02/10 (A5, A6): num retrato o cenário vem do "Onde está:"; numa cena, da descrição da cena."""
    instrucao = _instrucao_enviada(lambda p: p.montar_prompt("", ["Auri: x"], "estilo: x", "modelo/x"))

    assert '"Aparência fixa:" (traços que não mudam: sempre entram no prompt' in instrucao
    assert 'num retrato, os do "Onde está:" do elemento' in instrucao
    assert "nunca um fundo genérico ou neutro" in instrucao
    assert 'Numa cena, o cenário é o da descrição da cena' in instrucao
    assert "pule num retrato" not in instrucao and "só se houver cena — num retrato, pule" not in instrucao


def teste_sugerir_estado_junta_as_tres_partes_com_rotulos() -> None:
    resposta = json.dumps(
        {
            "aparencia_fixa": "Mulher jovem, pequena e esguia, pele pálida, cabelo dourado e longo.",
            "instante": "De camisola, sorri e ergue os braços.",
            "ambiente": "Quarto de pedra com uma nesga de luz na janela.",
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_estado("texto", TipoElemento.PERSONAGEM, "Auri", None, None, "algum/modelo")

    assert sugestao.descricao == (
        "Aparência fixa: Mulher jovem, pequena e esguia, pele pálida, cabelo dourado e longo.\n"
        "Neste instante: De camisola, sorri e ergue os braços.\n"
        "Onde está: Quarto de pedra com uma nesga de luz na janela."
    )


def teste_sugerir_estado_sem_ambiente_nao_poe_o_rotulo() -> None:
    """Texto que não diz onde o elemento está: a parte do ambiente some, nada é inventado (A4)."""
    resposta = json.dumps({"aparencia_fixa": "Barba grisalha.", "instante": "De pé.", "ambiente": None})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_estado("texto", TipoElemento.PERSONAGEM, "Ned", None, None, "algum/modelo")

    assert "Onde está" not in sugestao.descricao
    assert sugestao.descricao == "Aparência fixa: Barba grisalha.\nNeste instante: De pé."


def teste_sugerir_estado_aceita_o_formato_antigo_de_um_campo() -> None:
    """A7: resposta só com `descricao` continua valendo."""
    resposta = json.dumps({"descricao": "Capa de pele.", "ambiente": "Um salão de pedra."})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_estado("texto", TipoElemento.PERSONAGEM, "Ned", None, None, "algum/modelo")

    assert sugestao.descricao == "Capa de pele.\nOnde está: Um salão de pedra."


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
# Leitura profunda de identidade — fase 2b (item 4.4/3.4f)
# --------------------------------------------------------------------------- #


def teste_sugerir_identidade_interpreta_o_json() -> None:
    resposta = json.dumps({"descricao": "É filho adotivo, não de sangue."})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_identidade(
        texto_capitulo="texto do capítulo",
        tipo=TipoElemento.PERSONAGEM,
        nome="Vis",
        identidade_vigente="Um jovem aprendiz de ferreiro.",
        modelo="algum/modelo",
    )

    assert sugestao.descricao == "É filho adotivo, não de sangue."
    assert sugestao.modelo == "algum/modelo"


def teste_sugerir_identidade_null_vira_nenhum_incremento() -> None:
    """O caso comum: nada de novo no capítulo. `null` é uma resposta válida,
    diferente de `sugerir_estado`, onde a ausência de descrição é erro."""
    resposta = json.dumps({"descricao": None})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_identidade(
        texto_capitulo="t",
        tipo=TipoElemento.PERSONAGEM,
        nome="Vis",
        identidade_vigente=None,
        modelo="m",
    )

    assert sugestao.descricao is None


def teste_sugerir_identidade_manda_a_identidade_vigente_e_o_capitulo() -> None:
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=_resposta_de_conversa('{"descricao": null}'))

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)),
    )

    provedor.sugerir_identidade(
        texto_capitulo="Vis descobre que é filho adotivo.",
        tipo=TipoElemento.PERSONAGEM,
        nome="Vis",
        identidade_vigente="Um jovem aprendiz de ferreiro.",
        modelo="m",
    )

    enviado = capturado["corpo"]["messages"][1]["content"]
    assert "Vis" in enviado
    assert "Um jovem aprendiz de ferreiro." in enviado
    assert "Vis descobre que é filho adotivo." in enviado


def teste_sugerir_identidade_sem_json_levanta_erro() -> None:
    provedor = _provedor({"/chat/completions": _resposta_de_conversa("não é json")})

    with pytest.raises(ErroDoProvedorIA):
        provedor.sugerir_identidade(
            texto_capitulo="t",
            tipo=TipoElemento.PERSONAGEM,
            nome="Vis",
            identidade_vigente=None,
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
# Sugestão de perfil de renderização (rascunho, pendência da Etapa 8)
# --------------------------------------------------------------------------- #


def teste_sugerir_perfil_interpreta_o_json() -> None:
    resposta = json.dumps(
        {
            "estilo": "aquarela sombria",
            "artista_referencia": "Alan Lee",
            "iluminacao": "luz de vela",
            "paleta": "tons terrosos",
            "formato": "retrato",
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_perfil_renderizacao(
        titulo="O Senhor dos Anéis",
        autor="J.R.R. Tolkien",
        idioma="pt-BR",
        categoria_estilo=None,
        modelo="algum/modelo",
    )

    assert sugestao.estilo == "aquarela sombria"
    assert sugestao.artista_referencia == "Alan Lee"
    assert sugestao.modelo == "algum/modelo"
    assert sugestao.reconheceu_a_obra is True


def teste_sugerir_perfil_nao_reconhecer_a_obra_fica_explicito() -> None:
    """Item 6.5: `reconheceu_a_obra=False` distingue "não sei que livro é
    este" de "reconheci, mas não sei um artista de referência específico"."""
    resposta = json.dumps(
        {
            "reconheceu_a_obra": False,
            "estilo": None,
            "artista_referencia": None,
            "iluminacao": None,
            "paleta": None,
            "formato": None,
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_perfil_renderizacao(
        titulo="Título genérico sem autor",
        autor=None,
        idioma=None,
        categoria_estilo=None,
        modelo="m",
    )

    assert sugestao.reconheceu_a_obra is False
    assert sugestao.estilo is None


def teste_sugerir_perfil_sem_o_campo_conta_como_reconhecida() -> None:
    """Ausência do campo (modelo antigo, ou ignorou parte da instrução) não
    deveria gerar um falso aviso de "não reconheci" — só `false` explícito conta."""
    resposta = json.dumps({"estilo": "aquarela sombria"})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_perfil_renderizacao(
        titulo="X", autor=None, idioma=None, categoria_estilo=None, modelo="m"
    )

    assert sugestao.reconheceu_a_obra is True


def teste_sugerir_perfil_usa_a_categoria_devolvida_pelo_modelo() -> None:
    """Sem categoria escolhida pelo usuário, a IA escolhe uma sozinha."""
    resposta = json.dumps({"estilo": "x", "categoria_estilo": "PINTURA_A_OLEO"})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_perfil_renderizacao(
        titulo="X", autor=None, idioma=None, categoria_estilo=None, modelo="m"
    )

    assert sugestao.categoria_estilo == CategoriaEstilo.PINTURA_A_OLEO


def teste_sugerir_perfil_categoria_pedida_prevalece_se_modelo_nao_confirmar() -> None:
    """Se o modelo não devolver `categoria_estilo` (ou devolver algo inválido),
    cai na categoria que o usuário pediu — nunca fica perdido."""
    resposta = json.dumps({"estilo": "x"})
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_perfil_renderizacao(
        titulo="X",
        autor=None,
        idioma=None,
        categoria_estilo=CategoriaEstilo.CARTOON_ANIMACAO,
        modelo="m",
    )

    assert sugestao.categoria_estilo == CategoriaEstilo.CARTOON_ANIMACAO


def teste_sugerir_perfil_trata_a_palavra_nulo_como_ausencia() -> None:
    """Achado testando com `perplexity/sonar-pro`: às vezes o modelo escreve a
    palavra "nulo" como texto em vez de usar `null` de verdade no JSON."""
    resposta = json.dumps(
        {
            "estilo": "realismo sombrio",
            "artista_referencia": "nulo",
            "iluminacao": "NULL",
            "paleta": "Não informado",
            "formato": "retrato",
        }
    )
    provedor = _provedor({"/chat/completions": _resposta_de_conversa(resposta)})

    sugestao = provedor.sugerir_perfil_renderizacao(
        titulo="Um livro qualquer", autor=None, idioma=None, categoria_estilo=None, modelo="m"
    )

    assert sugestao.artista_referencia is None
    assert sugestao.iluminacao is None
    assert sugestao.paleta is None
    assert sugestao.estilo == "realismo sombrio"


def teste_sugerir_perfil_manda_os_metadados_e_liga_a_busca_web() -> None:
    """É a única operação desta classe que liga o plugin de busca do
    OpenRouter — não manda nenhum texto do livro, só os metadados."""
    capturado = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado["corpo"] = json.loads(pedido.content)
        return httpx.Response(
            200, json=_resposta_de_conversa('{"estilo": "x"}')
        )

    provedor = ProvedorOpenRouter(
        chave_api="k",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)
        ),
    )

    provedor.sugerir_perfil_renderizacao(
        titulo="A Vontade de Muitos",
        autor="James Islington",
        idioma="pt-BR",
        categoria_estilo=CategoriaEstilo.FOTORREALISTA_CINEMATOGRAFICO,
        modelo="m",
    )

    corpo = capturado["corpo"]
    assert corpo["plugins"] == [{"id": "web"}]
    enviado = corpo["messages"][1]["content"]
    assert "A Vontade de Muitos" in enviado
    assert "James Islington" in enviado
    assert "FOTORREALISTA_CINEMATOGRAFICO" in enviado


def teste_sugerir_perfil_sem_json_levanta_erro() -> None:
    provedor = _provedor({"/chat/completions": _resposta_de_conversa("não é json")})

    with pytest.raises(ErroDoProvedorIA):
        provedor.sugerir_perfil_renderizacao(
            titulo="X", autor=None, idioma=None, categoria_estilo=None, modelo="m"
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


def teste_modelo_de_imagem_nasce_com_o_padrao_e_o_de_suavizacao_vazio(cliente: TestClient) -> None:
    """Incremento 12: a imagem já tem modelo (`meta/muse-image`) sem ninguém configurar nada."""
    corpo = cliente.get("/configuracao").json()

    assert corpo["modelo_imagem"] == "meta/muse-image"
    assert corpo["modelo_suavizacao"] is None


def teste_gravar_modelo_de_imagem_e_de_suavizacao(cliente: TestClient) -> None:
    resposta = cliente.put(
        "/configuracao",
        json={"modelo_imagem": "black-forest-labs/flux.2-klein-4b", "modelo_suavizacao": "barato/modelo"},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["modelo_imagem"] == "black-forest-labs/flux.2-klein-4b"
    assert corpo["modelo_suavizacao"] == "barato/modelo"
    assert cliente.get("/configuracao").json()["modelo_imagem"] == "black-forest-labs/flux.2-klein-4b"


def teste_modelo_de_imagem_nao_pode_ficar_vazio(cliente: TestClient) -> None:
    """Sem modelo de imagem a geração não tem o que chamar: recusa (422) e mantém o valor."""
    for vazio in ("", "   ", None):
        resposta = cliente.put("/configuracao", json={"modelo_imagem": vazio})

        assert resposta.status_code == 422, vazio
    assert cliente.get("/configuracao").json()["modelo_imagem"] == "meta/muse-image"


def teste_modelo_de_suavizacao_pode_voltar_a_vazio(cliente: TestClient) -> None:
    """Vazio = "usa o modelo_prompt" (S6); apagar é desfazer a escolha."""
    cliente.put("/configuracao", json={"modelo_suavizacao": "barato/modelo"})

    resposta = cliente.put("/configuracao", json={"modelo_suavizacao": ""})

    assert resposta.json()["modelo_suavizacao"] is None


def teste_gravar_um_modelo_de_texto_nao_mexe_no_de_imagem(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelo_imagem": "outro/modelo-de-imagem"})

    resposta = cliente.put("/configuracao", json={"modelo_prompt": "um/modelo"})

    assert resposta.json()["modelo_imagem"] == "outro/modelo-de-imagem"


def teste_gravar_prioridade_ia(cliente: TestClient) -> None:
    """Item 4.3 — controla a releitura da leitura profunda (item 4.4)."""
    resposta = cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    assert resposta.status_code == 200
    assert resposta.json()["prioridade_ia"] == "QUALIDADE"
    assert cliente.get("/configuracao").json()["prioridade_ia"] == "QUALIDADE"


def teste_gravar_modelos(cliente: TestClient) -> None:
    resposta = cliente.put(
        "/configuracao",
        json={
            "modelo_extracao": "algum/modelo",
            "modelo_prompt": "outro/modelo",
            "modelo_perfil": "terceiro/modelo",
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["modelo_extracao"] == "algum/modelo"
    assert corpo["modelo_prompt"] == "outro/modelo"
    assert corpo["modelo_perfil"] == "terceiro/modelo"


def teste_modelo_perfil_e_independente_do_modelo_de_extracao(cliente: TestClient) -> None:
    """Item 6.5: a sugestão de perfil é uma chamada única por livro, então
    compensa escolher um modelo diferente (normalmente mais caro) do usado
    para extrair elementos a cada capítulo."""
    cliente.put("/configuracao", json={"modelo_extracao": "barato/modelo"})

    resposta = cliente.put("/configuracao", json={"modelo_perfil": "caro/modelo"})

    corpo = resposta.json()
    assert corpo["modelo_extracao"] == "barato/modelo"
    assert corpo["modelo_perfil"] == "caro/modelo"


def teste_put_recusa_o_campo_antigo_da_chave(cliente: TestClient) -> None:
    """Item 4.3: a chave não passa mais por aqui. Recusar (422) em vez de
    ignorar em silêncio — senão o usuário acharia que a chave foi salva."""
    resposta = cliente.put("/configuracao", json={"chave_api_openrouter": "sk-secreta"})

    assert resposta.status_code == 422
    # E nada foi gravado: a configuração continua sem chave.
    assert cliente.get("/configuracao").json()["tem_chave_api"] is False


def teste_a_chave_do_ambiente_nunca_sai_na_resposta(
    cliente: TestClient, monkeypatch
) -> None:
    """Uma chave que sai do servidor vaza em log, em cache ou em captura de tela."""
    from imagineer import configuracao as modulo_de_configuracao

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-secreta")
    try:
        for resposta in (
            cliente.get("/configuracao"),
            cliente.put("/configuracao", json={}),
        ):
            assert "sk-secreta" not in resposta.text
            assert "chave_api_openrouter" not in resposta.json()
    finally:
        obter.cache_clear()


def teste_gravar_so_um_modelo_nao_apaga_os_outros(cliente: TestClient) -> None:
    """Só o que vem no corpo é aplicado."""
    cliente.put("/configuracao", json={"modelo_prompt": "um/modelo"})

    resposta = cliente.put("/configuracao", json={"modelo_extracao": "novo/modelo"})

    assert resposta.json()["modelo_prompt"] == "um/modelo"
    assert resposta.json()["modelo_extracao"] == "novo/modelo"


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


def teste_chave_do_fal_aceita_a_variavel_de_conta(cliente: TestClient, monkeypatch) -> None:
    """IMAGINEER_KEY_FAL_AI (variável de conta do Allan) vale como chave do fal.ai, sem revelar o valor."""
    from imagineer import configuracao as modulo_de_configuracao

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.delenv("FAL_KEY", raising=False)  # o conftest a deixa vazia, e a vazia ganharia da alternativa
    monkeypatch.delenv("CHAVE_API_FAL", raising=False)
    monkeypatch.setenv("IMAGINEER_KEY_FAL_AI", "chave-do-fal")
    try:
        resposta = cliente.get("/configuracao")
        assert resposta.json()["fornecedores_de_imagem"]["fal"] is True
        assert "chave-do-fal" not in resposta.text
    finally:
        obter.cache_clear()


def teste_chave_do_replicate_aceita_a_variavel_de_conta(cliente: TestClient, monkeypatch) -> None:
    """IMAGINEER_KEY_REPLICATE (variável de conta do Allan) vale como chave do Replicate."""
    from imagineer import configuracao as modulo_de_configuracao

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    monkeypatch.delenv("CHAVE_API_REPLICATE", raising=False)
    monkeypatch.setenv("IMAGINEER_KEY_REPLICATE", "chave-do-replicate")
    try:
        resposta = cliente.get("/configuracao")
        assert resposta.json()["fornecedores_de_imagem"]["replicate"] is True
        assert "chave-do-replicate" not in resposta.text
    finally:
        obter.cache_clear()


# --------------------------------------------------------------------------- #
# Chave por header (item 4.3)
# --------------------------------------------------------------------------- #


def teste_o_header_tem_precedencia_sobre_o_ambiente(monkeypatch) -> None:
    """A chave pessoal de quem usa o app vale mais que a chave do servidor."""
    from imagineer import configuracao as modulo_de_configuracao
    from imagineer.servicos.configuracao_ia import resolver_chave

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-ambiente")
    try:
        chave = resolver_chave("sk-do-header")
        assert chave.valor == "sk-do-header"
        assert chave.origem == "cabecalho"
    finally:
        obter.cache_clear()


def teste_sem_header_vale_o_ambiente(monkeypatch) -> None:
    from imagineer import configuracao as modulo_de_configuracao
    from imagineer.servicos.configuracao_ia import resolver_chave

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-ambiente")
    try:
        chave = resolver_chave(None)
        assert chave.valor == "sk-do-ambiente"
        assert chave.origem == "ambiente"
    finally:
        obter.cache_clear()


def teste_header_vazio_ou_so_espacos_conta_como_ausente(monkeypatch) -> None:
    """Um app que manda o header sempre, mesmo sem chave própria, não quebra."""
    from imagineer import configuracao as modulo_de_configuracao
    from imagineer.servicos.configuracao_ia import resolver_chave

    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-ambiente")
    try:
        for vazio in ("", "   ", None):
            assert resolver_chave(vazio).origem == "ambiente"
    finally:
        obter.cache_clear()


def teste_sem_nenhuma_chave_a_origem_e_ausente() -> None:
    from imagineer.servicos.configuracao_ia import resolver_chave

    chave = resolver_chave(None)

    assert chave.valor is None
    assert chave.origem == "ausente"


def teste_a_rota_repassa_o_header_para_o_provedor(
    cliente: TestClient, monkeypatch
) -> None:
    """O nome do header e a ligação com ``obter_provedor`` — o que os testes
    acima (só a função de resolução) não pegam, como um erro de digitação no
    nome do header."""
    from imagineer.ia.falso import ProvedorFalso
    from imagineer.rotas import configuracao as rota

    recebidos: list[str | None] = []

    def falso(cabecalho: str | None = None, usuario=None, chave_fal=None, chave_replicate=None) -> ProvedorFalso:
        recebidos.append(cabecalho)
        return ProvedorFalso()

    monkeypatch.setattr(rota, "construir_provedor", falso)

    cliente.get("/configuracao/modelos", headers={"X-Chave-API-OpenRouter": "sk-do-app"})
    cliente.get("/configuracao/modelos")

    assert recebidos == ["sk-do-app", None]


def teste_get_configuracao_ignora_o_header(cliente: TestClient) -> None:
    """``GET /configuracao`` só diz o que o *servidor* tem, e nunca ecoa o header."""
    resposta = cliente.get(
        "/configuracao", headers={"X-Chave-API-OpenRouter": "sk-do-app"}
    )

    assert resposta.json()["tem_chave_api"] is False
    assert resposta.json()["origem_da_chave"] == "ausente"
    assert "sk-do-app" not in resposta.text


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


def teste_listar_modelos_filtra_json_moderacao_e_ordena_por_custo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Os três filtros do item 4.3, confirmados contra o /models real antes
    de implementar: suporta_json, moderado e ordenação por custo_saida."""
    from imagineer.ia.provedor import ModeloDisponivel

    usar_provedor_falso(
        ProvedorFalso(
            modelos=[
                ModeloDisponivel(
                    id="caro/sem-json",
                    nome="Caro sem JSON",
                    contexto=128_000,
                    gratuito=False,
                    suporta_json=False,
                    custo_saida=0.01,
                    moderado=True,
                ),
                ModeloDisponivel(
                    id="barato/com-json",
                    nome="Barato com JSON",
                    contexto=128_000,
                    gratuito=True,
                    suporta_json=True,
                    custo_saida=0.0,
                    moderado=False,
                ),
            ]
        )
    )

    todos = cliente.get("/configuracao/modelos").json()
    assert {m["id"] for m in todos} == {"caro/sem-json", "barato/com-json"}
    assert all("suporta_json" in m and "custo_saida" in m and "moderado" in m for m in todos)

    com_json = cliente.get(
        "/configuracao/modelos", params={"somente_com_json": True}
    ).json()
    assert [m["id"] for m in com_json] == ["barato/com-json"]

    nao_moderados = cliente.get(
        "/configuracao/modelos", params={"somente_nao_moderados": True}
    ).json()
    assert [m["id"] for m in nao_moderados] == ["barato/com-json"]

    ordenados = cliente.get(
        "/configuracao/modelos", params={"ordenar_por_custo": True}
    ).json()
    assert [m["id"] for m in ordenados] == ["barato/com-json", "caro/sem-json"]


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
            "elementos_conhecidos": ["Jon: manto"],
            "modelo": MODELO_FALSO,
            "orientacao": None,
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


# --------------------------------------------------------------------------- #
# Lista de modelos de imagem (item 7.5b, Z2)
# --------------------------------------------------------------------------- #


def teste_modelos_de_imagem_nasce_com_a_lista_padrao(cliente: TestClient) -> None:
    corpo = cliente.get("/configuracao").json()

    assert corpo["modelos_de_imagem"] == [
        "meta/muse-image",
        "bytedance-seed/seedream-5-0-flash",
        "google/gemini-2.5-flash-image",
    ]
    assert corpo["modelo_imagem"] in corpo["modelos_de_imagem"]  # o padrão está na lista


def teste_gravar_modelos_de_imagem_normaliza_a_lista(cliente: TestClient) -> None:
    """Sem espaços nas pontas, sem itens vazios nem repetidos, na ordem em que vieram."""
    resposta = cliente.put(
        "/configuracao",
        json={"modelos_de_imagem": [" recraft/recraft-v4.1 ", "", "   ", "qwen/qwen-image-3", "recraft/recraft-v4.1"]},
    )

    assert resposta.status_code == 200
    esperado = ["recraft/recraft-v4.1", "qwen/qwen-image-3"]
    assert resposta.json()["modelos_de_imagem"] == esperado
    assert cliente.get("/configuracao").json()["modelos_de_imagem"] == esperado


def teste_modelos_de_imagem_pode_ficar_vazia_e_o_padrao_continua(cliente: TestClient) -> None:
    corpo = cliente.put("/configuracao", json={"modelos_de_imagem": []}).json()

    assert corpo["modelos_de_imagem"] == []
    assert corpo["modelo_imagem"] == "meta/muse-image"  # o padrão não depende da lista


def teste_modelos_de_imagem_recusa_lista_grande_demais_e_item_longo_demais(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"modelos_de_imagem": [f"m/{i}" for i in range(21)]}).status_code == 422
    assert cliente.put("/configuracao", json={"modelos_de_imagem": ["x" * 201]}).status_code == 422
    assert cliente.put("/configuracao", json={"modelos_de_imagem": [f"m/{i}" for i in range(20)]}).status_code == 200


def teste_modelos_sem_filtro_nasce_vazia(cliente: TestClient) -> None:
    """F13: nenhum modelo permite desligar o filtro até o usuário incluí-lo."""
    assert cliente.get("/configuracao").json()["modelos_sem_filtro"] == []


def teste_gravar_modelos_sem_filtro_normaliza_a_lista_e_nao_mexe_na_de_imagem(cliente: TestClient) -> None:
    resposta = cliente.put(
        "/configuracao",
        json={"modelos_sem_filtro": [" replicate:black-forest-labs/flux-schnell ", "", "replicate:black-forest-labs/flux-schnell"]},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["modelos_sem_filtro"] == ["replicate:black-forest-labs/flux-schnell"]
    assert corpo["modelos_de_imagem"] != corpo["modelos_sem_filtro"]  # são listas separadas
    assert cliente.get("/configuracao").json()["modelos_sem_filtro"] == ["replicate:black-forest-labs/flux-schnell"]


def teste_modelos_sem_filtro_recusa_lista_grande_demais_e_item_longo_demais(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"modelos_sem_filtro": [f"m/{i}" for i in range(21)]}).status_code == 422
    assert cliente.put("/configuracao", json={"modelos_sem_filtro": ["x" * 201]}).status_code == 422


def teste_gravar_outro_campo_nao_mexe_na_lista_de_modelos_sem_filtro(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelos_sem_filtro": ["replicate:um/modelo"]})

    resposta = cliente.put("/configuracao", json={"modelo_prompt": "um/modelo"})

    assert resposta.json()["modelos_sem_filtro"] == ["replicate:um/modelo"]


def teste_gravar_outro_campo_nao_mexe_na_lista_de_modelos_de_imagem(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelos_de_imagem": ["so/este"]})

    resposta = cliente.put("/configuracao", json={"modelo_prompt": "um/modelo"})

    assert resposta.json()["modelos_de_imagem"] == ["so/este"]


# --------------------------------------------------------------------------- #
# Modelos que aceitam imagens de referência (item 7.5b, W1)
# --------------------------------------------------------------------------- #


def teste_w1_modelos_com_referencia_nasce_vazio(cliente: TestClient) -> None:
    assert cliente.get("/configuracao").json()["modelos_com_referencia"] == {}


def teste_w1_gravar_modelos_com_referencia_normaliza_as_chaves(cliente: TestClient) -> None:
    resposta = cliente.put(
        "/configuracao",
        json={"modelos_com_referencia": {" replicate:bytedance/seedream-4.5 ": "image_input", "  ": "images"}},
    )

    assert resposta.status_code == 200
    esperado = {"replicate:bytedance/seedream-4.5": "image_input"}
    assert resposta.json()["modelos_com_referencia"] == esperado
    assert cliente.get("/configuracao").json()["modelos_com_referencia"] == esperado


def teste_w1_o_parametro_tem_de_ser_um_nome_simples(cliente: TestClient) -> None:
    for parametro in ("", "image input", "image-input", "1imagens", "a" * 51):
        resposta = cliente.put("/configuracao", json={"modelos_com_referencia": {"replicate:x/y": parametro}})
        assert resposta.status_code == 422, parametro


def teste_w1_limita_o_numero_de_modelos(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"modelos_com_referencia": {f"m/{i}": "images" for i in range(21)}}).status_code == 422


def teste_w1_gravar_outro_campo_nao_mexe_no_dicionario(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelos_com_referencia": {"replicate:x/y": "images"}})

    resposta = cliente.put("/configuracao", json={"modelo_prompt": "um/modelo"})

    assert resposta.json()["modelos_com_referencia"] == {"replicate:x/y": "images"}
