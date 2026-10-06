"""Rotas de configuração da integração com IA (Etapas 4.3 e 6.7)."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from typing import Annotated

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao, obter_usuario
from imagineer.configuracao import obter_configuracoes
from imagineer.ia.provedor import ProvedorIA
from imagineer.ia.provedores import PROVEDORES, Provedor
from imagineer.modelos import ModoDeNarracao, MotorDeNarracao, PrioridadeIA, Usuario
from imagineer.servicos.catalogo_de_modelos_de_imagem import chave_do_modelo_de_imagem, montar_catalogo, testar_modelo_de_imagem
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
    chave_api_fal: str | None = Header(default=None, alias="X-Chave-API-Fal", description="Chave pessoal do fal.ai (CT24). Nunca é gravada."),
    chave_api_replicate: str | None = Header(
        default=None, alias="X-Chave-API-Replicate", description="Chave pessoal do Replicate (CT24). Nunca é gravada."
    ),
    usuario: Usuario = Depends(obter_usuario),
) -> ProvedorIA:
    """Dependência que entrega o provedor de IA já configurado.

    Existe como dependência do FastAPI, e não como objeto global, para os testes
    poderem substituí-la por um provedor falso — e para uma troca de chave valer
    no pedido seguinte, sem reiniciar o serviço.
    """
    return construir_provedor(chave_api_openrouter, usuario, chave_api_fal, chave_api_replicate)


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
    modelo_video: str | None = Field(
        description="Modelo de texto que monta o prompt de vídeo (item 4.8). Vazio = usa o `modelo_prompt`."
    )
    prioridade_ia: PrioridadeIA = Field(
        description=(
            "ECONOMIA (padrão) reaproveita leituras já feitas; QUALIDADE relê "
            "o capítulo toda vez que um prompt é montado (item 4.4)."
        )
    )
    narracao_motor: MotorDeNarracao = Field(
        description="Quem narra (RL21): `APARELHO` (a voz do Android, o padrão) ou `IA` (o servidor gera o MP3 do capítulo com `modelo_narracao`, NA1)."
    )
    modelo_narracao: str | None = Field(
        description="O modelo de **voz** do OpenRouter que fala o capítulo (NA1); nulo = nenhum escolhido. A lista: `GET /configuracao/modelos-de-narracao`."
    )
    narracao_modo: ModoDeNarracao = Field(description="`UMA_VOZ` (padrão) ou `POR_PERSONAGEM` (RL25). Guardado; só `UMA_VOZ` gera áudio por enquanto (NA10).")
    narracao_voz: str | None = Field(description="A voz do `modelo_narracao` (RL24), como `pt-BR-Luana:MAI-Voice-2.1-Flash`; nula = a padrão do modelo (alguns modelos exigem uma).")
    narracao_instrucoes: str | None = Field(description="As instruções de tom da narração (RL23), em texto livre. Guardadas, mas **ainda não enviadas** ao modelo (NA2).")


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
    modelo_video: str | None = Field(default=None, max_length=200)
    prioridade_ia: PrioridadeIA | None = None
    narracao_motor: MotorDeNarracao | None = None
    modelo_narracao: str | None = Field(default=None, max_length=200)
    narracao_modo: ModoDeNarracao | None = None
    narracao_voz: str | None = Field(default=None, max_length=100)
    narracao_instrucoes: str | None = Field(default=None, max_length=2000)


class ModeloDeImagemDoCatalogo(BaseModel):
    """Um modelo de imagem do catálogo (MI1)."""

    id: str = Field(description="Como a configuração o guarda: sem prefixo = OpenRouter; `fal:` ou `replicate:` nos outros.")
    nome: str
    fornecedor: str
    preco_por_milhao_de_tokens: Decimal | None = Field(
        default=None, description="Só OpenRouter: o preço de 1 milhão de tokens de imagem. **Não** é o preço por imagem."
    )
    preco_por_imagem: Decimal | None = Field(default=None, description="Nulo = ainda sem preço (teste para medir).")
    origem_do_preco: str | None = Field(default=None, description="`medido` (o que as imagens do modelo já custaram), `tabela` (estimado) ou nulo.")
    moderacao: str
    aceita_referencia: bool
    resolucao_tipica: str | None = Field(default=None, description="`largura×altura` da imagem mais recente do modelo; nulo = nenhuma ainda.")
    em_uso: bool = Field(description="É o modelo de imagem padrão.")
    disponivel: bool = Field(description="Está na lista de escolha ao gerar.")


class CatalogoDeImagem(BaseModel):
    modelos: list[ModeloDeImagemDoCatalogo]
    aviso: str | None = None


class PedidoDeTeste(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modelo: str = Field(min_length=1, max_length=200)


class PrecoInformado(BaseModel):
    """O preço por imagem que a pessoa informa para um modelo de imagem (PD5)."""

    model_config = ConfigDict(extra="forbid")

    modelo: str = Field(min_length=1, max_length=200)
    preco: str | None = Field(default=None, description="Dólares por imagem, maior que zero. Nulo ou vazio limpa o preço informado.")


class TesteDeImagem(BaseModel):
    """O resultado do teste de um modelo de imagem (MI5)."""

    modelo: str
    largura: int | None
    altura: int | None
    tamanho_em_bytes: int
    custo: Decimal | None
    estimado: bool
    segundos: float
    tipo_de_midia: str
    previa_base64: str = Field(description="A imagem reduzida (JPEG, até 512 px) em base64.")


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
def ver_configuracao(sessao: Session = Depends(obter_sessao), usuario: Usuario = Depends(obter_usuario)) -> ConfiguracaoAtual:
    """Diz quais modelos estão escolhidos e se há chave — sem devolver a chave."""
    configuracao = obter_ou_criar(sessao)
    chave = resolver_chave(None, usuario)  # sem header: só o que o servidor tem **para esta pessoa** (CT9)
    configuracoes = obter_configuracoes()
    do_servidor = usuario.usa_chaves_do_servidor

    return ConfiguracaoAtual(
        tem_chave_api=chave.valor is not None,
        origem_da_chave=chave.origem,
        modelo_extracao=configuracao.modelo_extracao,
        modelo_prompt=configuracao.modelo_prompt,
        modelo_perfil=configuracao.modelo_perfil,
        modelo_imagem=configuracao.modelo_imagem,
        fornecedores_de_imagem={
            "openrouter": chave.valor is not None,
            "fal": do_servidor and bool(configuracoes.chave_api_fal.strip()),
            "replicate": do_servidor and bool(configuracoes.chave_api_replicate.strip()),
        },
        modelos_de_imagem=list(configuracao.modelos_de_imagem or []),
        modelos_sem_filtro=list(configuracao.modelos_sem_filtro or []),
        modelos_com_referencia=dict(configuracao.modelos_com_referencia or {}),
        modelo_suavizacao=configuracao.modelo_suavizacao,
        modelo_traducao=configuracao.modelo_traducao,
        modelo_video=configuracao.modelo_video,
        prioridade_ia=configuracao.prioridade_ia,
        narracao_motor=configuracao.narracao_motor,
        modelo_narracao=configuracao.modelo_narracao,
        narracao_modo=configuracao.narracao_modo,
        narracao_voz=configuracao.narracao_voz,
        narracao_instrucoes=configuracao.narracao_instrucoes,
    )


class ProvedorDaLista(BaseModel):
    """Um provedor da lista fixa (CT24): o que o app precisa para montar o campo de chave dele."""

    id: Provedor
    nome: str
    cabecalho: str = Field(description="O header em que o app manda a chave deste provedor, a cada chamada.")
    usado_para: str
    servidor_fornece: bool = Field(
        description="Esta pessoa pode usar a chave **do servidor** para este provedor (só quem tem `usa_chaves_do_servidor`, e se o servidor a tem). "
        "Se sim, ela não precisa cadastrar a dela."
    )


@rotas.get("/provedores", response_model=list[ProvedorDaLista], summary="Os provedores de IA e o header de chave de cada um")
def listar_provedores(usuario: Usuario = Depends(obter_usuario)) -> list[ProvedorDaLista]:
    """A lista **fixa** de provedores (CT24). A tela de Configurações mostra um campo de chave por provedor, guarda a chave no aparelho e a manda
    no header indicado. **Nunca devolve chave.**"""
    chaves_do_servidor = {
        Provedor.OPENROUTER: obter_configuracoes().chave_api_openrouter,
        Provedor.FAL: obter_configuracoes().chave_api_fal,
        Provedor.REPLICATE: obter_configuracoes().chave_api_replicate,
    }
    return [
        ProvedorDaLista(
            id=provedor,
            nome=dados.nome,
            cabecalho=dados.cabecalho,
            usado_para=dados.usado_para,
            servidor_fornece=usuario.usa_chaves_do_servidor and bool((chaves_do_servidor[provedor] or "").strip()),
        )
        for provedor, dados in PROVEDORES.items()
    ]


@rotas.put("", response_model=ConfiguracaoAtual, summary="Grava a configuração")
def gravar_configuracao(
    nova: ConfiguracaoNova, sessao: Session = Depends(obter_sessao), usuario: Usuario = Depends(obter_usuario)
) -> ConfiguracaoAtual:
    """Escolhe os modelos e a prioridade de IA. A chave não passa por aqui."""
    configuracao = obter_ou_criar(sessao)

    for campo, valor in nova.model_dump(exclude_unset=True).items():
        if campo in ("narracao_motor", "narracao_modo") and valor is None:
            continue  # enumeração: nulo não "apaga" (não há valor vazio); fica o que estava
        if campo in ("prioridade_ia", "narracao_motor", "narracao_modo"):
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
    return ver_configuracao(sessao, usuario)


@rotas.get("/modelos-de-imagem", response_model=CatalogoDeImagem, summary="Os modelos de imagem, com preço, moderação e resolução")
def listar_modelos_de_imagem(
    sessao: Session = Depends(obter_sessao), provedor: ProvedorIA = Depends(obter_provedor)
) -> CatalogoDeImagem:
    """O catálogo (MI1): OpenRouter (lido do endpoint público dele), fal.ai e Replicate, com o preço **por imagem** só quando se sabe
    (medido ou de tabela; MI2), a moderação (MI3) e a resolução que o modelo já entregou aqui (MI4)."""
    entradas, aviso = montar_catalogo(sessao, obter_ou_criar(sessao), provedor)
    return CatalogoDeImagem(modelos=[ModeloDeImagemDoCatalogo(**vars(e)) for e in entradas], aviso=aviso)


@rotas.put("/modelos-de-imagem/preco", response_model=CatalogoDeImagem, summary="Informa (ou limpa) o preço por imagem de um modelo")
def informar_preco_do_modelo(
    corpo: PrecoInformado, sessao: Session = Depends(obter_sessao), provedor: ProvedorIA = Depends(obter_provedor)
) -> CatalogoDeImagem:
    """Grava o preço por imagem que a pessoa digitou (PD5); vale na hora, em cima do que o fornecedor publica. Devolve o catálogo."""
    configuracao = obter_ou_criar(sessao)
    chave = chave_do_modelo_de_imagem(corpo.modelo)
    informados = dict(configuracao.precos_informados or {})
    texto = (corpo.preco or "").strip().replace(",", ".")
    if not texto:
        informados.pop(chave, None)
    else:
        try:
            valor = Decimal(texto)
        except InvalidOperation:
            valor = Decimal(0)
        if not valor.is_finite() or valor <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="O preço por imagem precisa ser um número maior que zero (em dólares)."
            )
        informados[chave] = format(valor.normalize(), "f")
    configuracao.precos_informados = informados  # reatribui: o JSON não percebe a mudança dentro do dict
    sessao.commit()
    return listar_modelos_de_imagem(sessao, provedor)


@rotas.post("/modelos-de-imagem/testar", response_model=TesteDeImagem, summary="Gera uma imagem de teste e mede resolução e custo")
def testar_modelo(pedido: PedidoDeTeste, provedor: ProvedorIA = Depends(obter_provedor)) -> TesteDeImagem:
    """Gera **uma** imagem de teste com o modelo (MI5). **Gasta dinheiro** (cerca de um centavo): o app confirma antes."""
    return TesteDeImagem(**vars(testar_modelo_de_imagem(provedor, pedido.modelo.strip())))


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
