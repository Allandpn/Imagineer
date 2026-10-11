"""os pins viram favoritos de paragrafo (item 7.5g, FV4)

Os Pins saem do app (pin e favorito de paragrafo se confundiam; a decisao do Allan foi ficar so com os favoritos). Esta migration converte cada
pin que ja existe em um favorito de tipo PARAGRAFO, no mesmo livro, capitulo e posicao, para ninguem perder o que marcou.

- O `trecho` do favorito (o comeco do paragrafo, ate 300 caracteres) e calculado aqui a partir do texto do capitulo, do mesmo jeito que a rota
  de favoritos o faz. Se nao der para calcular (paragrafo vazio), vale a nota do pin, se houver.
- Um paragrafo que ja era favorito NAO e duplicado.
- A tabela `pins` e as rotas `/pins` FICAM, sem uso: nada e apagado. Por isso o `downgrade` nao desfaz nada (os favoritos criados continuam
  valendo; um pin so existe de verdade na tabela `pins`, que nao foi tocada).

Identificador desta migration: d1e2f3a4b5c7
Vem depois de: c0d1e2f3a4b6
Criada em: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c7'
down_revision: Union[str, Sequence[str], None] = 'c0d1e2f3a4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LIMITE_DO_TRECHO = 300
"""O mesmo da rota de favoritos: quanto do comeco do paragrafo se guarda."""


def _comeco_do_paragrafo(texto: str, posicao: int) -> str:
    """O comeco do paragrafo que COMECA em `posicao` (UTF-16): ate a linha em branco seguinte, em um espaco so, e no maximo 300 caracteres.
    E uma copia da regra da rota (uma migration nao importa o codigo da aplicacao: ele muda, e a migration tem de continuar fazendo o que fez)."""
    em_bytes = texto.encode("utf-16-le")
    resto = em_bytes[posicao * 2:].decode("utf-16-le", errors="ignore")
    paragrafo = resto.split("\n\n", 1)[0]
    limpo = " ".join(paragrafo.split())
    if len(limpo) <= LIMITE_DO_TRECHO:
        return limpo
    return limpo[:LIMITE_DO_TRECHO].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"


def aplicar() -> None:
    """Cria um favorito PARAGRAFO para cada pin que ainda nao e favorito."""
    conexao = op.get_bind()
    metadados = sa.MetaData()
    pins = sa.Table("pins", metadados, autoload_with=conexao)
    favoritos = sa.Table("favoritos", metadados, autoload_with=conexao)
    capitulos = sa.Table("capitulos", metadados, autoload_with=conexao)

    ja_favoritos = {
        (linha.livro_id, linha.capitulo_id, linha.posicao)
        for linha in conexao.execute(
            sa.select(favoritos.c.livro_id, favoritos.c.capitulo_id, favoritos.c.posicao).where(favoritos.c.tipo == "PARAGRAFO")
        )
    }
    for pin in conexao.execute(sa.select(pins).order_by(pins.c.id)).all():
        chave = (pin.livro_id, pin.capitulo_id, pin.posicao_no_texto)
        if chave in ja_favoritos:
            continue
        texto = conexao.scalar(sa.select(capitulos.c.texto).where(capitulos.c.id == pin.capitulo_id)) or ""
        trecho = _comeco_do_paragrafo(texto, pin.posicao_no_texto) or (pin.nota or None)
        conexao.execute(
            favoritos.insert().values(
                livro_id=pin.livro_id,
                tipo="PARAGRAFO",
                capitulo_id=pin.capitulo_id,
                posicao=pin.posicao_no_texto,
                trecho=trecho,
                criado_em=pin.criado_em,
            )
        )
        ja_favoritos.add(chave)


def reverter() -> None:
    """Nao desfaz nada: os pins nunca foram apagados (a tabela `pins` continua como estava), e os favoritos criados agora podem ter sido
    editados ou apagados pela pessoa depois. Nao ha o que reverter sem risco de apagar favoritos de verdade."""


upgrade = aplicar
downgrade = reverter
