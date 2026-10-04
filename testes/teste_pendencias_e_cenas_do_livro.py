"""As telas Pendências e Cenas do livro (item 7.5b, LY7 e LY8): artefatos do livro inteiro, por capítulo."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from testes.teste_posicao_manual import _cenario
from testes.teste_rotas_prompts import _frame


def _livro_id(cliente: TestClient, capitulo_id: int) -> int:
    return cliente.get(f"/capitulos/{capitulo_id}").json()["livro_id"]


def teste_ly7_as_pendencias_reunem_elementos_e_cenas_sugeridos_por_capitulo(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)

    resposta = cliente.get(f"/livros/{_livro_id(cliente, capitulo_id)}/pendencias")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    [grupo] = corpo["capitulos"]
    assert grupo["capitulo_id"] == capitulo_id and grupo["ordem"] == 1
    assert {a["tipo"] for a in grupo["artefatos"]} == {"CENA", "ELEMENTO"}
    assert {a["rotulo"] for a in grupo["artefatos"] if a["tipo"] == "ELEMENTO"} == {"Arya"}
    assert corpo["total"] == len(grupo["artefatos"]) == 2
    assert all(a["situacao"] == "SUGERIDO" for a in grupo["artefatos"])


def teste_ly7_o_que_ja_foi_confirmado_sai_das_pendencias_e_capitulo_sem_pendencia_nao_aparece(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = _livro_id(cliente, capitulo_id)
    cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Arya", "estado_inicial": {"capitulo_id": capitulo_id, "descricao": "x"}},
    )
    from imagineer.modelos import SugestaoDeElemento

    sugestao = sessao_com_tabelas.query(SugestaoDeElemento).one()
    elemento = cliente.get(f"/livros/{livro_id}/elementos").json()[0]
    sugestao.elemento_id = elemento["id"]  # a sugestão foi confirmada
    sessao_com_tabelas.commit()

    corpo = cliente.get(f"/livros/{livro_id}/pendencias").json()

    assert [a["tipo"] for g in corpo["capitulos"] for a in g["artefatos"]] == ["CENA"]  # só a cena continua pendente
    assert corpo["total"] == 1


def teste_ly7_capitulo_arquivado_fica_de_fora(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = _livro_id(cliente, capitulo_id)
    assert cliente.patch(f"/capitulos/{capitulo_id}", json={"ignorado": True}).status_code == 200

    corpo = cliente.get(f"/livros/{livro_id}/pendencias").json()

    assert corpo == {"total": 0, "capitulos": []}


def teste_ly8_as_cenas_do_livro_trazem_sugeridas_e_confirmadas_com_a_situacao(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = _livro_id(cliente, capitulo_id)
    _frame(cliente, capitulo_id, [], tipo="CENA")  # uma cena de um trecho, já confirmada

    corpo = cliente.get(f"/livros/{livro_id}/cenas").json()

    [grupo] = corpo["capitulos"]
    assert all(a["tipo"] == "CENA" for a in grupo["artefatos"])
    assert sorted(a["situacao"] for a in grupo["artefatos"]) == ["CONFIRMADO", "SUGERIDO"]
    assert corpo["total"] == 2  # os elementos (Arya) não entram


def teste_ly8_livro_sem_cenas_e_livro_inexistente(cliente: TestClient) -> None:
    assert cliente.get("/livros/999/cenas").status_code == 404
    assert cliente.get("/livros/999/pendencias").status_code == 404


def teste_ly7_livro_na_lixeira_responde_404(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = _livro_id(cliente, capitulo_id)
    cliente.delete(f"/livros/{livro_id}")

    assert cliente.get(f"/livros/{livro_id}/pendencias").status_code == 404
    assert cliente.get(f"/livros/{livro_id}/cenas").status_code == 404
