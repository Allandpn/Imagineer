"""A lixeira de cenas e retratos (item 7.5b, LT3): apagar só marca, o frame some de tudo, restaura religando a cena e apagar de vez remove."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.modelos import Frame, Imagem, Prompt, SugestaoDeCena
from testes.teste_galeria_do_elemento import _galeria, _prompt_do_frame
from testes.teste_posicao_manual import _cenario as _cenario_de_cena
from testes.teste_rotas_prompts import _diretorio_de_imagens, _importar_imagem, _frame  # noqa: F401
from testes.teste_vinculos_do_retrato import MODELO_FALSO, _perfil, _preparar_prompt, _retrato


def _frame_com_imagem(cliente: TestClient, usar_provedor_falso):
    """Uma cena com um prompt e uma imagem importada. Devolve (frame, prompt, imagem, capitulo_id, livro_id)."""
    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    livro = _livro_com_capitulos(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": _perfil(cliente)["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    capitulo = livro["capitulos"][0]["id"]
    frame = _frame(cliente, capitulo, [], tipo="CENA")
    prompt = _prompt_do_frame(cliente, frame["id"])
    imagem = _importar_imagem(cliente, prompt["id"])
    return frame, prompt, imagem, capitulo, livro["id"]


def _apagar(cliente: TestClient, frame_id: int) -> None:
    assert cliente.delete(f"/frames/{frame_id}").status_code == 204


def teste_lt3_apagar_o_frame_o_move_para_a_lixeira_e_ele_some_de_tudo(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    frame, prompt, imagem, capitulo, _ = _frame_com_imagem(cliente, usar_provedor_falso)

    _apagar(cliente, frame["id"])

    assert cliente.get(f"/capitulos/{capitulo}/frames").json() == []
    assert cliente.get(f"/frames/{frame['id']}").status_code == 404
    assert cliente.get(f"/frames/{frame['id']}/prompts").status_code == 404
    assert all(a.get("frame_id") != frame["id"] for a in cliente.get(f"/capitulos/{capitulo}/artefatos").json()["artefatos"])
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Frame, frame["id"]).apagado_em is not None  # a linha continua
    assert sessao_com_tabelas.get(Prompt, prompt["id"]) is not None
    assert sessao_com_tabelas.get(Imagem, imagem["id"]) is not None


def teste_lt3_apagar_de_novo_nao_da_erro_e_frame_inexistente_e_404(cliente: TestClient, usar_provedor_falso) -> None:
    frame, *_ = _frame_com_imagem(cliente, usar_provedor_falso)
    _apagar(cliente, frame["id"])

    assert cliente.delete(f"/frames/{frame['id']}").status_code == 204
    assert cliente.delete("/frames/999").status_code == 404


def teste_lt3_a_lixeira_lista_o_frame_com_o_que_ele_leva(cliente: TestClient, usar_provedor_falso) -> None:
    frame, prompt, imagem, capitulo, livro = _frame_com_imagem(cliente, usar_provedor_falso)
    _apagar(cliente, frame["id"])

    corpo = cliente.get("/lixeira/frames").json()

    [item] = corpo["frames"]
    assert (item["id"], item["tipo"], item["capitulo_id"], item["livro_id"]) == (frame["id"], "CENA", capitulo, livro)
    assert (item["total_de_prompts"], item["total_de_imagens"], item["imagem_id"]) == (1, 1, imagem["id"])
    assert item["tamanho_em_bytes"] > 0 and corpo["total_em_bytes"] == item["tamanho_em_bytes"]


def teste_lt3_restaurar_traz_o_frame_com_prompts_e_imagens(cliente: TestClient, usar_provedor_falso) -> None:
    frame, prompt, imagem, capitulo, _ = _frame_com_imagem(cliente, usar_provedor_falso)
    _apagar(cliente, frame["id"])

    resposta = cliente.post(f"/lixeira/frames/{frame['id']}/restaurar")

    assert resposta.status_code == 200, resposta.text
    assert [f["id"] for f in cliente.get(f"/capitulos/{capitulo}/frames").json()] == [frame["id"]]
    assert [p["id"] for p in cliente.get(f"/frames/{frame['id']}/prompts").json()] == [prompt["id"]]
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 200
    assert cliente.get("/lixeira/frames").json()["frames"] == []


def teste_lt1_restaurar_ou_apagar_de_vez_o_que_nao_esta_na_lixeira_e_404(cliente: TestClient, usar_provedor_falso) -> None:
    frame, *_ = _frame_com_imagem(cliente, usar_provedor_falso)

    assert cliente.post(f"/lixeira/frames/{frame['id']}/restaurar").status_code == 404
    assert cliente.delete(f"/lixeira/frames/{frame['id']}").status_code == 404
    assert cliente.get(f"/frames/{frame['id']}").status_code == 200


def teste_lt3_a_cena_sugerida_volta_a_pendente_e_restaurar_a_religa(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario_de_cena(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = sessao_com_tabelas.query(SugestaoDeCena).one()
    frame = _frame(cliente, capitulo_id, [], tipo="CENA")
    cena.frame_id = frame["id"]
    sessao_com_tabelas.commit()

    _apagar(cliente, frame["id"])
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(SugestaoDeCena, cena.id).frame_id is None  # pendente de novo

    cliente.post(f"/lixeira/frames/{frame['id']}/restaurar")
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(SugestaoDeCena, cena.id).frame_id == frame["id"]  # religada


def teste_lt3_restaurar_nao_religa_se_a_cena_ja_ganhou_outro_frame(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario_de_cena(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = sessao_com_tabelas.query(SugestaoDeCena).one()
    antigo = _frame(cliente, capitulo_id, [], tipo="CENA")
    cena.frame_id = antigo["id"]
    sessao_com_tabelas.commit()
    _apagar(cliente, antigo["id"])
    novo = _frame(cliente, capitulo_id, [], tipo="CENA")  # a pessoa confirmou a cena de novo, com outro frame
    sessao_com_tabelas.expire_all()
    sessao_com_tabelas.get(SugestaoDeCena, cena.id).frame_id = novo["id"]
    sessao_com_tabelas.commit()

    cliente.post(f"/lixeira/frames/{antigo['id']}/restaurar")

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(SugestaoDeCena, cena.id).frame_id == novo["id"]  # a ligação nova não foi roubada


def teste_lt3_apagar_de_vez_remove_o_frame_os_prompts_e_o_arquivo_da_imagem(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    frame, prompt, imagem, _, _ = _frame_com_imagem(cliente, usar_provedor_falso)
    _apagar(cliente, frame["id"])

    resposta = cliente.delete(f"/lixeira/frames/{frame['id']}")

    assert resposta.status_code == 204, resposta.text
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Frame, frame["id"]) is None
    assert sessao_com_tabelas.get(Prompt, prompt["id"]) is None
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 404


def teste_lt3_esvaziar_remove_so_os_frames_da_lixeira(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    frame, _, _, capitulo, _ = _frame_com_imagem(cliente, usar_provedor_falso)
    ficar = _frame(cliente, capitulo, [], tipo="CENA")
    _apagar(cliente, frame["id"])

    resposta = cliente.delete("/lixeira/frames")

    assert resposta.json()["removidas"] == 1
    assert [f["id"] for f in cliente.get(f"/capitulos/{capitulo}/frames").json()] == [ficar["id"]]


def teste_lt3_frame_de_um_livro_que_tambem_esta_na_lixeira_nao_aparece_na_lista_de_frames(cliente: TestClient, usar_provedor_falso) -> None:
    frame, _, _, _, livro = _frame_com_imagem(cliente, usar_provedor_falso)
    _apagar(cliente, frame["id"])

    cliente.delete(f"/livros/{livro}")

    assert cliente.get("/lixeira/frames").json()["frames"] == []  # sai com o livro
    cliente.post(f"/lixeira/livros/{livro}/restaurar")
    assert len(cliente.get("/lixeira/frames").json()["frames"]) == 1  # e volta à lista quando o livro volta


def teste_lt3_o_retrato_apagado_some_da_galeria_do_elemento_e_volta_ao_restaurar(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="um retrato"))
    frame = _retrato(cliente, capitulo, e["criatura"], []).json()
    prompt = _prompt_do_frame(cliente, frame["id"])
    _importar_imagem(cliente, prompt["id"])
    assert len(_galeria(cliente, e["criatura"]["id"])["imagens"]) == 1

    _apagar(cliente, frame["id"])
    assert _galeria(cliente, e["criatura"]["id"])["imagens"] == []

    cliente.post(f"/lixeira/frames/{frame['id']}/restaurar")
    assert len(_galeria(cliente, e["criatura"]["id"])["imagens"]) == 1
