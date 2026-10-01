"""Marcador (posição automática) e pins (posições à mão) — itens 3.4h e 6.10."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Marcador, Pin
from testes.teste_rotas_sugestoes import _livro_com_capitulos

AGORA = datetime.now(timezone.utc)


def _cenario(cliente: TestClient, sessao: Session, capitulos: int = 2) -> tuple[dict, list[int]]:
    """Um livro com capítulos de texto conhecido ("0123456789" repetido, 100 caracteres)."""
    livro = _livro_com_capitulos(cliente, capitulos=capitulos)
    ids = [c["id"] for c in livro["capitulos"]]
    for id_ in ids:
        sessao.get(Capitulo, id_).texto = "0123456789" * 10
    sessao.commit()
    return livro, ids


def _marcar(cliente: TestClient, livro_id: int, capitulo_id: int, posicao: int, lido_em: datetime):
    return cliente.put(
        f"/livros/{livro_id}/marcador",
        json={"capitulo_id": capitulo_id, "posicao_no_texto": posicao, "lido_em": lido_em.isoformat()},
    )


def _revisao(cliente: TestClient, livro_id: int) -> int:
    return cliente.get(f"/livros/{livro_id}").json()["revisao"]


# --------------------------------------------------------------------------- #
# Marcador
# --------------------------------------------------------------------------- #


def teste_livro_sem_leitura_devolve_marcador_nulo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, _ = _cenario(cliente, sessao_com_tabelas)

    resposta = cliente.get(f"/livros/{livro['id']}/marcador")

    assert resposta.status_code == 200
    assert resposta.json() == {"marcador": None}


def teste_gravar_cria_o_marcador_e_a_leitura_devolve(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, c2) = _cenario(cliente, sessao_com_tabelas)
    lido_em = AGORA - timedelta(minutes=5)

    gravado = _marcar(cliente, livro["id"], c2, 40, lido_em)

    assert gravado.status_code == 200, gravado.text
    corpo = gravado.json()
    assert corpo["aceito"] is True
    assert (corpo["marcador"]["capitulo_id"], corpo["marcador"]["posicao_no_texto"]) == (c2, 40)
    lido = cliente.get(f"/livros/{livro['id']}/marcador").json()["marcador"]
    assert (lido["livro_id"], lido["capitulo_id"], lido["posicao_no_texto"]) == (livro["id"], c2, 40)
    devolvido = datetime.fromisoformat(lido["lido_em"])
    if devolvido.tzinfo is None:  # o SQLite dos testes devolve sem fuso; o PostgreSQL, com
        devolvido = devolvido.replace(tzinfo=timezone.utc)
    assert abs(devolvido - lido_em) < timedelta(seconds=1)


def teste_o_mais_recente_vence_e_o_mais_antigo_e_recusado_devolvendo_o_vigente(
    cliente: TestClient, sessao_com_tabelas: Session
) -> None:
    """O aparelho que sincroniza tarde não passa por cima de uma leitura mais nova de outro."""
    livro, (c1, c2) = _cenario(cliente, sessao_com_tabelas)
    _marcar(cliente, livro["id"], c1, 10, AGORA - timedelta(hours=2))

    mais_novo = _marcar(cliente, livro["id"], c2, 70, AGORA - timedelta(hours=1)).json()
    mais_antigo = _marcar(cliente, livro["id"], c1, 5, AGORA - timedelta(hours=3)).json()

    assert mais_novo["aceito"] is True
    assert mais_antigo["aceito"] is False
    assert (mais_antigo["marcador"]["capitulo_id"], mais_antigo["marcador"]["posicao_no_texto"]) == (c2, 70)
    guardado = cliente.get(f"/livros/{livro['id']}/marcador").json()["marcador"]
    assert (guardado["capitulo_id"], guardado["posicao_no_texto"]) == (c2, 70)


def teste_mesmo_lido_em_conta_como_mais_novo_e_e_aceito(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    lido_em = AGORA - timedelta(minutes=1)
    _marcar(cliente, livro["id"], c1, 10, lido_em)

    repetido = _marcar(cliente, livro["id"], c1, 20, lido_em).json()

    assert repetido["aceito"] is True
    assert repetido["marcador"]["posicao_no_texto"] == 20


def teste_lido_em_no_futuro_e_limitado_ao_relogio_do_servidor(
    cliente: TestClient, sessao_com_tabelas: Session
) -> None:
    """Um aparelho com o relógio adiantado não pode travar o marcador contra os outros."""
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)

    gravado = _marcar(cliente, livro["id"], c1, 10, AGORA + timedelta(days=365)).json()

    lido_em = datetime.fromisoformat(gravado["marcador"]["lido_em"])
    if lido_em.tzinfo is None:
        lido_em = lido_em.replace(tzinfo=timezone.utc)
    assert lido_em <= datetime.now(timezone.utc)
    # E uma leitura de verdade, feita depois, ainda consegue passar por cima dele:
    depois = _marcar(cliente, livro["id"], c1, 99, datetime.now(timezone.utc)).json()
    assert depois["aceito"] is True


def teste_lido_em_sem_fuso_e_recusado(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)

    resposta = cliente.put(
        f"/livros/{livro['id']}/marcador",
        json={"capitulo_id": c1, "posicao_no_texto": 1, "lido_em": "2026-10-01T10:00:00"},
    )

    assert resposta.status_code == 422


def teste_marcador_valida_capitulo_e_posicao(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    outro, (outro_capitulo, _) = _cenario(cliente, sessao_com_tabelas)

    de_outro_livro = _marcar(cliente, livro["id"], outro_capitulo, 1, AGORA)
    inexistente = _marcar(cliente, livro["id"], 999999, 1, AGORA)
    alem_do_fim = _marcar(cliente, livro["id"], c1, 101, AGORA)
    negativa = _marcar(cliente, livro["id"], c1, -1, AGORA)
    no_fim = _marcar(cliente, livro["id"], c1, 100, AGORA)  # o texto tem 100: o fim exato vale

    assert [r.status_code for r in (de_outro_livro, inexistente, alem_do_fim, negativa, no_fim)] == [
        422, 422, 422, 422, 200,
    ]
    assert cliente.get(f"/livros/{outro['id']}/marcador").json() == {"marcador": None}


def teste_o_limite_da_posicao_e_em_utf16_e_nao_em_caracteres(
    cliente: TestClient, sessao_com_tabelas: Session
) -> None:
    """'a😀b' tem 3 caracteres Unicode mas 4 unidades UTF-16: o app conta como o segundo."""
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    sessao_com_tabelas.get(Capitulo, c1).texto = "a\U0001F600b"
    sessao_com_tabelas.commit()

    assert _marcar(cliente, livro["id"], c1, 4, AGORA).status_code == 200
    assert _marcar(cliente, livro["id"], c1, 5, AGORA).status_code == 422


def teste_livro_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/livros/9999/marcador").status_code == 404
    assert cliente.get("/livros/9999/pins").status_code == 404
    assert cliente.post("/livros/9999/pins", json={"capitulo_id": 1, "posicao_no_texto": 0}).status_code == 404
    assert _marcar(cliente, 9999, 1, 0, AGORA).status_code == 404


# --------------------------------------------------------------------------- #
# Pins
# --------------------------------------------------------------------------- #


def _pin(cliente: TestClient, livro_id: int, capitulo_id: int, posicao: int, **extra):
    return cliente.post(
        f"/livros/{livro_id}/pins", json={"capitulo_id": capitulo_id, "posicao_no_texto": posicao, **extra}
    )


def teste_criar_pin_com_e_sem_nota(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)

    com_nota = _pin(cliente, livro["id"], c1, 30, nota="  Aqui ele descobre tudo  ")
    sem_nota = _pin(cliente, livro["id"], c1, 60)
    em_branco = _pin(cliente, livro["id"], c1, 70, nota="   ")

    assert [r.status_code for r in (com_nota, sem_nota, em_branco)] == [201, 201, 201]
    assert com_nota.json()["nota"] == "Aqui ele descobre tudo"  # sem os espaços das pontas
    assert sem_nota.json()["nota"] is None
    assert em_branco.json()["nota"] is None  # texto em branco é "sem nota"
    assert com_nota.json()["criado_em"] is not None and com_nota.json()["livro_id"] == livro["id"]


def teste_pin_valida_capitulo_posicao_e_tamanho_da_nota(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    _, (outro_capitulo, _) = _cenario(cliente, sessao_com_tabelas)

    assert _pin(cliente, livro["id"], outro_capitulo, 1).status_code == 422
    assert _pin(cliente, livro["id"], c1, 101).status_code == 422
    assert _pin(cliente, livro["id"], c1, -3).status_code == 422
    assert _pin(cliente, livro["id"], c1, 1, nota="x" * 1001).status_code == 422
    assert _pin(cliente, livro["id"], c1, 1, nota="x" * 1000).status_code == 201


def teste_pins_vem_na_ordem_do_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    """Ordem do capítulo e, dentro dele, da posição — não a ordem de criação."""
    livro, (c1, c2) = _cenario(cliente, sessao_com_tabelas)
    _pin(cliente, livro["id"], c2, 5, nota="terceiro")
    _pin(cliente, livro["id"], c1, 50, nota="segundo")
    _pin(cliente, livro["id"], c1, 20, nota="primeiro")

    pins = cliente.get(f"/livros/{livro['id']}/pins").json()

    assert [p["nota"] for p in pins] == ["primeiro", "segundo", "terceiro"]


def teste_pins_de_um_livro_nao_aparecem_no_outro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    outro, _ = _cenario(cliente, sessao_com_tabelas)
    _pin(cliente, livro["id"], c1, 1, nota="meu")

    assert cliente.get(f"/livros/{outro['id']}/pins").json() == []


def teste_ajustar_e_apagar_a_nota_do_pin(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    pin = _pin(cliente, livro["id"], c1, 10, nota="antiga").json()

    ajustado = cliente.patch(f"/pins/{pin['id']}", json={"nota": "nova"})
    apagada = cliente.patch(f"/pins/{pin['id']}", json={"nota": None})
    sem_campo = cliente.patch(f"/pins/{pin['id']}", json={})

    assert ajustado.json()["nota"] == "nova"
    assert apagada.json()["nota"] is None
    assert sem_campo.status_code == 422  # a nota é obrigatória no corpo (mesmo que nula): "nada a mudar" é erro
    assert apagada.json()["posicao_no_texto"] == 10  # a posição não muda


def teste_remover_pin(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    pin = _pin(cliente, livro["id"], c1, 10).json()

    assert cliente.delete(f"/pins/{pin['id']}").status_code == 204
    assert cliente.get(f"/livros/{livro['id']}/pins").json() == []
    assert cliente.delete(f"/pins/{pin['id']}").status_code == 404
    assert cliente.patch(f"/pins/{pin['id']}", json={"nota": "x"}).status_code == 404


# --------------------------------------------------------------------------- #
# O que NÃO deve acontecer, e o que apaga junto
# --------------------------------------------------------------------------- #


def teste_marcador_e_pins_nao_sobem_a_revisao_do_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    """Item 3.4h: o marcador é gravado o tempo todo e faria o app reler a lista do livro sem parar."""
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    antes = _revisao(cliente, livro["id"])
    etag_antes = cliente.get(f"/livros/{livro['id']}").headers["etag"]

    _marcar(cliente, livro["id"], c1, 10, AGORA - timedelta(minutes=2))
    _marcar(cliente, livro["id"], c1, 20, AGORA - timedelta(minutes=1))
    pin = _pin(cliente, livro["id"], c1, 30, nota="a").json()
    cliente.patch(f"/pins/{pin['id']}", json={"nota": "b"})
    cliente.delete(f"/pins/{pin['id']}")

    assert _revisao(cliente, livro["id"]) == antes
    assert cliente.get(f"/livros/{livro['id']}").headers["etag"] == etag_antes


def teste_apagar_o_livro_apaga_marcador_e_pins(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, _) = _cenario(cliente, sessao_com_tabelas)
    _marcar(cliente, livro["id"], c1, 10, AGORA)
    _pin(cliente, livro["id"], c1, 20)

    assert cliente.delete(f"/livros/{livro['id']}").status_code == 204

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.query(Marcador).count() == 0
    assert sessao_com_tabelas.query(Pin).count() == 0


def teste_so_existe_um_marcador_por_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, (c1, c2) = _cenario(cliente, sessao_com_tabelas)

    _marcar(cliente, livro["id"], c1, 10, AGORA - timedelta(minutes=3))
    _marcar(cliente, livro["id"], c2, 20, AGORA - timedelta(minutes=2))
    _marcar(cliente, livro["id"], c1, 30, AGORA - timedelta(minutes=1))

    assert sessao_com_tabelas.query(Marcador).filter_by(livro_id=livro["id"]).count() == 1
