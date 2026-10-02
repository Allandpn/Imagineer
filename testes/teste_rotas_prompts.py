"""Testes das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

import io

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient

from imagineer import configuracao as modulo_de_configuracao
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, PromptMontado
from imagineer.modelos.prompt import Prompt

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


@pytest.fixture(autouse=True)
def _diretorio_de_imagens(tmp_path, monkeypatch):
    """Usa uma pasta temporária como DIRETORIO_IMAGENS, em vez do caminho real.

    Sem isto, o catálogo tentaria gravar em ``/dados/imagens`` — inexistente numa
    máquina de desenvolvimento e proibido de criar em produção às cegas.
    """
    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("DIRETORIO_IMAGENS", str(tmp_path))
    try:
        yield tmp_path
    finally:
        obter.cache_clear()


def _epub(*, titulo: str = "A Guerra dos Tronos", identificador: str = "urn:isbn:1") -> bytes:
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")

    item = epub.EpubHtml(title="Capítulo 1", file_name="c1.xhtml", lang="pt-BR")
    item.content = f"<p>{TEXTO_LONGO * 6}</p>"
    livro.add_item(item)

    livro.toc = (item,)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", item]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


def _livro(cliente: TestClient, **kwargs) -> dict:
    resposta = cliente.post(
        "/livros", files={"arquivo": ("l.epub", _epub(**kwargs), "application/epub+zip")}
    )
    assert resposta.status_code == 201
    return resposta.json()["livro"]


def _elemento_com_estado(cliente: TestClient, livro_id: int, capitulo_id: int, nome: str) -> dict:
    resposta = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": nome,
            "estado_inicial": {"capitulo_id": capitulo_id, "descricao": f"{nome} está assim."},
        },
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _frame(
    cliente: TestClient,
    capitulo_id: int,
    estados_ids: list[int] | None = None,
    tipo: str = "CENA",
) -> dict:
    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"tipo": tipo, "titulo": "No pátio", "estados_ids": estados_ids or []},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _perfil(cliente: TestClient, **kwargs) -> dict:
    corpo = {"nome": "Aquarela sombria", "estilo": "aquarela"} | kwargs
    resposta = cliente.post("/perfis-renderizacao", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _montar_frame_completo(
    cliente: TestClient,
    usar_provedor_falso,
    provedor: ProvedorFalso | None = None,
    tipo: str = "CENA",
) -> tuple[dict, dict]:
    """Livro, capítulo, elemento com estado, frame com ele e perfil padrão do livro."""
    usar_provedor_falso(provedor or ProvedorFalso(prompt="uma pintura de teste"))
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned Stark")
    frame = _frame(cliente, capitulo["id"], [ned["estados"][0]["id"]], tipo=tipo)
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    # modelo_extracao também é usado nas leituras profundas (item 4.4), que
    # rodam dentro de POST /frames/{id}/prompts antes de montar o prompt.
    cliente.put(
        "/configuracao",
        json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO},
    )
    return livro, frame


# --------------------------------------------------------------------------- #
# Criar prompt
# --------------------------------------------------------------------------- #


def teste_criar_prompt_usa_perfil_padrao_do_livro_e_modelo_da_configuracao(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso(prompt="uma pintura de teste")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["texto"] == "uma pintura de teste"
    assert corpo["modelo_ia"] == MODELO_FALSO
    assert corpo["imagens"] == []

    # A leitura profunda por elemento (item 4.4) já rodou antes de montar o
    # prompt e sobrescreveu a descrição do estado — o livro é a fonte de verdade.
    chamada = provedor.chamadas_de_prompt[0]
    assert "Ned Stark: watercolor-ready appearance description" in chamada["elementos"]
    assert "Aquarela sombria" in chamada["perfil_renderizacao"]
    assert "aquarela" in chamada["perfil_renderizacao"]


def teste_formato_padrao_e_16_9_para_cena_sem_override(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Item 4.5/4.7: sem formato no perfil, o padrão vem do tipo do frame."""
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_prompt[0]
    assert "16:9" in chamada["perfil_renderizacao"]
    assert "landscape" in chamada["perfil_renderizacao"]


def teste_formato_padrao_e_2_3_para_personagem_sem_override(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="PERSONAGEM")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_prompt[0]
    assert "2:3" in chamada["perfil_renderizacao"]
    assert "portrait" in chamada["perfil_renderizacao"]


def teste_formato_do_perfil_sobrepoe_o_padrao_automatico(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O override do perfil vale pros dois tipos de frame igualmente —
    mesmo princípio de 'explícito sempre vence' usado no resto do prompt."""
    provedor = usar_provedor_falso(ProvedorFalso(prompt="pintura"))
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned Stark")
    frame = _frame(cliente, capitulo["id"], [ned["estados"][0]["id"]], tipo="CENA")
    perfil = _perfil(cliente, formato="1:1, square")
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put(
        "/configuracao",
        json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO},
    )

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_prompt[0]
    assert "1:1, square" in chamada["perfil_renderizacao"]
    assert "16:9" not in chamada["perfil_renderizacao"]


def teste_criar_prompt_inclui_identidade_do_elemento_no_contexto(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """"Nome (identidade): aparência" — a IA que monta o prompt (e a que
    fundamenta uma cena) passam a receber a identidade do elemento, não só a
    aparência (item 4.5) — é o que permite deixar o gênero explícito."""
    provedor = ProvedorFalso(prompt="uma pintura de teste")
    usar_provedor_falso(provedor)
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Ned Stark",
            "descricao": "um lorde do norte, homem de meia-idade",
            "estado_inicial": {"capitulo_id": capitulo["id"], "descricao": "Ned está assim."},
        },
    ).json()
    frame = _frame(cliente, capitulo["id"], [elemento["estados"][0]["id"]], tipo="PERSONAGEM")
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put(
        "/configuracao",
        json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO},
    )

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    chamada = provedor.chamadas_de_prompt[0]
    assert any(
        e.startswith("Ned Stark (um lorde do norte, homem de meia-idade):")
        for e in chamada["elementos"]
    )


def teste_criar_prompt_sem_identidade_do_elemento_omite_os_parenteses(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Sem identidade cadastrada, o formato cai pro que já existia — sem
    parênteses vazios nem "None" aparecendo no meio do prompt."""
    provedor = ProvedorFalso(prompt="uma pintura de teste")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_prompt[0]
    assert "Ned Stark: watercolor-ready appearance description" in chamada["elementos"]
    assert not any("(" in e for e in chamada["elementos"])


def teste_criar_prompt_manda_comentario_com_prioridade(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O comentário do usuário chega até o provedor (item 4.4)."""
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    resposta = cliente.post(
        f"/frames/{frame['id']}/prompts", json={"comentario": "A barba dele é rala."}
    )

    assert resposta.status_code == 201, resposta.text
    assert provedor.chamadas_de_prompt[0]["comentario_do_usuario"] == "A barba dele é rala."


def teste_leitura_profunda_em_modo_economia_roda_so_uma_vez(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """ECONOMIA (padrão): a segunda chamada reaproveita o que já foi lido."""
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_estado) == 1


def teste_leitura_profunda_em_modo_qualidade_roda_toda_vez(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """QUALIDADE: cada prompt novo relê o capítulo de origem do estado."""
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_estado) == 2


def teste_leitura_profunda_le_o_capitulo_de_origem_do_estado(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Relê o capítulo onde o estado foi registrado, não o do frame."""
    provedor = ProvedorFalso(prompt="pintura")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_estado[0]
    assert chamada["nome"] == "Ned Stark"
    assert TEXTO_LONGO in chamada["texto_capitulo"]


def teste_fase_2b_cria_historico_de_identidade_quando_ha_algo_novo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """A leitura profunda de identidade (fase 2b, item 4.4) roda junto da de
    aparência, e um incremento vira linha em HistoricoIdentidadeElemento."""
    provedor = ProvedorFalso(prompt="pintura", identidade="É filho adotivo, não de sangue.")
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    elemento_id = cliente.get(f"/frames/{frame['id']}").json()["elementos"][0]["elemento_id"]

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    elemento = cliente.get(f"/elementos/{elemento_id}").json()
    assert len(elemento["historico_identidade"]) == 1
    assert elemento["historico_identidade"][0]["descricao"] == "É filho adotivo, não de sangue."


def teste_fase_2b_nao_cria_registro_quando_nada_e_novo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O caso comum: a IA não acha nada novo, e nenhuma linha é criada."""
    provedor = ProvedorFalso(prompt="pintura")  # identidade=None por padrão
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    elemento_id = cliente.get(f"/frames/{frame['id']}").json()["elementos"][0]["elemento_id"]

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    elemento = cliente.get(f"/elementos/{elemento_id}").json()
    assert elemento["historico_identidade"] == []
    assert len(provedor.chamadas_de_identidade) == 1


def teste_fase_2b_nao_repete_a_pergunta_para_o_mesmo_par_elemento_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Mesmo em QUALIDADE (que relê o estado toda vez), a leitura profunda de
    identidade só é tentada uma vez por (elemento, capítulo) — evita
    incrementos quase idênticos repetidos a cada prompt gerado."""
    provedor = ProvedorFalso(prompt="pintura", identidade="Algo novo.")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_identidade) == 1


def teste_fase_2b_manda_a_identidade_vigente_como_contexto(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso(prompt="pintura")
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_identidade[0]
    assert chamada["nome"] == "Ned Stark"
    assert TEXTO_LONGO in chamada["texto_capitulo"]


def teste_criar_prompt_sem_modelo_de_extracao_para_leitura_profunda_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """A leitura profunda também precisa de um modelo configurado."""
    usar_provedor_falso(ProvedorFalso())
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned Stark")
    frame = _frame(cliente, capitulo["id"], [ned["estados"][0]["id"]])
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    # Só o modelo de prompt é configurado — falta o de extração/leitura profunda.
    cliente.put("/configuracao", json={"modelo_prompt": MODELO_FALSO})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 422


def teste_criar_prompt_sem_perfil_e_sem_padrao_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro(cliente)
    frame = _frame(cliente, livro["capitulos"][0]["id"])

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 422


def teste_criar_prompt_sem_modelo_responde_422(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro(cliente)
    frame = _frame(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 422


def teste_criar_prompt_com_perfil_e_modelo_explicitos_no_pedido(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(prompt="outra pintura"))
    livro = _livro(cliente)
    frame = _frame(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente, nome="Traço a nanquim")

    resposta = cliente.post(
        f"/frames/{frame['id']}/prompts",
        json={"perfil_renderizacao_id": perfil["id"], "modelo": MODELO_FALSO},
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["perfil_renderizacao_id"] == perfil["id"]


def teste_prompt_traz_a_imagem_ancora_dos_elementos_do_frame(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Consistência de personagem (item 3.1): a API avisa qual referência existe.

    O fluxo de geração é manual, então a API não anexa a imagem sozinha — só
    avisa o app de que ela existe, para o usuário anexá-la também.
    """
    provedor = ProvedorFalso(prompt="pintura")
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)

    # Gera um primeiro prompt e importa uma imagem para ele, depois marca essa
    # imagem como a âncora do estado do Ned Stark.
    primeiro = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, primeiro["id"])
    estado_id = frame["elementos"][0]["estado_id"]
    ajuste = cliente.patch(f"/estados/{estado_id}", json={"imagem_ancora_id": imagem["id"]})
    assert ajuste.status_code == 200, ajuste.text

    assert primeiro["referencias_visuais"] == []  # ainda não havia âncora nessa hora

    segundo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    assert [r["id"] for r in segundo["referencias_visuais"]] == [imagem["id"]]

    # GET /prompts/{id} também traz a referência atual, não uma foto congelada
    # de quando o prompt foi criado.
    reaberto = cliente.get(f"/prompts/{primeiro['id']}").json()
    assert [r["id"] for r in reaberto["referencias_visuais"]] == [imagem["id"]]


def teste_criar_prompt_sem_imagem_ancora_nao_traz_referencias(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    assert resposta["referencias_visuais"] == []


def teste_referencias_visuais_cai_na_ancora_padrao_do_elemento(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Item 4.5: sem âncora no Estado usado pelo frame, cai na referência
    principal do Elemento — mitiga a variação entre capítulos distantes e
    entre ferramentas de geração diferentes a cada vez."""
    provedor = ProvedorFalso(prompt="pintura")
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    elemento_id = frame["elementos"][0]["elemento_id"]

    primeiro = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, primeiro["id"])
    ajuste = cliente.patch(
        f"/elementos/{elemento_id}", json={"imagem_ancora_padrao_id": imagem["id"]}
    )
    assert ajuste.status_code == 200, ajuste.text

    segundo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    assert [r["id"] for r in segundo["referencias_visuais"]] == [imagem["id"]]


def teste_referencias_visuais_ancora_do_estado_tem_prioridade_sobre_a_padrao(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """A âncora do Estado (mais específica — "como ele está nesta cena") vence
    a padrão do Elemento ("como ele normalmente parece") quando as duas existem."""
    provedor = ProvedorFalso(prompt="pintura")
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    elemento_id = frame["elementos"][0]["elemento_id"]
    estado_id = frame["elementos"][0]["estado_id"]

    primeiro = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem_padrao = _importar_imagem(cliente, primeiro["id"], nome="padrao.png")
    cliente.patch(
        f"/elementos/{elemento_id}", json={"imagem_ancora_padrao_id": imagem_padrao["id"]}
    )
    imagem_do_estado = _importar_imagem(cliente, primeiro["id"], nome="do-estado.png")
    cliente.patch(f"/estados/{estado_id}", json={"imagem_ancora_id": imagem_do_estado["id"]})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    assert [r["id"] for r in resposta["referencias_visuais"]] == [imagem_do_estado["id"]]


def teste_criar_prompt_com_chave_ausente_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ChaveDeApiAusente("sem chave")))
    livro = _livro(cliente)
    frame = _frame(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente)

    resposta = cliente.post(
        f"/frames/{frame['id']}/prompts",
        json={"perfil_renderizacao_id": perfil["id"], "modelo": MODELO_FALSO},
    )

    assert resposta.status_code == 422


def teste_criar_prompt_com_erro_de_rede_responde_502(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("o serviço caiu")))
    livro = _livro(cliente)
    frame = _frame(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente)

    resposta = cliente.post(
        f"/frames/{frame['id']}/prompts",
        json={"perfil_renderizacao_id": perfil["id"], "modelo": MODELO_FALSO},
    )

    assert resposta.status_code == 502


def teste_criar_prompt_de_frame_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    assert cliente.post("/frames/999/prompts", json={}).status_code == 404


# --------------------------------------------------------------------------- #
# Frame do tipo PERSONAGEM: retrato solo, sem fundamentação de cena (item 4.4)
# --------------------------------------------------------------------------- #


def teste_prompt_de_personagem_nao_referencia_titulo_nem_descricao_do_frame(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Um retrato usa só a descrição do elemento — nunca o texto do frame."""
    provedor = ProvedorFalso(prompt="retrato")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="PERSONAGEM")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    chamada = provedor.chamadas_de_prompt[0]
    assert chamada["descricao_do_frame"] == ""


def teste_prompt_de_personagem_nao_fundamenta_o_frame(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Um retrato não tem "quem, onde, o quê" de cena para conferir."""
    provedor = ProvedorFalso()
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="PERSONAGEM")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert provedor.chamadas_de_fundamentacao == []


# --------------------------------------------------------------------------- #
# Frame do tipo CENA: fundamentação contra o capítulo (item 4.4)
# --------------------------------------------------------------------------- #


def teste_prompt_de_cena_fundamenta_e_manda_contexto_com_prioridade_menor(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso(contexto="o capítulo confirma que é de manhã")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    fundamentacao = provedor.chamadas_de_fundamentacao[0]
    assert fundamentacao["titulo"] == "No pátio"
    assert TEXTO_LONGO in fundamentacao["texto_capitulo"]
    assert "Ned Stark: watercolor-ready appearance description" in fundamentacao["participantes"]

    chamada_de_prompt = provedor.chamadas_de_prompt[0]
    assert chamada_de_prompt["contexto_do_livro"] == "o capítulo confirma que é de manhã"
    assert chamada_de_prompt["descricao_do_frame"] == "No pátio"


def teste_fundamentacao_em_modo_economia_roda_so_uma_vez(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso()
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 1


def teste_fundamentacao_em_modo_qualidade_roda_toda_vez(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso()
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor, tipo="CENA")
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert len(provedor.chamadas_de_fundamentacao) == 2


def teste_frame_de_cena_sem_participantes_nao_fundamenta(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Nada para confirmar "quem, onde, o quê" quando ninguém está ligado ainda."""
    provedor = ProvedorFalso()
    usar_provedor_falso(provedor)
    livro = _livro(cliente)
    frame = _frame(cliente, livro["capitulos"][0]["id"], tipo="CENA")
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_prompt": MODELO_FALSO})

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    assert provedor.chamadas_de_fundamentacao == []


# --------------------------------------------------------------------------- #
# Histórico, ajuste e remoção de prompts
# --------------------------------------------------------------------------- #


def teste_listar_prompts_do_frame(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    resposta = cliente.get(f"/frames/{frame['id']}/prompts")

    assert resposta.status_code == 200
    assert len(resposta.json()) == 2


def teste_ajustar_prompt_anota_avaliacao(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    resposta = cliente.patch(f"/prompts/{prompt['id']}", json={"avaliacao": "Ficou ótima."})

    assert resposta.status_code == 200
    assert resposta.json()["avaliacao"] == "Ficou ótima."


def teste_remover_prompt_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.delete("/prompts/999").status_code == 404


# --------------------------------------------------------------------------- #
# Catálogo de imagens
# --------------------------------------------------------------------------- #


def _importar_imagem(cliente: TestClient, prompt_id: int, nome: str = "resultado.png") -> dict:
    resposta = cliente.post(
        f"/prompts/{prompt_id}/imagens",
        files={"arquivo": (nome, b"conteudo-fake-da-imagem", "image/png")},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def teste_importar_imagem_e_baixar_o_arquivo(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    imagem = _importar_imagem(cliente, prompt["id"])
    assert imagem["prompt_id"] == prompt["id"]

    baixado = cliente.get(f"/imagens/{imagem['id']}/arquivo")
    assert baixado.status_code == 200
    assert baixado.content == b"conteudo-fake-da-imagem"

    detalhe = cliente.get(f"/prompts/{prompt['id']}").json()
    assert len(detalhe["imagens"]) == 1


def teste_importar_imagem_com_extensao_invalida_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/imagens",
        files={"arquivo": ("resultado.txt", b"nao e imagem", "text/plain")},
    )

    assert resposta.status_code == 422


def teste_importar_imagem_de_prompt_inexistente_responde_404(cliente: TestClient) -> None:
    resposta = cliente.post(
        "/prompts/999/imagens",
        files={"arquivo": ("resultado.png", b"x", "image/png")},
    )
    assert resposta.status_code == 404


def teste_remover_imagem_apaga_o_arquivo_do_disco(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])

    arquivos_antes = list(_diretorio_de_imagens.rglob("*.png"))
    assert len(arquivos_antes) == 1

    resposta = cliente.delete(f"/imagens/{imagem['id']}")

    assert resposta.status_code == 204
    assert list(_diretorio_de_imagens.rglob("*.png")) == []
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 404


def teste_remover_prompt_apaga_as_imagens_e_os_arquivos(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    _importar_imagem(cliente, prompt["id"])
    _importar_imagem(cliente, prompt["id"], nome="outra.png")

    resposta = cliente.delete(f"/prompts/{prompt['id']}")

    assert resposta.status_code == 204
    assert list(_diretorio_de_imagens.rglob("*.png")) == []
    assert cliente.get(f"/prompts/{prompt['id']}").status_code == 404


def teste_remover_imagem_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.delete("/imagens/999").status_code == 404


# --------------------------------------------------------------------------- #
# Situação da geração e suavização (item 3.4c, S5)
# --------------------------------------------------------------------------- #


def teste_prompt_novo_nasce_nao_tentado_e_sem_original(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)

    criado = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    assert criado["situacao_da_geracao"] == "NAO_TENTADO"
    assert criado["motivo_da_recusa"] is None
    assert criado["prompt_original_id"] is None


def teste_listagem_e_detalhe_trazem_situacao_motivo_e_original(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    """O suavizado é um prompt novo, ligado ao original; os dois aparecem na lista."""
    from imagineer.modelos.prompt import SituacaoDaGeracao

    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    original = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    registro = sessao_com_tabelas.get(Prompt, original["id"])
    registro.situacao_da_geracao = SituacaoDaGeracao.RECUSADO
    registro.motivo_da_recusa = "The response was filtered due to the prompt triggering our content management policy."
    suavizado = Prompt(
        frame_id=frame["id"],
        texto="versão mais suave",
        situacao_da_geracao=SituacaoDaGeracao.COM_SUCESSO,
        prompt_original_id=original["id"],
    )
    sessao_com_tabelas.add(suavizado)
    sessao_com_tabelas.commit()

    lista = cliente.get(f"/frames/{frame['id']}/prompts").json()
    por_id = {prompt["id"]: prompt for prompt in lista}

    assert por_id[original["id"]]["situacao_da_geracao"] == "RECUSADO"
    assert "content management policy" in por_id[original["id"]]["motivo_da_recusa"]
    assert por_id[suavizado.id]["situacao_da_geracao"] == "COM_SUCESSO"
    assert por_id[suavizado.id]["prompt_original_id"] == original["id"]
    detalhe = cliente.get(f"/prompts/{suavizado.id}").json()
    assert detalhe["prompt_original_id"] == original["id"]
    assert detalhe["situacao_da_geracao"] == "COM_SUCESSO"


def teste_apagar_o_original_nao_apaga_o_suavizado(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    """`ON DELETE SET NULL`: o suavizado é um prompt por si só; só perde o vínculo."""
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    original = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    suavizado = Prompt(frame_id=frame["id"], texto="mais suave", prompt_original_id=original["id"])
    sessao_com_tabelas.add(suavizado)
    sessao_com_tabelas.commit()

    assert cliente.delete(f"/prompts/{original['id']}").status_code == 204

    restante = cliente.get(f"/prompts/{suavizado.id}")
    assert restante.status_code == 200
    assert restante.json()["prompt_original_id"] is None


# --------------------------------------------------------------------------- #
# Gerar a imagem pelo servidor (item 6.6, S1 a S12)
# --------------------------------------------------------------------------- #


def _prompt_pronto(cliente: TestClient, usar_provedor_falso, **opcoes) -> tuple[ProvedorFalso, dict]:
    """Um frame com um prompt já montado, e o provedor falso que vai gerar (e talvez recusar) a imagem."""
    provedor = ProvedorFalso(prompt="close-up, Auri, nude, 2:3", **opcoes)
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    return provedor, prompt


def _por_id(cliente: TestClient, frame_id: int) -> dict[int, dict]:
    return {p["id"]: p for p in cliente.get(f"/frames/{frame_id}/prompts").json()}


def teste_s1_gera_a_imagem_do_prompt_original(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["resultado"] == "GERADA"
    assert corpo["suavizado"] is False
    assert corpo["prompt"]["id"] == prompt["id"]
    assert corpo["prompt"]["situacao_da_geracao"] == "COM_SUCESSO"
    assert corpo["imagem"]["largura"] == 20 and corpo["imagem"]["altura"] == 30
    assert corpo["imagem"]["orientacao"] == "RETRATO"
    # Foi o prompt original, com o modelo de imagem padrão, e sem suavizar.
    assert provedor.chamadas_de_imagem == [{"prompt": "close-up, Auri, nude, 2:3", "modelo": "meta/muse-image"}]
    assert provedor.chamadas_de_suavizacao == []


def teste_a_imagem_gerada_entra_no_catalogo_como_a_importada(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").json()

    detalhe = cliente.get(f"/prompts/{prompt['id']}").json()
    assert [imagem["id"] for imagem in detalhe["imagens"]] == [corpo["imagem"]["id"]]
    baixada = cliente.get(f"/imagens/{corpo['imagem']['id']}/arquivo")
    assert baixada.status_code == 200
    assert baixada.content.startswith(b"\x89PNG")
    assert list(_diretorio_de_imagens.rglob("*.png"))  # o arquivo está em disco


def teste_o_modelo_de_imagem_da_configuracao_e_o_que_vale(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_imagem": "black-forest-labs/flux.2-klein-4b"})

    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert provedor.chamadas_de_imagem[0]["modelo"] == "black-forest-labs/flux.2-klein-4b"


def teste_s2_recusa_suaviza_e_a_segunda_tentativa_gera(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(
        cliente, usar_provedor_falso, recusas_de_imagem=1, prompt_suavizado="close-up, Auri, covered by her hair, 2:3"
    )
    cliente.put("/configuracao", json={"modelo_suavizacao": "barato/modelo"})

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").json()

    assert corpo["resultado"] == "GERADA"
    assert corpo["suavizado"] is True
    suavizado = corpo["prompt"]
    assert suavizado["id"] != prompt["id"]
    assert suavizado["texto"] == "close-up, Auri, covered by her hair, 2:3"
    assert suavizado["prompt_original_id"] == prompt["id"]
    assert suavizado["situacao_da_geracao"] == "COM_SUCESSO"
    assert suavizado["modelo_ia"] == "barato/modelo"
    assert corpo["imagem"] is not None
    # O original nunca é sobrescrito: continua com o texto e a recusa registrada (S5).
    original = _por_id(cliente, prompt["frame_id"])[prompt["id"]]
    assert original["texto"] == "close-up, Auri, nude, 2:3"
    assert original["situacao_da_geracao"] == "RECUSADO"
    assert "content management policy" in original["motivo_da_recusa"]
    assert original["total_de_imagens"] == 0
    # A suavização usou o modelo próprio e o texto recusado; a 2ª tentativa foi com o texto suave.
    assert provedor.chamadas_de_suavizacao == [{"texto": "close-up, Auri, nude, 2:3", "modelo": "barato/modelo"}]
    assert [c["prompt"] for c in provedor.chamadas_de_imagem] == [
        "close-up, Auri, nude, 2:3",
        "close-up, Auri, covered by her hair, 2:3",
    ]


def teste_sem_modelo_de_suavizacao_usa_o_modelo_de_prompt(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=1)

    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert provedor.chamadas_de_suavizacao[0]["modelo"] == MODELO_FALSO  # o modelo_prompt


def teste_s3_recusa_de_novo_devolve_ao_usuario_com_o_prompt_para_editar(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=2)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert resposta.status_code == 200  # recusa não é erro de servidor
    corpo = resposta.json()
    assert corpo["resultado"] == "RECUSADA"
    assert corpo["imagem"] is None
    assert corpo["suavizado"] is True
    assert corpo["prompt"]["situacao_da_geracao"] == "RECUSADO"
    assert corpo["prompt"]["motivo_da_recusa"]
    assert corpo["prompt"]["prompt_original_id"] == prompt["id"]
    # S12: uma suavização por pedido, sem laço (2 envios, 1 suavização).
    assert len(provedor.chamadas_de_imagem) == 2
    assert len(provedor.chamadas_de_suavizacao) == 1
    prompts = _por_id(cliente, prompt["frame_id"])
    assert {p["situacao_da_geracao"] for p in prompts.values()} == {"RECUSADO"}


def teste_s3_texto_editado_vira_prompt_novo_e_vai_direto_sem_suavizar(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"texto": "close-up, Auri, wrapped in linen, 2:3"}
    ).json()

    assert corpo["resultado"] == "GERADA"
    assert corpo["suavizado"] is False  # a edição é do usuário, não do sistema
    editado = corpo["prompt"]
    assert editado["id"] != prompt["id"]
    assert editado["texto"] == "close-up, Auri, wrapped in linen, 2:3"
    assert editado["prompt_original_id"] == prompt["id"]
    assert editado["modelo_ia"] is None
    assert provedor.chamadas_de_imagem == [{"prompt": "close-up, Auri, wrapped in linen, 2:3", "modelo": "meta/muse-image"}]
    assert cliente.get(f"/prompts/{prompt['id']}").json()["texto"] == "close-up, Auri, nude, 2:3"


def teste_s3_texto_editado_que_o_provedor_recusa_nao_dispara_suavizacao(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=1)

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"texto": "versão editada"}).json()

    assert corpo["resultado"] == "RECUSADA"
    assert corpo["suavizado"] is False
    assert corpo["prompt"]["texto"] == "versão editada"
    assert corpo["prompt"]["situacao_da_geracao"] == "RECUSADO"
    assert provedor.chamadas_de_suavizacao == []  # chamada direta (S3)


def teste_texto_igual_ao_do_prompt_segue_o_fluxo_normal(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"texto": "  close-up, Auri, nude, 2:3 "}).json()

    assert corpo["prompt"]["id"] == prompt["id"]  # não criou prompt novo
    assert corpo["resultado"] == "GERADA"


def teste_s4_erro_que_nao_e_recusa_da_502_sem_suavizar_e_sem_mudar_o_prompt(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)
    provedor._erro = ErroDoProvedorIA("O OpenRouter respondeu 503: temporariamente indisponível")

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert resposta.status_code == 502
    assert provedor.chamadas_de_suavizacao == []
    assert cliente.get(f"/prompts/{prompt['id']}").json()["situacao_da_geracao"] == "NAO_TENTADO"


def teste_recusa_sem_nenhum_modelo_de_texto_da_422_mas_nao_perde_a_recusa(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=1)
    cliente.put("/configuracao", json={"modelo_prompt": ""})  # sem modelo_suavizacao nem modelo_prompt

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert resposta.status_code == 422
    assert "suavizá-lo" in resposta.json()["detail"]
    assert provedor.chamadas_de_suavizacao == []
    detalhe = cliente.get(f"/prompts/{prompt['id']}").json()
    assert detalhe["situacao_da_geracao"] == "RECUSADO"  # a recusa foi gravada antes do erro


def teste_gerar_de_novo_um_prompt_ja_recusado_que_agora_passa_limpa_o_motivo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=2)
    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")  # recusa duas vezes

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").json()  # o provedor agora aceita

    assert corpo["resultado"] == "GERADA"
    assert corpo["prompt"]["id"] == prompt["id"]
    assert corpo["prompt"]["situacao_da_geracao"] == "COM_SUCESSO"
    assert corpo["prompt"]["motivo_da_recusa"] is None


def teste_gerar_imagem_de_prompt_inexistente_da_404(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())

    assert cliente.post("/prompts/9999/gerar-imagem").status_code == 404


def teste_gerar_imagem_sem_chave_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)
    provedor._erro = ChaveDeApiAusente("Não há chave de API do OpenRouter configurada.")

    assert cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").status_code == 422


# --------------------------------------------------------------------------- #
# Origem da imagem (item 7.5b, T3)
# --------------------------------------------------------------------------- #


def teste_imagem_importada_tem_origem_importada(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    importada = cliente.post(
        f"/prompts/{prompt['id']}/imagens", files={"arquivo": ("a.png", b"\x89PNG\r\n\x1a\nxx", "image/png")}
    ).json()

    assert importada["origem"] == "IMPORTADA"


def teste_imagem_gerada_tem_origem_gerada_e_a_importada_no_mesmo_prompt_continua_importada(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)
    gerada = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").json()["imagem"]
    cliente.post(f"/prompts/{prompt['id']}/imagens", files={"arquivo": ("a.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})

    imagens = cliente.get(f"/prompts/{prompt['id']}").json()["imagens"]

    assert gerada["origem"] == "GERADA"
    assert sorted(imagem["origem"] for imagem in imagens) == ["GERADA", "IMPORTADA"]


# --------------------------------------------------------------------------- #
# Qual modelo de imagem foi usado, e tentar com outro (item 7.5b, Z1 a Z11)
# --------------------------------------------------------------------------- #


def teste_z1_prompt_nunca_tentado_nao_tem_modelo_de_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    assert prompt["modelo_imagem"] is None


def teste_z1_o_modelo_padrao_fica_no_prompt_e_na_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").json()

    assert corpo["prompt"]["modelo_imagem"] == "meta/muse-image"
    assert corpo["imagem"]["modelo"] == "meta/muse-image"
    # E fica no banco: a listagem e o detalhe devolvem o mesmo.
    assert cliente.get(f"/prompts/{prompt['id']}").json()["modelo_imagem"] == "meta/muse-image"
    assert cliente.get(f"/prompts/{prompt['id']}").json()["imagens"][0]["modelo"] == "meta/muse-image"


def teste_z3_o_modelo_do_pedido_vale_so_para_aquele_pedido(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "bytedance-seed/seedream-5-0-flash"}
    ).json()

    assert provedor.chamadas_de_imagem == [{"prompt": "close-up, Auri, nude, 2:3", "modelo": "bytedance-seed/seedream-5-0-flash"}]
    assert corpo["prompt"]["modelo_imagem"] == "bytedance-seed/seedream-5-0-flash"
    assert corpo["imagem"]["modelo"] == "bytedance-seed/seedream-5-0-flash"
    # Não mudou o padrão do servidor.
    assert cliente.get("/configuracao").json()["modelo_imagem"] == "meta/muse-image"
    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")
    assert provedor.chamadas_de_imagem[-1]["modelo"] == "meta/muse-image"


def teste_z3_modelo_em_branco_vale_o_padrao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "   "})

    assert provedor.chamadas_de_imagem[0]["modelo"] == "meta/muse-image"


def teste_z1_a_tentativa_recusada_tambem_guarda_o_modelo(cliente: TestClient, usar_provedor_falso) -> None:
    """É o que permite dizer "Recusado por X" (Z7)."""
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=2)

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "outro/modelo"}).json()

    assert corpo["resultado"] == "RECUSADA"
    original = _por_id(cliente, prompt["frame_id"])[prompt["id"]]
    assert original["situacao_da_geracao"] == "RECUSADO"
    assert original["modelo_imagem"] == "outro/modelo"
    assert corpo["prompt"]["modelo_imagem"] == "outro/modelo"  # o suavizado foi enviado ao mesmo modelo


def teste_z3_original_suavizado_e_segunda_tentativa_usam_o_mesmo_modelo(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=1)

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "google/gemini-2.5-flash-image"}
    ).json()

    assert corpo["resultado"] == "GERADA" and corpo["suavizado"] is True
    assert [c["modelo"] for c in provedor.chamadas_de_imagem] == ["google/gemini-2.5-flash-image"] * 2
    assert corpo["imagem"]["modelo"] == "google/gemini-2.5-flash-image"


def teste_z10_o_original_recusado_pode_ser_reenviado_a_outro_modelo(cliente: TestClient, usar_provedor_falso) -> None:
    """O Gerar imagem do cartão do original, com outro modelo: o original vai direto ao novo modelo, sem suavizar."""
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=2)
    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")  # o modelo padrão recusa o original e o suavizado

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "bytedance-seed/seedream-5-0-flash"}).json()

    assert corpo["resultado"] == "GERADA"
    assert corpo["suavizado"] is False  # o novo modelo aceitou o ORIGINAL: nada foi suavizado
    assert corpo["prompt"]["id"] == prompt["id"]
    assert provedor.chamadas_de_imagem[-1] == {"prompt": "close-up, Auri, nude, 2:3", "modelo": "bytedance-seed/seedream-5-0-flash"}
    assert corpo["prompt"]["situacao_da_geracao"] == "COM_SUCESSO"
    assert corpo["prompt"]["modelo_imagem"] == "bytedance-seed/seedream-5-0-flash"


def teste_z3_texto_editado_com_modelo_novo_vai_direto_a_esse_modelo(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"texto": "versão editada", "modelo": "recraft/recraft-v4.1"}
    ).json()

    assert provedor.chamadas_de_imagem == [{"prompt": "versão editada", "modelo": "recraft/recraft-v4.1"}]
    assert corpo["prompt"]["modelo_imagem"] == "recraft/recraft-v4.1"
    assert corpo["prompt"]["prompt_original_id"] == prompt["id"]


def teste_z4_modelo_com_mais_de_200_caracteres_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "x" * 201})

    assert resposta.status_code == 422


# --------------------------------------------------------------------------- #
# Gerar sem o filtro de segurança (item 7.5b, F12 a F18)
# --------------------------------------------------------------------------- #

MODELO_SEM_FILTRO = "replicate:black-forest-labs/flux-schnell"


def _recusado_com_modelo_sem_filtro(cliente: TestClient, usar_provedor_falso, texto: str = "close-up, Auri, nude", **opcoes):
    """Um prompt que o provedor recusou (as duas tentativas), com um modelo na lista de modelos sem filtro."""
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso, recusas_de_imagem=2, **opcoes)
    cliente.put("/configuracao", json={"modelos_sem_filtro": [MODELO_SEM_FILTRO]})
    cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")  # S1 e S2: recusa duas vezes
    return provedor, prompt


def teste_f12_gera_sem_o_filtro_um_prompt_recusado_e_registra_isso(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["resultado"] == "GERADA"
    assert corpo["suavizado"] is False  # chamada direta (F12, F18)
    assert corpo["prompt"]["sem_filtro_de_seguranca"] is True  # F16
    assert corpo["imagem"]["sem_filtro_de_seguranca"] is True
    assert corpo["prompt"]["modelo_imagem"] == MODELO_SEM_FILTRO
    assert provedor.chamadas_de_imagem[-1] == {
        "prompt": provedor.chamadas_de_imagem[0]["prompt"],
        "modelo": MODELO_SEM_FILTRO,
        "sem_filtro_de_seguranca": True,
    }
    assert len(provedor.chamadas_de_suavizacao) == 1  # só a da primeira geração; esta não suavizou de novo


def teste_f16_geracao_normal_nao_marca_sem_filtro(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem").json()

    assert corpo["prompt"]["sem_filtro_de_seguranca"] is False
    assert corpo["imagem"]["sem_filtro_de_seguranca"] is False


def teste_f12_prompt_que_nunca_foi_recusado_nao_pode_ser_gerado_sem_filtro(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_pronto(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelos_sem_filtro": [MODELO_SEM_FILTRO]})

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True}
    )

    assert resposta.status_code == 422
    assert "recusou" in resposta.json()["detail"]


def teste_f12_sem_modelo_no_pedido_nunca_usa_o_padrao(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"sem_filtro_de_seguranca": True})

    assert resposta.status_code == 422
    assert "Escolha o modelo" in resposta.json()["detail"]


def teste_f13_modelo_fora_da_lista_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem",
        json={"modelo": "replicate:outro/modelo", "sem_filtro_de_seguranca": True},
    )

    assert resposta.status_code == 422
    assert "modelos_sem_filtro" in resposta.json()["detail"]


def teste_f14_so_o_replicate_pode_ficar_sem_filtro(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)
    # Mesmo na lista, um modelo de outro fornecedor é recusado.
    cliente.put("/configuracao", json={"modelos_sem_filtro": ["fal:fal-ai/flux/dev", "meta/muse-image"]})

    for modelo in ("fal:fal-ai/flux/dev", "meta/muse-image"):
        resposta = cliente.post(
            f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": modelo, "sem_filtro_de_seguranca": True}
        )
        assert resposta.status_code == 422
        assert "Replicate" in resposta.json()["detail"]


def teste_f15_prompt_com_sinal_de_menor_nunca_gera_sem_filtro(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    provedor, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)
    sessao_com_tabelas.get(Prompt, prompt["id"]).texto = "a young girl in a field, nude"
    sessao_com_tabelas.commit()

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True}
    )

    assert resposta.status_code == 422
    assert "menor de idade" in resposta.json()["detail"]
    assert all("sem_filtro_de_seguranca" not in chamada for chamada in provedor.chamadas_de_imagem)


def teste_f15_o_texto_editado_tambem_passa_pela_trava(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem",
        json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True, "texto": "a 12-year-old child"},
    )

    assert resposta.status_code == 422


def teste_f12_texto_editado_sem_filtro_vira_prompt_novo_e_vai_direto(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem",
        json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True, "texto": "close-up, Auri, adult woman"},
    ).json()

    assert corpo["prompt"]["id"] != prompt["id"]
    assert corpo["prompt"]["prompt_original_id"] == prompt["id"]
    assert corpo["prompt"]["sem_filtro_de_seguranca"] is True
    assert provedor.chamadas_de_imagem[-1]["prompt"] == "close-up, Auri, adult woman"


def teste_f17_se_recusar_mesmo_sem_filtro_volta_recusada_sem_subir_de_nivel(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)
    provedor._recusas_de_imagem = 99  # recusa tudo

    corpo = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True}
    ).json()

    assert corpo["resultado"] == "RECUSADA"
    assert corpo["prompt"]["sem_filtro_de_seguranca"] is True
    assert provedor.chamadas_de_imagem[-1]["sem_filtro_de_seguranca"] is True
    assert len(provedor.chamadas_de_suavizacao) == 1  # nada de suavizar de novo


def teste_f16_uma_geracao_normal_depois_limpa_a_marca_do_prompt(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt = _recusado_com_modelo_sem_filtro(cliente, usar_provedor_falso)
    cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": MODELO_SEM_FILTRO, "sem_filtro_de_seguranca": True}
    )

    corpo = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "outro/modelo"}).json()

    assert corpo["prompt"]["sem_filtro_de_seguranca"] is False


def teste_z1_erro_do_provedor_nao_grava_o_modelo_no_prompt(cliente: TestClient, usar_provedor_falso) -> None:
    """Um 502 não foi uma tentativa concluída: o prompt continua como estava."""
    provedor, prompt = _prompt_pronto(cliente, usar_provedor_falso)
    provedor._erro = ErroDoProvedorIA("O OpenRouter respondeu 503: temporariamente indisponível")

    assert cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "outro/modelo"}).status_code == 502

    assert cliente.get(f"/prompts/{prompt['id']}").json()["modelo_imagem"] is None
