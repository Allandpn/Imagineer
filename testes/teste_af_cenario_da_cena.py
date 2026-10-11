"""O cenário e a fotografia da cena (item 4.11, AF1 a AF4, AF7 e AF8): ambiente, clima, luz, hora, atmosfera, enquadramento e lente, com herança do anterior.

Nenhum teste fala com o OpenRouter: o provedor é o ``ProvedorFalso`` ou um ``MockTransport``.
"""

import copy
import json

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.cenario import (
    TAMANHO_DO_FIM_DO_CAPITULO_ANTERIOR,
    aplicar_edicao,
    bloco_do_cenario,
    fim_do_capitulo,
    linhas_do_cenario,
    luz_e_clima_do_cenario,
    normalizar_cenario,
    onde_do_cenario,
)
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, _interpretar_dossie, texto_dos_presentes
from imagineer.modelos import Capitulo, Frame
from testes.teste_fl_dossie import DOSSIE
from testes.teste_fl_momentos import ESTADO, MOMENTOS, _cena_no_trecho, _cenario


def _campo(texto: str | None, origem: str = "texto") -> dict:
    return {"texto": texto, "origem": origem}


CENARIO = {
    "ambiente": _campo("taverna do Corvo Torto"),
    "clima": _campo("chuva fina lá fora", "anterior"),
    "iluminacao": _campo("uma vela no castiçal"),
    "hora_e_estacao": _campo("noite de inverno", "anterior"),
    "atmosfera": _campo("tons de âmbar e sombra"),
    "enquadramento": _campo("plano médio, na altura dos olhos", "sugerido"),
    "lente": _campo("50 mm, fundo desfocado", "sugerido"),
}


# --------------------------------------------------------------------------- #
# As funções puras (AF1 a AF4)
# --------------------------------------------------------------------------- #


def teste_af3_o_fim_do_capitulo_e_o_texto_inteiro_se_cabe_e_nulo_se_vazio() -> None:
    assert fim_do_capitulo("Um texto curto.\n") == "Um texto curto."
    assert fim_do_capitulo("   ") is None and fim_do_capitulo(None) is None


def teste_af3_o_fim_do_capitulo_pega_o_final_e_comeca_num_paragrafo_quando_da() -> None:
    texto = "A" * 2000 + "\n" + "B" * 1500 + "\n" + "C" * 1000

    fim = fim_do_capitulo(texto)

    assert fim.endswith("C" * 1000) and len(fim) <= TAMANHO_DO_FIM_DO_CAPITULO_ANTERIOR
    assert fim.startswith("B") and "A" not in fim  # abriu no começo de um parágrafo, não no meio de um


def teste_af1_normalizar_arruma_origem_e_aceita_texto_solto() -> None:
    cenario = normalizar_cenario(
        {
            "ambiente": {"texto": "  um pátio  ", "origem": "TEXTO"},
            "clima": "garoa",
            "iluminacao": {"texto": "luz fria", "origem": "inventada"},
            "enquadramento": {"texto": "plano aberto"},
            "lente": {"texto": None, "origem": "sugerido"},
        }
    )

    assert cenario["ambiente"] == _campo("um pátio")
    assert cenario["clima"] == _campo("garoa")
    assert cenario["iluminacao"] == _campo("luz fria")  # origem desconhecida: vale a do livro
    assert cenario["enquadramento"] == _campo("plano aberto", "sugerido")  # sem origem, a câmera é sugerida
    assert cenario["lente"] == _campo(None) and cenario["atmosfera"] == _campo(None)
    assert set(cenario) == {"ambiente", "clima", "iluminacao", "hora_e_estacao", "atmosfera", "enquadramento", "lente"}


def teste_af1_sem_nenhum_texto_ou_sem_objeto_nao_ha_cenario() -> None:
    assert normalizar_cenario(None) is None and normalizar_cenario("x") is None and normalizar_cenario({}) is None
    assert normalizar_cenario({"ambiente": {"texto": "  ", "origem": "texto"}}) is None


def teste_af4_o_onde_e_o_luz_e_clima_das_telas_antigas_saem_do_cenario() -> None:
    assert onde_do_cenario(CENARIO) == "taverna do Corvo Torto"
    assert luz_e_clima_do_cenario(CENARIO) == "chuva fina lá fora. uma vela no castiçal. noite de inverno"
    assert onde_do_cenario(None) is None and luz_e_clima_do_cenario({}) is None


def teste_af8_editar_vira_a_palavra_da_pessoa_e_o_que_ficou_igual_mantem_a_origem() -> None:
    novo = aplicar_edicao(CENARIO, {"clima": _campo("sol forte", "anterior"), "iluminacao": _campo("uma vela no castiçal", "texto")})

    assert novo["clima"] == _campo("sol forte", "texto")  # mudou: agora é dela, mesmo que o app tenha mandado "anterior"
    assert novo["hora_e_estacao"] == _campo("noite de inverno", "anterior")  # ausente: como estava
    assert novo["lente"] == CENARIO["lente"]
    assert novo["ambiente"] == CENARIO["ambiente"]


def teste_af8_texto_nulo_apaga_o_campo_e_campo_nulo_nao_mexe() -> None:
    novo = aplicar_edicao(CENARIO, {"lente": _campo(None), "ambiente": None})

    assert novo["lente"] == _campo(None)
    assert novo["ambiente"] == CENARIO["ambiente"]


def teste_af8_sem_cenario_antes_a_pessoa_escreve_do_zero() -> None:
    novo = aplicar_edicao(None, {"clima": _campo("neblina")})

    assert novo["clima"] == _campo("neblina") and novo["ambiente"] == _campo(None)
    assert aplicar_edicao(CENARIO, None) == CENARIO


def teste_af7_as_linhas_marcam_o_que_nao_veio_do_texto() -> None:
    linhas = linhas_do_cenario(CENARIO)

    assert "- Ambiente: taverna do Corvo Torto" in linhas
    assert "- Clima: chuva fina lá fora [herdado do anterior]" in linhas
    assert "- Lente e profundidade de campo: 50 mm, fundo desfocado [sugerido]" in linhas
    assert len(linhas) == 7
    assert linhas_do_cenario({**CENARIO, "lente": _campo(None)}).__len__() == 6


def teste_af7_sem_cenario_nao_ha_bloco() -> None:
    assert bloco_do_cenario(None) is None and bloco_do_cenario({}) is None
    assert bloco_do_cenario(CENARIO).startswith("CENÁRIO E FOTOGRAFIA")


# --------------------------------------------------------------------------- #
# A leitura (AF2, AF3, AF4)
# --------------------------------------------------------------------------- #


def _provedor_openrouter(resposta: dict) -> tuple[ProvedorOpenRouter, list[dict]]:
    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(resposta)}, "finish_reason": "stop"}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))
    return provedor, pedidos


def _conteudo(pedido: dict) -> tuple[str, str]:
    """A instrução e o texto do usuário (que pode vir em blocos) de um pedido ao OpenRouter."""
    instrucao = pedido["messages"][0]["content"]
    usuario = pedido["messages"][1]["content"]
    if isinstance(usuario, list):
        usuario = "\n".join(bloco["text"] for bloco in usuario)
    return instrucao, usuario


def teste_af2_a_instrucao_manda_herdar_campo_a_campo_e_sugerir_a_camera() -> None:
    provedor, pedidos = _provedor_openrouter({"presentes": [], "onde": "x"})
    provedor.fundamentar_frame("capítulo", "Cena", None, None, None, None, [], "x/m")
    instrucao, _ = _conteudo(pedidos[0])

    assert '"cenario"' in instrucao and "7 campos" in instrucao
    assert "HERDA do anterior" in instrucao and "FIM DO CAPÍTULO ANTERIOR" in instrucao
    assert "NUNCA invente um fato do livro" in instrucao and "NÃO herde quando o texto mostra uma MUDANÇA" in instrucao
    assert '"enquadramento" e "lente" NÃO existem no livro: SUGIRA' in instrucao


def teste_af3_o_fim_do_capitulo_anterior_vai_na_chamada_depois_do_resto_e_so_quando_ha() -> None:
    provedor, pedidos = _provedor_openrouter({"presentes": [], "onde": "x"})

    provedor.fundamentar_frame("capítulo atual", "Cena", None, None, None, None, [], "x/m", trecho="o trecho", fim_do_capitulo_anterior="A chuva não parava.")
    provedor.fundamentar_frame("capítulo atual", "Cena", None, None, None, None, [], "x/m", trecho="o trecho")
    com, sem = _conteudo(pedidos[0])[1], _conteudo(pedidos[1])[1]

    assert "FIM DO CAPÍTULO ANTERIOR" in com and "A chuva não parava." in com
    assert com.index("o trecho") < com.index("A chuva não parava.")  # depois do que varia (o capítulo é o prefixo em cache)
    assert "FIM DO CAPÍTULO ANTERIOR" not in sem


def teste_af4_o_interpretador_guarda_o_cenario_e_completa_onde_e_luz_e_clima() -> None:
    resposta = {"presentes": [], "acao": "espera", "cenario": CENARIO}

    contexto, dossie = _interpretar_dossie(json.dumps(resposta))

    assert dossie["cenario"] == CENARIO
    assert dossie["onde"] == "taverna do Corvo Torto"
    assert dossie["luz_e_clima"] == "chuva fina lá fora. uma vela no castiçal. noite de inverno"
    assert contexto == f"Onde: {dossie['onde']}\nLuz e clima: {dossie['luz_e_clima']}\nAção: espera"


def teste_af4_o_onde_e_o_luz_e_clima_que_a_ia_deu_nao_sao_trocados_pelo_cenario() -> None:
    _, dossie = _interpretar_dossie(json.dumps({"presentes": [], "onde": "o salão", "luz_e_clima": "tochas", "cenario": CENARIO}))

    assert dossie["onde"] == "o salão" and dossie["luz_e_clima"] == "tochas"


def teste_af4_dossie_sem_cenario_continua_como_antes() -> None:
    _, dossie = _interpretar_dossie(json.dumps({"presentes": [], "onde": "o salão"}))

    assert "cenario" not in dossie


def teste_af7_o_cenario_entra_na_lista_que_a_montagem_recebe() -> None:
    texto = texto_dos_presentes({**copy.deepcopy(DOSSIE), "cenario": CENARIO})

    assert "CENÁRIO E FOTOGRAFIA" in texto and "- Clima: chuva fina lá fora [herdado do anterior]" in texto
    assert "CENÁRIO E FOTOGRAFIA" not in texto_dos_presentes(DOSSIE)


# --------------------------------------------------------------------------- #
# As rotas (AF3, AF4, AF8)
# --------------------------------------------------------------------------- #

DOSSIE_COM_CENARIO = {**DOSSIE, "cenario": CENARIO}


def _cena_no_segundo_capitulo(cliente: TestClient, usar_provedor_falso, sessao: Session, texto_anterior: str | None = "Chovia sem parar sobre a estrada."):
    """Um livro com um capítulo anterior (o do EPUB) e a cena num segundo capítulo, criado direto no banco."""
    provedor = ProvedorFalso(prompt="two figures", estado=ESTADO, momentos=MOMENTOS, dossie=copy.deepcopy(DOSSIE_COM_CENARIO))
    provedor, livro, primeiro, estado_id = _cenario(cliente, usar_provedor_falso, provedor)
    if texto_anterior is not None:
        sessao.get(Capitulo, primeiro["id"]).texto = texto_anterior
    segundo = Capitulo(livro_id=livro["id"], ordem=sessao.get(Capitulo, primeiro["id"]).ordem + 1, titulo="Dois", texto="A taverna estava cheia. " * 10)
    sessao.add(segundo)
    sessao.commit()
    frame = cliente.post(f"/capitulos/{segundo.id}/frames", json={"tipo": "CENA", "titulo": "A cena", "estados_ids": [estado_id]})
    assert frame.status_code == 201, frame.text
    return provedor, livro, primeiro, segundo, frame.json()


def teste_af4_o_dossie_lido_traz_o_cenario_com_as_origens(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)

    corpo = cliente.post(f"/frames/{frame['id']}/dossie").json()

    assert corpo["cenario"]["clima"] == _campo("chuva fina lá fora", "anterior")
    assert corpo["cenario"]["lente"] == _campo("50 mm, fundo desfocado", "sugerido")
    assert cliente.get(f"/frames/{frame['id']}/dossie").json()["cenario"] == corpo["cenario"]


def teste_af3_a_leitura_recebe_o_fim_do_capitulo_anterior(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor, *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)

    cliente.post(f"/frames/{frame['id']}/dossie")

    assert provedor.chamadas_de_fundamentacao[-1]["fim_do_capitulo_anterior"] == "Chovia sem parar sobre a estrada."


def teste_af3_o_primeiro_capitulo_nao_tem_anterior(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, capitulo, estado_id = _cenario(cliente, usar_provedor_falso, ProvedorFalso(prompt="x", estado=ESTADO, momentos=MOMENTOS, dossie=copy.deepcopy(DOSSIE)))
    frame = _cena_no_trecho(cliente, capitulo["id"], estado_id, None)

    cliente.post(f"/frames/{frame['id']}/dossie")

    assert "fim_do_capitulo_anterior" not in provedor.chamadas_de_fundamentacao[-1]


def teste_af3_capitulo_ignorado_nao_e_o_anterior(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor, livro, primeiro, segundo, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)
    sessao_com_tabelas.get(Capitulo, primeiro["id"]).ignorado = True
    sessao_com_tabelas.commit()

    cliente.post(f"/frames/{frame['id']}/dossie")

    assert "fim_do_capitulo_anterior" not in provedor.chamadas_de_fundamentacao[-1]


def teste_af8_confirmar_com_cenario_edita_so_o_que_veio_e_o_editado_vira_a_palavra_da_pessoa(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)
    lido = cliente.post(f"/frames/{frame['id']}/dossie").json()

    resposta = cliente.put(
        f"/frames/{frame['id']}/dossie",
        json={"presentes": lido["presentes"], "cenario": {"clima": {"texto": "sol de rachar", "origem": "anterior"}, "lente": {"texto": "85 mm"}}},
    )

    assert resposta.status_code == 200, resposta.text
    cenario = resposta.json()["cenario"]
    assert cenario["clima"] == _campo("sol de rachar", "texto")
    assert cenario["lente"] == _campo("85 mm", "texto")
    assert cenario["ambiente"] == _campo("taverna do Corvo Torto")  # não veio: como estava
    assert cenario["hora_e_estacao"] == _campo("noite de inverno", "anterior")
    # O luz_e_clima das telas antigas acompanha o cenário editado.
    assert resposta.json()["luz_e_clima"] == "sol de rachar. uma vela no castiçal. noite de inverno"
    sessao_com_tabelas.expire_all()
    assert "Luz e clima: sol de rachar" in sessao_com_tabelas.get(Frame, frame["id"]).contexto_do_livro


def teste_af8_confirmar_sem_cenario_nao_apaga_o_que_estava(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)
    lido = cliente.post(f"/frames/{frame['id']}/dossie").json()

    resposta = cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lido["presentes"], "acao": "outra ação"})

    assert resposta.json()["cenario"] == lido["cenario"] and resposta.json()["acao"] == "outra ação"


def teste_af8_o_luz_e_clima_que_a_pessoa_mandou_vale_mais_que_o_do_cenario(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)
    lido = cliente.post(f"/frames/{frame['id']}/dossie").json()

    resposta = cliente.put(
        f"/frames/{frame['id']}/dossie",
        json={"presentes": lido["presentes"], "luz_e_clima": "escuridão total", "cenario": {"clima": {"texto": "sol"}}},
    )

    assert resposta.json()["luz_e_clima"] == "escuridão total"


def teste_af8_campo_desconhecido_no_cenario_e_recusado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)

    resposta = cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": [], "cenario": {"cor_do_ceu": {"texto": "azul"}}})

    assert resposta.status_code == 422


def teste_af7_o_prompt_da_cena_leva_o_cenario_do_dossie_confirmado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor, *_, frame = _cena_no_segundo_capitulo(cliente, usar_provedor_falso, sessao_com_tabelas)
    lido = cliente.post(f"/frames/{frame['id']}/dossie").json()
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lido["presentes"], "cenario": {"clima": {"texto": "neblina densa"}}})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    enviado = provedor.chamadas_de_prompt[-1]["dossie"]
    assert enviado["cenario"]["clima"] == _campo("neblina densa", "texto")
