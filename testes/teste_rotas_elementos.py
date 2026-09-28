"""Testes das rotas de elementos e estados (Etapa 6.3).

A parte mais importante aqui é a rota de estados vigentes: ela expõe a consulta do
item 3.4b, e é o que dá contexto à IA no passo 6 do fluxo.
"""

import io

from ebooklib import epub
from fastapi.testclient import TestClient

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


def _epub(*, titulo: str = "A Guerra dos Tronos", identificador: str = "urn:isbn:1", capitulos: int = 4) -> bytes:
    """EPUB simples com N capítulos numerados."""
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")

    itens = []
    for numero in range(1, capitulos + 1):
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


def _livro_importado(cliente: TestClient, **kwargs) -> dict:
    """Importa um livro e devolve o corpo do livro criado."""
    resposta = cliente.post(
        "/livros", files={"arquivo": ("livro.epub", _epub(**kwargs), "application/epub+zip")}
    )
    assert resposta.status_code == 201
    return resposta.json()["livro"]


def _criar(cliente: TestClient, livro_id: int, **corpo) -> dict:
    """Cadastra um elemento e devolve o corpo da resposta."""
    resposta = cliente.post(f"/livros/{livro_id}/elementos", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# --------------------------------------------------------------------------- #
# Cadastro
# --------------------------------------------------------------------------- #


def teste_criar_elemento_com_estado_inicial(cliente: TestClient) -> None:
    """O passo 7 confirma o elemento e o primeiro estado de uma vez.

    Em dois pedidos separados, uma falha no meio deixaria um elemento sem estado.
    """
    livro = _livro_importado(cliente)
    primeiro = livro["capitulos"][0]

    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Ned Stark",
        descricao="Senhor de Winterfell.",
        estado_inicial={"capitulo_id": primeiro["id"], "descricao": "Capa de pele."},
    )

    assert elemento["nome"] == "Ned Stark"
    assert elemento["tipo"] == "PERSONAGEM"
    assert len(elemento["estados"]) == 1
    assert elemento["estados"][0]["descricao"] == "Capa de pele."
    assert elemento["estados"][0]["capitulo_id"] == primeiro["id"]


def teste_criar_elemento_sem_estado_inicial(cliente: TestClient) -> None:
    """O estado é opcional: o usuário pode só reconhecer que o elemento existe."""
    livro = _livro_importado(cliente)

    elemento = _criar(cliente, livro["id"], tipo="AMBIENTE", nome="Winterfell")

    assert elemento["estados"] == []
    assert elemento["descricao"] is None


def teste_elemento_repetido_responde_409_com_o_id_existente(cliente: TestClient) -> None:
    """A extração automática reencontra o mesmo personagem em outro capítulo.

    A resposta traz o id do que já existe, para o app poder oferecer "usar o
    existente" em vez de só reclamar.
    """
    livro = _livro_importado(cliente)
    primeiro = _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")

    resposta = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    )

    assert resposta.status_code == 409
    detalhe = resposta.json()["detail"]
    assert "Jon" in detalhe
    assert str(primeiro["id"]) in detalhe


def teste_mesmo_nome_em_tipos_diferentes_e_permitido(cliente: TestClient) -> None:
    """A região Winterfell e o castelo Winterfell são registros distintos."""
    livro = _livro_importado(cliente)
    _criar(cliente, livro["id"], tipo="AMBIENTE", nome="Winterfell")

    resposta = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "EDIFICACAO", "nome": "Winterfell"}
    )

    assert resposta.status_code == 201


def teste_tipo_invalido_responde_422(cliente: TestClient) -> None:
    """O enum é validado pelo esquema, antes de chegar ao banco."""
    livro = _livro_importado(cliente)

    resposta = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "DRAGAO_VOADOR", "nome": "X"}
    )

    assert resposta.status_code == 422


def teste_criar_elemento_em_livro_inexistente_responde_404(cliente: TestClient) -> None:
    resposta = cliente.post("/livros/999/elementos", json={"tipo": "PERSONAGEM", "nome": "X"})

    assert resposta.status_code == 404


def teste_estado_de_capitulo_de_outro_livro_responde_422(cliente: TestClient) -> None:
    """Nada no banco impede isso, e o dado resultante seria incoerente.

    As chaves estrangeiras de ``elemento_id`` e ``capitulo_id`` são independentes:
    sem esta checagem, o estado apareceria na narrativa errada sem erro visível.
    """
    primeiro_livro = _livro_importado(cliente)
    outro_livro = _livro_importado(cliente, titulo="Outro", identificador="urn:isbn:2")
    capitulo_alheio = outro_livro["capitulos"][0]

    resposta = cliente.post(
        f"/livros/{primeiro_livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "estado_inicial": {"capitulo_id": capitulo_alheio["id"], "descricao": "X"},
        },
    )

    assert resposta.status_code == 422
    assert str(outro_livro["id"]) in resposta.json()["detail"]


# --------------------------------------------------------------------------- #
# Leitura e ajuste
# --------------------------------------------------------------------------- #


def teste_listar_elementos_com_o_estado_mais_recente(cliente: TestClient) -> None:
    """"Mais recente" é pela ordem narrativa, não pela de cadastro."""
    livro = _livro_importado(cliente)
    cap1, _cap2, cap3, _cap4 = livro["capitulos"]

    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": cap3["id"], "descricao": "Com cicatriz."},
    )
    # Cadastrado depois, mas pertence a um capítulo anterior.
    cliente.post(
        f"/elementos/{elemento['id']}/estados",
        json={"capitulo_id": cap1["id"], "descricao": "Sem cicatriz."},
    )

    resposta = cliente.get(f"/livros/{livro['id']}/elementos")

    assert resposta.status_code == 200
    (encontrado,) = resposta.json()
    assert encontrado["total_de_estados"] == 2
    assert encontrado["estado_vigente"]["descricao"] == "Com cicatriz."


def teste_listar_elementos_filtrando_por_tipo(cliente: TestClient) -> None:
    """A tela do app separa por tipo, então a rota filtra."""
    livro = _livro_importado(cliente)
    _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")
    _criar(cliente, livro["id"], tipo="AMBIENTE", nome="Winterfell")

    resposta = cliente.get(f"/livros/{livro['id']}/elementos", params={"tipo": "AMBIENTE"})

    assert [e["nome"] for e in resposta.json()] == ["Winterfell"]


def teste_abrir_elemento_traz_estados_em_ordem_narrativa(cliente: TestClient) -> None:
    """Os estados saem na ordem da história, não na de cadastro."""
    livro = _livro_importado(cliente)
    cap1, _cap2, cap3, _cap4 = livro["capitulos"]

    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": cap3["id"], "descricao": "Terceiro"},
    )
    cliente.post(
        f"/elementos/{elemento['id']}/estados",
        json={"capitulo_id": cap1["id"], "descricao": "Primeiro"},
    )

    resposta = cliente.get(f"/elementos/{elemento['id']}")

    assert [e["descricao"] for e in resposta.json()["estados"]] == ["Primeiro", "Terceiro"]


def teste_ajustar_elemento_muda_so_o_que_foi_enviado(cliente: TestClient) -> None:
    """Mandar o nome não pode apagar a descrição."""
    livro = _livro_importado(cliente)
    elemento = _criar(
        cliente, livro["id"], tipo="PERSONAGEM", nome="Ned", descricao="Senhor de Winterfell."
    )

    resposta = cliente.patch(f"/elementos/{elemento['id']}", json={"nome": "Eddard Stark"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == "Eddard Stark"
    assert corpo["descricao"] == "Senhor de Winterfell."


def teste_ajustar_elemento_ancora_padrao_inexistente_responde_422(cliente: TestClient) -> None:
    """Item 4.5: a referência visual principal precisa ser uma imagem real do catálogo."""
    livro = _livro_importado(cliente)
    elemento = _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")

    resposta = cliente.patch(
        f"/elementos/{elemento['id']}", json={"imagem_ancora_padrao_id": 999}
    )

    assert resposta.status_code == 422
    assert "999" in resposta.json()["detail"]


def teste_renomear_para_um_nome_ja_usado_responde_409(cliente: TestClient) -> None:
    """A unicidade vale também no ajuste."""
    livro = _livro_importado(cliente)
    _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")
    outro = _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Arya")

    resposta = cliente.patch(f"/elementos/{outro['id']}", json={"nome": "Jon"})

    assert resposta.status_code == 409


def teste_ajustar_elemento_mantendo_o_proprio_nome_funciona(cliente: TestClient) -> None:
    """Salvar sem mudar o nome não pode disparar conflito com ele mesmo."""
    livro = _livro_importado(cliente)
    elemento = _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")

    resposta = cliente.patch(
        f"/elementos/{elemento['id']}", json={"nome": "Jon", "descricao": "O bastardo."}
    )

    assert resposta.status_code == 200
    assert resposta.json()["descricao"] == "O bastardo."


def teste_remover_elemento_apaga_os_estados(cliente: TestClient) -> None:
    livro = _livro_importado(cliente)
    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": livro["capitulos"][0]["id"], "descricao": "X"},
    )
    estado_id = elemento["estados"][0]["id"]

    assert cliente.delete(f"/elementos/{elemento['id']}").status_code == 204
    assert cliente.get(f"/elementos/{elemento['id']}").status_code == 404
    assert cliente.patch(f"/estados/{estado_id}", json={"descricao": "Y"}).status_code == 404


def teste_rotas_de_elemento_inexistente_respondem_404(cliente: TestClient) -> None:
    assert cliente.get("/elementos/999").status_code == 404
    assert cliente.patch("/elementos/999", json={"nome": "X"}).status_code == 404
    assert cliente.delete("/elementos/999").status_code == 404
    assert cliente.post("/elementos/999/estados", json={"capitulo_id": 1, "descricao": "X"}).status_code == 404


# --------------------------------------------------------------------------- #
# Estados
# --------------------------------------------------------------------------- #


def teste_dois_estados_no_mesmo_capitulo_sao_permitidos(cliente: TestClient) -> None:
    """Um personagem pode entrar ferido e sair curado (item 3.4b)."""
    livro = _livro_importado(cliente)
    capitulo = livro["capitulos"][0]
    elemento = _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")

    for descricao in ("Ferido.", "Curado."):
        resposta = cliente.post(
            f"/elementos/{elemento['id']}/estados",
            json={"capitulo_id": capitulo["id"], "descricao": descricao},
        )
        assert resposta.status_code == 201

    vigente = cliente.get(f"/livros/{livro['id']}/elementos").json()[0]["estado_vigente"]
    # O desempate entre dois estados do mesmo capítulo é o id: o maior é o mais
    # adiante na narrativa.
    assert vigente["descricao"] == "Curado."


def teste_abrir_estado_traz_a_identidade_do_elemento(cliente: TestClient) -> None:
    """Faltava: só existiam PATCH e DELETE, sem como abrir um estado isolado."""
    livro = _livro_importado(cliente)
    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": livro["capitulos"][0]["id"], "descricao": "Manto negro."},
    )
    estado_id = elemento["estados"][0]["id"]

    resposta = cliente.get(f"/estados/{estado_id}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["id"] == estado_id
    assert corpo["descricao"] == "Manto negro."
    assert corpo["elemento_id"] == elemento["id"]
    assert corpo["elemento_tipo"] == "PERSONAGEM"
    assert corpo["elemento_nome"] == "Jon"


def teste_abrir_estado_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/estados/999").status_code == 404


def teste_ajustar_a_descricao_de_um_estado(cliente: TestClient) -> None:
    livro = _livro_importado(cliente)
    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": livro["capitulos"][0]["id"], "descricao": "Manto."},
    )
    estado_id = elemento["estados"][0]["id"]

    resposta = cliente.patch(f"/estados/{estado_id}", json={"descricao": "Manto negro."})

    assert resposta.status_code == 200
    assert resposta.json()["descricao"] == "Manto negro."


def teste_imagem_ancora_inexistente_responde_422(cliente: TestClient) -> None:
    """Sem esta checagem, a chave estrangeira falharia no commit e daria 500."""
    livro = _livro_importado(cliente)
    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": livro["capitulos"][0]["id"], "descricao": "X"},
    )
    estado_id = elemento["estados"][0]["id"]

    resposta = cliente.patch(f"/estados/{estado_id}", json={"imagem_ancora_id": 999})

    assert resposta.status_code == 422
    assert "999" in resposta.json()["detail"]


def teste_remover_estado_mantem_o_elemento(cliente: TestClient) -> None:
    """Um estado a menos não apaga a identidade do elemento."""
    livro = _livro_importado(cliente)
    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": livro["capitulos"][0]["id"], "descricao": "X"},
    )

    assert cliente.delete(f"/estados/{elemento['estados'][0]['id']}").status_code == 204

    resposta = cliente.get(f"/elementos/{elemento['id']}")
    assert resposta.status_code == 200
    assert resposta.json()["estados"] == []


def teste_remover_estado_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.delete("/estados/999").status_code == 404


# --------------------------------------------------------------------------- #
# Estados vigentes — a consulta do item 3.4b
# --------------------------------------------------------------------------- #


def teste_estados_vigentes_respeitam_a_ordem_narrativa(cliente: TestClient) -> None:
    """No capítulo 2 vale o estado do capítulo 1, porque o do 3 não aconteceu."""
    livro = _livro_importado(cliente)
    cap1, cap2, cap3, _cap4 = livro["capitulos"]

    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": cap1["id"], "descricao": "Sem cicatrizes."},
    )
    cliente.post(
        f"/elementos/{elemento['id']}/estados",
        json={"capitulo_id": cap3["id"], "descricao": "Com cicatriz."},
    )

    def vigente_em(capitulo):
        resposta = cliente.get(f"/capitulos/{capitulo['id']}/estados-vigentes")
        assert resposta.status_code == 200
        return resposta.json()[0]["estado_vigente"]

    assert vigente_em(cap1)["descricao"] == "Sem cicatrizes."
    assert vigente_em(cap2)["descricao"] == "Sem cicatrizes."
    assert vigente_em(cap3)["descricao"] == "Com cicatriz."


def teste_estados_vigentes_ignoram_a_ordem_de_cadastro(cliente: TestClient) -> None:
    """Processar capítulos fora de ordem não confunde a consulta.

    Aqui o estado do capítulo 3 é cadastrado antes do estado do capítulo 1 — o que
    acontece se o usuário revisitar um capítulo antigo. Ordenar por data de
    criação ou por id do estado daria a resposta errada.
    """
    livro = _livro_importado(cliente)
    cap1, _cap2, cap3, _cap4 = livro["capitulos"]

    elemento = _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": cap3["id"], "descricao": "Com cicatriz."},
    )
    tardio = cliente.post(
        f"/elementos/{elemento['id']}/estados",
        json={"capitulo_id": cap1["id"], "descricao": "Sem cicatrizes."},
    ).json()

    # O estado do capítulo 1 tem id MAIOR, mas é anterior na narrativa.
    assert tardio["id"] > elemento["estados"][0]["id"]

    vigente = cliente.get(f"/capitulos/{cap1['id']}/estados-vigentes").json()[0]
    assert vigente["estado_vigente"]["descricao"] == "Sem cicatrizes."


def teste_elemento_sem_estado_anterior_vem_com_vigente_nulo(cliente: TestClient) -> None:
    """O nulo é informação: significa primeira aparição.

    É o caso em que não há estado anterior para mandar de contexto à IA (item 4.4).
    """
    livro = _livro_importado(cliente)
    cap1, _cap2, cap3, _cap4 = livro["capitulos"]
    _criar(
        cliente,
        livro["id"],
        tipo="PERSONAGEM",
        nome="Jon",
        estado_inicial={"capitulo_id": cap3["id"], "descricao": "Aparece no 3."},
    )

    no_primeiro = cliente.get(f"/capitulos/{cap1['id']}/estados-vigentes").json()

    assert len(no_primeiro) == 1
    assert no_primeiro[0]["nome"] == "Jon"
    assert no_primeiro[0]["estado_vigente"] is None


def teste_estados_vigentes_trazem_todos_os_elementos_do_livro(cliente: TestClient) -> None:
    """A tela de revisão precisa da lista completa, não só de quem já apareceu."""
    livro = _livro_importado(cliente)
    cap1 = livro["capitulos"][0]
    _criar(cliente, livro["id"], tipo="PERSONAGEM", nome="Jon")
    _criar(cliente, livro["id"], tipo="AMBIENTE", nome="Winterfell")
    _criar(cliente, livro["id"], tipo="OBJETO", nome="Garralonga")

    vigentes = cliente.get(f"/capitulos/{cap1['id']}/estados-vigentes").json()

    assert len(vigentes) == 3
    assert all(v["estado_vigente"] is None for v in vigentes)


def teste_estados_vigentes_de_capitulo_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/capitulos/999/estados-vigentes").status_code == 404


def teste_estados_vigentes_nao_misturam_livros(cliente: TestClient) -> None:
    """Cada livro tem os seus elementos, e a consulta não os cruza."""
    primeiro = _livro_importado(cliente)
    segundo = _livro_importado(cliente, titulo="Outro", identificador="urn:isbn:2")
    _criar(cliente, primeiro["id"], tipo="PERSONAGEM", nome="Jon")
    _criar(cliente, segundo["id"], tipo="PERSONAGEM", nome="Frodo")

    vigentes = cliente.get(
        f"/capitulos/{primeiro['capitulos'][0]['id']}/estados-vigentes"
    ).json()

    assert [v["nome"] for v in vigentes] == ["Jon"]
