"""Rotas dos modelos de IA por livro (item 7.5g, MV3): ver o que vale para o livro e trocar por livro."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.modelos import Livro
from imagineer.rotas._comum import buscar_livro
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.modelos_do_livro import CAMPOS_DE_MODELO_DO_LIVRO, trocas_do_livro

rotas = APIRouter(prefix="/livros", tags=["Modelos por livro"])


class TrocasDeModelos(BaseModel):
    """O corpo de `PUT /livros/{id}/modelos`: as trocas do livro, **todas de uma vez**. Campo ausente, `null` ou vazio = sem troca (vale o global).
    Um campo que não é de modelo é recusado (422)."""

    model_config = ConfigDict(extra="forbid")

    modelo_extracao: str | None = Field(default=None, max_length=200)
    modelo_prompt: str | None = Field(default=None, max_length=200)
    modelo_leitura: str | None = Field(default=None, max_length=200)
    modelo_reserva: str | None = Field(default=None, max_length=200)
    modelo_conferencia: str | None = Field(default=None, max_length=200)
    modelo_perfil: str | None = Field(default=None, max_length=200)
    modelo_imagem: str | None = Field(default=None, max_length=200)
    modelo_suavizacao: str | None = Field(default=None, max_length=200)
    modelo_traducao: str | None = Field(default=None, max_length=200)
    modelo_video: str | None = Field(default=None, max_length=200)
    modelo_narracao: str | None = Field(default=None, max_length=200)
    narracao_voz: str | None = Field(default=None, max_length=100)


class ModeloEmUso(BaseModel):
    """O que vale para uma tarefa neste livro e de onde vem."""

    modelo: str | None = Field(description="O modelo (ou a voz) que vale; nulo = nenhum escolhido nem no livro nem na configuração global.")
    origem: Literal["livro", "global"] = Field(description="`livro`: o livro o trocou; `global`: vale o da configuração geral.")


class ModelosDoLivro(BaseModel):
    """As trocas do livro e o que vale, tarefa por tarefa."""

    trocas: dict[str, str] = Field(description="Só o que o livro trocou, com as mesmas chaves da configuração.")
    valendo: dict[str, ModeloEmUso] = Field(description="Uma entrada por tarefa (todas as chaves de modelo), com o que vale e a origem.")


def _resposta(sessao: Session, livro: Livro) -> ModelosDoLivro:
    base = obter_ou_criar(sessao)
    trocas = trocas_do_livro(livro)
    valendo = {
        campo: ModeloEmUso(modelo=trocas.get(campo) or (getattr(base, campo, None) or None), origem="livro" if campo in trocas else "global")
        for campo in CAMPOS_DE_MODELO_DO_LIVRO
    }
    return ModelosDoLivro(trocas=trocas, valendo=valendo)


@rotas.get("/{livro_id}/modelos", response_model=ModelosDoLivro, summary="As trocas de modelo do livro e o que vale em cada tarefa")
def ver_modelos_do_livro(livro_id: int, sessao: Session = Depends(obter_sessao)) -> ModelosDoLivro:
    """Para cada tarefa, o modelo que vale **neste livro** e se ele vem do livro ou da configuração global (MV3). Não gasta nada."""
    return _resposta(sessao, buscar_livro(sessao, livro_id))


@rotas.put("/{livro_id}/modelos", response_model=ModelosDoLivro, summary="Troca os modelos do livro (todas as trocas de uma vez)")
def trocar_modelos_do_livro(livro_id: int, corpo: TrocasDeModelos, sessao: Session = Depends(obter_sessao)) -> ModelosDoLivro:
    """**Substitui** as trocas do livro pelas do corpo (MV3): o que não vem, ou vem `null` ou vazio, deixa de ser troca e volta a valer o global.
    Sem nenhuma troca, a coluna fica nula. Não mexe na configuração global nem sobe a `revisao` do livro."""
    livro = buscar_livro(sessao, livro_id)
    novas = {campo: valor.strip() for campo, valor in corpo.model_dump().items() if valor and valor.strip()}
    livro.modelos = novas or None
    sessao.commit()
    sessao.refresh(livro)
    return _resposta(sessao, livro)
