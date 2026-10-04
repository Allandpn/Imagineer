"""Editar o título e a descrição de uma cena sugerida (item 7.5b, LV6): `PATCH /sugestoes-cena/{id}`."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import SugestaoDeCena
from testes.teste_posicao_manual import _cenario


def _cena(sessao: Session) -> SugestaoDeCena:
    return sessao.query(SugestaoDeCena).one()


def teste_lv6_edita_titulo_e_descricao_da_cena(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = _cena(sessao_com_tabelas)

    resposta = cliente.patch(f"/sugestoes-cena/{cena.id}", json={"titulo": "A espada de Ned", "descricao": "  Ned ergue a espada.  "})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert (corpo["titulo"], corpo["descricao"]) == ("A espada de Ned", "Ned ergue a espada.")


def teste_lv6_descricao_vazia_apaga_e_so_o_que_veio_muda(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = _cena(sessao_com_tabelas)
    cliente.patch(f"/sugestoes-cena/{cena.id}", json={"descricao": "algo"})

    resposta = cliente.patch(f"/sugestoes-cena/{cena.id}", json={"descricao": "   "}).json()

    assert resposta["descricao"] is None
    assert resposta["titulo"] == "A espada"  # o título não foi tocado


def teste_lv6_o_frame_da_cena_acompanha_a_edicao(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, capitulo_id = _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = _cena(sessao_com_tabelas)
    # confirma a cena: nasce o frame (o participante precisa ser um elemento confirmado; aqui usamos o frame direto)
    from imagineer.modelos import Frame, TipoDeFrame

    frame = Frame(capitulo_id=capitulo_id, tipo=TipoDeFrame.CENA, titulo="A espada")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.flush()
    cena.frame_id = frame.id
    sessao_com_tabelas.commit()

    resposta = cliente.patch(f"/sugestoes-cena/{cena.id}", json={"titulo": "Novo título", "descricao": "Nova."})

    assert resposta.status_code == 200, resposta.text
    sessao_com_tabelas.expire_all()
    assert (frame.titulo, frame.descricao) == ("Novo título", "Nova.")


def teste_lv6_corpo_vazio_ou_titulo_vazio_e_recusado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = _cena(sessao_com_tabelas)

    assert cliente.patch(f"/sugestoes-cena/{cena.id}", json={}).status_code == 422
    assert cliente.patch(f"/sugestoes-cena/{cena.id}", json={"titulo": ""}).status_code == 422


def teste_descartar_continua_funcionando(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _cenario(cliente, usar_provedor_falso, sessao_com_tabelas)
    cena = _cena(sessao_com_tabelas)

    resposta = cliente.patch(f"/sugestoes-cena/{cena.id}", json={"descartada": True})

    assert resposta.status_code == 200
    assert resposta.json()["descartada"] is True
