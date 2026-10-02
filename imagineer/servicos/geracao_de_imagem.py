"""Gerar a imagem de um prompt, com suavização se o provedor recusar (item 6.6, S1 a S12).

O fluxo, decidido pelo Allan (02/10/2026):

1. envia o prompt **original**;
2. se o provedor **recusar o conteúdo**, suaviza o prompt (uma vez) e faz a segunda tentativa;
3. se recusar de novo, **devolve ao usuário** para ele editar; a tentativa depois da edição é direta.

O original **nunca é sobrescrito**: o suavizado e o editado são prompts novos, ligados ao de onde saíram
(``prompt_original_id``). A situação de cada um (``situacao_da_geracao``) é gravada na hora, para uma
recusa não se perder se o resto falhar.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from imagineer.ia.provedor import ConteudoRecusado, ImagemGerada, ModeloNaoEscolhido, ProvedorIA
from imagineer.modelos import Configuracao, Imagem, Prompt
from imagineer.modelos.prompt import OrigemDaImagem, SituacaoDaGeracao
from imagineer.servicos.catalogo_imagens import salvar_imagem
from imagineer.servicos.imagens_reduzidas import ler_dimensoes

EXTENSOES_POR_TIPO = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
"""A extensão do arquivo gravado, pelo ``media_type`` que o provedor informou (padrão ``.png``)."""


@dataclass
class ResultadoDaGeracao:
    """O desfecho de um pedido de geração."""

    gerada: bool
    suavizado: bool
    """O prompt enviado por último é uma versão suavizada **pelo sistema** (não a edição do usuário)."""

    prompt: Prompt
    """O prompt enviado por último: o original, o suavizado ou o editado."""

    imagem: Imagem | None = None


def gerar_imagem_do_prompt(
    sessao: Session,
    provedor: ProvedorIA,
    prompt: Prompt,
    configuracao: Configuracao,
    texto_editado: str | None = None,
    modelo: str | None = None,
) -> ResultadoDaGeracao:
    """Roda o fluxo S1 a S3 e devolve o desfecho. Erros que não são recusa de conteúdo propagam, sem suavizar (S4).

    ``modelo`` é o modelo de imagem **só deste pedido** (Z3); em branco, vale o da configuração. Todas as tentativas
    do pedido (o original, o suavizado, o editado) usam o mesmo modelo.
    """
    modelo_de_imagem = (modelo or "").strip() or configuracao.modelo_imagem
    texto = (texto_editado or "").strip()

    if texto and texto != prompt.texto.strip():
        # S3: o usuário editou à mão. Prompt novo, chamada direta, sem suavização.
        editado = _prompt_derivado(sessao, prompt, texto, modelo_ia=None)
        imagem = _tentar(sessao, provedor, editado, modelo_de_imagem)
        return ResultadoDaGeracao(gerada=imagem is not None, suavizado=False, prompt=editado, imagem=imagem)

    # S1: o prompt como está.
    imagem = _tentar(sessao, provedor, prompt, modelo_de_imagem)
    if imagem is not None:
        return ResultadoDaGeracao(gerada=True, suavizado=False, prompt=prompt, imagem=imagem)

    # S2: recusou. Suaviza e tenta uma segunda vez.
    modelo_de_texto = configuracao.modelo_suavizacao or configuracao.modelo_prompt
    if not modelo_de_texto:
        raise ModeloNaoEscolhido(
            "O provedor recusou o prompt e não há modelo para suavizá-lo. Escolha "
            "'modelo_suavizacao' (ou 'modelo_prompt') em /configuracao."
        )
    suave = provedor.suavizar_prompt(prompt.texto, modelo_de_texto)
    suavizado = _prompt_derivado(sessao, prompt, suave.texto, modelo_ia=modelo_de_texto)
    imagem = _tentar(sessao, provedor, suavizado, modelo_de_imagem)
    return ResultadoDaGeracao(gerada=imagem is not None, suavizado=True, prompt=suavizado, imagem=imagem)


def _prompt_derivado(sessao: Session, origem: Prompt, texto: str, modelo_ia: str | None) -> Prompt:
    """Um prompt novo, ligado ao de onde saiu (S5). O de origem não é tocado."""
    novo = Prompt(
        frame_id=origem.frame_id,
        perfil_renderizacao_id=origem.perfil_renderizacao_id,
        modelo_ia=modelo_ia,
        texto=texto,
        prompt_original_id=origem.id,
    )
    sessao.add(novo)
    sessao.commit()
    sessao.refresh(novo)
    return novo


def _tentar(sessao: Session, provedor: ProvedorIA, prompt: Prompt, modelo: str) -> Imagem | None:
    """Uma tentativa de gerar a imagem. Grava a situação e o modelo do prompt; devolve a imagem, ou ``None`` se recusou."""
    try:
        gerada = provedor.gerar_imagem(prompt.texto, modelo)
    except ConteudoRecusado as recusa:
        prompt.modelo_imagem = modelo  # Z1: a tentativa recusada também guarda o modelo
        prompt.situacao_da_geracao = SituacaoDaGeracao.RECUSADO
        prompt.motivo_da_recusa = recusa.motivo
        sessao.commit()
        return None

    imagem = _gravar_imagem(sessao, prompt, gerada, modelo)
    prompt.modelo_imagem = modelo
    prompt.situacao_da_geracao = SituacaoDaGeracao.COM_SUCESSO
    prompt.motivo_da_recusa = None
    sessao.commit()
    sessao.refresh(imagem)
    return imagem


def _gravar_imagem(sessao: Session, prompt: Prompt, gerada: ImagemGerada, modelo: str) -> Imagem:
    """Grava a imagem gerada pelo mesmo caminho da importação (disco, linha no catálogo, dimensões)."""
    extensao = EXTENSOES_POR_TIPO.get(gerada.tipo_de_midia.lower(), ".png")
    caminho = salvar_imagem(prompt.id, f"gerada{extensao}", gerada.conteudo)
    dimensoes = ler_dimensoes(gerada.conteudo)
    imagem = Imagem(
        prompt_id=prompt.id,
        caminho_arquivo=caminho,
        tamanho_em_bytes=len(gerada.conteudo),
        largura=dimensoes[0] if dimensoes else None,
        altura=dimensoes[1] if dimensoes else None,
        origem=OrigemDaImagem.GERADA,
        modelo=modelo,
    )
    sessao.add(imagem)
    return imagem
