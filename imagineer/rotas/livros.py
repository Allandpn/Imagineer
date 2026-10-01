"""Rotas de livros (Etapa 6.2): importar, listar, abrir e remover.

Cobrem os passos 1 a 4 do fluxo da Etapa 2.
"""

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.frame import (
    LivroAjuste,
    PerfilRenderizacaoSugestao,
    SugestaoDePerfilPedido,
)
from imagineer.esquemas.livro import (
    CapituloResumo,
    LivroDetalhe,
    LivroResumo,
    RespostaImportacao,
    TextoDeCapitulo,
)
from imagineer.esquemas.prompt import MidiaDeImagem, MidiasDoLivro
from imagineer.ia.provedor import (
    ModeloNaoEscolhido,
    ProvedorIA,
)
from imagineer.modelos import (
    Capitulo,
    Frame,
    Imagem,
    Livro,
    PerfilRenderizacao,
    Prompt,
    SugestaoDeCena,
    SugestaoDeElemento,
)
from imagineer.rotas._comum import (
    buscar_livro as _buscar_livro,
)
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.imagens_reduzidas import garantir_dimensoes
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
def abrir_livro(
    livro_id: int,
    requisicao: Request,
    resposta: Response,
    sessao: Session = Depends(obter_sessao),
) -> LivroDetalhe | Response:
    """O livro com a estrutura de capítulos, sem o texto deles.

    **`ETag` é a `revisao` do livro** (item 6.9). Um cliente que já tem a revisão atual manda
    `If-None-Match` e recebe `304`, sem corpo — economiza até esta lista, que já é ~90 vezes menor
    que os textos.
    """
    livro = _buscar_livro(sessao, livro_id)
    etag = f'"{livro.revisao}"'

    if etag in _etags_aceitos(requisicao.headers.get("if-none-match")):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    resposta.headers["ETag"] = etag
    return _detalhe_do_livro(sessao, livro)


def _etags_aceitos(cabecalho: str | None) -> set[str]:
    """Os `ETag` de um `If-None-Match`, que pode trazer vários separados por vírgula e o prefixo
    `W/` de validador fraco (que aqui vale o mesmo)."""
    if not cabecalho:
        return set()
    return {parte.strip().removeprefix("W/") for parte in cabecalho.split(",")}


@rotas.get(
    "/{livro_id}/textos",
    response_model=list[TextoDeCapitulo],
    summary="O texto de todos os capítulos do livro, numa chamada só",
)
def baixar_textos(livro_id: int, sessao: Session = Depends(obter_sessao)) -> list[TextoDeCapitulo]:
    """Existe para "Baixar para ler offline" (itens 7.0a e 6.9).

    O texto de um livro tem ~0,7 MB em mediana (~0,3 MB comprimido), então uma chamada é
    melhor que uma por capítulo (a mediana é de 50). É uma **otimização**: o app poderia
    baixar capítulo por capítulo em `GET /capitulos/{id}`. Inclui os capítulos arquivados —
    "arquivado" é só organização, e quem baixa o livro quer tudo.

    Em ordem de leitura. **Não** faz parte de `GET /livros/{id}`, que continua devolvendo só os
    metadados dos capítulos (7,5 KB contra 674 KB de texto, item 6.2).
    """
    _buscar_livro(sessao, livro_id)

    linhas = sessao.execute(
        select(Capitulo.id, Capitulo.ordem, Capitulo.texto)
        .where(Capitulo.livro_id == livro_id)
        .order_by(Capitulo.ordem)
    ).all()
    return [TextoDeCapitulo(capitulo_id=i, ordem=o, texto=t) for i, o, t in linhas]


@rotas.get(
    "/{livro_id}/midias",
    response_model=MidiasDoLivro,
    summary="O manifesto das imagens do livro, com o tamanho de cada uma",
)
def listar_midias(livro_id: int, sessao: Session = Depends(obter_sessao)) -> MidiasDoLivro:
    """O que o app precisa baixar para ler o livro offline, e quanto isso ocupa (item 6.9).

    Permite mostrar **"Baixar — 240 MB" antes de começar** (item 7.0a, A4). Cada imagem traz o
    tamanho do arquivo **original**.

    O tamanho vem da coluna `Imagem.tamanho_em_bytes`, preenchida na importação. Imagens
    importadas **antes** da coluna existir não têm valor: o tamanho é calculado do arquivo em
    disco e **gravado** na primeira vez, então a consulta seguinte já o encontra.

    Uma imagem cujo **arquivo sumiu do disco** fica de fora: listá-la faria o download falhar
    no meio, e `GET /imagens/{id}/arquivo` já responderia 404 para ela.
    """
    _buscar_livro(sessao, livro_id)

    linhas = sessao.execute(
        select(Imagem, Prompt.frame_id)
        .join(Prompt, Prompt.id == Imagem.prompt_id)
        .join(Frame, Frame.id == Prompt.frame_id)
        .join(Capitulo, Capitulo.id == Frame.capitulo_id)
        .where(Capitulo.livro_id == livro_id)
        .order_by(Imagem.id)
    ).all()

    midias: list[MidiaDeImagem] = []
    gravou = False
    for imagem, frame_id in linhas:
        caminho = caminho_absoluto(imagem.caminho_arquivo)
        if not caminho.is_file():
            continue
        if imagem.tamanho_em_bytes is None:
            imagem.tamanho_em_bytes = caminho.stat().st_size
            gravou = True
        if garantir_dimensoes(imagem, caminho):
            gravou = True
        tipo, _ = mimetypes.guess_type(caminho.name)
        midias.append(
            MidiaDeImagem(
                imagem_id=imagem.id,
                prompt_id=imagem.prompt_id,
                frame_id=frame_id,
                tamanho_em_bytes=imagem.tamanho_em_bytes,
                tipo_do_arquivo=tipo or "application/octet-stream",
                largura=imagem.largura,
                altura=imagem.altura,
            )
        )
    if gravou:
        sessao.commit()

    return MidiasDoLivro(
        total_em_bytes=sum(m.tamanho_em_bytes for m in midias), imagens=midias
    )


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

    # Digitar um título é confirmá-lo — deixa de contar como pendente
    # (item 6.2), mesmo que o valor mandado seja igual ao que já estava lá.
    if "titulo" in campos:
        livro.titulo_confirmado = True

    sessao.commit()
    sessao.refresh(livro)
    return _detalhe_do_livro(sessao, livro)


@rotas.post(
    "/{livro_id}/perfis-renderizacao/sugestao",
    response_model=PerfilRenderizacaoSugestao,
    summary="Sugere um perfil de renderização por IA (rascunho)",
)
def sugerir_perfil_renderizacao(
    livro_id: int,
    pedido: SugestaoDePerfilPedido | None = None,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> PerfilRenderizacaoSugestao:
    """Sugere um estilo visual a partir só de título/autor/idioma do livro.

    **Rascunho de validação, ainda sem especificação fechada** (pendência da
    Etapa 8) — não persiste nada; devolve a sugestão solta para o usuário
    decidir se usa em `POST /perfis-renderizacao`. Não lê nenhum capítulo: a
    ideia de usar o primeiro capítulo foi descartada porque não há como saber
    de antemão onde a narrativa de fato começa (muitos livros têm prólogo,
    sumário residual ou epígrafe antes do primeiro capítulo "de verdade").
    Em vez disso, pede para a IA reconhecer a obra pelos metadados — inclusive
    buscando na internet — o que troca o risco de ler o trecho errado do livro
    pelo risco de a IA confundir com outra obra ou inventar um tom genérico.

    `pedido.categoria_estilo` (opcional) deixa o usuário escolher a família de
    estilo (pintura a óleo, cartoon...) e a IA detalha os atributos dentro
    dela. Achado testando com IA real: sem essa restrição, uma sugestão livre
    já misturou movimentos artísticos incompatíveis na mesma resposta, e o
    prompt de imagem gerado a partir dela saiu visualmente confuso.
    """
    livro = _buscar_livro(sessao, livro_id)
    configuracao = obter_ou_criar(sessao)
    modelo_perfil = configuracao.modelo_perfil

    if not modelo_perfil:
        raise ModeloNaoEscolhido(
            "Nenhum modelo de sugestão de perfil foi escolhido. Configure "
            "'modelo_perfil' em /configuracao."
        )

    categoria_estilo = pedido.categoria_estilo if pedido else None

    sugestao = provedor.sugerir_perfil_renderizacao(
        livro.titulo, livro.autor, livro.idioma, categoria_estilo, modelo_perfil
    )

    return PerfilRenderizacaoSugestao(
        estilo=sugestao.estilo,
        artista_referencia=sugestao.artista_referencia,
        iluminacao=sugestao.iluminacao,
        paleta=sugestao.paleta,
        formato=sugestao.formato,
        categoria_estilo=sugestao.categoria_estilo,
        reconheceu_a_obra=sugestao.reconheceu_a_obra,
        modelo=sugestao.modelo,
    )


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
        "revisao": livro.revisao,
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


def _sugestoes_pendentes_por_capitulo(sessao: Session, livro_id: int) -> dict[int, int]:
    """Quantas sugestões (elemento ou cena) de cada capítulo ainda não foram
    confirmadas (item 4.6) — o que alimenta o indicador de pendência da tela
    de Livro, numa consulta por tipo em vez de uma por capítulo.
    """
    contagem: dict[int, int] = {}
    for capitulo_id, total in sessao.execute(
        select(SugestaoDeElemento.capitulo_id, func.count(SugestaoDeElemento.id))
        .join(Capitulo, Capitulo.id == SugestaoDeElemento.capitulo_id)
        .where(
            Capitulo.livro_id == livro_id,
            SugestaoDeElemento.elemento_id.is_(None),
            SugestaoDeElemento.descartada.is_(False),
        )
        .group_by(SugestaoDeElemento.capitulo_id)
    ).all():
        contagem[capitulo_id] = contagem.get(capitulo_id, 0) + total

    for capitulo_id, total in sessao.execute(
        select(SugestaoDeCena.capitulo_id, func.count(SugestaoDeCena.id))
        .join(Capitulo, Capitulo.id == SugestaoDeCena.capitulo_id)
        .where(
            Capitulo.livro_id == livro_id,
            SugestaoDeCena.frame_id.is_(None),
            SugestaoDeCena.descartada.is_(False),
        )
        .group_by(SugestaoDeCena.capitulo_id)
    ).all():
        contagem[capitulo_id] = contagem.get(capitulo_id, 0) + total

    return contagem


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

    pendentes = _sugestoes_pendentes_por_capitulo(sessao, livro.id)

    capitulos = [
        CapituloResumo(
            id=identificador,
            ordem=ordem,
            titulo=titulo,
            ignorado=ignorado,
            tamanho_do_texto=tamanho,
            sugestoes_pendentes=pendentes.get(identificador, 0),
        )
        for identificador, ordem, titulo, ignorado, tamanho in linhas
    ]

    return LivroDetalhe(
        **_campos_do_livro(livro),
        identificador_epub=livro.identificador_epub,
        perfil_renderizacao_padrao_id=livro.perfil_renderizacao_padrao_id,
        metadados_pendentes=_metadados_pendentes(livro),
        total_de_capitulos=len(capitulos),
        capitulos_ignorados=sum(1 for c in capitulos if c.ignorado),
        capitulos=capitulos,
    )


def _metadados_pendentes(livro: Livro) -> list[str]:
    """Campos mandatórios que a extração não conseguiu obter (item 6.2).

    Lista, não booleanos separados: acrescentar outro campo obrigatório no
    futuro é só somar uma checagem aqui, sem coluna nem campo de resposta novo.
    """
    pendentes = []
    if not livro.titulo_confirmado:
        pendentes.append("titulo")
    if livro.autor is None:
        pendentes.append("autor")
    return pendentes
