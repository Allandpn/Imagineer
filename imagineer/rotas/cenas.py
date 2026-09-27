"""Rotas de cenas (Etapa 6.4).

A cena é o recorte narrativo que vai virar uma imagem. O que ela guarda de
próprio são os atributos situacionais — horário, clima, humor — e o que ela
referencia são os **estados** dos elementos, não os elementos: é isso que registra
*como* cada um estava naquele ponto (item 3.4c).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.cena import (
    CenaAjuste,
    CenaDetalhe,
    CenaNova,
    CenaResumo,
    EstadoComElemento,
    EstadosDaCena,
)
from imagineer.modelos import (
    Capitulo,
    Cena,
    Elemento,
    EstadoElemento,
    cenas_estados_elemento,
)

rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Cenas"])
rotas = APIRouter(prefix="/cenas", tags=["Cenas"])


@rotas_de_capitulo.get(
    "/{capitulo_id}/cenas",
    response_model=list[CenaResumo],
    summary="Lista as cenas de um capítulo",
)
def listar_cenas(
    capitulo_id: int, sessao: Session = Depends(obter_sessao)
) -> list[CenaResumo]:
    """As cenas do capítulo, na ordem em que foram criadas.

    A Cena não tem campo ``ordem``, diferente do Capítulo (item 3.4c): as cenas são
    criadas enquanto o usuário lê o capítulo, então a ordem de criação já é a
    narrativa.
    """
    _buscar_capitulo(sessao, capitulo_id)

    cenas = list(
        sessao.scalars(
            select(Cena).where(Cena.capitulo_id == capitulo_id).order_by(Cena.id)
        )
    )
    contagens = _contar_elementos(sessao, [cena.id for cena in cenas])

    return [_resumo(cena, contagens.get(cena.id, 0)) for cena in cenas]


@rotas_de_capitulo.post(
    "/{capitulo_id}/cenas",
    response_model=CenaDetalhe,
    status_code=status.HTTP_201_CREATED,
    summary="Cria uma cena",
)
def criar_cena(
    capitulo_id: int, nova: CenaNova, sessao: Session = Depends(obter_sessao)
) -> CenaDetalhe:
    """Cria a cena e, se vier, já liga os estados dos elementos que aparecem nela."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    cena = Cena(
        capitulo_id=capitulo.id,
        titulo=nova.titulo,
        descricao=nova.descricao,
        horario=nova.horario,
        clima=nova.clima,
        humor=nova.humor,
    )
    cena.estados_elemento = _estados_do_livro(sessao, nova.estados_ids, capitulo.livro_id)

    sessao.add(cena)
    sessao.commit()
    sessao.refresh(cena)
    return _detalhe(sessao, cena)


@rotas.get("/{cena_id}", response_model=CenaDetalhe, summary="Abre uma cena")
def abrir_cena(cena_id: int, sessao: Session = Depends(obter_sessao)) -> CenaDetalhe:
    """A cena com os elementos que aparecem nela, cada um no seu estado."""
    return _detalhe(sessao, _buscar_cena(sessao, cena_id))


@rotas.patch("/{cena_id}", response_model=CenaDetalhe, summary="Ajusta uma cena")
def ajustar_cena(
    cena_id: int, ajuste: CenaAjuste, sessao: Session = Depends(obter_sessao)
) -> CenaDetalhe:
    """Muda título, descrição ou os atributos situacionais."""
    cena = _buscar_cena(sessao, cena_id)

    for campo, valor in ajuste.model_dump(exclude_unset=True).items():
        setattr(cena, campo, valor)

    sessao.commit()
    sessao.refresh(cena)
    return _detalhe(sessao, cena)


@rotas.put(
    "/{cena_id}/estados",
    response_model=CenaDetalhe,
    summary="Define quem aparece na cena",
)
def definir_estados(
    cena_id: int, corpo: EstadosDaCena, sessao: Session = Depends(obter_sessao)
) -> CenaDetalhe:
    """Substitui a lista de estados da cena pela que veio no pedido.

    É ``PUT`` porque o app manda o conjunto inteiro: na tela, o usuário marca e
    desmarca elementos e salva. Trocar a lista **não** apaga estado nenhum — só
    desfaz as ligações.
    """
    cena = _buscar_cena(sessao, cena_id)
    capitulo = _buscar_capitulo(sessao, cena.capitulo_id)

    cena.estados_elemento = _estados_do_livro(sessao, corpo.estados_ids, capitulo.livro_id)
    sessao.commit()
    sessao.refresh(cena)
    return _detalhe(sessao, cena)


@rotas.delete(
    "/{cena_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove uma cena"
)
def remover_cena(cena_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga a cena e os prompts dela — mas **não** os estados que ela citava.

    Um estado pertence ao elemento e à narrativa, não à cena que o referenciou
    (item 3.4c).
    """
    sessao.delete(_buscar_cena(sessao, cena_id))
    sessao.commit()


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _estados_do_livro(
    sessao: Session, estados_ids: list[int], livro_id: int
) -> list[EstadoElemento]:
    """Carrega os estados pedidos, exigindo que sejam todos do mesmo livro.

    Nada no banco impede associar a uma cena o estado de um personagem de outro
    livro: a cena aponta para um capítulo e o estado aponta para um elemento, e as
    duas cadeias são independentes. Sem esta checagem o prompt sairia com um
    personagem que não pertence à história.

    Ids repetidos são contados uma vez. A chave primária da tabela de associação já
    impediria o repetido, e devolver erro por isso só criaria trabalho para o app.
    """
    pedidos = list(dict.fromkeys(estados_ids))
    if not pedidos:
        return []

    encontrados = list(
        sessao.scalars(select(EstadoElemento).where(EstadoElemento.id.in_(pedidos)))
    )

    ausentes = sorted(set(pedidos) - {estado.id for estado in encontrados})
    if ausentes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existem estados com os ids {ausentes}.",
        )

    livros_por_estado = dict(
        sessao.execute(
            select(EstadoElemento.id, Elemento.livro_id)
            .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
            .where(EstadoElemento.id.in_(pedidos))
        ).all()
    )
    de_outro_livro = sorted(
        identificador
        for identificador, dono in livros_por_estado.items()
        if dono != livro_id
    )
    if de_outro_livro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Os estados {de_outro_livro} pertencem a elementos de outro livro, "
                f"não do livro {livro_id}."
            ),
        )

    # Devolve na ordem em que o app pediu, que é a ordem que a tela mostra.
    por_id = {estado.id: estado for estado in encontrados}
    return [por_id[identificador] for identificador in pedidos]


def _contar_elementos(sessao: Session, cenas_ids: list[int]) -> dict[int, int]:
    """Quantos estados cada cena referencia, numa consulta só."""
    if not cenas_ids:
        return {}

    return dict(
        sessao.execute(
            select(
                cenas_estados_elemento.c.cena_id,
                func.count(cenas_estados_elemento.c.estado_elemento_id),
            )
            .where(cenas_estados_elemento.c.cena_id.in_(cenas_ids))
            .group_by(cenas_estados_elemento.c.cena_id)
        ).all()
    )


def _resumo(cena: Cena, total: int) -> CenaResumo:
    return CenaResumo(
        id=cena.id,
        capitulo_id=cena.capitulo_id,
        titulo=cena.titulo,
        descricao=cena.descricao,
        horario=cena.horario,
        clima=cena.clima,
        humor=cena.humor,
        total_de_elementos=total,
    )


def _detalhe(sessao: Session, cena: Cena) -> CenaDetalhe:
    """A cena com cada estado acompanhado da identidade do elemento."""
    linhas = sessao.execute(
        select(
            EstadoElemento.id,
            Elemento.id,
            Elemento.tipo,
            Elemento.nome,
            EstadoElemento.descricao,
            EstadoElemento.capitulo_id,
        )
        .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
        .join(
            cenas_estados_elemento,
            cenas_estados_elemento.c.estado_elemento_id == EstadoElemento.id,
        )
        .where(cenas_estados_elemento.c.cena_id == cena.id)
        .order_by(Elemento.tipo, Elemento.nome)
    ).all()

    elementos = [
        EstadoComElemento(
            estado_id=estado_id,
            elemento_id=elemento_id,
            tipo=tipo,
            nome=nome,
            descricao=descricao,
            capitulo_id=capitulo_id,
        )
        for estado_id, elemento_id, tipo, nome, descricao, capitulo_id in linhas
    ]

    return CenaDetalhe(
        **_resumo(cena, len(elementos)).model_dump(),
        elementos=elementos,
    )


def _buscar_cena(sessao: Session, cena_id: int) -> Cena:
    cena = sessao.get(Cena, cena_id)
    if cena is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe cena com id {cena_id}.",
        )
    return cena


def _buscar_capitulo(sessao: Session, capitulo_id: int) -> Capitulo:
    capitulo = sessao.get(Capitulo, capitulo_id)
    if capitulo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe capítulo com id {capitulo_id}.",
        )
    return capitulo
