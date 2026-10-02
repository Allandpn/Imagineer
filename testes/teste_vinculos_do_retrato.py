"""O retrato com elementos vinculados (item 7.5b, V1 a V10): a decisão do Allan de 02/10/2026."""

from fastapi.testclient import TestClient

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from testes.teste_rotas_prompts import _frame, _livro, _perfil


def _elemento(cliente: TestClient, livro_id: int, capitulo_id: int, nome: str, tipo: str, identidade: str | None = None) -> dict:
    corpo = {"tipo": tipo, "nome": nome, "estado_inicial": {"capitulo_id": capitulo_id, "descricao": f"{nome} está assim."}}
    if identidade:
        corpo["descricao"] = identidade
    resposta = cliente.post(f"/livros/{livro_id}/elementos", json=corpo)
    assert resposta.status_code == 201, resposta.text
    elemento = resposta.json()
    detalhe = cliente.get(f"/elementos/{elemento['id']}").json()
    return {"id": elemento["id"], "estado_id": detalhe["estados"][0]["id"], "nome": nome}


def _cenario(cliente: TestClient):
    """Um livro com uma criatura (sujeito), um objeto, um ambiente e um personagem, cada um com um estado."""
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    elementos = {
        "criatura": _elemento(cliente, livro["id"], capitulo["id"], "Foxen", "CRIATURA", "uma criatura de luz"),
        "objeto": _elemento(cliente, livro["id"], capitulo["id"], "Prato", "OBJETO"),
        "ambiente": _elemento(cliente, livro["id"], capitulo["id"], "Manto", "AMBIENTE"),
        "personagem": _elemento(cliente, livro["id"], capitulo["id"], "Auri", "PERSONAGEM"),
        "outro_objeto": _elemento(cliente, livro["id"], capitulo["id"], "Xícara", "OBJETO"),
    }
    return livro, capitulo, elementos


def _retrato(cliente, capitulo, sujeito, vinculados=None) -> dict:
    corpo = {"tipo": "PERSONAGEM", "estados_ids": [sujeito["estado_id"]]}
    if vinculados is not None:
        corpo["estados_vinculados_ids"] = [v["estado_id"] for v in vinculados]
    return cliente.post(f"/capitulos/{capitulo['id']}/frames", json=corpo)


def teste_v4_cria_o_retrato_ja_com_vinculados(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)

    resposta = _retrato(cliente, capitulo, e["criatura"], [e["objeto"], e["ambiente"]])

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert [x["nome"] for x in corpo["elementos"]] == ["Foxen"]  # o sujeito continua um só (V1)
    assert sorted(x["nome"] for x in corpo["vinculados"]) == ["Manto", "Prato"]
    assert corpo["total_de_elementos"] == 1


def teste_v10_retrato_sem_vinculados_e_igual_ao_de_antes(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)

    corpo = _retrato(cliente, capitulo, e["criatura"]).json()

    assert corpo["vinculados"] == []


def teste_v4_o_put_substitui_a_lista_e_vazia_tira_todos(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)
    frame = _retrato(cliente, capitulo, e["criatura"], [e["objeto"]]).json()

    trocado = cliente.put(f"/frames/{frame['id']}/vinculos", json={"estados_ids": [e["ambiente"]["estado_id"]]})
    assert [x["nome"] for x in trocado.json()["vinculados"]] == ["Manto"]

    limpo = cliente.put(f"/frames/{frame['id']}/vinculos", json={"estados_ids": []})
    assert limpo.status_code == 200 and limpo.json()["vinculados"] == []
    assert cliente.get(f"/frames/{frame['id']}").json()["vinculados"] == []


def teste_v2_o_sujeito_personagem_nao_aceita_vinculados(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)

    resposta = _retrato(cliente, capitulo, e["personagem"], [e["objeto"]])

    assert resposta.status_code == 422
    assert "personagem" in resposta.json()["detail"] and "cena" in resposta.json()["detail"]


def teste_v2_um_personagem_nao_pode_ser_vinculado(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)

    resposta = _retrato(cliente, capitulo, e["criatura"], [e["personagem"]])

    assert resposta.status_code == 422
    assert "Auri" in resposta.json()["detail"] and "individual" in resposta.json()["detail"]


def teste_v3_o_sujeito_nao_pode_ser_vinculado_a_si_mesmo(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)

    resposta = _retrato(cliente, capitulo, e["criatura"], [e["criatura"]])

    assert resposta.status_code == 422
    assert "si mesmo" in resposta.json()["detail"]


def teste_v3_no_maximo_quatro_vinculados(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)
    cinco = [e["objeto"], e["ambiente"], e["outro_objeto"], e["objeto"], e["ambiente"]]

    assert _retrato(cliente, capitulo, e["criatura"], cinco).status_code == 422  # 5 itens: o esquema recusa


def teste_v3_so_o_retrato_aceita_vinculos_a_cena_nao(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"]], tipo="CENA")

    resposta = cliente.put(f"/frames/{cena['id']}/vinculos", json={"estados_ids": [e["ambiente"]["estado_id"]]})

    assert resposta.status_code == 422
    assert "cena" in resposta.json()["detail"]


def teste_v3_estado_de_outro_livro_da_422(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)
    outro_livro = _livro(cliente, titulo="Outro livro", identificador="urn:isbn:2")
    de_fora = _elemento(cliente, outro_livro["id"], outro_livro["capitulos"][0]["id"], "Espada", "OBJETO")

    resposta = _retrato(cliente, capitulo, e["criatura"], [de_fora])

    assert resposta.status_code == 422


def teste_v3_estado_inexistente_da_404(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)

    resposta = cliente.post(
        f"/capitulos/{capitulo['id']}/frames",
        json={"tipo": "PERSONAGEM", "estados_ids": [e["criatura"]["estado_id"]], "estados_vinculados_ids": [99999]},
    )

    assert resposta.status_code == 404


def teste_v4_trocar_o_sujeito_por_um_personagem_revalida_os_vinculos(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)
    frame = _retrato(cliente, capitulo, e["criatura"], [e["objeto"]]).json()

    resposta = cliente.put(f"/frames/{frame['id']}/estados", json={"estados_ids": [e["personagem"]["estado_id"]]})

    assert resposta.status_code == 422
    # Sem vínculos, trocar para um personagem continua valendo (retrato solo).
    cliente.put(f"/frames/{frame['id']}/vinculos", json={"estados_ids": []})
    assert cliente.put(f"/frames/{frame['id']}/estados", json={"estados_ids": [e["personagem"]["estado_id"]]}).status_code == 200


def teste_v1_remover_o_frame_nao_apaga_os_estados_vinculados(cliente: TestClient) -> None:
    _, capitulo, e = _cenario(cliente)
    frame = _retrato(cliente, capitulo, e["criatura"], [e["objeto"]]).json()

    assert cliente.delete(f"/frames/{frame['id']}").status_code == 204

    assert cliente.get(f"/elementos/{e['objeto']['id']}").json()["estados"][0]["id"] == e["objeto"]["estado_id"]


# --------------------------------------------------------------------------- #
# O prompt (V5, V6)
# --------------------------------------------------------------------------- #


def _preparar_prompt(cliente: TestClient, usar_provedor_falso, provedor: ProvedorFalso):
    usar_provedor_falso(provedor)
    livro, capitulo, e = _cenario(cliente)
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    return capitulo, e


def teste_v5_o_prompt_leva_os_vinculados_separados_do_sujeito(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="uma criatura")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"], [e["objeto"], e["ambiente"]]).json()

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    chamada = provedor.chamadas_de_prompt[-1]
    assert chamada["descricao_do_frame"] == ""  # continua um retrato, sem descrição de cena
    assert len(chamada["elementos"]) == 1 and chamada["elementos"][0].startswith("Foxen (uma criatura de luz):")
    assert [linha.split(":")[0] for linha in chamada["elementos_vinculados"]] == ["Prato", "Manto"] or sorted(
        linha.split(":")[0] for linha in chamada["elementos_vinculados"]
    ) == ["Manto", "Prato"]


def teste_v10_sem_vinculados_a_chamada_nao_traz_o_campo(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="uma criatura")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"]).json()

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert "elementos_vinculados" not in provedor.chamadas_de_prompt[-1]


def teste_v6_a_leitura_profunda_tambem_reler_os_vinculados(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="uma criatura")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"], [e["objeto"]]).json()

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    nomes_lidos = sorted(chamada["nome"] for chamada in provedor.chamadas_de_estado)
    assert nomes_lidos == ["Foxen", "Prato"]


def teste_v7_mudar_os_vinculos_nao_refaz_o_prompt_que_ja_existe(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="uma criatura")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"]).json()
    primeiro = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    cliente.put(f"/frames/{frame['id']}/vinculos", json={"estados_ids": [e["objeto"]["estado_id"]]})

    prompts = cliente.get(f"/frames/{frame['id']}/prompts").json()
    assert [p["id"] for p in prompts] == [primeiro["id"]]  # nenhum prompt novo, nenhum refeito
    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    assert provedor.chamadas_de_prompt[-1]["elementos_vinculados"][0].startswith("Prato")  # o novo usa os vínculos atuais


def teste_v5_a_instrucao_e_o_pedido_do_prompt_falam_dos_vinculados() -> None:
    """A instrução diz que o retrato é do sujeito e os vinculados aparecem junto, sem mais ninguém; o pedido os rotula."""
    import json

    import httpx

    from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter

    capturado: dict = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "um prompt"}}]})

    provedor = ProvedorOpenRouter(chave_api="k", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))

    provedor.montar_prompt(
        "", ["Foxen: brilha"], "estilo: x", "modelo/x", elementos_vinculados=["Prato: de prata", "Manto: um quarto de pedra"]
    )

    sistema = " ".join(capturado["messages"][0]["content"].split())
    usuario = capturado["messages"][1]["content"]
    assert "ELEMENTOS VINCULADOS AO SUJEITO" in sistema and "sem acrescentar mais ninguém" in sistema
    assert "ELEMENTOS VINCULADOS AO SUJEITO (aparecem junto dele neste retrato):\n- Prato: de prata\n- Manto: um quarto de pedra" in usuario


def teste_v10_sem_vinculados_o_pedido_nao_menciona_o_bloco() -> None:
    import json

    import httpx

    from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter

    capturado: dict = {}

    def responder(pedido: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "um prompt"}}]})

    provedor = ProvedorOpenRouter(chave_api="k", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))

    provedor.montar_prompt("", ["Foxen: brilha"], "estilo: x", "modelo/x")

    assert "ELEMENTOS VINCULADOS AO SUJEITO (" not in capturado["messages"][1]["content"]
