"""Rotas de livros (Etapa 6.2): importar, listar, abrir e remover.

Cobrem os passos 1 a 4 do fluxo da Etapa 2.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.frame import LivroAjuste
from imagineer.esquemas.livro import (
    CapituloResumo,
    LivroDetalhe,
    LivroResumo,
    RespostaImportacao,
)
from imagineer.modelos import Capitulo, Livro, PerfilRenderizacao
from imagineer.servicos.importacao_epub import (
    ArquivoEpubInvalido,
    importar_epub,
    livros_com_mesmo_identificador,
)
from imagineer.servicos.upload import ler_com_limite

rotas = APIRouter(prefix="/livros", tags=["Livros"])

TAMANHO_MAXIMO_DO_EPUB = 60 * 1024 * 1024
"""Limite do arquivo enviado, em bytes.

O maior dos dezoito livros de validação tem 46 MB — uma história em quadrinhos —
então 60 MB acomoda o caso real com folga e ainda protege o Raspberry Pi de um
arquivo absurdo.
"""


@rotas.post(
    "",
    response_model=RespostaImportacao,
    status_code=status.HTTP_201_CREATED,
    summary="Importa um arquivo EPUB",
)
async def importar_livro(
    arquivo: UploadFile = File(description="O arquivo .epub a importar"),
    sessao: Session = Depends(obter_sessao),
) -> RespostaImportacao:
    """Recebe o EPUB, estrutura em capítulos e grava.

    É **síncrono** de propósito: medido nos livros de validação, extrair e gravar
    leva de 0,03 a 0,33 segundo mesmo no maior deles. Uma fila em segundo plano
    resolveria um problema que não existe e acrescentaria estado para o app
    acompanhar.
    """
    conteudo = await ler_com_limite(arquivo, TAMANHO_MAXIMO_DO_EPUB)

    try:
        livro = importar_epub(sessao, conteudo, arquivo.filename or "livro.epub")
    except ArquivoEpubInvalido as erro:
        # 422 e não 400: o pedido está bem formado, o conteúdo é que não serve.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    # Importar o mesmo livro duas vezes é permitido (item 3.4a): o app avisa, não
    # impede. Por isso os semelhantes vão na resposta.
    semelhantes = [
        outro
        for outro in livros_com_mesmo_identificador(sessao, livro.identificador_epub)
        if outro.id != livro.id
    ]

    return RespostaImportacao(
        livro=_detalhe_do_livro(sessao, livro),
        livros_semelhantes=[_resumo_do_livro(sessao, outro) for outro in semelhantes],
    )


@rotas.get("", response_model=list[LivroResumo], summary="Lista os livros")
def listar_livros(sessao: Session = Depends(obter_sessao)) -> list[LivroResumo]:
    """Devolve a biblioteca, em ordem alfabética de título.

    As contagens de capítulos são feitas pelo banco, numa consulta só. Carregar os
    capítulos de cada livro para contá-los em Python traria megabytes de texto
    para descartar em seguida.
    """
    linhas = sessao.execute(
        select(
            Livro,
            func.count(Capitulo.id),
            func.coalesce(func.sum(_um_se_ignorado()), 0),
        )
        .outerjoin(Capitulo, Capitulo.livro_id == Livro.id)
        .group_by(Livro.id)
        .order_by(Livro.titulo)
    ).all()

    return [
        LivroResumo(
            **_campos_do_livro(livro),
            total_de_capitulos=total,
            capitulos_ignorados=ignorados,
        )
        for livro, total, ignorados in linhas
    ]


@rotas.get("/{livro_id}", response_model=LivroDetalhe, summary="Abre um livro")
def abrir_livro(livro_id: int, sessao: Session = Depends(obter_sessao)) -> LivroDetalhe:
    """O livro com a estrutura de capítulos, sem o texto deles."""
    return _detalhe_do_livro(sessao, _buscar_livro(sessao, livro_id))


@rotas.patch("/{livro_id}", response_model=LivroDetalhe, summary="Ajusta um livro")
def ajustar_livro(
    livro_id: int, ajuste: LivroAjuste, sessao: Session = Depends(obter_sessao)
) -> LivroDetalhe:
    """Corrige os metadados do livro e define o perfil de renderização padrão.

    Corrigir metadados não é luxo: na validação da importação, um EPUB de
    *Treasure Island* declarava-se *Death and the Afterlife in Ancient Egypt*, de
    outro autor. A importação é fiel ao que o arquivo diz (item 2.2), então quem
    conserta é o usuário.
    """
    livro = _buscar_livro(sessao, livro_id)
    campos = ajuste.model_dump(exclude_unset=True)

    if campos.get("perfil_renderizacao_padrao_id") is not None:
        _exigir_perfil(sessao, campos["perfil_renderizacao_padrao_id"])

    for campo, valor in campos.items():
        setattr(livro, campo, valor)

    sessao.commit()
    sessao.refresh(livro)
    return _detalhe_do_livro(sessao, livro)


@rotas.delete(
    "/{livro_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um livro",
)
def remover_livro(livro_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga o livro e, em cascata, tudo que só existia por causa dele.

    Capítulos, elementos, estados, frames, prompts e imagens vão junto (item 3.4).
    Os perfis de renderização não: eles não pertencem ao livro.
    """
    sessao.delete(_buscar_livro(sessao, livro_id))
    sessao.commit()


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _buscar_livro(sessao: Session, livro_id: int) -> Livro:
    """Devolve o livro ou responde 404."""
    livro = sessao.get(Livro, livro_id)
    if livro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe livro com id {livro_id}.",
        )
    return livro


def _exigir_perfil(sessao: Session, perfil_id: int) -> None:
    """Confere que o perfil existe, para o erro sair claro.

    Sem isto, a chave estrangeira falharia no commit e o app receberia um 500 em
    vez de uma mensagem que dá para mostrar na tela.
    """
    if sessao.get(PerfilRenderizacao, perfil_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não existe perfil de renderização com id {perfil_id}.",
        )


def _um_se_ignorado():
    """Expressão SQL que vale 1 para capítulo ignorado e 0 para os outros.

    Serve para somar os ignorados na mesma consulta que conta o total, em vez de
    fazer uma segunda ida ao banco por livro.
    """
    return case((Capitulo.ignorado.is_(True), 1), else_=0).cast(Integer)


def _campos_do_livro(livro: Livro) -> dict:
    """Os campos do livro que aparecem tanto no resumo quanto no detalhe."""
    return {
        "id": livro.id,
        "titulo": livro.titulo,
        "autor": livro.autor,
        "idioma": livro.idioma,
        "nome_arquivo": livro.nome_arquivo,
        "data_importacao": livro.data_importacao,
    }


def _resumo_do_livro(sessao: Session, livro: Livro) -> LivroResumo:
    """Monta o resumo de um livro, contando os capítulos no banco."""
    total, ignorados = sessao.execute(
        select(func.count(Capitulo.id), func.coalesce(func.sum(_um_se_ignorado()), 0))
        .where(Capitulo.livro_id == livro.id)
    ).one()

    return LivroResumo(
        **_campos_do_livro(livro),
        total_de_capitulos=total,
        capitulos_ignorados=ignorados,
    )


def _detalhe_do_livro(sessao: Session, livro: Livro) -> LivroDetalhe:
    """Monta o detalhe de um livro com a lista de capítulos sem texto.

    A consulta pede ``length(texto)`` ao banco em vez de selecionar o texto: assim
    o tamanho chega calculado e o conteúdo dos capítulos nunca sai do PostgreSQL.
    Em *Os 100 Melhores Contos de Crime* isso é 1,7 MB que não trafegam.
    """
    linhas = sessao.execute(
        select(
            Capitulo.id,
            Capitulo.ordem,
            Capitulo.titulo,
            Capitulo.ignorado,
            func.length(Capitulo.texto),
        )
        .where(Capitulo.livro_id == livro.id)
        .order_by(Capitulo.ordem)
    ).all()

    capitulos = [
        CapituloResumo(
            id=identificador,
            ordem=ordem,
            titulo=titulo,
            ignorado=ignorado,
            tamanho_do_texto=tamanho,
        )
        for identificador, ordem, titulo, ignorado, tamanho in linhas
    ]

    return LivroDetalhe(
        **_campos_do_livro(livro),
        identificador_epub=livro.identificador_epub,
        perfil_renderizacao_padrao_id=livro.perfil_renderizacao_padrao_id,
        total_de_capitulos=len(capitulos),
        capitulos_ignorados=sum(1 for c in capitulos if c.ignorado),
        capitulos=capitulos,
    )
