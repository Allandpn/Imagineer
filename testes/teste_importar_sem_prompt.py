"""Importar uma imagem para um frame que ainda não tem prompt (item 7.5b, PI1 a PI3)."""

from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from testes.teste_rotas_prompts import _frame
from testes.teste_vinculos_do_retrato import MODELO_FALSO, _perfil, _preparar_prompt, _retrato


def _enviar(cliente: TestClient, frame_id: int, nome: str = "minha.png"):
    return cliente.post(f"/frames/{frame_id}/imagens", files={"arquivo": (nome, b"conteudo-fake-da-imagem", "image/png")})


def _frame_sem_prompt(cliente: TestClient, usar_provedor_falso):
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="um retrato"))
    frame = _retrato(cliente, capitulo, e["criatura"], []).json()
    return frame, capitulo


def teste_pi1_sem_prompt_o_servidor_cria_o_prompt_so_da_imagem_e_importa_nele(cliente: TestClient, usar_provedor_falso) -> None:
    frame, _ = _frame_sem_prompt(cliente, usar_provedor_falso)
    assert cliente.get(f"/frames/{frame['id']}/prompts").json() == []

    resposta = _enviar(cliente, frame["id"])

    assert resposta.status_code == 201, resposta.text
    [prompt] = cliente.get(f"/frames/{frame['id']}/prompts").json()
    assert prompt["so_imagem"] is True and prompt["texto"] == "Imagem importada, sem prompt." and prompt["total_de_imagens"] == 1
    assert cliente.get(f"/imagens/{resposta.json()['id']}/arquivo").status_code == 200


def teste_pi1_importar_de_novo_reaproveita_o_mesmo_prompt_so_da_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    frame, _ = _frame_sem_prompt(cliente, usar_provedor_falso)

    _enviar(cliente, frame["id"], "a.png")
    _enviar(cliente, frame["id"], "b.png")

    [prompt] = cliente.get(f"/frames/{frame['id']}/prompts").json()
    assert prompt["total_de_imagens"] == 2


def teste_pi1_com_prompt_de_verdade_a_imagem_vai_para_o_mais_recente_e_nao_cria_outro(cliente: TestClient, usar_provedor_falso) -> None:
    frame, _ = _frame_sem_prompt(cliente, usar_provedor_falso)
    real = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    _enviar(cliente, frame["id"])  # vai para o prompt real

    prompts = cliente.get(f"/frames/{frame['id']}/prompts").json()

    assert [(p["id"], p["so_imagem"], p["total_de_imagens"]) for p in prompts] == [(real["id"], False, 1)]


def teste_pi1_o_prompt_de_verdade_vence_o_so_da_imagem_mesmo_sendo_mais_antigo(cliente: TestClient, usar_provedor_falso) -> None:
    frame, _ = _frame_sem_prompt(cliente, usar_provedor_falso)
    _enviar(cliente, frame["id"])  # cria o prompt só da imagem
    real = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    _enviar(cliente, frame["id"], "outra.png")

    por_id = {p["id"]: p for p in cliente.get(f"/frames/{frame['id']}/prompts").json()}
    assert por_id[real["id"]]["total_de_imagens"] == 1  # a nova foi para o prompt de verdade


def teste_pi1_arquivo_que_nao_e_imagem_e_frame_inexistente(cliente: TestClient, usar_provedor_falso) -> None:
    frame, _ = _frame_sem_prompt(cliente, usar_provedor_falso)

    assert _enviar(cliente, frame["id"], "texto.txt").status_code == 422
    assert _enviar(cliente, 999).status_code == 404
    assert cliente.get(f"/frames/{frame['id']}/prompts").json() == []  # o prompt só da imagem não fica se o envio foi recusado


def teste_pi2_o_prompt_so_da_imagem_nao_gera_imagem_sem_texto_novo(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = usar_provedor_falso(ProvedorFalso(prompt="um retrato"))
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"], []).json()
    _enviar(cliente, frame["id"])
    [so_imagem] = cliente.get(f"/frames/{frame['id']}/prompts").json()

    resposta = cliente.post(f"/prompts/{so_imagem['id']}/gerar-imagem", json={})

    assert resposta.status_code == 422
    assert "só guarda uma imagem importada" in resposta.json()["detail"]
    assert provedor.chamadas_de_imagem == []  # nada foi cobrado


def teste_pi2_com_texto_novo_o_fluxo_de_sempre_cria_um_prompt_de_verdade(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = usar_provedor_falso(ProvedorFalso(prompt="um retrato"))
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"], []).json()
    _enviar(cliente, frame["id"])
    [so_imagem] = cliente.get(f"/frames/{frame['id']}/prompts").json()

    resposta = cliente.post(f"/prompts/{so_imagem['id']}/gerar-imagem", json={"texto": "a red apple"})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["prompt"]["so_imagem"] is False
