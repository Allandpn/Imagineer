"""Rotas do administrador: os limites do servidor (itens CT15 a CT20). **Só o dono** as enxerga; para os demais é 404, como nas outras rotas."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao, obter_usuario
from imagineer.modelos import DONO_ID, Livro, Usuario
from imagineer.servicos.limites import (
    BYTES_POR_GB,
    cota_efetiva_em_gb,
    FRACAO_MAXIMA_DO_ARMAZENAMENTO,
    limpar_cache_do_uso,
    obter_limites,
    uso_da_aplicacao_em_bytes,
    uso_da_pessoa_em_bytes,
)

rotas = APIRouter(prefix="/admin", tags=["Administração"])

_MAXIMO = 1_000_000


def _exigir_dono(usuario: Usuario = Depends(obter_usuario)) -> Usuario:
    """404 (e não 403) para quem não é o dono: a rota nem "existe" para os outros."""
    if not usuario.dono:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return usuario


class LimitesAtuais(BaseModel):
    """O que ``GET /admin/limites`` devolve: os limites e o quanto do espaço já está usado."""

    model_config = ConfigDict(from_attributes=True)

    tamanho_maximo_do_video_mb: int
    tamanho_maximo_do_epub_mb: int
    tamanho_maximo_da_imagem_mb: int
    caracteres_maximos_da_narracao: int
    armazenamento_total_em_gb: int
    cota_por_pessoa_em_gb: int
    uso_da_aplicacao_em_bytes: int = Field(description="O que a aplicação ocupa em disco agora (imagens, vídeos e áudios).")
    recusa_novos_arquivos_a_partir_de_bytes: int = Field(description="90% do armazenamento total: daí em diante, uploads e gerações dão 507.")


class LimitesNovos(BaseModel):
    """O que ``PUT /admin/limites`` aceita: só os campos presentes mudam; cada valor é um inteiro maior que zero."""

    model_config = ConfigDict(extra="forbid")

    tamanho_maximo_do_video_mb: int | None = Field(default=None, gt=0, le=_MAXIMO)
    tamanho_maximo_do_epub_mb: int | None = Field(default=None, gt=0, le=_MAXIMO)
    tamanho_maximo_da_imagem_mb: int | None = Field(default=None, gt=0, le=_MAXIMO)
    caracteres_maximos_da_narracao: int | None = Field(default=None, gt=0, le=_MAXIMO * 10)
    armazenamento_total_em_gb: int | None = Field(default=None, gt=0, le=_MAXIMO)
    cota_por_pessoa_em_gb: int | None = Field(default=None, gt=0, le=_MAXIMO)


def _atuais(sessao: Session) -> LimitesAtuais:
    limites = obter_limites(sessao)
    return LimitesAtuais(
        **{c: getattr(limites, c) for c in LimitesNovos.model_fields},
        uso_da_aplicacao_em_bytes=uso_da_aplicacao_em_bytes(),
        recusa_novos_arquivos_a_partir_de_bytes=int(limites.armazenamento_total_em_gb * BYTES_POR_GB * FRACAO_MAXIMA_DO_ARMAZENAMENTO),
    )


@rotas.get("/limites", response_model=LimitesAtuais, summary="Os limites do servidor e o espaço usado (só o dono)")
def ver_limites(sessao: Session = Depends(obter_sessao), _: Usuario = Depends(_exigir_dono)) -> LimitesAtuais:
    """Os limites de tamanho de arquivo, o teto da narração, o armazenamento da aplicação e a cota por pessoa (CT15 a CT18)."""
    limpar_cache_do_uso()
    return _atuais(sessao)


@rotas.put("/limites", response_model=LimitesAtuais, summary="Muda os limites do servidor (só o dono)")
def gravar_limites(novos: LimitesNovos, sessao: Session = Depends(obter_sessao), _: Usuario = Depends(_exigir_dono)) -> LimitesAtuais:
    """Só os campos enviados mudam. Vale no pedido seguinte, sem reiniciar o servidor."""
    limites = obter_limites(sessao)
    for campo, valor in novos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(limites, campo, valor)
    sessao.commit()
    limpar_cache_do_uso()
    return _atuais(sessao)


# --------------------------------------------------------------------------- #
# Contas (CT21 a CT23)
# --------------------------------------------------------------------------- #


class UsuarioDaLista(BaseModel):
    """Uma conta, como o dono a vê em ``GET /admin/usuarios``."""

    id: int
    login: str | None
    nome: str | None
    dono: bool
    usa_chaves_do_servidor: bool
    cota_em_gb: int | None = Field(description="A cota **própria** da pessoa; nulo = usa o padrão de `/admin/limites`.")
    cota_efetiva_em_gb: int | None = Field(description="A cota que vale agora; nulo para o dono, que não tem cota.")
    livros: int = Field(description="Quantos livros a pessoa tem (os da lixeira contam: ainda ocupam espaço).")
    uso_em_bytes: int = Field(description="Imagens, vídeos e áudios dos livros dela.")
    criado_em: datetime


class UsuarioAjuste(BaseModel):
    """O que ``PATCH /admin/usuarios/{id}`` aceita: só os campos enviados mudam."""

    model_config = ConfigDict(extra="forbid")

    usa_chaves_do_servidor: bool | None = Field(default=None, description="Libera (`true`) ou tira (`false`) as chaves de IA do servidor.")
    cota_em_gb: int | None = Field(default=None, gt=0, le=_MAXIMO, description="Cota própria; `null` volta ao padrão.")


def _linha_da_conta(sessao: Session, usuario: Usuario) -> UsuarioDaLista:
    limites = obter_limites(sessao)
    livros = sessao.scalar(select(func.count(Livro.id)).where(Livro.usuario_id == usuario.id))
    return UsuarioDaLista(
        id=usuario.id,
        login=usuario.login,
        nome=usuario.nome,
        dono=usuario.dono,
        usa_chaves_do_servidor=usuario.usa_chaves_do_servidor,
        cota_em_gb=usuario.cota_em_gb,
        cota_efetiva_em_gb=cota_efetiva_em_gb(limites, usuario),
        livros=int(livros or 0),
        uso_em_bytes=uso_da_pessoa_em_bytes(sessao, usuario.id),
        criado_em=usuario.criado_em,
    )


@rotas.get("/usuarios", response_model=list[UsuarioDaLista], summary="As contas, com o uso de espaço de cada uma (só o dono)")
def listar_usuarios(sessao: Session = Depends(obter_sessao), _: Usuario = Depends(_exigir_dono)) -> list[UsuarioDaLista]:
    """Todas as contas, o dono primeiro e depois por ordem de chegada (CT21)."""
    return [_linha_da_conta(sessao, u) for u in sessao.scalars(select(Usuario).order_by(Usuario.id))]


@rotas.patch("/usuarios/{usuario_id}", response_model=UsuarioDaLista, summary="Libera as chaves do servidor ou muda a cota de uma conta (só o dono)")
def ajustar_usuario(
    usuario_id: int, ajuste: UsuarioAjuste, sessao: Session = Depends(obter_sessao), _: Usuario = Depends(_exigir_dono)
) -> UsuarioDaLista:
    """Só os campos enviados mudam (CT22). O dono não pode ficar sem as chaves nem ganhar cota."""
    usuario = sessao.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não existe usuário com id {usuario_id}.")
    campos = ajuste.model_dump(exclude_unset=True)
    if usuario.id == DONO_ID and (campos.get("usa_chaves_do_servidor") is False or campos.get("cota_em_gb") is not None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O dono não pode ficar sem as chaves do servidor nem ganhar cota.",
        )
    if campos.get("usa_chaves_do_servidor") is None:
        campos.pop("usa_chaves_do_servidor", None)  # `null` não desliga nada: só `false` desliga
    for campo, valor in campos.items():
        setattr(usuario, campo, valor)
    sessao.commit()
    return _linha_da_conta(sessao, usuario)
