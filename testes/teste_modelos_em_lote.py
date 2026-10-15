"""As variantes ``:batch`` do OpenRouter (achado de 15/10/2026): o catálogo as lista por metade do preço, mas o endpoint de conversa as recusa
(``google/gemini-4-argon:batch`` deu 404 em inglês na tela do app). O servidor as tira das listas, recusa ao gravar e explica ao usar."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.ia.provedor import ModeloNaoEscolhido, e_variante_em_lote, mensagem_de_variante_em_lote
from testes.teste_rotas_prompts import _livro


def _modelo(id_: str, saidas: list[str] | None = None) -> dict:
    return {
        "id": id_,
        "name": id_,
        "context_length": 1_000_000,
        "pricing": {"prompt": "0.000001", "completion": "0.000005"},
        "architecture": {"input_modalities": ["text"], "output_modalities": saidas or ["text"]},
        "supported_parameters": ["max_tokens", "temperature"],
    }


def _provedor_com_catalogo(modelos: list[dict]):
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        if pedido.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": modelos})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave-de-teste", cliente=cliente), pedidos


def teste_o_sufixo_e_reconhecido_e_a_mensagem_diz_o_que_fazer() -> None:
    assert e_variante_em_lote("google/gemini-4-argon:batch") and e_variante_em_lote("  OPENAI/GPT-5:BATCH ")
    assert not e_variante_em_lote("google/gemini-4-argon") and not e_variante_em_lote("openai/gpt-oss-120b:free")
    assert not e_variante_em_lote(None) and not e_variante_em_lote("")

    mensagem = mensagem_de_variante_em_lote("google/gemini-4-argon:batch")

    assert "google/gemini-4-argon:batch" in mensagem and "Escolha google/gemini-4-argon," in mensagem and "dobro" in mensagem


def teste_a_lista_de_modelos_de_texto_nao_traz_a_variante_em_lote() -> None:
    from imagineer.ia import catalogo_de_texto

    catalogo_de_texto.limpar_cache_do_catalogo()
    provedor, _ = _provedor_com_catalogo([_modelo("google/gemini-4-argon"), _modelo("google/gemini-4-argon:batch"), _modelo("openai/gpt-4.1-mini")])

    assert [m.id for m in provedor.listar_modelos()] == ["google/gemini-4-argon", "openai/gpt-4.1-mini"]
    catalogo_de_texto.limpar_cache_do_catalogo()


def teste_as_listas_de_imagem_e_de_voz_tambem_tiram_a_variante() -> None:
    provedor, _ = _provedor_com_catalogo([_modelo("a/imagem"), _modelo("a/imagem:batch")])
    assert [m.id for m in provedor.listar_modelos_de_imagem()] == ["a/imagem"]
    assert [m.id for m in provedor.listar_modelos_de_voz()] == ["a/imagem"]  # o catálogo de teste devolve o mesmo para qualquer filtro


def teste_usar_um_modelo_em_lote_na_conversa_explica_e_nem_chama_o_provedor() -> None:
    provedor, pedidos = _provedor_com_catalogo([])

    with pytest.raises(ModeloNaoEscolhido, match="Escolha google/gemini-4-argon,"):
        provedor.traduzir_prompt("a knight", "pt", "google/gemini-4-argon:batch")

    assert pedidos == []  # nenhuma ida ao OpenRouter: o erro já sai em português e sem cobrança


def teste_narrar_e_gerar_imagem_com_modelo_em_lote_tambem_explicam() -> None:
    provedor, pedidos = _provedor_com_catalogo([])

    with pytest.raises(ModeloNaoEscolhido, match="lote"):
        provedor.narrar("texto", "a/voz:batch", None)
    with pytest.raises(ModeloNaoEscolhido, match="lote"):
        provedor.gerar_imagem("um prompt", "a/imagem:batch")

    assert pedidos == []


def teste_gravar_a_configuracao_com_modelo_em_lote_da_422_e_nao_grava(cliente: TestClient) -> None:
    resposta = cliente.put("/configuracao", json={"modelo_extracao": "google/gemini-4-argon:batch"})

    assert resposta.status_code == 422
    assert "Escolha google/gemini-4-argon," in json.dumps(resposta.json(), ensure_ascii=False)
    assert cliente.get("/configuracao").json()["modelo_extracao"] is None  # nada foi gravado


def teste_cada_campo_de_modelo_da_configuracao_recusa_a_variante(cliente: TestClient) -> None:
    for campo in ("modelo_prompt", "modelo_leitura", "modelo_reserva", "modelo_perfil", "modelo_imagem", "modelo_suavizacao", "modelo_traducao", "modelo_video", "modelo_narracao"):
        assert cliente.put("/configuracao", json={campo: "x/y:batch"}).status_code == 422, campo
    assert cliente.put("/configuracao", json={"modelos_de_imagem": ["a/b", "c/d:batch"]}).status_code == 422


def teste_o_modelo_normal_e_o_vazio_continuam_valendo(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"modelo_extracao": "google/gemini-4-argon"}).json()["modelo_extracao"] == "google/gemini-4-argon"
    assert cliente.put("/configuracao", json={"modelo_extracao": ""}).json()["modelo_extracao"] is None
    assert cliente.put("/configuracao", json={"modelo_prompt": "openai/gpt-oss-120b:free"}).status_code == 200  # outro sufixo, não é lote


def teste_a_troca_por_livro_tambem_recusa_a_variante(cliente: TestClient) -> None:
    livro = _livro(cliente)

    recusada = cliente.put(f"/livros/{livro['id']}/modelos", json={"modelo_prompt": "google/gemini-4-argon:batch"})
    aceita = cliente.put(f"/livros/{livro['id']}/modelos", json={"modelo_prompt": "google/gemini-4-argon"})

    assert recusada.status_code == 422
    assert aceita.status_code == 200 and aceita.json()["trocas"] == {"modelo_prompt": "google/gemini-4-argon"}
