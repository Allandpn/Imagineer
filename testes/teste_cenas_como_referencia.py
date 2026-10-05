"""Imagens de cenas como referência (item 7.5b, EV15): `cenas` no seletor de elementos e imagens."""

from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from imagineer.servicos.geracao_de_imagem import _frase_de_contexto
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _frame, _importar_imagem
from testes.teste_vinculos_do_retrato import _preparar_prompt


def _cena_com_imagem(cliente: TestClient, capitulo: dict, estado_id: int, titulo: str, imagens: int = 1) -> tuple[dict, list[dict]]:
    frame = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "CENA", "titulo": titulo, "estados_ids": [estado_id]}).json()
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    return frame, [_importar_imagem(cliente, prompt["id"], f"{titulo}{n}.png") for n in range(imagens)]


def _seletor(cliente: TestClient, frame_id: int) -> dict:
    resposta = cliente.get(f"/frames/{frame_id}/elementos-para-vincular")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def teste_o_seletor_traz_as_cenas_do_livro_que_tem_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    estado = e["criatura"]["estado_id"]
    com_imagem, imagens = _cena_com_imagem(cliente, capitulo, estado, "A partida", imagens=2)
    sem_imagem = _frame(cliente, capitulo["id"], [estado], tipo="CENA")  # cena sem imagem não é referência de nada
    cliente.post(f"/frames/{sem_imagem['id']}/prompts", json={})
    atual = _frame(cliente, capitulo["id"], [estado], tipo="CENA")

    cenas = _seletor(cliente, atual["id"])["cenas"]

    assert [c["frame_id"] for c in cenas] == [com_imagem["id"]]
    cena = cenas[0]
    assert cena["titulo"] == "A partida" and cena["capitulo_id"] == capitulo["id"] and cena["ordem_do_capitulo"] >= 1
    assert [i["id"] for i in cena["imagens"]] == sorted((i["id"] for i in imagens), reverse=True)  # as mais novas primeiro
    assert all(i["ancora"] is False for i in cena["imagens"])


def teste_a_cena_em_edicao_entra_tambem_para_refinar_a_propria_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    frame, imagens = _cena_com_imagem(cliente, capitulo, e["criatura"]["estado_id"], "A partida")

    cenas = _seletor(cliente, frame["id"])["cenas"]

    assert [c["frame_id"] for c in cenas] == [frame["id"]]


def teste_imagem_na_lixeira_e_cena_na_lixeira_nao_entram(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    estado = e["criatura"]["estado_id"]
    cena_a, imagens_a = _cena_com_imagem(cliente, capitulo, estado, "Na lixeira")
    cena_b, imagens_b = _cena_com_imagem(cliente, capitulo, estado, "Fica", imagens=2)
    cliente.delete(f"/imagens/{imagens_b[0]['id']}")  # só uma das duas imagens vai para a lixeira
    cliente.delete(f"/frames/{cena_a['id']}")  # a cena inteira
    atual = _frame(cliente, capitulo["id"], [estado], tipo="CENA")

    cenas = _seletor(cliente, atual["id"])["cenas"]

    assert [c["frame_id"] for c in cenas] == [cena_b["id"]]
    assert [i["id"] for i in cenas[0]["imagens"]] == [imagens_b[1]["id"]]


def teste_a_cena_de_um_trecho_ainda_sem_frame_tambem_traz_as_cenas(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    estado = e["criatura"]["estado_id"]
    frame, _ = _cena_com_imagem(cliente, capitulo, estado, "A partida")

    resposta = cliente.get(f"/capitulos/{capitulo['id']}/elementos-para-cena")  # a cena de um trecho, ainda sem frame

    assert [c["frame_id"] for c in resposta.json()["cenas"]] == [frame["id"]]


def teste_a_imagem_de_uma_cena_vale_como_referencia_no_put(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    estado = e["criatura"]["estado_id"]
    _, imagens = _cena_com_imagem(cliente, capitulo, estado, "A partida")
    atual = _frame(cliente, capitulo["id"], [estado], tipo="CENA")

    resposta = cliente.put(f"/frames/{atual['id']}/referencias", json={"imagens_ids": [imagens[0]["id"]]})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["imagens_de_referencia"] == [imagens[0]["id"]]


def teste_a_frase_das_referencias_diz_que_a_imagem_e_da_cena_e_nao_do_personagem() -> None:
    frase = _frase_de_contexto(['the scene "A partida"', "Auri"])

    assert 'image 1 is the scene "A partida"' in frase and "image 2 is Auri" in frase
