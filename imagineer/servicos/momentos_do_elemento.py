"""A linha do tempo de um elemento dentro do capítulo, e qual momento vale para uma cena (item 4.9, FL3, FL4, FL7).

Antes, o estado de um elemento guardava **um instante só** (o primeiro do capítulo): uma cena do fim do capítulo recebia a roupa e o estado do
começo. Agora a leitura devolve **momentos**, cada um com a citação de onde começa; o servidor acha a citação no texto (a posição) e, na hora de
montar uma cena, escolhe o momento que **cobre** o trecho dela.

Tudo aqui é **conservador**: sem posição, sem trecho, ou com estado de outro capítulo, o momento escolhido é o primeiro, que é o ``instante`` de
sempre. Nunca se inventa uma posição.
"""

from imagineer.ia.provedor import MomentoSugerido
from imagineer.modelos import EstadoElemento, Frame
from imagineer.servicos.aparencia_de_elemento import aparencia_fixa_de
from imagineer.servicos.posicao_no_texto import posicao_da_citacao

CAMPOS_DO_MOMENTO = ("ancora", "roupa", "estado_fisico", "expressao_e_postura", "humor", "lugar")

_ROTULOS_DO_INSTANTE = (
    ("roupa", "clothing/hairstyle"),
    ("estado_fisico", "physical state"),
    ("expressao_e_postura", "expression and posture"),
    ("humor", "visible mood"),
)
"""Como cada campo do momento aparece, rotulado, na descrição que a IA recebe. Os rótulos deixam a instrução da cena dizer o que usar de cada um
(da pose e da expressão de um momento, a cena **não** usa: ela mesma diz o que acontece)."""


def momentos_com_posicao(momentos: list[MomentoSugerido] | None, texto_do_capitulo: str) -> list[dict] | None:
    """Os momentos como se guardam (``EstadoElemento.momentos``): cada um com a ``posicao`` achada no capítulo, ou sem ela se a âncora não foi achada.

    A âncora é a citação que a IA devolveu; ``posicao_da_citacao`` a procura (exata, e depois normalizada) e devolve o início do parágrafo, em UTF-16.
    Âncora vazia ou que não está no texto: o momento fica **sem** ``posicao`` (só serve como "o primeiro"), nunca com uma posição chutada.
    """
    if not momentos:
        return None
    guardados = []
    for momento in momentos:
        dado = {campo: getattr(momento, campo) for campo in CAMPOS_DO_MOMENTO}
        posicao = posicao_da_citacao(texto_do_capitulo, momento.ancora)
        if posicao is not None:
            dado["posicao"] = posicao
        guardados.append(dado)
    return guardados


def posicao_do_frame(frame: Frame) -> int | None:
    """Onde, no capítulo, a cena acontece (UTF-16): a posição que a pessoa **escolheu** ("Ilustrar aqui") ou, sem ela, a do início do ``trecho`` da cena."""
    if frame.posicao_no_texto is not None:
        return frame.posicao_no_texto
    if frame.trecho and frame.capitulo is not None:
        return posicao_da_citacao(frame.capitulo.texto, frame.trecho)
    return None


def indice_do_momento(estado: EstadoElemento, posicao_da_cena: int | None, capitulo_do_frame_id: int | None) -> int:
    """O índice do momento do ``estado`` que cobre a cena (FL7): o **último com posição ≤ a da cena**; 0 (o primeiro) em qualquer dúvida.

    Dúvida é: o estado não tem momentos; a cena não tem posição; o estado é de **outro capítulo** (as posições são deslocamentos no texto do capítulo
    de origem do estado, e não se comparam com as de outro texto); ou nenhum momento tem posição ≤ a da cena.
    """
    momentos = estado.momentos or []
    if len(momentos) < 2 or posicao_da_cena is None or estado.capitulo_id != capitulo_do_frame_id:
        return 0
    escolhido = 0
    for indice, momento in enumerate(momentos):
        posicao = momento.get("posicao")
        if posicao is not None and posicao <= posicao_da_cena:
            escolhido = indice
    return escolhido


def descricao_para_a_cena(estado: EstadoElemento, frame: Frame) -> str:
    """A descrição do ``estado`` que a IA recebe ao montar a **cena** ``frame``: a do momento que cobre o trecho dela.

    O primeiro momento (ou a dúvida) devolve a ``descricao`` **exatamente como está**. Escolhido outro momento, a "Aparência fixa:" fica e o
    "Neste instante:" passa a ser o do momento, com cada parte rotulada (roupa e penteado, estado físico, expressão e postura, humor), e o
    "Onde está:" passa a ser o ``lugar`` do momento, se ele tiver um.
    """
    indice = indice_do_momento(estado, posicao_do_frame(frame), frame.capitulo_id)
    if indice == 0:
        return estado.descricao

    momento = estado.momentos[indice]
    partes = [f"{rotulo}: {momento[campo]}" for campo, rotulo in _ROTULOS_DO_INSTANTE if momento.get(campo)]
    if not partes and not momento.get("lugar"):
        return estado.descricao  # o momento escolhido não diz nada de útil: melhor o estado de sempre que só a aparência fixa

    linhas = []
    fixa = aparencia_fixa_de(estado.descricao)
    if fixa:
        linhas.append(f"Aparência fixa: {fixa}")
    if partes:
        linhas.append("Neste instante: " + "; ".join(partes))
    if momento.get("lugar"):
        linhas.append(f"Onde está: {momento['lugar']}")
    return "\n".join(linhas)
