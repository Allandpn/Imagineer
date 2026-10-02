"""A ficha do elemento com as imagens e as cenas dele (item 7.5b, FI1 a FI9)."""

from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from testes.teste_rotas_prompts import _frame, _importar_imagem
from testes.teste_vinculos_do_retrato import _cenario, _preparar_prompt, _retrato


def _montar(cliente: TestClient, usar_provedor_falso):
    """Um livro com criatura, objeto, ambiente e personagem, e o provedor falso pronto para montar prompts."""
    provedor = ProvedorFalso(prompt="um prompt")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    return capitulo, e


def _prompt_do_frame(cliente: TestClient, frame_id: int) -> dict:
    resposta = cliente.post(f"/frames/{frame_id}/prompts", json={})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _galeria(cliente: TestClient, elemento_id: int) -> dict:
    resposta = cliente.get(f"/elementos/{elemento_id}/galeria")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def teste_fi1_elemento_sem_imagem_nem_cena_vem_com_as_listas_vazias(cliente: TestClient, usar_provedor_falso) -> None:
    _, e = _montar(cliente, usar_provedor_falso)

    assert _galeria(cliente, e["criatura"]["id"]) == {"imagens": [], "cenas": []}


def teste_fi1_elemento_inexistente_da_404(cliente: TestClient) -> None:
    assert cliente.get("/elementos/99999/galeria").status_code == 404


def teste_fi2_as_imagens_do_retrato_vem_das_mais_novas_para_as_mais_antigas_com_o_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"]).json()
    prompt = _prompt_do_frame(cliente, retrato["id"])
    primeira = _importar_imagem(cliente, prompt["id"])
    segunda = _importar_imagem(cliente, prompt["id"])

    imagens = _galeria(cliente, e["criatura"]["id"])["imagens"]

    assert [i["id"] for i in imagens] == [segunda["id"], primeira["id"]]
    assert imagens[0]["frame_id"] == retrato["id"] and imagens[0]["prompt_id"] == prompt["id"]
    assert imagens[0]["capitulo_id"] == capitulo["id"] and imagens[0]["ordem_do_capitulo"] >= 1
    assert imagens[0]["origem"] == "IMPORTADA" and imagens[0]["ancora"] is False
    assert imagens[0]["sem_filtro_de_seguranca"] is False


def teste_fi2_so_as_imagens_de_retrato_do_proprio_elemento_entram(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    do_objeto = _prompt_do_frame(cliente, _retrato(cliente, capitulo, e["objeto"]).json()["id"])
    _importar_imagem(cliente, do_objeto["id"])
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"]], tipo="CENA")
    da_cena = _prompt_do_frame(cliente, cena["id"])
    _importar_imagem(cliente, da_cena["id"])

    # A imagem do retrato do objeto e a da cena não são imagens do retrato da criatura.
    assert _galeria(cliente, e["criatura"]["id"])["imagens"] == []
    assert len(_galeria(cliente, e["objeto"]["id"])["imagens"]) == 1


def teste_fi9_o_retrato_em_que_ele_e_vinculado_nao_entra(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"], [e["objeto"]]).json()
    _importar_imagem(cliente, _prompt_do_frame(cliente, retrato["id"])["id"])

    assert len(_galeria(cliente, e["criatura"]["id"])["imagens"]) == 1
    assert _galeria(cliente, e["objeto"]["id"])["imagens"] == []  # vinculado: não é o retrato dele (FI9)


def teste_fi2_a_ancora_padrao_vem_marcada(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    prompt = _prompt_do_frame(cliente, _retrato(cliente, capitulo, e["criatura"]).json()["id"])
    primeira = _importar_imagem(cliente, prompt["id"])
    segunda = _importar_imagem(cliente, prompt["id"])
    cliente.patch(f"/elementos/{e['criatura']['id']}", json={"imagem_ancora_padrao_id": primeira["id"]})

    imagens = _galeria(cliente, e["criatura"]["id"])["imagens"]

    assert {i["id"]: i["ancora"] for i in imagens} == {segunda["id"]: False, primeira["id"]: True}


def teste_fi3_as_cenas_em_que_ele_participa_com_os_outros_participantes_e_a_imagem_mais_recente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"], e["ambiente"]["estado_id"]], tipo="CENA")
    prompt = _prompt_do_frame(cliente, cena["id"])
    _importar_imagem(cliente, prompt["id"])
    ultima = _importar_imagem(cliente, prompt["id"])

    [achada] = _galeria(cliente, e["criatura"]["id"])["cenas"]

    assert achada["frame_id"] == cena["id"] and achada["titulo"] == "No pátio"
    assert achada["participantes"] == ["Manto", "Prato"]  # os OUTROS, em ordem alfabética
    assert achada["total_de_imagens"] == 2 and achada["imagem_id"] == ultima["id"]
    assert achada["capitulo_id"] == capitulo["id"]


def teste_fi3_cena_sem_imagem_tambem_aparece(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")

    [achada] = _galeria(cliente, e["criatura"]["id"])["cenas"]

    assert achada["imagem_id"] is None and achada["imagem_orientacao"] is None and achada["total_de_imagens"] == 0
    assert achada["participantes"] == []


def teste_fi3_so_as_cenas_em_que_ele_participa(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    _frame(cliente, capitulo["id"], [e["objeto"]["estado_id"]], tipo="CENA")
    propria = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")

    assert [c["frame_id"] for c in _galeria(cliente, e["criatura"]["id"])["cenas"]] == [propria["id"]]


def teste_fi3_as_cenas_vem_na_ordem_narrativa_e_cada_uma_uma_vez_so(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    primeira = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    segunda = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"]], tipo="CENA")

    cenas = _galeria(cliente, e["criatura"]["id"])["cenas"]

    assert [c["frame_id"] for c in cenas] == [primeira["id"], segunda["id"]]


# --------------------------------------------------------------------------- #
# A capa na lista (FI4)
# --------------------------------------------------------------------------- #


def _capa_de(cliente: TestClient, elementos: dict, nome: str) -> int | None:
    livro_id = cliente.get(f"/elementos/{elementos['criatura']['id']}").json()["livro_id"]
    lista = cliente.get(f"/livros/{livro_id}/elementos").json()
    return next(x for x in lista if x["nome"] == nome)["imagem_de_capa_id"]


def teste_fi4_sem_imagem_a_capa_e_nula(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)

    assert _capa_de(cliente, e, "Foxen") is None


def teste_fi4_a_capa_e_a_imagem_mais_recente_do_retrato(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    prompt = _prompt_do_frame(cliente, _retrato(cliente, capitulo, e["criatura"]).json()["id"])
    _importar_imagem(cliente, prompt["id"])
    segunda = _importar_imagem(cliente, prompt["id"])

    assert _capa_de(cliente, e, "Foxen") == segunda["id"]
    assert _capa_de(cliente, e, "Prato") is None  # a de outro elemento não vaza


def teste_fi4_a_ancora_padrao_vence_a_mais_recente(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    prompt = _prompt_do_frame(cliente, _retrato(cliente, capitulo, e["criatura"]).json()["id"])
    primeira = _importar_imagem(cliente, prompt["id"])
    _importar_imagem(cliente, prompt["id"])
    cliente.patch(f"/elementos/{e['criatura']['id']}", json={"imagem_ancora_padrao_id": primeira["id"]})

    assert _capa_de(cliente, e, "Foxen") == primeira["id"]


def teste_fi4_imagem_de_cena_nao_vira_capa(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"]], tipo="CENA")
    _importar_imagem(cliente, _prompt_do_frame(cliente, cena["id"])["id"])

    assert _capa_de(cliente, e, "Foxen") is None
