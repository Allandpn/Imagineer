"""Reanálise com orientação do usuário (item 6.7, M1): "falta a cena em que X chega ao porto"."""

import json

import httpx
from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import TipoElemento
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

JON = ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")


def _cenario(cliente: TestClient, usar_provedor_falso):
    provedor = usar_provedor_falso(ProvedorFalso(elementos=[JON]))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    _escolher_modelo_de_extracao(cliente)
    return provedor, livro["capitulos"][0]["id"]


def _orientacoes(provedor: ProvedorFalso) -> list:
    return [c["orientacao"] for c in provedor.chamadas_de_extracao]


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #


def teste_sem_corpo_tudo_continua_como_antes(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)

    primeira = cliente.post(f"/capitulos/{c1}/sugestoes")
    segunda = cliente.post(f"/capitulos/{c1}/sugestoes")  # servida do que está salvo

    assert primeira.status_code == 200 and segunda.status_code == 200
    assert primeira.json()["orientacao"] is None
    assert _orientacoes(provedor) == [None]  # só a primeira chamou a IA


def teste_orientacao_roda_a_ia_mesmo_sem_forcar_e_chega_ao_provedor(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Mandar a orientação é o pedido de reanalisar: ignorá-la em silêncio seria pior."""
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/capitulos/{c1}/sugestoes")

    resposta = cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "falta a cena do porto"})

    assert resposta.status_code == 200, resposta.text
    assert _orientacoes(provedor) == [None, "falta a cena do porto"]  # a IA rodou de novo
    assert resposta.json()["orientacao"] == "falta a cena do porto"


def teste_a_orientacao_fica_guardada_e_vale_nas_reanalises_seguintes(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Só as sugestões não confirmadas são refeitas: sem guardar, o pedido sumiria."""
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "o objeto Y também aparece"})

    cliente.post(f"/capitulos/{c1}/sugestoes?forcar=true")  # reanálise sem digitar nada

    assert _orientacoes(provedor) == ["o objeto Y também aparece", "o objeto Y também aparece"]
    assert cliente.get(f"/capitulos/{c1}/sugestoes").json()["orientacao"] == "o objeto Y também aparece"


def teste_a_leitura_sem_ia_devolve_a_orientacao_vigente(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "procure o porto"})

    lida = cliente.get(f"/capitulos/{c1}/sugestoes")

    assert lida.json()["orientacao"] == "procure o porto"
    assert len(provedor.chamadas_de_extracao) == 1  # o GET nunca chama a IA


def teste_nova_orientacao_substitui_a_anterior(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "primeira"})

    resposta = cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "  segunda  "})

    assert resposta.json()["orientacao"] == "segunda"  # sem os espaços das pontas
    assert _orientacoes(provedor) == ["primeira", "segunda"]


def teste_orientacao_em_branco_apaga_a_guardada_e_roda_a_ia_sem_ela(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "procure o porto"})

    apagada = cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "   "})

    assert apagada.json()["orientacao"] is None
    assert _orientacoes(provedor) == ["procure o porto", None]
    assert cliente.get(f"/capitulos/{c1}/sugestoes").json()["orientacao"] is None


def teste_orientacao_ausente_ou_nula_nao_mexe_na_guardada(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "procure o porto"})

    sem_campo = cliente.post(f"/capitulos/{c1}/sugestoes", json={})
    nula = cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": None})

    assert sem_campo.json()["orientacao"] == nula.json()["orientacao"] == "procure o porto"
    assert len(provedor.chamadas_de_extracao) == 1  # nenhum dos dois reanalisou


def teste_orientacao_longa_demais_e_recusada(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)

    assert cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "x" * 1001}).status_code == 422
    assert len(provedor.chamadas_de_extracao) == 0  # a recusada não gastou IA
    assert cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "x" * 1000}).status_code == 200


def teste_o_que_o_usuario_ja_confirmou_sobrevive_a_reanalise_com_orientacao(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso)
    livro_id = cliente.get(f"/capitulos/{c1}").json()["livro_id"]
    sugestao = cliente.post(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]
    jon = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "estado_inicial": {"capitulo_id": c1, "descricao": "manto"}},
    ).json()
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": jon["id"]})

    depois = cliente.post(f"/capitulos/{c1}/sugestoes", json={"orientacao": "falta alguém"}).json()

    assert [(e["nome"], e["elemento_id"]) for e in depois["elementos"]] == [("Jon", jon["id"])]  # sem duplicar


# --------------------------------------------------------------------------- #
# O provedor real: o que vai para o modelo
# --------------------------------------------------------------------------- #


def _provedor_real(pedidos: list) -> ProvedorOpenRouter:
    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"elementos": [], "cenas": []}'}}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="c", cliente=cliente)


def teste_a_orientacao_vai_para_o_modelo_como_palpite() -> None:
    pedidos: list[dict] = []

    _provedor_real(pedidos).extrair_elementos("o texto", [], "m", orientacao="falta a cena do porto")

    mensagens = pedidos[0]["messages"]
    assert "ORIENTAÇÃO DO USUÁRIO" in mensagens[1]["content"]
    assert "falta a cena do porto" in mensagens[1]["content"]
    assert "palpite" in mensagens[1]["content"]  # o pedido avisa que não é um fato
    assert "PALPITE do usuário" in mensagens[0]["content"]  # e a instrução manda não inventar


def teste_sem_orientacao_o_pedido_nao_muda() -> None:
    pedidos: list[dict] = []

    _provedor_real(pedidos).extrair_elementos("o texto", [], "m")

    assert "ORIENTAÇÃO DO USUÁRIO" not in pedidos[0]["messages"][1]["content"]
