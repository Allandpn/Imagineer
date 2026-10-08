"""O trecho do livro em que a cena acontece (FD7, item 4.5): conferido contra o capítulo, guardado no frame e entregue à IA."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import CenaSugerida, ParticipanteSugerido
from imagineer.modelos import Capitulo, Frame, SugestaoDeCena, TipoElemento
from imagineer.servicos.posicao_no_texto import LIMITE_DO_TRECHO_DA_IA, MINIMO_DO_TRECHO, trecho_literal
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _elemento_com_estado, _perfil
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

TEXTO = (
    "Abertura calma.\n\n"
    "Ned ergueu a espada diante do portão.\nO vento soprou forte sobre o pátio, e as tochas tremeram.\n\n"
    "Depois, no pátio, Jon chorou em silêncio."
)
TRECHO = "Ned ergueu a espada diante do portão. O vento soprou forte sobre o pátio, e as tochas tremeram."


# --------------------------------------------------------------------------- #
# A conferência contra o capítulo, pura
# --------------------------------------------------------------------------- #


def teste_trecho_exato_vira_o_texto_do_livro_sem_quebras_de_linha() -> None:
    citacao = "Ned ergueu a espada diante do portão.\nO vento soprou forte sobre o pátio"

    assert trecho_literal(TEXTO, citacao, 600) == "Ned ergueu a espada diante do portão. O vento soprou forte sobre o pátio"


def teste_trecho_com_acento_aspas_e_caixa_diferentes_volta_como_esta_no_livro() -> None:
    texto = "Nada.\n\nEla disse: “Não é D’Arcy”, e saiu para a chuva.\n\nFim."

    assert trecho_literal(texto, 'disse: "NAO e D\'Arcy", e saiu', 600) == "disse: “Não é D’Arcy”, e saiu"


def teste_citacao_que_nao_esta_no_capitulo_e_descartada() -> None:
    assert trecho_literal(TEXTO, "Arya correu pelo bosque inteiro, sozinha.", 600) is None
    # Nem a que começa certo e termina inventada: nunca se guarda uma frase que o autor não escreveu.
    assert trecho_literal(TEXTO, "Ned ergueu a espada diante do portão. E tudo ficou em silêncio absoluto.", 600) is None


def teste_vazia_nula_ou_curta_demais_nao_vale() -> None:
    assert trecho_literal(TEXTO, None, 600) is None
    assert trecho_literal(TEXTO, "   ", 600) is None
    assert trecho_literal(TEXTO, "Ned", 600) is None  # existe, mas não diz nada sobre a cena
    assert MINIMO_DO_TRECHO > 3


def teste_trecho_longo_e_cortado_na_ultima_palavra_com_reticencias() -> None:
    texto = "Início.\n\n" + " ".join(["palavra"] * 300) + "\n\nFim."
    citacao = " ".join(["palavra"] * 300)

    achado = trecho_literal(texto, citacao, 100)

    assert achado.endswith("palavra…") and len(achado) <= 101
    assert "  " not in achado


def teste_trecho_com_emoji_nao_quebra() -> None:
    texto = "Começo \U0001F600.\n\nO Muro caiu com um estrondo enorme."

    assert trecho_literal(texto, "O Muro caiu com um estrondo", 600) == "O Muro caiu com um estrondo"


# --------------------------------------------------------------------------- #
# A análise do capítulo
# --------------------------------------------------------------------------- #


def _cena(titulo: str, trecho: str | None) -> CenaSugerida:
    return CenaSugerida(
        titulo=titulo, participantes=[ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned")], trecho=trecho
    )


def _analisar(cliente: TestClient, usar_provedor_falso, sessao: Session, cenas) -> int:
    usar_provedor_falso(ProvedorFalso(elementos=[], cenas_sugeridas=cenas))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo = livro["capitulos"][0]
    sessao.get(Capitulo, capitulo["id"]).texto = TEXTO
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{capitulo['id']}/sugestoes")
    return capitulo["id"]


def teste_analisar_guarda_so_o_trecho_que_esta_no_capitulo(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _analisar(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        [_cena("Certa", TRECHO), _cena("Inventada", "Arya correu pelo bosque inteiro, sozinha."), _cena("Sem trecho", None)],
    )

    cenas = sessao_com_tabelas.query(SugestaoDeCena).order_by(SugestaoDeCena.id).all()

    assert [c.trecho for c in cenas] == [TRECHO, None, None]


def teste_trecho_da_ia_acima_do_limite_e_cortado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    from imagineer.modelos import Capitulo

    longo = " ".join(["palavra"] * 300)
    usar_provedor_falso(ProvedorFalso(elementos=[], cenas_sugeridas=[_cena("Longa", longo)]))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    sessao_com_tabelas.get(Capitulo, livro["capitulos"][0]["id"]).texto = "Início.\n\n" + longo
    sessao_com_tabelas.commit()
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    (cena,) = sessao_com_tabelas.query(SugestaoDeCena).all()

    assert cena.trecho.endswith("…") and len(cena.trecho) <= LIMITE_DO_TRECHO_DA_IA + 1


def teste_a_sugestao_de_cena_devolve_o_trecho(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    capitulo_id = _analisar(cliente, usar_provedor_falso, sessao_com_tabelas, [_cena("Certa", TRECHO)])

    sugestoes = cliente.get(f"/capitulos/{capitulo_id}/sugestoes").json()

    assert sugestoes["cenas"][0]["trecho"] == TRECHO


def teste_a_instrucao_da_analise_pede_o_trecho_e_o_interpretador_o_le() -> None:
    from imagineer.ia import openrouter

    assert '"trecho":' in openrouter._INSTRUCAO_DE_EXTRACAO
    cenas = openrouter._interpretar_cenas_sugeridas(
        {"cenas": [{"titulo": "A", "participantes": [{"tipo": "PERSONAGEM", "nome": "Ned"}], "trecho": "  Ned ergueu a espada.  "}]}
    )
    assert cenas[0].trecho == "Ned ergueu a espada."


# --------------------------------------------------------------------------- #
# O frame
# --------------------------------------------------------------------------- #


def _capitulo_com_texto(cliente: TestClient, sessao: Session) -> tuple[dict, int]:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, capitulo_id).texto = TEXTO
    sessao.commit()
    return livro, capitulo_id


def teste_o_frame_criado_a_partir_da_sugestao_herda_o_trecho(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    capitulo_id = _analisar(cliente, usar_provedor_falso, sessao_com_tabelas, [_cena("Certa", TRECHO)])
    sugestao = cliente.get(f"/capitulos/{capitulo_id}/sugestoes").json()["cenas"][0]
    livro_id = sessao_com_tabelas.get(Capitulo, capitulo_id).livro_id
    ned = _elemento_com_estado(cliente, livro_id, capitulo_id, "Ned")

    frame = cliente.post(
        f"/capitulos/{capitulo_id}/frames", json={"sugestao_cena_id": sugestao["id"], "estados_ids": [ned["estados"][0]["id"]]}
    ).json()

    assert frame["trecho"] == TRECHO
    assert cliente.get(f"/capitulos/{capitulo_id}/frames").json()[0]["trecho"] == TRECHO


def teste_cena_de_um_trecho_selecionado_guarda_o_trecho_como_esta_no_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo_id = _capitulo_com_texto(cliente, sessao_com_tabelas)
    ned = _elemento_com_estado(cliente, livro["id"], capitulo_id, "Ned")

    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"tipo": "CENA", "titulo": "No portão", "estados_ids": [ned["estados"][0]["id"]], "trecho": "ned ergueu a ESPADA diante do portão"},
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["trecho"] == "Ned ergueu a espada diante do portão"


def teste_trecho_que_nao_esta_no_capitulo_da_422(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo_id = _capitulo_com_texto(cliente, sessao_com_tabelas)
    ned = _elemento_com_estado(cliente, livro["id"], capitulo_id, "Ned")

    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"tipo": "CENA", "titulo": "X", "estados_ids": [ned["estados"][0]["id"]], "trecho": "Arya correu pelo bosque inteiro, sozinha."},
    )

    assert resposta.status_code == 422 and "não está no texto" in resposta.json()["detail"]


def teste_ajustar_o_trecho_confere_apaga_e_refaz_a_fundamentacao(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo_id = _capitulo_com_texto(cliente, sessao_com_tabelas)
    ned = _elemento_com_estado(cliente, livro["id"], capitulo_id, "Ned")
    frame = cliente.post(
        f"/capitulos/{capitulo_id}/frames", json={"tipo": "CENA", "titulo": "X", "estados_ids": [ned["estados"][0]["id"]]}
    ).json()
    registro = sessao_com_tabelas.get(Frame, frame["id"])
    registro.confirmado_pela_leitura_profunda = True
    sessao_com_tabelas.commit()

    assert cliente.patch(f"/frames/{frame['id']}", json={"trecho": "Arya correu pelo bosque inteiro."}).status_code == 422

    certo = cliente.patch(f"/frames/{frame['id']}", json={"trecho": "Depois, no pátio, Jon chorou"})
    assert certo.status_code == 200 and certo.json()["trecho"] == "Depois, no pátio, Jon chorou"
    sessao_com_tabelas.refresh(registro)
    assert registro.confirmado_pela_leitura_profunda is False  # o trecho mudou: a fundamentação de antes não vale

    apagado = cliente.patch(f"/frames/{frame['id']}", json={"trecho": None})
    assert apagado.status_code == 200 and apagado.json()["trecho"] is None


def teste_ajustar_outro_campo_nao_mexe_no_trecho_nem_na_fundamentacao(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo_id = _capitulo_com_texto(cliente, sessao_com_tabelas)
    ned = _elemento_com_estado(cliente, livro["id"], capitulo_id, "Ned")
    frame = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"tipo": "CENA", "titulo": "X", "estados_ids": [ned["estados"][0]["id"]], "trecho": TRECHO},
    ).json()
    registro = sessao_com_tabelas.get(Frame, frame["id"])
    registro.confirmado_pela_leitura_profunda = True
    sessao_com_tabelas.commit()

    resposta = cliente.patch(f"/frames/{frame['id']}", json={"titulo": "Outro título"})

    assert resposta.json()["trecho"] == TRECHO
    sessao_com_tabelas.refresh(registro)
    assert registro.confirmado_pela_leitura_profunda is True


def teste_a_migracao_encadeia_e_cria_a_coluna_nas_duas_tabelas() -> None:
    from pathlib import Path

    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "a7b8c9d0e1f2_trecho_da_cena.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'" in texto
    assert 'add_column("sugestoes_cena"' in texto and 'add_column("frames"' in texto


# --------------------------------------------------------------------------- #
# O que a IA recebe
# --------------------------------------------------------------------------- #


def _cena_com_trecho_pronta(cliente: TestClient, usar_provedor_falso, sessao: Session, provedor: ProvedorFalso, trecho: str | None):
    usar_provedor_falso(provedor)
    livro, capitulo_id = _capitulo_com_texto(cliente, sessao)
    ned = _elemento_com_estado(cliente, livro["id"], capitulo_id, "Ned")
    corpo = {"tipo": "CENA", "titulo": "No portão", "estados_ids": [ned["estados"][0]["id"]]}
    if trecho:
        corpo["trecho"] = trecho
    frame = cliente.post(f"/capitulos/{capitulo_id}/frames", json=corpo).json()
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    return frame


def teste_a_fundamentacao_e_a_montagem_recebem_o_trecho(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor = ProvedorFalso(prompt="p")
    frame = _cena_com_trecho_pronta(cliente, usar_provedor_falso, sessao_com_tabelas, provedor, TRECHO)

    assert cliente.post(f"/frames/{frame['id']}/prompts", json={}).status_code == 201

    assert provedor.chamadas_de_fundamentacao[0]["trecho"] == TRECHO
    assert provedor.chamadas_de_prompt[0]["trecho_do_livro"] == TRECHO


def teste_sem_trecho_o_pedido_e_o_de_antes(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor = ProvedorFalso(prompt="p")
    frame = _cena_com_trecho_pronta(cliente, usar_provedor_falso, sessao_com_tabelas, provedor, None)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert "trecho" not in provedor.chamadas_de_fundamentacao[0]
    assert "trecho_do_livro" not in provedor.chamadas_de_prompt[0]


def teste_o_pedido_a_ia_leva_o_trecho_rotulado() -> None:
    import json

    import httpx

    from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter

    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"contexto": "c"}'}}]})

    provedor = ProvedorOpenRouter(chave_api="chave", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))

    provedor.fundamentar_frame("TEXTO DO CAP", "No portão", None, None, None, None, [], "m/x", trecho=TRECHO)
    provedor.montar_prompt("cena", ["Ned: x"], "estilo", "m/x", trecho_do_livro=TRECHO)
    provedor.montar_prompt("cena", ["Ned: x"], "estilo", "m/x")

    fundamentacao, com, sem = (p["messages"][1]["content"] for p in pedidos)
    assert "TRECHO DO LIVRO EM QUE A CENA ACONTECE (literal, as palavras do autor):\n" + TRECHO in fundamentacao
    # 4.10 (LM9): o capítulo inteiro vem primeiro, para ficar em cache; o trecho, que varia a cada cena, vem depois.
    assert fundamentacao.index("TEXTO DO CAP") < fundamentacao.index("TRECHO DO LIVRO")
    assert "TRECHO DO LIVRO (o que o autor escreveu neste momento" in com and TRECHO in com
    assert "TRECHO DO LIVRO" not in sem
    sistema = pedidos[0]["messages"][0]["content"]
    assert "TRECHO DO LIVRO EM QUE A CENA ACONTECE" in sistema
    assert "não acrescente nada que ele" in " ".join(pedidos[1]["messages"][0]["content"].replace("\\\n", "").split())
