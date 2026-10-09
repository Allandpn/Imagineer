"""Os esquemas JSON das respostas de leitura (item 4.10, LM8; etapa E4).

Três coisas são conferidas: (1) cada esquema é **bem formado** para o modo estrito dos provedores; (2) uma resposta de exemplo de cada operação
**passa** no esquema e **também** no interpretador que a lê (o esquema nunca é mais restrito que o interpretador); (3) o pedido só leva
``response_format`` quando o modelo aceita esquema estrito. O validador de JSON Schema é mínimo e fica aqui, no teste: sem dependência nova.
"""

import json

import httpx
import pytest

from imagineer.ia import catalogo_de_texto
from imagineer.ia.esquemas_json import ESQUEMAS
from imagineer.ia.openrouter import (
    ENDERECO_BASE,
    ProvedorOpenRouter,
    _interpretar_cenas_sugeridas,
    _interpretar_contexto,
    _interpretar_elementos,
    _interpretar_estado,
    _interpretar_identidade,
)
from imagineer.ia.tarefas import PERFIS
from imagineer.modelos import TipoElemento

PROIBIDOS = {"minLength", "maxLength", "pattern", "format", "$ref", "minItems", "maxItems", "minimum", "maximum"}


# --------------------------------------------------------------------------- #
# O validador mínimo
# --------------------------------------------------------------------------- #


def _tipo_confere(valor, tipo: str) -> bool:
    return {
        "string": isinstance(valor, str),
        "boolean": isinstance(valor, bool),
        "null": valor is None,
        "array": isinstance(valor, list),
        "object": isinstance(valor, dict),
        "integer": isinstance(valor, int) and not isinstance(valor, bool),
        "number": isinstance(valor, (int, float)) and not isinstance(valor, bool),
    }[tipo]


def erros_do_esquema(valor, esquema: dict, caminho: str = "$") -> list[str]:
    """Os erros de ``valor`` contra ``esquema`` (``type``, ``enum``, ``properties``, ``required``, ``additionalProperties``, ``items``)."""
    tipos = esquema["type"] if isinstance(esquema["type"], list) else [esquema["type"]]
    if not any(_tipo_confere(valor, t) for t in tipos):
        return [f"{caminho}: esperava {tipos}, veio {type(valor).__name__}"]
    if "enum" in esquema and valor not in esquema["enum"]:
        return [f"{caminho}: {valor!r} não está em {esquema['enum']}"]

    erros: list[str] = []
    if isinstance(valor, dict) and "object" in tipos:
        for chave in esquema["required"]:
            if chave not in valor:
                erros.append(f"{caminho}: falta {chave!r}")
        for chave, conteudo in valor.items():
            if chave not in esquema["properties"]:
                if esquema["additionalProperties"] is False:
                    erros.append(f"{caminho}: {chave!r} não é permitido")
                continue
            erros += erros_do_esquema(conteudo, esquema["properties"][chave], f"{caminho}.{chave}")
    if isinstance(valor, list) and "array" in tipos:
        for posicao, item in enumerate(valor):
            erros += erros_do_esquema(item, esquema["items"], f"{caminho}[{posicao}]")
    return erros


def _percorrer(esquema: dict, caminho: str = "$"):
    """Todos os nós do esquema, com o caminho de cada um."""
    yield caminho, esquema
    for chave, filho in (esquema.get("properties") or {}).items():
        yield from _percorrer(filho, f"{caminho}.{chave}")
    if isinstance(esquema.get("items"), dict):
        yield from _percorrer(esquema["items"], f"{caminho}[]")


# --------------------------------------------------------------------------- #
# Respostas de exemplo (o que um modelo bem comportado devolveria)
# --------------------------------------------------------------------------- #

EXEMPLOS = {
    "extracao": {
        "elementos": [
            {"tipo": "PERSONAGEM", "nome": "Ned Stark", "descricao": "senhor de Winterfell"},
            {"tipo": "OBJETO", "nome": "a espada", "descricao": None},
        ],
        "cenas": [
            {
                "titulo": "O duelo no pátio",
                "descricao": "Ned ergue a espada.",
                "horario": "manhã",
                "clima": None,
                "humor": "tenso",
                "trecho_ancora": "Ned ergueu a espada",
                "trecho": "Ned ergueu a espada diante do portão.",
                "participantes": [{"tipo": "PERSONAGEM", "nome": "Ned Stark"}, {"tipo": "OBJETO", "nome": "a espada"}],
            }
        ],
    },
    "estado": {"aparencia_fixa": "barba rala, olhos cinzentos", "instante": "de capa escura, mão no punho", "ambiente": "pátio de pedra"},
    "identidade": {"descricao": "agora é Lorde Comandante"},
    "fundamentacao": {"contexto": "de manhã, no pátio, com vento"},
    "estado_com_momentos": {
        "aparencia_fixa": "barba rala",
        "instante": "de capa",
        "ambiente": None,
        "momentos": [
            {"ancora": "Ned ergueu", "roupa": "capa escura", "estado_fisico": None, "expressao_e_postura": "queixo erguido", "humor": "tenso", "lugar": "pátio"}
        ],
    },
    "dossie": {
        "momento_incerto": False,
        "presentes": [
            {"nome": "Ned", "tipo": "PESSOA", "elemento": "Ned Stark", "caracteristicas": "capa escura, espada em punho", "incerto": False},
            {"nome": "o cão", "tipo": "CRIATURA", "elemento": None, "caracteristicas": "pelo cinza, deitado", "incerto": True},
        ],
        "onde": "pátio de pedra",
        "luz_e_clima": "manhã fria",
        "acao": "Ned ergue a espada",
        "faltou": ["a cor do portão"],
    },
}


# --------------------------------------------------------------------------- #
# (1) Bem formados
# --------------------------------------------------------------------------- #


def teste_lm8_os_esquemas_previstos_existem() -> None:
    assert {"extracao", "estado", "identidade", "fundamentacao", "estado_com_momentos", "dossie"} <= set(ESQUEMAS)


@pytest.mark.parametrize("nome", sorted(ESQUEMAS))
def teste_lm8_todo_objeto_e_estrito_com_todas_as_propriedades_obrigatorias(nome: str) -> None:
    for caminho, no in _percorrer(ESQUEMAS[nome]):
        if "object" in (no["type"] if isinstance(no["type"], list) else [no["type"]]):
            assert no["additionalProperties"] is False, f"{nome} {caminho}"
            assert no["required"] == list(no["properties"]), f"{nome} {caminho}"


@pytest.mark.parametrize("nome", sorted(ESQUEMAS))
def teste_lm8_nenhum_campo_proibido_no_modo_estrito(nome: str) -> None:
    for caminho, no in _percorrer(ESQUEMAS[nome]):
        assert not (PROIBIDOS & set(no)), f"{nome} {caminho}: {PROIBIDOS & set(no)}"


@pytest.mark.parametrize("nome", sorted(ESQUEMAS))
def teste_lm8_o_esquema_e_serializavel_em_json(nome: str) -> None:
    assert json.loads(json.dumps(ESQUEMAS[nome])) == ESQUEMAS[nome]


def teste_lm8_o_enum_de_tipos_vem_do_tipo_de_elemento_do_sistema() -> None:
    tipo = ESQUEMAS["extracao"]["properties"]["elementos"]["items"]["properties"]["tipo"]

    assert tipo["enum"] == [t.name for t in TipoElemento]


def teste_lm8_todo_esquema_citado_por_um_perfil_existe() -> None:
    for operacao, perfil in PERFIS.items():
        assert perfil.esquema is None or perfil.esquema in ESQUEMAS, operacao


def teste_lm8_as_quatro_tarefas_de_leitura_usam_esquema() -> None:
    assert {o: PERFIS[o].esquema for o in ("extracao", "estado", "identidade", "fundamentacao")} == {
        "extracao": "extracao", "estado": "estado_com_momentos", "identidade": "identidade", "fundamentacao": "fundamentacao",
    }


# --------------------------------------------------------------------------- #
# (2) Respostas de exemplo
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("nome", sorted(EXEMPLOS))
def teste_lm8_a_resposta_de_exemplo_passa_no_esquema(nome: str) -> None:
    assert erros_do_esquema(EXEMPLOS[nome], ESQUEMAS[nome]) == []


@pytest.mark.parametrize("nome", sorted(EXEMPLOS))
def teste_lm8_o_validador_recusa_propriedade_extra(nome: str) -> None:
    resposta = {**EXEMPLOS[nome], "campo_inventado": 1}

    assert erros_do_esquema(resposta, ESQUEMAS[nome])


@pytest.mark.parametrize("nome", sorted(EXEMPLOS))
def teste_lm8_o_validador_recusa_propriedade_que_falta(nome: str) -> None:
    resposta = dict(EXEMPLOS[nome])
    resposta.pop(next(iter(resposta)))

    assert erros_do_esquema(resposta, ESQUEMAS[nome])


def teste_lm8_o_validador_recusa_tipo_de_elemento_desconhecido() -> None:
    resposta = json.loads(json.dumps(EXEMPLOS["extracao"]))
    resposta["elementos"][0]["tipo"] = "MONSTRO"

    assert any("MONSTRO" in e for e in erros_do_esquema(resposta, ESQUEMAS["extracao"]))


def teste_lm8_o_validador_recusa_tipo_de_presente_desconhecido() -> None:
    resposta = json.loads(json.dumps(EXEMPLOS["dossie"]))
    resposta["presentes"][0]["tipo"] = "FANTASMA"

    assert erros_do_esquema(resposta, ESQUEMAS["dossie"])


def teste_lm8_campo_opcional_aceita_nulo_mas_o_obrigatorio_nao() -> None:
    com_nulo = {**EXEMPLOS["fundamentacao"], "contexto": None}

    assert erros_do_esquema(com_nulo, ESQUEMAS["fundamentacao"])  # ``contexto`` é texto: o interpretador exige
    assert erros_do_esquema({"descricao": None}, ESQUEMAS["identidade"]) == []  # ``None`` é o caso comum da identidade


def teste_lm8_o_esquema_nao_e_mais_restrito_que_o_interpretador_da_extracao() -> None:
    """A resposta de exemplo (que passa no esquema) é lida de ponta a ponta pelo interpretador."""
    elementos = _interpretar_elementos(EXEMPLOS["extracao"])
    cenas = _interpretar_cenas_sugeridas(EXEMPLOS["extracao"])

    assert [(e.tipo, e.nome) for e in elementos] == [(TipoElemento.PERSONAGEM, "Ned Stark"), (TipoElemento.OBJETO, "a espada")]
    assert elementos[1].descricao is None
    assert cenas[0].titulo == "O duelo no pátio" and [p.nome for p in cenas[0].participantes] == ["Ned Stark", "a espada"]
    assert cenas[0].clima is None and cenas[0].trecho == "Ned ergueu a espada diante do portão."


def teste_lm8_o_esquema_nao_e_mais_restrito_que_o_interpretador_do_estado() -> None:
    texto = _interpretar_estado(json.dumps(EXEMPLOS["estado"]))

    assert texto == (
        "Aparência fixa: barba rala, olhos cinzentos\n"
        "Neste instante: de capa escura, mão no punho\n"
        "Onde está: pátio de pedra"
    )


def teste_lm8_o_estado_com_nulos_que_o_esquema_aceita_o_interpretador_tambem_le() -> None:
    """O esquema deixa ``aparencia_fixa`` nula; o interpretador, desde que o instante venha, aceita."""
    resposta = {"aparencia_fixa": None, "instante": "de capa", "ambiente": None}

    assert erros_do_esquema(resposta, ESQUEMAS["estado"]) == []
    assert _interpretar_estado(json.dumps(resposta)) == "Neste instante: de capa"


def teste_lm8_o_esquema_nao_e_mais_restrito_que_o_interpretador_da_identidade() -> None:
    assert _interpretar_identidade(json.dumps(EXEMPLOS["identidade"])) == "agora é Lorde Comandante"
    assert _interpretar_identidade(json.dumps({"descricao": None})) is None


def teste_lm8_o_esquema_nao_e_mais_restrito_que_o_interpretador_da_fundamentacao() -> None:
    assert _interpretar_contexto(json.dumps(EXEMPLOS["fundamentacao"])) == "de manhã, no pátio, com vento"


def teste_lm8_o_estado_novo_mantem_o_instante_para_o_interpretador_de_hoje() -> None:
    """O formato novo (com ``momentos``) ainda é lido pelo interpretador de hoje: o ``instante`` continua (4.9, FL3)."""
    texto = _interpretar_estado(json.dumps(EXEMPLOS["estado_com_momentos"]))

    assert "Neste instante: de capa" in texto


# --------------------------------------------------------------------------- #
# (3) O pedido só leva ``response_format`` quando o modelo aceita
# --------------------------------------------------------------------------- #


def _modelo(*parametros: str) -> dict:
    return {
        "id": "x/modelo",
        "context_length": 100000,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "supported_parameters": ["max_tokens", *parametros],
        "reasoning": None,
        "top_provider": {"max_completion_tokens": 64000},
    }


def _provedor(corpos: list[dict], conteudo: str) -> ProvedorOpenRouter:
    def responder(pedido: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": conteudo}, "finish_reason": "stop"}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave", cliente=cliente, dormir=lambda _: None)


def teste_lm8_modelo_com_structured_outputs_recebe_o_esquema_estrito_da_tarefa(monkeypatch) -> None:
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [_modelo("structured_outputs")]})
    corpos: list[dict] = []

    _provedor(corpos, json.dumps(EXEMPLOS["estado"])).sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")

    (corpo,) = corpos
    # Item 4.9 (FL3): a leitura do estado pede a linha do tempo; o esquema `estado` (um instante só) fica em ESQUEMAS para o formato antigo.
    assert corpo["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "estado_com_momentos", "strict": True, "schema": ESQUEMAS["estado_com_momentos"]},
    }
    assert corpo["provider"] == {"require_parameters": True}


@pytest.mark.parametrize(
    "operacao, chamada, resposta",
    [
        ("extracao", lambda p: p.extrair_elementos("c", [], "x/modelo"), EXEMPLOS["extracao"]),
        ("identidade", lambda p: p.sugerir_identidade("c", TipoElemento.PERSONAGEM, "Ned", None, "x/modelo"), EXEMPLOS["identidade"]),
        ("fundamentacao", lambda p: p.fundamentar_frame("c", "Cena", None, None, None, None, [], "x/modelo"), EXEMPLOS["fundamentacao"]),
    ],
)
def teste_lm8_cada_tarefa_de_leitura_manda_o_seu_esquema(monkeypatch, operacao, chamada, resposta) -> None:
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [_modelo("structured_outputs")]})
    corpos: list[dict] = []

    chamada(_provedor(corpos, json.dumps(resposta)))

    assert corpos[0]["response_format"]["json_schema"]["name"] == PERFIS[operacao].esquema
    assert corpos[0]["response_format"]["json_schema"]["schema"] == ESQUEMAS[PERFIS[operacao].esquema]


def teste_lm8_modelo_so_com_response_format_nao_recebe_esquema_estrito(monkeypatch) -> None:
    """``response_format`` sozinho é JSON solto, não o esquema: o modo estrito exige ``structured_outputs``."""
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [_modelo("response_format")]})
    corpos: list[dict] = []

    _provedor(corpos, json.dumps(EXEMPLOS["estado"])).sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")

    assert "response_format" not in corpos[0] and "provider" not in corpos[0]


def teste_lm8_sem_catalogo_o_pedido_nao_leva_esquema() -> None:
    corpos: list[dict] = []

    _provedor(corpos, json.dumps(EXEMPLOS["estado"])).sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")

    assert "response_format" not in corpos[0]


def teste_lm8_tarefa_de_texto_livre_nunca_leva_esquema(monkeypatch) -> None:
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [_modelo("structured_outputs")]})
    corpos: list[dict] = []

    _provedor(corpos, "a red door").traduzir_prompt("uma porta vermelha", "en", "x/modelo")

    assert "response_format" not in corpos[0]


def teste_lm8_se_o_provedor_recusar_o_esquema_a_leitura_cai_para_o_interpretador_tolerante(monkeypatch) -> None:
    """O LM4 em ação: o catálogo diz que aceita, o provedor recusa; a leitura repete sem o esquema e dá certo."""
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [_modelo("structured_outputs")]})
    respostas = [
        httpx.Response(400, text="Provider returned error: json_schema is not supported"),
        httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(EXEMPLOS["estado"]) + "\n```"}, "finish_reason": "stop"}]}),
    ]
    corpos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(pedido.content))
        return respostas.pop(0)

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    provedor = ProvedorOpenRouter(chave_api="chave", cliente=cliente, dormir=lambda _: None)

    estado = provedor.sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Ned", None, None, "x/modelo")

    assert "response_format" in corpos[0] and "response_format" not in corpos[1]
    assert "barba rala" in estado.descricao  # a cerca de markdown foi lida pelo interpretador tolerante
