"""O seletor único de vínculo (item 7.5b, VM1 a VM3): `GET /livros/{id}/elementos-por-capitulo` e a canônica vinda de outro capítulo."""

from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from testes.teste_galeria_do_elemento import _prompt_do_frame
from testes.teste_rotas_prompts import _diretorio_de_imagens, _importar_imagem  # noqa: F401
from testes.teste_rotas_sugestoes import _livro_com_capitulos
from testes.teste_vinculos_do_retrato import MODELO_FALSO, _elemento, _perfil, _retrato


def _novo_estado(cliente: TestClient, elemento_id: int, capitulo_id: int) -> int:
    resposta = cliente.post(f"/elementos/{elemento_id}/estados", json={"capitulo_id": capitulo_id, "descricao": "mudou"})
    assert resposta.status_code == 201, resposta.text
    detalhe = cliente.get(f"/elementos/{elemento_id}").json()
    return next(e["id"] for e in detalhe["estados"] if e["capitulo_id"] == capitulo_id)


def _por_capitulo(cliente: TestClient, livro_id: int) -> list[dict]:
    resposta = cliente.get(f"/livros/{livro_id}/elementos-por-capitulo")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["capitulos"]


def _cenario(cliente: TestClient, usar_provedor_falso):
    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": _perfil(cliente)["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    foxen = _elemento(cliente, livro["id"], primeiro["id"], "Foxen", "CRIATURA")
    prato = _elemento(cliente, livro["id"], primeiro["id"], "Prato", "OBJETO")
    return livro, primeiro, segundo, foxen, prato


def teste_vm2_elemento_so_com_estado_aparece_sem_imagem_e_capitulo_vazio_nao_aparece(cliente: TestClient, usar_provedor_falso) -> None:
    livro, primeiro, _, foxen, prato = _cenario(cliente, usar_provedor_falso)

    capitulos = _por_capitulo(cliente, livro["id"])

    assert [c["capitulo_id"] for c in capitulos] == [primeiro["id"]]  # o segundo não tem elemento nenhum
    assert [(e["nome"], e["imagens"]) for e in capitulos[0]["elementos"]] == [("Foxen", []), ("Prato", [])]


def teste_vm2_as_imagens_vem_no_capitulo_do_retrato_e_o_elemento_aparece_em_cada_capitulo_em_que_tem_estado(
    cliente: TestClient, usar_provedor_falso
) -> None:
    livro, primeiro, segundo, foxen, _ = _cenario(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, primeiro, foxen).json()
    imagem = _importar_imagem(cliente, _prompt_do_frame(cliente, retrato["id"])["id"])
    _novo_estado(cliente, foxen["id"], segundo["id"])

    capitulos = {c["capitulo_id"]: c for c in _por_capitulo(cliente, livro["id"])}

    do_primeiro = next(e for e in capitulos[primeiro["id"]]["elementos"] if e["nome"] == "Foxen")
    do_segundo = next(e for e in capitulos[segundo["id"]]["elementos"] if e["nome"] == "Foxen")
    assert [i["id"] for i in do_primeiro["imagens"]] == [imagem["id"]]
    assert do_segundo["imagens"] == []  # a imagem é do capítulo 1, não do 2


def teste_vm2_imagem_na_lixeira_nao_aparece(cliente: TestClient, usar_provedor_falso) -> None:
    livro, primeiro, _, foxen, _ = _cenario(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, primeiro, foxen).json()
    imagem = _importar_imagem(cliente, _prompt_do_frame(cliente, retrato["id"])["id"])
    cliente.delete(f"/imagens/{imagem['id']}")

    [capitulo] = _por_capitulo(cliente, livro["id"])

    assert next(e for e in capitulo["elementos"] if e["nome"] == "Foxen")["imagens"] == []


def teste_vm2_livro_inexistente_da_404(cliente: TestClient) -> None:
    assert cliente.get("/livros/99999/elementos-por-capitulo").status_code == 404


def teste_vm3_o_retrato_aceita_como_canonica_a_imagem_de_outro_retrato_do_mesmo_elemento(
    cliente: TestClient, usar_provedor_falso
) -> None:
    livro, primeiro, segundo, foxen, _ = _cenario(cliente, usar_provedor_falso)
    antigo = _retrato(cliente, primeiro, foxen).json()
    imagem = _importar_imagem(cliente, _prompt_do_frame(cliente, antigo["id"])["id"])
    estado_novo = _novo_estado(cliente, foxen["id"], segundo["id"])
    novo = cliente.post(f"/capitulos/{segundo['id']}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [estado_novo]}).json()

    resposta = cliente.put(f"/frames/{novo['id']}/imagem-canonica", json={"imagem_id": imagem["id"]})

    assert resposta.status_code == 200, resposta.text
    artefatos = cliente.get(f"/capitulos/{segundo['id']}/artefatos").json()["artefatos"]
    assert next(a for a in artefatos if a["frame_id"] == novo["id"])["imagem_id"] == imagem["id"]  # o capítulo 2 mostra a do 1


def teste_vm3_imagem_de_outro_elemento_continua_recusada(cliente: TestClient, usar_provedor_falso) -> None:
    livro, primeiro, segundo, foxen, prato = _cenario(cliente, usar_provedor_falso)
    do_prato = _retrato(cliente, primeiro, prato).json()
    imagem_do_prato = _importar_imagem(cliente, _prompt_do_frame(cliente, do_prato["id"])["id"])
    do_foxen = _retrato(cliente, primeiro, foxen).json()

    resposta = cliente.put(f"/frames/{do_foxen['id']}/imagem-canonica", json={"imagem_id": imagem_do_prato["id"]})

    assert resposta.status_code == 422
