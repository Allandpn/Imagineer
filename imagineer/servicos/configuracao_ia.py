"""De onde vem a chave e qual modelo usar (item 4.3 da especificação).

A chave de API pode vir de dois lugares, nesta ordem de precedência:

1. o header ``X-Chave-API-OpenRouter`` da chamada — a chave pessoal de quem usa o
   app, guardada só no celular;
2. a variável de ambiente ``CHAVE_API_OPENROUTER`` — a chave do próprio servidor.

**O banco nunca guarda a chave.** Guardar a chave de cada usuário no servidor não
escala para mais de uma pessoa no mesmo backend, e a chave num backup de banco é
um vazamento esperando acontecer. O header vale só para a chamada em curso.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from imagineer.configuracao import obter_configuracoes
from imagineer.ia.openrouter import ProvedorOpenRouter
from imagineer.ia.provedor import ProvedorIA
from imagineer.modelos.configuracao import ID_UNICO, Configuracao
from imagineer.servicos.uso_de_ia import gravar_uso


@dataclass
class ChaveResolvida:
    """A chave em uso e de onde ela veio."""

    valor: str | None
    origem: str
    """``"cabecalho"``, ``"ambiente"`` ou ``"ausente"`` — nunca a chave em si."""


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


def resolver_chave(cabecalho: str | None = None) -> ChaveResolvida:
    """Decide qual chave usar, e informa a origem sem revelar o valor.

    ``cabecalho`` é o valor de ``X-Chave-API-OpenRouter``. Ausente, vazio ou só
    com espaços conta como ausente — um app que manda o header sempre, mesmo sem
    ter chave própria, não pode quebrar por isso.
    """
    do_cabecalho = (cabecalho or "").strip()
    if do_cabecalho:
        return ChaveResolvida(valor=do_cabecalho, origem="cabecalho")

    do_ambiente = (obter_configuracoes().chave_api_openrouter or "").strip()
    if do_ambiente:
        return ChaveResolvida(valor=do_ambiente, origem="ambiente")

    return ChaveResolvida(valor=None, origem="ausente")


def construir_provedor(cabecalho: str | None = None) -> ProvedorIA:
    """Monta o provedor de IA com a chave que vale para esta chamada.

    As rotas dependem desta função (via ``obter_provedor``), e não de uma
    instância global. É o que permite aos testes substituírem o provedor inteiro
    por um falso, e o que faz uma troca de chave valer no pedido seguinte sem
    reiniciar o serviço.
    """
    return ProvedorOpenRouter(chave_api=resolver_chave(cabecalho).valor, ao_usar=gravar_uso)
