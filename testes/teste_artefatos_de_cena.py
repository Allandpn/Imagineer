"""Os artefatos de cena (item 3.4g, 6.8): a posição vem da citação da IA, gravada ao analisar."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import CenaSugerida, ElementoSugerido, ParticipanteSugerido
from imagineer.modelos import Capitulo, SugestaoDeCena, TipoElemento
from imagineer.servicos.posicao_no_texto import posicao_da_citacao
from testes.teste_rotas_prompts import _importar_imagem
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

# --------------------------------------------------------------------------- #
# A localização pela citação, pura
# --------------------------------------------------------------------------- #

TEXTO = "Abertura calma.\n\nNed ergueu a espada.\nO vento soprou forte.\n\nDepois, no pátio, Jon chorou."


def teste_citacao_exata_aponta_o_inicio_do_paragrafo() -> None:
    assert posicao_da_citacao(TEXTO, "O vento soprou") == TEXTO.index("Ned ergueu")
    assert posicao_da_citacao(TEXTO, "no pátio, Jon") == TEXTO.index("Depois")


def teste_citacao_com_acento_aspas_e_caixa_diferentes_ainda_acha() -> None:
    texto = "Nada.\n\nEla disse: “Não é D’Arcy”, e saiu.\n\nFim."

    assert posicao_da_citacao(texto, 'disse: "NAO e D\'Arcy"') == texto.index("Ela disse")


def teste_citacao_que_a_ia_completou_de_cabeca_acha_pelas_primeiras_palavras() -> None:
    citacao = "Ned ergueu a espada. E então tudo ficou em silêncio absoluto."  # o fim não está no texto

    assert posicao_da_citacao(TEXTO, citacao) == TEXTO.index("Ned ergueu")


def teste_citacao_ausente_vazia_ou_nula_nao_acha() -> None:
    assert posicao_da_citacao(TEXTO, "Arya correu pelo bosque inteiro.") is None
    assert posicao_da_citacao(TEXTO, "   ") is None
    assert posicao_da_citacao(TEXTO, "") is None
    assert posicao_da_citacao(TEXTO, None) is None


def teste_citacao_nao_e_por_palavra_inteira() -> None:
    """Diferente do nome: um trecho pode começar no meio de uma palavra."""
    assert posicao_da_citacao(TEXTO, "gueu a espada") == TEXTO.index("Ned ergueu")


def teste_citacao_em_utf16_depois_de_um_emoji() -> None:
    texto = "Começo \U0001F600.\n\nO Muro caiu."

    assert posicao_da_citacao(texto, "Muro caiu") == 12  # o emoji vale 2 em UTF-16


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #

NED = ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned")


def _cena(titulo: str, trecho: str | None) -> CenaSugerida:
    return CenaSugerida(titulo=titulo, participantes=[NED], trecho_ancora=trecho)


def _cenario(cliente: TestClient, usar_provedor_falso, sessao: Session, cenas, elementos=None):
    usar_provedor_falso(ProvedorFalso(elementos=elementos or [], cenas_sugeridas=cenas))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo = livro["capitulos"][0]
    sessao.get(Capitulo, capitulo["id"]).texto = TEXTO
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{capitulo['id']}/sugestoes")
    return livro, capitulo["id"]


def _artefatos(cliente: TestClient, capitulo_id: int) -> list[dict]:
    return cliente.get(f"/capitulos/{capitulo_id}/artefatos").json()["artefatos"]


def teste_analisar_grava_a_citacao_e_a_posicao_da_cena(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        [_cena("A espada", "O vento soprou"), _cena("Sem citação", None), _cena("Inventada", "Arya no bosque")],
    )

    cenas = sessao_com_tabelas.query(SugestaoDeCena).order_by(SugestaoDeCena.id).all()

    assert [(c.trecho_ancora, c.posicao_no_texto) for c in cenas] == [
        ("O vento soprou", TEXTO.index("Ned ergueu")),
        (None, None),
        ("Arya no bosque", None),
    ]


def teste_citacao_longa_demais_e_cortada_sem_derrubar_a_analise(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [_cena("Longa", "Ned ergueu a espada. " + "x" * 500)])

    (cena,) = sessao_com_tabelas.query(SugestaoDeCena).all()

    assert len(cena.trecho_ancora) == 300
    assert cena.posicao_no_texto == TEXTO.index("Ned ergueu")  # achada pelas primeiras palavras


def teste_cena_vira_artefato_misturada_com_elemento_e_por_posicao(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        [_cena("Choro no pátio", "Jon chorou"), _cena("Sem posição", None)],
        elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned")],
    )

    artefatos = _artefatos(cliente, c1)

    assert [(m["tipo"], m["rotulo"], m["posicao_no_texto"]) for m in artefatos] == [
        ("ELEMENTO", "Ned", TEXTO.index("Ned ergueu")),
        ("CENA", "Choro no pátio", TEXTO.index("Depois")),
        ("CENA", "Sem posição", None),  # sem posição vem depois
    ]
    cena = artefatos[1]
    assert cena["tipo_do_elemento"] is None
    assert cena["situacao"] == "SUGERIDO"
    assert cena["frame_id"] is None and cena["imagem_id"] is None


def teste_cena_descartada_nao_vira_artefato(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [_cena("A", "Jon chorou"), _cena("B", "Ned")])
    primeira = cliente.get(f"/capitulos/{c1}/sugestoes").json()["cenas"][0]
    cliente.patch(f"/sugestoes-cena/{primeira['id']}", json={"descartada": True})

    assert [m["rotulo"] for m in _artefatos(cliente, c1)] == ["B"]


def teste_situacao_da_cena_acompanha_o_andamento_ate_a_imagem(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [_cena("A espada", "Ned ergueu")])
    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["cenas"][0]
    assert _artefatos(cliente, c1)[0]["situacao"] == "SUGERIDO"

    frame = cliente.post(f"/capitulos/{c1}/frames", json={"sugestao_cena_id": sugestao["id"]})
    assert frame.status_code == 201, frame.text
    frame = frame.json()
    artefato = _artefatos(cliente, c1)[0]
    assert (artefato["situacao"], artefato["frame_id"]) == ("CONFIRMADO", frame["id"])
    assert artefato["posicao_no_texto"] == TEXTO.index("Ned ergueu")  # a posição sobrevive à confirmação

    cliente.put("/configuracao", json={"modelo_prompt": "falso/modelo-de-teste"})
    perfil = cliente.post("/perfis-renderizacao", json={"nome": "P"}).json()
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={"perfil_renderizacao_id": perfil["id"]}).json()
    assert _artefatos(cliente, c1)[0]["situacao"] == "PROMPT_PRONTO"

    imagem = _importar_imagem(cliente, prompt["id"])
    artefato = _artefatos(cliente, c1)[0]
    assert (artefato["situacao"], artefato["imagem_id"]) == ("ILUSTRADO", imagem["id"])


def teste_cena_analisada_antes_da_coluna_fica_sem_posicao_mas_continua_valendo(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """D5: sem citação gravada, a cena segue como artefato sem posição — nada é reanalisado sozinho."""
    provedor = ProvedorFalso(cenas_sugeridas=[_cena("Antiga", None)])
    usar_provedor_falso(provedor)
    livro = _livro_com_capitulos(cliente, capitulos=1)
    c1 = livro["capitulos"][0]["id"]
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{c1}/sugestoes")

    (artefato,) = _artefatos(cliente, c1)

    assert (artefato["rotulo"], artefato["posicao_no_texto"]) == ("Antiga", None)
    assert len(provedor.chamadas_de_extracao) == 1  # ler os artefatos não chamou a IA
