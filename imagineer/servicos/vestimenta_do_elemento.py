"""A roupa característica de um personagem neste livro (pendência PD9, 13/10/2026).

O retrato (a âncora do personagem) saía com a roupa de **um** estado qualquer, quase sempre "roupa simples": o que o primeiro capítulo dizia dele. O
personagem de um livro tem, em geral, **um traje que o define**. Este serviço pergunta à IA qual é, **uma vez**, lendo só as descrições de estado já
guardadas (não o livro inteiro), e grava em ``Elemento.vestimenta``. A pessoa pode corrigir na ficha, e a roupa corrigida nunca é sobrescrita.
"""

import logging

from sqlalchemy.orm import Session

from imagineer.ia.provedor import ErroDoProvedorIA, ModeloNaoEscolhido, ProvedorIA
from imagineer.modelos import Configuracao, Elemento
from imagineer.modelos.elemento import TipoElemento
from imagineer.servicos.identidade_de_elemento import resumir_texto

LIMITE_DE_ESTADOS = 15
"""Quantos estados (capítulos) se mandam à IA: os mais antigos primeiro; o traje que define o personagem já aparece cedo e a chamada fica curta."""

LIMITE_DA_DESCRICAO = 500
"""Caracteres de cada descrição de estado."""


def descricoes_de_estados(elemento: Elemento) -> list[str]:
    """"Capítulo N: descrição" para cada estado do elemento, na ordem do livro, sem os de descrição vazia."""
    estados = sorted(elemento.estados, key=lambda e: (e.capitulo.ordem, e.id))
    linhas = []
    for estado in estados[:LIMITE_DE_ESTADOS]:
        if estado.descricao and estado.descricao.strip():
            linhas.append(f"Capítulo {estado.capitulo.ordem}: {resumir_texto(estado.descricao, LIMITE_DA_DESCRICAO)}")
    return linhas


def garantir_vestimenta(sessao: Session, provedor: ProvedorIA, elemento: Elemento, configuracao: Configuracao) -> None:
    """Preenche ``elemento.vestimenta`` se a pessoa e a IA ainda não o fizeram. **Nunca derruba** o prompt: sem modelo, sem descrições ou com o
    provedor falhando, o retrato segue como era (e a pessoa pode digitar a roupa na ficha). Só personagens (é a roupa de uma pessoa)."""
    if elemento.tipo != TipoElemento.PERSONAGEM or (elemento.vestimenta and elemento.vestimenta.strip()):
        return
    modelo = configuracao.modelo_leitura or configuracao.modelo_extracao or configuracao.modelo_prompt
    descricoes = descricoes_de_estados(elemento)
    if not modelo or not descricoes:
        return
    try:
        achada = provedor.identificar_vestimenta(elemento.nome, elemento.descricao, descricoes, modelo)
    except (ErroDoProvedorIA, ModeloNaoEscolhido):
        logging.getLogger(__name__).warning("Não foi possível identificar a vestimenta de %s agora.", elemento.nome)
        return
    if achada.vestimenta:
        elemento.vestimenta = achada.vestimenta
        sessao.add(elemento)
