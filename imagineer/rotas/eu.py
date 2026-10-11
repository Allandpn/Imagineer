"""``GET /eu``: quem o servidor acha que está falando com ele (CT12)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao, obter_usuario
from imagineer.modelos import Livro, Usuario
from imagineer.servicos.limites import cota_efetiva_em_gb, obter_limites, uso_da_pessoa_em_bytes

rotas = APIRouter(tags=["Contas"])


class EuAtual(BaseModel):
    """A pessoa do pedido. Serve ao app para mostrar "conectado como…" e esconder o que não é dela."""

    id: int
    login: str | None = Field(description="O login do Tailscale (e-mail). Nulo no modo `pessoal`.")
    nome: str | None
    dono: bool
    usa_chaves_do_servidor: bool = Field(
        description="Se esta pessoa gasta as chaves de IA do servidor (CT9). Falso = precisa informar a própria chave do OpenRouter no app."
    )
    livros: int = Field(default=0, description="Quantos livros a pessoa tem (item 7.5g, PF1: a tela Perfil).")
    uso_em_bytes: int = Field(default=0, description="O espaço que as imagens, os vídeos e os áudios dos livros dela ocupam no servidor.")
    cota_efetiva_em_gb: int | None = Field(default=None, description="A cota que vale para ela agora; nula para o dono, que não tem cota.")


@rotas.get("/eu", response_model=EuAtual, summary="Quem sou eu para o servidor")
def ver_quem_sou(usuario: Usuario = Depends(obter_usuario), sessao: Session = Depends(obter_sessao)) -> EuAtual:
    """Devolve a pessoa que fez o pedido. Em modo `pessoal` é sempre o dono; em `tailscale`, quem o proxy identificou. Traz também, para a tela
    Perfil, quantos livros ela tem e quanto espaço usa (item 7.5g, PF1)."""
    livros = sessao.scalar(select(func.count(Livro.id)).where(Livro.usuario_id == usuario.id))
    return EuAtual(
        id=usuario.id,
        login=usuario.login,
        nome=usuario.nome,
        dono=usuario.dono,
        usa_chaves_do_servidor=usuario.usa_chaves_do_servidor,
        livros=int(livros or 0),
        uso_em_bytes=uso_da_pessoa_em_bytes(sessao, usuario.id),
        cota_efetiva_em_gb=cota_efetiva_em_gb(obter_limites(sessao), usuario),
    )
