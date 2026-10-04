"""A lixeira de elementos (item 7.5b, LT4): apagar só marca, o elemento some de tudo, leva os retratos e restaurar traz tudo de volta."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.modelos import Elemento, EstadoElemento, Frame, Imagem, Prompt, SugestaoDeElemento
from testes.teste_galeria_do_elemento import _prompt_do_frame
from testes.teste_posicao_manual import _cenario as _cenario_de_cena
from testes.teste_rotas_prompts import _importar_imagem
from testes.teste_vinculos_do_retrato import _preparar_prompt, _retrato


def _elemento_com_retrato(cliente: TestClient, usar_provedor_falso):
    """A criatura Foxen com um retrato, um prompt e uma imagem. Devolve (capitulo, elemento, frame, prompt, imagem, livro_id)."""
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, ProvedorFalso(prompt="um retrato"))
    elemento = e["criatura"]
    frame = _retrato(cliente, capitulo, elemento, []).json()
    prompt = _prompt_do_frame(cliente, frame["id"])
    imagem = _importar_imagem(cliente, prompt["id"])
    livro_id = cliente.get(f"/elementos/{elemento['id']}").json()["livro_id"]
    return capitulo, elemento, frame, prompt, imagem, livro_id


def _apagar(cliente: TestClient, elemento_id: int) -> None:
    assert cliente.delete(f"/elementos/{elemento_id}").status_code == 204


def _nomes(cliente: TestClient, livro_id: int) -> list[str]:
    return [e["nome"] for e in cliente.get(f"/livros/{livro_id}/elementos").json()]


def teste_lt4_apagar_o_elemento_o_move_para_a_lixeira_e_ele_some_de_tudo(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    capitulo, elemento, frame, prompt, imagem, livro_id = _elemento_com_retrato(cliente, usar_provedor_falso)
    assert "Foxen" in _nomes(cliente, livro_id)

    _apagar(cliente, elemento["id"])

    assert "Foxen" not in _nomes(cliente, livro_id)
    assert cliente.get(f"/elementos/{elemento['id']}").status_code == 404
    assert cliente.patch(f"/estados/{elemento['estado_id']}", json={"descricao": "Y"}).status_code == 404
    assert cliente.get(f"/frames/{frame['id']}").status_code == 404  # o retrato foi junto
    assert cliente.get(f"/capitulos/{capitulo['id']}/frames").json() == []
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Elemento, elemento["id"]).apagado_em is not None  # a linha continua
    assert sessao_com_tabelas.get(EstadoElemento, elemento["estado_id"]) is not None
    assert sessao_com_tabelas.get(Prompt, prompt["id"]) is not None
    assert sessao_com_tabelas.get(Imagem, imagem["id"]) is not None


def teste_lt4_apagar_de_novo_nao_da_erro_e_elemento_inexistente_e_404(cliente: TestClient, usar_provedor_falso) -> None:
    _, elemento, *_ = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    assert cliente.delete(f"/elementos/{elemento['id']}").status_code == 204
    assert cliente.delete("/elementos/999").status_code == 404


def teste_lt4_a_lixeira_lista_o_elemento_com_o_que_ele_leva(cliente: TestClient, usar_provedor_falso) -> None:
    _, elemento, _, _, imagem, livro_id = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    corpo = cliente.get("/lixeira/elementos").json()

    [item] = corpo["elementos"]
    assert (item["id"], item["nome"], item["tipo"], item["livro_id"]) == (elemento["id"], "Foxen", "CRIATURA", livro_id)
    assert (item["total_de_estados"], item["total_de_retratos"], item["total_de_imagens"], item["imagem_id"]) == (1, 1, 1, imagem["id"])
    assert item["tamanho_em_bytes"] > 0 and corpo["total_em_bytes"] == item["tamanho_em_bytes"]


def teste_lt4_restaurar_traz_o_elemento_os_estados_e_o_retrato_com_prompts_e_imagens(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, elemento, frame, prompt, imagem, livro_id = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    resposta = cliente.post(f"/lixeira/elementos/{elemento['id']}/restaurar")

    assert resposta.status_code == 200, resposta.text
    assert "Foxen" in _nomes(cliente, livro_id)
    assert [e["id"] for e in cliente.get(f"/elementos/{elemento['id']}").json()["estados"]] == [elemento["estado_id"]]
    assert [f["id"] for f in cliente.get(f"/capitulos/{capitulo['id']}/frames").json()] == [frame["id"]]
    assert [p["id"] for p in cliente.get(f"/frames/{frame['id']}/prompts").json()] == [prompt["id"]]
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 200
    assert cliente.get("/lixeira/elementos").json()["elementos"] == []


def teste_lt4_o_retrato_que_foi_com_o_elemento_nao_aparece_sozinho_na_lixeira_de_cenas(cliente: TestClient, usar_provedor_falso) -> None:
    _, elemento, frame, *_ = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    assert cliente.get("/lixeira/frames").json()["frames"] == []
    assert cliente.post(f"/lixeira/frames/{frame['id']}/restaurar").status_code == 404  # volta com o elemento
    assert cliente.delete(f"/lixeira/frames/{frame['id']}").status_code == 404


def teste_lt1_restaurar_ou_apagar_de_vez_o_que_nao_esta_na_lixeira_e_404(cliente: TestClient, usar_provedor_falso) -> None:
    _, elemento, *_ = _elemento_com_retrato(cliente, usar_provedor_falso)

    assert cliente.post(f"/lixeira/elementos/{elemento['id']}/restaurar").status_code == 404
    assert cliente.delete(f"/lixeira/elementos/{elemento['id']}").status_code == 404
    assert cliente.get(f"/elementos/{elemento['id']}").status_code == 200


def teste_lt4_o_nome_continua_ocupado_na_lixeira_e_o_409_diz_isso(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, elemento, _, _, _, livro_id = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    resposta = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "CRIATURA", "nome": "Foxen", "estado_inicial": {"capitulo_id": capitulo["id"], "descricao": "de novo"}},
    )

    assert resposta.status_code == 409
    assert "lixeira" in resposta.json()["detail"]


def teste_lt4_a_sugestao_que_o_citava_volta_a_pendente_e_restaurar_a_religa(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, capitulo_id = _cenario_de_cena(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = cliente.get(f"/capitulos/{capitulo_id}").json()["livro_id"]
    arya = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Arya", "estado_inicial": {"capitulo_id": capitulo_id, "descricao": "x"}},
    ).json()
    sugestao = sessao_com_tabelas.query(SugestaoDeElemento).one()
    sugestao.elemento_id = arya["id"]
    sessao_com_tabelas.commit()

    _apagar(cliente, arya["id"])
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(SugestaoDeElemento, sugestao.id).elemento_id is None  # pendente de novo

    cliente.post(f"/lixeira/elementos/{arya['id']}/restaurar")
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(SugestaoDeElemento, sugestao.id).elemento_id == arya["id"]  # religada


def teste_lt4_restaurar_nao_religa_a_sugestao_descartada(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario_de_cena(cliente, usar_provedor_falso, sessao_com_tabelas)
    livro_id = cliente.get(f"/capitulos/{capitulo_id}").json()["livro_id"]
    arya = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Arya", "estado_inicial": {"capitulo_id": capitulo_id, "descricao": "x"}},
    ).json()
    sugestao = sessao_com_tabelas.query(SugestaoDeElemento).one()
    sugestao.elemento_id = arya["id"]
    sessao_com_tabelas.commit()
    _apagar(cliente, arya["id"])
    sessao_com_tabelas.expire_all()
    sessao_com_tabelas.get(SugestaoDeElemento, sugestao.id).descartada = True  # a pessoa a descartou enquanto isso
    sessao_com_tabelas.commit()

    cliente.post(f"/lixeira/elementos/{arya['id']}/restaurar")

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(SugestaoDeElemento, sugestao.id).elemento_id is None


def teste_lt4_apagar_de_vez_remove_elemento_estados_retrato_e_arquivo_da_imagem(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, elemento, frame, prompt, imagem, _ = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    resposta = cliente.delete(f"/lixeira/elementos/{elemento['id']}")

    assert resposta.status_code == 204, resposta.text
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Elemento, elemento["id"]) is None
    assert sessao_com_tabelas.get(EstadoElemento, elemento["estado_id"]) is None
    assert sessao_com_tabelas.get(Frame, frame["id"]) is None
    assert sessao_com_tabelas.get(Prompt, prompt["id"]) is None
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 404


def teste_lt4_esvaziar_remove_so_os_elementos_da_lixeira(cliente: TestClient, usar_provedor_falso) -> None:
    _, elemento, _, _, _, livro_id = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    resposta = cliente.delete("/lixeira/elementos")

    assert resposta.json()["removidas"] == 1
    assert "Foxen" not in _nomes(cliente, livro_id)
    assert "Prato" in _nomes(cliente, livro_id)  # os outros elementos ficam


def teste_lt4_elemento_de_um_livro_que_tambem_esta_na_lixeira_nao_aparece_na_lista_de_elementos(cliente: TestClient, usar_provedor_falso) -> None:
    _, elemento, _, _, _, livro_id = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    cliente.delete(f"/livros/{livro_id}")

    assert cliente.get("/lixeira/elementos").json()["elementos"] == []  # sai com o livro
    cliente.post(f"/lixeira/livros/{livro_id}/restaurar")
    assert len(cliente.get("/lixeira/elementos").json()["elementos"]) == 1  # e volta à lista quando o livro volta


def teste_lt4_criar_frame_com_o_estado_de_um_elemento_da_lixeira_e_404(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, elemento, *_ = _elemento_com_retrato(cliente, usar_provedor_falso)
    _apagar(cliente, elemento["id"])

    resposta = _retrato(cliente, capitulo, elemento, [])

    assert resposta.status_code == 404
