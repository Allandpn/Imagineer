"""O dossiê da cena (item 4.9, FL5 a FL9, FL12 e FL13.2; etapa 3).

A fundamentação de três frases lia o capítulo inteiro mas devolvia pouco. O dossiê devolve a lista fechada de **quem e o que está presente naquele momento**,
com as características de cada um, mais o lugar, a luz e a ação. A pessoa vê a lista, tira, acrescenta e edita; a lista confirmada é a que o prompt trata como
"aparece só isto". Nenhum teste fala com o OpenRouter.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.openrouter import (
    ENDERECO_BASE,
    ProvedorOpenRouter,
    _interpretar_dossie,
    contexto_do_dossie,
    presentes_incluidos,
    texto_dos_presentes,
)
from imagineer.ia.provedor import ErroDoProvedorIA
from imagineer.modelos import Frame, Prompt
from imagineer.servicos.dossie_da_cena import confirmar_dossie, dossie_esta_velho, entrada_do_dossie, guardar_dossie

from testes.teste_fl_momentos import ESTADO, MOMENTOS, POS_3, _cena_no_trecho, _cenario

DOSSIE = {
    "momento_incerto": False,
    "presentes": [
        {"nome": "Maren", "tipo": "PESSOA", "elemento": "maren", "caracteristicas": "manto verde de lã, de costas para a lareira", "incerto": False, "incluir": True},
        {"nome": "o cão", "tipo": "CRIATURA", "elemento": None, "caracteristicas": "cinzento, deitado sob a mesa", "incerto": True, "incluir": True},
        {"nome": "a mesa", "tipo": "OBJETO", "elemento": "Fantasma", "caracteristicas": "redonda, de carvalho", "incerto": False, "incluir": True},
    ],
    "onde": "taverna do Corvo Torto",
    "luz_e_clima": "uma vela no castiçal",
    "acao": "Maren espera sentada",
    "faltou": ["a cor do portão"],
}


def _provedor_falso(**mudancas) -> ProvedorFalso:
    return ProvedorFalso(prompt="two figures", estado=ESTADO, momentos=MOMENTOS, dossie=json.loads(json.dumps(DOSSIE)), **mudancas)


# --------------------------------------------------------------------------- #
# A instrução (FL5, FL6)
# --------------------------------------------------------------------------- #


def _instrucao_do_dossie() -> str:
    pedidos = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"presentes": [], "onde": "x"})}, "finish_reason": "stop"}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))
    provedor.fundamentar_frame("capítulo", "Cena", None, None, None, None, [], "x/m")
    return pedidos[0]["messages"][0]["content"]


def teste_fl5_a_instrucao_le_o_capitulo_inteiro_para_montar_a_lista_fechada() -> None:
    instrucao = _instrucao_do_dossie()

    assert "para montar o DOSSIÊ de uma cena" in instrucao
    assert "a lista FECHADA de QUEM e O QUE está presente naquele momento" in instrucao
    assert "leia o capítulo todo ANTES de descrever" in instrucao


def teste_fl6_o_capitulo_inteiro_vale_e_so_se_separa_o_outro_momento() -> None:
    instrucao = _instrucao_do_dossie()

    assert "O capítulo inteiro vale." in instrucao
    assert "ESPALHADOS" in instrucao and "(antes ou depois do trecho)" in instrucao
    assert "o spoiler" not in instrucao  # o risco foi assumido pelo Allan: a instrução não manda esconder o que vem adiante
    assert "você não precisa esconder o que o capítulo revela adiante" in instrucao
    assert "A única separação que você mantém é a de MOMENTO" in instrucao
    assert 'INCLUA o item com "incerto": true' in instrucao


def teste_fl5_o_trecho_diz_qual_e_o_momento_e_sem_ele_o_momento_e_incerto() -> None:
    instrucao = _instrucao_do_dossie()

    assert 'O trecho diz QUAL é o momento' in instrucao
    assert 'Sem trecho, o momento é o que a descrição do usuário conta, e você marca "momento_incerto": true' in instrucao


def teste_fl5_a_instrucao_pede_os_campos_do_dossie_e_a_lista_do_que_faltou() -> None:
    instrucao = _instrucao_do_dossie()

    for campo in ('"momento_incerto"', '"presentes"', '"elemento"', '"caracteristicas"', '"incerto"', '"onde"', '"luz_e_clima"', '"acao"', '"faltou"'):
        assert campo in instrucao
    assert "PESSOA, CRIATURA, OBJETO ou LUGAR" in instrucao
    assert "não entra quem só é mencionado, lembrado ou está" in instrucao
    assert "O que o capítulo não deixa claro vai em" in instrucao


def teste_fl5_a_instrucao_nao_repete_a_aparencia_dos_cadastrados_e_troca_nomes_inventados_pelo_que_se_ve() -> None:
    instrucao = _instrucao_do_dossie()

    assert "não repita a aparência estabelecida" in instrucao
    assert "escreva o que SE VÊ" in instrucao
    assert "Você NÃO substitui a descrição do usuário" in instrucao


# --------------------------------------------------------------------------- #
# O interpretador (FL5)
# --------------------------------------------------------------------------- #


def _resposta(**mudancas) -> str:
    return json.dumps({"momento_incerto": False, "presentes": [], "onde": None, "luz_e_clima": None, "acao": None, "faltou": [], **mudancas})


def teste_fl5_o_interpretador_normaliza_o_dossie_e_deriva_o_contexto() -> None:
    contexto, dossie = _interpretar_dossie(
        _resposta(
            momento_incerto=True,
            presentes=[{"nome": "Maren", "tipo": "pessoa", "elemento": "Maren", "caracteristicas": "manto verde", "incerto": False}],
            onde="taverna", luz_e_clima="vela", acao="espera", faltou=["a cor do portão", "  "],
        )
    )

    assert contexto == "Onde: taverna\nLuz e clima: vela\nAção: espera"
    assert dossie == {
        "momento_incerto": True,
        "presentes": [{"nome": "Maren", "tipo": "PESSOA", "elemento": "Maren", "caracteristicas": "manto verde", "incerto": False, "incluir": True}],
        "onde": "taverna", "luz_e_clima": "vela", "acao": "espera", "faltou": ["a cor do portão"],
    }


def teste_fl5_tipo_desconhecido_vira_objeto_e_item_sem_nome_ou_que_nao_e_objeto_e_descartado() -> None:
    _, dossie = _interpretar_dossie(
        _resposta(
            presentes=[
                {"nome": "x", "tipo": "FANTASMA"},
                {"nome": None, "tipo": "PESSOA"},
                "lixo",
                {"nome": "y", "tipo": "lugar", "caracteristicas": None},
            ],
            onde="a",
        )
    )

    assert [(p["nome"], p["tipo"], p["caracteristicas"]) for p in dossie["presentes"]] == [("x", "OBJETO", ""), ("y", "LUGAR", "")]


def teste_fl5_incerto_so_vale_quando_e_verdadeiro_de_verdade() -> None:
    _, dossie = _interpretar_dossie(_resposta(presentes=[{"nome": "a", "incerto": "sim"}, {"nome": "b", "incerto": True}], onde="x"))

    assert [p["incerto"] for p in dossie["presentes"]] == [False, True]


def teste_fl5_resposta_no_formato_antigo_devolve_o_contexto_e_nenhum_dossie() -> None:
    contexto, dossie = _interpretar_dossie(json.dumps({"contexto": "no pátio, de dia"}))

    assert (contexto, dossie) == ("no pátio, de dia", None)


def teste_fl5_a_cerca_de_markdown_e_aceita() -> None:
    contexto, dossie = _interpretar_dossie("```json\n" + _resposta(onde="taverna") + "\n```")

    assert dossie["onde"] == "taverna" and contexto == "Onde: taverna"


def teste_fl5_dossie_sem_nada_e_erro_em_portugues() -> None:
    with pytest.raises(ErroDoProvedorIA, match="sem nenhum presente, lugar, luz nem ação"):
        _interpretar_dossie(_resposta())


def teste_fl5_resposta_que_nao_e_json_e_erro_em_portugues() -> None:
    with pytest.raises(ErroDoProvedorIA, match="não devolveu JSON"):
        _interpretar_dossie("Claro! Aqui está.")


def teste_fl5_o_provedor_devolve_o_dossie_e_o_contexto_do_texto_dele() -> None:
    conteudo = _resposta(presentes=[{"nome": "Maren", "tipo": "PESSOA", "elemento": None, "caracteristicas": "manto", "incerto": False}], onde="taverna", acao="espera")
    provedor = ProvedorOpenRouter(
        chave_api="c",
        cliente=httpx.Client(
            base_url=ENDERECO_BASE,
            transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"choices": [{"message": {"content": conteudo}, "finish_reason": "stop"}]})),
        ),
    )

    fundamentado = provedor.fundamentar_frame("capítulo", "Cena", None, None, None, None, [], "x/m")

    assert fundamentado.contexto == "Onde: taverna\nAção: espera" and fundamentado.dossie["presentes"][0]["nome"] == "Maren"


def teste_fl5_a_fundamentacao_usa_o_esquema_do_dossie_e_o_contexto_do_dossie_so_junta_o_que_ha() -> None:
    from imagineer.ia.tarefas import PERFIS

    assert PERFIS["fundamentacao"].esquema == "dossie"
    assert contexto_do_dossie({"onde": "a", "luz_e_clima": None, "acao": "c"}) == "Onde: a\nAção: c"
    assert contexto_do_dossie({}) == ""


# --------------------------------------------------------------------------- #
# O que a montagem recebe (FL9, FL12)
# --------------------------------------------------------------------------- #


def teste_fl12_a_lista_confirmada_vira_o_bloco_o_que_aparece_na_cena() -> None:
    texto = texto_dos_presentes(DOSSIE)

    assert texto.splitlines() == [
        "O QUE APARECE NA CENA (lista fechada, confirmada pela pessoa; aparece SÓ isto, mais o que a descrição da cena citar):",
        '1. Maren [pessoa] (é o elemento cadastrado "maren"): manto verde de lã, de costas para a lareira',
        "2. o cão [criatura]: cinzento, deitado sob a mesa [incerto]",
        '3. a mesa [objeto] (é o elemento cadastrado "Fantasma"): redonda, de carvalho',
        "Pessoas e criaturas no quadro: 2",
        "LUGAR: taverna do Corvo Torto",
        "LUZ E CLIMA: uma vela no castiçal",
        "AÇÃO (um instante parado): Maren espera sentada",
    ]


def teste_fl9_o_que_a_pessoa_tirou_nao_entra_na_lista_nem_na_contagem() -> None:
    dossie = json.loads(json.dumps(DOSSIE))
    dossie["presentes"][1]["incluir"] = False

    texto = texto_dos_presentes(dossie)

    assert "o cão" not in texto and "Pessoas e criaturas no quadro: 1" in texto
    assert [p["nome"] for p in presentes_incluidos(dossie)] == ["Maren", "a mesa"]


def teste_fl12_lista_vazia_diz_que_nao_ha_nada_alem_da_descricao() -> None:
    texto = texto_dos_presentes({"presentes": [], "onde": "taverna"})

    assert "(nada além do que a descrição da cena cita)" in texto and "Pessoas e criaturas no quadro: 0" in texto


def teste_fl12_presente_sem_incluir_informado_conta_como_incluido() -> None:
    assert [p["nome"] for p in presentes_incluidos({"presentes": [{"nome": "a"}, {"nome": "b", "incluir": False}]})] == ["a"]


def _pedido_de_montagem(dossie: dict | None, contexto: str | None = None) -> tuple[str, str]:
    pedidos = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "a prompt"}, "finish_reason": "stop"}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))
    provedor.montar_prompt("cena", ["Maren: x"], "estilo", "x/m", contexto_do_livro=contexto, trecho_do_livro="o trecho", dossie=dossie)
    return pedidos[0]["messages"][0]["content"], pedidos[0]["messages"][1]["content"]


def teste_fl12_o_pedido_leva_a_lista_antes_do_trecho() -> None:
    _, pedido = _pedido_de_montagem(DOSSIE)

    assert "O QUE APARECE NA CENA" in pedido
    assert pedido.index("O QUE APARECE NA CENA") < pedido.index("TRECHO DO LIVRO")
    assert pedido.index("ELEMENTOS QUE APARECEM") < pedido.index("O QUE APARECE NA CENA")


def teste_fl12_sem_dossie_o_pedido_e_o_de_sempre() -> None:
    _, pedido = _pedido_de_montagem(None, contexto="o capítulo confirma o pátio")

    assert "O QUE APARECE NA CENA" not in pedido and "CONTEXTO DO LIVRO" in pedido


def teste_fl12_a_instrucao_manda_uma_frase_por_figura_a_contagem_e_a_ordem_do_texto() -> None:
    instrucao, _ = _pedido_de_montagem(DOSSIE)

    assert "escreva UMA frase por figura" in instrucao
    assert "para não misturar atributos entre as figuras" in instrucao
    assert 'diga quantas pessoas e criaturas são ("exactly two figures: ...")' in instrucao
    assert "câmera, a AÇÃO e as figuras (o mais importante vem primeiro" in instrucao
    assert "até uns 150 palavras, sem repetir o mesmo elemento" in instrucao
    assert 'Os itens de tipo "lugar" da lista são o cenário, e não uma figura.' in instrucao


def teste_fl12_a_prioridade_poe_a_lista_confirmada_logo_depois_da_descricao_do_usuario() -> None:
    instrucao, _ = _pedido_de_montagem(DOSSIE)

    assert instrucao.index("2. A descrição da cena escrita pelo usuário") < instrucao.index("2a. O que aparece na cena") < instrucao.index("2b. O trecho do livro")


def teste_fl12_o_item_incerto_so_entra_se_a_descricao_sustenta() -> None:
    instrucao, _ = _pedido_de_montagem(DOSSIE)

    assert "[incerto] só entra se a descrição da cena o sustenta" in instrucao


# --------------------------------------------------------------------------- #
# O serviço: guardar, comparar e confirmar (FL8, FL9)
# --------------------------------------------------------------------------- #


def _frame(**campos) -> SimpleNamespace:
    base = dict(
        titulo="A espera", descricao="Maren espera", horario=None, clima=None, humor=None, trecho="trocou a camisola", posicao_no_texto=None,
        dossie=None, dossie_entrada=None, contexto_do_livro=None, confirmado_pela_leitura_profunda=False,
    )
    base.update(campos)
    return SimpleNamespace(**base)


PARTICIPANTES = ["Maren: Aparência fixa: mulher alta"]


@pytest.mark.parametrize(
    "mudanca",
    [
        {"titulo": "Outro"}, {"descricao": "mudou"}, {"horario": "noite"}, {"clima": "chuva"}, {"humor": "tenso"}, {"trecho": "outro trecho"},
        {"posicao_no_texto": 10},
    ],
)
def teste_fl8_mudar_qualquer_entrada_da_cena_muda_o_resumo(mudanca: dict) -> None:
    assert entrada_do_dossie(_frame(**mudanca), PARTICIPANTES) != entrada_do_dossie(_frame(), PARTICIPANTES)


def teste_fl8_mudar_um_participante_ou_o_estado_dele_muda_o_resumo() -> None:
    assert entrada_do_dossie(_frame(), ["Maren: outra roupa"]) != entrada_do_dossie(_frame(), PARTICIPANTES)
    assert entrada_do_dossie(_frame(), PARTICIPANTES + ["Hospius: x"]) != entrada_do_dossie(_frame(), PARTICIPANTES)


def _estado_de(estado_id: int, nome: str, momentos: list[dict] | None, capitulo_id: int = 1, descricao: str = "x") -> SimpleNamespace:
    return SimpleNamespace(id=estado_id, elemento=SimpleNamespace(nome=nome), momentos=momentos, capitulo_id=capitulo_id, descricao=descricao)


def teste_fl8_o_resumo_dos_participantes_tem_estado_elemento_e_momento_usado_em_ordem_de_estado() -> None:
    from imagineer.servicos.dossie_da_cena import entrada_dos_participantes

    momentos = [{"roupa": "a", "posicao": 0}, {"roupa": "b", "posicao": 100}]
    frame = SimpleNamespace(
        estados_elemento=[_estado_de(9, "Hospius", None), _estado_de(2, "Maren", momentos)], posicao_no_texto=150, trecho=None,
        capitulo=SimpleNamespace(texto="x"), capitulo_id=1,
    )

    assert entrada_dos_participantes(frame) == [[2, "Maren", 1], [9, "Hospius", 0]]


def teste_fl8_reescrever_a_descricao_do_estado_nao_muda_o_resumo_dos_participantes() -> None:
    from imagineer.servicos.dossie_da_cena import entrada_dos_participantes

    def frame_com(descricao: str) -> SimpleNamespace:
        return SimpleNamespace(
            estados_elemento=[_estado_de(2, "Maren", None, descricao=descricao)], posicao_no_texto=None, trecho=None, capitulo=SimpleNamespace(texto="x"), capitulo_id=1
        )

    assert entrada_dos_participantes(frame_com("de camisola")) == entrada_dos_participantes(frame_com("de armadura"))


def teste_fl8_o_mesmo_conteudo_da_o_mesmo_resumo() -> None:
    assert entrada_do_dossie(_frame(), PARTICIPANTES) == entrada_do_dossie(_frame(), list(PARTICIPANTES))
    assert len(entrada_do_dossie(_frame(), PARTICIPANTES)) == 40


def teste_fl8_sem_dossie_nao_ha_o_que_envelhecer() -> None:
    assert dossie_esta_velho(_frame(), PARTICIPANTES) is False


def teste_fl8_guardar_marca_o_frame_como_lido_e_deixa_o_contexto() -> None:
    frame = _frame()

    guardado = guardar_dossie(frame, DOSSIE, "o texto do provedor", PARTICIPANTES, ["Maren"])

    assert frame.dossie is guardado and guardado["confirmado"] is False
    # FL8: o contexto é o texto do dossiê (lugar, luz e ação), e não o que o provedor devolveu junto.
    assert frame.contexto_do_livro == contexto_do_dossie(DOSSIE)
    assert frame.contexto_do_livro.splitlines() == ["Onde: taverna do Corvo Torto", "Luz e clima: uma vela no castiçal", "Ação: Maren espera sentada"]
    assert frame.confirmado_pela_leitura_profunda is True
    assert dossie_esta_velho(frame, PARTICIPANTES) is False
    assert dossie_esta_velho(frame, ["Maren: mudou"]) is True


def teste_fl8_guardar_liga_o_presente_ao_elemento_cadastrado_sem_diferenca_de_maiusculas() -> None:
    frame = _frame()

    guardado = guardar_dossie(frame, DOSSIE, "", PARTICIPANTES, ["Maren"])

    assert [p["elemento"] for p in guardado["presentes"]] == ["Maren", None, None]  # "maren" casou; "Fantasma" não é do frame


def teste_fl8_guardar_nao_mexe_no_dossie_que_veio_da_ia() -> None:
    original = json.loads(json.dumps(DOSSIE))

    guardar_dossie(_frame(), original, "", PARTICIPANTES, ["Maren"])

    assert original == DOSSIE


def teste_fl9_confirmar_troca_a_lista_marca_confirmado_e_atualiza_o_resumo() -> None:
    frame = _frame()
    guardar_dossie(frame, DOSSIE, "", PARTICIPANTES, ["Maren"])
    novo = {"presentes": [{"nome": "Maren", "tipo": "PESSOA", "elemento": "Maren", "caracteristicas": "só ela", "incerto": False, "incluir": True}]}

    atual = confirmar_dossie(frame, novo, {"presentes"}, ["Maren: mudou"], ["Maren"])

    assert atual["confirmado"] is True and [p["nome"] for p in atual["presentes"]] == ["Maren"]
    assert dossie_esta_velho(frame, ["Maren: mudou"]) is False  # o que ela confirmou vale para o estado de agora


def teste_fl9_o_que_nao_veio_no_pedido_fica_como_estava_e_o_que_veio_nulo_apaga() -> None:
    frame = _frame()
    guardar_dossie(frame, DOSSIE, "", PARTICIPANTES, ["Maren"])

    atual = confirmar_dossie(frame, {"presentes": [], "luz_e_clima": None}, {"presentes", "luz_e_clima"}, PARTICIPANTES, [])

    assert atual["onde"] == "taverna do Corvo Torto" and atual["acao"] == "Maren espera sentada"  # não vieram: ficam
    assert atual["luz_e_clima"] is None  # veio nulo: apaga
    assert atual["faltou"] == ["a cor do portão"] and atual["momento_incerto"] is False  # o que a IA leu e a pessoa não edita


def teste_fl9_sem_dossie_lido_a_pessoa_escreve_a_lista_do_zero() -> None:
    frame = _frame()

    atual = confirmar_dossie(frame, {"presentes": [{"nome": "a", "tipo": "OBJETO", "caracteristicas": "x", "incerto": False, "incluir": True}], "onde": "aqui"}, {"presentes", "onde"}, PARTICIPANTES, [])

    assert atual["onde"] == "aqui" and atual["confirmado"] is True and atual["faltou"] == [] and frame.contexto_do_livro == "Onde: aqui"


def teste_fl9_confirmar_nao_mexe_no_dicionario_do_pedido() -> None:
    novo = {"presentes": [{"nome": "Maren", "tipo": "PESSOA", "elemento": "maren", "caracteristicas": "x", "incerto": False, "incluir": True}]}

    confirmar_dossie(_frame(), novo, {"presentes"}, PARTICIPANTES, ["Maren"])

    assert novo["presentes"][0]["elemento"] == "maren"


# --------------------------------------------------------------------------- #
# As rotas (FL9)
# --------------------------------------------------------------------------- #


def _cena(cliente, usar_provedor_falso, provedor=None, trecho="trocou a camisola por um manto verde"):
    provedor, livro, capitulo, estado_id = _cenario(cliente, usar_provedor_falso, provedor or _provedor_falso())
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, trecho)
    return provedor, livro, capitulo, estado_id, frame


def teste_fl9_get_sem_dossie_lido_devolve_nulo_e_nao_gasta(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)

    resposta = cliente.get(f"/frames/{frame['id']}/dossie")

    assert resposta.status_code == 200 and resposta.json() is None
    assert provedor.chamadas_de_fundamentacao == []


def teste_fl9_post_le_o_capitulo_guarda_e_devolve_o_dossie_com_o_modelo(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/frames/{frame['id']}/dossie")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["modelo"] == MODELO_FALSO and corpo["custo"] is None
    assert corpo["confirmado"] is False and corpo["desatualizado"] is False and corpo["momento_incerto"] is False
    assert [(p["nome"], p["tipo"], p["incluir"]) for p in corpo["presentes"]] == [("Maren", "PESSOA", True), ("o cão", "CRIATURA", True), ("a mesa", "OBJETO", True)]
    assert corpo["onde"] == "taverna do Corvo Torto" and corpo["faltou"] == ["a cor do portão"]
    assert len(provedor.chamadas_de_fundamentacao) == 1
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Frame, frame["id"]).contexto_do_livro == "Onde: taverna do Corvo Torto\nLuz e clima: uma vela no castiçal\nAção: Maren espera sentada"


def teste_fl9_post_liga_o_presente_ao_elemento_cadastrado(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/frames/{frame['id']}/dossie").json()

    assert [p["elemento"] for p in corpo["presentes"]] == ["Maren", None, None]


def teste_fl9_get_devolve_o_que_o_post_guardou_sem_gastar(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    lido = cliente.post(f"/frames/{frame['id']}/dossie").json()

    guardado = cliente.get(f"/frames/{frame['id']}/dossie").json()

    assert {k: v for k, v in lido.items() if k not in ("modelo", "custo")} == guardado
    assert len(provedor.chamadas_de_fundamentacao) == 1


def teste_fl9_cada_post_gasta_e_refaz(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)

    cliente.post(f"/frames/{frame['id']}/dossie")
    cliente.post(f"/frames/{frame['id']}/dossie")

    assert len(provedor.chamadas_de_fundamentacao) == 2


def teste_fl9_post_refaz_ate_o_que_a_pessoa_ja_confirmou(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": []})

    refeito = cliente.post(f"/frames/{frame['id']}/dossie").json()

    assert refeito["confirmado"] is False and len(refeito["presentes"]) == 3  # é o botão "ler de novo"


def teste_fl9_post_manda_o_momento_e_os_participantes_para_a_leitura(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso, trecho="uma pedra lhe cortou a testa")

    cliente.post(f"/frames/{frame['id']}/dossie")

    chamada = provedor.chamadas_de_fundamentacao[0]
    assert "corte na testa" in chamada["participantes"][0]  # o momento do elemento que cobre o trecho (etapa 2)
    assert chamada["trecho"] == "uma pedra lhe cortou a testa" and chamada["titulo"] == "A cena"


def teste_fl9_post_sem_nenhum_modelo_escolhido_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_extracao": "", "modelo_prompt": ""})

    resposta = cliente.post(f"/frames/{frame['id']}/dossie")

    assert resposta.status_code == 422 and "modelo de leitura" in resposta.json()["detail"]


def teste_fl9_post_com_o_modelo_no_formato_antigo_da_502_em_portugues(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso, ProvedorFalso(prompt="x", estado=ESTADO, momentos=MOMENTOS))  # sem dossiê: só o contexto

    resposta = cliente.post(f"/frames/{frame['id']}/dossie")

    assert resposta.status_code == 502 and "lista de quem aparece" in resposta.json()["detail"]


def teste_fl9_post_com_erro_do_provedor_da_502(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso, _provedor_falso(erro=ErroDoProvedorIA("caiu")))

    assert cliente.post(f"/frames/{frame['id']}/dossie").status_code == 502


def teste_fl9_um_retrato_nao_tem_dossie(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso, _provedor_falso())
    retrato = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [estado_id]}).json()

    for metodo, corpo in (("get", None), ("post", None), ("put", {"presentes": []})):
        resposta = getattr(cliente, metodo)(f"/frames/{retrato['id']}/dossie", **({"json": corpo} if corpo is not None else {}))
        assert resposta.status_code == 422 and "Só uma cena tem dossiê" in resposta.json()["detail"], metodo


def teste_fl9_frame_inexistente_da_404(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(_provedor_falso())

    assert cliente.get("/frames/999/dossie").status_code == 404
    assert cliente.post("/frames/999/dossie").status_code == 404
    assert cliente.put("/frames/999/dossie", json={"presentes": []}).status_code == 404


def teste_fl9_put_grava_a_lista_confirmada_sem_gastar(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    lido = cliente.get(f"/frames/{frame['id']}/dossie").json()
    lista = lido["presentes"]
    lista[1]["incluir"] = False  # tirou o cão
    lista.append({"nome": "uma vela", "tipo": "OBJETO", "caracteristicas": "de cera, acesa"})  # acrescentou

    resposta = cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lista, "acao": "Maren espera, de costas"})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["confirmado"] is True and corpo["desatualizado"] is False
    assert [(p["nome"], p["incluir"]) for p in corpo["presentes"]] == [("Maren", True), ("o cão", False), ("a mesa", True), ("uma vela", True)]
    assert corpo["acao"] == "Maren espera, de costas" and corpo["onde"] == "taverna do Corvo Torto"  # o que não veio ficou
    assert len(provedor.chamadas_de_fundamentacao) == 1  # o PUT não gasta


def teste_fl9_put_sem_dossie_lido_escreve_a_lista_do_zero(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)

    resposta = cliente.put(
        f"/frames/{frame['id']}/dossie",
        json={"presentes": [{"nome": "Maren", "tipo": "PESSOA", "elemento": "Maren", "caracteristicas": "manto verde"}], "onde": "a taverna"},
    )

    assert resposta.status_code == 200 and resposta.json()["confirmado"] is True
    assert resposta.json()["presentes"][0]["incluir"] is True and resposta.json()["faltou"] == []
    assert provedor.chamadas_de_fundamentacao == []


def teste_fl9_put_com_campo_nulo_apaga_e_ausente_mantem(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")

    corpo = cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": [], "luz_e_clima": None}).json()

    assert corpo["luz_e_clima"] is None and corpo["onde"] == "taverna do Corvo Torto" and corpo["acao"] == "Maren espera sentada"


@pytest.mark.parametrize(
    "corpo",
    [
        {},  # falta a lista
        {"presentes": [{"nome": "", "tipo": "OBJETO"}]},
        {"presentes": [{"nome": "x", "tipo": "FANTASMA"}]},
        {"presentes": [{"nome": "x"}]},
        {"presentes": [{"nome": f"n{i}", "tipo": "OBJETO"} for i in range(41)]},
        {"presentes": [], "modelo_imagem": "x"},
    ],
)
def teste_fl9_put_invalido_da_422(cliente: TestClient, usar_provedor_falso, corpo: dict) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)

    assert cliente.put(f"/frames/{frame['id']}/dossie", json=corpo).status_code == 422


def teste_fl8_depois_de_mudar_a_cena_o_get_diz_que_esta_desatualizado(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["desatualizado"] is False

    cliente.patch(f"/frames/{frame['id']}", json={"descricao": "Maren, agora de pé"})

    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["desatualizado"] is True


def teste_fl8_trocar_quem_esta_ligado_a_cena_deixa_o_dossie_velho(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, _, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")

    cliente.put(f"/frames/{frame['id']}/estados", json={"estados_ids": []})

    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["desatualizado"] is True


def teste_fl8_editar_o_texto_da_aparencia_nao_envelhece_o_dossie_se_o_momento_e_o_mesmo(cliente: TestClient, usar_provedor_falso) -> None:
    """O dossiê diz quem está na cena, e não como é a aparência de cada um: reescrever o texto do estado não pode apagar a lista confirmada."""
    _, _, _, estado_id, frame = _cena(cliente, usar_provedor_falso, trecho="Maren acordou antes do sol")  # cena no 1º momento
    cliente.post(f"/frames/{frame['id']}/dossie")

    cliente.patch(f"/estados/{estado_id}", json={"descricao": "Maren, do jeito que eu quero"})

    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["desatualizado"] is False


def teste_fl8_apagar_os_momentos_a_mao_muda_o_momento_que_vale_e_envelhece_o_dossie(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, estado_id, frame = _cena(cliente, usar_provedor_falso)  # cena no 2º momento
    cliente.post(f"/frames/{frame['id']}/dossie")

    cliente.patch(f"/estados/{estado_id}", json={"descricao": "Maren, do jeito que eu quero"})  # apaga os momentos: passa a valer o primeiro

    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["desatualizado"] is True


def teste_fl8_reler_os_estados_em_qualidade_nao_apaga_a_confirmacao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": []})
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_estado) >= 2  # o estado foi relido (POST /dossie e o prompt em QUALIDADE)
    assert len(provedor.chamadas_de_fundamentacao) == 1 and cliente.get(f"/frames/{frame['id']}/dossie").json()["confirmado"] is True


def teste_fl9_o_post_do_dossie_le_antes_os_estados_dos_participantes(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso, trecho="uma pedra lhe cortou a testa")

    cliente.post(f"/frames/{frame['id']}/dossie")

    assert len(provedor.chamadas_de_estado) == 1  # o rascunho de identidade não chega à IA do dossiê
    assert "corte na testa" in provedor.chamadas_de_fundamentacao[0]["participantes"][0]


# --------------------------------------------------------------------------- #
# O prompt usa o dossiê (FL8, FL9, FL12)
# --------------------------------------------------------------------------- #


def teste_fl9_o_prompt_de_um_toque_le_o_dossie_e_o_manda_como_lista_fechada(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    chamada = provedor.chamadas_de_prompt[0]
    assert [p["nome"] for p in chamada["dossie"]["presentes"]] == ["Maren", "o cão", "a mesa"]
    assert chamada["contexto_do_livro"] is None  # o dossiê já substitui o contexto antigo
    assert len(provedor.chamadas_de_fundamentacao) == 1
    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["confirmado"] is False  # o fluxo de um toque não confirma por ela


def teste_fl9_o_prompt_usa_o_dossie_confirmado_sem_ler_de_novo_nem_em_qualidade(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    lista = cliente.get(f"/frames/{frame['id']}/dossie").json()["presentes"]
    lista[1]["incluir"] = False
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lista})
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 1  # só a leitura do POST /dossie: o confirmado manda
    enviado = provedor.chamadas_de_prompt[-1]["dossie"]
    assert enviado["confirmado"] is True and [p["incluir"] for p in enviado["presentes"]] == [True, False, True]


def teste_fl8_em_economia_o_dossie_lido_e_reaproveitado(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 1


def teste_fl8_em_economia_o_dossie_velho_e_refeito(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    cliente.patch(f"/frames/{frame['id']}", json={"descricao": "Maren, agora de pé"})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 2


def teste_fl8_em_qualidade_o_dossie_nao_confirmado_e_relido_toda_vez(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 2


def teste_fl8_dossie_confirmado_mas_velho_e_refeito_e_perde_a_confirmacao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": []})

    cliente.patch(f"/frames/{frame['id']}", json={"descricao": "a cena mudou"})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 2
    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["confirmado"] is False


def teste_fl15_frame_antigo_sem_dossie_e_ja_lido_continua_com_o_contexto_de_antes(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    """Compatibilidade: um frame lido pela fundamentação de três frases (sem dossiê) não é relido em ECONOMIA nem ganha lista de repente."""
    provedor, *_, frame = _cena(cliente, usar_provedor_falso)
    antigo = sessao_com_tabelas.get(Frame, frame["id"])
    antigo.contexto_do_livro = "o capítulo confirma que é de manhã"
    antigo.confirmado_pela_leitura_profunda = True
    sessao_com_tabelas.commit()

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert provedor.chamadas_de_fundamentacao == []
    chamada = provedor.chamadas_de_prompt[0]
    assert chamada["contexto_do_livro"] == "o capítulo confirma que é de manhã" and "dossie" not in chamada


def teste_fl8_modelo_no_formato_antigo_no_fluxo_de_um_toque_segue_com_o_contexto(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, *_, frame = _cena(cliente, usar_provedor_falso, ProvedorFalso(prompt="x", estado=ESTADO, momentos=MOMENTOS, contexto="é no pátio"))

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201
    chamada = provedor.chamadas_de_prompt[0]
    assert chamada["contexto_do_livro"] == "é no pátio" and "dossie" not in chamada
    assert cliente.get(f"/frames/{frame['id']}/dossie").json() is None


def teste_fl9_cena_sem_elementos_le_o_dossie_so_pelo_texto_do_autor(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, _ = _cenario(cliente, usar_provedor_falso, _provedor_falso())
    cena = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "CENA", "titulo": "Só o ambiente", "descricao": "a taverna vazia"}).json()

    resposta = cliente.post(f"/frames/{cena['id']}/dossie")

    assert resposta.status_code == 200 and provedor.chamadas_de_fundamentacao[0]["participantes"] == []


# --------------------------------------------------------------------------- #
# A ficha do prompt (FL13.2)
# --------------------------------------------------------------------------- #


def teste_fl13_a_ficha_guarda_os_presentes_o_momento_usado_e_o_estado_do_dossie(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso, trecho="uma pedra lhe cortou a testa")

    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    ficha = prompt["ficha"]
    assert ficha["dossie"] == {"confirmado": False, "momento_incerto": False}
    assert [p["nome"] for p in ficha["presentes"]] == ["Maren", "o cão", "a mesa"]
    assert set(ficha["presentes"][0]) == {"nome", "tipo", "elemento", "caracteristicas", "incerto"}
    (momento,) = ficha["momentos"]
    assert (momento["elemento"], momento["indice"], momento["total"]) == ("Maren", 2, 3)
    assert momento["momento"]["estado_fisico"] == "corte na testa, sangue até o queixo"
    assert ficha["referencias"] == []


def teste_fl13_a_ficha_so_leva_o_que_a_pessoa_deixou_na_lista(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    lista = cliente.get(f"/frames/{frame['id']}/dossie").json()["presentes"]
    lista[1]["incluir"] = False
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lista})

    ficha = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["ficha"]

    assert [p["nome"] for p in ficha["presentes"]] == ["Maren", "a mesa"] and ficha["dossie"]["confirmado"] is True


def teste_fl13_a_ficha_fica_guardada_no_prompt(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Prompt, prompt["id"]).ficha == prompt["ficha"]
    assert cliente.get(f"/prompts/{prompt['id']}").json()["ficha"] == prompt["ficha"]


def teste_fl13_retrato_e_video_ficam_sem_ficha(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, capitulo, estado_id, frame = _cena(cliente, usar_provedor_falso)
    retrato = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [estado_id]}).json()

    assert cliente.post(f"/frames/{retrato['id']}/prompts", json={}).json()["ficha"] is None
    assert cliente.post(f"/frames/{frame['id']}/prompts", json={"tipo": "VIDEO"}).json()["ficha"] is None


def teste_fl13_cena_sem_dossie_tem_ficha_com_a_lista_vazia(cliente: TestClient, usar_provedor_falso) -> None:
    *_, frame = _cena(cliente, usar_provedor_falso, ProvedorFalso(prompt="x", estado=ESTADO, momentos=MOMENTOS))

    ficha = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["ficha"]

    assert ficha["dossie"] is None and ficha["presentes"] == []


def teste_fl13_a_geracao_anota_as_referencias_na_ficha() -> None:
    from imagineer.servicos.geracao_de_imagem import _anotar_referencias_na_ficha

    com_ficha = SimpleNamespace(ficha={"presentes": [], "referencias": []})
    sem_ficha = SimpleNamespace(ficha=None)

    _anotar_referencias_na_ficha(com_ficha, [4, 7])
    _anotar_referencias_na_ficha(sem_ficha, [4, 7])

    assert com_ficha.ficha == {"presentes": [], "referencias": [4, 7]}
    assert sem_ficha.ficha is None  # prompt sem ficha continua sem ficha


# --------------------------------------------------------------------------- #
# A migração
# --------------------------------------------------------------------------- #


def teste_fl8_a_migracao_adiciona_e_remove_as_tres_colunas() -> None:
    import importlib.util

    import sqlalchemy as sa
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    from testes.teste_lm_migracao_do_uso import RAIZ

    arquivo = RAIZ / "migracoes" / "versions" / "b9c0d1e2f3a5_dossie_da_cena_e_ficha_do_prompt.py"
    especificacao = importlib.util.spec_from_file_location("migracao_b9c0d1e2f3a5", arquivo)
    migracao = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(migracao)
    motor = sa.create_engine("sqlite://")
    with motor.begin() as conexao:
        conexao.execute(sa.text("CREATE TABLE frames (id INTEGER PRIMARY KEY, titulo TEXT)"))
        conexao.execute(sa.text("CREATE TABLE prompts (id INTEGER PRIMARY KEY, texto TEXT)"))
        conexao.execute(sa.text("INSERT INTO frames (titulo) VALUES ('A cena')"))
        conexao.execute(sa.text("INSERT INTO prompts (texto) VALUES ('a prompt')"))

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.aplicar()
    with motor.connect() as conexao:
        assert tuple(conexao.execute(sa.text("SELECT titulo, dossie, dossie_entrada FROM frames")).one()) == ("A cena", None, None)
        assert tuple(conexao.execute(sa.text("SELECT texto, ficha FROM prompts")).one()) == ("a prompt", None)

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.reverter()
    assert {c["name"] for c in sa.inspect(motor).get_columns("frames")} == {"id", "titulo"}
    assert {c["name"] for c in sa.inspect(motor).get_columns("prompts")} == {"id", "texto"}

    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)
    assert diretorio.get_revision("b9c0d1e2f3a5").down_revision == "a8b9c0d1e2f4" and len(diretorio.get_heads()) == 1
