"""Rotas do dicionário (RL19): consulta de palavras nos dicionários StarDict da pasta do servidor."""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.configuracao import obter_configuracoes
from imagineer.servicos import dicionarios as servico
from imagineer.servicos.configuracao_ia import obter_ou_criar

rotas = APIRouter(prefix="/dicionario", tags=["Dicionário"])


class DicionarioDisponivel(BaseModel):
    id: str
    nome: str
    idioma_das_entradas: str | None
    palavras: int
    padrao_para: list[str]
    ativo: bool = Field(description="Se a pessoa deixou este dicionário ligado (RL29). Desligado, nunca é consultado.")


class PreferenciasDosDicionarios(BaseModel):
    """O que a pessoa escolheu na tela de dicionários (RL28): a ordem de preferência e quais ficam desligados."""

    model_config = ConfigDict(extra="forbid")

    ordem: list[str] = Field(max_length=100, description="Os identificadores, do preferido ao último.")
    desativados: list[str] = Field(max_length=100, description="Os identificadores que não devem ser consultados.")


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


def ordenar_por_preferencia(dicionarios: list[servico.Dicionario], ordem: list[str]) -> list[servico.Dicionario]:
    """Os dicionários na ordem de preferência (RL29): os da ``ordem`` primeiro, **na ordem dela**; os que ela não cita (um arquivo novo
    na pasta) vão para o fim, **na ordem em que já estavam**; um identificador que não existe mais é ignorado."""
    posicao = {identificador: i for i, identificador in enumerate(ordem)}
    return sorted(dicionarios, key=lambda d: posicao.get(d.id, len(posicao)))  # sorted é estável: o resto mantém a ordem


def _como_disponivel(d: servico.Dicionario, desativados: set[str]) -> DicionarioDisponivel:
    return DicionarioDisponivel(
        id=d.id,
        nome=d.nome,
        idioma_das_entradas=d.idioma_das_entradas,
        palavras=d.palavras,
        padrao_para=d.padrao_para,
        ativo=d.id not in desativados,
    )


@rotas.get("/dicionarios", response_model=list[DicionarioDisponivel], summary="Os dicionários que há na pasta do servidor, na ordem de preferência")
def listar_dicionarios(
    dicionarios: list[servico.Dicionario] = Depends(obter_dicionarios), sessao: Session = Depends(obter_sessao)
) -> list[DicionarioDisponivel]:
    """A lista do que o servidor encontrou, **na ordem de preferência da pessoa**, com o idioma das entradas, para quais idiomas de
    livro cada um é consultado e se está ligado (RL29)."""
    configuracao = obter_ou_criar(sessao)
    desativados = set(configuracao.dicionarios_desativados or [])
    return [_como_disponivel(d, desativados) for d in ordenar_por_preferencia(dicionarios, list(configuracao.ordem_dos_dicionarios or []))]


@rotas.put("/preferencias", response_model=list[DicionarioDisponivel], summary="Grava a ordem e quais dicionários ficam ligados")
def gravar_preferencias(
    preferencias: PreferenciasDosDicionarios,
    dicionarios: list[servico.Dicionario] = Depends(obter_dicionarios),
    sessao: Session = Depends(obter_sessao),
) -> list[DicionarioDisponivel]:
    """**Substitui** a ordem e a lista de desligados (RL29). Um identificador que o servidor não conhece é recusado (422): um erro de
    digitação engolido em silêncio faria a pessoa achar que o dicionário foi desligado."""
    conhecidos = {d.id for d in dicionarios}
    desconhecidos = [i for i in [*preferencias.ordem, *preferencias.desativados] if i not in conhecidos]
    if desconhecidos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Dicionário desconhecido: {', '.join(dict.fromkeys(desconhecidos))}.",
        )
    configuracao = obter_ou_criar(sessao)
    configuracao.ordem_dos_dicionarios = list(dict.fromkeys(preferencias.ordem))
    configuracao.dicionarios_desativados = list(dict.fromkeys(preferencias.desativados))
    sessao.commit()
    return listar_dicionarios(dicionarios, sessao)


@rotas.get("/verbete", response_model=ConsultaResposta, summary="Procura uma palavra nos dicionários")
def procurar_verbete(
    palavra: str = Query(min_length=1, max_length=200, description="A palavra selecionada no texto."),
    idioma: str | None = Query(default=None, description="O idioma do livro (pt, pt-BR, en-US...): decide quais dicionários valem."),
    todos: bool = Query(default=False, description="Consulta **todos** os dicionários, ignorando o idioma."),
    dicionarios: list[servico.Dicionario] = Depends(obter_dicionarios),
    sessao: Session = Depends(obter_sessao),
) -> ConsultaResposta:
    """Os verbetes da palavra, um bloco por dicionário, **na ordem de preferência** e **sem os desligados** (RL29); ``resultados`` vazio
    quando nada foi achado."""
    configuracao = obter_ou_criar(sessao)
    desativados = set(configuracao.dicionarios_desativados or [])
    ligados = [d for d in ordenar_por_preferencia(dicionarios, list(configuracao.ordem_dos_dicionarios or [])) if d.id not in desativados]
    limpa, achados = servico.consultar(ligados, palavra, idioma, todos)
    return ConsultaResposta(
        palavra=limpa,
        resultados=[
            VerbeteResposta(
                dicionario_id=a.dicionario.id, dicionario=a.dicionario.nome, entrada=a.verbete.entrada, texto=a.verbete.texto
            )
            for a in achados
        ],
    )
