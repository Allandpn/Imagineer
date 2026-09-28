"""Testes das rotas de livros e capítulos (Etapa 6.2).

Os testes exercitam a API de verdade, pelo ``TestClient``, com o banco trocado
por SQLite em memória — então cobrem o caminho inteiro: HTTP, esquema de resposta,
serviço de importação e banco.
"""

import io

from ebooklib import epub
from fastapi.testclient import TestClient

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, PerfilRenderizacaoSugerido

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


def _epub_de_teste(
    *,
    titulo: str = "A Guerra dos Tronos",
    identificador: str = "urn:isbn:9788580410150",
    capitulos: list[tuple[str, str | None]] | None = None,
) -> bytes:
    """Gera os bytes de um EPUB simples para enviar à rota de importação."""
    if capitulos is None:
        capitulos = [
            (f"<p>{TEXTO_LONGO * 6}</p>", "Bran"),
            (f"<p>{TEXTO_LONGO * 6}</p>", "Catelyn"),
            (f"<p>{TEXTO_LONGO * 6}</p>", "Créditos"),
        ]

    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")
    livro.add_author("George R. R. Martin")

    itens = []
    for indice, (html, titulo_do_indice) in enumerate(capitulos, start=1):
        item = epub.EpubHtml(
            title=titulo_do_indice or "", file_name=f"c{indice}.xhtml", lang="pt-BR"
        )
        item.content = html
        livro.add_item(item)
        itens.append(item)

    livro.toc = tuple(item for item in itens if item.title)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", *itens]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


def _importar(cliente: TestClient, **kwargs):
    """Envia um EPUB para POST /livros e devolve a resposta."""
    return cliente.post(
        "/livros",
        files={"arquivo": ("guerra.epub", _epub_de_teste(**kwargs), "application/epub+zip")},
    )


# --------------------------------------------------------------------------- #
# POST /livros
# --------------------------------------------------------------------------- #


def teste_importar_devolve_o_livro_com_os_capitulos(cliente: TestClient) -> None:
    """A importação responde 201 com a estrutura que o app vai mostrar."""
    resposta = _importar(cliente)

    assert resposta.status_code == 201
    corpo = resposta.json()
    livro = corpo["livro"]
    assert livro["titulo"] == "A Guerra dos Tronos"
    assert livro["autor"] == "George R. R. Martin"
    assert livro["total_de_capitulos"] == 3
    assert livro["capitulos_ignorados"] == 1
    assert [c["titulo"] for c in livro["capitulos"]] == ["Bran", "Catelyn", "Créditos"]
    assert corpo["livros_semelhantes"] == []


def teste_listagem_de_capitulos_nao_traz_o_texto(cliente: TestClient) -> None:
    """A decisão de desenho mais importante da Etapa 6.2.

    Devolver o texto de todos os capítulos daria respostas de megabytes. A
    listagem traz o tamanho, que é o que o app usa para mostrar se o capítulo é
    curto ou longo.
    """
    livro = _importar(cliente).json()["livro"]

    primeiro = livro["capitulos"][0]
    assert "texto" not in primeiro
    assert primeiro["tamanho_do_texto"] > 0


def teste_importar_o_mesmo_livro_avisa_em_vez_de_impedir(cliente: TestClient) -> None:
    """Reimportar é permitido (item 3.4a); a resposta traz o semelhante."""
    primeiro = _importar(cliente).json()["livro"]
    segunda = _importar(cliente)

    assert segunda.status_code == 201
    semelhantes = segunda.json()["livros_semelhantes"]
    assert [s["id"] for s in semelhantes] == [primeiro["id"]]


def teste_identificadores_diferentes_nao_sao_semelhantes(cliente: TestClient) -> None:
    """O aviso é pelo identificador do EPUB, não pelo título."""
    _importar(cliente, identificador="urn:isbn:1111111111111")
    segunda = _importar(cliente, identificador="urn:isbn:2222222222222")

    assert segunda.json()["livros_semelhantes"] == []


def teste_arquivo_que_nao_e_epub_responde_422(cliente: TestClient) -> None:
    """O pedido está bem formado; o conteúdo é que não serve.

    E a mensagem precisa ser a do serviço, não um traço de pilha do zipfile.
    """
    resposta = cliente.post(
        "/livros", files={"arquivo": ("qualquer.txt", b"isto nao e um epub", "text/plain")}
    )

    assert resposta.status_code == 422
    assert "qualquer.txt" in resposta.json()["detail"]


def teste_arquivo_vazio_responde_422(cliente: TestClient) -> None:
    """Um upload sem bytes não deve virar erro obscuro mais adiante."""
    resposta = cliente.post("/livros", files={"arquivo": ("vazio.epub", b"", "application/epub+zip")})

    assert resposta.status_code == 422
    assert "vazio" in resposta.json()["detail"].lower()


def teste_arquivo_acima_do_limite_responde_413(cliente: TestClient, monkeypatch) -> None:
    """O limite protege o Raspberry Pi, e é checado durante a leitura.

    O limite real é de 60 MB; aqui ele é reduzido para o teste não precisar
    fabricar 60 MB de dados.
    """
    from imagineer.rotas import livros as rotas_livros

    monkeypatch.setattr(rotas_livros, "TAMANHO_MAXIMO_DO_EPUB", 1024)

    resposta = cliente.post(
        "/livros",
        files={"arquivo": ("grande.epub", b"x" * 5000, "application/epub+zip")},
    )

    assert resposta.status_code == 413
    assert "limite" in resposta.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# GET /livros e GET /livros/{id}
# --------------------------------------------------------------------------- #


def teste_listar_livros_traz_as_contagens(cliente: TestClient) -> None:
    """A listagem da biblioteca, com quantos capítulos cada livro tem."""
    _importar(cliente, titulo="Zebra")
    _importar(cliente, titulo="Abacaxi", identificador="urn:isbn:3333333333333")

    resposta = cliente.get("/livros")

    assert resposta.status_code == 200
    livros = resposta.json()
    # Ordem alfabética de título.
    assert [l["titulo"] for l in livros] == ["Abacaxi", "Zebra"]
    assert livros[0]["total_de_capitulos"] == 3
    assert livros[0]["capitulos_ignorados"] == 1


def teste_listar_livros_vazio(cliente: TestClient) -> None:
    """Sem livros, a resposta é uma lista vazia — não um erro."""
    assert cliente.get("/livros").json() == []


def teste_abrir_livro_traz_capitulos_em_ordem(cliente: TestClient) -> None:
    """A ordem é a de leitura, definida por ``Capitulo.ordem`` (item 3.4a)."""
    livro_id = _importar(cliente).json()["livro"]["id"]

    resposta = cliente.get(f"/livros/{livro_id}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [c["ordem"] for c in corpo["capitulos"]] == [1, 2, 3]
    assert corpo["identificador_epub"] == "urn:isbn:9788580410150"
    assert corpo["perfil_renderizacao_padrao_id"] is None


def teste_abrir_livro_inexistente_responde_404(cliente: TestClient) -> None:
    resposta = cliente.get("/livros/999")

    assert resposta.status_code == 404
    assert "999" in resposta.json()["detail"]


# --------------------------------------------------------------------------- #
# DELETE /livros/{id}
# --------------------------------------------------------------------------- #


def teste_remover_livro_apaga_os_capitulos(cliente: TestClient) -> None:
    """O cascade da Etapa 3 vale também pela API."""
    livro = _importar(cliente).json()["livro"]
    capitulo_id = livro["capitulos"][0]["id"]

    assert cliente.delete(f"/livros/{livro['id']}").status_code == 204

    assert cliente.get(f"/livros/{livro['id']}").status_code == 404
    assert cliente.get(f"/capitulos/{capitulo_id}").status_code == 404


def teste_remover_livro_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.delete("/livros/999").status_code == 404


# --------------------------------------------------------------------------- #
# GET e PATCH /capitulos/{id}
# --------------------------------------------------------------------------- #


def teste_abrir_capitulo_traz_o_texto(cliente: TestClient) -> None:
    """É a única rota que devolve o texto do capítulo."""
    livro = _importar(cliente).json()["livro"]
    capitulo_id = livro["capitulos"][0]["id"]

    resposta = cliente.get(f"/capitulos/{capitulo_id}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "Este é um parágrafo" in corpo["texto"]
    assert corpo["tamanho_do_texto"] == len(corpo["texto"])
    assert corpo["livro_id"] == livro["id"]


def teste_abrir_capitulo_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/capitulos/999").status_code == 404


def teste_desmarcar_capitulo_sugerido_como_ignorado(cliente: TestClient) -> None:
    """O usuário confirma ou desfaz a sugestão da importação (item 2.2)."""
    livro = _importar(cliente).json()["livro"]
    creditos = next(c for c in livro["capitulos"] if c["titulo"] == "Créditos")
    assert creditos["ignorado"] is True

    resposta = cliente.patch(f"/capitulos/{creditos['id']}", json={"ignorado": False})

    assert resposta.status_code == 200
    assert resposta.json()["ignorado"] is False
    # E ficou gravado.
    assert cliente.get(f"/capitulos/{creditos['id']}").json()["ignorado"] is False


def teste_ajustar_so_o_titulo_nao_mexe_no_ignorado(cliente: TestClient) -> None:
    """Mandar um campo só não pode sobrescrever os outros.

    É o que ``exclude_unset`` garante: "não mandei" é diferente de "mandei nulo".
    """
    livro = _importar(cliente).json()["livro"]
    creditos = next(c for c in livro["capitulos"] if c["titulo"] == "Créditos")

    resposta = cliente.patch(f"/capitulos/{creditos['id']}", json={"titulo": "Ficha"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["titulo"] == "Ficha"
    assert corpo["ignorado"] is True


def teste_ajuste_reflete_nas_contagens_do_livro(cliente: TestClient) -> None:
    """Desmarcar um capítulo muda o total de ignorados na listagem."""
    livro = _importar(cliente).json()["livro"]
    creditos = next(c for c in livro["capitulos"] if c["titulo"] == "Créditos")

    cliente.patch(f"/capitulos/{creditos['id']}", json={"ignorado": False})

    assert cliente.get(f"/livros/{livro['id']}").json()["capitulos_ignorados"] == 0
    assert cliente.get("/livros").json()[0]["capitulos_ignorados"] == 0


def teste_ajustar_capitulo_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.patch("/capitulos/999", json={"ignorado": True}).status_code == 404


# --------------------------------------------------------------------------- #
# POST /livros/{id}/perfis-renderizacao/sugestao (rascunho, pendência da Etapa 8)
# --------------------------------------------------------------------------- #


def teste_sugerir_perfil_devolve_o_que_o_provedor_deu(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Não persiste nada — só repassa a sugestão do provedor."""
    usar_provedor_falso(
        ProvedorFalso(
            perfil_sugerido=PerfilRenderizacaoSugerido(
                estilo="aquarela sombria",
                artista_referencia="Alan Lee",
                iluminacao="luz de vela",
                paleta="tons terrosos",
                formato="retrato",
            )
        )
    )
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    assert resposta.status_code == 200
    assert resposta.json() == {
        "estilo": "aquarela sombria",
        "artista_referencia": "Alan Lee",
        "iluminacao": "luz de vela",
        "paleta": "tons terrosos",
        "formato": "retrato",
        "categoria_estilo": None,
        "reconheceu_a_obra": True,
        "modelo": MODELO_FALSO,
    }
    # Nada foi criado — é só uma sugestão solta.
    assert cliente.get("/perfis-renderizacao").json() == []


def teste_sugerir_perfil_avisa_quando_nao_reconhece_a_obra(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Item 6.5: o app precisa distinguir "não reconheci o livro" de um
    formulário só com campos vazios sem explicação nenhuma."""
    usar_provedor_falso(
        ProvedorFalso(
            perfil_sugerido=PerfilRenderizacaoSugerido(
                estilo=None,
                artista_referencia=None,
                iluminacao=None,
                paleta=None,
                formato=None,
                reconheceu_a_obra=False,
            )
        )
    )
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    assert resposta.status_code == 200
    assert resposta.json()["reconheceu_a_obra"] is False


def teste_sugerir_perfil_manda_os_metadados_do_livro(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O provedor recebe título/autor/idioma, nunca o texto de um capítulo."""
    provedor = usar_provedor_falso(ProvedorFalso())
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    (chamada,) = provedor.chamadas_de_sugestao_de_perfil
    assert chamada == {
        "titulo": "A Guerra dos Tronos",
        "autor": "George R. R. Martin",
        "idioma": "pt-BR",
        "categoria_estilo": None,
        "modelo": MODELO_FALSO,
    }


def teste_sugerir_perfil_manda_a_categoria_escolhida(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O usuário pode escolher a categoria (item 6.5) — a IA detalha dentro dela."""
    provedor = usar_provedor_falso(ProvedorFalso())
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post(
        f"/livros/{livro['id']}/perfis-renderizacao/sugestao",
        json={"categoria_estilo": "PINTURA_A_OLEO"},
    )

    assert resposta.status_code == 200
    (chamada,) = provedor.chamadas_de_sugestao_de_perfil
    assert chamada["categoria_estilo"].name == "PINTURA_A_OLEO"


def teste_sugerir_perfil_sem_categoria_funciona_igual(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Sem corpo nenhum no pedido, continua funcionando (categoria opcional)."""
    usar_provedor_falso(ProvedorFalso())
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    assert resposta.status_code == 200


def teste_sugerir_perfil_livro_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post("/livros/999/perfis-renderizacao/sugestao")

    assert resposta.status_code == 404


def teste_sugerir_perfil_sem_modelo_escolhido_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _importar(cliente).json()["livro"]

    resposta = cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    assert resposta.status_code == 422


def teste_sugerir_perfil_sem_chave_de_api_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ChaveDeApiAusente("sem chave")))
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    assert resposta.status_code == 422


def teste_sugerir_perfil_erro_do_provedor_responde_502(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("o provedor caiu")))
    livro = _importar(cliente).json()["livro"]
    cliente.put("/configuracao", json={"modelo_perfil": MODELO_FALSO})

    resposta = cliente.post(f"/livros/{livro['id']}/perfis-renderizacao/sugestao")

    assert resposta.status_code == 502
