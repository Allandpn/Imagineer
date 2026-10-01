"""Duas decisões pequenas da análise (item 6.7): sinalizar o que não está no texto e uma análise por vez."""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import Capitulo, TipoElemento
from imagineer.servicos.trava_de_analise import AnaliseEmAndamento, analise_exclusiva
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos

TEXTO = "Abertura calma.\n\nNed ergueu a espada.\n\nDepois Jon chorou."


def _cenario(cliente: TestClient, usar_provedor_falso, sessao: Session, elementos):
    provedor = usar_provedor_falso(ProvedorFalso(elementos=elementos))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, capitulo_id).texto = TEXTO
    sessao.commit()
    _escolher_modelo_de_extracao(cliente)
    return provedor, capitulo_id


# --------------------------------------------------------------------------- #
# achado_no_texto
# --------------------------------------------------------------------------- #


def teste_sugestao_cujo_nome_nao_esta_no_texto_vem_sinalizada_e_nao_apagada(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas,
        [
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned"),
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Daenerys"),  # não está no capítulo
            ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ned Stark"),  # o texto só diz "Ned": pedaço de nome próprio
        ],
    )

    elementos = cliente.post(f"/capitulos/{c1}/sugestoes").json()["elementos"]

    assert {e["nome"]: e["achado_no_texto"] for e in elementos} == {
        "Ned": True, "Daenerys": False, "Ned Stark": True,
    }
    assert len(elementos) == 3  # nenhuma foi apagada


def teste_achado_no_texto_tambem_vale_na_leitura_sem_ia(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    provedor, c1 = _cenario(
        cliente, usar_provedor_falso, sessao_com_tabelas, [ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Daenerys")]
    )
    cliente.post(f"/capitulos/{c1}/sugestoes")

    lido = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"][0]

    assert lido["achado_no_texto"] is False
    assert len(provedor.chamadas_de_extracao) == 1


# --------------------------------------------------------------------------- #
# Uma análise por capítulo de cada vez
# --------------------------------------------------------------------------- #


def teste_a_trava_recusa_a_segunda_reserva_e_libera_ao_sair() -> None:
    with analise_exclusiva(10):
        with pytest.raises(AnaliseEmAndamento):
            with analise_exclusiva(10):
                pass
        with analise_exclusiva(11):  # outro capítulo não é barrado
            pass

    with analise_exclusiva(10):  # liberou
        pass


def teste_a_trava_e_liberada_mesmo_quando_a_analise_falha() -> None:
    """Uma IA que dá erro não pode deixar o capítulo travado para sempre."""
    with pytest.raises(RuntimeError):
        with analise_exclusiva(20):
            raise RuntimeError("a IA caiu")

    with analise_exclusiva(20):
        pass


def teste_segunda_analise_do_mesmo_capitulo_recebe_409_sem_gastar_ia(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    provedor, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [])

    with analise_exclusiva(c1):  # uma análise "em andamento"
        resposta = cliente.post(f"/capitulos/{c1}/sugestoes")

    assert resposta.status_code == 409
    assert "em andamento" in resposta.json()["detail"]
    assert provedor.chamadas_de_extracao == []  # a recusada não gastou IA


def teste_leitura_nao_e_barrada_por_uma_analise_em_andamento(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [])

    with analise_exclusiva(c1):
        lida = cliente.get(f"/capitulos/{c1}/sugestoes")

    assert lida.status_code == 200


def teste_post_servido_do_salvo_nao_e_barrado_pela_trava(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """A trava só vale para quem vai rodar a IA: o POST que devolve o já salvo passa."""
    _, c1 = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas, [])
    cliente.post(f"/capitulos/{c1}/sugestoes")  # já analisado

    with analise_exclusiva(c1):
        servido = cliente.post(f"/capitulos/{c1}/sugestoes")

    assert servido.status_code == 200


def teste_analise_que_falha_na_ia_nao_deixa_o_capitulo_travado(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    from imagineer.ia.provedor import ErroDoProvedorIA

    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("a IA caiu")))
    livro = _livro_com_capitulos(cliente, capitulos=1)
    c1 = livro["capitulos"][0]["id"]
    _escolher_modelo_de_extracao(cliente)

    falhou = cliente.post(f"/capitulos/{c1}/sugestoes")
    de_novo = cliente.post(f"/capitulos/{c1}/sugestoes")

    assert falhou.status_code == 502
    assert de_novo.status_code == 502  # tentou de novo (e falhou de novo), em vez de 409 "em andamento"


def teste_duas_analises_de_verdade_ao_mesmo_tempo_so_uma_roda(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """A primeira fica presa dentro da IA; a segunda, que chega nesse meio-tempo, é recusada."""
    dentro_da_ia = threading.Event()
    liberar = threading.Event()

    class ProvedorLento(ProvedorFalso):
        def extrair_elementos(self, *args, **kwargs):
            dentro_da_ia.set()
            liberar.wait(timeout=10)
            return super().extrair_elementos(*args, **kwargs)

    provedor = usar_provedor_falso(ProvedorLento())
    livro = _livro_com_capitulos(cliente, capitulos=1)
    c1 = livro["capitulos"][0]["id"]
    _escolher_modelo_de_extracao(cliente)

    primeira: dict = {}
    fio = threading.Thread(target=lambda: primeira.update(r=cliente.post(f"/capitulos/{c1}/sugestoes")))
    fio.start()
    assert dentro_da_ia.wait(timeout=10)

    segunda = cliente.post(f"/capitulos/{c1}/sugestoes")
    liberar.set()
    fio.join(timeout=10)

    assert segunda.status_code == 409
    assert primeira["r"].status_code == 200
    assert len(provedor.chamadas_de_extracao) == 1  # uma só chamada à IA
