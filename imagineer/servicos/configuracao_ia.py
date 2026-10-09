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
from functools import partial

from sqlalchemy.orm import Session

from imagineer.configuracao import obter_configuracoes
from imagineer.ia.fornecedores_de_imagem import montar_geradores
from imagineer.ia.openrouter import ProvedorOpenRouter
from imagineer.ia.provedor import ProvedorIA
from imagineer.modelos.configuracao import Configuracao
from imagineer.modelos.usuario import Usuario
from imagineer.servicos.acesso import usuario_ou_dono
from imagineer.servicos.uso_de_ia import gravar_uso


@dataclass
class ChaveResolvida:
    """A chave em uso e de onde ela veio."""

    valor: str | None
    origem: str
    """``"cabecalho"``, ``"ambiente"`` ou ``"ausente"`` — nunca a chave em si."""


def obter_ou_criar(sessao: Session) -> Configuracao:
    """Devolve a configuração **da pessoa do pedido** (CT8), criando-a vazia se ainda não existir.

    Cada usuário tem a sua linha: o ``id`` dela é o id do usuário. Criar sob demanda evita semear a tabela numa migration — e é o que
    dá a cada pessoa nova uma configuração própria na primeira visita. Sessão sem usuário = a do dono, como antes das contas.
    """
    usuario_id = usuario_ou_dono(sessao)
    configuracao = sessao.get(Configuracao, usuario_id)
    if configuracao is None:
        configuracao = Configuracao(id=usuario_id)
        sessao.add(configuracao)
        sessao.commit()
        sessao.refresh(configuracao)
    return configuracao


def modelo_de_leitura(configuracao: Configuracao) -> str | None:
    """O modelo que **lê o capítulo** para descrever um elemento ou uma cena (item 4.10, LM12).

    A cadeia: ``modelo_leitura`` → ``modelo_extracao`` → ``modelo_prompt``. Quem ainda não escolheu um modelo só para a leitura continua
    com o de extração, como era antes dele existir; e quem só tem o de prompt, com ele. ``None`` = nenhum dos três foi escolhido."""
    return configuracao.modelo_leitura or configuracao.modelo_extracao or configuracao.modelo_prompt


def ler_modelo_reserva(sessao: Session, usuario_id: int) -> str | None:
    """O ``modelo_reserva`` da pessoa, ou ``None``. **Só lê**: não cria a linha de configuração (quem nunca configurou nada não ganha uma)."""
    configuracao = sessao.get(Configuracao, usuario_id)
    return configuracao.modelo_reserva if configuracao is not None else None


def resolver_chave(cabecalho: str | None = None, usuario: Usuario | None = None) -> ChaveResolvida:
    """Decide qual chave usar, e informa a origem sem revelar o valor.

    ``cabecalho`` é o valor de ``X-Chave-API-OpenRouter``. Ausente, vazio ou só
    com espaços conta como ausente — um app que manda o header sempre, mesmo sem
    ter chave própria, não pode quebrar por isso.

    **A chave do servidor é do dono (CT9):** só entra se ``usuario`` pode usá-la (``usa_chaves_do_servidor``). ``usuario=None`` é o
    comportamento de antes das contas (testes e segundo plano): pode.
    """
    do_cabecalho = (cabecalho or "").strip()
    if do_cabecalho:
        return ChaveResolvida(valor=do_cabecalho, origem="cabecalho")

    if usuario is not None and not usuario.usa_chaves_do_servidor:
        return ChaveResolvida(valor=None, origem="ausente")

    do_ambiente = (obter_configuracoes().chave_api_openrouter or "").strip()
    if do_ambiente:
        return ChaveResolvida(valor=do_ambiente, origem="ambiente")

    return ChaveResolvida(valor=None, origem="ausente")


def _chave_de_imagem(do_cabecalho: str | None, do_servidor: str, usuario: Usuario | None) -> str | None:
    """A chave do fal.ai ou do Replicate: a do header (CT24); sem ela, a do servidor, **só** para quem pode usá-la (CT9)."""
    propria = (do_cabecalho or "").strip()
    if propria:
        return propria
    return do_servidor if usuario is None or usuario.usa_chaves_do_servidor else None


def construir_provedor(
    cabecalho: str | None = None,
    usuario: Usuario | None = None,
    chave_fal: str | None = None,
    chave_replicate: str | None = None,
    modelo_reserva: str | None = None,
) -> ProvedorIA:
    """Monta o provedor de IA com a chave que vale para esta chamada.

    As rotas dependem desta função (via ``obter_provedor``), e não de uma
    instância global. É o que permite aos testes substituírem o provedor inteiro
    por um falso, e o que faz uma troca de chave valer no pedido seguinte sem
    reiniciar o serviço.

    ``cabecalho``, ``chave_fal`` e ``chave_replicate`` são as chaves que o app mandou, uma por provedor (CT24); cada uma tem precedência sobre a do
    servidor. Com ``usuario``: o gasto de cada chamada é gravado **no nome dele** (CT10), e a chave do servidor só entra se ele a pode usar (CT9).

    ``modelo_reserva`` (4.10, LM13) é o modelo a que o OpenRouter recorre quando o principal de uma chamada de texto falha.
    """
    configuracoes = obter_configuracoes()
    return ProvedorOpenRouter(
        chave_api=resolver_chave(cabecalho, usuario).valor,
        modelo_reserva=modelo_reserva,
        ao_usar=gravar_uso if usuario is None else partial(gravar_uso, usuario_id=usuario.id),
        geradores_de_imagem=montar_geradores(
            _chave_de_imagem(chave_fal, configuracoes.chave_api_fal, usuario),
            _chave_de_imagem(chave_replicate, configuracoes.chave_api_replicate, usuario),
        ),
    )
