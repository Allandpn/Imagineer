"""``GET /eu``: quem o servidor acha que está falando com ele (CT12)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from imagineer.banco.sessao import obter_usuario
from imagineer.modelos import Usuario

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


@rotas.get("/eu", response_model=EuAtual, summary="Quem sou eu para o servidor")
def ver_quem_sou(usuario: Usuario = Depends(obter_usuario)) -> EuAtual:
    """Devolve a pessoa que fez o pedido. Em modo `pessoal` é sempre o dono; em `tailscale`, quem o proxy identificou."""
    return EuAtual(
        id=usuario.id,
        login=usuario.login,
        nome=usuario.nome,
        dono=usuario.dono,
        usa_chaves_do_servidor=usuario.usa_chaves_do_servidor,
    )
