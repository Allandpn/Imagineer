"""Os favoritos (RL31 a RL38): o livro, um parágrafo, um elemento, uma cena e uma imagem."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.modelos import Capitulo
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _elemento_com_estado, _frame, _importar_imagem, _montar_frame_completo
from testes.teste_rotas_sugestoes import _livro_com_capitulos

PARAGRAFOS = "Primeiro parágrafo do capítulo.\n\nSegundo parágrafo, mais longo, com\nquebra de linha dentro dele.\n\nTerceiro."


def _favoritar(cliente: TestClient, livro_id: int, **corpo):
    return cliente.post(f"/livros/{livro_id}/favoritos", json=corpo)


def _lista(cliente: TestClient, livro_id: int, **params) -> list[dict]:
    resposta = cliente.get(f"/livros/{livro_id}/favoritos", params=params)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _livro_com_texto(cliente: TestClient, sessao: Session) -> tuple[dict, dict]:
    livro = _livro_com_capitulos(cliente, capitulos=2)
    capitulo = livro["capitulos"][0]
    sessao.get(Capitulo, capitulo["id"]).texto = PARAGRAFOS
    sessao.commit()
    return livro, capitulo


# --------------------------------------------------------------------------- #
# O livro
# --------------------------------------------------------------------------- #


def teste_favoritar_o_livro_aparece_no_resumo_e_desfavoritar_tira(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    assert cliente.get(f"/livros/{livro['id']}").json()["favorito_id"] is None

    criado = _favoritar(cliente, livro["id"], tipo="LIVRO")

    assert criado.status_code == 201, criado.text
    assert criado.json()["rotulo"] == livro["titulo"] and criado.json()["tipo"] == "LIVRO"
    assert cliente.get(f"/livros/{livro['id']}").json()["favorito_id"] == criado.json()["id"]
    assert [l["favorito_id"] for l in cliente.get("/livros").json()] == [criado.json()["id"]]

    assert cliente.delete(f"/favoritos/{criado.json()['id']}").status_code == 204
    assert cliente.get(f"/livros/{livro['id']}").json()["favorito_id"] is None


def teste_favoritar_de_novo_devolve_o_que_ja_existe_com_200(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)

    primeira = _favoritar(cliente, livro["id"], tipo="LIVRO")
    segunda = _favoritar(cliente, livro["id"], tipo="LIVRO")

    assert (primeira.status_code, segunda.status_code) == (201, 200)
    assert primeira.json()["id"] == segunda.json()["id"]
    assert len(_lista(cliente, livro["id"])) == 1


def teste_favorito_nao_sobe_a_revisao_do_livro(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    _favoritar(cliente, livro["id"], tipo="LIVRO")
    _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=0)

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] == antes


# --------------------------------------------------------------------------- #
# O parágrafo
# --------------------------------------------------------------------------- #


def teste_paragrafo_guarda_o_comeco_dele_em_um_espaco_so(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)
    segundo = PARAGRAFOS.index("Segundo")

    resposta = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=segundo)

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["rotulo"] == "Segundo parágrafo, mais longo, com quebra de linha dentro dele."  # até a linha em branco, sem a quebra
    assert corpo["capitulo_id"] == capitulo["id"] and corpo["posicao"] == segundo and corpo["ordem_do_capitulo"] == capitulo["ordem"]


def teste_paragrafo_longo_e_cortado_na_ultima_palavra(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo = livro["capitulos"][0]
    sessao_com_tabelas.get(Capitulo, capitulo["id"]).texto = " ".join(["palavra"] * 200)
    sessao_com_tabelas.commit()

    corpo = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=0).json()

    assert corpo["rotulo"].endswith("palavra…") and len(corpo["rotulo"]) <= 301


def teste_paragrafo_depois_de_um_emoji_conta_em_utf16(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    capitulo = livro["capitulos"][0]
    sessao_com_tabelas.get(Capitulo, capitulo["id"]).texto = "Começo \U0001F600.\n\nO Muro caiu."
    sessao_com_tabelas.commit()

    certo = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=12)  # o emoji vale 2
    no_meio = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=8)  # corta o emoji ao meio

    assert certo.status_code == 201 and certo.json()["rotulo"] == "O Muro caiu."
    assert no_meio.status_code == 422


def teste_paragrafo_com_posicao_fora_do_capitulo_ou_de_outro_livro_da_422(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)
    outro = _livro_com_capitulos(cliente, capitulos=1, identificador="urn:isbn:2")

    assert _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=99999).status_code == 422
    assert _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=outro["capitulos"][0]["id"], posicao=0).status_code == 422


def teste_o_mesmo_paragrafo_e_um_favorito_so_e_paragrafos_diferentes_sao_dois(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)

    a = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=0).json()
    de_novo = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=0).json()
    b = _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=PARAGRAFOS.index("Terceiro")).json()

    assert a["id"] == de_novo["id"] != b["id"]
    assert len(_lista(cliente, livro["id"], tipo="PARAGRAFO")) == 2


# --------------------------------------------------------------------------- #
# O alvo certo para cada tipo
# --------------------------------------------------------------------------- #


def teste_o_corpo_precisa_dos_campos_do_tipo_e_so_deles(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)

    assert _favoritar(cliente, livro["id"], tipo="ELEMENTO").status_code == 422  # falta o elemento
    assert _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=1).status_code == 422  # falta a posição
    assert _favoritar(cliente, livro["id"], tipo="LIVRO", elemento_id=1).status_code == 422  # o livro não leva alvo
    assert _favoritar(cliente, livro["id"], tipo="ELEMENTO", elemento_id=1, frame_id=2).status_code == 422  # campo de outro tipo
    assert _favoritar(cliente, livro["id"], tipo="COISA").status_code == 422
    assert _favoritar(cliente, livro["id"], tipo="LIVRO", extra=1).status_code == 422


def teste_elemento_de_outro_livro_da_422_e_inexistente_da_404(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    outro = _livro_com_capitulos(cliente, capitulos=1, identificador="urn:isbn:2")
    do_outro = cliente.post(f"/livros/{outro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Arya"}).json()

    assert _favoritar(cliente, livro["id"], tipo="ELEMENTO", elemento_id=do_outro["id"]).status_code == 422
    assert _favoritar(cliente, livro["id"], tipo="ELEMENTO", elemento_id=99999).status_code == 404


def teste_elemento_na_lixeira_some_da_lista_e_volta_ao_restaurar(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=1)
    jon = cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}).json()
    criado = _favoritar(cliente, livro["id"], tipo="ELEMENTO", elemento_id=jon["id"])
    assert criado.json()["rotulo"] == "Jon"

    assert cliente.delete(f"/elementos/{jon['id']}").status_code == 204
    assert _lista(cliente, livro["id"]) == []  # na lixeira: não aparece

    assert cliente.post(f"/lixeira/elementos/{jon['id']}/restaurar").status_code == 200
    assert [f["rotulo"] for f in _lista(cliente, livro["id"])] == ["Jon"]  # voltou, e o favorito também


def teste_cena_favorita_com_titulo_e_capitulo_e_retrato_nao_vale(cliente: TestClient, usar_provedor_falso) -> None:
    livro, cena = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="p"))
    retrato = _frame(cliente, cena["capitulo_id"], [cena["elementos"][0]["estado_id"]], tipo="PERSONAGEM")

    boa = _favoritar(cliente, livro["id"], tipo="CENA", frame_id=cena["id"])
    ruim = _favoritar(cliente, livro["id"], tipo="CENA", frame_id=retrato["id"])

    assert boa.status_code == 201 and boa.json()["rotulo"] == cena["titulo"] and boa.json()["capitulo_id"] == cena["capitulo_id"]
    assert ruim.status_code == 422


def teste_cena_na_lixeira_some_da_lista(cliente: TestClient, usar_provedor_falso) -> None:
    livro, cena = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="p"))
    _favoritar(cliente, livro["id"], tipo="CENA", frame_id=cena["id"])
    assert len(_lista(cliente, livro["id"])) == 1

    cliente.delete(f"/frames/{cena['id']}")

    assert _lista(cliente, livro["id"]) == []


def teste_imagem_favorita_e_some_quando_vai_para_a_lixeira(cliente: TestClient, usar_provedor_falso) -> None:
    livro, cena = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="p"))
    prompt = cliente.post(f"/frames/{cena['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])

    criada = _favoritar(cliente, livro["id"], tipo="IMAGEM", imagem_id=imagem["id"])
    assert criada.status_code == 201 and criada.json()["rotulo"] == f"Imagem de {cena['titulo']}"
    assert criada.json()["capitulo_id"] == cena["capitulo_id"]
    assert criada.json()["frame_id"] == cena["id"]  # o frame de onde a imagem é, para o app levar ao lugar

    cliente.delete(f"/imagens/{imagem['id']}")
    assert _lista(cliente, livro["id"]) == []
    assert _favoritar(cliente, livro["id"], tipo="IMAGEM", imagem_id=imagem["id"]).status_code == 404  # na lixeira não se favorita


def teste_imagem_de_outro_livro_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    livro, cena = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="p"))
    prompt = cliente.post(f"/frames/{cena['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])
    outro = _livro_com_capitulos(cliente, capitulos=1, identificador="urn:isbn:2")

    assert _favoritar(cliente, outro["id"], tipo="IMAGEM", imagem_id=imagem["id"]).status_code == 422


# --------------------------------------------------------------------------- #
# A lista
# --------------------------------------------------------------------------- #


def teste_a_lista_vai_do_mais_novo_ao_mais_antigo_e_filtra_por_tipo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)
    jon = cliente.post(f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}).json()
    _favoritar(cliente, livro["id"], tipo="LIVRO")
    _favoritar(cliente, livro["id"], tipo="ELEMENTO", elemento_id=jon["id"])
    _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=capitulo["id"], posicao=0)

    assert [f["tipo"] for f in _lista(cliente, livro["id"])] == ["PARAGRAFO", "ELEMENTO", "LIVRO"]
    assert [f["tipo"] for f in _lista(cliente, livro["id"], tipo="ELEMENTO")] == ["ELEMENTO"]
    assert cliente.get(f"/livros/{livro['id']}/favoritos", params={"tipo": "COISA"}).status_code == 422


def teste_os_favoritos_de_um_livro_nao_aparecem_no_outro(cliente: TestClient) -> None:
    a = _livro_com_capitulos(cliente, capitulos=1)
    b = _livro_com_capitulos(cliente, capitulos=1, identificador="urn:isbn:2")
    _favoritar(cliente, a["id"], tipo="LIVRO")

    assert _lista(cliente, b["id"]) == []
    assert cliente.get("/livros/99999/favoritos").status_code == 404


def teste_desfavoritar_um_que_nao_existe_da_404(cliente: TestClient) -> None:
    assert cliente.delete("/favoritos/99999").status_code == 404


def teste_a_migracao_dos_favoritos_encadeia_e_cria_a_tabela() -> None:
    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "d0e1f2a3b4c5_favoritos.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'" in texto
    assert 'create_table(\n        "favoritos"' in texto and "ondelete=\"CASCADE\"" in texto
