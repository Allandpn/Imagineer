"""Narradores: quem transforma o texto de um capítulo em voz (item NA1 a NA3).

Cada fornecedor de voz é uma classe de ``Narrador``, como cada fornecedor de imagem é um ``GeradorDeImagemExterno`` (item 6.6): as
rotas só conhecem a interface, e um fornecedor novo (ElevenLabs, fal.ai) entra como mais uma classe, sem mexer nelas.

O narrador **só fala o texto que recebe**: quem divide o capítulo em trechos, concatena os áudios, guarda o arquivo e registra o gasto
é ``imagineer/servicos/narracao.py``.
"""

import re
from abc import ABC, abstractmethod
from decimal import Decimal

import httpx

from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA

LIMITE_DO_TRECHO = 3500
"""Caracteres por pedido (NA2). O endpoint de fala limita a entrada de cada pedido, e um capítulo passa disso com folga; 3.500 fica
abaixo do limite e ainda dá trechos grandes o bastante para a voz manter o ritmo."""

CARACTERES_POR_MINUTO = 900
"""Quantos caracteres uma voz de narração fala por minuto (NA3). Medida típica de leitura em português (~150 palavras por minuto);
serve só para **estimar** a duração e o custo antes de gerar."""

TEMPO_LIMITE_DO_PEDIDO = 180.0
"""Segundos esperando um trecho. Um trecho de 3.500 caracteres leva de 10 a 40 segundos para ser falado."""


def dividir_em_trechos(texto: str, limite: int = LIMITE_DO_TRECHO) -> list[str]:
    """Divide o texto em trechos de **até** ``limite`` caracteres, cortando no ponto menos prejudicial para a voz (NA2).

    A ordem de preferência do corte: **fim de parágrafo**; se um parágrafo sozinho passa do limite, **fim de frase**; se uma frase
    passa, o **último espaço** antes do limite (e, sem nenhum espaço, no próprio limite). Parágrafos que cabem juntos ficam no mesmo
    trecho, separados por uma linha em branco (que a voz lê como pausa). Nenhum caractere do texto se perde, e a ordem é mantida.
    """
    paragrafos = [p.strip() for p in re.split(r"\n+", texto) if p.strip()]
    trechos: list[str] = []
    atual = ""

    def fechar() -> None:
        nonlocal atual
        if atual:
            trechos.append(atual)
            atual = ""

    for paragrafo in paragrafos:
        for pedaco in _cortar_o_paragrafo(paragrafo, limite):
            separador = "\n\n" if atual else ""
            if atual and len(atual) + len(separador) + len(pedaco) > limite:
                fechar()
                separador = ""
            atual += separador + pedaco
    fechar()
    return trechos


def _cortar_o_paragrafo(paragrafo: str, limite: int) -> list[str]:
    """Um parágrafo que cabe vai inteiro; um maior é cortado em frases e, se preciso, em palavras."""
    if len(paragrafo) <= limite:
        return [paragrafo]
    pedacos: list[str] = []
    atual = ""
    for frase in re.split(r"(?<=[.!?…])\s+", paragrafo):
        for parte in _cortar_a_frase(frase, limite):
            if atual and len(atual) + 1 + len(parte) > limite:
                pedacos.append(atual)
                atual = parte
            else:
                atual = f"{atual} {parte}" if atual else parte
    if atual:
        pedacos.append(atual)
    return pedacos


def _cortar_a_frase(frase: str, limite: int) -> list[str]:
    """Uma frase que cabe vai inteira; uma maior é cortada no último espaço antes do limite."""
    partes: list[str] = []
    while len(frase) > limite:
        corte = frase.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(frase[:corte].strip())
        frase = frase[corte:].strip()
    if frase:
        partes.append(frase)
    return partes


class Narrador(ABC):
    """Fala um trecho de texto e devolve o áudio (MP3)."""

    nome: str
    """Como o fornecedor aparece nas mensagens e em ``usos_ia.provedor`` ("openai")."""

    modelo: str
    """O modelo de voz usado."""

    @property
    @abstractmethod
    def disponivel(self) -> bool:
        """``True`` se o servidor tem o que o fornecedor exige (a chave). Sem isso, gerar nem começa (NA5, 422)."""

    @abstractmethod
    def narrar(self, texto: str, voz: str | None, instrucoes: str | None) -> bytes:
        """Fala ``texto`` e devolve o MP3.

        ``voz`` nula = a padrão do fornecedor; ``instrucoes`` nulas = sem instrução de tom (NA1). Levanta ``ChaveDeApiAusente`` se o
        fornecedor recusar a chave e ``ErroDoProvedorIA`` para qualquer outra falha, sempre com a mensagem em português."""

    @abstractmethod
    def custo_estimado(self, caracteres: int) -> Decimal:
        """O custo **estimado**, em dólares, de narrar ``caracteres`` (NA3). Estimado porque o fornecedor não informa o custo."""


class NarradorOpenAI(Narrador):
    """A voz da OpenAI (``gpt-4o-mini-tts``), pelo endpoint de fala — não pelo OpenRouter (NA1).

    O endpoint recebe o texto e devolve **aquele texto** falado, e aceita ``instructions`` para o tom. Os modelos de conversa com áudio
    (os que o OpenRouter oferece) podem parafrasear o texto, o que um narrador de livro não pode fazer.
    """

    nome = "openai"
    modelo = "gpt-4o-mini-tts"
    endereco = "https://api.openai.com/v1/audio/speech"

    VOZ_PADRAO = "alloy"
    """A voz quando ``configuracao.narracao_voz`` é nula: o endpoint **exige** uma voz, então "a padrão" é esta."""

    PRECO_POR_MINUTO = Decimal("0.015")
    """Dólares por minuto de áudio no ``gpt-4o-mini-tts``: o valor da **tabela publicada pela OpenAI** (≈ US$ 0,015 por minuto de
    fala, somando a entrada em texto e a saída em áudio). É uma estimativa — a resposta não traz o custo —, por isso o gasto é gravado
    como estimado (CU2). Se o preço mudar, troca-se aqui."""

    def __init__(self, chave_api: str, cliente: httpx.Client | None = None):
        self._chave_api = chave_api
        self._cliente = cliente or httpx.Client(timeout=TEMPO_LIMITE_DO_PEDIDO)

    @property
    def disponivel(self) -> bool:
        return bool(self._chave_api)

    def narrar(self, texto: str, voz: str | None, instrucoes: str | None) -> bytes:
        if not self._chave_api:
            raise ChaveDeApiAusente(
                "Não há chave da OpenAI configurada no servidor. Defina OPENAI_API_KEY (ou CHAVE_API_OPENAI) no .env e rode "
                "`docker compose up -d`."
            )
        corpo = {"model": self.modelo, "input": texto, "voice": voz or self.VOZ_PADRAO, "response_format": "mp3"}
        if instrucoes:
            corpo["instructions"] = instrucoes

        try:
            resposta = self._cliente.post(self.endereco, json=corpo, headers={"Authorization": f"Bearer {self._chave_api}"})
        except httpx.TimeoutException as erro:
            raise ErroDoProvedorIA("A OpenAI não respondeu no tempo esperado ao narrar um trecho.") from erro
        except httpx.HTTPError as erro:
            raise ErroDoProvedorIA(f"Não foi possível falar com a OpenAI: {erro}") from erro

        if resposta.status_code in (401, 403):
            raise ChaveDeApiAusente("A OpenAI recusou a chave de API. Confira OPENAI_API_KEY no .env do servidor.")
        if resposta.status_code == 429:
            raise ErroDoProvedorIA("A OpenAI recusou por excesso de pedidos ou falta de saldo (429). Confira o saldo e tente de novo.")
        if resposta.status_code >= 400:
            raise ErroDoProvedorIA(f"A OpenAI respondeu {resposta.status_code}: {_resumir(resposta.text)}")
        if not resposta.content:
            raise ErroDoProvedorIA("A OpenAI devolveu um áudio vazio.")
        return resposta.content

    def custo_estimado(self, caracteres: int) -> Decimal:
        return (Decimal(caracteres) / CARACTERES_POR_MINUTO * self.PRECO_POR_MINUTO).quantize(Decimal("0.00000001"))


def minutos_estimados(caracteres: int) -> float:
    """A duração estimada da fala, em minutos (NA3)."""
    return caracteres / CARACTERES_POR_MINUTO


def _resumir(texto: str, limite: int = 300) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


class NarradorFalso(Narrador):
    """Um narrador para os testes: devolve bytes previsíveis, sem rede e sem chave. Guarda o que recebeu em ``pedidos``.

    ``falhar_no_trecho`` (contado de 1) faz aquele trecho levantar ``ErroDoProvedorIA``, para testar a falha no meio (NA7)."""

    nome = "openai"
    modelo = "gpt-4o-mini-tts"

    def __init__(self, disponivel: bool = True, falhar_no_trecho: int | None = None):
        self._disponivel = disponivel
        self._falhar_no_trecho = falhar_no_trecho
        self.pedidos: list[tuple[str, str | None, str | None]] = []

    @property
    def disponivel(self) -> bool:
        return self._disponivel

    def narrar(self, texto: str, voz: str | None, instrucoes: str | None) -> bytes:
        self.pedidos.append((texto, voz, instrucoes))
        if self._falhar_no_trecho == len(self.pedidos):
            raise ErroDoProvedorIA("A OpenAI respondeu 500: falha de teste.")
        return f"MP3[{len(self.pedidos)}]".encode()

    def custo_estimado(self, caracteres: int) -> Decimal:
        return Decimal(caracteres) / 1_000_000
