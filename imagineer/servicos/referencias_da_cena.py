"""As imagens de referência que uma cena leva **sozinha**, só como identidade (item 4.9, FL10).

Antes, as âncoras dos elementos não vinham marcadas: a pessoa tinha de lembrar de escolher o retrato de cada personagem no seletor, e a cena saía sem a
identidade deles. Agora, se o modelo de imagem aceita referências, a âncora de cada elemento **que está na lista da cena** vai por padrão, no máximo 4, o
sujeito principal primeiro. A pessoa continua podendo tirar qualquer uma no seletor (EV3). A frase que acompanha as imagens (FL11) trava a referência
como "só identidade".

Regras:

- só entra o elemento que **está na lista da cena** (a confirmada pela pessoa, ou, sem dossiê, os elementos ligados ao frame): um elemento vinculado que
  não está na lista não manda imagem;
- ambiente e edificação **não** vão como referência (o fundo deles vazaria para a cena, W12);
- elemento **sem âncora** não manda nada: vale a aparência escrita no prompt;
- a âncora é a do estado ligado ao frame e, senão, a padrão do elemento (W2).
"""

from imagineer.ia.fornecedores_de_imagem import separar_fornecedor
from imagineer.modelos import Configuracao, Frame, Imagem, Prompt, TipoDeFrame, TipoElemento
from imagineer.modelos.prompt import TipoDePrompt
from imagineer.servicos.catalogo_imagens import caminho_absoluto

TIPOS_QUE_NAO_VAO_COMO_REFERENCIA = frozenset({TipoElemento.AMBIENTE, TipoElemento.EDIFICACAO})
"""O fundo e a arquitetura deles vazariam para a cena (W12, FL10): a referência só leva identidade."""

MAXIMO_DE_REFERENCIAS_AUTOMATICAS = 4
"""O limite de imagens por pedido (W3)."""


def _imagem_utilizavel(imagem: Imagem | None) -> bool:
    """A imagem existe, não está na lixeira e o arquivo está no disco: uma âncora quebrada não pode impedir a cena de ser gerada."""
    return imagem is not None and imagem.apagada_em is None and caminho_absoluto(imagem.caminho_arquivo).is_file()


def ancoras_da_cena(frame: Frame, presentes: list[dict] | None) -> list[int]:
    """Os ids das âncoras que a cena leva por padrão (FL10), na ordem: o sujeito principal e depois os demais da lista.

    ``presentes`` é a lista da cena que ficou (os presentes com ``elemento``, na ordem do dossiê); ``None`` = a cena não tem dossiê, e valem os elementos
    ligados ao frame, na ordem dos estados. Nome que não bate com nenhum elemento ligado ao frame é ignorado.
    """
    estados = sorted(frame.estados_elemento, key=lambda e: e.id)
    por_nome: dict[str, object] = {}
    for estado in estados:
        por_nome.setdefault(estado.elemento.nome.strip().casefold(), estado)  # dois estados do mesmo elemento: vale o primeiro
    if presentes is None:
        ordem = estados
    else:
        ordem = []
        for presente in presentes:
            estado = por_nome.get((presente.get("elemento") or "").strip().casefold())
            if estado is not None and estado not in ordem:
                ordem.append(estado)

    ids: list[int] = []
    for estado in ordem:
        if estado.elemento.tipo in TIPOS_QUE_NAO_VAO_COMO_REFERENCIA:
            continue
        ancora = estado.imagem_ancora or estado.elemento.imagem_ancora_padrao
        if _imagem_utilizavel(ancora) and ancora.id not in ids:
            ids.append(ancora.id)
    return ids[:MAXIMO_DE_REFERENCIAS_AUTOMATICAS]


def presentes_do_dossie(frame: Frame) -> list[dict] | None:
    """Os presentes que a pessoa deixou na lista da cena (``incluir``), ou ``None`` se a cena não tem dossiê."""
    if frame.dossie is None:
        return None
    return [p for p in frame.dossie.get("presentes") or [] if p.get("incluir", True)]


def referencias_automaticas(prompt: Prompt, configuracao: Configuracao, modelo_de_imagem: str) -> list[int]:
    """As referências que a geração do ``prompt`` leva quando o pedido **não diz** quais (FL10); vazio se não vale.

    Só uma **cena** de imagem, e só se o ``modelo_de_imagem`` aceita referências (``modelos_com_referencia``, W1) e não é do fal.ai (W4): num modelo
    que não aceita, não se manda nada e a geração segue como sempre. A lista é a que **valeu para o prompt** (a ficha dele), e não a de agora: regerar
    um prompt antigo usa o que ele usava.
    """
    frame = prompt.frame
    if frame is None or frame.tipo != TipoDeFrame.CENA or prompt.tipo == TipoDePrompt.VIDEO or prompt.so_imagem:
        return []
    if not (configuracao.modelos_com_referencia or {}).get(modelo_de_imagem) or separar_fornecedor(modelo_de_imagem)[0] == "fal":
        return []

    ficha = prompt.ficha or {}
    presentes = ficha.get("presentes") if ficha.get("dossie") else None
    return ancoras_da_cena(frame, presentes)
