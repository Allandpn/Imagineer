"""A imagem canônica de um frame (item 7.5b, CAN1 a CAN9): a rota, a âncora do retrato e o que o capítulo mostra."""

from fastapi.testclient import TestClient

from testes.teste_galeria_do_elemento import _galeria, _montar, _prompt_do_frame
from testes.teste_rotas_prompts import _diretorio_de_imagens, _frame, _importar_imagem  # noqa: F401
from testes.teste_vinculos_do_retrato import _retrato


def _escolher(cliente: TestClient, frame_id: int, imagem_id: int | None):
    return cliente.put(f"/frames/{frame_id}/imagem-canonica", json={"imagem_id": imagem_id})


def _retrato_com_duas_imagens(cliente: TestClient, usar_provedor_falso):
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"]).json()
    prompt = _prompt_do_frame(cliente, retrato["id"])
    primeira = _importar_imagem(cliente, prompt["id"])
    segunda = _importar_imagem(cliente, prompt["id"])
    return capitulo, e, retrato, primeira, segunda


def teste_can3_escolher_grava_e_o_frame_informa(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, retrato, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    resposta = _escolher(cliente, retrato["id"], primeira["id"])

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"frame_id": retrato["id"], "imagem_canonica_id": primeira["id"]}
    assert cliente.get(f"/frames/{retrato['id']}").json()["imagem_canonica_id"] == primeira["id"]


def teste_can3_imagem_de_outro_frame_ou_inexistente_da_422_e_frame_inexistente_da_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    capitulo, e, retrato, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    outro = _retrato(cliente, capitulo, e["objeto"]).json()

    assert _escolher(cliente, outro["id"], primeira["id"]).status_code == 422
    assert _escolher(cliente, retrato["id"], 99999).status_code == 422
    assert _escolher(cliente, 99999, primeira["id"]).status_code == 404
    assert cliente.get(f"/frames/{retrato['id']}").json()["imagem_canonica_id"] is None


def teste_can2_no_retrato_a_canonica_vira_a_ancora_do_estado_e_a_padrao_se_nao_havia(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, e, retrato, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    _escolher(cliente, retrato["id"], primeira["id"])

    assert cliente.get(f"/estados/{e['criatura']['estado_id']}").json()["imagem_ancora_id"] == primeira["id"]
    assert cliente.get(f"/elementos/{e['criatura']['id']}").json()["imagem_ancora_padrao_id"] == primeira["id"]


def teste_can2_a_ancora_padrao_ja_escolhida_nao_e_trocada(cliente: TestClient, usar_provedor_falso) -> None:
    _, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    cliente.patch(f"/elementos/{e['criatura']['id']}", json={"imagem_ancora_padrao_id": primeira["id"]})

    _escolher(cliente, retrato["id"], segunda["id"])

    assert cliente.get(f"/elementos/{e['criatura']['id']}").json()["imagem_ancora_padrao_id"] == primeira["id"]
    assert cliente.get(f"/estados/{e['criatura']['estado_id']}").json()["imagem_ancora_id"] == segunda["id"]


def teste_can3_nulo_tira_a_escolha_e_solta_a_ancora_so_se_era_a_mesma(cliente: TestClient, usar_provedor_falso) -> None:
    _, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _escolher(cliente, retrato["id"], primeira["id"])
    cliente.patch(f"/estados/{e['criatura']['estado_id']}", json={"imagem_ancora_id": segunda["id"]})  # a mão, outra

    resposta = _escolher(cliente, retrato["id"], None)

    assert resposta.json()["imagem_canonica_id"] is None
    assert cliente.get(f"/estados/{e['criatura']['estado_id']}").json()["imagem_ancora_id"] == segunda["id"]  # não era a mesma


def teste_can3_na_cena_so_grava_a_canonica_sem_mexer_em_ancora(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    prompt = _prompt_do_frame(cliente, cena["id"])
    imagem = _importar_imagem(cliente, prompt["id"])

    assert _escolher(cliente, cena["id"], imagem["id"]).status_code == 200

    assert cliente.get(f"/estados/{e['criatura']['estado_id']}").json()["imagem_ancora_id"] is None
    assert cliente.get(f"/elementos/{e['criatura']['id']}").json()["imagem_ancora_padrao_id"] is None


def _artefato_do_frame(cliente: TestClient, capitulo_id: int, frame_id: int) -> dict:
    artefatos = cliente.get(f"/capitulos/{capitulo_id}/artefatos").json()["artefatos"]
    return next(a for a in artefatos if a["frame_id"] == frame_id)


def teste_can4_o_capitulo_mostra_a_canonica_e_sem_escolha_a_mais_recente(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, _, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    assert _artefato_do_frame(cliente, capitulo["id"], retrato["id"])["imagem_id"] == segunda["id"]  # sem escolha

    _escolher(cliente, retrato["id"], primeira["id"])
    assert _artefato_do_frame(cliente, capitulo["id"], retrato["id"])["imagem_id"] == primeira["id"]

    _escolher(cliente, retrato["id"], None)
    assert _artefato_do_frame(cliente, capitulo["id"], retrato["id"])["imagem_id"] == segunda["id"]


def teste_can4_imagem_nova_nao_tira_a_canonica_escolhida(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, _, retrato, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _escolher(cliente, retrato["id"], primeira["id"])
    prompt = _prompt_do_frame(cliente, retrato["id"])

    _importar_imagem(cliente, prompt["id"])  # CAN7: uma terceira, depois da escolha

    assert _artefato_do_frame(cliente, capitulo["id"], retrato["id"])["imagem_id"] == primeira["id"]


def teste_can5_a_ficha_marca_a_canonica_no_retrato_e_usa_na_cena(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    da_cena = _importar_imagem(cliente, _prompt_do_frame(cliente, cena["id"])["id"])
    da_cena_2 = _importar_imagem(cliente, _prompt_do_frame(cliente, cena["id"])["id"])
    _escolher(cliente, retrato["id"], primeira["id"])
    _escolher(cliente, cena["id"], da_cena["id"])

    galeria = _galeria(cliente, e["criatura"]["id"])

    assert {i["id"]: i["canonica"] for i in galeria["imagens"]} == {primeira["id"]: True, segunda["id"]: False}
    assert galeria["cenas"][0]["imagem_id"] == da_cena["id"]  # a canônica, e não a mais recente (da_cena_2)
    assert da_cena_2["id"] > da_cena["id"]


def teste_can5_a_imagem_do_prompt_diz_se_e_a_canonica(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _escolher(cliente, retrato["id"], primeira["id"])

    imagens = cliente.get(f"/prompts/{primeira['prompt_id']}").json()["imagens"]
    assert {i["id"]: i["canonica"] for i in imagens} == {primeira["id"]: True, segunda["id"]: False}
