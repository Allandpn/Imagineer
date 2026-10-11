"""O cenário e a fotografia do elemento que não é pessoa (item 4.11, AF5, AF6, AF9): a leitura do estado, a herança e o retrato que deixa de ser neutro.

Nenhum teste fala com o OpenRouter: o provedor é o ``ProvedorFalso`` ou um ``MockTransport``.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, _interpretar_cenario_do_elemento
from imagineer.modelos import Capitulo, Elemento, EstadoElemento, TipoElemento
from imagineer.servicos.cenario_do_elemento import cenario_anterior_do_elemento
from testes.teste_af_cenario_da_cena import CENARIO, _campo
from testes.teste_fl_retrato_neutro import BLOCO_DO_RETRATO_NEUTRO, _retrato_de


def _provedor_openrouter(resposta: dict) -> tuple[ProvedorOpenRouter, list[dict]]:
    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(resposta)}, "finish_reason": "stop"}]})

    return ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))), pedidos


def _pedido(pedido: dict) -> tuple[str, str]:
    instrucao = pedido["messages"][0]["content"]
    usuario = pedido["messages"][1]["content"]
    if isinstance(usuario, list):
        usuario = "\n".join(bloco["text"] for bloco in usuario)
    return instrucao, usuario


RESPOSTA = {"aparencia_fixa": "de ferro", "instante": "sobre a mesa", "ambiente": None, "cenario": CENARIO}


# --------------------------------------------------------------------------- #
# A leitura do estado (AF5)
# --------------------------------------------------------------------------- #


def teste_af5_a_instrucao_pede_o_cenario_so_para_quem_nao_e_pessoa_e_manda_herdar() -> None:
    provedor, pedidos = _provedor_openrouter(RESPOSTA)
    provedor.sugerir_estado("capítulo", TipoElemento.OBJETO, "a espada", None, None, "x/m")
    instrucao, _ = _pedido(pedidos[0])

    assert "Você devolve CINCO partes" in instrucao and '5. "cenario"' in instrucao
    assert "para uma PESSOA (PERSONAGEM) ou um GRUPO devolva null" in instrucao
    assert "CENÁRIO DESTE ELEMENTO NO ESTADO ANTERIOR" in instrucao and "NUNCA invente um fato do livro" in instrucao


def teste_af5_o_cenario_anterior_e_o_fim_do_capitulo_anterior_vao_so_para_quem_le_cenario() -> None:
    provedor, pedidos = _provedor_openrouter(RESPOSTA)

    provedor.sugerir_estado("cap", TipoElemento.OBJETO, "a espada", None, None, "x/m", cenario_anterior=CENARIO, fim_do_capitulo_anterior="Chovia.")
    provedor.sugerir_estado("cap", TipoElemento.PERSONAGEM, "Maren", None, None, "x/m", cenario_anterior=CENARIO, fim_do_capitulo_anterior="Chovia.")
    objeto, pessoa = _pedido(pedidos[0])[1], _pedido(pedidos[1])[1]

    assert "CENÁRIO DESTE ELEMENTO NO ESTADO ANTERIOR" in objeto and "- Clima: chuva fina lá fora [herdado do anterior]" in objeto
    assert "FIM DO CAPÍTULO ANTERIOR" in objeto and "Chovia." in objeto
    assert "ESTADO ANTERIOR" not in pessoa and "FIM DO CAPÍTULO ANTERIOR" not in pessoa


def teste_af5_o_cenario_lido_vem_normalizado_para_objeto_e_some_para_pessoa() -> None:
    provedor, _ = _provedor_openrouter(RESPOSTA)

    objeto = provedor.sugerir_estado("cap", TipoElemento.OBJETO, "a espada", None, None, "x/m")
    pessoa = provedor.sugerir_estado("cap", TipoElemento.PERSONAGEM, "Maren", None, None, "x/m")

    assert objeto.cenario == CENARIO
    assert pessoa.cenario is None  # mesmo que o modelo o devolva, pessoa não lê cenário


@pytest.mark.parametrize("tipo", ["OBJETO", "AMBIENTE", "EDIFICACAO", "CRIATURA", "VEICULO"])
def teste_af5_estes_tipos_leem_cenario(tipo: str) -> None:
    assert _interpretar_cenario_do_elemento(json.dumps(RESPOSTA), TipoElemento[tipo]) == CENARIO


@pytest.mark.parametrize("tipo", ["PERSONAGEM", "GRUPO"])
def teste_af5_pessoa_e_grupo_nao_leem_cenario(tipo: str) -> None:
    assert _interpretar_cenario_do_elemento(json.dumps(RESPOSTA), TipoElemento[tipo]) is None


def teste_af5_resposta_sem_cenario_ou_com_cenario_nulo_deixa_nulo() -> None:
    assert _interpretar_cenario_do_elemento(json.dumps({"aparencia_fixa": "x", "instante": "y"}), TipoElemento.OBJETO) is None
    assert _interpretar_cenario_do_elemento(json.dumps({**RESPOSTA, "cenario": None}), TipoElemento.OBJETO) is None


# --------------------------------------------------------------------------- #
# A herança do estado anterior (AF5)
# --------------------------------------------------------------------------- #


def _estado(sessao: Session, elemento: Elemento, capitulo: Capitulo, cenario: dict | None) -> EstadoElemento:
    estado = EstadoElemento(elemento_id=elemento.id, capitulo_id=capitulo.id, descricao="x", cenario=cenario)
    sessao.add(estado)
    sessao.commit()
    return estado


def _tres_capitulos_e_um_objeto(cliente: TestClient, sessao: Session):
    from testes.teste_rotas_prompts import _livro

    livro = _livro(cliente)
    primeiro = sessao.get(Capitulo, livro["capitulos"][0]["id"])
    segundo = Capitulo(livro_id=livro["id"], ordem=primeiro.ordem + 1, titulo="Dois", texto="texto dois")
    terceiro = Capitulo(livro_id=livro["id"], ordem=primeiro.ordem + 2, titulo="Três", texto="texto três")
    sessao.add_all([segundo, terceiro])
    elemento = Elemento(livro_id=livro["id"], tipo=TipoElemento.OBJETO, nome="a espada")
    sessao.add(elemento)
    sessao.commit()
    return primeiro, segundo, terceiro, elemento


def teste_af5_herda_o_cenario_do_estado_mais_proximo_antes_e_ignora_os_depois(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    primeiro, segundo, terceiro, elemento = _tres_capitulos_e_um_objeto(cliente, sessao_com_tabelas)
    outro = {**CENARIO, "clima": _campo("neve")}
    _estado(sessao_com_tabelas, elemento, primeiro, CENARIO)
    _estado(sessao_com_tabelas, elemento, terceiro, outro)
    do_segundo = _estado(sessao_com_tabelas, elemento, segundo, None)

    assert cenario_anterior_do_elemento(sessao_com_tabelas, do_segundo) == CENARIO  # o do terceiro é depois: não conta


def teste_af5_pula_o_estado_anterior_que_ficou_sem_cenario(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    primeiro, segundo, terceiro, elemento = _tres_capitulos_e_um_objeto(cliente, sessao_com_tabelas)
    _estado(sessao_com_tabelas, elemento, primeiro, CENARIO)
    _estado(sessao_com_tabelas, elemento, segundo, None)
    do_terceiro = _estado(sessao_com_tabelas, elemento, terceiro, None)

    assert cenario_anterior_do_elemento(sessao_com_tabelas, do_terceiro) == CENARIO


def teste_af5_sem_estado_anterior_nao_ha_o_que_herdar(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    primeiro, _, _, elemento = _tres_capitulos_e_um_objeto(cliente, sessao_com_tabelas)
    unico = _estado(sessao_com_tabelas, elemento, primeiro, CENARIO)

    assert cenario_anterior_do_elemento(sessao_com_tabelas, unico) is None


# --------------------------------------------------------------------------- #
# O retrato (AF6)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tipo", ["CRIATURA", "OBJETO", "AMBIENTE", "EDIFICACAO", "VEICULO"])
def teste_af6_o_retrato_destes_tipos_nao_leva_o_bloco_neutro(cliente: TestClient, usar_provedor_falso, tipo: str) -> None:
    _, frame = _retrato_de(cliente, usar_provedor_falso, tipo, cenario_do_elemento=CENARIO)

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert BLOCO_DO_RETRATO_NEUTRO[TipoElemento[tipo]] not in texto
    assert "Neutral reference portrait" not in texto and "plain uniform light-gray studio background" not in texto


def teste_af6_a_ia_recebe_o_cenario_o_onde_esta_e_a_iluminacao_do_perfil(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso, "CRIATURA", cenario_do_elemento=CENARIO)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_prompt[0]
    elementos = " ".join(chamada["elementos"])
    assert "CENÁRIO E FOTOGRAFIA DESTE ELEMENTO" in elementos
    assert "- Ambiente: taverna do Corvo Torto" in elementos and "- Clima: chuva fina lá fora [herdado do anterior]" in elementos
    assert "Onde está" in elementos  # o lugar do elemento volta a valer (não é mais neutro)
    assert "luz de vela, contraste alto" in chamada["perfil_renderizacao"]  # a iluminação do perfil entra como estilo


def teste_af6_a_leitura_profunda_guarda_o_cenario_no_estado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, frame = _retrato_de(cliente, usar_provedor_falso, "OBJETO", cenario_do_elemento=CENARIO)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    sessao_com_tabelas.expire_all()
    estado = sessao_com_tabelas.query(EstadoElemento).one()
    assert estado.cenario == CENARIO
    assert cliente.get(f"/estados/{estado.id}").json()["cenario"]["clima"] == _campo("chuva fina lá fora", "anterior")


def teste_af6_o_retrato_de_pessoa_continua_neutro_e_sem_cenario(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso, "PERSONAGEM", cenario_do_elemento=CENARIO)

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert texto == f"a woman in a dark cloak {BLOCO_DO_RETRATO_NEUTRO[TipoElemento.PERSONAGEM]}"
    assert "CENÁRIO" not in " ".join(provedor.chamadas_de_prompt[0]["elementos"])
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.query(EstadoElemento).one().cenario is None


def teste_af6_com_comentario_do_usuario_nada_muda_para_quem_le_cenario(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso, "OBJETO", cenario_do_elemento=CENARIO)

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={"comentario": "sobre uma mesa de madeira"})

    assert resposta.status_code == 201
    assert "Neutral reference portrait" not in resposta.json()["texto"]
    assert provedor.chamadas_de_prompt[0]["comentario_do_usuario"] == "sobre uma mesa de madeira"


def teste_af9_a_migracao_vem_depois_da_dos_modelos_por_livro_e_e_a_unica_cabeca() -> None:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    raiz = Path(__file__).resolve().parent.parent
    configuracao = Config(str(raiz / "alembic.ini"))
    configuracao.set_main_option("script_location", str(raiz / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)

    assert diretorio.get_revision("a3b4c5d6e7f9").down_revision == "e2f3a4b5c6d8"
    assert diretorio.get_heads() == ["a3b4c5d6e7f9"]


def teste_af6_a_instrucao_abre_a_excecao_do_retrato_com_cenario() -> None:
    provedor, pedidos = _provedor_openrouter("x")
    provedor.montar_prompt("", ["x"], "estilo", "x/m")
    instrucao = _pedido(pedidos[0])[0]

    assert 'CENÁRIO E FOTOGRAFIA DESTE ELEMENTO" NÃO é neutro' in instrucao
    assert "o sistema NÃO acrescenta bloco nenhum" in instrucao
