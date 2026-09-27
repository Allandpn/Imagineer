"""De onde vem a chave e qual modelo usar (item 4.3 da especificação).

A chave de API pode vir de dois lugares: da variável de ambiente
``CHAVE_API_OPENROUTER`` ou do banco, cadastrada pelo app. **O banco tem
precedência**, porque é a fonte que o usuário acabou de mexer — se ele cadastrou
uma chave pela tela, é essa que ele espera que valha.

A variável de ambiente existe para o sistema subir já configurado e para nunca
obrigar a chave a passar pelo banco. O cadastro pelo app existe porque o servidor
roda num Raspberry Pi: trocar de chave não deveria exigir SSH e reiniciar o
container.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from imagineer.configuracao import obter_configuracoes
from imagineer.ia.openrouter import ProvedorOpenRouter
from imagineer.ia.provedor import ProvedorIA
from imagineer.modelos.configuracao import ID_UNICO, Configuracao


@dataclass
class ChaveResolvida:
    """A chave em uso e de onde ela veio."""

    valor: str | None
    origem: str
    """``"banco"``, ``"ambiente"`` ou ``"ausente"`` — nunca a chave em si."""


def obter_ou_criar(sessao: Session) -> Configuracao:
    """Devolve a linha de configuração, criando-a vazia se ainda não existir.

    Criar sob demanda evita ter que semear a tabela numa migration, e mantém o
    sistema funcionando num banco recém-criado.
    """
    configuracao = sessao.get(Configuracao, ID_UNICO)
    if configuracao is None:
        configuracao = Configuracao(id=ID_UNICO)
        sessao.add(configuracao)
        sessao.commit()
        sessao.refresh(configuracao)
    return configuracao


def resolver_chave(sessao: Session) -> ChaveResolvida:
    """Decide qual chave usar, e informa a origem sem revelar o valor."""
    do_banco = (obter_ou_criar(sessao).chave_api_openrouter or "").strip()
    if do_banco:
        return ChaveResolvida(valor=do_banco, origem="banco")

    do_ambiente = (obter_configuracoes().chave_api_openrouter or "").strip()
    if do_ambiente:
        return ChaveResolvida(valor=do_ambiente, origem="ambiente")

    return ChaveResolvida(valor=None, origem="ausente")


def construir_provedor(sessao: Session) -> ProvedorIA:
    """Monta o provedor de IA com a chave que vale agora.

    As rotas dependem desta função, e não de uma instância global. É o que permite
    aos testes substituírem o provedor inteiro por um falso, e o que faz uma troca
    de chave valer no pedido seguinte sem reiniciar o serviço.
    """
    return ProvedorOpenRouter(chave_api=resolver_chave(sessao).valor)
