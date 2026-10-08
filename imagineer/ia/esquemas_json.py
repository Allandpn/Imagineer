"""Os esquemas JSON das respostas de leitura (item 4.10, LM8).

Quando o modelo aceita, o pedido leva ``response_format`` com ``json_schema`` em modo **estrito**: o provedor garante que a resposta é um JSON
desse formato, e o servidor deixa de depender de o modelo "seguir bem instruções de formato". Se o modelo não aceita, nada muda: o
interpretador tolerante (``_extrair_json``) continua valendo.

**Regras do modo estrito** (que os provedores exigem): todo objeto tem ``additionalProperties: false`` e **todas** as propriedades em
``required``; um campo que pode faltar é ``{"type": ["string", "null"]}``; sem ``minLength``, ``pattern``, ``format`` nem ``$ref``.

**O esquema nunca pode ser mais restrito que o interpretador** que lê a resposta (``_interpretar_*`` em ``openrouter.py``): um esquema que
recusasse o que o interpretador aceita faria o modelo falhar à toa. Por isso os de hoje saem do formato que a instrução já pede.
"""

from imagineer.modelos import TipoElemento

_TEXTO = {"type": "string"}
_TEXTO_OU_NULO = {"type": ["string", "null"]}


def _objeto(**propriedades: dict) -> dict:
    """Um objeto no modo estrito: sem propriedades extras e com todas obrigatórias."""
    return {
        "type": "object",
        "properties": propriedades,
        "required": list(propriedades),
        "additionalProperties": False,
    }


def _lista(itens: dict) -> dict:
    return {"type": "array", "items": itens}


_TIPO_DE_ELEMENTO = {"type": "string", "enum": [tipo.name for tipo in TipoElemento]}
"""Os tipos de elemento, tirados do próprio ``TipoElemento``: assim o esquema não fica para trás se um tipo novo nascer."""

_TIPO_DE_PRESENTE = {"type": "string", "enum": ["PESSOA", "CRIATURA", "OBJETO", "LUGAR"]}
"""O que o dossiê da cena distingue entre os presentes (item 4.9, FL5)."""


ESQUEMAS: dict[str, dict] = {
    # A extração (fase 1): os elementos do capítulo e as cenas sugeridas. Mesmo formato da ``_INSTRUCAO_DE_EXTRACAO``.
    "extracao": _objeto(
        elementos=_lista(_objeto(tipo=_TIPO_DE_ELEMENTO, nome=_TEXTO, descricao=_TEXTO_OU_NULO)),
        cenas=_lista(
            _objeto(
                titulo=_TEXTO,
                descricao=_TEXTO_OU_NULO,
                horario=_TEXTO_OU_NULO,
                clima=_TEXTO_OU_NULO,
                humor=_TEXTO_OU_NULO,
                trecho_ancora=_TEXTO_OU_NULO,
                trecho=_TEXTO_OU_NULO,
                participantes=_lista(_objeto(tipo=_TIPO_DE_ELEMENTO, nome=_TEXTO)),
            )
        ),
    ),
    # A leitura profunda de um elemento (fase 2), no formato **de hoje**: as três partes do estado.
    "estado": _objeto(aparencia_fixa=_TEXTO_OU_NULO, instante=_TEXTO_OU_NULO, ambiente=_TEXTO_OU_NULO),
    # A leitura de identidade (fase 2b): ``descricao`` nula é o caso comum ("nada de novo neste capítulo").
    "identidade": _objeto(descricao=_TEXTO_OU_NULO),
    # A fundamentação da cena (fase 3), no formato **de hoje**: um contexto só.
    "fundamentacao": _objeto(contexto=_TEXTO),
    # --- Os formatos novos do item 4.9. Ficam prontos aqui, mas **nenhum perfil os usa ainda**: quem implementar as etapas 2 e 3
    # do 4.9 troca o esquema junto com a instrução (a instrução de hoje não pede ``momentos`` nem ``presentes``, e um esquema
    # estrito os exigiria do modelo).
    "estado_com_momentos": _objeto(
        aparencia_fixa=_TEXTO,
        instante=_TEXTO,
        ambiente=_TEXTO_OU_NULO,
        momentos=_lista(
            _objeto(
                ancora=_TEXTO_OU_NULO,
                roupa=_TEXTO_OU_NULO,
                estado_fisico=_TEXTO_OU_NULO,
                expressao_e_postura=_TEXTO_OU_NULO,
                humor=_TEXTO_OU_NULO,
                lugar=_TEXTO_OU_NULO,
            )
        ),
    ),
    "dossie": _objeto(
        momento_incerto={"type": "boolean"},
        presentes=_lista(
            _objeto(nome=_TEXTO, tipo=_TIPO_DE_PRESENTE, elemento=_TEXTO_OU_NULO, caracteristicas=_TEXTO, incerto={"type": "boolean"})
        ),
        onde=_TEXTO_OU_NULO,
        luz_e_clima=_TEXTO_OU_NULO,
        acao=_TEXTO_OU_NULO,
        faltou=_lista(_TEXTO),
    ),
}
"""Nome do esquema (o ``esquema`` de ``PerfilDaTarefa``) -> o JSON Schema em modo estrito."""
