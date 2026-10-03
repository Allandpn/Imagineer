"""A lixeira de imagens (item 7.5b, LX1 a LX10)."""

from fastapi.testclient import TestClient

from testes.teste_galeria_do_elemento import _galeria, _montar, _prompt_do_frame
from testes.teste_imagem_canonica import _artefato_do_frame, _escolher, _retrato_com_duas_imagens
from testes.teste_rotas_prompts import _diretorio_de_imagens, _frame, _importar_imagem  # noqa: F401
from testes.teste_vinculos_do_retrato import _retrato


def _lixeira(cliente: TestClient) -> dict:
    resposta = cliente.get("/lixeira/imagens")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _apagar(cliente: TestClient, imagem_id: int) -> None:
    assert cliente.delete(f"/imagens/{imagem_id}").status_code == 204


def teste_lx5_lixeira_vazia(cliente: TestClient) -> None:
    assert _lixeira(cliente) == {"imagens": [], "total_em_bytes": 0}


def teste_lx4_apagar_move_para_a_lixeira_com_o_contexto(cliente: TestClient, usar_provedor_falso) -> None:
    _, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    _apagar(cliente, primeira["id"])

    lixeira = _lixeira(cliente)
    [item] = lixeira["imagens"]
    assert item["id"] == primeira["id"] and item["frame_id"] == retrato["id"] and item["prompt_id"] == primeira["prompt_id"]
    assert item["frame_tipo"] == "PERSONAGEM" and item["nome_do_elemento"] == e["criatura"]["nome"]
    assert item["titulo_do_livro"] and item["ordem_do_capitulo"] >= 1 and item["origem"] == "IMPORTADA"
    assert item["apagada_em"]
    assert lixeira["total_em_bytes"] > 0
    assert segunda["id"] != item["id"]


def teste_lx4_a_imagem_some_do_prompt_da_galeria_e_do_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    _apagar(cliente, segunda["id"])  # a mais recente

    assert [i["id"] for i in cliente.get(f"/prompts/{primeira['prompt_id']}").json()["imagens"]] == [primeira["id"]]
    assert [i["id"] for i in _galeria(cliente, e["criatura"]["id"])["imagens"]] == [primeira["id"]]
    assert _artefato_do_frame(cliente, capitulo["id"], retrato["id"])["imagem_id"] == primeira["id"]
    resumo = cliente.get(f"/frames/{retrato['id']}/prompts").json()
    assert resumo[0]["total_de_imagens"] == 1


def teste_lx4_apagar_a_unica_imagem_volta_o_artefato_para_prompt_pronto(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"]).json()
    imagem = _importar_imagem(cliente, _prompt_do_frame(cliente, retrato["id"])["id"])

    _apagar(cliente, imagem["id"])

    assert _artefato_do_frame(cliente, capitulo["id"], retrato["id"])["situacao"] == "PROMPT_PRONTO"


def teste_lx4_apagar_solta_a_canonica_e_as_ancoras_que_apontavam_para_ela(cliente: TestClient, usar_provedor_falso) -> None:
    _, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _escolher(cliente, retrato["id"], primeira["id"])  # também vira a âncora do estado e a padrão do elemento

    _apagar(cliente, primeira["id"])

    assert cliente.get(f"/frames/{retrato['id']}").json()["imagem_canonica_id"] is None
    assert cliente.get(f"/estados/{e['criatura']['estado_id']}").json()["imagem_ancora_id"] is None
    assert cliente.get(f"/elementos/{e['criatura']['id']}").json()["imagem_ancora_padrao_id"] is None


def teste_lx4_apagar_outra_imagem_nao_mexe_na_canonica(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _escolher(cliente, retrato["id"], primeira["id"])

    _apagar(cliente, segunda["id"])

    assert cliente.get(f"/frames/{retrato['id']}").json()["imagem_canonica_id"] == primeira["id"]


def teste_lx4_apagar_duas_vezes_nao_da_erro_e_nao_duplica(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    _apagar(cliente, primeira["id"])
    _apagar(cliente, primeira["id"])

    assert len(_lixeira(cliente)["imagens"]) == 1
    assert cliente.delete("/imagens/99999").status_code == 404


def teste_lx4_imagem_da_lixeira_nao_vira_canonica_nem_ancora(cliente: TestClient, usar_provedor_falso) -> None:
    _, e, retrato, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _apagar(cliente, primeira["id"])

    assert _escolher(cliente, retrato["id"], primeira["id"]).status_code == 422
    resposta = cliente.patch(f"/elementos/{e['criatura']['id']}", json={"imagem_ancora_padrao_id": primeira["id"]})
    assert resposta.status_code == 422


def teste_lx4_o_seletor_de_referencias_nao_oferece_a_da_lixeira(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    _apagar(cliente, primeira["id"])

    candidatas = cliente.get(f"/frames/{cena['id']}/referencias-candidatas").json()

    ids = [i["id"] for el in candidatas["elementos"] for i in el["imagens"]]
    assert primeira["id"] not in ids and segunda["id"] in ids


def teste_lx5_restaurar_devolve_a_imagem_mas_nao_a_canonica(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, retrato, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _escolher(cliente, retrato["id"], primeira["id"])
    _apagar(cliente, primeira["id"])

    resposta = cliente.post(f"/lixeira/imagens/{primeira['id']}/restaurar")

    assert resposta.status_code == 200 and resposta.json()["id"] == primeira["id"]
    assert _lixeira(cliente)["imagens"] == []
    ids = [i["id"] for i in cliente.get(f"/prompts/{primeira['prompt_id']}").json()["imagens"]]
    assert ids == [primeira["id"], segunda["id"]]
    assert cliente.get(f"/frames/{retrato['id']}").json()["imagem_canonica_id"] is None  # LX4: não refaz


def teste_lx5_restaurar_ou_apagar_de_vez_o_que_nao_esta_na_lixeira_da_404(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    assert cliente.post(f"/lixeira/imagens/{primeira['id']}/restaurar").status_code == 404
    assert cliente.delete(f"/lixeira/imagens/{primeira['id']}").status_code == 404
    assert cliente.post("/lixeira/imagens/99999/restaurar").status_code == 404
    assert cliente.get(f"/imagens/{primeira['id']}/arquivo").status_code == 200  # a ativa continua intacta


def teste_lx5_apagar_de_vez_remove_a_linha_e_o_arquivo(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, _, _, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _apagar(cliente, primeira["id"])
    assert len(list(_diretorio_de_imagens.rglob("*.png"))) == 2

    assert cliente.delete(f"/lixeira/imagens/{primeira['id']}").status_code == 204

    assert _lixeira(cliente)["imagens"] == []
    assert cliente.get(f"/imagens/{primeira['id']}/arquivo").status_code == 404
    assert cliente.get(f"/imagens/{segunda['id']}/arquivo").status_code == 200
    assert len(list(_diretorio_de_imagens.rglob("*.png"))) == 1


def teste_lx5_esvaziar_apaga_so_o_que_esta_na_lixeira(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, _, _, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _apagar(cliente, primeira["id"])

    resposta = cliente.delete("/lixeira/imagens")

    assert resposta.status_code == 200
    assert resposta.json()["removidas"] == 1 and resposta.json()["liberados_em_bytes"] > 0
    assert cliente.get(f"/imagens/{segunda['id']}/arquivo").status_code == 200  # a ativa não é tocada
    assert len(list(_diretorio_de_imagens.rglob("*.png"))) == 1
    assert cliente.delete("/lixeira/imagens").json() == {"removidas": 0, "liberados_em_bytes": 0}


def teste_lx5_a_lixeira_lista_da_mais_recente_para_a_mais_antiga(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)

    _apagar(cliente, primeira["id"])
    _apagar(cliente, segunda["id"])

    assert [i["id"] for i in _lixeira(cliente)["imagens"]] == [segunda["id"], primeira["id"]]


def teste_lx4_a_imagem_da_lixeira_nao_entra_no_manifesto_de_midias_do_livro(cliente: TestClient, usar_provedor_falso) -> None:
    _, e, _, primeira, segunda = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _apagar(cliente, primeira["id"])

    livro_id = cliente.get(f"/elementos/{e['criatura']['id']}").json()["livro_id"]
    resposta = cliente.get(f"/livros/{livro_id}/midias")

    assert resposta.status_code == 200, resposta.text
    ids = [m["imagem_id"] for m in resposta.json()["imagens"]]
    assert primeira["id"] not in ids and segunda["id"] in ids


def teste_lx7_apagar_o_prompt_leva_tambem_as_imagens_da_lixeira(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, _, _, primeira, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    _apagar(cliente, primeira["id"])

    assert cliente.delete(f"/prompts/{primeira['prompt_id']}").status_code == 204

    assert _lixeira(cliente)["imagens"] == []
    assert list(_diretorio_de_imagens.rglob("*.png")) == []
