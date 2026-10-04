"""Capítulo lido e progresso do livro (item 7.5b, LE1 e LE6): `PATCH /capitulos/{id}` com `lido`."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo
from testes.teste_rotas_sugestoes import _livro_com_capitulos


def _marcar(cliente: TestClient, capitulo_id: int, lido: bool):
    return cliente.patch(f"/capitulos/{capitulo_id}", json={"lido": lido})


def teste_capitulo_novo_nao_esta_lido_e_o_livro_tem_zero_lidos(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=3)

    assert [c["lido"] for c in livro["capitulos"]] == [False, False, False]
    assert livro["capitulos_lidos"] == 0
    assert cliente.get("/livros").json()[0]["capitulos_lidos"] == 0


def teste_marcar_como_lido_aparece_no_capitulo_no_livro_e_na_listagem(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=3)
    primeiro, segundo = livro["capitulos"][0]["id"], livro["capitulos"][1]["id"]

    resposta = _marcar(cliente, primeiro, True)
    _marcar(cliente, segundo, True)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["lido"] is True
    assert cliente.get(f"/capitulos/{primeiro}").json()["lido"] is True
    detalhe = cliente.get(f"/livros/{livro['id']}").json()
    assert [c["lido"] for c in detalhe["capitulos"]] == [True, True, False]
    assert detalhe["capitulos_lidos"] == 2
    assert cliente.get("/livros").json()[0]["capitulos_lidos"] == 2


def teste_desmarcar_volta_a_nao_lido(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    capitulo = livro["capitulos"][0]["id"]
    _marcar(cliente, capitulo, True)

    resposta = _marcar(cliente, capitulo, False)

    assert resposta.json()["lido"] is False
    assert cliente.get(f"/livros/{livro['id']}").json()["capitulos_lidos"] == 0


def teste_marcar_de_novo_mantem_a_hora_de_antes_e_ajustar_outro_campo_nao_mexe_no_lido(
    cliente: TestClient, sessao_com_tabelas: Session
) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    capitulo = livro["capitulos"][0]["id"]
    _marcar(cliente, capitulo, True)
    sessao_com_tabelas.expire_all()
    primeira_hora = sessao_com_tabelas.get(Capitulo, capitulo).lido_em

    _marcar(cliente, capitulo, True)
    cliente.patch(f"/capitulos/{capitulo}", json={"titulo": "Novo título"})  # sem `lido`: não mexe

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Capitulo, capitulo).lido_em == primeira_hora
    assert cliente.get(f"/capitulos/{capitulo}").json()["lido"] is True


def teste_capitulo_arquivado_nao_conta_no_progresso(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    lido, arquivado = livro["capitulos"][0]["id"], livro["capitulos"][1]["id"]
    _marcar(cliente, lido, True)
    _marcar(cliente, arquivado, True)

    cliente.patch(f"/capitulos/{arquivado}", json={"ignorado": True})

    assert cliente.get(f"/livros/{livro['id']}").json()["capitulos_lidos"] == 1
    assert cliente.get("/livros").json()[0]["capitulos_lidos"] == 1


def teste_marcar_lido_sobe_a_revisao_do_livro_para_o_outro_aparelho_ver(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    _marcar(cliente, livro["capitulos"][0]["id"], True)

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] > antes


def teste_capitulo_que_nao_existe_e_404(cliente: TestClient) -> None:
    assert _marcar(cliente, 999, True).status_code == 404


def teste_total_de_caracteres_do_livro_so_conta_os_capitulos_ativos(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=3)
    ids = [c["id"] for c in livro["capitulos"]]
    for capitulo_id, texto in zip(ids, ["a" * 100, "b" * 250, "c" * 1000]):
        sessao_com_tabelas.get(Capitulo, capitulo_id).texto = texto
    sessao_com_tabelas.commit()
    cliente.patch(f"/capitulos/{ids[2]}", json={"ignorado": True})

    assert cliente.get(f"/livros/{livro['id']}").json()["total_de_caracteres"] == 350
    assert cliente.get("/livros").json()[0]["total_de_caracteres"] == 350
