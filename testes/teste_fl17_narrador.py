"""O narrador em primeira pessoa (item 4.9, FL17).

Num livro narrado em "eu", o trecho diz "meu buril" e o modelo não sabe quem é o "eu": numa cena real, o prompt atribuiu ao outro personagem o que o
narrador fazia. O livro passa a poder apontar o personagem que narra, e a IA recebe uma linha fixa dizendo isso. Nenhum teste fala com o OpenRouter.
"""

import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, linha_do_narrador
from imagineer.modelos import Livro, Usuario
from imagineer.rotas.livros import _exigir_narrador
from imagineer.servicos.acesso import definir_usuario

from testes.teste_fl_momentos import _cena_no_trecho, _cenario, _epub


def _elemento_do_livro(cliente: TestClient, livro_id: int, nome: str, tipo: str = "PERSONAGEM") -> int:
    resposta = cliente.post(f"/livros/{livro_id}/elementos", json={"tipo": tipo, "nome": nome})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


def teste_fl17_o_livro_comeca_sem_narrador_e_o_detalhe_mostra_o_campo(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)

    assert cliente.get(f"/livros/{livro['id']}").json()["narrador_elemento_id"] is None


def teste_fl17_define_e_tira_o_narrador_pelo_patch(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)
    vis = _elemento_do_livro(cliente, livro["id"], "Vis")

    definido = cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": vis})
    assert definido.status_code == 200 and definido.json()["narrador_elemento_id"] == vis

    tirado = cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": None})
    assert tirado.status_code == 200 and tirado.json()["narrador_elemento_id"] is None


def teste_fl17_ajustar_outro_campo_nao_mexe_no_narrador(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)
    vis = _elemento_do_livro(cliente, livro["id"], "Vis")
    cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": vis})

    resposta = cliente.patch(f"/livros/{livro['id']}", json={"autor": "Alguém"})

    assert resposta.json()["narrador_elemento_id"] == vis


def teste_fl17_o_narrador_tem_de_ser_do_proprio_livro(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)
    outro = cliente.post("/livros", files={"arquivo": ("l.epub", _epub(), "application/epub+zip")}).json()["livro"]
    de_outro_livro = _elemento_do_livro(cliente, outro["id"], "Intruso")

    resposta = cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": de_outro_livro})

    assert resposta.status_code == 404
    assert cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": 99999}).status_code == 404


def teste_fl17_so_um_personagem_pode_narrar(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)
    arena = _elemento_do_livro(cliente, livro["id"], "A arena", tipo="AMBIENTE")

    resposta = cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": arena})

    assert resposta.status_code == 422


def teste_fl17_o_elemento_de_outra_pessoa_nao_existe_para_o_pedido(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)
    vis = _elemento_do_livro(cliente, livro["id"], "Vis")
    maria = Usuario(login="maria@exemplo.com", nome="Maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()

    definir_usuario(sessao_com_tabelas, maria.id)  # o pedido agora é da Maria, dona de nada
    with pytest.raises(HTTPException) as erro:
        _exigir_narrador(sessao_com_tabelas, sessao_com_tabelas.get(Livro, livro["id"]), vis)

    assert erro.value.status_code == 404


def teste_fl17_mandar_o_narrador_para_a_lixeira_nao_derruba_o_livro(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, _, _ = _cenario(cliente, usar_provedor_falso)
    vis = _elemento_do_livro(cliente, livro["id"], "Vis")
    cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": vis})

    # Apagar um elemento só o manda para a lixeira (LT4); o livro segue inteiro. (Apagar de vez: o banco faz SET NULL, conferido na migração em PostgreSQL.)
    assert cliente.delete(f"/elementos/{vis}").status_code in (200, 204)

    assert cliente.get(f"/livros/{livro['id']}").status_code == 200


# --------------------------------------------------------------------------- #
# A linha que a IA recebe
# --------------------------------------------------------------------------- #


def teste_fl17_a_linha_diz_quem_e_o_eu_e_que_a_acao_e_dele() -> None:
    linha = linha_do_narrador("Vis")

    assert "narrado em primeira pessoa por Vis" in linha
    assert "significam sempre Vis" in linha
    assert "o que o narrador faz, é ele quem faz" in linha


def _corpo_das_chamadas(chamar) -> str:
    pedidos = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"presentes": [], "onde": "x"})}, "finish_reason": "stop"}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))
    chamar(provedor)
    return json.dumps(pedidos[0], ensure_ascii=False)


def teste_fl17_o_provedor_real_poe_a_linha_na_montagem_do_prompt_so_com_narrador() -> None:
    com = _corpo_das_chamadas(lambda p: p.montar_prompt("cena", ["Vis: x"], "estilo", "m/x", narrador="Vis"))
    sem = _corpo_das_chamadas(lambda p: p.montar_prompt("cena", ["Vis: x"], "estilo", "m/x"))

    assert "narrado em primeira pessoa por Vis" in com
    assert "primeira pessoa" not in sem.split("ESTILO VISUAL")[-1] and "NARRAÇÃO:" not in sem


def teste_fl17_o_provedor_real_poe_a_linha_na_leitura_do_dossie_so_com_narrador() -> None:
    com = _corpo_das_chamadas(lambda p: p.fundamentar_frame("capítulo", "Cena", None, None, None, None, [], "x/m", narrador="Vis"))
    sem = _corpo_das_chamadas(lambda p: p.fundamentar_frame("capítulo", "Cena", None, None, None, None, [], "x/m"))

    assert "narrado em primeira pessoa por Vis" in com
    assert "NARRAÇÃO:" not in sem


def teste_fl17_a_rota_de_prompt_entrega_o_nome_do_narrador_ao_provedor(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, livro, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    vis = _elemento_do_livro(cliente, livro["id"], "Vis")
    cliente.patch(f"/livros/{livro['id']}", json={"narrador_elemento_id": vis})
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    assert provedor.chamadas_de_prompt[0]["narrador"] == "Vis"
    assert provedor.chamadas_de_fundamentacao[0]["narrador"] == "Vis"


def teste_fl17_sem_narrador_o_provedor_nao_recebe_nada_novo(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert "narrador" not in provedor.chamadas_de_prompt[0]
    assert "narrador" not in provedor.chamadas_de_fundamentacao[0]
