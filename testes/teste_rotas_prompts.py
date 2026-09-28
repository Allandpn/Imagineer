"""Testes das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

import io

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient

from imagineer import configuracao as modulo_de_configuracao
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, PromptMontado

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
