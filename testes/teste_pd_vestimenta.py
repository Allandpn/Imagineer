"""A roupa certa nas cenas e a vestimenta característica do elemento (pendências PD1, PD2 e PD9, 13/10/2026).

O caso real: a *Sedotia* não tinha estado no Capítulo XIX. A cena herdou o estado de um capítulo antigo ("roupa simples", "floresta densa") e a
IA de lá copiou isso em vez de ler a roupa que o capítulo diz com clareza.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import ROTULO_DA_VESTIMENTA_DO_RETRATO
from imagineer.modelos import Elemento, EstadoElemento, Frame
from imagineer.modelos.elemento import TipoElemento
from imagineer.servicos.momentos_do_elemento import (
    ROTULO_DA_ROUPA_HERDADA,
    descricao_herdada,
    descricao_para_a_cena,
    roupa_de_antes,
)

DESCRICAO = (
    "Aparência fixa: mulher de pele escura e cabelo castanho encaracolado\n"
    "Neste instante: roupa simples, com um arco tensionado, corpo inclinado para frente\n"
    "Onde está: floresta densa, com árvores ao redor"
)


def _elemento(vestimenta: str | None = None) -> Elemento:
    return Elemento(livro_id=1, tipo=TipoElemento.PERSONAGEM, nome="Sedotia", vestimenta=vestimenta)


def _estado(capitulo_id: int, descricao: str = DESCRICAO, momentos: list[dict] | None = None, vestimenta: str | None = None) -> EstadoElemento:
    return EstadoElemento(capitulo_id=capitulo_id, descricao=descricao, momentos=momentos, elemento=_elemento(vestimenta))


def _cena(capitulo_id: int) -> Frame:
    return Frame(capitulo_id=capitulo_id)


def teste_estado_de_outro_capitulo_so_leva_o_que_atravessa_capitulos() -> None:
    herdada = descricao_herdada(_estado(capitulo_id=5, momentos=[{"ancora": "x", "roupa": "gibão de couro curtido"}]))

    assert "Aparência fixa: mulher de pele escura" in herdada
    assert f"{ROTULO_DA_ROUPA_HERDADA}: gibão de couro curtido" in herdada
    # O que é daquele momento, de outro lugar, não vai para a cena daqui.
    assert "arco tensionado" not in herdada and "floresta" not in herdada and "Neste instante" not in herdada and "Onde está" not in herdada


def teste_a_vestimenta_caracteristica_do_elemento_vale_mais_que_a_roupa_do_momento_antigo() -> None:
    estado = _estado(capitulo_id=5, momentos=[{"ancora": "x", "roupa": "roupa simples"}], vestimenta="túnica cinza com capuz")

    assert roupa_de_antes(estado) == "túnica cinza com capuz"
    assert "túnica cinza com capuz" in descricao_herdada(estado) and "roupa simples" not in descricao_herdada(estado)


def teste_sem_vestimenta_vale_a_roupa_do_ultimo_momento_do_estado() -> None:
    momentos = [{"ancora": "a", "roupa": "camisola"}, {"ancora": "b", "roupa": None}, {"ancora": "c", "roupa": "armadura de couro"}]

    assert roupa_de_antes(_estado(capitulo_id=5, momentos=momentos)) == "armadura de couro"


def teste_sem_nenhuma_roupa_conhecida_a_linha_nao_aparece() -> None:
    herdada = descricao_herdada(_estado(capitulo_id=5, momentos=None))

    assert herdada == "Aparência fixa: mulher de pele escura e cabelo castanho encaracolado"
    assert ROTULO_DA_ROUPA_HERDADA not in herdada


def teste_estado_do_formato_antigo_sem_rotulos_volta_como_esta() -> None:
    antigo = "mulher de pele escura, com um arco, roupa simples"

    assert descricao_herdada(_estado(capitulo_id=5, descricao=antigo)) == antigo


def teste_a_cena_usa_a_descricao_herdada_so_quando_o_estado_e_de_outro_capitulo() -> None:
    do_outro = _estado(capitulo_id=5)
    do_mesmo = _estado(capitulo_id=9)

    assert descricao_para_a_cena(do_outro, _cena(capitulo_id=9)) == descricao_herdada(do_outro)
    assert descricao_para_a_cena(do_mesmo, _cena(capitulo_id=9)) == DESCRICAO  # o do próprio capítulo continua inteiro


def teste_a_vestimenta_se_grava_e_se_le_pela_api_do_elemento(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    livro = _livro_com_capitulos(cliente, capitulos=1)
    criado = cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Sedotia"}).json()
    assert cliente.get(f"/elementos/{criado['id']}").json()["vestimenta"] is None

    ajustado = cliente.patch(f"/elementos/{criado['id']}", json={"vestimenta": "túnica cinza com capuz"})

    assert ajustado.status_code == 200, ajustado.text
    assert cliente.get(f"/elementos/{criado['id']}").json()["vestimenta"] == "túnica cinza com capuz"
    cliente.patch(f"/elementos/{criado['id']}", json={"vestimenta": None})
    assert cliente.get(f"/elementos/{criado['id']}").json()["vestimenta"] is None


def teste_as_duas_instrucoes_explicam_a_roupa_de_antes_e_que_a_do_capitulo_vale_mais() -> None:
    from imagineer.ia.openrouter import _INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME, _INSTRUCAO_DE_PROMPT

    assert ROTULO_DA_ROUPA_HERDADA.split(" (")[0] in _INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME
    assert "A roupa é a deste capítulo" in _INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME
    assert "roupa simples" in _INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME  # o exemplo do que não escrever
    assert "Roupa de antes" in _INSTRUCAO_DE_PROMPT


# --------------------------------------------------------------------------- #
# PD9: a IA identifica a roupa característica ao gerar o retrato
# --------------------------------------------------------------------------- #


def _retrato_da_sedotia(cliente: TestClient, usar_provedor_falso, provedor: ProvedorFalso, vestimenta: str | None = None) -> tuple[int, int]:
    """Um livro com a Ned Stark (o ajudante dos testes de prompt) e o retrato dele; devolve ``(frame_id, elemento_id)``.

    O nome do personagem não importa aqui: o que se prova é o caminho da roupa."""
    from testes.teste_rotas_prompts import _montar_frame_completo

    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="PERSONAGEM")
    estado = cliente.get(f"/frames/{frame['id']}").json()["elementos"][0]
    elemento_id = estado["elemento_id"]
    if vestimenta:
        cliente.patch(f"/elementos/{elemento_id}", json={"vestimenta": vestimenta})
    return frame["id"], elemento_id


def teste_o_retrato_pede_a_vestimenta_a_ia_uma_vez_grava_e_manda_no_pedido(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(vestimenta="túnica de lã cinza com capuz")
    frame_id, elemento_id = _retrato_da_sedotia(cliente, usar_provedor_falso, provedor)

    resposta = cliente.post(f"/frames/{frame_id}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    assert cliente.get(f"/elementos/{elemento_id}").json()["vestimenta"] == "túnica de lã cinza com capuz"
    (chamada,) = provedor.chamadas_de_vestimenta
    assert chamada["nome"] == "Ned Stark" and chamada["descricoes"] and all(d.startswith("Capítulo ") for d in chamada["descricoes"])
    elementos_do_pedido = provedor.chamadas_de_prompt[0]["elementos"]
    assert any(ROTULO_DA_VESTIMENTA_DO_RETRATO in e and "túnica de lã cinza com capuz" in e for e in elementos_do_pedido)

    cliente.post(f"/frames/{frame_id}/prompts", json={})  # o segundo retrato não pergunta de novo
    assert len(provedor.chamadas_de_vestimenta) == 1


def teste_a_vestimenta_digitada_pela_pessoa_nunca_e_sobrescrita_pela_ia(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(vestimenta="a roupa que a IA achou")
    frame_id, elemento_id = _retrato_da_sedotia(cliente, usar_provedor_falso, provedor, vestimenta="armadura de couro tingida de verde")

    cliente.post(f"/frames/{frame_id}/prompts", json={})

    assert cliente.get(f"/elementos/{elemento_id}").json()["vestimenta"] == "armadura de couro tingida de verde"
    assert provedor.chamadas_de_vestimenta == []  # nem perguntou: a roupa já era da pessoa


def teste_sem_roupa_concreta_o_retrato_segue_como_era(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(vestimenta=None)  # as descrições só dizem uma roupa vaga: nada concreto
    frame_id, elemento_id = _retrato_da_sedotia(cliente, usar_provedor_falso, provedor)

    assert cliente.post(f"/frames/{frame_id}/prompts", json={}).status_code == 201
    assert cliente.get(f"/elementos/{elemento_id}").json()["vestimenta"] is None
    assert not any(ROTULO_DA_VESTIMENTA_DO_RETRATO in e for e in provedor.chamadas_de_prompt[0]["elementos"])


def teste_o_retrato_de_uma_cena_nao_pergunta_a_vestimenta(cliente: TestClient, usar_provedor_falso) -> None:
    from testes.teste_rotas_prompts import _montar_frame_completo

    provedor = ProvedorFalso(vestimenta="qualquer")
    _, cena = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")

    assert cliente.post(f"/frames/{cena['id']}/prompts", json={}).status_code == 201
    assert provedor.chamadas_de_vestimenta == []  # a roupa de uma cena vem do capítulo dela, não do retrato


def teste_a_ia_identifica_a_vestimenta_so_com_as_descricoes_e_aceita_nulo() -> None:
    import httpx

    from imagineer.ia.openrouter import ProvedorOpenRouter

    pedidos: list = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        import json

        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"vestimenta": "túnica cinza"}'}, "finish_reason": "stop"}], "usage": {}})

    cliente = httpx.Client(base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(responder))
    provedor = ProvedorOpenRouter(chave_api="sk-teste", cliente=cliente)

    achada = provedor.identificar_vestimenta("Sedotia", "mulher", ["Capítulo 2: túnica cinza de lã", "Capítulo 5: túnica cinza e capa"], "x/modelo")

    assert achada.vestimenta == "túnica cinza"
    texto = str(pedidos[0]["messages"])
    assert "Sedotia" in texto and "túnica cinza de lã" in texto and "ROUPA CARACTERÍSTICA" in texto
