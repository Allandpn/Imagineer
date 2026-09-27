"""Rotas de prompts e catálogo de imagens (Etapa 6.6).

Cobrem os passos 8 a 11 do fluxo da Etapa 2: montar o prompt a partir da cena,
levá-lo a uma ferramenta de geração de imagem fora do sistema, e trazer o
resultado de volta para o catálogo.
"""

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.prompt import (
    ImagemResumo,
    PromptAjuste,
    PromptDetalhe,
    PromptNovo,
    PromptResumo,
)
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    ProvedorIA,
)
from imagineer.modelos import Cena, Imagem, Livro, PerfilRenderizacao, Prompt
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.catalogo_imagens import (
    TAMANHO_MAXIMO_DA_IMAGEM,
    ExtensaoDeImagemInvalida,
    caminho_absoluto,
    remover_arquivo,
    salvar_imagem,
)
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.upload import ler_com_limite

rotas_de_cena = APIRouter(prefix="/cenas", tags=["Prompts"])
rotas = APIRouter(prefix="/prompts", tags=["Prompts"])
rotas_de_imagem = APIRouter(prefix="/imagens", tags=["Prompts"])


# --------------------------------------------------------------------------- #
# Prompts de uma cena
# --------------------------------------------------------------------------- #


@rotas_de_cena.get(
    "/{cena_id}/prompts",
    response_model=list[PromptResumo],
    summary="O histórico de prompts da cena",
)
def listar_prompts(cena_id: int, sessao: Session = Depends(obter_sessao)) -> list[PromptResumo]:
    """Os prompts já montados para a cena, do mais antigo ao mais recente."""
    _buscar_cena(sessao, cena_id)

    prompts = list(
        sessao.scalars(select(Prompt).where(Prompt.cena_id == cena_id).order_by(Prompt.id))
    )
    contagens = _contar_imagens(sessao, [prompt.id for prompt in prompts])
    return [_resumo(prompt, contagens.get(prompt.id, 0)) for prompt in prompts]


@rotas_de_cena.post(
    "/{cena_id}/prompts",
    response_model=PromptDetalhe,
    status_code=status.HTTP_201_CREATED,
    summary="Monta o prompt com a IA",
)
def criar_prompt(
    cena_id: int,
    corpo: PromptNovo,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> PromptDetalhe:
    """Monta o prompt de imagem a partir da cena (passo 8).

    Os elementos vêm dos estados ligados à cena, o perfil vem do pedido ou do
    padrão do livro, e o modelo vem do pedido ou da configuração — sempre nessa
    ordem de preferência.
    """
    cena = _buscar_cena(sessao, cena_id)
    livro = cena.capitulo.livro

    perfil = _resolver_perfil(sessao, corpo.perfil_renderizacao_id, livro)
    modelo = corpo.modelo or obter_ou_criar(sessao).modelo_prompt
    if not modelo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nenhum modelo de prompt foi escolhido. Configure um em /configuracao.",
        )

    try:
        resultado = provedor.montar_prompt(
            descricao_da_cena=_descricao_da_cena(cena),
            elementos=_elementos_da_cena(cena),
            perfil_renderizacao=_descricao_do_perfil(perfil),
            modelo=modelo,
        )
    except (ChaveDeApiAusente, ModeloNaoEscolhido) as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro
    except ErroDoProvedorIA as erro:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(erro)
        ) from erro

    prompt = Prompt(
        cena_id=cena.id,
        perfil_renderizacao_id=perfil.id if perfil else None,
        modelo_ia=resultado.modelo,
        texto=resultado.texto,
    )
    sessao.add(prompt)
    sessao.commit()
    sessao.refresh(prompt)
    return _detalhe(prompt, [])


# --------------------------------------------------------------------------- #
# Um prompt
# --------------------------------------------------------------------------- #


@rotas.get("/{prompt_id}", response_model=PromptDetalhe, summary="Abre um prompt")
def abrir_prompt(prompt_id: int, sessao: Session = Depends(obter_sessao)) -> PromptDetalhe:
    """O prompt com as imagens que saíram dele."""
    prompt = _buscar_prompt(sessao, prompt_id)
    imagens = list(
        sessao.scalars(
            select(Imagem).where(Imagem.prompt_id == prompt_id).order_by(Imagem.id)
        )
    )
    return _detalhe(prompt, imagens)


@rotas.patch("/{prompt_id}", response_model=PromptDetalhe, summary="Anota a avaliação do resultado")
def ajustar_prompt(
    prompt_id: int, ajuste: PromptAjuste, sessao: Session = Depends(obter_sessao)
) -> PromptDetalhe:
    """Registra o que você achou do resultado, para comparar modelos depois."""
    prompt = _buscar_prompt(sessao, prompt_id)
    prompt.avaliacao = ajuste.avaliacao
    sessao.commit()
    sessao.refresh(prompt)
    return abrir_prompt(prompt_id, sessao)


@rotas.delete(
    "/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove o prompt e suas imagens"
)
def remover_prompt(prompt_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga o prompt, as linhas de imagem e os arquivos delas no disco.

    A cascata do banco (item 3.4c) já apaga as linhas de ``imagens`` sozinha; o
    que ela não faz é tocar no disco, então os arquivos são removidos aqui, antes
    do commit.
    """
    prompt = _buscar_prompt(sessao, prompt_id)
    caminhos = list(
        sessao.scalars(select(Imagem.caminho_arquivo).where(Imagem.prompt_id == prompt_id))
    )

    sessao.delete(prompt)
    sessao.commit()

    for caminho in caminhos:
        remover_arquivo(caminho)


# --------------------------------------------------------------------------- #
# Imagens de um prompt
# --------------------------------------------------------------------------- #


@rotas.post(
    "/{prompt_id}/imagens",
    response_model=ImagemResumo,
    status_code=status.HTTP_201_CREATED,
    summary="Importa o arquivo de imagem gerado",
)
async def importar_imagem(
    prompt_id: int,
    arquivo: UploadFile = File(description="O arquivo de imagem gerado"),
    sessao: Session = Depends(obter_sessao),
) -> ImagemResumo:
    """Recebe de volta a imagem gerada fora do sistema (passos 10 e 11)."""
    prompt = _buscar_prompt(sessao, prompt_id)
    conteudo = await ler_com_limite(arquivo, TAMANHO_MAXIMO_DA_IMAGEM)

    try:
        caminho = salvar_imagem(prompt.id, arquivo.filename or "", conteudo)
    except ExtensaoDeImagemInvalida as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    imagem = Imagem(prompt_id=prompt.id, caminho_arquivo=caminho)
    sessao.add(imagem)
    sessao.commit()
    sessao.refresh(imagem)
    return ImagemResumo.model_validate(imagem)


# --------------------------------------------------------------------------- #
# Uma imagem
# --------------------------------------------------------------------------- #


@rotas_de_imagem.get("/{imagem_id}/arquivo", summary="Devolve o arquivo da imagem")
def baixar_imagem(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> FileResponse:
    """O arquivo de imagem em si, para exibir ou baixar no app."""
    imagem = _buscar_imagem(sessao, imagem_id)
    caminho = caminho_absoluto(imagem.caminho_arquivo)
    if not caminho.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O arquivo desta imagem não está mais no disco.",
        )

    tipo, _ = mimetypes.guess_type(caminho.name)
    return FileResponse(caminho, media_type=tipo or "application/octet-stream")


@rotas_de_imagem.delete(
    "/{imagem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a imagem do catálogo, e o arquivo do disco",
)
def remover_imagem(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga a linha do catálogo e o arquivo em disco."""
    imagem = _buscar_imagem(sessao, imagem_id)
    caminho_relativo = imagem.caminho_arquivo

    sessao.delete(imagem)
    sessao.commit()

    remover_arquivo(caminho_relativo)


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _resolver_perfil(
    sessao: Session, perfil_id: int | None, livro: Livro
) -> PerfilRenderizacao | None:
    """O perfil pedido, ou o padrão do livro na ausência de um pedido explícito.

    Sem nenhum dos dois, devolve ``None`` — quem chama decide o que fazer, porque
    montar um prompt sem perfil nenhum não faz sentido (item 6.6).
    """
    escolhido = perfil_id or livro.perfil_renderizacao_padrao_id
    if escolhido is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Nenhum perfil de renderização foi informado, e o livro não tem "
                "um perfil padrão definido. Informe um ou configure o padrão do "
                "livro em PATCH /livros/{id}."
            ),
        )

    perfil = sessao.get(PerfilRenderizacao, escolhido)
    if perfil is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não existe perfil de renderização com id {escolhido}.",
        )
    return perfil


def _descricao_da_cena(cena: Cena) -> str:
    """O texto que descreve a cena para a IA montar o prompt."""
    partes = [cena.titulo]
    if cena.descricao:
        partes.append(cena.descricao)

    situacionais = ", ".join(
        f"{rotulo}: {valor}"
        for rotulo, valor in (
            ("horário", cena.horario),
            ("clima", cena.clima),
            ("humor", cena.humor),
        )
        if valor
    )
    if situacionais:
        partes.append(situacionais)

    return "\n".join(partes)


def _elementos_da_cena(cena: Cena) -> list[str]:
    """"Nome: descrição do estado", para cada elemento que aparece na cena."""
    return [
        f"{estado.elemento.nome}: {estado.descricao}"
        for estado in sorted(cena.estados_elemento, key=lambda e: (e.elemento.tipo.name, e.elemento.nome))
    ]


def _descricao_do_perfil(perfil: PerfilRenderizacao | None) -> str:
    """O texto de estilo que vai para a IA, só com os campos preenchidos.

    Cada ferramenta de imagem entende um subconjunto diferente de campos
    (item 3.4c), então só o que o perfil de fato define entra no texto.
    """
    if perfil is None:
        return ""

    partes = [perfil.nome]
    if perfil.estilo:
        partes.append(perfil.estilo)
    if perfil.artista_referencia:
        partes.append(f"referência: {perfil.artista_referencia}")
    if perfil.iluminacao:
        partes.append(f"iluminação: {perfil.iluminacao}")
    if perfil.paleta:
        partes.append(f"paleta: {perfil.paleta}")
    if perfil.formato:
        partes.append(f"formato: {perfil.formato}")

    return "; ".join(partes)


def _contar_imagens(sessao: Session, prompts_ids: list[int]) -> dict[int, int]:
    if not prompts_ids:
        return {}
    return dict(
        sessao.execute(
            select(Imagem.prompt_id, func.count(Imagem.id))
            .where(Imagem.prompt_id.in_(prompts_ids))
            .group_by(Imagem.prompt_id)
        ).all()
    )


def _resumo(prompt: Prompt, total_de_imagens: int) -> PromptResumo:
    return PromptResumo(
        id=prompt.id,
        cena_id=prompt.cena_id,
        perfil_renderizacao_id=prompt.perfil_renderizacao_id,
        modelo_ia=prompt.modelo_ia,
        texto=prompt.texto,
        avaliacao=prompt.avaliacao,
        data_criacao=prompt.data_criacao,
        total_de_imagens=total_de_imagens,
    )


def _detalhe(prompt: Prompt, imagens: list[Imagem]) -> PromptDetalhe:
    return PromptDetalhe(
        **_resumo(prompt, len(imagens)).model_dump(),
        imagens=[ImagemResumo.model_validate(imagem) for imagem in imagens],
    )


def _buscar_cena(sessao: Session, cena_id: int) -> Cena:
    cena = sessao.get(Cena, cena_id)
    if cena is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe cena com id {cena_id}.",
        )
    return cena


def _buscar_prompt(sessao: Session, prompt_id: int) -> Prompt:
    prompt = sessao.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe prompt com id {prompt_id}.",
        )
    return prompt


def _buscar_imagem(sessao: Session, imagem_id: int) -> Imagem:
    imagem = sessao.get(Imagem, imagem_id)
    if imagem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe imagem com id {imagem_id}.",
        )
    return imagem
