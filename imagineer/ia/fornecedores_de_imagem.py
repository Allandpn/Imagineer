"""Fornecedores de imagem além do OpenRouter: fal.ai e Replicate (item 6.6, F1 a F11).

O id de um modelo de imagem pode levar o fornecedor como prefixo (``fal:fal-ai/flux/dev``,
``replicate:black-forest-labs/flux-1.1-pro``); **sem prefixo é o OpenRouter**. Cada fornecedor tem um
gerador, que recebe só o prompt e devolve a imagem.

**A moderação de cada fornecedor fica sempre ligada (F3):** estes geradores só enviam o prompt. Nenhum
parâmetro que desligue ou afrouxe uma verificação de segurança é enviado, e a recusa de cada fornecedor
vira ``ConteudoRecusado`` para o fluxo de suavizar (S1 a S3) continuar valendo.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable

import httpx

from imagineer.ia.provedor import (
    ReferenciasParaGerar,
    ChaveDeApiAusente,
    ConteudoRecusado,
    ErroDoProvedorIA,
    ImagemGerada,
)

FORNECEDORES_EXTERNOS = ("fal", "replicate")
"""Os fornecedores que têm gerador próprio. Qualquer outro id é do OpenRouter."""

TEMPO_LIMITE_DA_GERACAO = 600.0
"""Segundos, **contados desde o pedido**, esperando uma geração terminar.

Longo de propósito (10 minutos): um modelo pode estar numa **fila** ou iniciando a frio, e o fornecedor **cobra a
imagem mesmo que a espera acabe aqui**; desistir cedo seria pagar e ficar sem a imagem (achado no teste do
``flux-schnell``, 02/10/2026). O app espera um pouco mais (660 s), para o erro, se vier, chegar com o nome do fornecedor."""

INTERVALO_DA_CONSULTA = 1.5
"""Segundos entre uma consulta de status e a seguinte."""

VARIAVEIS_DA_CHAVE = {"fal": "FAL_KEY", "replicate": "REPLICATE_API_TOKEN"}
NOMES_DOS_FORNECEDORES = {"fal": "fal.ai", "replicate": "Replicate"}


def separar_fornecedor(modelo: str) -> tuple[str, str]:
    """Separa o fornecedor do id (F1). Devolve ``("openrouter", id)`` se não há prefixo reconhecido.

    O prefixo só vale se for ``openrouter``, ``fal`` ou ``replicate`` **e** não tiver barra antes dos dois
    pontos: os sufixos do OpenRouter (``openai/gpt-oss-120b:batch``) não são fornecedor.
    """
    prefixo, separador, resto = modelo.partition(":")
    if separador and "/" not in prefixo and prefixo.strip().lower() in ("openrouter", *FORNECEDORES_EXTERNOS):
        return prefixo.strip().lower(), resto.strip()
    return "openrouter", modelo.strip()


class GeradorDeImagemExterno(ABC):
    """Gera uma imagem num fornecedor que não é o OpenRouter."""

    nome: str
    """Como o fornecedor aparece nas mensagens ("fal.ai", "Replicate")."""

    def __init__(
        self,
        chave_api: str,
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self._chave_api = chave_api
        self._cliente = cliente or httpx.Client(timeout=60.0)
        self._dormir = dormir
        self._relogio = relogio
        """``dormir`` e ``relogio`` vêm de fora para os testes não esperarem de verdade."""

    @abstractmethod
    def gerar(
        self,
        prompt: str,
        id_do_modelo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        """Gera a imagem. Levanta ``ConteudoRecusado`` se o fornecedor recusar o conteúdo (F4).

        ``sem_filtro_de_seguranca`` só existe no Replicate (F14); nos outros é recusado. ``referencias`` (W4) só no
        Replicate nesta fatia."""

    # ----------------------------------------------------------------------- #
    # Compartilhado
    # ----------------------------------------------------------------------- #

    def _cabecalho_de_autorizacao(self) -> dict[str, str]:
        raise NotImplementedError

    def _pedir(self, metodo: str, url: str, json: dict | None = None, cabecalhos: dict | None = None) -> dict:
        """Faz a chamada traduzindo qualquer falha em ``ErroDoProvedorIA`` (F10); a recusa fica a cargo da subclasse."""
        todos = {**self._cabecalho_de_autorizacao(), **(cabecalhos or {})}
        try:
            resposta = self._cliente.request(metodo, url, json=json, headers=todos)
        except httpx.TimeoutException as erro:
            raise ErroDoProvedorIA(f"O {self.nome} não respondeu no tempo esperado.") from erro
        except httpx.HTTPError as erro:
            raise ErroDoProvedorIA(f"Não foi possível falar com o {self.nome}: {erro}") from erro

        if resposta.status_code in (401, 403):
            raise ChaveDeApiAusente(
                f"O {self.nome} recusou a chave de API. Confira {VARIAVEIS_DA_CHAVE[self._fornecedor()]} no .env do servidor."
            )
        if resposta.status_code >= 400:
            self._ao_receber_erro(resposta)
            raise ErroDoProvedorIA(f"O {self.nome} respondeu {resposta.status_code}: {_resumir(resposta.text)}")
        try:
            dados = resposta.json()
        except ValueError as erro:
            raise ErroDoProvedorIA(f"O {self.nome} respondeu algo que não é JSON.") from erro
        if not isinstance(dados, dict):
            raise ErroDoProvedorIA(f"O {self.nome} respondeu num formato inesperado.")
        return dados

    def _ao_receber_erro(self, resposta: httpx.Response) -> None:
        """Gancho: a subclasse levanta ``ConteudoRecusado`` aqui se o erro for uma recusa de conteúdo."""

    def _fornecedor(self) -> str:
        raise NotImplementedError

    def _baixar(self, url: str, tipo_informado: str | None) -> ImagemGerada:
        """Baixa a imagem pronta. O tipo vem do fornecedor, do cabeçalho ou da extensão, nessa ordem."""
        try:
            resposta = self._cliente.get(url)
        except httpx.HTTPError as erro:
            raise ErroDoProvedorIA(f"Não consegui baixar a imagem do {self.nome}: {erro}") from erro
        if resposta.status_code >= 400 or not resposta.content:
            raise ErroDoProvedorIA(f"O {self.nome} não entregou o arquivo da imagem ({resposta.status_code}).")
        tipo = tipo_informado or resposta.headers.get("content-type", "").split(";")[0].strip() or _tipo_pela_extensao(url)
        return ImagemGerada(conteudo=resposta.content, tipo_de_midia=tipo)

    def _esperar(self, inicio: float, situacao: str | None = None) -> None:
        """Espera o intervalo da consulta; passado o limite, levanta o erro dizendo **a última situação** que o fornecedor deu."""
        if self._relogio() - inicio > TEMPO_LIMITE_DA_GERACAO:
            ultima = f" A última situação foi: {situacao}." if situacao else ""
            raise ErroDoProvedorIA(
                f"O {self.nome} não terminou a imagem em {int(TEMPO_LIMITE_DA_GERACAO)} segundos.{ultima}"
            )
        self._dormir(INTERVALO_DA_CONSULTA)


class GeradorFal(GeradorDeImagemExterno):
    """fal.ai (F5): fila (``queue.fal.run``), consulta do status e leitura do resultado."""

    nome = "fal.ai"

    def _fornecedor(self) -> str:
        return "fal"

    def _cabecalho_de_autorizacao(self) -> dict[str, str]:
        return {"Authorization": f"Key {self._chave_api}"}

    def _ao_receber_erro(self, resposta: httpx.Response) -> None:
        # O fal.ai descreve a recusa por `type`, nunca pela mensagem (item de erros da documentação deles).
        try:
            for item in resposta.json().get("detail") or []:
                if isinstance(item, dict) and item.get("type") == "content_policy_violation":
                    raise ConteudoRecusado(str(item.get("msg") or "O fal.ai recusou o conteúdo do prompt."))
        except (ValueError, AttributeError):
            return

    def gerar(
        self,
        prompt: str,
        id_do_modelo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        if sem_filtro_de_seguranca:
            # F14: o filtro só se desliga no Replicate. Quem chama já barrou isso; aqui é a segunda trava.
            raise ErroDoProvedorIA("Desligar o filtro de segurança só é permitido no Replicate.")
        if referencias is not None:
            # W4: imagens de referência no fal.ai ficam para outra fatia (cada modelo tem o seu parâmetro).
            raise ErroDoProvedorIA("Imagens de referência ainda não são enviadas ao fal.ai.")
        # F3: só o prompt. Nenhum parâmetro de segurança é enviado.
        inicio = self._relogio()
        envio = self._pedir("POST", f"https://queue.fal.run/{id_do_modelo}", json={"prompt": prompt})
        url_do_status, url_do_resultado = envio.get("status_url"), envio.get("response_url")
        if not (isinstance(url_do_status, str) and isinstance(url_do_resultado, str)):
            raise ErroDoProvedorIA("O fal.ai respondeu num formato inesperado.")

        while str(self._pedir("GET", url_do_status).get("status", "")).upper() != "COMPLETED":
            self._esperar(inicio)

        resultado = self._pedir("GET", url_do_resultado)
        return self._extrair(resultado)

    def _extrair(self, resultado: dict) -> ImagemGerada:
        imagens = resultado.get("images")
        if not imagens and isinstance(resultado.get("image"), dict):
            imagens = [resultado["image"]]
        if not (isinstance(imagens, list) and imagens and isinstance(imagens[0], dict) and imagens[0].get("url")):
            raise ErroDoProvedorIA("O fal.ai respondeu sem a imagem.")

        # F4: com o filtro disparado, o fal.ai devolve uma imagem PRETA, não um erro. Descarta, nunca grava.
        marcas = resultado.get("has_nsfw_concepts")
        if isinstance(marcas, list) and marcas and marcas[0] is True:
            raise ConteudoRecusado("O verificador de segurança do fal.ai marcou a imagem como imprópria.")

        return self._baixar(str(imagens[0]["url"]), imagens[0].get("content_type"))


class GeradorReplicate(GeradorDeImagemExterno):
    """Replicate (F6): predição de um modelo oficial, esperando na própria chamada e, se preciso, consultando."""

    nome = "Replicate"

    def _fornecedor(self) -> str:
        return "replicate"

    def _cabecalho_de_autorizacao(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._chave_api}"}

    def gerar(
        self,
        prompt: str,
        id_do_modelo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        entrada: dict[str, object] = {"prompt": prompt}
        if referencias is not None:
            # W4: o parâmetro de imagens de cada modelo (image_input, images, input_images), com uma LISTA de data URLs.
            entrada[referencias.parametro] = [imagem.como_data_url() for imagem in referencias.imagens]
        if sem_filtro_de_seguranca:
            # F12: o ÚNICO caso em que se manda um parâmetro de segurança, só por pedido explícito do usuário.
            entrada["disable_safety_checker"] = True
        # F3: fora disso, só o prompt.
        inicio = self._relogio()  # conta desde o pedido, inclusive o `Prefer: wait` do Replicate
        predicao = self._pedir(
            "POST",
            f"https://api.replicate.com/v1/models/{id_do_modelo}/predictions",
            json={"input": entrada},
            cabecalhos={"Prefer": "wait=60"},
        )
        while predicao.get("status") in ("starting", "processing"):
            url_da_consulta = (predicao.get("urls") or {}).get("get")
            if not isinstance(url_da_consulta, str):
                raise ErroDoProvedorIA("O Replicate respondeu num formato inesperado.")
            try:
                self._esperar(inicio, _DESCRICAO_DA_SITUACAO.get(str(predicao.get("status")), str(predicao.get("status"))))
            except ErroDoProvedorIA as erro:
                raise ErroDoProvedorIA(f"{erro} {self._cancelar(predicao)}") from erro
            predicao = self._pedir("GET", url_da_consulta)

        situacao = predicao.get("status")
        if situacao == "failed":
            erro = str(predicao.get("error") or "")
            if _fala_de_conteudo(erro):
                raise ConteudoRecusado(erro)
            raise ErroDoProvedorIA(f"O Replicate não gerou a imagem: {_resumir(erro) or 'sem detalhe'}")
        if situacao != "succeeded":
            raise ErroDoProvedorIA(f"O Replicate terminou a predição como \"{situacao}\".")

        saida = predicao.get("output")
        url = saida if isinstance(saida, str) else (saida[0] if isinstance(saida, list) and saida else None)
        if not isinstance(url, str) or not url:
            raise ErroDoProvedorIA("O Replicate respondeu sem a imagem.")
        return self._baixar(url, None)

    def _cancelar(self, predicao: dict) -> str:
        """Tenta cancelar a predição que ficou sem resposta, para o Replicate não gerar (e cobrar) uma imagem que ninguém vai receber.

        Devolve a frase que diz o que aconteceu. Falha ao cancelar não esconde o erro original."""
        url = (predicao.get("urls") or {}).get("cancel")
        if not isinstance(url, str):
            return "Não foi possível pedir o cancelamento; confira o painel do Replicate."
        try:
            self._pedir("POST", url)
        except ErroDoProvedorIA:
            return "Não consegui cancelar o pedido; confira o painel do Replicate."
        return "O pedido foi cancelado no Replicate (na fila, não é cobrado; se já estava gerando, confira o painel)."


_DESCRICAO_DA_SITUACAO = {
    "starting": "na fila ou iniciando o modelo (starting)",
    "processing": "gerando a imagem (processing)",
}
"""O que cada situação do Replicate quer dizer, para o usuário saber se o modelo estava na fila ou já trabalhando."""

_MARCAS_DE_CONTEUDO_DO_REPLICATE = ("nsfw", "safety", "sensitive", "content policy", "flagged")
"""Trechos (em minúsculas) que, numa predição `failed`, indicam recusa de conteúdo (F4). O Replicate não documenta o
formato do erro de segurança, então é por texto: a detecção fica aqui, fácil de ajustar."""


def _fala_de_conteudo(erro: str) -> bool:
    minusculo = erro.lower()
    return any(marca in minusculo for marca in _MARCAS_DE_CONTEUDO_DO_REPLICATE)


def _tipo_pela_extensao(url: str) -> str:
    caminho = url.split("?")[0].lower()
    for extensao, tipo in ((".webp", "image/webp"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".gif", "image/gif")):
        if caminho.endswith(extensao):
            return tipo
    return "image/png"


def _resumir(texto: str, limite: int = 200) -> str:
    achatado = " ".join(texto.split())
    return achatado if len(achatado) <= limite else achatado[:limite] + "…"


def montar_geradores(chave_fal: str | None, chave_replicate: str | None) -> dict[str, GeradorDeImagemExterno]:
    """Os geradores dos fornecedores que têm chave (F2); quem não tem não aparece, e pedir o modelo dele dá 422."""
    geradores: dict[str, GeradorDeImagemExterno] = {}
    if (chave_fal or "").strip():
        geradores["fal"] = GeradorFal(chave_fal.strip())
    if (chave_replicate or "").strip():
        geradores["replicate"] = GeradorReplicate(chave_replicate.strip())
    return geradores
