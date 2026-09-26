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

    chave_api_openrouter: str = ""
    """Chave de API do OpenRouter. Vazia enquanto a Etapa 4 não for implementada."""

    diretorio_imagens: str = "/dados/imagens"
    """Pasta onde as imagens do catálogo são gravadas (nunca no banco — só a referência)."""


@lru_cache
def obter_configuracoes() -> Configuracoes:
    """Devolve as configurações da aplicação, lendo o ambiente uma única vez.

    O ``lru_cache`` faz com que o arquivo ``.env`` seja lido apenas na primeira
    chamada; as seguintes recebem o mesmo objeto já pronto. Além de evitar
    leitura repetida de disco, isso dá um ponto único para os testes
    substituírem a configuração quando precisarem.
    """
    return Configuracoes()
