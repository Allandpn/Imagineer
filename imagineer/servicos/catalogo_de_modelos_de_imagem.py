"""O catálogo dos modelos de imagem, com preço por imagem, moderação e resolução (item 7.5b, MI1 a MI5, PD1 a PD4).

O OpenRouter cobra a imagem **por token**, e não por imagem; quantos tokens uma imagem tem depende da resolução. Por isso o preço
por imagem **não se calcula**: ou vem do que as imagens do modelo **já custaram** de verdade (``medido``), ou do preço
que a pessoa **informou** (``informado``), ou do que o fal.ai **publica** (``fornecedor``, estimado); sem nenhum dos três fica **sem
preço** (MI2, PD1). Nunca um valor inventado, e **nenhum nome ou preço escrito no código** (PD2, PD4).
"""

import base64
import io
import time
from dataclasses import dataclass
from decimal import Decimal

from PIL import Image as PilImage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.ia.fornecedores_de_imagem import separar_fornecedor
from imagineer.ia.provedor import ErroDoProvedorIA, ModeloDeImagemDisponivel, ProvedorIA
from imagineer.modelos import Configuracao, Imagem, UsoDeIA
from imagineer.servicos.imagens_reduzidas import ler_dimensoes
from imagineer.servicos import precos_de_imagem as fornecedores
from imagineer.servicos.precos_de_imagem import preco_informado
from imagineer.servicos.uso_de_ia import coletando_o_custo

PROMPT_DE_TESTE = "a single red apple on a plain white table, soft daylight, simple still life"
"""O prompt do teste de resolução (MI5): neutro, sem gente, para nunca esbarrar na moderação."""

NOMES_DOS_FORNECEDORES = {"openrouter": "OpenRouter", "fal": "fal.ai", "replicate": "Replicate"}


@dataclass
class EntradaDoCatalogo:
    """Um modelo de imagem do catálogo."""

    id: str
    nome: str
    fornecedor: str
    preco_por_milhao_de_tokens: Decimal | None
    preco_por_imagem: Decimal | None
    origem_do_preco: str | None
    moderacao: str
    aceita_referencia: bool
    resolucao_tipica: str | None
    em_uso: bool
    disponivel: bool


def _chave_do_uso(modelo: str) -> str:
    """Como o ``usos_ia`` guarda o modelo: o OpenRouter **sem** prefixo, os outros **com** (o provedor já grava assim)."""
    fornecedor, id_do_modelo = separar_fornecedor(modelo)
    return id_do_modelo if fornecedor == "openrouter" else f"{fornecedor}:{id_do_modelo}"


def chave_do_modelo_de_imagem(modelo: str) -> str:
    """A chave de um modelo como o ``usos_ia`` e os preços informados a guardam (o OpenRouter sem prefixo; os outros com)."""
    return _chave_do_uso(modelo)


def _precos_medidos(sessao: Session) -> dict[str, Decimal]:
    """A **média** do custo das imagens já geradas, por modelo (MI2). Só vale o custo que o fornecedor informou (não o estimado)."""
    linhas = sessao.execute(
        select(UsoDeIA.modelo, func.avg(UsoDeIA.custo))
        .where(UsoDeIA.operacao == "imagem", UsoDeIA.custo.is_not(None), UsoDeIA.estimado.is_(False))
        .group_by(UsoDeIA.modelo)
    ).all()
    return {modelo: Decimal(str(media)) for modelo, media in linhas if media is not None}


def _resolucoes_tipicas(sessao: Session) -> dict[str, str]:
    """A resolução da imagem **mais recente** de cada modelo (MI4), como ``1024×1024``."""
    linhas = sessao.execute(
        select(Imagem.modelo, Imagem.largura, Imagem.altura)
        .where(Imagem.modelo.is_not(None), Imagem.largura.is_not(None), Imagem.altura.is_not(None))
        .order_by(Imagem.id)
    ).all()
    return {_chave_do_uso(modelo): f"{largura}×{altura}" for modelo, largura, altura in linhas}  # a última sobrescreve


def _megapixels(resolucao: str | None) -> float:
    """Os megapixels de uma resolução ``larguraxaltura`` (MI4), ou 1 se não se sabe (PD1)."""
    try:
        largura, altura = (int(parte) for parte in (resolucao or "").replace("x", "×").split("×"))
        return largura * altura / 1_000_000
    except ValueError:
        return 1.0


def _moderacao(fornecedor: str, moderado: bool, modelo: str, sem_filtro: set[str]) -> str:
    """O texto de moderação (MI3)."""
    if fornecedor == "openrouter":
        return "moderado" if moderado else "sem moderação"
    return "filtro pode ser desligado" if modelo in sem_filtro else "filtro sempre ligado"


def montar_catalogo(sessao: Session, configuracao: Configuracao, provedor: ProvedorIA) -> tuple[list[EntradaDoCatalogo], str | None]:
    """O catálogo (MI1) e um aviso se o OpenRouter não respondeu (nesse caso, só vêm os outros fornecedores)."""
    aviso = None
    do_openrouter: list[ModeloDeImagemDisponivel] = []
    try:
        do_openrouter = provedor.listar_modelos_de_imagem()
    except ErroDoProvedorIA as erro:
        aviso = f"Não foi possível ler os modelos do OpenRouter agora ({erro}). Aparecem só os de outros fornecedores e os que você já usa."

    medidos = _precos_medidos(sessao)
    resolucoes = _resolucoes_tipicas(sessao)
    informados = {_chave_do_uso(m): v for m, v in (configuracao.precos_informados or {}).items()}
    do_fal = fornecedores.modelos_de_imagem_do_fal()
    do_replicate = fornecedores.modelos_de_imagem_do_replicate()
    if fornecedores._chave_do_fal() and not do_fal:
        aviso = (aviso + " " if aviso else "") + "Não foi possível ler a lista de modelos do fal.ai agora."
    if fornecedores._chave_do_replicate() and not do_replicate:
        aviso = (aviso + " " if aviso else "") + "Não foi possível ler a lista de modelos do Replicate agora."
    # Um pedido só ao fal.ai com o preço de todos os modelos dele que aparecem (guardado por 6 horas).
    ids_do_fal = {_chave_do_uso(i).split(":", 1)[1] for i, _ in do_fal} | {
        _chave_do_uso(m).split(":", 1)[1]
        for m in [*(configuracao.modelos_de_imagem or []), configuracao.modelo_imagem, *medidos]
        if _chave_do_uso(m).startswith("fal:")
    }
    precos_do_fornecedor = fornecedores.precos_do_fal(sorted(ids_do_fal))
    sem_filtro = set(configuracao.modelos_sem_filtro or [])
    com_referencia = set((configuracao.modelos_com_referencia or {}).keys())
    escolhiveis = {_chave_do_uso(m) for m in (configuracao.modelos_de_imagem or [])} | {_chave_do_uso(configuracao.modelo_imagem)}
    em_uso = _chave_do_uso(configuracao.modelo_imagem)

    entradas: dict[str, EntradaDoCatalogo] = {}

    def acrescentar(id_completo: str, nome: str, preco_token: float | None, moderado: bool) -> None:
        chave = _chave_do_uso(id_completo)
        if chave in entradas:
            return
        fornecedor, _ = separar_fornecedor(id_completo)
        # Como o app e a configuração guardam o id: o OpenRouter sem prefixo; os outros, com.
        id_publico = chave
        preco_por_imagem, origem = None, None
        if chave in medidos:
            preco_por_imagem, origem = medidos[chave], "medido"
        elif (digitado := preco_informado(chave, informados)) is not None:
            preco_por_imagem, origem = digitado, "informado"
        elif chave.startswith("fal:") and chave.split(":", 1)[1] in precos_do_fornecedor:
            preco_por_imagem = precos_do_fornecedor[chave.split(":", 1)[1]].por_imagem(_megapixels(resolucoes.get(chave)))
            origem = "fornecedor" if preco_por_imagem is not None else None
        entradas[chave] = EntradaDoCatalogo(
            id=id_publico,
            nome=nome,
            fornecedor=NOMES_DOS_FORNECEDORES[fornecedor],
            preco_por_milhao_de_tokens=(Decimal(str(preco_token)) * 1_000_000).quantize(Decimal("0.01")) if preco_token else None,
            preco_por_imagem=preco_por_imagem,
            origem_do_preco=origem,
            moderacao=_moderacao(fornecedor, moderado, id_publico, sem_filtro),
            aceita_referencia=id_publico in com_referencia or id_completo in com_referencia,
            resolucao_tipica=resolucoes.get(chave),
            em_uso=chave == em_uso,
            disponivel=chave in escolhiveis,
        )

    for modelo in do_openrouter:
        acrescentar(modelo.id, modelo.nome, modelo.preco_por_token, modelo.moderado)
    for id_do_fornecedor, nome in [*do_fal, *do_replicate]:
        acrescentar(id_do_fornecedor, nome, None, False)
    for id_da_configuracao in [*(configuracao.modelos_de_imagem or []), configuracao.modelo_imagem, *medidos]:
        if id_da_configuracao:
            acrescentar(id_da_configuracao, id_da_configuracao.split(":", 1)[-1], None, False)

    ordenadas = sorted(entradas.values(), key=lambda e: (not e.em_uso, not e.disponivel, e.fornecedor, e.nome.lower()))
    return ordenadas, aviso


@dataclass
class ResultadoDoTeste:
    """O que o teste de um modelo de imagem mostrou (MI5)."""

    modelo: str
    largura: int | None
    altura: int | None
    tamanho_em_bytes: int
    custo: Decimal | None
    estimado: bool
    segundos: float
    tipo_de_midia: str
    previa_base64: str


def testar_modelo_de_imagem(provedor: ProvedorIA, modelo: str) -> ResultadoDoTeste:
    """Gera **uma** imagem de teste com o ``modelo`` e diz resolução, custo e tempo (MI5). **Gasta dinheiro.**

    O custo entra em ``usos_ia`` como qualquer imagem (sem livro); a recusa não cobra e sobe como ``ConteudoRecusado``.
    """
    inicio = time.monotonic()
    with coletando_o_custo() as custos:
        imagem = provedor.gerar_imagem(PROMPT_DE_TESTE, modelo)
    segundos = time.monotonic() - inicio
    custo = next((c for c in custos if c is not None), None)
    fornecedor, _ = separar_fornecedor(modelo)
    dimensoes = ler_dimensoes(imagem.conteudo)
    return ResultadoDoTeste(
        modelo=modelo,
        largura=dimensoes[0] if dimensoes else None,
        altura=dimensoes[1] if dimensoes else None,
        tamanho_em_bytes=len(imagem.conteudo),
        custo=custo,
        estimado=custo is not None and fornecedor != "openrouter",
        segundos=round(segundos, 1),
        tipo_de_midia="image/jpeg",
        previa_base64=_previa(imagem.conteudo),
    )


def _previa(conteudo: bytes, maior_lado: int = 512) -> str:
    """A imagem reduzida (JPEG, no máximo 512 px) em base64, para o app mostrar sem baixar o original."""
    try:
        with PilImage.open(io.BytesIO(conteudo)) as origem:
            origem = origem.convert("RGB")
            origem.thumbnail((maior_lado, maior_lado))
            saida = io.BytesIO()
            origem.save(saida, format="JPEG", quality=80)
            return base64.b64encode(saida.getvalue()).decode()
    except (OSError, ValueError):
        return ""
