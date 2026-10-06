"""Rota da pesquisa no texto dos livros (item 7.5b, LV5): no capítulo, no livro ou na biblioteca."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.busca import OcorrenciaNoTexto, ResultadoDaBusca
from imagineer.servicos.acesso import usuario_ou_dono
from imagineer.modelos import Capitulo, Livro
from imagineer.rotas._comum import buscar_capitulo as _buscar_capitulo, buscar_livro as _buscar_livro
from imagineer.servicos.busca_no_texto import procurar

rotas = APIRouter(prefix="/busca", tags=["Busca"])

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


@rotas.get("", response_model=ResultadoDaBusca, summary="Procura um termo no texto dos capítulos")
def buscar(
    q: str = Query(min_length=2, description="O que procurar (sem acento, sem diferença de maiúsculas)."),
    livro_id: int | None = Query(None, description="Só neste livro. Sem ele (e sem `capitulo_id`): a biblioteca inteira."),
    capitulo_id: int | None = Query(None, description="Só neste capítulo."),
    limite: int = Query(LIMITE_PADRAO, ge=1, le=LIMITE_MAXIMO),
    sessao: Session = Depends(obter_sessao),
) -> ResultadoDaBusca:
    """As ocorrências de ``q`` em livros, na ordem da biblioteca (título), do capítulo e do texto.

    Os capítulos **arquivados** ficam de fora: o leitor não os mostra. Vem no máximo ``limite``
    ocorrências, mas ``total`` conta todas, para o app dizer "e mais N".
    """
    consulta = (
        select(Livro.id, Livro.titulo, Capitulo.id, Capitulo.ordem, Capitulo.titulo, Capitulo.texto)
        .join(Capitulo, Capitulo.livro_id == Livro.id)
        .where(Capitulo.ignorado.is_(False), Livro.apagado_em.is_(None), Livro.usuario_id == usuario_ou_dono(sessao))  # lixeira (LT2); só os da pessoa (CT6-c)
        .order_by(Livro.titulo, Livro.id, Capitulo.ordem)
    )
    if capitulo_id is not None:
        _buscar_capitulo(sessao, capitulo_id)  # 404 se não existe
        consulta = consulta.where(Capitulo.id == capitulo_id)
    elif livro_id is not None:
        _buscar_livro(sessao, livro_id)  # 404 se não existe
        consulta = consulta.where(Livro.id == livro_id)

    ocorrencias: list[OcorrenciaNoTexto] = []
    total = 0
    # yield_per: o texto de uma biblioteca inteira não cabe numa leitura só; lê um punhado de capítulos por vez.
    for livro, livro_titulo, capitulo, ordem, capitulo_titulo, texto in sessao.execute(consulta).yield_per(20):
        for achado in procurar(texto, q):
            total += 1
            if len(ocorrencias) < limite:
                ocorrencias.append(
                    OcorrenciaNoTexto(
                        livro_id=livro,
                        livro_titulo=livro_titulo,
                        capitulo_id=capitulo,
                        capitulo_ordem=ordem,
                        capitulo_titulo=capitulo_titulo,
                        posicao_no_texto=achado.posicao_no_texto,
                        inicio_do_paragrafo=achado.inicio_do_paragrafo,
                        trecho=achado.trecho,
                        inicio_no_trecho=achado.inicio_no_trecho,
                        fim_no_trecho=achado.fim_no_trecho,
                    )
                )
    return ResultadoDaBusca(termo=q, total=total, ocorrencias=ocorrencias, truncado=total > len(ocorrencias))
