"""Testes da `revisao` do livro e do `ETag` (itens 6.9 e 7.0a).

A `revisao` sobe sozinha a cada mudança no que o leitor mostra — e **não** sobe numa leitura. O
valor deste arquivo está na tabela de ações: **uma linha para cada caminho que altera dado**, para
que uma rota nova sem cobertura salte aos olhos, e para provar que o ouvinte do banco pega todas.
"""

import pytest
from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ElementoSugerido
from imagineer.modelos import TipoElemento

# A fixture autouse de pasta temporária de imagens e os auxiliares moram nos testes de prompts.
from testes.teste_rotas_prompts import (  # noqa: F401
    _diretorio_de_imagens,
    _frame,
    _importar_imagem,
    _montar_frame_completo,
)


def _revisao(cliente: TestClient, livro_id: int) -> int:
    resposta = cliente.get(f"/livros/{livro_id}")
    assert resposta.status_code == 200
    return resposta.json()["revisao"]


@pytest.fixture
def cenario(cliente: TestClient, usar_provedor_falso) -> dict:
    """Um livro completo: elemento, frame, prompt, imagem, sugestões já geradas e perfil padrão."""
    provedor = ProvedorFalso(
        prompt="uma pintura de teste",
        elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
    )
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    capitulo_id = livro["capitulos"][0]["id"]
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])
    sugestoes = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()
    elemento = cliente.get(f"/livros/{livro['id']}/elementos").json()[0]
    perfil_id = cliente.get(f"/livros/{livro['id']}").json()["perfil_renderizacao_padrao_id"]
    return {
        "livro_id": livro["id"],
        "capitulo_id": capitulo_id,
        "frame_id": frame["id"],
        "prompt_id": prompt["id"],
        "imagem_id": imagem["id"],
        "elemento_id": elemento["id"],
        "sugestao_id": sugestoes["elementos"][0]["id"],
        "perfil_id": perfil_id,
    }


# --------------------------------------------------------------------------- #
# A tabela: cada caminho que altera dado tem de subir a revisão
# --------------------------------------------------------------------------- #

ACOES_QUE_ALTERAM_DADO = {
    "ajustar o livro": lambda c, x: c.patch(f"/livros/{x['livro_id']}", json={"titulo": "Outro título"}),
    "tirar o perfil padrão do livro": lambda c, x: c.patch(
        f"/livros/{x['livro_id']}", json={"perfil_renderizacao_padrao_id": None}
    ),
    "arquivar um capítulo": lambda c, x: c.patch(f"/capitulos/{x['capitulo_id']}", json={"ignorado": True}),
    "criar um elemento": lambda c, x: c.post(
        f"/livros/{x['livro_id']}/elementos", json={"tipo": "AMBIENTE", "nome": "Winterfell"}
    ),
    "ajustar um elemento": lambda c, x: c.patch(f"/elementos/{x['elemento_id']}", json={"descricao": "novo"}),
    "registrar um estado": lambda c, x: c.post(
        f"/elementos/{x['elemento_id']}/estados",
        json={"capitulo_id": x["capitulo_id"], "descricao": "Outro estado."},
    ),
    "apagar um elemento": lambda c, x: c.delete(f"/elementos/{x['elemento_id']}"),
    "criar um frame": lambda c, x: c.post(
        f"/capitulos/{x['capitulo_id']}/frames", json={"tipo": "CENA", "titulo": "Outro", "estados_ids": []}
    ),
    "ajustar um frame": lambda c, x: c.patch(f"/frames/{x['frame_id']}", json={"titulo": "Novo título"}),
    "apagar um frame": lambda c, x: c.delete(f"/frames/{x['frame_id']}"),
    "criar um prompt": lambda c, x: c.post(f"/frames/{x['frame_id']}/prompts", json={}),
    "anotar a avaliação de um prompt": lambda c, x: c.patch(
        f"/prompts/{x['prompt_id']}", json={"avaliacao": "ficou ótimo"}
    ),
    "apagar um prompt": lambda c, x: c.delete(f"/prompts/{x['prompt_id']}"),
    "importar uma imagem": lambda c, x: c.post(
        f"/prompts/{x['prompt_id']}/imagens", files={"arquivo": ("g.png", b"png-falso", "image/png")}
    ),
    "apagar uma imagem": lambda c, x: c.delete(f"/imagens/{x['imagem_id']}"),
    "analisar de novo o capítulo": lambda c, x: c.post(f"/capitulos/{x['capitulo_id']}/sugestoes?forcar=true"),
    "vincular uma sugestão a um elemento": lambda c, x: c.patch(
        f"/sugestoes-elemento/{x['sugestao_id']}", json={"elemento_id": x["elemento_id"]}
    ),
}


@pytest.mark.parametrize("nome_da_acao", list(ACOES_QUE_ALTERAM_DADO))
def teste_toda_acao_que_altera_dado_sobe_a_revisao(
    cliente: TestClient, cenario: dict, nome_da_acao: str
) -> None:
    antes = _revisao(cliente, cenario["livro_id"])

    resposta = ACOES_QUE_ALTERAM_DADO[nome_da_acao](cliente, cenario)

    assert resposta.status_code < 300, f"{nome_da_acao}: {resposta.status_code} {resposta.text}"
    # Um livro apagado por outro caminho nem chegaria aqui; nenhuma destas apaga o livro.
    assert _revisao(cliente, cenario["livro_id"]) > antes, f"a revisão não subiu ao {nome_da_acao}"


def teste_gravar_o_mesmo_valor_nao_sobe_a_revisao(cliente: TestClient, cenario: dict) -> None:
    """Sem mudança real no banco, não há o que revisar: o app não relê à toa."""
    titulo = cliente.get(f"/livros/{cenario['livro_id']}").json()["titulo"]
    antes = _revisao(cliente, cenario["livro_id"])

    cliente.patch(f"/livros/{cenario['livro_id']}", json={"titulo": titulo})

    assert _revisao(cliente, cenario["livro_id"]) == antes


def teste_apagar_o_perfil_sobe_a_revisao_do_livro_que_o_usava(
    cliente: TestClient, cenario: dict
) -> None:
    """O ponto cego do ORM: o *banco* zera o perfil padrão (`ON DELETE SET NULL`), sem nenhum
    evento — e o livro mostra o perfil padrão."""
    antes = _revisao(cliente, cenario["livro_id"])

    resposta = cliente.delete(f"/perfis-renderizacao/{cenario['perfil_id']}")

    assert resposta.status_code == 204
    assert _revisao(cliente, cenario["livro_id"]) > antes
    assert cliente.get(f"/livros/{cenario['livro_id']}").json()["perfil_renderizacao_padrao_id"] is None


def teste_apagar_um_perfil_que_nenhum_livro_usa_nao_sobe_a_revisao_de_ninguem(
    cliente: TestClient, cenario: dict
) -> None:
    solto = cliente.post("/perfis-renderizacao", json={"nome": "Sem uso"}).json()
    antes = _revisao(cliente, cenario["livro_id"])

    cliente.delete(f"/perfis-renderizacao/{solto['id']}")

    assert _revisao(cliente, cenario["livro_id"]) == antes


# --------------------------------------------------------------------------- #
# Ler não sobe a revisão
# --------------------------------------------------------------------------- #


def teste_leituras_nao_sobem_a_revisao(cliente: TestClient, cenario: dict) -> None:
    livro_id, capitulo_id = cenario["livro_id"], cenario["capitulo_id"]
    antes = _revisao(cliente, livro_id)

    cliente.get("/livros")
    cliente.get(f"/livros/{livro_id}")
    cliente.get(f"/livros/{livro_id}/textos")
    cliente.get(f"/capitulos/{capitulo_id}")
    cliente.get(f"/capitulos/{capitulo_id}/sugestoes")
    cliente.get(f"/livros/{livro_id}/elementos")
    cliente.get(f"/imagens/{cenario['imagem_id']}/arquivo")

    assert _revisao(cliente, livro_id) == antes


def teste_o_manifesto_de_midias_nao_sobe_a_revisao_ao_gravar_o_tamanho(
    cliente: TestClient, cenario: dict, sessao_com_tabelas
) -> None:
    """O manifesto grava `tamanho_em_bytes` nas imagens antigas — mas isso não muda o que o
    leitor mostra, e uma leitura que sobe a revisão faria o app reler sem motivo, sempre."""
    from sqlalchemy import update

    from imagineer.modelos import Imagem

    sessao_com_tabelas.execute(update(Imagem).values(tamanho_em_bytes=None))
    sessao_com_tabelas.commit()
    antes = _revisao(cliente, cenario["livro_id"])

    cliente.get(f"/livros/{cenario['livro_id']}/midias")  # grava o tamanho que faltava

    assert _revisao(cliente, cenario["livro_id"]) == antes


def teste_mudar_so_o_que_o_leitor_nao_ve_nao_sobe_a_revisao_de_outro_livro(
    cliente: TestClient, cenario: dict, usar_provedor_falso
) -> None:
    """A revisão é **por livro**: mexer num livro não mexe no de outro."""
    outro = cliente.post(
        "/livros",
        files={"arquivo": ("o.epub", _epub_simples(), "application/epub+zip")},
    ).json()["livro"]
    antes_do_outro = _revisao(cliente, outro["id"])

    cliente.patch(f"/livros/{cenario['livro_id']}", json={"titulo": "Só deste"})

    assert _revisao(cliente, outro["id"]) == antes_do_outro


def _epub_simples() -> bytes:
    from testes.teste_rotas_sugestoes import _epub

    return _epub(titulo="Outro livro", identificador="urn:isbn:2")


# --------------------------------------------------------------------------- #
# A revisão aparece, e o ETag é ela
# --------------------------------------------------------------------------- #


def teste_a_revisao_aparece_na_lista_e_no_detalhe(cliente: TestClient, cenario: dict) -> None:
    detalhe = cliente.get(f"/livros/{cenario['livro_id']}").json()
    na_lista = next(l for l in cliente.get("/livros").json() if l["id"] == cenario["livro_id"])

    assert isinstance(detalhe["revisao"], int)
    assert na_lista["revisao"] == detalhe["revisao"]


def teste_o_etag_do_detalhe_e_a_revisao(cliente: TestClient, cenario: dict) -> None:
    resposta = cliente.get(f"/livros/{cenario['livro_id']}")

    assert resposta.headers["etag"] == f'"{resposta.json()["revisao"]}"'


def teste_if_none_match_com_a_revisao_atual_responde_304_sem_corpo(
    cliente: TestClient, cenario: dict
) -> None:
    etag = cliente.get(f"/livros/{cenario['livro_id']}").headers["etag"]

    repetida = cliente.get(f"/livros/{cenario['livro_id']}", headers={"If-None-Match": etag})

    assert repetida.status_code == 304
    assert repetida.content == b""
    assert repetida.headers["etag"] == etag  # o cliente confirma de que revisão está falando


def teste_if_none_match_de_uma_revisao_velha_devolve_o_livro_inteiro(
    cliente: TestClient, cenario: dict
) -> None:
    velho = cliente.get(f"/livros/{cenario['livro_id']}").headers["etag"]
    cliente.patch(f"/capitulos/{cenario['capitulo_id']}", json={"ignorado": True})

    resposta = cliente.get(f"/livros/{cenario['livro_id']}", headers={"If-None-Match": velho})

    assert resposta.status_code == 200
    assert resposta.headers["etag"] != velho
    assert resposta.json()["capitulos"][0]["ignorado"] is True  # a mudança que motivou a revisão


def teste_if_none_match_aceita_varias_revisoes_e_o_prefixo_fraco(
    cliente: TestClient, cenario: dict
) -> None:
    etag = cliente.get(f"/livros/{cenario['livro_id']}").headers["etag"]

    com_varias = cliente.get(
        f"/livros/{cenario['livro_id']}", headers={"If-None-Match": f'"999", W/{etag}, "1000"'}
    )

    assert com_varias.status_code == 304


def teste_a_leitura_continua_comprimida_com_o_etag(cliente: TestClient, cenario: dict) -> None:
    """O ETag convive com o gzip: a revisão vale para o conteúdo, comprimido ou não."""
    resposta = cliente.get(f"/livros/{cenario['livro_id']}", headers={"Accept-Encoding": "gzip"})

    assert resposta.status_code == 200
    assert resposta.headers.get("etag")
