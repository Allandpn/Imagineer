"""Tempo de leitura e estatísticas (RL16, RL17)."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Livro
from testes.teste_rotas_sugestoes import _livro_com_capitulos

HOJE = date.today()


def _somar(cliente: TestClient, livro_id: int, segundos: int, dia: date = HOJE):
    return cliente.post(f"/livros/{livro_id}/leitura/tempo", json={"dia": dia.isoformat(), "segundos": segundos})


def teste_soma_ao_dia_em_vez_de_criar_outro_registro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)

    assert _somar(cliente, livro["id"], 60).json()["segundos"] == 60
    assert _somar(cliente, livro["id"], 45).json()["segundos"] == 105

    estatisticas = cliente.get("/estatisticas/leitura").json()
    assert estatisticas["dias"] == [{"dia": HOJE.isoformat(), "segundos": 105}]


def teste_recusa_segundos_invalidos(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)

    assert _somar(cliente, livro["id"], 0).status_code == 422
    assert _somar(cliente, livro["id"], -5).status_code == 422
    assert _somar(cliente, livro["id"], 3601).status_code == 422
    assert _somar(cliente, livro["id"], 3600).status_code == 200


def teste_recusa_dia_no_futuro_mas_aceita_amanha_por_causa_do_fuso(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)

    assert _somar(cliente, livro["id"], 60, HOJE + timedelta(days=1)).status_code == 200
    assert _somar(cliente, livro["id"], 60, HOJE + timedelta(days=2)).status_code == 422


def teste_livro_inexistente_da_404(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    assert _somar(cliente, 999999, 60).status_code == 404


def teste_soma_dos_dias_junta_os_livros_e_o_resumo_e_por_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    a = _livro_com_capitulos(cliente, capitulos=1)
    b = _livro_com_capitulos(cliente, capitulos=1)
    ontem = HOJE - timedelta(days=1)
    _somar(cliente, a["id"], 600)
    _somar(cliente, a["id"], 300, ontem)
    _somar(cliente, b["id"], 120)

    corpo = cliente.get("/estatisticas/leitura").json()

    assert corpo["dias"] == [{"dia": ontem.isoformat(), "segundos": 300}, {"dia": HOJE.isoformat(), "segundos": 720}]
    por_livro = {l["livro_id"]: l for l in corpo["livros"]}
    assert por_livro[a["id"]]["segundos"] == 900
    assert por_livro[a["id"]]["dias_lidos"] == 2
    assert por_livro[a["id"]]["ultimo_dia"] == HOJE.isoformat()
    assert por_livro[b["id"]]["segundos"] == 120


def teste_so_os_ultimos_90_dias_entram_na_lista_de_dias(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    _somar(cliente, livro["id"], 60, HOJE - timedelta(days=100))
    _somar(cliente, livro["id"], 60)

    corpo = cliente.get("/estatisticas/leitura").json()

    assert [d["dia"] for d in corpo["dias"]] == [HOJE.isoformat()]
    assert corpo["livros"][0]["segundos"] == 120  # o resumo do livro conta tudo


def teste_livro_na_lixeira_fica_fora(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    _somar(cliente, livro["id"], 60)
    assert cliente.delete(f"/livros/{livro['id']}").status_code == 204

    corpo = cliente.get("/estatisticas/leitura").json()

    assert corpo == {"dias": [], "livros": []}


def teste_sem_leitura_a_lista_vem_vazia(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    assert cliente.get("/estatisticas/leitura").json() == {"dias": [], "livros": []}


def teste_nao_sobe_a_revisao_do_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    _somar(cliente, livro["id"], 60)

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] == antes
    assert sessao_com_tabelas.get(Livro, livro["id"]) is not None
