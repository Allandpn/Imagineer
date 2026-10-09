"""O dossiê da cena: quem e o que está presente naquele momento, confirmado pela pessoa (item 4.9, FL5 a FL9).

A fundamentação de três frases ignorava o resto do capítulo; o dossiê é uma leitura do capítulo **inteiro** que devolve a lista fechada de presentes, com as
características de cada um naquele momento, mais o lugar, a luz e a ação. A pessoa vê a lista e pode tirar, acrescentar e editar; a lista confirmada é a que
a montagem do prompt trata como "aparece só isto".

Este módulo não fala com a IA nem com o HTTP: guarda, compara e normaliza.
"""

import copy
import hashlib
import json

from imagineer.ia.openrouter import contexto_do_dossie
from imagineer.modelos import Frame
from imagineer.servicos.momentos_do_elemento import indice_do_momento, posicao_do_frame


def entrada_dos_participantes(frame: Frame) -> list[list]:
    """Quem está ligado à cena, no que decide o dossiê: para cada estado, ``[id do estado, nome do elemento, índice do momento que vale para a cena]``.

    De propósito **não** entra o texto da aparência: reler os estados (``QUALIDADE``) reescreve esse texto sem mudar *quem está na cena*, e isso não pode
    apagar a lista que a pessoa confirmou. Mudam o resumo: ligar ou tirar um elemento, trocar o estado dele, ou mudar o momento do capítulo que vale.
    """
    posicao = posicao_do_frame(frame)
    return [
        [estado.id, estado.elemento.nome, indice_do_momento(estado, posicao, frame.capitulo_id)]
        for estado in sorted(frame.estados_elemento, key=lambda e: e.id)
    ]


def entrada_do_dossie(frame: Frame, participantes: list) -> str:
    """Um resumo (hash) do que decide o dossiê (FL8): o que a pessoa escreveu sobre a cena (título, descrição, horário, clima, humor), o trecho, a
    posição escolhida e os ``participantes`` (ver ``entrada_dos_participantes``).
    """
    dados = [frame.titulo, frame.descricao, frame.horario, frame.clima, frame.humor, frame.trecho, frame.posicao_no_texto, list(participantes)]
    return hashlib.sha1(json.dumps(dados, ensure_ascii=False).encode("utf-8")).hexdigest()


def dossie_esta_velho(frame: Frame, participantes: list) -> bool:
    """O dossiê guardado foi lido com entradas diferentes das de agora (FL8). Sem dossiê não há o que envelhecer: ``False``."""
    return frame.dossie is not None and frame.dossie_entrada != entrada_do_dossie(frame, participantes)


def _nome_cadastrado(nome: str | None, cadastrados: list[str]) -> str | None:
    """O nome do elemento **cadastrado** a que ``nome`` se refere (sem diferença de maiúsculas e espaços nas pontas), ou ``None``.

    A IA devolve, em ``elemento``, o nome de um participante; se ela inventar um nome que não está no frame, o item continua na lista como um presente
    qualquer (um prato, um cão), mas **sem** ligação a um elemento: a ligação decide quem manda imagem de referência (FL10).
    """
    if not nome:
        return None
    for cadastrado in cadastrados:
        if cadastrado.strip().casefold() == nome.strip().casefold():
            return cadastrado
    return None


def guardar_dossie(frame: Frame, dossie: dict, contexto: str, participantes: list, nomes_cadastrados: list[str]) -> dict:
    """Guarda o dossiê **lido pela IA** no frame (ainda não confirmado) e devolve o que ficou guardado.

    Também deixa ``contexto_do_livro`` com o texto dele (lugar, luz e ação, FL8), para as telas e os prompts antigos, e marca o frame como lido.
    """
    guardado = copy.deepcopy(dossie)
    for presente in guardado.get("presentes", []):
        presente["elemento"] = _nome_cadastrado(presente.get("elemento"), nomes_cadastrados)
        presente.setdefault("incluir", True)
    guardado["confirmado"] = False
    frame.dossie = guardado
    frame.dossie_entrada = entrada_do_dossie(frame, participantes)
    frame.contexto_do_livro = contexto_do_dossie(guardado) or contexto  # o texto do dossiê (FL8); o do provedor só se o dossiê não tem lugar, luz nem ação
    frame.confirmado_pela_leitura_profunda = True
    return guardado


def confirmar_dossie(frame: Frame, novo: dict, campos_enviados: set[str], participantes: list, nomes_cadastrados: list[str]) -> dict:
    """Grava a lista que a **pessoa** confirmou (FL9): os presentes que ela deixou, tirou ou acrescentou, e o texto que ela editou.

    ``campos_enviados`` diz o que veio no pedido: o que não veio **fica como estava** (``onde``, ``luz_e_clima``, ``acao``). Sem dossiê lido antes, a
    pessoa pode escrever a lista do zero. Marca ``confirmado`` e atualiza o resumo das entradas: o que ela confirmou **agora** vale para o estado atual da
    cena (só uma mudança depois disto o torna velho).
    """
    atual = copy.deepcopy(frame.dossie) if frame.dossie is not None else {"momento_incerto": False, "onde": None, "luz_e_clima": None, "acao": None, "faltou": []}
    atual["presentes"] = [
        {**presente, "elemento": _nome_cadastrado(presente.get("elemento"), nomes_cadastrados)} for presente in copy.deepcopy(novo["presentes"])
    ]
    for campo in ("onde", "luz_e_clima", "acao"):
        if campo in campos_enviados:
            atual[campo] = novo.get(campo)
    atual["confirmado"] = True
    frame.dossie = atual
    frame.dossie_entrada = entrada_do_dossie(frame, participantes)
    frame.contexto_do_livro = contexto_do_dossie(atual)
    frame.confirmado_pela_leitura_profunda = True
    return atual
