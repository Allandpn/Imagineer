"""A lixeira de livros (item 7.5b, LT1 e LT2): apagar só marca, o livro some de tudo, restaura inteiro e apagar de vez remove."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro
from testes.teste_importacao_epub import TEXTO_LONGO  # noqa: F401
from testes.teste_rotas_prompts import _diretorio_de_imagens, _importar_imagem  # noqa: F401
from testes.teste_rotas_sugestoes import _epub_com_capitulos, _livro_com_capitulos
from testes.teste_galeria_do_elemento import _prompt_do_frame
from testes.teste_rotas_prompts import _frame
from imagineer.ia.falso import ProvedorFalso
from testes.teste_vinculos_do_retrato import MODELO_FALSO, _perfil


def _apagar(cliente: TestClient, livro_id: int):
    resposta = cliente.delete(f"/livros/{livro_id}")
    assert resposta.status_code == 204, resposta.text


def teste_lt2_apagar_o_livro_o_move_para_a_lixeira_e_ele_some_de_tudo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente)
    capitulo = livro["capitulos"][0]["id"]

    _apagar(cliente, livro["id"])

    assert cliente.get("/livros").json() == []
    assert cliente.get(f"/livros/{livro['id']}").status_code == 404
    assert cliente.get(f"/capitulos/{capitulo}").status_code == 404
    assert cliente.get("/busca", params={"q": "parágrafo"}).json()["total"] == 0
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Livro, livro["id"]).apagado_em is not None  # a linha continua no banco
    assert sessao_com_tabelas.query(Capitulo).filter_by(livro_id=livro["id"]).count() > 0


def teste_lt2_apagar_de_novo_nao_da_erro_e_livro_que_nao_existe_e_404(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente)
    _apagar(cliente, livro["id"])

    assert cliente.delete(f"/livros/{livro['id']}").status_code == 204
    assert cliente.delete("/livros/999").status_code == 404


def teste_lt2_a_lixeira_lista_o_livro_com_o_que_ele_leva(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=3)
    _apagar(cliente, livro["id"])

    corpo = cliente.get("/lixeira/livros").json()

    [item] = corpo["livros"]
    assert (item["id"], item["titulo"], item["total_de_capitulos"]) == (livro["id"], livro["titulo"], 3)
    assert item["total_de_imagens"] == 0 and item["tamanho_das_imagens_em_bytes"] == 0
    assert item["apagado_em"]
    assert corpo["total_em_bytes"] == 0


def teste_lt2_restaurar_traz_o_livro_de_volta_inteiro(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=3)
    _apagar(cliente, livro["id"])

    resposta = cliente.post(f"/lixeira/livros/{livro['id']}/restaurar")

    assert resposta.status_code == 200, resposta.text
    assert [l["id"] for l in cliente.get("/livros").json()] == [livro["id"]]
    assert len(cliente.get(f"/livros/{livro['id']}").json()["capitulos"]) == 3
    assert cliente.get("/lixeira/livros").json()["livros"] == []


def teste_lt1_restaurar_ou_apagar_de_vez_o_que_nao_esta_na_lixeira_e_404(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente)

    assert cliente.post(f"/lixeira/livros/{livro['id']}/restaurar").status_code == 404
    assert cliente.delete(f"/lixeira/livros/{livro['id']}").status_code == 404
    assert cliente.get(f"/livros/{livro['id']}").status_code == 200  # nada aconteceu com ele


def teste_lt2_apagar_de_vez_remove_o_livro_os_capitulos_e_os_arquivos_das_imagens(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": _perfil(cliente)["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    capitulo = livro["capitulos"][0]["id"]
    frame = _frame(cliente, capitulo, [], tipo="CENA")
    prompt = _prompt_do_frame(cliente, frame["id"])
    imagem = _importar_imagem(cliente, prompt["id"])
    arquivo = cliente.get(f"/imagens/{imagem['id']}/arquivo")
    assert arquivo.status_code == 200
    _apagar(cliente, livro["id"])
    [item] = cliente.get("/lixeira/livros").json()["livros"]
    assert item["total_de_imagens"] == 1 and item["tamanho_das_imagens_em_bytes"] > 0

    resposta = cliente.delete(f"/lixeira/livros/{livro['id']}")

    assert resposta.status_code == 204, resposta.text
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Livro, livro["id"]) is None
    assert sessao_com_tabelas.query(Capitulo).filter_by(livro_id=livro["id"]).count() == 0
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 404  # a linha e o arquivo se foram


def teste_lt2_esvaziar_remove_so_os_livros_da_lixeira(cliente: TestClient) -> None:
    ficar = _livro_com_capitulos(cliente, identificador="urn:isbn:1")
    ir1 = _livro_com_capitulos(cliente, identificador="urn:isbn:2")
    ir2 = _livro_com_capitulos(cliente, identificador="urn:isbn:3")
    _apagar(cliente, ir1["id"])
    _apagar(cliente, ir2["id"])

    resposta = cliente.delete("/lixeira/livros")

    assert resposta.json()["removidas"] == 2
    assert [l["id"] for l in cliente.get("/livros").json()] == [ficar["id"]]
    assert cliente.get("/lixeira/livros").json()["livros"] == []


def teste_lt2_importar_o_mesmo_epub_de_um_livro_na_lixeira_nao_avisa_de_repetido(cliente: TestClient) -> None:
    antigo = _livro_com_capitulos(cliente)
    _apagar(cliente, antigo["id"])

    resposta = cliente.post("/livros", files={"arquivo": ("livro.epub", _epub_com_capitulos(), "application/epub+zip")})

    assert resposta.status_code == 201
    assert resposta.json()["livros_semelhantes"] == []  # o da lixeira não conta
