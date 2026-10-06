"""Leitura centralizada das variáveis de ambiente.

Toda configuração do sistema entra por aqui — e só por aqui. Isso cumpre a
Etapa 4.3 da especificação (a chave de API nunca fica escrita no código) e
evita que espalhemos ``os.environ`` por toda a aplicação.

A classe ``Configuracoes`` é um modelo Pydantic: os nomes dos campos são os
nomes das variáveis de ambiente, e o Pydantic valida e converte os valores na
subida da aplicação. Se faltar uma variável obrigatória, o erro aparece na
hora, com mensagem clara, em vez de estourar no meio de um request.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracoes(BaseSettings):
    """Variáveis de ambiente da aplicação.

    Os valores são lidos do arquivo ``.env`` ou do ambiente do processo
    (é assim que o docker-compose os injeta no container).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    url_banco: str
    """Endereço de conexão do PostgreSQL, no formato esperado pelo SQLAlchemy."""

    chave_api_openrouter: str = Field(
        default="",
        validation_alias=AliasChoices("CHAVE_API_OPENROUTER", "IMAGINEER_KEY_OPEN_ROUTER"),
    )
    """Chave de API do OpenRouter.

    Aceita duas variáveis de ambiente: ``CHAVE_API_OPENROUTER`` (o nome do
    projeto, em português, como as demais) e ``IMAGINEER_KEY_OPEN_ROUTER`` — o
    nome de uma variável de conta que Allan já mantém fora deste projeto,
    aceito para não obrigar a renomear algo que já existe no ambiente dele.
    Divergência registrada na Etapa 5 (Decisões Técnicas)."""

    chave_api_fal: str = Field(default="", validation_alias=AliasChoices("FAL_KEY", "CHAVE_API_FAL", "IMAGINEER_KEY_FAL_AI"))
    """Chave do fal.ai (F2). ``FAL_KEY`` é o nome que o próprio fal.ai usa; ``CHAVE_API_FAL`` é o nome do projeto;
    ``IMAGINEER_KEY_FAL_AI`` é a variável de conta do Allan (mesmo padrão do OpenRouter)."""

    chave_api_replicate: str = Field(default="", validation_alias=AliasChoices("REPLICATE_API_TOKEN", "CHAVE_API_REPLICATE", "IMAGINEER_KEY_REPLICATE"))
    """Chave do Replicate (F2). ``REPLICATE_API_TOKEN`` é o nome que o próprio Replicate usa;
    ``IMAGINEER_KEY_REPLICATE`` é a variável de conta do Allan (mesmo padrão do OpenRouter e do fal.ai)."""

    autenticacao: Literal["pessoal", "tailscale"] = Field(default="pessoal", validation_alias=AliasChoices("IMAGINEER_AUTENTICACAO"))
    """Como o servidor sabe quem chamou (CT2). ``pessoal`` (o padrão): todo pedido é do dono, nada muda. ``tailscale``: vale o cabeçalho de
    identidade do Tailscale, **só** vindo de um proxy confiável (``proxies_confiaveis``)."""

    dono_tailscale: str = Field(default="", validation_alias=AliasChoices("IMAGINEER_DONO"))
    """O login do Tailscale do dono (um e-mail). **Obrigatório** no modo ``tailscale`` (CT4): é por ele que o primeiro pedido do Allan "reivindica" a
    conta 1 em vez de virar uma conta nova e vazia."""

    proxies_confiaveis: str = Field(default="127.0.0.1,::1", validation_alias=AliasChoices("IMAGINEER_PROXIES_CONFIAVEIS"))
    """Endereços e faixas CIDR, separados por vírgula, de onde o cabeçalho de identidade é aceito (CT3). Em contêiner o proxy aparece como a ponte
    do Docker (ex.: ``172.16.0.0/12``); uma conexão vinda direto da tailnet (``100.x``) nunca passa."""

    @model_validator(mode="after")
    def _modo_tailscale_exige_o_dono(self) -> "Configuracoes":
        if self.autenticacao == "tailscale" and not self.dono_tailscale.strip():
            raise ValueError(
                "IMAGINEER_AUTENTICACAO=tailscale exige IMAGINEER_DONO (o login do Tailscale do dono): sem ele o dono chegaria como uma conta nova e vazia."
            )
        return self

    diretorio_imagens: str = "/dados/imagens"
    """Pasta onde as imagens do catálogo são gravadas (nunca no banco — só a referência)."""

    diretorio_dicionarios: str = "dictdata"
    """Pasta com os dicionários StarDict (RL19). Ausente ou vazia não é erro: a consulta devolve vazio. No Docker, o
    ``docker-compose.yml`` a monta somente leitura em ``/dicionarios``."""


@lru_cache
def obter_configuracoes() -> Configuracoes:
    """Devolve as configurações da aplicação, lendo o ambiente uma única vez.

    O ``lru_cache`` faz com que o arquivo ``.env`` seja lido apenas na primeira
    chamada; as seguintes recebem o mesmo objeto já pronto. Além de evitar
    leitura repetida de disco, isso dá um ponto único para os testes
    substituírem a configuração quando precisarem.
    """
    return Configuracoes()
