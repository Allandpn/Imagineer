"""Rota dos custos de IA (item 7.5b, CU4): quanto se gastou no mês, e onde."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.custos import CustosDoMes, GastoAgrupado
from imagineer.servicos.acesso import gastos_da_pessoa, usuario_ou_dono
from imagineer.modelos import Livro, UsoDeIA

rotas = APIRouter(prefix="/custos", tags=["Custos"])

ZERO = Decimal("0")


@rotas.get("", response_model=CustosDoMes, summary="Os custos de IA de um mês, por provedor, operação, livro e modelo")
def custos_do_mes(
    mes: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="`AAAA-MM`; o padrão é o mês atual."),
    sessao: Session = Depends(obter_sessao),
) -> CustosDoMes:
    """Soma o que foi registrado em ``usos_ia`` no mês. Só entra no total o que tem **custo conhecido**; as chamadas sem custo
    (o fornecedor não informou e a tabela de preços não tem o modelo) aparecem em ``sem_custo``. ``estimado`` é a parte do total
    que veio da tabela de preços."""
    inicio = _inicio_do_mes(mes)
    fim = datetime(inicio.year + (inicio.month == 12), inicio.month % 12 + 1, 1, tzinfo=timezone.utc)

    linhas = sessao.scalars(select(UsoDeIA).where(UsoDeIA.criado_em >= inicio, UsoDeIA.criado_em < fim, gastos_da_pessoa(sessao))).all()  # CT10
    titulos = dict(sessao.execute(select(Livro.id, Livro.titulo).where(Livro.usuario_id == usuario_ou_dono(sessao))).all())

    por_provedor, por_operacao, por_livro, por_modelo = (defaultdict(_Acumulado) for _ in range(4))
    total = estimado = ZERO
    sem_custo = 0
    for uso in linhas:
        custo = uso.custo
        if custo is not None:
            total += custo
            if uso.estimado:
                estimado += custo
        else:
            sem_custo += 1
        por_provedor[(uso.provedor, None)].somar(custo)
        por_operacao[(uso.operacao, None)].somar(custo)
        por_modelo[(uso.modelo, None)].somar(custo)
        por_livro[(titulos.get(uso.livro_id, "Sem livro") if uso.livro_id is not None else "Sem livro", uso.livro_id)].somar(custo)

    return CustosDoMes(
        mes=inicio.strftime("%Y-%m"),
        total=total,
        estimado=estimado,
        chamadas=len(linhas),
        sem_custo=sem_custo,
        por_provedor=_ordenar(por_provedor),
        por_operacao=_ordenar(por_operacao),
        por_livro=_ordenar(por_livro),
        por_modelo=_ordenar(por_modelo),
        meses_com_gasto=_meses_com_gasto(sessao),
    )


class _Acumulado:
    """O que se soma de um grupo: o total com custo, quantas chamadas e quantas sem custo."""

    def __init__(self) -> None:
        self.total = ZERO
        self.chamadas = 0
        self.sem_custo = 0

    def somar(self, custo: Decimal | None) -> None:
        self.chamadas += 1
        if custo is None:
            self.sem_custo += 1
        else:
            self.total += custo


def _ordenar(grupos: dict[tuple[str, int | None], _Acumulado]) -> list[GastoAgrupado]:
    """Do que mais custou para o que menos custou (e, empatando, o nome)."""
    ordenados = sorted(grupos.items(), key=lambda item: (-item[1].total, item[0][0]))
    return [
        GastoAgrupado(nome=nome, livro_id=livro_id, total=acumulado.total, chamadas=acumulado.chamadas, sem_custo=acumulado.sem_custo)
        for (nome, livro_id), acumulado in ordenados
    ]


def _inicio_do_mes(mes: str | None) -> datetime:
    if mes is None:
        agora = datetime.now(timezone.utc)
        return datetime(agora.year, agora.month, 1, tzinfo=timezone.utc)
    try:
        ano, numero = mes.split("-")
        return datetime(int(ano), int(numero), 1, tzinfo=timezone.utc)
    except ValueError as erro:  # o padrão da Query já barra isto; a rede de segurança fica
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Use o mês como AAAA-MM.") from erro


def _meses_com_gasto(sessao: Session) -> list[str]:
    datas = sessao.scalars(select(UsoDeIA.criado_em).where(gastos_da_pessoa(sessao))).all()
    return sorted({f"{d.year:04d}-{d.month:02d}" for d in datas}, reverse=True)
