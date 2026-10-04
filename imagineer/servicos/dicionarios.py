"""Consulta de dicionários no formato StarDict (RL19), lidos de uma pasta do servidor.

**O formato.** Um dicionário StarDict são arquivos com o mesmo nome e extensões diferentes:

- ``.ifo``: texto ``chave=valor`` (nome do dicionário, quantidade de palavras, tipo do conteúdo);
- ``.idx``: o índice, uma sequência de ``palavra\\0`` + 4 bytes (posição no ``.dict``) + 4 bytes (tamanho), em *big-endian*;
- ``.dict``: os verbetes, um colado no outro;
- ``.syn`` (opcional): formas alternativas, ``palavra\\0`` + 4 bytes com **o número da entrada** no ``.idx``.

**Por que busca binária.** Os ``.idx`` e ``.syn`` vêm ordenados **sem diferença entre maiúsculas e minúsculas** (só as letras
ASCII, como o ``g_ascii_strcasecmp`` do StarDict), então dá para achar uma palavra em ~20 comparações em vez de carregar centenas
de milhares de palavras na memória (os ``.syn`` destes dicionários passam de 900 mil formas: um ``dict`` do Python precisaria de
centenas de MB, o que um Raspberry Pi não tem). O que fica na memória é só uma lista de **posições** (4 bytes por palavra). A
ordenação é **conferida** ao montar a lista: um arquivo fora de ordem faria a busca binária errar **em silêncio**, então é recusado.
"""

import html
import logging
import mmap
import re
import struct
import threading
import unicodedata
from array import array
from dataclasses import dataclass, field
from pathlib import Path

registro = logging.getLogger(__name__)

LIMITE_DE_VERBETES_POR_DICIONARIO = 3
LIMITE_DO_TEXTO = 6000
LIMITE_DA_PALAVRA = 60


@dataclass
class VerbeteAchado:
    """Um verbete achado: a ``entrada`` (como o dicionário escreve a palavra) e o ``texto`` já em texto simples."""

    entrada: str
    texto: str


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _identificador(nome: str) -> str:
    """O nome do dicionário virado em um identificador de URL: minúsculas, sem acento, hifens entre as palavras."""
    return re.sub(r"[^a-z0-9]+", "-", _sem_acento(nome).lower()).strip("-") or "dicionario"


def _idiomas_do_nome(nome: str) -> tuple[str | None, list[str]]:
    """Dá, pelo nome do dicionário, o idioma das **entradas** e os idiomas de **livro** para os quais ele é consultado por padrão.

    Um dicionário de inglês para português serve a quem lê um livro **em inglês**; um de português para inglês, a quem lê em
    português e quer a tradução, mas isso não é o que se quer ao tocar numa palavra de um livro em português, então só aparece
    em "todos". Nome que não bate com nenhuma regra: sem idioma e só em "todos".
    """
    n = _sem_acento(nome).lower()
    if "english-portuguese" in n or "ingles-portugues" in n:
        return "en", ["en"]
    if "portuguese-english" in n or "portugues-ingles" in n:
        return "pt", []
    if "espanhol-portugues" in n:
        return "es", ["es"]
    if "portugues-espanhol" in n:
        return "pt", []
    if "lingua portuguesa" in n or "aurelio" in n:
        return "pt", ["pt"]
    if "britannica" in n or "thesaurus" in n:
        return "en", ["en"]
    return None, []


def texto_simples(conteudo: str) -> str:
    """Converte um verbete em HTML (como os destes dicionários) em texto simples.

    Quebras viram quebra de linha, o número de cada sentido (``<B> 1</B>``) ganha uma linha própria e o resto das etiquetas some.
    """
    t = conteudo.replace("\r", "")
    t = re.sub(r"<\s*B\s*>\s*(\d+)\s*</\s*B\s*>", r"\n\1 ", t, flags=re.IGNORECASE)
    t = re.sub(r"<\s*(br|p|/p|div|/div|li)\b[^>]*>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) > LIMITE_DO_TEXTO:
        t = t[:LIMITE_DO_TEXTO].rstrip() + "…"
    return t


def _decodificar(dados: bytes) -> str:
    """UTF-8 e, se não for, Windows-1252: os verbetes do Michaelis estão em Latin-1 apesar do que o ``.ifo`` diz."""
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


class DicionarioForaDeOrdem(Exception):
    """O índice de um dicionário não está ordenado como a busca binária exige."""


class _Indice:
    """Um arquivo de índice (``.idx`` ou ``.syn``) mapeado na memória, com a lista de onde cada entrada começa."""

    def __init__(self, caminho: Path, tamanho_do_complemento: int) -> None:
        self._arquivo = open(caminho, "rb")
        self.dados = mmap.mmap(self._arquivo.fileno(), 0, access=mmap.ACCESS_READ) if caminho.stat().st_size else b""
        self._complemento = tamanho_do_complemento
        self.posicoes = array("I")
        anterior = b""
        i = 0
        tamanho = len(self.dados)
        while i < tamanho:
            fim = self.dados.find(b"\0", i)
            if fim == -1:
                break
            chave = bytes(self.dados[i:fim]).lower()
            if chave < anterior:
                raise DicionarioForaDeOrdem(f"{caminho.name}: {chave!r} vem depois de {anterior!r}")
            anterior = chave
            self.posicoes.append(i)
            i = fim + 1 + tamanho_do_complemento

    def __len__(self) -> int:
        return len(self.posicoes)

    def _palavra(self, k: int) -> bytes:
        inicio = self.posicoes[k]
        return bytes(self.dados[inicio : self.dados.find(b"\0", inicio)])

    def entrada(self, k: int) -> tuple[bytes, bytes]:
        """A palavra e os bytes que vêm depois dela (a posição e o tamanho no ``.idx``; o número da entrada no ``.syn``)."""
        inicio = self.posicoes[k]
        fim = self.dados.find(b"\0", inicio)
        return bytes(self.dados[inicio:fim]), bytes(self.dados[fim + 1 : fim + 1 + self._complemento])

    def achar(self, palavra: bytes) -> list[int]:
        """Os números de **todas** as entradas cuja palavra é igual a ``palavra`` (sem diferença entre maiúsculas e minúsculas ASCII)."""
        chave = palavra.lower()
        baixo, alto = 0, len(self.posicoes)
        while baixo < alto:  # o primeiro k com palavra(k).lower() >= chave
            meio = (baixo + alto) // 2
            if self._palavra(meio).lower() < chave:
                baixo = meio + 1
            else:
                alto = meio
        achados = []
        while baixo < len(self.posicoes) and self._palavra(baixo).lower() == chave:
            achados.append(baixo)
            baixo += 1
        return achados


@dataclass
class Dicionario:
    """Um dicionário StarDict da pasta."""

    id: str
    nome: str
    base: Path
    palavras: int
    idioma_das_entradas: str | None
    padrao_para: list[str]
    tipo_do_conteudo: str
    _idx: _Indice | None = field(default=None, repr=False)
    _syn: _Indice | None = field(default=None, repr=False)
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _quebrado: str | None = field(default=None, repr=False)

    def _abrir(self) -> bool:
        """Monta os índices na primeira consulta. ``False`` se o dicionário não pode ser usado (e o motivo vai para o log, uma vez)."""
        with self._trava:
            if self._quebrado is not None:
                return False
            if self._idx is not None:
                return True
            try:
                self._idx = _Indice(self.base.with_suffix(".idx"), 8)
                syn = self.base.with_suffix(".syn")
                self._syn = _Indice(syn, 4) if syn.exists() else None
            except (DicionarioForaDeOrdem, OSError) as erro:
                self._quebrado = str(erro)
                self._idx = self._syn = None
                registro.warning("Dicionário %s ignorado: %s", self.nome, erro)
                return False
            return True

    def buscar(self, palavra: str) -> list[VerbeteAchado]:
        """Os verbetes de ``palavra`` (até ``LIMITE_DE_VERBETES_POR_DICIONARIO``), pelo índice principal e pelas formas alternativas."""
        if not self._abrir() or self._idx is None:
            return []
        bytes_da_palavra = palavra.encode("utf-8")
        numeros = self._idx.achar(bytes_da_palavra)
        if self._syn is not None:
            for k in self._syn.achar(bytes_da_palavra):
                _, numero = self._syn.entrada(k)
                alvo = struct.unpack(">I", numero)[0]
                if alvo < len(self._idx) and alvo not in numeros:
                    numeros.append(alvo)
        resultado: list[VerbeteAchado] = []
        for k in numeros[:LIMITE_DE_VERBETES_POR_DICIONARIO]:
            entrada, posicao_e_tamanho = self._idx.entrada(k)
            posicao, tamanho = struct.unpack(">II", posicao_e_tamanho)
            conteudo = self._ler(posicao, tamanho)
            if conteudo is not None:
                resultado.append(VerbeteAchado(_decodificar(entrada), conteudo))
        return resultado

    def _ler(self, posicao: int, tamanho: int) -> str | None:
        try:
            with open(self.base.with_suffix(".dict"), "rb") as arquivo:
                arquivo.seek(posicao)
                dados = arquivo.read(tamanho)
        except OSError as erro:
            registro.warning("Dicionário %s: não consegui ler o verbete (%s)", self.nome, erro)
            return None
        return texto_simples(_decodificar(dados))


def _ler_ifo(caminho: Path) -> dict[str, str]:
    dados: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in linha:
            chave, valor = linha.split("=", 1)
            dados[chave.strip()] = valor.strip()
    return dados


def descobrir_dicionarios(pasta: Path) -> list[Dicionario]:
    """Os dicionários StarDict da pasta (um ``.ifo`` com ``.idx`` e ``.dict`` do lado). Pasta ausente: lista vazia."""
    if not pasta.is_dir():
        return []
    achados: list[Dicionario] = []
    usados: set[str] = set()
    for ifo in sorted(pasta.glob("*.ifo")):
        base = ifo.with_suffix("")
        if not (base.with_suffix(".idx").exists() and base.with_suffix(".dict").exists()):
            registro.warning("Dicionário %s ignorado: falta o .idx ou o .dict (um .dict.dz não é lido).", ifo.name)
            continue
        info = _ler_ifo(ifo)
        nome = info.get("bookname") or base.name
        id_ = _identificador(nome)
        while id_ in usados:
            id_ += "-2"
        usados.add(id_)
        idioma, padrao = _idiomas_do_nome(nome)
        achados.append(
            Dicionario(
                id=id_,
                nome=nome,
                base=base,
                palavras=int(info.get("wordcount", "0") or 0),
                idioma_das_entradas=idioma,
                padrao_para=padrao,
                tipo_do_conteudo=info.get("sametypesequence", "m"),
            )
        )
    return achados


_PONTUACAO_DAS_PONTAS = " \t\r\n.,;:!?\"'()[]{}“”‘’«»…—–-_*"


def limpar_palavra(palavra: str) -> str:
    """Tira espaços e pontuação das pontas ("«casa»," → "casa") e junta espaços de dentro; limita o tamanho."""
    return re.sub(r"\s+", " ", palavra.strip(_PONTUACAO_DAS_PONTAS))[:LIMITE_DA_PALAVRA]


def variantes_da_palavra(palavra: str) -> list[str]:
    """Como procurar a palavra: como veio, em minúsculas e com a inicial maiúscula (sem repetir)."""
    candidatas = [palavra, palavra.lower(), palavra[:1].upper() + palavra[1:].lower()]
    return list(dict.fromkeys(c for c in candidatas if c))


def formas_base_em_ingles(palavra: str) -> list[str]:
    """Formas simples de uma palavra inglesa, para quando a flexionada não está no dicionário: sem *'s*, *s*, *es*, *ed*, *ing*..."""
    p = palavra.lower()
    formas: list[str] = []
    if p.endswith(("'s", "’s")):
        formas.append(p[:-2])
    if p.endswith("ies") and len(p) > 4:
        formas.append(p[:-3] + "y")
    if p.endswith("ied") and len(p) > 4:
        formas.append(p[:-3] + "y")
    if p.endswith("es") and len(p) > 3:
        formas.append(p[:-2])
    if p.endswith("s") and not p.endswith("ss") and len(p) > 3:
        formas.append(p[:-1])
    if p.endswith("ed") and len(p) > 4:
        formas += [p[:-2], p[:-1]]
        if len(p) > 5 and p[-3] == p[-4]:  # "stopped" → "stop"
            formas.append(p[:-3])
    if p.endswith("ing") and len(p) > 5:
        formas += [p[:-3], p[:-3] + "e"]
        if p[-4] == p[-5]:  # "running" → "run"
            formas.append(p[:-4])
    return list(dict.fromkeys(f for f in formas if len(f) >= 2))


def idioma_do_livro(idioma: str | None) -> str | None:
    """O idioma do livro reduzido a duas letras ("pt-BR" → "pt", "eng" → "en"); ``None`` se não dá para saber."""
    if not idioma:
        return None
    base = re.split(r"[-_]", idioma.strip().lower())[0]
    return {"por": "pt", "eng": "en", "spa": "es"}.get(base, base[:2]) or None


@dataclass
class ResultadoDoDicionario:
    dicionario: Dicionario
    verbete: VerbeteAchado


def consultar(
    dicionarios: list[Dicionario], palavra: str, idioma: str | None, todos: bool = False
) -> tuple[str, list[ResultadoDoDicionario]]:
    """Procura ``palavra`` nos dicionários que valem para o ``idioma`` do livro (ou em todos, com ``todos``).

    Devolve ``(palavra limpa, resultados)``. Procura primeiro a palavra como veio; só se **nada** for achado e o idioma for o inglês,
    tenta as formas simples. Sem idioma conhecido, vale como "todos os de uso padrão".
    """
    limpa = limpar_palavra(palavra)
    if not limpa:
        return "", []
    lingua = idioma_do_livro(idioma)
    if todos:
        escolhidos = list(dicionarios)
    elif lingua is None:
        escolhidos = [d for d in dicionarios if d.padrao_para]
    else:
        escolhidos = [d for d in dicionarios if lingua in d.padrao_para]

    def procurar(formas: list[str]) -> list[ResultadoDoDicionario]:
        achados: list[ResultadoDoDicionario] = []
        for d in escolhidos:
            vistos: set[str] = set()
            for forma in formas:
                for verbete in d.buscar(forma):
                    if verbete.texto not in vistos:
                        vistos.add(verbete.texto)
                        achados.append(ResultadoDoDicionario(d, verbete))
                if len(vistos) >= LIMITE_DE_VERBETES_POR_DICIONARIO:
                    break
        return achados

    resultados = procurar(variantes_da_palavra(limpa))
    if not resultados and (lingua == "en" or todos):
        resultados = procurar(formas_base_em_ingles(limpa))
    return limpa, resultados
