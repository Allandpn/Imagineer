"""Ajustes dos marcadores achados com dados reais (30/09/2026): nome parcial, sem duplicatas."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import Capitulo, TipoElemento
from imagineer.servicos.posicao_no_texto import posicao_da_primeira_mencao
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

TEXTO = "Abertura sem ninguém.\n\nA senhora Ellanher entrou. Septimus sorriu.\n\nNo fim, Letens ardia."


def teste_nome_parcial_acha_o_pedaco_que_e_nome_proprio() -> None:
    """O texto diz "Ellanher", a IA sugeriu "Septimus Ellanher": o marcador vai para a primeira menção de qualquer pedaço."""
    assert posicao_da_primeira_mencao(TEXTO, "Septimus Ellanher") == TEXTO.index("A senhora")


def teste_vale_o_pedaco_que_aparece_primeiro_no_texto() -> None:
    texto = "Zero.\n\nSó Septimus aqui.\n\nDepois Ellanher."

    assert posicao_da_primeira_mencao(texto, "Septimus Ellanher") == texto.index("Só Septimus")


def teste_o_nome_completo_tem_prioridade_sobre_os_pedacos() -> None:
    texto = "Zero com Ellanher.\n\nMais adiante, Septimus Ellanher falou."

    assert posicao_da_primeira_mencao(texto, "Septimus Ellanher") == texto.index("Mais adiante")


def teste_so_pedacos_com_maiuscula_servem_de_reserva() -> None:
    """"anfiteatro de Letens": só "Letens" é nome próprio; "de" e "anfiteatro" não podem apontar nada."""
    assert posicao_da_primeira_mencao(TEXTO, "anfiteatro de Letens") == TEXTO.index("No fim")
    assert posicao_da_primeira_mencao("Um anfiteatro de pedra.", "anfiteatro de Letens") is None
    assert posicao_da_primeira_mencao("Nada de moedas aqui.", "moedas de prata") is None


def teste_quem_nao_aparece_no_texto_nao_tem_posicao() -> None:
    assert posicao_da_primeira_mencao(TEXTO, "Hrolf") is None


def _analisar(cliente: TestClient, usar_provedor_falso, sessao: Session, elementos):
    usar_provedor_falso(ProvedorFalso(elementos=elementos))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    c1 = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, c1).texto = TEXTO
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{c1}/sugestoes")
    return livro, c1


def teste_reanalisar_nao_recria_a_sugestao_ja_confirmada(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """Antes: a confirmada sobrevivia à reanálise e a IA a listava de novo, duplicando o cartão."""
    livro, c1 = _analisar(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        [
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Septimus Ellanher"),
            ElementoSugerido(tipo=TipoElemento.OBJETO, nome="espada"),
        ],
    )
    sugestao = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]
    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Septimus Ellanher"}
    ).json()
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": elemento["id"]})

    depois = cliente.post(f"/capitulos/{c1}/sugestoes", params={"forcar": True}).json()["elementos"]

    assert sorted(e["nome"] for e in depois) == ["Septimus Ellanher", "espada"]  # nenhum repetido
    assert next(e for e in depois if e["nome"] == "Septimus Ellanher")["id"] == sugestao["id"]  # a mesma


def teste_um_icone_por_elemento_mesmo_com_duplicatas_antigas(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """Duplicatas já existentes no banco (de reanálises antigas) não desenham o ícone duas vezes."""
    from imagineer.modelos import SugestaoDeElemento  # noqa: PLC0415

    livro, c1 = _analisar(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ellanher")],
    )
    original = sessao_com_tabelas.query(SugestaoDeElemento).filter_by(capitulo_id=c1).one()
    sessao_com_tabelas.add(
        SugestaoDeElemento(capitulo_id=c1, tipo=original.tipo, nome=original.nome, modelo=original.modelo)
    )
    sessao_com_tabelas.commit()
    assert len(cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"]) == 2  # o painel mostra as duas

    marcadores = cliente.get(f"/capitulos/{c1}/marcadores").json()["marcadores"]

    assert [m["rotulo"] for m in marcadores] == ["Ellanher"]
    assert marcadores[0]["sugestao_id"] == original.id  # fica a mais antiga
