"""Os momentos do elemento dentro do capítulo (item 4.9, FL3, FL4 e FL7; etapa 2).

O estado de um elemento guardava um instante só (o primeiro do capítulo): uma cena do fim recebia a roupa do começo. Agora a leitura devolve uma linha do
tempo; o servidor acha a posição de cada momento no texto e, ao montar uma cena, escolhe o momento que cobre o trecho dela. Nenhum teste fala com o OpenRouter.
"""

import io
import json
from types import SimpleNamespace

import httpx
import pytest
from ebooklib import epub
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, _interpretar_momentos
from imagineer.ia.provedor import MomentoSugerido
from imagineer.modelos import EstadoElemento, TipoElemento
from imagineer.servicos.momentos_do_elemento import (
    descricao_para_a_cena,
    indice_do_momento,
    momentos_com_posicao,
    posicao_do_frame,
)

PARAGRAFOS = [
    "Maren acordou antes do sol, na cabana de pedra à beira do rio, vestindo a camisola de linho cinza que a avó lhe deixara, e ficou ouvindo a água correr.",
    "Mais tarde, no vilarejo, ela trocou a camisola por um manto verde de lã, pois ia ao mercado vender o peixe que pescara na véspera, entre as redes.",
    "Ao anoitecer, na volta, uma pedra lhe cortou a testa e o sangue escorreu até o queixo, e ela chegou em casa arfando, com o manto rasgado.",
]
TEXTO = "\n\n".join(PARAGRAFOS)

ESTADO = "Aparência fixa: mulher alta, cabelos negros\nNeste instante: camisola de linho cinza\nOnde está: cabana de pedra"

MOMENTOS = [
    MomentoSugerido(ancora="Maren acordou antes do sol", roupa="camisola de linho cinza", expressao_e_postura="olhar sonolento", lugar="cabana de pedra"),
    MomentoSugerido(ancora="trocou a camisola por um manto verde", roupa="manto verde de lã", humor="animada", lugar="vilarejo"),
    MomentoSugerido(ancora="uma pedra lhe cortou a testa", roupa="manto verde de lã, rasgado", estado_fisico="corte na testa, sangue até o queixo"),
]


def _epub() -> bytes:
    livro = epub.EpubBook()
    livro.set_identifier("urn:isbn:momentos")
    livro.set_title("Livro dos Momentos")
    livro.set_language("pt-BR")
    item = epub.EpubHtml(title="Capítulo 1", file_name="c1.xhtml", lang="pt-BR")
    item.content = "".join(f"<p>{paragrafo}</p>" for paragrafo in PARAGRAFOS)
    livro.add_item(item)
    livro.toc = (item,)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", item]
    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# A instrução e o interpretador (FL3)
# --------------------------------------------------------------------------- #


def _instrucao_de_estado() -> str:
    pedidos = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"aparencia_fixa": "a", "instante": "b", "ambiente": None})}}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))
    provedor.sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Maren", None, None, "x/m")
    return pedidos[0]["messages"][0]["content"]


def teste_fl3_a_instrucao_pede_quatro_partes_e_a_linha_do_tempo() -> None:
    instrucao = _instrucao_de_estado()

    assert "Você devolve QUATRO partes" in instrucao
    assert '4. "momentos": a LINHA DO TEMPO do elemento neste capítulo, em ORDEM DO TEXTO' in instrucao
    assert '"ancora" (uma citação LITERAL de até uns 80' in instrucao
    assert '"estado_fisico" (ferimentos, sujeira, cansaço)' in instrucao


def teste_fl3_a_instrucao_diz_quando_nasce_um_momento_novo_e_que_o_primeiro_e_o_instante() -> None:
    instrucao = _instrucao_de_estado()

    assert "Um NOVO momento só existe quando ALGO MUDOU" in instrucao
    assert "Um capítulo em que nada muda tem UM momento só" in instrucao
    assert 'O primeiro momento é o mesmo do "instante"' in instrucao
    assert "Nunca duas versões contraditórias no mesmo momento" in instrucao


def teste_fl3_os_detalhes_que_completam_um_momento_podem_vir_de_qualquer_ponto_do_capitulo() -> None:
    instrucao = _instrucao_de_estado()

    assert "podem vir de QUALQUER ponto do capítulo, inclusive DEPOIS de onde ele começa" in instrucao
    assert 'a "ancora" marca só onde o momento COMEÇA' in instrucao


def teste_fl3_o_formato_pedido_leva_os_momentos() -> None:
    instrucao = _instrucao_de_estado()

    assert '"momentos": [' in instrucao and '"ancora": "citação literal de onde o momento começa, ou null"' in instrucao
    assert "nas partes acima, com um só momento" in instrucao


def teste_fl3_o_interpretador_le_os_momentos_em_ordem() -> None:
    resposta = json.dumps(
        {
            "aparencia_fixa": "a", "instante": "b", "ambiente": None,
            "momentos": [
                {"ancora": "Maren acordou", "roupa": "camisola", "estado_fisico": None, "expressao_e_postura": "sonolenta", "humor": None, "lugar": "cabana"},
                {"ancora": "trocou a camisola", "roupa": "manto", "estado_fisico": "ferida", "expressao_e_postura": None, "humor": "animada", "lugar": None},
            ],
        }
    )

    momentos = _interpretar_momentos(resposta)

    assert [m.ancora for m in momentos] == ["Maren acordou", "trocou a camisola"]
    assert momentos[0] == MomentoSugerido(ancora="Maren acordou", roupa="camisola", expressao_e_postura="sonolenta", lugar="cabana")
    assert momentos[1].estado_fisico == "ferida" and momentos[1].humor == "animada" and momentos[1].lugar is None


def teste_fl3_resposta_no_formato_antigo_nao_tem_momentos() -> None:
    assert _interpretar_momentos(json.dumps({"aparencia_fixa": "a", "instante": "b", "ambiente": None})) is None
    assert _interpretar_momentos(json.dumps({"aparencia_fixa": "a", "instante": "b", "momentos": "lixo"})) is None
    assert _interpretar_momentos("não é json") is None


def teste_fl3_entrada_ruim_ou_sem_conteudo_e_descartada_sem_derrubar_as_outras() -> None:
    resposta = json.dumps(
        {
            "instante": "b",
            "momentos": [
                "isto não é um objeto",
                {"ancora": "só a âncora", "roupa": None, "humor": "null"},
                {"ancora": "boa", "roupa": "manto"},
            ],
        }
    )

    momentos = _interpretar_momentos(resposta)

    assert [m.ancora for m in momentos] == ["boa"]


def teste_fl3_lista_de_momentos_toda_vazia_vira_none() -> None:
    assert _interpretar_momentos(json.dumps({"momentos": []})) is None
    assert _interpretar_momentos(json.dumps({"momentos": [{"ancora": "x"}]})) is None


def teste_fl3_o_interpretador_aceita_a_cerca_de_markdown() -> None:
    resposta = "```json\n" + json.dumps({"momentos": [{"ancora": "x", "roupa": "manto"}]}) + "\n```"

    assert _interpretar_momentos(resposta)[0].roupa == "manto"


def teste_fl3_o_provedor_devolve_a_descricao_de_sempre_e_os_momentos() -> None:
    conteudo = json.dumps(
        {
            "aparencia_fixa": "mulher alta", "instante": "camisola cinza", "ambiente": "cabana",
            "momentos": [{"ancora": "Maren acordou", "roupa": "camisola cinza", "estado_fisico": None, "expressao_e_postura": None, "humor": None, "lugar": "cabana"}],
        }
    )

    def responder(pedido: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": conteudo}, "finish_reason": "stop"}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))

    estado = provedor.sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Maren", None, None, "x/m")

    assert estado.descricao == "Aparência fixa: mulher alta\nNeste instante: camisola cinza\nOnde está: cabana"
    assert [m.roupa for m in estado.momentos] == ["camisola cinza"]


def teste_fl3_resposta_no_formato_antigo_continua_valendo_sem_momentos() -> None:
    conteudo = json.dumps({"aparencia_fixa": "mulher alta", "instante": "camisola cinza", "ambiente": None})
    provedor = ProvedorOpenRouter(
        chave_api="c",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE,
            transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"choices": [{"message": {"content": conteudo}, "finish_reason": "stop"}]})),
        ),
    )

    estado = provedor.sugerir_estado("capítulo", TipoElemento.PERSONAGEM, "Maren", None, None, "x/m")

    assert estado.momentos is None and "camisola cinza" in estado.descricao


# --------------------------------------------------------------------------- #
# A posição de cada momento (FL4)
# --------------------------------------------------------------------------- #


def teste_fl4_cada_momento_ganha_a_posicao_do_paragrafo_onde_a_ancora_esta() -> None:
    guardados = momentos_com_posicao(MOMENTOS, TEXTO)

    assert [m["posicao"] for m in guardados] == [0, len(PARAGRAFOS[0]) + 2, len(PARAGRAFOS[0]) + 2 + len(PARAGRAFOS[1]) + 2]
    assert guardados[1]["ancora"] == "trocou a camisola por um manto verde" and guardados[1]["roupa"] == "manto verde de lã"
    assert set(guardados[0]) == {"ancora", "roupa", "estado_fisico", "expressao_e_postura", "humor", "lugar", "posicao"}


def teste_fl4_ancora_que_nao_esta_no_texto_deixa_o_momento_sem_posicao() -> None:
    guardados = momentos_com_posicao([MomentoSugerido(ancora="frase que não existe", roupa="manto")], TEXTO)

    assert "posicao" not in guardados[0]  # nunca inventa uma posição


def teste_fl4_sem_ancora_o_momento_fica_sem_posicao() -> None:
    guardados = momentos_com_posicao([MomentoSugerido(ancora=None, roupa="manto")], TEXTO)

    assert "posicao" not in guardados[0] and guardados[0]["roupa"] == "manto"


def teste_fl4_sem_momentos_nao_ha_o_que_guardar() -> None:
    assert momentos_com_posicao(None, TEXTO) is None
    assert momentos_com_posicao([], TEXTO) is None


def teste_fl4_a_posicao_conta_em_utf16_como_o_resto_do_sistema() -> None:
    texto = "Início 😀 do dia.\n\nMaren trocou o manto."

    guardados = momentos_com_posicao([MomentoSugerido(ancora="Maren trocou o manto", roupa="manto")], texto)

    # 😀 ocupa 2 unidades em UTF-16 (e 1 caractere em Python): o segundo parágrafo começa 1 unidade depois do índice em caracteres.
    assert guardados[0]["posicao"] == texto.index("Maren") + 1


# --------------------------------------------------------------------------- #
# Escolher o momento que cobre a cena (FL7)
# --------------------------------------------------------------------------- #


def _estado(momentos: list[dict] | None, capitulo_id: int = 1, descricao: str = ESTADO) -> SimpleNamespace:
    return SimpleNamespace(momentos=momentos, capitulo_id=capitulo_id, descricao=descricao)


def _tres_momentos() -> list[dict]:
    return momentos_com_posicao(MOMENTOS, TEXTO)


POS_2 = len(PARAGRAFOS[0]) + 2
POS_3 = POS_2 + len(PARAGRAFOS[1]) + 2


@pytest.mark.parametrize(
    "posicao_da_cena, esperado",
    [(0, 0), (POS_2 - 1, 0), (POS_2, 1), (POS_2 + 40, 1), (POS_3 - 1, 1), (POS_3, 2), (POS_3 + 999, 2)],
)
def teste_fl7_vale_o_ultimo_momento_com_posicao_menor_ou_igual_a_da_cena(posicao_da_cena: int, esperado: int) -> None:
    assert indice_do_momento(_estado(_tres_momentos()), posicao_da_cena, 1) == esperado


def teste_fl7_na_duvida_vale_o_primeiro_momento() -> None:
    momentos = _tres_momentos()

    assert indice_do_momento(_estado(None), 100, 1) == 0  # estado antigo
    assert indice_do_momento(_estado(momentos[:1]), 100, 1) == 0  # um momento só
    assert indice_do_momento(_estado(momentos), None, 1) == 0  # cena sem posição
    assert indice_do_momento(_estado(momentos, capitulo_id=1), 100000, 2) == 0  # estado de OUTRO capítulo: posições incomparáveis


def teste_fl7_momento_sem_posicao_nunca_e_escolhido() -> None:
    momentos = _tres_momentos()
    del momentos[1]["posicao"]

    assert indice_do_momento(_estado(momentos), POS_3 - 1, 1) == 0  # o do meio perdeu a posição: sobra o primeiro
    assert indice_do_momento(_estado(momentos), POS_3, 1) == 2


def teste_fl7_se_nenhum_momento_comeca_antes_da_cena_vale_o_primeiro() -> None:
    momentos = _tres_momentos()
    for momento in momentos:
        momento["posicao"] += 1000

    assert indice_do_momento(_estado(momentos), 10, 1) == 0


def _cena(posicao: int | None = None, trecho: str | None = None, capitulo_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(posicao_no_texto=posicao, trecho=trecho, capitulo=SimpleNamespace(texto=TEXTO), capitulo_id=capitulo_id)


def teste_fl7_a_posicao_escolhida_pela_pessoa_vale_mais_que_a_do_trecho() -> None:
    assert posicao_do_frame(_cena(posicao=POS_3, trecho="Mais tarde, no vilarejo")) == POS_3


def teste_fl7_sem_posicao_escolhida_vale_a_do_comeco_do_trecho() -> None:
    assert posicao_do_frame(_cena(trecho="trocou a camisola por um manto verde")) == POS_2


def teste_fl7_sem_posicao_nem_trecho_nao_ha_posicao() -> None:
    assert posicao_do_frame(_cena()) is None
    assert posicao_do_frame(_cena(trecho="frase que não existe")) is None


def teste_fl7_primeiro_momento_devolve_a_descricao_exatamente_como_esta() -> None:
    estado = _estado(_tres_momentos())

    assert descricao_para_a_cena(estado, _cena(posicao=0)) == ESTADO


def teste_fl7_outro_momento_troca_o_instante_e_o_lugar_e_mantem_a_aparencia_fixa() -> None:
    estado = _estado(_tres_momentos())

    descricao = descricao_para_a_cena(estado, _cena(posicao=POS_2))

    assert descricao == (
        "Aparência fixa: mulher alta, cabelos negros\n"
        "Neste instante: clothing/hairstyle: manto verde de lã; visible mood: animada\n"
        "Onde está: vilarejo"
    )


def teste_fl7_o_momento_do_fim_traz_o_estado_fisico() -> None:
    descricao = descricao_para_a_cena(_estado(_tres_momentos()), _cena(posicao=POS_3))

    assert "physical state: corte na testa, sangue até o queixo" in descricao
    assert "clothing/hairstyle: manto verde de lã, rasgado" in descricao
    assert "Onde está" not in descricao  # esse momento não tem lugar


def teste_fl7_momento_sem_nenhum_conteudo_volta_a_descricao() -> None:
    momentos = [{"roupa": "x", "posicao": 0}, {"ancora": "y", "posicao": 10}]

    assert descricao_para_a_cena(_estado(momentos), _cena(posicao=10)) == ESTADO


# --------------------------------------------------------------------------- #
# As rotas
# --------------------------------------------------------------------------- #


def _cenario(cliente: TestClient, usar_provedor_falso, provedor: ProvedorFalso | None = None):
    """Um livro de três parágrafos, a Maren com estado no capítulo 1, e a configuração dos modelos. Devolve (provedor, livro, capitulo, estado_id)."""
    provedor = usar_provedor_falso(provedor or ProvedorFalso(prompt="two figures", estado=ESTADO, momentos=MOMENTOS))
    resposta = cliente.post("/livros", files={"arquivo": ("l.epub", _epub(), "application/epub+zip")})
    assert resposta.status_code == 201, resposta.text
    livro = resposta.json()["livro"]
    capitulo = livro["capitulos"][0]
    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Maren", "estado_inicial": {"capitulo_id": capitulo["id"], "descricao": "Maren está assim."}},
    ).json()
    estado_id = cliente.get(f"/elementos/{elemento['id']}").json()["estados"][0]["id"]
    perfil = cliente.post("/perfis-renderizacao", json={"nome": "Aquarela", "estilo": "aquarela"}).json()
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    return provedor, livro, capitulo, estado_id


def _cena_no_trecho(cliente: TestClient, capitulo_id: int, estado_id: int, trecho: str | None) -> dict:
    corpo = {"tipo": "CENA", "titulo": "A cena", "estados_ids": [estado_id]}
    if trecho:
        corpo["trecho"] = trecho
    resposta = cliente.post(f"/capitulos/{capitulo_id}/frames", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def teste_fl4_a_leitura_profunda_guarda_os_momentos_com_posicao(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    sessao_com_tabelas.expire_all()
    estado = sessao_com_tabelas.get(EstadoElemento, estado_id)
    assert estado.descricao == ESTADO
    assert [m["roupa"] for m in estado.momentos] == ["camisola de linho cinza", "manto verde de lã", "manto verde de lã, rasgado"]
    assert [m["posicao"] for m in estado.momentos] == [0, POS_2, POS_3]


def teste_fl7_a_cena_no_comeco_do_capitulo_recebe_o_primeiro_momento_como_sempre(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, "Maren acordou antes do sol")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    (linha,) = provedor.chamadas_de_prompt[0]["elementos"]
    assert linha == f"Maren: {ESTADO}"


def teste_fl7_a_cena_do_meio_recebe_o_manto_e_nao_a_camisola(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, "trocou a camisola por um manto verde")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    (linha,) = provedor.chamadas_de_prompt[0]["elementos"]
    assert "manto verde de lã" in linha and "camisola" not in linha
    assert "Aparência fixa: mulher alta, cabelos negros" in linha and "Onde está: vilarejo" in linha


def teste_fl7_a_cena_do_fim_recebe_o_ferimento(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, "uma pedra lhe cortou a testa")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    (linha,) = provedor.chamadas_de_prompt[0]["elementos"]
    assert "corte na testa" in linha and "rasgado" in linha


def teste_fl7_a_posicao_escolhida_pela_pessoa_decide_a_cena(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = cliente.post(
        f"/capitulos/{capitulo['id']}/frames",
        json={"tipo": "CENA", "titulo": "Aqui", "estados_ids": [estado_id], "posicao_no_texto": POS_3},
    ).json()

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert "corte na testa" in provedor.chamadas_de_prompt[0]["elementos"][0]


def teste_fl7_cena_sem_trecho_nem_posicao_recebe_o_primeiro_momento(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert provedor.chamadas_de_prompt[0]["elementos"] == [f"Maren: {ESTADO}"]


def teste_fl7_a_fundamentacao_tambem_recebe_o_momento_da_cena(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, "uma pedra lhe cortou a testa")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert "corte na testa" in provedor.chamadas_de_fundamentacao[0]["participantes"][0]


def teste_fl7_o_retrato_nao_escolhe_momento_e_usa_o_estado_como_esta(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [estado_id]}).json()

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    (linha,) = provedor.chamadas_de_prompt[0]["elementos"]
    assert "camisola de linho cinza" in linha and "manto" not in linha


def teste_fl4_em_economia_os_momentos_nao_sao_relidos_e_em_qualidade_sao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    assert len(provedor.chamadas_de_estado) == 1  # ECONOMIA: reaproveita

    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    assert len(provedor.chamadas_de_estado) == 2  # QUALIDADE: relê


def teste_fl4_leitura_no_formato_antigo_deixa_os_momentos_nulos(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso, ProvedorFalso(prompt="x", estado=ESTADO))
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, "trocou a camisola por um manto verde")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(EstadoElemento, estado_id).momentos is None


def teste_fl4_a_api_do_estado_traz_os_momentos(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    estado = cliente.get(f"/estados/{estado_id}").json()

    assert [m["posicao"] for m in estado["momentos"]] == [0, POS_2, POS_3]
    assert estado["momentos"][2]["estado_fisico"] == "corte na testa, sangue até o queixo"


def teste_fl4_estado_que_nunca_foi_lido_vem_com_momentos_nulos(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, estado_id = _cenario(cliente, usar_provedor_falso)

    assert cliente.get(f"/estados/{estado_id}").json()["momentos"] is None


def teste_fl4_editar_a_descricao_a_mao_apaga_os_momentos(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    resposta = cliente.patch(f"/estados/{estado_id}", json={"descricao": "Maren, do jeito que eu quero"})

    assert resposta.status_code == 200 and resposta.json()["momentos"] is None
    assert cliente.get(f"/estados/{estado_id}").json()["momentos"] is None


def teste_fl4_mandar_a_mesma_descricao_ou_so_a_ancora_nao_apaga_os_momentos(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso)
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    cliente.patch(f"/estados/{estado_id}", json={"descricao": ESTADO})
    cliente.patch(f"/estados/{estado_id}", json={"imagem_ancora_id": None})

    assert len(cliente.get(f"/estados/{estado_id}").json()["momentos"]) == 3


def teste_fl7_a_instrucao_da_cena_diz_que_so_a_roupa_e_o_estado_fisico_do_momento_valem() -> None:
    from testes.teste_pedidos_de_07_10 import _instrucao_de_montagem

    instrucao = _instrucao_de_montagem()

    assert 'O "Neste instante:" de uma cena pode vir em partes rotuladas' in instrucao
    assert '"clothing/hairstyle:", "physical state:", "expression and posture:", "visible mood:"' in instrucao
    assert "Use só a roupa e o penteado e o estado físico" in instrucao


# --------------------------------------------------------------------------- #
# A migração
# --------------------------------------------------------------------------- #


def teste_fl4_a_migracao_adiciona_e_remove_a_coluna_sem_mexer_nos_estados() -> None:
    import importlib.util

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from testes.teste_lm_migracao_do_uso import RAIZ

    arquivo = RAIZ / "migracoes" / "versions" / "a8b9c0d1e2f4_momentos_do_estado.py"
    especificacao = importlib.util.spec_from_file_location("migracao_a8b9c0d1e2f4", arquivo)
    migracao = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(migracao)
    motor = sa.create_engine("sqlite://")
    with motor.begin() as conexao:
        conexao.execute(sa.text("CREATE TABLE estados_elemento (id INTEGER PRIMARY KEY, descricao TEXT)"))
        conexao.execute(sa.text("INSERT INTO estados_elemento (descricao) VALUES ('Maren está assim.')"))

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.aplicar()
    with motor.connect() as conexao:
        assert tuple(conexao.execute(sa.text("SELECT descricao, momentos FROM estados_elemento")).one()) == ("Maren está assim.", None)

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.reverter()
    assert {c["name"] for c in sa.inspect(motor).get_columns("estados_elemento")} == {"id", "descricao"}
    assert migracao.upgrade is migracao.aplicar and migracao.downgrade is migracao.reverter


def teste_fl4_a_migracao_vem_depois_da_do_modelo_de_leitura() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from testes.teste_lm_migracao_do_uso import RAIZ

    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)

    assert diretorio.get_revision("a8b9c0d1e2f4").down_revision == "f7a8b9c0d1e3"
    assert len(diretorio.get_heads()) == 1
