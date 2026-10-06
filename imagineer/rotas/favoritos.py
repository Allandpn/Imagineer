"""Rotas dos favoritos (RL31 a RL38): uma estrela no livro, num parágrafo, num elemento, numa cena ou numa imagem."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.favorito import FavoritoNovo, FavoritoResposta
from imagineer.servicos.acesso import buscar_visivel
from imagineer.modelos import Capitulo, Elemento, Favorito, Frame, Imagem, Livro, TipoDeFavorito, TipoDeFrame
from imagineer.rotas._comum import buscar_elemento, buscar_frame, buscar_livro, obter_ou_404
from imagineer.rotas.destaques import _trecho_em_utf16
from imagineer.rotas.leitura import _capitulo_do_livro, _conferir_posicao

rotas_de_livro = APIRouter(prefix="/livros", tags=["Favoritos"])
rotas = APIRouter(prefix="/favoritos", tags=["Favoritos"])

LIMITE_DO_TRECHO_DO_PARAGRAFO = 300
"""Quanto do começo do parágrafo o servidor guarda para a lista (RL33)."""


def _recusar(detalhe: str) -> None:
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detalhe)


def _comeco_do_paragrafo(capitulo: Capitulo, posicao: int) -> str:
    """O começo do parágrafo que **começa** em ``posicao`` (UTF-16): até a linha em branco seguinte, em um espaço só, e no máximo 300 caracteres."""
    ate_o_fim = _trecho_em_utf16(capitulo.texto, posicao, len(capitulo.texto.encode("utf-16-le")) // 2)
    paragrafo = ate_o_fim.split("\n\n", 1)[0]
    limpo = " ".join(paragrafo.split())
    if len(limpo) <= LIMITE_DO_TRECHO_DO_PARAGRAFO:
        return limpo
    return limpo[:LIMITE_DO_TRECHO_DO_PARAGRAFO].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"


def _exigir_so(novo: FavoritoNovo, *campos: str) -> None:
    """422 se faltar um dos campos do alvo ou se vier um campo de outro tipo (um engano de quem chama não vira favorito errado)."""
    todos = ("capitulo_id", "posicao", "elemento_id", "frame_id", "imagem_id")
    for campo in todos:
        presente = getattr(novo, campo) is not None
        if campo in campos and not presente:
            _recusar(f"Um favorito do tipo {novo.tipo.value} pede o campo {campo}.")
        if campo not in campos and presente:
            _recusar(f"Um favorito do tipo {novo.tipo.value} não leva o campo {campo}.")


def _livro_da_imagem(imagem: Imagem) -> int | None:
    frame = imagem.prompt.frame if imagem.prompt is not None else None
    return frame.capitulo.livro_id if frame is not None else None


def _validar_e_procurar(sessao: Session, livro_id: int, novo: FavoritoNovo) -> tuple[dict, str | None]:
    """Confere o alvo e devolve os campos que identificam o favorito e, no parágrafo, o ``trecho`` a guardar. 422 se o alvo é de outro livro."""
    if novo.tipo == TipoDeFavorito.LIVRO:
        _exigir_so(novo)
        return {}, None
    if novo.tipo == TipoDeFavorito.PARAGRAFO:
        _exigir_so(novo, "capitulo_id", "posicao")
        capitulo = _capitulo_do_livro(sessao, livro_id, novo.capitulo_id)
        _conferir_posicao(capitulo, novo.posicao)
        return {"capitulo_id": novo.capitulo_id, "posicao": novo.posicao}, _comeco_do_paragrafo(capitulo, novo.posicao)
    if novo.tipo == TipoDeFavorito.ELEMENTO:
        _exigir_so(novo, "elemento_id")
        elemento = buscar_elemento(sessao, novo.elemento_id)
        if elemento.livro_id != livro_id:
            _recusar(f"O elemento {novo.elemento_id} não é deste livro.")
        return {"elemento_id": novo.elemento_id}, None
    if novo.tipo == TipoDeFavorito.CENA:
        _exigir_so(novo, "frame_id")
        frame = buscar_frame(sessao, novo.frame_id)
        if frame.capitulo.livro_id != livro_id:
            _recusar(f"A cena {novo.frame_id} não é deste livro.")
        if frame.tipo != TipoDeFrame.CENA:
            _recusar("Só uma cena se favorita por aqui: o retrato de um elemento é favoritado pelo próprio elemento.")
        return {"frame_id": novo.frame_id}, None
    _exigir_so(novo, "imagem_id")
    imagem = buscar_visivel(sessao, Imagem, novo.imagem_id)
    if imagem is None or imagem.apagada_em is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Imagem {novo.imagem_id} não encontrada.")
    if _livro_da_imagem(imagem) != livro_id:
        _recusar(f"A imagem {novo.imagem_id} não é deste livro.")
    return {"imagem_id": novo.imagem_id}, None


def _resposta(sessao: Session, favorito: Favorito) -> FavoritoResposta | None:
    """O favorito como a API o devolve, ou ``None`` se o alvo está na lixeira (ou sumiu): ele **não aparece** e volta se o alvo for restaurado."""
    capitulo: Capitulo | None = None
    frame_da_imagem: Frame | None = None
    if favorito.tipo == TipoDeFavorito.LIVRO:
        livro = sessao.get(Livro, favorito.livro_id)
        if livro is None or livro.apagado_em is not None:
            return None
        rotulo = livro.titulo
    elif favorito.tipo == TipoDeFavorito.PARAGRAFO:
        capitulo = sessao.get(Capitulo, favorito.capitulo_id)
        if capitulo is None:
            return None
        rotulo = favorito.trecho or "Parágrafo"
    elif favorito.tipo == TipoDeFavorito.ELEMENTO:
        elemento = sessao.get(Elemento, favorito.elemento_id)
        if elemento is None or elemento.apagado_em is not None:
            return None
        rotulo = elemento.nome
    elif favorito.tipo == TipoDeFavorito.CENA:
        frame = sessao.get(Frame, favorito.frame_id)
        if frame is None or frame.apagado_em is not None:
            return None
        capitulo = frame.capitulo
        rotulo = frame.titulo
    else:
        imagem = sessao.get(Imagem, favorito.imagem_id)
        if imagem is None or imagem.apagada_em is not None or imagem.prompt is None or imagem.prompt.frame is None:
            return None
        frame = imagem.prompt.frame
        if frame.apagado_em is not None:
            return None
        capitulo = frame.capitulo
        frame_da_imagem = frame
        rotulo = f"Imagem de {frame.titulo}"
    return FavoritoResposta(
        id=favorito.id,
        livro_id=favorito.livro_id,
        tipo=favorito.tipo,
        rotulo=rotulo,
        capitulo_id=capitulo.id if capitulo is not None else None,
        ordem_do_capitulo=capitulo.ordem if capitulo is not None else None,
        titulo_do_capitulo=capitulo.titulo if capitulo is not None else None,
        posicao=favorito.posicao,
        elemento_id=favorito.elemento_id,
        # Na imagem, o frame de onde ela é (não está guardado: vem do prompt dela): é o que leva o app ao lugar certo no capítulo.
        frame_id=favorito.frame_id or (frame_da_imagem.id if frame_da_imagem is not None else None),
        imagem_id=favorito.imagem_id,
        criado_em=favorito.criado_em,
    )


@rotas_de_livro.get("/{livro_id}/favoritos", response_model=list[FavoritoResposta], summary="Os favoritos de um livro")
def listar_favoritos(
    livro_id: int,
    tipo: TipoDeFavorito | None = Query(default=None, description="Só os deste tipo; ausente = todos."),
    sessao: Session = Depends(obter_sessao),
) -> list[FavoritoResposta]:
    """Do mais novo para o mais antigo. **Só os que ainda existem** (RL34): o alvo na lixeira não aparece e volta se for restaurado."""
    buscar_livro(sessao, livro_id)
    consulta = select(Favorito).where(Favorito.livro_id == livro_id).order_by(Favorito.id.desc())
    if tipo is not None:
        consulta = consulta.where(Favorito.tipo == tipo)
    respostas = (_resposta(sessao, f) for f in sessao.scalars(consulta))
    return [r for r in respostas if r is not None]


@rotas_de_livro.post(
    "/{livro_id}/favoritos",
    response_model=FavoritoResposta,
    status_code=status.HTTP_201_CREATED,
    summary="Favorita um item do livro (idempotente)",
)
def favoritar(livro_id: int, novo: FavoritoNovo, resposta: Response, sessao: Session = Depends(obter_sessao)) -> FavoritoResposta:
    """Favorita o item. **Favoritar de novo o que já é favorito devolve o que já existe, com 200** (RL32): o app não precisa conferir antes."""
    buscar_livro(sessao, livro_id)
    alvo, trecho = _validar_e_procurar(sessao, livro_id, novo)

    # Um por alvo: o que não faz parte do alvo deste tipo é nulo no registro, e entra na busca como nulo.
    condicoes = [Favorito.livro_id == livro_id, Favorito.tipo == novo.tipo]
    for campo in ("capitulo_id", "posicao", "elemento_id", "frame_id", "imagem_id"):
        coluna = getattr(Favorito, campo)
        condicoes.append(coluna == alvo[campo] if campo in alvo else coluna.is_(None))
    existente = sessao.scalars(select(Favorito).where(*condicoes)).first()
    if existente is not None:
        resposta.status_code = status.HTTP_200_OK
        return _resposta(sessao, existente) or _resposta_do_recem_criado(sessao, existente)

    favorito = Favorito(livro_id=livro_id, tipo=novo.tipo, trecho=trecho, **alvo)
    sessao.add(favorito)
    sessao.commit()
    sessao.refresh(favorito)
    return _resposta_do_recem_criado(sessao, favorito)


def _resposta_do_recem_criado(sessao: Session, favorito: Favorito) -> FavoritoResposta:
    """O favorito que acabou de ser criado ou achado: o alvo foi conferido, então ele existe."""
    resposta = _resposta(sessao, favorito)
    if resposta is None:  # alvo na lixeira entre a conferência e aqui: não deveria acontecer
        _recusar("O item não está mais disponível.")
    return resposta


@rotas.delete("/{favorito_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Desfavorita")
def desfavoritar(favorito_id: int, sessao: Session = Depends(obter_sessao)) -> Response:
    sessao.delete(obter_ou_404(sessao, Favorito, favorito_id, "favorito"))
    sessao.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
