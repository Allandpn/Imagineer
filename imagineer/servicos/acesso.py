"""O isolamento entre usuários: de quem é cada coisa, e se o pedido pode vê-la (CT5, CT6).

**O usuário do pedido vai na própria sessão do banco** (``sessao.info["usuario_id"]``, posto por ``obter_sessao``): a sessão já viaja por todo
helper e rota, então ninguém precisa receber um parâmetro novo. **Sessão sem usuário = sem escopo** (CT6-d): o segundo plano e os testes que a
montam à mão funcionam como antes das contas; quem chama já recebeu ids de um pedido conferido.

O dono de qualquer coisa é o dono do **livro** de que ela depende (CT5). ``dono_de`` sobe a cadeia; um tipo que não sabe subir é **negado** (falha
fechada): ninguém esquece um tipo novo em silêncio, o teste de isolamento acusa.
"""

from typing import TypeVar

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from imagineer.modelos import (
    AudioDeCapitulo,
    Capitulo,
    Destaque,
    Elemento,
    EstadoElemento,
    Favorito,
    Frame,
    HistoricoIdentidadeElemento,
    Imagem,
    Livro,
    Marcador,
    PerfilRenderizacao,
    Pin,
    Prompt,
    SugestaoDeCena,
    SugestaoDeElemento,
    TempoDeLeitura,
    UsoDeIA,
    Video,
)
from imagineer.modelos.usuario import DONO_ID

T = TypeVar("T")

_CHAVE_DO_USUARIO = "usuario_id"
_CHAVE_DOS_DONOS = "_donos_dos_livros"


def definir_usuario(sessao: Session, usuario_id: int | None) -> None:
    """Põe o usuário do pedido na sessão (``obter_sessao`` faz isso). Troca o cache de donos: ele é do usuário anterior."""
    sessao.info[_CHAVE_DO_USUARIO] = usuario_id
    sessao.info.pop(_CHAVE_DOS_DONOS, None)


def usuario_da_sessao(sessao: Session) -> int | None:
    """O usuário do pedido, ou ``None`` se a sessão não tem (sem escopo)."""
    return sessao.info.get(_CHAVE_DO_USUARIO)


def usuario_ou_dono(sessao: Session) -> int:
    """O usuário do pedido; numa sessão sem usuário, o dono (o comportamento de antes das contas)."""
    return usuario_da_sessao(sessao) or DONO_ID


def livro_id_de(sessao: Session, objeto: object) -> int | None:
    """O id do livro de que ``objeto`` depende, subindo a cadeia; ``None`` se o tipo não tem livro ou não é conhecido."""
    if isinstance(objeto, Livro):
        return objeto.id
    if isinstance(objeto, (Capitulo, Elemento, Pin, Marcador, Destaque, Favorito, TempoDeLeitura)):
        return objeto.livro_id
    if isinstance(objeto, (EstadoElemento, HistoricoIdentidadeElemento)):
        return _livro_id_do(sessao, Elemento, objeto.elemento_id)
    if isinstance(objeto, (SugestaoDeElemento, SugestaoDeCena, AudioDeCapitulo, Frame)):
        return _livro_id_do(sessao, Capitulo, objeto.capitulo_id)
    if isinstance(objeto, Prompt):
        return _livro_id_do(sessao, Frame, objeto.frame_id)
    if isinstance(objeto, Imagem):
        return _livro_id_do(sessao, Prompt, objeto.prompt_id)
    if isinstance(objeto, Video):
        return _livro_id_do(sessao, Frame, objeto.frame_id)
    return None


def _livro_id_do(sessao: Session, modelo: type, id_: int | None) -> int | None:
    pai = sessao.get(modelo, id_) if id_ is not None else None
    return None if pai is None else livro_id_de(sessao, pai)


def dono_do_livro(sessao: Session, livro_id: int) -> int | None:
    """O ``usuario_id`` do livro, guardado na sessão (um livro nunca muda de dono)."""
    donos: dict[int, int | None] = sessao.info.setdefault(_CHAVE_DOS_DONOS, {})
    if livro_id not in donos:
        donos[livro_id] = sessao.scalar(select(Livro.usuario_id).where(Livro.id == livro_id))
    return donos[livro_id]


def pertence(sessao: Session, objeto: object) -> bool:
    """O pedido pode ver ``objeto``? Sempre sim numa sessão sem usuário.

    Perfil de renderização: o **de fábrica** (sem dono) é de todos; o próprio, só de quem o criou. Gasto de IA: sem dono = do dono (CT10)."""
    usuario_id = usuario_da_sessao(sessao)
    if usuario_id is None:
        return True
    if isinstance(objeto, PerfilRenderizacao):
        return objeto.usuario_id is None or objeto.usuario_id == usuario_id
    if isinstance(objeto, UsoDeIA):
        return (objeto.usuario_id or DONO_ID) == usuario_id
    livro_id = livro_id_de(sessao, objeto)
    return livro_id is not None and dono_do_livro(sessao, livro_id) == usuario_id


def buscar_visivel(sessao: Session, modelo: type[T], id_: int | None) -> T | None:
    """``sessao.get`` que devolve ``None`` também quando a coisa é de **outra pessoa** — para o chamador responder "não existe" como já fazia."""
    if id_ is None:
        return None
    objeto = sessao.get(modelo, id_)
    return objeto if objeto is not None and pertence(sessao, objeto) else None


def gastos_da_pessoa(sessao: Session) -> ColumnElement[bool]:
    """A condição "o gasto é da pessoa do pedido" para ``select(UsoDeIA)`` (CT10). Gasto **sem dono** é de antes das contas, ou seja, do dono."""
    usuario_id = usuario_ou_dono(sessao)
    if usuario_id == DONO_ID:
        return or_(UsoDeIA.usuario_id == usuario_id, UsoDeIA.usuario_id.is_(None))
    return UsoDeIA.usuario_id == usuario_id
