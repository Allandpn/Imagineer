"""Onde ficam os marcadores no texto (item 3.4g) e `GET /capitulos/{id}/marcadores` (item 6.8)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import Capitulo, TipoElemento
from imagineer.servicos.posicao_no_texto import posicao_da_primeira_mencao
from testes.teste_rotas_prompts import _frame, _importar_imagem
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

# --------------------------------------------------------------------------- #
# A localização, pura
# --------------------------------------------------------------------------- #

TEXTO = "Primeiro parágrafo, sem ninguém.\n\nJon chegou ao muro.\nOutra linha do mesmo parágrafo.\n\nTerceiro, com Ned."


def teste_acha_o_inicio_do_paragrafo_da_primeira_mencao() -> None:
    assert posicao_da_primeira_mencao(TEXTO, "Jon") == TEXTO.index("Jon chegou")
    # Ned só aparece no último parágrafo: o marcador vai para o começo dele, não para o nome.
    assert posicao_da_primeira_mencao(TEXTO, "Ned") == TEXTO.index("Terceiro")


def teste_a_primeira_ocorrencia_vence_e_quebra_de_linha_simples_nao_separa_paragrafo() -> None:
    texto = "Abertura.\n\nMuro velho.\nO muro caiu. Muro.\n\nMuro de novo."

    assert posicao_da_primeira_mencao(texto, "Muro") == texto.index("Muro velho")


def teste_so_palavra_inteira() -> None:
    texto = "Ele tinha visto a Vision passar.\n\nDepois Vis chegou."

    assert posicao_da_primeira_mencao(texto, "Vis") == texto.index("Depois Vis")


def teste_sem_acento_e_sem_diferenca_de_caixa() -> None:
    texto = "Nada aqui.\n\nA Rainha ÁDRIA falou."

    assert posicao_da_primeira_mencao(texto, "Adria") == texto.index("A Rainha")


def teste_aspas_tipograficas_e_quebra_de_linha_dentro_do_nome() -> None:
    texto = "Nada.\n\nO D’Arcy chegou.\n\nEntão Hospius\nSextus saiu."

    assert posicao_da_primeira_mencao(texto, "D'Arcy") == texto.index("O D")
    assert posicao_da_primeira_mencao(texto, "Hospius Sextus") == texto.index("Então")


def teste_o_mapa_de_indices_aponta_para_o_texto_original_mesmo_com_texto_encurtado() -> None:
    """Tirar acentos e juntar quebras muda o tamanho do texto: sem o mapa, a posição sairia errada."""
    texto = ("é" * 50) + "\n\n\n\n" + ("ã" * 10) + "\n\nAqui mora Zé.\n\nFim."

    assert posicao_da_primeira_mencao(texto, "ze") == texto.index("Aqui mora")


def teste_nome_ausente_ou_vazio_nao_acha() -> None:
    assert posicao_da_primeira_mencao(TEXTO, "Arya") is None
    assert posicao_da_primeira_mencao(TEXTO, "   ") is None
    assert posicao_da_primeira_mencao(TEXTO, "") is None


def teste_a_posicao_e_em_utf16_e_nao_em_caracteres() -> None:
    """Um emoji conta 1 caractere no Python e 2 unidades UTF-16 no Kotlin."""
    texto = "Começo \U0001F600.\n\nO Muro."

    assert texto.index("O Muro") == 11  # em caracteres
    assert posicao_da_primeira_mencao(texto, "Muro") == 12  # em UTF-16: o emoji vale 2


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #


def _cenario(cliente: TestClient, usar_provedor_falso, sessao: Session, texto: str, elementos):
    usar_provedor_falso(ProvedorFalso(elementos=elementos))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo = livro["capitulos"][0]
    sessao.get(Capitulo, capitulo["id"]).texto = texto
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{capitulo['id']}/sugestoes")
    return livro, capitulo["id"]


def teste_marcadores_vem_por_posicao_e_os_sem_posicao_depois(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas, TEXTO,
        [
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Arya"),  # não aparece no texto
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned"),
            ElementoSugerido(tipo=TipoElemento.AMBIENTE, nome="muro"),
        ],
    )

    corpo = cliente.get(f"/capitulos/{c1}/marcadores").json()

    assert [(m["rotulo"], m["tipo_do_elemento"]) for m in corpo["marcadores"]] == [
        ("muro", "AMBIENTE"),  # parágrafo 2
        ("Ned", "PERSONAGEM"),  # parágrafo 3
        ("Arya", "PERSONAGEM"),  # sem posição, por último
    ]
    assert [m["posicao_no_texto"] for m in corpo["marcadores"]] == [
        TEXTO.index("Jon chegou"),
        TEXTO.index("Terceiro"),
        None,
    ]
    assert all(m["tipo"] == "ELEMENTO" and m["situacao"] == "SUGERIDO" for m in corpo["marcadores"])


def teste_funciona_em_capitulo_ja_analisado(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas, TEXTO,
        [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
    )

    resposta = cliente.get(f"/capitulos/{c1}/marcadores")

    assert resposta.status_code == 200
    assert len(resposta.json()["marcadores"]) == 1


def teste_capitulo_nunca_analisado_nao_tem_marcadores_e_nada_e_gasto(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = usar_provedor_falso(ProvedorFalso())
    livro = _livro_com_capitulos(cliente, capitulos=1)

    corpo = cliente.get(f"/capitulos/{livro['capitulos'][0]['id']}/marcadores").json()

    assert corpo == {"marcadores": []}
    assert provedor.chamadas_de_extracao == []


def teste_capitulo_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/capitulos/9999/marcadores").status_code == 404


def teste_sugestao_descartada_nao_vira_marcador(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas, TEXTO,
        [
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon"),
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned"),
        ],
    )
    jon = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]
    cliente.patch(f"/sugestoes-elemento/{jon['id']}", json={"descartada": True})

    corpo = cliente.get(f"/capitulos/{c1}/marcadores").json()

    assert [m["rotulo"] for m in corpo["marcadores"]] == ["Ned"]


def teste_situacao_acompanha_o_andamento_ate_a_imagem(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    livro, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas, TEXTO,
        [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
    )

    def marcador() -> dict:
        return cliente.get(f"/capitulos/{c1}/marcadores").json()["marcadores"][0]

    assert marcador()["situacao"] == "SUGERIDO"

    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "estado_inicial": {"capitulo_id": c1, "descricao": "manto"}},
    ).json()
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": jon["id"]})
    assert marcador()["situacao"] == "CONFIRMADO"
    assert marcador()["frame_id"] is None

    frame = _frame(cliente, c1, [jon["estados"][0]["id"]], tipo="PERSONAGEM")
    assert marcador()["frame_id"] == frame["id"]
    assert marcador()["situacao"] == "CONFIRMADO"  # há retrato, ainda sem prompt

    cliente.put("/configuracao", json={"modelo_prompt": "falso/modelo-de-teste"})
    perfil = cliente.post("/perfis-renderizacao", json={"nome": "P"}).json()
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={"perfil_renderizacao_id": perfil["id"]}).json()
    assert marcador()["situacao"] == "PROMPT_PRONTO"

    imagem = _importar_imagem(cliente, prompt["id"])
    assert marcador()["situacao"] == "ILUSTRADO"
    assert marcador()["imagem_id"] == imagem["id"]


def teste_o_rotulo_e_o_nome_do_cadastro_quando_a_sugestao_esta_casada(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    livro, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas, TEXTO,
        [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
    )
    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]
    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon Snow"}
    ).json()
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": elemento["id"]})

    (marcador,) = cliente.get(f"/capitulos/{c1}/marcadores").json()["marcadores"]

    assert marcador["rotulo"] == "Jon Snow"
    assert marcador["posicao_no_texto"] == TEXTO.index("Jon chegou")  # a posição vem do nome sugerido
