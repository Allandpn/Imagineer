"""Descartar sugestões, desfazer o casamento de verdade e mostrar com quem a sugestão foi casada
(itens 6.8 e 7.5b, correções achadas testando o incremento 10a no tablet, 30/09/2026)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import CenaSugerida, ElementoSugerido
from imagineer.modelos import Frame, SugestaoDeCena, TipoDeFrame, TipoElemento
from testes.teste_rotas_sugestoes import (  # noqa: F401
    _escolher_modelo_de_extracao,
    _livro_com_capitulos,
)


def _jon() -> ElementoSugerido:
    return ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon", descricao="Um bastardo.")


def _cenario(cliente: TestClient, usar_provedor_falso, cenas=None, elementos=None):
    """Livro de 3 capítulos; o provedor sugere Jon (e o que vier) em qualquer capítulo."""
    provedor = usar_provedor_falso(
        ProvedorFalso(elementos=elementos if elementos is not None else [_jon()], cenas_sugeridas=cenas)
    )
    livro = _livro_com_capitulos(cliente, capitulos=3)
    _escolher_modelo_de_extracao(cliente)
    return provedor, livro, [c["id"] for c in livro["capitulos"]]


def _analisar(cliente: TestClient, capitulo_id: int, forcar: bool = False) -> dict:
    resposta = cliente.post(f"/capitulos/{capitulo_id}/sugestoes", params={"forcar": forcar})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _pendentes_do_livro(cliente: TestClient, livro_id: int) -> list[int]:
    return [c["sugestoes_pendentes"] for c in cliente.get(f"/livros/{livro_id}").json()["capitulos"]]


# --------------------------------------------------------------------------- #
# Descartar elemento
# --------------------------------------------------------------------------- #


def teste_descartar_tira_a_sugestao_das_pendentes(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, (c1, c2, _c3) = _cenario(cliente, usar_provedor_falso)
    sugestao = _analisar(cliente, c1)["elementos"][0]
    assert _pendentes_do_livro(cliente, livro["id"])[0] == 1

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"descartada": True})

    assert resposta.status_code == 200
    assert resposta.json()["descartada"] is True
    assert _pendentes_do_livro(cliente, livro["id"])[0] == 0
    # E a contagem de "pendentes em capítulos anteriores" do capítulo seguinte também cai.
    _analisar(cliente, c2)
    assert cliente.get(f"/capitulos/{c2}/sugestoes").json()["sugestoes_pendentes_anteriores"] == 0


def teste_a_sugestao_descartada_continua_na_lista_marcada(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O app mostra as descartadas numa lista à parte, com "Restaurar"."""
    _, _, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    sugestao = _analisar(cliente, c1)["elementos"][0]
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"descartada": True})

    (lida,) = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"]

    assert lida["id"] == sugestao["id"]
    assert lida["descartada"] is True


def teste_restaurar_volta_a_ser_pendente(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    sugestao = _analisar(cliente, c1)["elementos"][0]
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"descartada": True})

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"descartada": False})

    assert resposta.json()["descartada"] is False
    assert _pendentes_do_livro(cliente, livro["id"])[0] == 1


def teste_nao_se_descarta_uma_sugestao_ligada_a_um_elemento(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    jon = cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}).json()
    sugestao = _analisar(cliente, c1)["elementos"][0]
    assert sugestao["elemento_id"] == jon["id"]  # casou sozinha

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"descartada": True})

    assert resposta.status_code == 409
    assert "Desfaça o casamento" in resposta.json()["detail"]


def teste_o_corpo_do_patch_precisa_de_uma_coisa_so(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    sugestao = _analisar(cliente, c1)["elementos"][0]

    vazio = cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={})
    os_dois = cliente.patch(
        f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": None, "descartada": True}
    )

    assert vazio.status_code == 422
    assert os_dois.status_code == 422


def teste_reanalise_nao_traz_de_volta_a_descartada_nem_a_recria(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, _, (c1, *_resto) = _cenario(
        cliente,
        usar_provedor_falso,
        elementos=[_jon(), ElementoSugerido(tipo=TipoElemento.OBJETO, nome="Espada")],
    )
    antes = _analisar(cliente, c1)["elementos"]
    jon = next(e for e in antes if e["nome"] == "Jon")
    cliente.patch(f"/sugestoes-elemento/{jon['id']}", json={"descartada": True})

    depois = _analisar(cliente, c1, forcar=True)["elementos"]

    jons = [e for e in depois if e["nome"] == "Jon"]
    assert len(jons) == 1  # não foi recriada...
    assert jons[0]["id"] == jon["id"] and jons[0]["descartada"] is True  # ...e continua descartada
    assert len([e for e in depois if e["nome"] == "Espada"]) == 1  # a não descartada foi refeita


def teste_sugestao_descartada_nao_e_casada_automaticamente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    jon = _analisar(cliente, c1)["elementos"][0]
    cliente.patch(f"/sugestoes-elemento/{jon['id']}", json={"descartada": True})

    cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"})
    (lida,) = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"]

    assert lida["elemento_id"] is None


# --------------------------------------------------------------------------- #
# Descartar cena
# --------------------------------------------------------------------------- #


def _cena(titulo: str = "A chegada") -> CenaSugerida:
    return CenaSugerida(titulo=titulo, descricao="Jon chega.", participantes=[_jon()])


def teste_descartar_cena_tira_das_pendentes_e_sobrevive_a_reanalise(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso, cenas=[_cena()])
    cena = _analisar(cliente, c1)["cenas"][0]
    # 1 elemento + 1 cena pendentes
    assert _pendentes_do_livro(cliente, livro["id"])[0] == 2

    resposta = cliente.patch(f"/sugestoes-cena/{cena['id']}", json={"descartada": True})

    assert resposta.status_code == 200 and resposta.json()["descartada"] is True
    assert _pendentes_do_livro(cliente, livro["id"])[0] == 1
    depois = _analisar(cliente, c1, forcar=True)["cenas"]
    assert [c["id"] for c in depois] == [cena["id"]]  # a mesma, não recriada
    assert depois[0]["descartada"] is True


def teste_cena_que_virou_frame_nao_se_descarta(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, _, (c1, *_resto) = _cenario(cliente, usar_provedor_falso, cenas=[_cena()])
    cena = _analisar(cliente, c1)["cenas"][0]
    frame = Frame(capitulo_id=c1, tipo=TipoDeFrame.CENA, titulo="A chegada")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()
    linha = sessao_com_tabelas.get(SugestaoDeCena, cena["id"])
    linha.frame_id = frame.id
    sessao_com_tabelas.commit()

    resposta = cliente.patch(f"/sugestoes-cena/{cena['id']}", json={"descartada": True})

    assert resposta.status_code == 409


def teste_descartar_cena_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.patch("/sugestoes-cena/9999", json={"descartada": True}).status_code == 404


# --------------------------------------------------------------------------- #
# Desfazer o casamento de verdade
# --------------------------------------------------------------------------- #


def teste_desfazer_o_casamento_nao_e_religado_sozinho(cliente: TestClient, usar_provedor_falso) -> None:
    """Antes: o casamento automático rodava a cada leitura e religava a sugestão ao mesmo
    elemento logo depois do "Desfazer"."""
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    jon = cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}).json()
    sugestao = _analisar(cliente, c1)["elementos"][0]
    assert sugestao["elemento_id"] == jon["id"]

    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": None})
    (lida,) = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"]
    outra_vez = _analisar(cliente, c1)["elementos"][0]

    assert lida["elemento_id"] is None
    assert outra_vez["elemento_id"] is None


def teste_ligar_de_novo_depois_de_desfazer_funciona(cliente: TestClient, usar_provedor_falso) -> None:
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    jon = cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}).json()
    sugestao = _analisar(cliente, c1)["elementos"][0]
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": None})

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": jon["id"]})

    assert resposta.json()["elemento_id"] == jon["id"]
    assert resposta.json()["casamento_automatico"] is False


def teste_desfazer_tambem_pode_ser_descartado_depois(cliente: TestClient, usar_provedor_falso) -> None:
    """O fluxo do app: Desfazer e, se não serve, Descartar."""
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"})
    sugestao = _analisar(cliente, c1)["elementos"][0]
    cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"elemento_id": None})

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao['id']}", json={"descartada": True})

    assert resposta.status_code == 200
    assert _pendentes_do_livro(cliente, livro["id"])[0] == 0


# --------------------------------------------------------------------------- #
# Com quem a sugestão foi casada, e o estado que vale no capítulo
# --------------------------------------------------------------------------- #


def teste_sugestao_casada_traz_o_elemento_a_identidade_e_o_estado_vigente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O cartão do capítulo 3 mostra o estado do capítulo 1 **como tal** (vigente, de outro
    capítulo), e não como se fosse deste."""
    _, livro, (c1, _c2, c3) = _cenario(cliente, usar_provedor_falso)
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "descricao": "Bastardo de Winterfell.",
            "estado_inicial": {"capitulo_id": c1, "descricao": "manto preto"},
        },
    ).json()

    (sugestao,) = _analisar(cliente, c3)["elementos"]

    assert sugestao["elemento_casado"] == {
        "id": jon["id"],
        "tipo": "PERSONAGEM",
        "nome": "Jon",
        "identidade": "Bastardo de Winterfell.",
    }
    assert sugestao["estado_id"] is None  # não há estado DESTE capítulo
    vigente = sugestao["estado_vigente"]
    assert (vigente["capitulo_id"], vigente["ordem_do_capitulo"], vigente["descricao"]) == (c1, 1, "manto preto")


def teste_sugestao_sem_elemento_nao_traz_casado_nem_estado(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, _, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)

    (sugestao,) = _analisar(cliente, c1)["elementos"]

    assert sugestao["elemento_casado"] is None
    assert sugestao["estado_vigente"] is None


def teste_elemento_casado_ainda_sem_nenhum_estado_tem_estado_vigente_nulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, livro, (c1, *_resto) = _cenario(cliente, usar_provedor_falso)
    cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"})

    (sugestao,) = _analisar(cliente, c1)["elementos"]

    assert sugestao["elemento_casado"]["nome"] == "Jon"
    assert sugestao["estado_vigente"] is None


# --------------------------------------------------------------------------- #
# O que a IA recebe
# --------------------------------------------------------------------------- #


def teste_a_ia_recebe_a_identidade_vigente_ate_o_capitulo_anterior_e_nunca_o_estado(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, livro, (c1, c2, c3) = _cenario(cliente, usar_provedor_falso, elementos=[])
    cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "descricao": "Bastardo.",
            "estado_inicial": {"capitulo_id": c1, "descricao": "manto preto"},
        },
    )
    cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "AMBIENTE", "nome": "Muralha"},  # sem identidade
    )

    _analisar(cliente, c3)

    (chamada,) = provedor.chamadas_de_extracao
    assert chamada["elementos_conhecidos"] == ["Jon (PERSONAGEM): Bastardo.", "Muralha (AMBIENTE)"]
    assert chamada["modelo"] == MODELO_FALSO


def teste_detalhe_do_elemento_traz_a_ordem_do_capitulo_de_cada_estado(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O app mostra o histórico como "capítulo 1: ..." sem precisar cruzar com a lista do livro."""
    _, livro, (c1, _c2, c3) = _cenario(cliente, usar_provedor_falso)
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "estado_inicial": {"capitulo_id": c3, "descricao": "manto"}},
    ).json()

    detalhe = cliente.get(f"/elementos/{jon['id']}").json()

    assert [e["ordem_do_capitulo"] for e in detalhe["estados"]] == [3]


# --------------------------------------------------------------------------- #
# Limites de tamanho e título do capítulo (item 7.5b, rodada 3)
# --------------------------------------------------------------------------- #

from imagineer.servicos.identidade_de_elemento import resumir_texto  # noqa: E402


def teste_resumir_texto_corta_na_ultima_palavra_inteira_e_termina_em_reticencias() -> None:
    texto = "uma frase com várias palavras para cortar no meio de algum lugar"

    resumo = resumir_texto(texto, 30)

    assert resumo == "uma frase com várias palavras…"
    assert len(resumo) <= 31


def teste_resumir_texto_nao_mexe_no_que_cabe_e_trata_vazio() -> None:
    assert resumir_texto("curto", 30) == "curto"
    assert resumir_texto("  espaços   repetidos\ne quebra ", 50) == "espaços repetidos e quebra"
    assert resumir_texto(None, 30) is None
    assert resumir_texto("", 30) is None


def teste_resumir_texto_sem_espaco_corta_seco() -> None:
    assert resumir_texto("a" * 100, 10) == "a" * 10 + "…"


def teste_a_identidade_da_sugestao_vem_resumida_e_a_ficha_traz_inteira(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, livro, (c1, _c2, c3) = _cenario(cliente, usar_provedor_falso)
    longa = "Bastardo de Winterfell que vigia a Muralha. " * 40  # ~1.800 caracteres
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "descricao": longa, "estado_inicial": {"capitulo_id": c1, "descricao": "x"}},
    ).json()

    (sugestao,) = _analisar(cliente, c3)["elementos"]

    resumo = sugestao["elemento_casado"]["identidade"]
    assert len(resumo) <= 301 and resumo.endswith("…")
    assert cliente.get(f"/elementos/{jon['id']}").json()["descricao"] == longa  # a ficha tem tudo


def teste_o_contexto_da_ia_tem_teto_e_prioriza_os_elementos_mais_recentes(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, livro, (c1, c2, c3) = _cenario(cliente, usar_provedor_falso, elementos=[])
    identidade = "palavra " * 100  # 800 caracteres: vai cortada em ~200
    for indice in range(80):  # 80 elementos * ~230 caracteres estouram o teto de 8.000
        resposta = cliente.post(
            f"/livros/{livro['id']}/elementos",
            json={
                "tipo": "OBJETO",
                "nome": f"Objeto {indice:02d}",
                "descricao": identidade,
                # os de número par apareceram no capítulo 2 (mais recente); os ímpares, no 1
                "estado_inicial": {"capitulo_id": c2 if indice % 2 == 0 else c1, "descricao": "x"},
            },
        )
        assert resposta.status_code == 201

    _analisar(cliente, c3)

    (chamada,) = provedor.chamadas_de_extracao
    linhas = chamada["elementos_conhecidos"]
    assert sum(len(linha) + 1 for linha in linhas) <= 8000
    assert 0 < len(linhas) < 80  # houve corte
    assert all(len(linha) <= 240 for linha in linhas)  # cada identidade cortada em ~200
    # os mais recentes (capítulo 2) vêm antes dos do capítulo 1
    nomes = [linha.split(" (")[0] for linha in linhas]
    numeros = [int(nome.split()[1]) for nome in nomes]
    posicao_do_primeiro_impar = next((i for i, n in enumerate(numeros) if n % 2), len(numeros))
    assert all(n % 2 == 0 for n in numeros[:posicao_do_primeiro_impar])
    assert posicao_do_primeiro_impar >= 30  # todos os pares (40) cabem antes de começar os ímpares, ou o teto corta antes


def teste_estado_vigente_e_a_ficha_trazem_o_titulo_do_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, livro, (c1, _c2, c3) = _cenario(cliente, usar_provedor_falso)
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Jon", "estado_inicial": {"capitulo_id": c1, "descricao": "manto"}},
    ).json()
    titulo_do_c1 = livro["capitulos"][0]["titulo"]

    (sugestao,) = _analisar(cliente, c3)["elementos"]
    ficha = cliente.get(f"/elementos/{jon['id']}").json()

    assert sugestao["estado_vigente"]["titulo_do_capitulo"] == titulo_do_c1
    assert ficha["estados"][0]["titulo_do_capitulo"] == titulo_do_c1
