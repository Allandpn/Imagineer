"""Pedidos de 22/10/2026 sobre a ficha do elemento: a primeira aparição dele no livro (AP1), o modelo de texto de cada imagem e a posição de retratos e cenas
no capítulo, para o app levar a pessoa até o lugar certo."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro
from testes.teste_galeria_do_elemento import _galeria, _montar, _prompt_do_frame
from testes.teste_rotas_prompts import _importar_imagem
from testes.teste_vinculos_do_retrato import _retrato


def _livro_com_capitulos(sessao: Session, textos: list[str], ignorados: tuple[int, ...] = ()) -> Livro:
    livro = Livro(titulo="Livro das aparições", nome_arquivo="a.epub", identificador_epub="aparicoes")
    sessao.add(livro)
    sessao.flush()
    for ordem, texto in enumerate(textos, start=1):
        sessao.add(Capitulo(livro_id=livro.id, ordem=ordem, titulo=f"Cap {ordem}", texto=texto, ignorado=ordem in ignorados))
    sessao.commit()
    return livro


def _criar_elemento(cliente: TestClient, livro_id: int, nome: str, tipo: str = "PERSONAGEM") -> int:
    resposta = cliente.post(f"/livros/{livro_id}/elementos", json={"tipo": tipo, "nome": nome})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


def teste_ap1_a_primeira_aparicao_vem_primeiro_com_o_paragrafo_que_a_descreve(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(
        sessao_com_tabelas,
        [
            "Nada sobre ele aqui.",
            "A estrada era longa.\n\nSeverin era alto, de barba ruiva e olhos cinzentos.\n\nEle partiu.",
            "Mais tarde, Severin voltou.",
        ],
    )
    severin = _criar_elemento(cliente, livro.id, "Severin")

    resposta = cliente.get(f"/elementos/{severin}/aparicoes")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert [a["capitulo_ordem"] for a in corpo["aparicoes"]] == [2, 3]  # o capítulo 1 não o cita
    primeira = corpo["aparicoes"][0]
    assert primeira["primeira"] is True and corpo["aparicoes"][1]["primeira"] is False
    assert primeira["trecho"] == "Severin era alto, de barba ruiva e olhos cinzentos."
    assert primeira["posicao_no_texto"] == len("A estrada era longa.\n\n")  # o início do parágrafo, em UTF-16
    assert primeira["tem_estado"] is False


def teste_ap1_capitulo_arquivado_nao_conta_e_sem_mencao_a_lista_e_vazia(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(sessao_com_tabelas, ["Severin chegou.", "Severin foi embora."], ignorados=(1,))
    severin = _criar_elemento(cliente, livro.id, "Severin")
    ninguem = _criar_elemento(cliente, livro.id, "Ninguém Citado")

    assert [a["capitulo_ordem"] for a in cliente.get(f"/elementos/{severin}/aparicoes").json()["aparicoes"]] == [2]
    assert cliente.get(f"/elementos/{ninguem}/aparicoes").json()["aparicoes"] == []


def teste_ap1_o_nome_inteiro_ou_o_pedaco_que_e_nome_proprio_acha_a_aparicao(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(sessao_com_tabelas, ["O velho Estevan sorriu."])
    estevan = _criar_elemento(cliente, livro.id, "Estevan Corvo")

    assert len(cliente.get(f"/elementos/{estevan}/aparicoes").json()["aparicoes"]) == 1


def teste_ap1_marca_os_capitulos_em_que_o_elemento_ja_tem_estado(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(sessao_com_tabelas, ["Severin chegou.", "Severin partiu."])
    capitulo_2 = sorted(livro.capitulos, key=lambda c: c.ordem)[1]
    resposta = cliente.post(
        f"/livros/{livro.id}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Severin", "estado_inicial": {"capitulo_id": capitulo_2.id, "descricao": "Alto."}},
    )
    assert resposta.status_code == 201, resposta.text

    aparicoes = cliente.get(f"/elementos/{resposta.json()['id']}/aparicoes").json()["aparicoes"]

    assert [(a["capitulo_ordem"], a["tem_estado"]) for a in aparicoes] == [(1, False), (2, True)]


def teste_ap1_elemento_inexistente_da_404(cliente: TestClient) -> None:
    assert cliente.get("/elementos/99999/aparicoes").status_code == 404


def teste_nav_a_imagem_do_retrato_traz_o_modelo_do_prompt_e_a_posicao_no_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"]).json()
    prompt = _prompt_do_frame(cliente, retrato["id"])
    _importar_imagem(cliente, prompt["id"])

    (imagem,) = _galeria(cliente, e["criatura"]["id"])["imagens"]

    assert imagem["modelo_do_prompt"] == prompt["modelo_ia"] and imagem["modelo_do_prompt"] is not None
    assert "posicao_no_texto" in imagem  # pode ser nulo (retrato sem posição), mas o campo existe para o app


def teste_nav_a_cena_do_elemento_traz_a_posicao_no_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    from testes.teste_rotas_prompts import _frame

    capitulo, e = _montar(cliente, usar_provedor_falso)
    _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")

    (cena,) = _galeria(cliente, e["criatura"]["id"])["cenas"]

    assert "posicao_no_texto" in cena
