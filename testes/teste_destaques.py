"""Destaques do leitor (RL9 a RL13): criar, listar, ajustar, remover e ligar a um elemento."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Elemento
from testes.teste_rotas_sugestoes import _livro_com_capitulos

TEXTO = "Harry abriu a porta. Hermione sorriu 😀 para ele."


def _cenario(cliente: TestClient, sessao: Session) -> tuple[int, int]:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao.get(Capitulo, capitulo_id).texto = TEXTO
    sessao.commit()
    return livro["id"], capitulo_id


def _criar(cliente: TestClient, livro_id: int, capitulo_id: int, inicio: int, fim: int, **extra):
    return cliente.post(f"/livros/{livro_id}/destaques", json={"capitulo_id": capitulo_id, "inicio": inicio, "fim": fim, **extra})


def _elemento(sessao: Session, livro_id: int, nome: str = "Harry") -> Elemento:
    elemento = Elemento(livro_id=livro_id, tipo="PERSONAGEM", nome=nome)
    sessao.add(elemento)
    sessao.commit()
    return elemento


def teste_cria_o_destaque_e_o_servidor_copia_o_trecho(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)

    resposta = _criar(cliente, livro_id, capitulo_id, 0, 5)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["trecho"] == "Harry"
    assert corpo["cor"] == "AMARELO"
    assert corpo["nota"] is None and corpo["elemento_id"] is None


def teste_a_posicao_e_em_utf16_e_conta_o_emoji_como_dois(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    # O emoji vale 2 unidades UTF-16 e 1 caractere em Python: depois dele, as duas contagens divergem em 1.
    depois_do_emoji = TEXTO.index("para") + 1

    resposta = _criar(cliente, livro_id, capitulo_id, depois_do_emoji, depois_do_emoji + 4)

    assert resposta.status_code == 201
    assert resposta.json()["trecho"] == "para"


def teste_recusa_comecar_ou_terminar_no_meio_do_emoji(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    emoji = TEXTO.index("😀")

    assert _criar(cliente, livro_id, capitulo_id, emoji + 1, emoji + 5).status_code == 422


def teste_recusa_posicoes_invalidas(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)

    assert _criar(cliente, livro_id, capitulo_id, 5, 5).status_code == 422  # vazio
    assert _criar(cliente, livro_id, capitulo_id, 8, 3).status_code == 422  # fim antes do início
    assert _criar(cliente, livro_id, capitulo_id, 0, 9999).status_code == 422  # passa do fim do texto
    assert _criar(cliente, livro_id, capitulo_id, -1, 3).status_code == 422
    assert _criar(cliente, livro_id, 999999, 0, 3).status_code == 422  # capítulo que não é deste livro


def teste_recusa_cor_desconhecida(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)

    assert _criar(cliente, livro_id, capitulo_id, 0, 5, cor="LILAS").status_code == 422


def teste_recusa_trecho_maior_que_o_limite(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    sessao_com_tabelas.get(Capitulo, capitulo_id).texto = "a" * 6000
    sessao_com_tabelas.commit()

    assert _criar(cliente, livro_id, capitulo_id, 0, 5001).status_code == 422
    assert _criar(cliente, livro_id, capitulo_id, 0, 5000).status_code == 201


def teste_lista_na_ordem_do_livro_e_filtra_por_capitulo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    primeiro, segundo = (c["id"] for c in livro["capitulos"])
    for id_ in (primeiro, segundo):
        sessao_com_tabelas.get(Capitulo, id_).texto = TEXTO
    sessao_com_tabelas.commit()
    _criar(cliente, livro["id"], segundo, 0, 5)
    _criar(cliente, livro["id"], primeiro, 20, 28)
    _criar(cliente, livro["id"], primeiro, 0, 5)

    todos = cliente.get(f"/livros/{livro['id']}/destaques").json()
    assert [(d["capitulo_id"], d["inicio"]) for d in todos] == [(primeiro, 0), (primeiro, 20), (segundo, 0)]

    so_o_segundo = cliente.get(f"/livros/{livro['id']}/destaques", params={"capitulo_id": segundo}).json()
    assert [d["capitulo_id"] for d in so_o_segundo] == [segundo]


def teste_ajusta_so_o_que_foi_enviado(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    destaque = _criar(cliente, livro_id, capitulo_id, 0, 5, nota="importante").json()

    cor = cliente.patch(f"/destaques/{destaque['id']}", json={"cor": "VERDE"}).json()
    assert cor["cor"] == "VERDE" and cor["nota"] == "importante"  # a nota não foi enviada: continua

    sem_nota = cliente.patch(f"/destaques/{destaque['id']}", json={"nota": "  "}).json()
    assert sem_nota["nota"] is None and sem_nota["cor"] == "VERDE"


def teste_liga_e_desfaz_o_elemento_e_a_ficha_lista_as_passagens(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    elemento = _elemento(sessao_com_tabelas, livro_id)
    destaque = _criar(cliente, livro_id, capitulo_id, 0, 5).json()

    ligado = cliente.patch(f"/destaques/{destaque['id']}", json={"elemento_id": elemento.id}).json()
    assert ligado["elemento_id"] == elemento.id
    passagens = cliente.get(f"/elementos/{elemento.id}/destaques").json()
    assert [p["id"] for p in passagens] == [destaque["id"]]

    desfeito = cliente.patch(f"/destaques/{destaque['id']}", json={"elemento_id": None}).json()
    assert desfeito["elemento_id"] is None
    assert cliente.get(f"/elementos/{elemento.id}/destaques").json() == []


def teste_recusa_elemento_de_outro_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    outro = _livro_com_capitulos(cliente, capitulos=1)
    estranho = _elemento(sessao_com_tabelas, outro["id"], "Outro")

    assert _criar(cliente, livro_id, capitulo_id, 0, 5, elemento_id=estranho.id).status_code == 422
    destaque = _criar(cliente, livro_id, capitulo_id, 0, 5).json()
    assert cliente.patch(f"/destaques/{destaque['id']}", json={"elemento_id": estranho.id}).status_code == 422


def teste_remove_o_destaque(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    destaque = _criar(cliente, livro_id, capitulo_id, 0, 5).json()

    assert cliente.delete(f"/destaques/{destaque['id']}").status_code == 204
    assert cliente.delete(f"/destaques/{destaque['id']}").status_code == 404
    assert cliente.get(f"/livros/{livro_id}/destaques").json() == []


def teste_destaque_nao_sobe_a_revisao_do_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro_id, capitulo_id = _cenario(cliente, sessao_com_tabelas)
    antes = cliente.get(f"/livros/{livro_id}").json()["revisao"]

    _criar(cliente, livro_id, capitulo_id, 0, 5)

    assert cliente.get(f"/livros/{livro_id}").json()["revisao"] == antes
