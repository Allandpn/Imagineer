"""Rotas do dicionário (RL19): consulta de palavras nos dicionários StarDict da pasta do servidor."""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from imagineer.configuracao import obter_configuracoes
from imagineer.servicos import dicionarios as servico

rotas = APIRouter(prefix="/dicionario", tags=["Dicionário"])


class DicionarioDisponivel(BaseModel):
    id: str
    nome: str
    idioma_das_entradas: str | None
    palavras: int
    padrao_para: list[str]


class VerbeteResposta(BaseModel):
    dicionario_id: str
    dicionario: str
    entrada: str
    texto: str


class ConsultaResposta(BaseModel):
    palavra: str
    resultados: list[VerbeteResposta]


@lru_cache
def _dicionarios_da_pasta(pasta: str) -> list[servico.Dicionario]:
    """Descobre os dicionários **uma vez por pasta** (os índices só são montados na primeira consulta de cada um)."""
    return servico.descobrir_dicionarios(Path(pasta))


def obter_dicionarios() -> list[servico.Dicionario]:
    """Os dicionários da pasta configurada. Existe como dependência para os testes apontarem para outra pasta."""
    return _dicionarios_da_pasta(obter_configuracoes().diretorio_dicionarios)


@rotas.get("/dicionarios", response_model=list[DicionarioDisponivel], summary="Os dicionários que há na pasta do servidor")
def listar_dicionarios(dicionarios: list[servico.Dicionario] = Depends(obter_dicionarios)) -> list[servico.Dicionario]:
    """A lista do que o servidor encontrou, com o idioma das entradas e para quais idiomas de livro cada um é consultado."""
    return dicionarios


@rotas.get("/verbete", response_model=ConsultaResposta, summary="Procura uma palavra nos dicionários")
def procurar_verbete(
    palavra: str = Query(min_length=1, max_length=200, description="A palavra selecionada no texto."),
    idioma: str | None = Query(default=None, description="O idioma do livro (pt, pt-BR, en-US...): decide quais dicionários valem."),
    todos: bool = Query(default=False, description="Consulta **todos** os dicionários, ignorando o idioma."),
    dicionarios: list[servico.Dicionario] = Depends(obter_dicionarios),
) -> ConsultaResposta:
    """Os verbetes da palavra, um bloco por dicionário; ``resultados`` vazio quando nada foi achado."""
    limpa, achados = servico.consultar(dicionarios, palavra, idioma, todos)
    return ConsultaResposta(
        palavra=limpa,
        resultados=[
            VerbeteResposta(
                dicionario_id=a.dicionario.id, dicionario=a.dicionario.nome, entrada=a.verbete.entrada, texto=a.verbete.texto
            )
            for a in achados
        ],
    )
