"""Rotas de configuração da integração com IA (Etapas 4.3 e 6.7)."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.configuracao import obter_configuracoes
from imagineer.ia.provedor import ProvedorIA
from imagineer.modelos import PrioridadeIA
from imagineer.servicos.configuracao_ia import (
    construir_provedor,
    obter_ou_criar,
    resolver_chave,
)

rotas = APIRouter(prefix="/configuracao", tags=["Configuração"])


def obter_provedor(
    chave_api_openrouter: str | None = Header(
        default=None,
        alias="X-Chave-API-OpenRouter",
        description=(
            "Chave pessoal do OpenRouter, guardada só no app. Tem precedência sobre "
            "a chave do servidor e nunca é gravada (item 4.3)."
        ),
    ),
) -> ProvedorIA:
    """Dependência que entrega o provedor de IA já configurado.

    Existe como dependência do FastAPI, e não como objeto global, para os testes
    poderem substituí-la por um provedor falso — e para uma troca de chave valer
    no pedido seguinte, sem reiniciar o serviço.
    """
    return construir_provedor(chave_api_openrouter)


class ConfiguracaoAtual(BaseModel):
    """O que `GET /configuracao` devolve.

    **Nunca inclui a chave de API**, só se ela existe e de onde veio. Uma chave que
    sai do servidor é uma chave que vaza em log, em cache de app ou numa captura
    de tela.
    """

    tem_chave_api: bool = Field(
        description="Se o *servidor* tem chave. Não considera o header do app."
    )
    origem_da_chave: str = Field(
        description='"ambiente" ou "ausente" — nunca a chave em si.'
    )
    modelo_extracao: str | None
    modelo_prompt: str | None
    modelo_perfil: str | None = Field(
        description=(
            "Modelo para sugerir perfil de renderização (item 6.5) — separado dos "
            "outros porque essa chamada é única por livro, não por capítulo, e "
            "compensa usar um modelo mais caro."
        )
    )
    modelo_imagem: str = Field(
        description=(
            "Modelo que gera a imagem a partir do prompt (modelo de imagem do OpenRouter). "
            "Nunca vazio: nasce `meta/muse-image`."
        )
    )
    fornecedores_de_imagem: dict[str, bool] = Field(
        description=(
            "Para cada fornecedor de imagem (`openrouter`, `fal`, `replicate`), se o **servidor** tem a chave dele "
            "(F2). Só diz se há chave; nunca a chave."
        )
    )
    modelos_de_imagem: list[str] = Field(
        description=(
            "Os modelos de imagem que o usuário pode escolher no app (Z2). O `modelo_imagem` é o padrão e "
            "aparece na escolha mesmo fora desta lista."
        )
    )
    modelos_com_referencia: dict[str, str] = Field(
        description=(
            "Os modelos de imagem que aceitam **imagens de referência**, e o parâmetro que recebe a lista (W1): "
            "`{\"replicate:bytedance/seedream-4.5\": \"image_input\"}`. Vazio = nenhum. O app só oferece escolher "
            "referências se o modelo em uso está aqui."
        )
    )
    modelos_sem_filtro: list[str] = Field(
        description=(
            "Os modelos de imagem em que o usuário pode pedir para desligar o filtro de segurança, depois de uma "
            "recusa (F12, F13). Vazia = nenhum. Só vale para `replicate:`; o app só oferece o botão se houver algum."
        )
    )
    modelo_suavizacao: str | None = Field(
        description=(
            "Modelo de texto que reescreve um prompt recusado pelo provedor de imagem. "
            "Vazio = usa o `modelo_prompt`."
        )
    )
    modelo_traducao: str | None = Field(
        description=(
            "Modelo de texto que traduz os prompts (português ↔ inglês). Vazio = usa o da suavização, "
            "senão o de extração, senão o de prompt."
        )
    )
    prioridade_ia: PrioridadeIA = Field(
        description=(
            "ECONOMIA (padrão) reaproveita leituras já feitas; QUALIDADE relê "
            "o capítulo toda vez que um prompt é montado (item 4.4)."
        )
    )


class ConfiguracaoNova(BaseModel):
    """O que o app manda para gravar a configuração.

    Só os campos presentes são aplicados. Campos desconhecidos são recusados (422)
    — em especial `chave_api_openrouter`, que já foi aceito: ignorá-lo em silêncio
    faria o usuário achar que a chave foi salva (item 4.3).
    """

    model_config = ConfigDict(extra="forbid")

    modelo_extracao: str | None = Field(default=None, max_length=200)
    modelo_prompt: str | None = Field(default=None, max_length=200)
    modelo_perfil: str | None = Field(default=None, max_length=200)
    modelo_imagem: str | None = Field(default=None, max_length=200)
    modelos_de_imagem: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=20)
    modelos_sem_filtro: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=20)
    modelos_com_referencia: (
        dict[
            Annotated[str, Field(max_length=200)],
            Annotated[str, Field(max_length=50, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")],
        ]
        | None
    ) = Field(default=None, max_length=20)
    modelo_suavizacao: str | None = Field(default=None, max_length=200)
    modelo_traducao: str | None = Field(default=None, max_length=200)
    prioridade_ia: PrioridadeIA | None = None


class ModeloDaLista(BaseModel):
    """Um modelo na tela de escolha."""

    id: str
    nome: str
    contexto: int = Field(description="Janela de contexto em tokens.")
    gratuito: bool
    suporta_json: bool = Field(
        description=(
            "Se o modelo aceita resposta estruturada/JSON. Modelos sem isso "
            "tendem a produzir o erro 'O modelo não devolveu JSON' (item 4.3)."
        )
    )
    custo_saida: float = Field(
        description="Preço por token de saída (US$), sempre presente mesmo sem filtrar por ele."
    )
    moderado: bool = Field(
        description="Se o modelo é moderado pelo provedor — pode rejeitar texto narrativo mais pesado."
    )


@rotas.get("", response_model=ConfiguracaoAtual, summary="A configuração atual")
def ver_configuracao(sessao: Session = Depends(obter_sessao)) -> ConfiguracaoAtual:
    """Diz quais modelos estão escolhidos e se há chave — sem devolver a chave."""
    configuracao = obter_ou_criar(sessao)
    chave = resolver_chave()  # sem header: só o que o servidor tem

    return ConfiguracaoAtual(
        tem_chave_api=chave.valor is not None,
        origem_da_chave=chave.origem,
        modelo_extracao=configuracao.modelo_extracao,
        modelo_prompt=configuracao.modelo_prompt,
        modelo_perfil=configuracao.modelo_perfil,
        modelo_imagem=configuracao.modelo_imagem,
        fornecedores_de_imagem={
            "openrouter": chave.valor is not None,
            "fal": bool(obter_configuracoes().chave_api_fal.strip()),
            "replicate": bool(obter_configuracoes().chave_api_replicate.strip()),
        },
        modelos_de_imagem=list(configuracao.modelos_de_imagem or []),
        modelos_sem_filtro=list(configuracao.modelos_sem_filtro or []),
        modelos_com_referencia=dict(configuracao.modelos_com_referencia or {}),
        modelo_suavizacao=configuracao.modelo_suavizacao,
        modelo_traducao=configuracao.modelo_traducao,
        prioridade_ia=configuracao.prioridade_ia,
    )


@rotas.put("", response_model=ConfiguracaoAtual, summary="Grava a configuração")
def gravar_configuracao(
    nova: ConfiguracaoNova, sessao: Session = Depends(obter_sessao)
) -> ConfiguracaoAtual:
    """Escolhe os modelos e a prioridade de IA. A chave não passa por aqui."""
    configuracao = obter_ou_criar(sessao)

    for campo, valor in nova.model_dump(exclude_unset=True).items():
        if campo == "prioridade_ia":
            # Não é campo de texto livre — não faz sentido "apagar" com string
            # vazia, então segue direto, sem a normalização abaixo.
            setattr(configuracao, campo, valor)
            continue
        if campo == "modelos_com_referencia":
            # W1: sem espaços nas pontas e sem chaves vazias.
            configuracao.modelos_com_referencia = {
                modelo.strip(): parametro for modelo, parametro in (valor or {}).items() if modelo.strip()
            }
            continue
        if campo in ("modelos_de_imagem", "modelos_sem_filtro"):
            # Z2/F13: sem espaços nas pontas, sem itens vazios nem repetidos, na ordem em que vieram.
            setattr(configuracao, campo, list(dict.fromkeys(m.strip() for m in (valor or []) if m.strip())))
            continue
        limpo = (valor or "").strip() or None
        if campo == "modelo_imagem":
            # Único modelo que não pode ficar vazio: sem ele a geração não tem o que chamar.
            if limpo is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="O modelo de imagem não pode ficar vazio.",
                )
            setattr(configuracao, campo, limpo)
            continue
        # String vazia e nulo significam a mesma coisa aqui: "não tenho isto".
        setattr(configuracao, campo, limpo)

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
    somente_com_json: bool = Query(
        default=False,
        description=(
            "Mostra só modelos que aceitam resposta estruturada/JSON — evita o "
            "erro 'O modelo não devolveu JSON', mais comum em modelos pequenos "
            "ou gratuitos (item 4.3)."
        ),
    ),
    somente_nao_moderados: bool = Query(
        default=False,
        description=(
            "Mostra só modelos sem moderação do provedor — útil quando o texto "
            "narrativo (violência, fantasia) é rejeitado por modelos mais "
            "restritivos."
        ),
    ),
    ordenar_por_custo: bool = Query(
        default=False,
        description="Ordena a lista por custo de saída crescente, o mais barato primeiro.",
    ),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> list[ModeloDaLista]:
    """Os modelos de texto do OpenRouter, para a tela de escolha.

    Funciona **sem chave cadastrada**: o endpoint de modelos do OpenRouter é
    público. É o que permite o usuário ver a lista antes de configurar a chave, que
    é a ordem em que ele faz as coisas.
    """
    modelos = provedor.listar_modelos()  # falha do serviço de fora vira 502 (imagineer/erros.py)

    filtrados = [
        ModeloDaLista(
            id=modelo.id,
            nome=modelo.nome,
            contexto=modelo.contexto,
            gratuito=modelo.gratuito,
            suporta_json=modelo.suporta_json,
            custo_saida=modelo.custo_saida,
            moderado=modelo.moderado,
        )
        for modelo in modelos
        if (not somente_gratuitos or modelo.gratuito)
        and modelo.contexto >= contexto_minimo
        and (not somente_com_json or modelo.suporta_json)
        and (not somente_nao_moderados or not modelo.moderado)
    ]

    if ordenar_por_custo:
        filtrados.sort(key=lambda m: m.custo_saida)

    return filtrados
