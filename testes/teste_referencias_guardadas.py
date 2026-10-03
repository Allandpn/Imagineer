"""As imagens de referência guardadas no servidor (item 7.5b, RS1 a RS3): a escolha do frame e o histórico por imagem."""

from fastapi.testclient import TestClient

from testes.teste_rotas_prompts import (
    MODELO_COM_REFERENCIA,
    _cena_com_referencia,
    _diretorio_de_imagens,  # noqa: F401
    _imagem_importada,
)


def _referencias(cliente: TestClient, frame_id: int, ids: list[int]):
    return cliente.put(f"/frames/{frame_id}/referencias", json={"imagens_ids": ids})


def teste_rs1_o_frame_comeca_sem_referencias_escolhidas(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, cena, _ = _cena_com_referencia(cliente, usar_provedor_falso)

    assert cliente.get(f"/frames/{cena['id']}").json()["imagens_de_referencia"] == []


def teste_rs1_guardar_e_ler_de_volta_na_ordem_escolhida(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, cena, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    a, b = _imagem_importada(cliente, prompt["id"]), _imagem_importada(cliente, prompt["id"])

    resposta = _referencias(cliente, cena["id"], [b["id"], a["id"]])

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["imagens_de_referencia"] == [b["id"], a["id"]]
    assert cliente.get(f"/frames/{cena['id']}").json()["imagens_de_referencia"] == [b["id"], a["id"]]


def teste_rs1_lista_vazia_limpa_a_escolha(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, cena, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    _referencias(cliente, cena["id"], [_imagem_importada(cliente, prompt["id"])["id"]])

    resposta = _referencias(cliente, cena["id"], [])

    assert resposta.status_code == 200 and resposta.json()["imagens_de_referencia"] == []


def teste_rs3_recusas(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, cena, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    a = _imagem_importada(cliente, prompt["id"])

    assert _referencias(cliente, cena["id"], [99999]).status_code == 422  # não existe
    assert _referencias(cliente, cena["id"], [a["id"], a["id"]]).status_code == 422  # repetida
    assert _referencias(cliente, cena["id"], [1, 2, 3, 4, 5]).status_code == 422  # mais de 4
    assert _referencias(cliente, 99999, [a["id"]]).status_code == 404
    assert cliente.get(f"/frames/{cena['id']}").json()["imagens_de_referencia"] == []  # nada foi gravado


def teste_rs3_imagem_da_lixeira_nao_serve_de_referencia(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, cena, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    a = _imagem_importada(cliente, prompt["id"])
    cliente.delete(f"/imagens/{a['id']}")

    assert _referencias(cliente, cena["id"], [a["id"]]).status_code == 422


def teste_rs1_a_imagem_que_vai_para_a_lixeira_sai_da_escolha(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, cena, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    a, b = _imagem_importada(cliente, prompt["id"]), _imagem_importada(cliente, prompt["id"])
    _referencias(cliente, cena["id"], [a["id"], b["id"]])

    cliente.delete(f"/imagens/{a['id']}")

    assert cliente.get(f"/frames/{cena['id']}").json()["imagens_de_referencia"] == [b["id"]]
    # Restaurar a traz de volta à escolha, porque o id continua guardado (só some da leitura enquanto está na lixeira).
    cliente.post(f"/lixeira/imagens/{a['id']}/restaurar")
    assert cliente.get(f"/frames/{cena['id']}").json()["imagens_de_referencia"] == [a["id"], b["id"]]


def teste_rs2_a_imagem_gerada_guarda_as_referencias_que_usou_e_a_importada_nao(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    ref = _imagem_importada(cliente, prompt["id"])

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_COM_REFERENCIA, "imagens_de_referencia": [ref["id"]]}
    ).json()

    assert corpo["imagem"]["imagens_de_referencia"] == [ref["id"]]
    assert ref["imagens_de_referencia"] == []  # importada: nenhuma
    detalhe = cliente.get(f"/prompts/{prompt['id']}").json()["imagens"]
    assert {i["id"]: i["imagens_de_referencia"] for i in detalhe} == {ref["id"]: [], corpo["imagem"]["id"]: [ref["id"]]}


def teste_rs2_cada_imagem_guarda_as_suas_referencias_mesmo_que_o_prompt_guarde_so_a_ultima(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, _, _, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    r1, r2 = _imagem_importada(cliente, prompt["id"]), _imagem_importada(cliente, prompt["id"])
    primeira = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_COM_REFERENCIA, "imagens_de_referencia": [r1["id"]]}
    ).json()["imagem"]
    segunda = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_COM_REFERENCIA, "imagens_de_referencia": [r2["id"]]}
    ).json()["imagem"]

    assert cliente.get(f"/prompts/{prompt['id']}").json()["imagens_de_referencia"] == [r2["id"]]  # W7: só a última
    imagens = {i["id"]: i["imagens_de_referencia"] for i in cliente.get(f"/prompts/{prompt['id']}").json()["imagens"]}
    assert imagens[primeira["id"]] == [r1["id"]] and imagens[segunda["id"]] == [r2["id"]]  # RS2: cada uma a sua
