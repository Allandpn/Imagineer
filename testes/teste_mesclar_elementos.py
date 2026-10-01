"""`POST /elementos/{id}/mesclar` — juntar um elemento duplicado a outro (itens 6.3 e 7.5b, rodada 4).

Achado testando no tablet (30/09/2026): o mesmo elemento foi cadastrado como veículo e como ambiente;
corrigir o tipo de um dava 409 e não havia como juntar os dois.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import HistoricoIdentidadeElemento, TipoElemento
from testes.teste_rotas_prompts import _frame  # noqa: F401
from testes.teste_rotas_sugestoes import _escolher_modelo_de_extracao, _livro_com_capitulos


def _elemento(cliente: TestClient, livro_id: int, tipo: str, nome: str, capitulo_id: int | None = None, **extra) -> dict:
    corpo = {"tipo": tipo, "nome": nome, **extra}
    if capitulo_id is not None:
        corpo["estado_inicial"] = {"capitulo_id": capitulo_id, "descricao": f"{nome} ({tipo}) no capítulo {capitulo_id}"}
    resposta = cliente.post(f"/livros/{livro_id}/elementos", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _duplicados(cliente: TestClient):
    """Muralha cadastrada como AMBIENTE (capítulo 1) e como VEICULO (capítulo 2)."""
    livro = _livro_com_capitulos(cliente, capitulos=3)
    c1, c2, c3 = (c["id"] for c in livro["capitulos"])
    ambiente = _elemento(cliente, livro["id"], "AMBIENTE", "Muralha", c1)
    veiculo = _elemento(cliente, livro["id"], "VEICULO", "Muralha", c2)
    return livro, (c1, c2, c3), ambiente, veiculo


def teste_o_conflito_que_motivou_a_rota(cliente: TestClient) -> None:
    """Mudar o tipo de um para o do outro dá 409; mesclar é a saída."""
    _, _, ambiente, _ = _duplicados(cliente)

    resposta = cliente.patch(f"/elementos/{ambiente['id']}", json={"tipo": "VEICULO"})

    assert resposta.status_code == 409


def teste_mesclar_junta_os_estados_no_destino_e_apaga_a_origem(cliente: TestClient) -> None:
    _, (c1, c2, _c3), ambiente, veiculo = _duplicados(cliente)

    resposta = cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]})

    assert resposta.status_code == 200
    ficha = resposta.json()
    assert ficha["id"] == veiculo["id"] and ficha["tipo"] == "VEICULO"  # o do destino fica
    assert [(e["capitulo_id"], e["descricao"]) for e in ficha["estados"]] == [
        (c1, f"Muralha (AMBIENTE) no capítulo {c1}"),  # veio da origem, em ordem narrativa
        (c2, f"Muralha (VEICULO) no capítulo {c2}"),
    ]
    assert cliente.get(f"/elementos/{ambiente['id']}").status_code == 404  # a origem deixou de existir


def teste_os_frames_que_usavam_a_origem_continuam_ligados(cliente: TestClient) -> None:
    _, (c1, *_), ambiente, veiculo = _duplicados(cliente)
    estado_da_origem = ambiente["estados"][0]["id"]
    frame = _frame(cliente, c1, [estado_da_origem])

    cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]})

    detalhe = cliente.get(f"/frames/{frame['id']}").json()
    assert [(e["estado_id"], e["elemento_id"]) for e in detalhe["elementos"]] == [(estado_da_origem, veiculo["id"])]


def teste_as_sugestoes_casadas_com_a_origem_passam_para_o_destino(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.AMBIENTE, nome="Muralha")])
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    c1 = livro["capitulos"][0]["id"]
    _escolher_modelo_de_extracao(cliente)
    ambiente = _elemento(cliente, livro["id"], "AMBIENTE", "Muralha", c1)
    veiculo = _elemento(cliente, livro["id"], "VEICULO", "Muralha", c1)
    (sugestao,) = cliente.post(f"/capitulos/{c1}/sugestoes").json()["elementos"]
    assert sugestao["elemento_id"] == ambiente["id"]

    cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]})

    (depois,) = cliente.get(f"/capitulos/{c1}/sugestoes").json()["elementos"]
    assert depois["elemento_id"] == veiculo["id"]
    assert depois["elemento_casado"]["tipo"] == "VEICULO"


def teste_o_historico_de_identidade_passa_para_o_destino(
    cliente: TestClient, sessao_com_tabelas: Session
) -> None:
    _, (c1, *_), ambiente, veiculo = _duplicados(cliente)
    sessao_com_tabelas.add(
        HistoricoIdentidadeElemento(elemento_id=ambiente["id"], capitulo_id=c1, descricao="Guarda a fronteira.")
    )
    sessao_com_tabelas.commit()

    ficha = cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]}).json()

    assert [h["descricao"] for h in ficha["historico_identidade"]] == ["Guarda a fronteira."]


def teste_o_destino_mantem_a_identidade_e_so_ganha_a_da_origem_se_nao_tiver(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    com = _elemento(cliente, livro["id"], "AMBIENTE", "Castelo", descricao="Identidade do destino.")
    origem = _elemento(cliente, livro["id"], "EDIFICACAO", "Castelo", descricao="Identidade da origem.")
    sem = _elemento(cliente, livro["id"], "OBJETO", "Sem identidade")
    outra = _elemento(cliente, livro["id"], "OBJETO", "Outra origem", descricao="Emprestada.")

    mantida = cliente.post(f"/elementos/{origem['id']}/mesclar", json={"destino_id": com["id"]}).json()
    emprestada = cliente.post(f"/elementos/{outra['id']}/mesclar", json={"destino_id": sem["id"]}).json()

    assert mantida["descricao"] == "Identidade do destino."
    assert emprestada["descricao"] == "Emprestada."


def teste_nao_se_junta_um_elemento_a_ele_mesmo(cliente: TestClient) -> None:
    _, _, ambiente, _ = _duplicados(cliente)

    resposta = cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": ambiente["id"]})

    assert resposta.status_code == 422
    assert cliente.get(f"/elementos/{ambiente['id']}").status_code == 200  # nada mudou


def teste_nao_se_junta_a_elemento_de_outro_livro(cliente: TestClient) -> None:
    livro_a, _, ambiente, _ = _duplicados(cliente)
    livro_b = _livro_com_capitulos(cliente, capitulos=1, identificador="urn:isbn:2")
    de_fora = _elemento(cliente, livro_b["id"], "AMBIENTE", "Muralha")

    resposta = cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": de_fora["id"]})

    assert resposta.status_code == 422
    assert len(cliente.get(f"/elementos/{ambiente['id']}").json()["estados"]) == 1  # intacto


def teste_origem_ou_destino_inexistente_responde_404(cliente: TestClient) -> None:
    _, _, ambiente, _ = _duplicados(cliente)

    assert cliente.post("/elementos/9999/mesclar", json={"destino_id": ambiente["id"]}).status_code == 404
    assert cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": 9999}).status_code == 404
    assert len(cliente.get(f"/elementos/{ambiente['id']}").json()["estados"]) == 1


def teste_mesclar_sobe_a_revisao_do_livro(cliente: TestClient) -> None:
    livro, _, ambiente, veiculo = _duplicados(cliente)
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]})

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] > antes


def teste_depois_de_mesclar_o_tipo_pode_ser_corrigido_sem_conflito(cliente: TestClient) -> None:
    """O fluxo do usuário inteiro: duplicados -> mesclar no veículo -> o nome/tipo ficam livres."""
    livro, _, ambiente, veiculo = _duplicados(cliente)
    cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]})

    lista = cliente.get(f"/livros/{livro['id']}/elementos").json()

    assert [(e["nome"], e["tipo"], e["total_de_estados"]) for e in lista] == [("Muralha", "VEICULO", 2)]


def teste_estados_do_mesmo_capitulo_ficam_os_dois(cliente: TestClient) -> None:
    """Nada impede dois estados do mesmo elemento no mesmo capítulo: a mesclagem não escolhe um."""
    livro = _livro_com_capitulos(cliente, capitulos=2)
    c1 = livro["capitulos"][0]["id"]
    ambiente = _elemento(cliente, livro["id"], "AMBIENTE", "Muralha", c1)
    veiculo = _elemento(cliente, livro["id"], "VEICULO", "Muralha", c1)

    ficha = cliente.post(f"/elementos/{ambiente['id']}/mesclar", json={"destino_id": veiculo["id"]}).json()

    assert len(ficha["estados"]) == 2
    assert {e["capitulo_id"] for e in ficha["estados"]} == {c1}
