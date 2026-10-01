"""Acrescentar, corrigir e apagar à mão os acréscimos de identidade (itens 3.4f, 6.3 e 7.5b, rodada 5)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Elemento
from imagineer.servicos.identidade_de_elemento import identidade_vigente

from testes.teste_rotas_sugestoes import _livro_com_capitulos


def _cenario(cliente: TestClient):
    livro = _livro_com_capitulos(cliente, capitulos=3)
    c1, c2, c3 = livro["capitulos"]
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "descricao": "Bastardo."},
    ).json()
    return livro, (c1, c2, c3), jon


def teste_criar_acrescimo_devolve_com_a_posicao_e_o_titulo_do_capitulo(cliente: TestClient) -> None:
    _, (c1, c2, _c3), jon = _cenario(cliente)

    resposta = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade",
        json={"capitulo_id": c2["id"], "descricao": "Agora é Lorde Comandante."},
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["descricao"] == "Agora é Lorde Comandante."
    assert corpo["capitulo_id"] == c2["id"]
    assert corpo["ordem_do_capitulo"] == c2["ordem"]
    assert corpo["titulo_do_capitulo"] == c2["titulo"]


def teste_o_acrescimo_aparece_na_ficha_e_soma_na_identidade_vigente(
    cliente: TestClient, sessao_com_tabelas: Session
) -> None:
    _, (c1, c2, c3), jon = _cenario(cliente)
    cliente.post(
        f"/elementos/{jon['id']}/historico-identidade",
        json={"capitulo_id": c2["id"], "descricao": "Agora é Lorde Comandante."},
    )

    ficha = cliente.get(f"/elementos/{jon['id']}").json()
    elemento = sessao_com_tabelas.get(Elemento, jon["id"])

    assert [h["descricao"] for h in ficha["historico_identidade"]] == ["Agora é Lorde Comandante."]
    # A identidade vigente (a que vai à IA e aparece no cartão) soma a inicial com o acréscimo,
    # mas só a partir do capítulo em que ele foi revelado.
    assert identidade_vigente(sessao_com_tabelas, elemento, c1["ordem"]) == "Bastardo."
    assert identidade_vigente(sessao_com_tabelas, elemento, c3["ordem"]) == "Bastardo. Agora é Lorde Comandante."


def teste_texto_vazio_e_recusado(cliente: TestClient) -> None:
    _, (c1, *_), jon = _cenario(cliente)

    resposta = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c1["id"], "descricao": ""}
    )

    assert resposta.status_code == 422


def teste_capitulo_de_outro_livro_e_recusado(cliente: TestClient) -> None:
    _, _, jon = _cenario(cliente)
    outro = _livro_com_capitulos(cliente, capitulos=1, identificador="urn:isbn:2")

    resposta = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade",
        json={"capitulo_id": outro["capitulos"][0]["id"], "descricao": "x"},
    )

    assert resposta.status_code == 422
    assert cliente.get(f"/elementos/{jon['id']}").json()["historico_identidade"] == []


def teste_elemento_ou_capitulo_inexistente_responde_404(cliente: TestClient) -> None:
    _, (c1, *_), jon = _cenario(cliente)

    assert cliente.post("/elementos/9999/historico-identidade", json={"capitulo_id": c1["id"], "descricao": "x"}).status_code == 404
    assert cliente.post(f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": 9999, "descricao": "x"}).status_code == 404


def teste_corrigir_o_texto_de_um_acrescimo(cliente: TestClient) -> None:
    _, (_c1, c2, _c3), jon = _cenario(cliente)
    criado = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c2["id"], "descricao": "Errado."}
    ).json()

    resposta = cliente.patch(f"/historico-identidade/{criado['id']}", json={"descricao": "Certo."})

    assert resposta.status_code == 200 and resposta.json()["descricao"] == "Certo."
    assert cliente.get(f"/elementos/{jon['id']}").json()["historico_identidade"][0]["descricao"] == "Certo."


def teste_corrigir_para_vazio_e_recusado_e_inexistente_e_404(cliente: TestClient) -> None:
    _, (_c1, c2, _c3), jon = _cenario(cliente)
    criado = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c2["id"], "descricao": "Ok."}
    ).json()

    assert cliente.patch(f"/historico-identidade/{criado['id']}", json={"descricao": ""}).status_code == 422
    assert cliente.patch("/historico-identidade/9999", json={"descricao": "x"}).status_code == 404


def teste_apagar_um_acrescimo(cliente: TestClient) -> None:
    _, (_c1, c2, _c3), jon = _cenario(cliente)
    criado = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c2["id"], "descricao": "Ok."}
    ).json()

    resposta = cliente.delete(f"/historico-identidade/{criado['id']}")

    assert resposta.status_code == 204
    assert cliente.get(f"/elementos/{jon['id']}").json()["historico_identidade"] == []
    assert cliente.delete(f"/historico-identidade/{criado['id']}").status_code == 404


def teste_mudar_acrescimos_sobe_a_revisao_do_livro(cliente: TestClient) -> None:
    livro, (_c1, c2, _c3), jon = _cenario(cliente)
    revisao = lambda: cliente.get(f"/livros/{livro['id']}").json()["revisao"]  # noqa: E731
    antes = revisao()

    criado = cliente.post(
        f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c2["id"], "descricao": "a"}
    ).json()
    depois_de_criar = revisao()
    cliente.patch(f"/historico-identidade/{criado['id']}", json={"descricao": "b"})
    depois_de_corrigir = revisao()
    cliente.delete(f"/historico-identidade/{criado['id']}")

    assert antes < depois_de_criar < depois_de_corrigir < revisao()
