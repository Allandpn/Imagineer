"""Onde, no texto de um capítulo, fica a primeira menção de um nome (item 3.4g, "Posição no texto").

O app desenha o artefato de cada sugestão no parágrafo da primeira vez que o elemento aparece.
Este módulo transforma um **nome** em uma **posição**, como o contrato do item 3.4g pede:

- a posição é o **início do parágrafo** que contém a primeira menção (o app desenha entre parágrafos);
- a unidade é **UTF-16**, a contagem de quem consome o número (o Kotlin), e não os caracteres
  Unicode do Python — um emoji conta 1 aqui e 2 lá, e tudo depois dele divergiria;
- a busca vai do mais exato ao mais tolerante: o nome **exato** e depois o nome **normalizado**
  (sem acento, sem diferença de maiúsculas, aspas tipográficas viradas retas, quebras de linha
  viradas espaço). **Normalizar muda o tamanho do texto**, então a busca normalizada guarda, para
  cada caractere normalizado, a posição do original de onde ele veio: sem esse mapa, o que se
  achasse no texto normalizado apontaria para o lugar errado do texto real.

**A busca é por palavra inteira**: "Vis" não casa com "visto" nem com "Vision". Sem isso, um nome
curto seria "achado" em qualquer palavra que o contenha.
"""

import re
import unicodedata

_ASPAS = {"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"'}


def _normalizar(texto: str) -> tuple[str, list[int]]:
    """Normaliza o texto e devolve, junto, de onde veio cada caractere.

    Devolve ``(texto_normalizado, origem)``, onde ``origem[k]`` é o índice, no texto original, do
    caractere que deu origem ao ``k``-ésimo caractere normalizado.
    """
    saida: list[str] = []
    origem: list[int] = []
    for indice, caractere in enumerate(texto):
        for parte in unicodedata.normalize("NFD", caractere):
            if unicodedata.category(parte) == "Mn":  # o acento solto, depois de decomposto
                continue
            parte = _ASPAS.get(parte, parte).lower()
            if parte.isspace():
                parte = " "
                if saida and saida[-1] == " ":  # juntar uma sequência de espaços e quebras em um só
                    continue
            saida.append(parte)
            origem.append(indice)
    return "".join(saida), origem


def _palavra_inteira(termo: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(termo) + r"(?!\w)")


def _inicio_do_paragrafo(texto: str, indice: int) -> int:
    """O índice onde começa o parágrafo que contém ``indice`` (parágrafos são separados por linha em branco)."""
    fronteira = texto.rfind("\n\n", 0, indice)
    inicio = 0 if fronteira == -1 else fronteira + 2
    while inicio < indice and texto[inicio].isspace():
        inicio += 1
    return inicio


LIMITE_DO_COMECO_DO_PARAGRAFO = 300
"""Quanto do começo de um parágrafo vai para uma lista (pins, favoritos)."""


def comeco_do_paragrafo(texto: str, posicao: int) -> str:
    """O começo do parágrafo que começa em ``posicao`` (UTF-16): até a linha em branco seguinte, em um espaço só, e no máximo 300 caracteres
    (cortado numa palavra, com reticências). Não levanta erro: uma posição que cai no meio de um emoji perde só esse caractere."""
    ate_o_fim = texto.encode("utf-16-le")[posicao * 2 :].decode("utf-16-le", errors="ignore")
    limpo = " ".join(ate_o_fim.split("\n\n", 1)[0].split())
    if len(limpo) <= LIMITE_DO_COMECO_DO_PARAGRAFO:
        return limpo
    return limpo[:LIMITE_DO_COMECO_DO_PARAGRAFO].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"


def tamanho_em_utf16(texto: str) -> int:
    """O tamanho do texto em unidades UTF-16: o limite de uma ``posicao_no_texto`` válida."""
    return len(texto.encode("utf-16-le")) // 2


def _em_utf16(texto: str, indice: int) -> int:
    """Converte um índice em caracteres Unicode para unidades UTF-16."""
    return len(texto[:indice].encode("utf-16-le")) // 2


def _indice_da_primeira_mencao(texto: str, termo: str) -> int | None:
    """O índice, no texto original, da primeira ocorrência de ``termo`` como palavra inteira.

    Busca **exata** primeiro; se não achar, a **normalizada** (com o mapa de volta ao original).
    """
    termo = termo.strip()
    if not termo:
        return None

    achado = _palavra_inteira(termo).search(texto)
    if achado is not None:
        return achado.start()

    texto_normalizado, origem = _normalizar(texto)
    termo_normalizado, _ = _normalizar(termo)
    termo_normalizado = termo_normalizado.strip()
    if not termo_normalizado:
        return None
    achado = _palavra_inteira(termo_normalizado).search(texto_normalizado)
    return None if achado is None else origem[achado.start()]


def _partes_de_nome_proprio(nome: str) -> list[str]:
    """As palavras do nome que começam com maiúscula e têm 3 letras ou mais ("Septimus Ellanher" -> as duas).

    É a reserva para quando o nome completo não aparece: o texto costuma usar só um pedaço
    ("Ellanher", "Septimus"). Palavras minúsculas ("de", "prata") ficam de fora de propósito:
    genéricas demais para apontarem o lugar certo.
    """
    palavras = re.findall(r"\w[\w'’-]*", nome)
    return [p for p in palavras if len(p) >= 3 and p[0].isupper()]


_MAXIMO_DE_PALAVRAS_DO_COMECO = 6
_MINIMO_DE_PALAVRAS_DO_COMECO = 3
"""Última tentativa: a IA costuma copiar bem o começo da citação e errar o fim (cortar, completar de
cabeça). Tenta-se o começo com 6 palavras, depois 5, 4 e 3, sempre o mais longo primeiro. Menos de 3
palavras é genérico demais: casaria com qualquer trecho parecido e apontaria o lugar errado."""


def _indice_da_citacao(texto: str, citacao: str) -> int | None:
    """O índice, no texto original, onde começa ``citacao`` — um **trecho**, não uma palavra inteira.

    Três tentativas, da mais exata à mais tolerante: (1) o trecho exato; (2) o trecho normalizado
    (com o mapa de volta ao original); (3) só o começo, normalizado, de 6 a 3 palavras.
    """
    citacao = citacao.strip()
    if not citacao:
        return None

    indice = texto.find(citacao)
    if indice != -1:
        return indice

    texto_normalizado, origem = _normalizar(texto)
    citacao_normalizada = _normalizar(citacao)[0].strip()
    if not citacao_normalizada:
        return None
    indice = texto_normalizado.find(citacao_normalizada)
    if indice != -1:
        return origem[indice]

    palavras = citacao_normalizada.split()
    for quantas in range(min(_MAXIMO_DE_PALAVRAS_DO_COMECO, len(palavras) - 1), _MINIMO_DE_PALAVRAS_DO_COMECO - 1, -1):
        indice = texto_normalizado.find(" ".join(palavras[:quantas]))
        if indice != -1:
            return origem[indice]
    return None


LIMITE_DO_TRECHO_DA_IA = 600
"""Quanto de um trecho que a IA citou o servidor guarda (FD7): 1 a 3 frases."""

LIMITE_DO_TRECHO_DA_PESSOA = 2000
"""Quanto de um trecho que a pessoa selecionou o servidor guarda (FD7): vale uns três parágrafos."""

MINIMO_DO_TRECHO = 10
"""Uma citação menor que isto não diz nada sobre a cena."""


def trecho_literal(texto: str, citacao: str | None, limite: int) -> str | None:
    """O trecho do capítulo que ``citacao`` cita, **como está no livro**, ou ``None`` se ela não está lá (FD7).

    Existe para nunca guardar uma frase inventada: a IA devolve uma citação, e aqui ela só vale se for **achada inteira** no texto, com a
    mesma tolerância de espaços, aspas e acentos da posição. O que se guarda é o texto **do livro** (as quebras de linha viram espaço),
    não o da citação. Acima de ``limite`` corta na última palavra e põe "…".
    """
    if not citacao or not citacao.strip():
        return None
    citacao = citacao.strip()
    indice = texto.find(citacao)
    if indice != -1:
        achado = texto[indice : indice + len(citacao)]
    else:
        normalizado, origem = _normalizar(texto)
        procurada = _normalizar(citacao)[0].strip()
        achada = normalizado.find(procurada) if procurada else -1
        if achada == -1:
            return None
        achado = texto[origem[achada] : origem[achada + len(procurada) - 1] + 1]
    limpo = " ".join(achado.split())
    if len(limpo) < MINIMO_DO_TRECHO:
        return None
    if len(limpo) <= limite:
        return limpo
    return limpo[:limite].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"


def posicao_da_citacao(texto: str, citacao: str | None) -> int | None:
    """A posição (UTF-16) do início do parágrafo onde ``citacao`` aparece, ou ``None``.

    É o caminho das **cenas** (item 3.4g): não há nome a buscar, só a citação que a IA devolveu.
    Citação vazia ou não encontrada: ``None``, e a cena continua valendo — só não ganha artefato.
    """
    if not citacao:
        return None
    indice = _indice_da_citacao(texto, citacao)
    if indice is None:
        return None
    return _em_utf16(texto, _inicio_do_paragrafo(texto, indice))


def posicao_da_primeira_mencao(texto: str, nome: str) -> int | None:
    """A posição (UTF-16) do início do parágrafo da primeira menção de ``nome``, ou ``None``.

    1. O nome **completo**: exato e depois normalizado (a primeira ocorrência é, por construção, a
       "primeira menção").
    2. Se o nome completo não aparece, a **primeira menção de qualquer pedaço que seja nome próprio**
       (ver ``_partes_de_nome_proprio``): vale a que vier antes no texto.

    Nome vazio ou nenhum pedaço no texto: ``None``, e a sugestão continua valendo — só não ganha
    artefato. (Isso também denuncia uma sugestão que a IA listou **sem** o elemento aparecer no capítulo.)
    """
    indice = _indice_da_primeira_mencao(texto, nome)
    if indice is None:
        candidatos = [
            i for parte in _partes_de_nome_proprio(nome) if (i := _indice_da_primeira_mencao(texto, parte)) is not None
        ]
        indice = min(candidatos, default=None)
    if indice is None:
        return None
    return _em_utf16(texto, _inicio_do_paragrafo(texto, indice))
