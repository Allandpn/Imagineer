"""O Claude Code, rodando no próprio servidor, como motor de **texto** (item 4.13, CC1 a CC9).

Em vez de chamar uma API paga por uso, o servidor roda ``claude -p`` (o modo sem tela do Claude Code), já logado na assinatura do Allan, e lê a
resposta. Quem decide **quando** isso vale é ``ProvedorOpenRouter._conversar``: um modelo cujo id começa com ``claude-code/`` vem para cá.
O que este módulo faz é só **falar com o programa**; as instruções de cada tarefa e a leitura das respostas continuam as mesmas de sempre.

Duas regras que não podem ser quebradas:

- **O Claude vira só um modelo de texto, sem poderes (CC5).** O texto de um livro pode conter frases com cara de ordem. Por isso o programa roda
  sem nenhuma ferramenta, sem configurações, sem memória, sem servidores MCP, sem salvar sessão e numa **pasta vazia e temporária**.
- **Nunca a chave de API (CC2).** O objetivo é gastar a assinatura. Se ``ANTHROPIC_API_KEY`` estivesse no ambiente, o Claude Code a usaria no lugar
  do login e cobraria por token sem ninguém perceber; por isso ela é tirada do ambiente do processo filho.
"""

import json
import os
import subprocess
import tempfile
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from imagineer.ia.provedor import ErroDoProvedorIA, ModeloDisponivel

PREFIXO_DO_MODELO = "claude-code/"
"""O começo do id de um modelo que vai para o Claude Code (CC3). O resto é o apelido que ``claude --model`` aceita."""

PROVEDOR_NO_USO = "claude_code"
"""O que ``usos_ia.provedor`` registra (CC7)."""

MODELOS: tuple[tuple[str, str], ...] = (
    ("opus", "Claude Opus (assinatura)"),
    ("sonnet", "Claude Sonnet (assinatura)"),
    ("haiku", "Claude Haiku (assinatura)"),
)
"""Os apelidos oferecidos na lista de modelos e o nome mostrado na tela. O apelido **muda de modelo sozinho** quando a Anthropic lança outro."""

CONTEXTO_DOS_MODELOS = 200_000
"""A janela que a lista informa. Conservadora: o que importa é que um capítulo caiba."""

TEMPO_LIMITE_PADRAO = 300
"""Segundos que uma chamada pode levar (CC4). Uma leitura grande, com o Claude pensando, passa de um minuto."""

VARIAVEIS_QUE_TROCARIAM_A_ASSINATURA_PELA_API = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
"""Variáveis que fariam o Claude Code deixar de usar o login da assinatura (ver o texto do módulo)."""

PREFIXO_DO_ERRO = "Claude indisponível"
"""Toda falha começa assim (CC4): o app mostra a mensagem tal como vem."""


def e_modelo_do_claude_code(id_do_modelo: str | None) -> bool:
    """Se o id é de um modelo que vai para o Claude Code."""
    return bool(id_do_modelo) and id_do_modelo.startswith(PREFIXO_DO_MODELO)


def apelido_do_modelo(id_do_modelo: str) -> str:
    """O apelido que ``claude --model`` entende: ``claude-code/sonnet`` → ``sonnet``."""
    return id_do_modelo.removeprefix(PREFIXO_DO_MODELO)


def modelos_do_claude_code() -> list[ModeloDisponivel]:
    """Os modelos do Claude Code, no formato da lista de modelos do app. Sem custo por chamada (a assinatura já está paga)."""
    return [
        ModeloDisponivel(
            id=PREFIXO_DO_MODELO + apelido,
            nome=nome,
            contexto=CONTEXTO_DOS_MODELOS,
            gratuito=False,
            suporta_json=True,
            custo_saida=0.0,
            preco_entrada=0.0,
            custo_do_capitulo_tipico=0.0,
            custo_do_capitulo_tipico_sem_cache=0.0,
        )
        for apelido, nome in MODELOS
    ]


@dataclass(frozen=True)
class RespostaDoClaudeCode:
    """O que uma chamada devolveu."""

    texto: str
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    tokens_em_cache: int | None = None
    cortada: bool = False
    """O Claude parou por ter chegado ao limite de saída (e não por ter terminado)."""


class ExecutorDoClaudeCode(ABC):
    """Quem de fato chama o Claude Code. Existe como interface para os testes usarem um falso, sem programa nenhum instalado."""

    @abstractmethod
    def conversar(self, apelido: str, instrucao: str, pedido: str) -> RespostaDoClaudeCode:
        """Manda ``pedido`` (com a ``instrucao`` como regra de sistema) ao modelo ``apelido`` e devolve a resposta.

        Levanta ``ErroDoProvedorIA`` com uma mensagem que começa em ``PREFIXO_DO_ERRO`` quando não dá."""


class ExecutorPorSubprocesso(ExecutorDoClaudeCode):
    """Roda ``claude -p`` como um processo filho, **uma chamada de cada vez** (CC4)."""

    _trinco = threading.Lock()
    """Um só para todas as instâncias: o provedor é recriado a cada pedido, e a fila tem de valer para o servidor inteiro."""

    def __init__(self, comando: Sequence[str] = ("claude",), tempo_limite: float = TEMPO_LIMITE_PADRAO):
        self._comando = list(comando)
        self._tempo_limite = tempo_limite

    def conversar(self, apelido: str, instrucao: str, pedido: str) -> RespostaDoClaudeCode:
        argumentos = [
            *self._comando,
            "-p",
            "--output-format", "json",
            "--model", apelido,
            "--system-prompt", instrucao,
            "--tools", "",  # CC5: nenhuma ferramenta
            "--setting-sources", "",  # CC5: nem configurações, nem CLAUDE.md, nem memória do Pi
            "--disable-slash-commands",
            "--strict-mcp-config",  # sem --mcp-config: nenhum servidor MCP
            "--no-session-persistence",
        ]
        ambiente = {k: v for k, v in os.environ.items() if k not in VARIAVEIS_QUE_TROCARIAM_A_ASSINATURA_PELA_API}

        with self._trinco, tempfile.TemporaryDirectory(prefix="imagineer-claude-") as pasta_vazia:
            try:
                concluido = subprocess.run(  # noqa: S603 - os argumentos são fixos; só o texto vai pela entrada padrão
                    argumentos,
                    input=pedido,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",  # um byte estranho na saída não pode derrubar a leitura
                    timeout=self._tempo_limite,
                    cwd=pasta_vazia,
                    env=ambiente,
                )
            except FileNotFoundError as erro:
                raise ErroDoProvedorIA(
                    f"{PREFIXO_DO_ERRO}: o programa '{self._comando[0]}' não está instalado neste servidor."
                ) from erro
            except subprocess.TimeoutExpired as erro:
                raise ErroDoProvedorIA(
                    f"{PREFIXO_DO_ERRO}: sem resposta em {int(self._tempo_limite)} s. Tente de novo ou escolha outro modelo."
                ) from erro

        return _ler_saida(concluido.returncode, concluido.stdout, concluido.stderr)


def _ler_saida(codigo: int, saida: str, erros: str) -> RespostaDoClaudeCode:
    """Lê o JSON que ``claude -p --output-format json`` imprime e o traduz em resposta, ou em erro com recado que dá para mostrar."""
    try:
        dados = json.loads(saida)
    except ValueError:
        dados = None
    if not isinstance(dados, dict):
        detalhe = _resumir((erros or saida).strip()) or f"o programa terminou com código {codigo} e sem resposta"
        raise ErroDoProvedorIA(f"{PREFIXO_DO_ERRO}: {detalhe}")

    texto = dados.get("result")
    if dados.get("is_error") or codigo != 0 or not isinstance(texto, str):
        raise ErroDoProvedorIA(f"{PREFIXO_DO_ERRO}: {_recado_do_erro(dados)}")

    uso = dados.get("usage") if isinstance(dados.get("usage"), dict) else {}

    def inteiro(chave: str) -> int | None:
        valor = uso.get(chave)
        return valor if isinstance(valor, int) and not isinstance(valor, bool) else None

    # Para o Claude Code, ``input_tokens`` é só a parte **nova** do pedido; o que veio do cache ou foi gravado nele vem em campos à parte.
    partes = [inteiro("input_tokens"), inteiro("cache_creation_input_tokens"), inteiro("cache_read_input_tokens")]
    entrada = sum(p for p in partes if p is not None) if any(p is not None for p in partes) else None
    return RespostaDoClaudeCode(
        texto=texto,
        tokens_entrada=entrada,
        tokens_saida=inteiro("output_tokens"),
        tokens_em_cache=inteiro("cache_read_input_tokens"),
        cortada=dados.get("stop_reason") == "max_tokens",
    )


def _recado_do_erro(dados: dict) -> str:
    """Um recado em português para o erro que o Claude Code relatou. O texto original vai junto: é o que dá para pesquisar."""
    original = _resumir(str(dados.get("result") or "").strip())
    minusculo = original.lower()
    acabou_a_cota = "limit" in minusculo and ("usage" in minusculo or "reached" in minusculo or "resets" in minusculo)
    if dados.get("api_error_status") == 429 or acabou_a_cota:
        return f"a cota da assinatura acabou por agora ({original}). Escolha outro modelo ou espere."
    if "not logged in" in minusculo or "/login" in minusculo or dados.get("api_error_status") == 401:
        return f"o login do Claude Code no servidor expirou ({original}). Entre de novo no servidor, com o comando 'claude' e depois /login."
    return original or "o Claude Code devolveu um erro sem mensagem."


def _resumir(texto: str, limite: int = 300) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"
