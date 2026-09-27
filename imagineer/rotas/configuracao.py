"""Rotas de configuração da integração com IA (Etapas 4.3 e 6.7)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.ia.provedor import ErroDoProvedorIA, ProvedorIA
from imagineer.servicos.configuracao_ia import (
    construir_provedor,
    obter_ou_criar,
    resolver_chave,
)

rotas = APIRouter(prefix="/configuracao", tags=["Configuração"])


def obter_provedor(sessao: Session = Depends(obter_sessao)) -> ProvedorIA:
    """Dependência que entrega o provedor de IA já configurado.

    Existe como dependência do FastAPI, e não como objeto global, para os testes
    poderem substituí-la por um provedor falso — e para uma troca de chave valer
    no pedido seguinte, sem reiniciar o serviço.
    """
    return construir_provedor(sessao)


class ConfiguracaoAtual(BaseModel):
    """O que `GET /configuracao` devolve.

    **Nunca inclui a chave de API**, só se ela existe e de onde veio. Uma chave que
    sai do servidor é uma chave que vaza em log, em cache de app ou numa captura
    de tela.
    """

    tem_chave_api: bool
    origem_da_chave: str = Field(
        description='"banco", "ambiente" ou "ausente" — nunca a chave em si.'
    )
    modelo_extracao: str | None
    modelo_prompt: str | None


class ConfiguracaoNova(BaseModel):
    """O que o app manda para gravar a configuração.

    Só os campos presentes são aplicados. Mandar `chave_api_openrouter` como
    string vazia **apaga** a chave do banco, fazendo a variável de ambiente voltar
    a valer — é assim que se desfaz um cadastro.
    """

    chave_api_openrouter: str | None = Field(default=None, max_length=200)
    modelo_extracao: str | None = Field(default=None, max_length=200)
    modelo_prompt: str | None = Field(default=None, max_length=200)


class ModeloDaLista(BaseModel):
    """Um modelo na tela de escolha."""

    id: str
    nome: str
    contexto: int = Field(description="Janela de contexto em tokens.")
    gratuito: bool


@rotas.get("", response_model=ConfiguracaoAtual, summary="A configuração atual")
def ver_configuracao(sessao: Session = Depends(obter_sessao)) -> ConfiguracaoAtual:
    """Diz quais modelos estão escolhidos e se há chave — sem devolver a chave."""
    configuracao = obter_ou_criar(sessao)
    chave = resolver_chave(sessao)

    return ConfiguracaoAtual(
        tem_chave_api=chave.valor is not None,
        origem_da_chave=chave.origem,
        modelo_extracao=configuracao.modelo_extracao,
        modelo_prompt=configuracao.modelo_prompt,
    )


@rotas.put("", response_model=ConfiguracaoAtual, summary="Grava a configuração")
def gravar_configuracao(
    nova: ConfiguracaoNova, sessao: Session = Depends(obter_sessao)
) -> ConfiguracaoAtual:
    """Cadastra a chave e escolhe os modelos.

    Uma chave vazia apaga o cadastro e devolve a vez à variável de ambiente.
    """
    configuracao = obter_ou_criar(sessao)

    for campo, valor in nova.model_dump(exclude_unset=True).items():
        # String vazia e nulo significam a mesma coisa aqui: "não tenho isto".
        setattr(configuracao, campo, (valor or "").strip() or None)

    sessao.commit()
    return ver_configuracao(sessao)


@rotas.get(
    "/modelos",
    response_model=list[ModeloDaLista],
    summary="Lista os modelos disponíveis no OpenRouter",
)
def listar_modelos(
    somente_gratuitos: bool = Query(
        default=False, description="Mostra só os modelos que não custam nada."
    ),
    contexto_minimo: int = Query(
        default=0,
        ge=0,
        description=(
            "Filtra por janela de contexto mínima. O maior capítulo dos livros de "
            "validação ocupa cerca de 28 mil tokens, então 32000 é um bom valor."
        ),
    ),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> list[ModeloDaLista]:
    """Os modelos de texto do OpenRouter, para a tela de escolha.

    Funciona **sem chave cadastrada**: o endpoint de modelos do OpenRouter é
    público. É o que permite o usuário ver a lista antes de configurar a chave, que
    é a ordem em que ele faz as coisas.
    """
    try:
        modelos = provedor.listar_modelos()
    except ErroDoProvedorIA as erro:
        # 502: o problema não é do pedido nem nosso, é do serviço de fora.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(erro)
        ) from erro

    return [
        ModeloDaLista(
            id=modelo.id, nome=modelo.nome, contexto=modelo.contexto, gratuito=modelo.gratuito
        )
        for modelo in modelos
        if (not somente_gratuitos or modelo.gratuito)
        and modelo.contexto >= contexto_minimo
    ]
