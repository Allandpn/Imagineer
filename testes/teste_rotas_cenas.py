"""Testes das rotas de cenas e perfis de renderização (Etapas 6.4 e 6.5)."""

import io

from ebooklib import epub
from fastapi.testclient import TestClient

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


def _epub(*, titulo: str = "A Guerra dos Tronos", identificador: str = "urn:isbn:1") -> bytes:
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")

    itens = []
    for numero in (1, 2, 3):
        item = epub.EpubHtml(title=f"Capítulo {numero}", file_name=f"c{numero}.xhtml", lang="pt-BR")
        item.content = f"<p>{TEXTO_LONGO * 6}</p>"
        livro.add_item(item)
        itens.append(item)

    livro.toc = tuple(itens)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", *itens]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


def _livro(cliente: TestClient, **kwargs) -> dict:
    resposta = cliente.post(
        "/livros", files={"arquivo": ("l.epub", _epub(**kwargs), "application/epub+zip")}
    )
    assert resposta.status_code == 201
    return resposta.json()["livro"]


def _elemento_com_estado(
    cliente: TestClient, livro_id: int, capitulo_id: int, nome: str, tipo: str = "PERSONAGEM"
) -> dict:
    """Cria um elemento já com um estado, e devolve o corpo do elemento."""
    resposta = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={
            "tipo": tipo,
            "nome": nome,
            "estado_inicial": {"capitulo_id": capitulo_id, "descricao": f"{nome} está assim."},
        },
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# --------------------------------------------------------------------------- #
# Cenas
# --------------------------------------------------------------------------- #


def teste_criar_cena_com_atributos_situacionais(cliente: TestClient) -> None:
    """Horário, clima e humor ficam na própria cena, sem entidade "Contexto"."""
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]

    resposta = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={
            "titulo": "A chegada do rei",
            "descricao": "A comitiva atravessa o portão.",
            "horario": "fim de tarde",
            "clima": "neve fina",
            "humor": "tensão contida",
        },
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["titulo"] == "A chegada do rei"
    assert corpo["horario"] == "fim de tarde"
    assert corpo["clima"] == "neve fina"
    assert corpo["humor"] == "tensão contida"
    assert corpo["elementos"] == []
    assert corpo["total_de_elementos"] == 0


def teste_cena_devolve_o_estado_com_a_identidade_do_elemento(cliente: TestClient) -> None:
    """A tela mostra "Ned Stark: capa de pele", não o id de um estado solto."""
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned Stark")

    resposta = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [ned["estados"][0]["id"]]},
    )

    (elemento,) = resposta.json()["elementos"]
    assert elemento["nome"] == "Ned Stark"
    assert elemento["tipo"] == "PERSONAGEM"
    assert elemento["descricao"] == "Ned Stark está assim."
    assert elemento["estado_id"] == ned["estados"][0]["id"]
    assert elemento["elemento_id"] == ned["id"]


def teste_listar_cenas_de_um_capitulo(cliente: TestClient) -> None:
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned")
    cliente.post(f"/capitulos/{capitulo['id']}/cenas", json={"titulo": "Primeira"})
    cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "Segunda", "estados_ids": [ned["estados"][0]["id"]]},
    )

    resposta = cliente.get(f"/capitulos/{capitulo['id']}/cenas")

    assert resposta.status_code == 200
    cenas = resposta.json()
    assert [c["titulo"] for c in cenas] == ["Primeira", "Segunda"]
    assert [c["total_de_elementos"] for c in cenas] == [0, 1]
    # A listagem não traz os elementos, só a contagem.
    assert "elementos" not in cenas[0]


def teste_cenas_de_capitulos_diferentes_nao_se_misturam(cliente: TestClient) -> None:
    livro = _livro(cliente)
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    cliente.post(f"/capitulos/{primeiro['id']}/cenas", json={"titulo": "Do primeiro"})
    cliente.post(f"/capitulos/{segundo['id']}/cenas", json={"titulo": "Do segundo"})

    assert [c["titulo"] for c in cliente.get(f"/capitulos/{primeiro['id']}/cenas").json()] == [
        "Do primeiro"
    ]


def teste_ajustar_cena_muda_so_o_que_foi_enviado(cliente: TestClient) -> None:
    livro = _livro(cliente)
    cena = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/cenas",
        json={"titulo": "No pátio", "clima": "neve"},
    ).json()

    resposta = cliente.patch(f"/cenas/{cena['id']}", json={"humor": "tensão"})

    corpo = resposta.json()
    assert corpo["humor"] == "tensão"
    assert corpo["clima"] == "neve"
    assert corpo["titulo"] == "No pátio"


def teste_definir_estados_substitui_a_lista_inteira(cliente: TestClient) -> None:
    """É PUT: o app manda o conjunto todo, como a tela funciona."""
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned")
    arya = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Arya")
    cena = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [ned["estados"][0]["id"]]},
    ).json()

    resposta = cliente.put(
        f"/cenas/{cena['id']}/estados", json={"estados_ids": [arya["estados"][0]["id"]]}
    )

    assert resposta.status_code == 200
    assert [e["nome"] for e in resposta.json()["elementos"]] == ["Arya"]


def teste_definir_estados_com_lista_vazia_esvazia_a_cena(cliente: TestClient) -> None:
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned")
    cena = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [ned["estados"][0]["id"]]},
    ).json()

    resposta = cliente.put(f"/cenas/{cena['id']}/estados", json={"estados_ids": []})

    assert resposta.json()["elementos"] == []
    # E o estado continua existindo: só a ligação foi desfeita.
    assert cliente.get(f"/elementos/{ned['id']}").json()["estados"] != []


def teste_ids_repetidos_contam_uma_vez(cliente: TestClient) -> None:
    """A chave primária da associação já impediria o repetido.

    Devolver erro por isso só criaria trabalho para o app.
    """
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned")
    estado_id = ned["estados"][0]["id"]

    resposta = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [estado_id, estado_id, estado_id]},
    )

    assert resposta.status_code == 201
    assert resposta.json()["total_de_elementos"] == 1


def teste_estado_inexistente_na_cena_responde_404(cliente: TestClient) -> None:
    livro = _livro(cliente)

    resposta = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [999]},
    )

    assert resposta.status_code == 404
    assert "999" in resposta.json()["detail"]


def teste_estado_de_outro_livro_na_cena_responde_422(cliente: TestClient) -> None:
    """Mesmo problema do item 6.3: o banco não impede, e o prompt sairia errado."""
    primeiro = _livro(cliente)
    segundo = _livro(cliente, titulo="Outro", identificador="urn:isbn:2")
    alheio = _elemento_com_estado(
        cliente, segundo["id"], segundo["capitulos"][0]["id"], "Frodo"
    )

    resposta = cliente.post(
        f"/capitulos/{primeiro['capitulos'][0]['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [alheio["estados"][0]["id"]]},
    )

    assert resposta.status_code == 422
    assert "outro livro" in resposta.json()["detail"]


def teste_remover_cena_nao_apaga_os_estados(cliente: TestClient) -> None:
    """Um estado pertence ao elemento e à narrativa, não à cena que o citou."""
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned")
    cena = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [ned["estados"][0]["id"]]},
    ).json()

    assert cliente.delete(f"/cenas/{cena['id']}").status_code == 204

    assert cliente.get(f"/cenas/{cena['id']}").status_code == 404
    assert len(cliente.get(f"/elementos/{ned['id']}").json()["estados"]) == 1


def teste_remover_elemento_tira_ele_da_cena(cliente: TestClient) -> None:
    """O caminho inverso: apagar o elemento desfaz a ligação com a cena."""
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned")
    cena = cliente.post(
        f"/capitulos/{capitulo['id']}/cenas",
        json={"titulo": "No pátio", "estados_ids": [ned["estados"][0]["id"]]},
    ).json()

    cliente.delete(f"/elementos/{ned['id']}")

    resposta = cliente.get(f"/cenas/{cena['id']}")
    assert resposta.status_code == 200
    assert resposta.json()["elementos"] == []


def teste_rotas_de_cena_inexistente_respondem_404(cliente: TestClient) -> None:
    assert cliente.get("/cenas/999").status_code == 404
    assert cliente.patch("/cenas/999", json={"titulo": "X"}).status_code == 404
    assert cliente.delete("/cenas/999").status_code == 404
    assert cliente.put("/cenas/999/estados", json={"estados_ids": []}).status_code == 404
    assert cliente.get("/capitulos/999/cenas").status_code == 404
    assert cliente.post("/capitulos/999/cenas", json={"titulo": "X"}).status_code == 404


def teste_cena_sem_titulo_responde_422(cliente: TestClient) -> None:
    """O título é obrigatório: é como a cena aparece na lista."""
    livro = _livro(cliente)

    resposta = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/cenas", json={"titulo": ""}
    )

    assert resposta.status_code == 422


# --------------------------------------------------------------------------- #
# Perfis de renderização
# --------------------------------------------------------------------------- #


def teste_criar_e_listar_perfis(cliente: TestClient) -> None:
    """Os perfis são compartilhados entre livros, então a lista é global."""
    cliente.post("/perfis-renderizacao", json={"nome": "Zebra"})
    resposta = cliente.post(
        "/perfis-renderizacao",
        json={
            "nome": "Aquarela sombria",
            "estilo": "aquarela",
            "iluminacao": "penumbra de vela",
            "paleta": "tons frios",
            "formato": "16:9",
            "modelo_alvo": "alguma ferramenta",
        },
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "Aquarela sombria"
    assert corpo["iluminacao"] == "penumbra de vela"

    nomes = [p["nome"] for p in cliente.get("/perfis-renderizacao").json()]
    assert nomes == ["Aquarela sombria", "Zebra"]


def teste_perfil_so_com_nome_e_valido(cliente: TestClient) -> None:
    """Cada ferramenta entende um subconjunto dos campos (item 3.4c)."""
    resposta = cliente.post("/perfis-renderizacao", json={"nome": "Mínimo"})

    assert resposta.status_code == 201
    assert resposta.json()["estilo"] is None


def teste_nome_de_perfil_repetido_responde_409(cliente: TestClient) -> None:
    """Dois perfis com o mesmo nome seriam indistinguíveis na tela de escolha."""
    cliente.post("/perfis-renderizacao", json={"nome": "Aquarela"})

    resposta = cliente.post("/perfis-renderizacao", json={"nome": "Aquarela"})

    assert resposta.status_code == 409
    assert "Aquarela" in resposta.json()["detail"]


def teste_ajustar_perfil_muda_so_o_que_foi_enviado(cliente: TestClient) -> None:
    perfil = cliente.post(
        "/perfis-renderizacao", json={"nome": "Aquarela", "estilo": "aquarela"}
    ).json()

    resposta = cliente.patch(
        f"/perfis-renderizacao/{perfil['id']}", json={"paleta": "tons quentes"}
    )

    corpo = resposta.json()
    assert corpo["paleta"] == "tons quentes"
    assert corpo["estilo"] == "aquarela"
    assert corpo["nome"] == "Aquarela"


def teste_renomear_perfil_para_nome_existente_responde_409(cliente: TestClient) -> None:
    cliente.post("/perfis-renderizacao", json={"nome": "Primeiro"})
    segundo = cliente.post("/perfis-renderizacao", json={"nome": "Segundo"}).json()

    resposta = cliente.patch(f"/perfis-renderizacao/{segundo['id']}", json={"nome": "Primeiro"})

    assert resposta.status_code == 409


def teste_rotas_de_perfil_inexistente_respondem_404(cliente: TestClient) -> None:
    assert cliente.get("/perfis-renderizacao/999").status_code == 404
    assert cliente.patch("/perfis-renderizacao/999", json={"nome": "X"}).status_code == 404
    assert cliente.delete("/perfis-renderizacao/999").status_code == 404


# --------------------------------------------------------------------------- #
# Perfil padrão do livro
# --------------------------------------------------------------------------- #


def teste_definir_o_perfil_padrao_do_livro(cliente: TestClient) -> None:
    livro = _livro(cliente)
    perfil = cliente.post("/perfis-renderizacao", json={"nome": "Aquarela"}).json()

    resposta = cliente.patch(
        f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]}
    )

    assert resposta.status_code == 200
    assert resposta.json()["perfil_renderizacao_padrao_id"] == perfil["id"]


def teste_apagar_o_perfil_deixa_o_livro_de_pe(cliente: TestClient) -> None:
    """O ON DELETE SET NULL do item 3.4c, valendo pela API.

    Apagar um estilo não pode apagar trabalho de catalogação.
    """
    livro = _livro(cliente)
    perfil = cliente.post("/perfis-renderizacao", json={"nome": "Aquarela"}).json()
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})

    assert cliente.delete(f"/perfis-renderizacao/{perfil['id']}").status_code == 204

    resposta = cliente.get(f"/livros/{livro['id']}")
    assert resposta.status_code == 200
    assert resposta.json()["perfil_renderizacao_padrao_id"] is None
    assert resposta.json()["total_de_capitulos"] == 3


def teste_perfil_inexistente_no_livro_responde_422(cliente: TestClient) -> None:
    """Sem a checagem, a chave estrangeira falharia no commit e daria 500."""
    livro = _livro(cliente)

    resposta = cliente.patch(
        f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": 999}
    )

    assert resposta.status_code == 422
    assert "999" in resposta.json()["detail"]


def teste_corrigir_metadados_errados_do_livro(cliente: TestClient) -> None:
    """Um EPUB pode declarar os metadados de outro livro.

    Caso real da validação: um arquivo de *Treasure Island* apresentava-se como
    *Death and the Afterlife in Ancient Egypt*. A importação é fiel ao arquivo,
    então quem conserta é o usuário.
    """
    livro = _livro(cliente, titulo="Death and the Afterlife in Ancient Egypt")

    resposta = cliente.patch(
        f"/livros/{livro['id']}",
        json={"titulo": "Treasure Island", "autor": "Robert Louis Stevenson", "idioma": "en"},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["titulo"] == "Treasure Island"
    assert corpo["autor"] == "Robert Louis Stevenson"
    assert corpo["idioma"] == "en"
    # E os capítulos continuam lá.
    assert len(corpo["capitulos"]) == 3


def teste_ajustar_livro_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.patch("/livros/999", json={"titulo": "X"}).status_code == 404
