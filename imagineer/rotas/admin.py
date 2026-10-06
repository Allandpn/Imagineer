"""Rotas do administrador: os limites do servidor (itens CT15 a CT20). **Só o dono** as enxerga; para os demais é 404, como nas outras rotas."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao, obter_usuario
from imagineer.modelos import Usuario
from imagineer.servicos.limites import (
    BYTES_POR_GB,
    FRACAO_MAXIMA_DO_ARMAZENAMENTO,
    limpar_cache_do_uso,
    obter_limites,
    uso_da_aplicacao_em_bytes,
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
