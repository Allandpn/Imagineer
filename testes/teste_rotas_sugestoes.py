"""Testes de `POST /capitulos/{id}/sugestoes` (Etapas 6.7 e 3.4e).

A rota não grava Elemento nem Frame — a IA sugere, o usuário confirma depois
pelas rotas de cadastro (Etapa 6.3/6.4). A sugestão em si, porém, é
persistida como linhas (`SugestaoDeElemento`/`SugestaoDeCena`), não mais
como um blob por capítulo.
"""

import io

from ebooklib import epub
from fastapi.testclient import TestClient

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ElementoSugerido,
    ErroDoProvedorIA,
    CenaSugerida,
    ParticipanteSugerido,
)
from imagineer.modelos import TipoElemento

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


def _epub(
    *,
    titulo: str = "A Guerra dos Tronos",
    identificador: str = "urn:isbn:1",
    repeticoes: int = 6,
) -> bytes:
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")

    item = epub.EpubHtml(title="Capítulo 1", file_name="c1.xhtml", lang="pt-BR")
    item.content = f"<p>{TEXTO_LONGO * repeticoes}</p>"
    livro.add_item(item)

    livro.toc = (item,)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", item]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


def _epub_com_capitulos(
    *, titulo: str = "A Guerra dos Tronos", identificador: str = "urn:isbn:1", capitulos: int = 2
) -> bytes:
    """EPUB com N capítulos, cada um longo o bastante para não ser descartado."""
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")

    itens = []
    for numero in range(1, capitulos + 1):
        item = epub.EpubHtml(
            title=f"Capítulo {numero}", file_name=f"c{numero}.xhtml", lang="pt-BR"
        )
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
    resposta = cliente.post(
        "/livros", files={"arquivo": ("livro.epub", _epub(**kwargs), "application/epub+zip")}
    )
    assert resposta.status_code == 201
    return resposta.json()["livro"]


def _livro_com_capitulos(cliente: TestClient, **kwargs) -> dict:
    resposta = cliente.post(
        "/livros",
        files={"arquivo": ("livro.epub", _epub_com_capitulos(**kwargs), "application/epub+zip")},
    )
    assert resposta.status_code == 201
    return resposta.json()["livro"]


def _escolher_modelo_de_extracao(cliente: TestClient, modelo: str = MODELO_FALSO) -> None:
    resposta = cliente.put("/configuracao", json={"modelo_extracao": modelo})
    assert resposta.status_code == 200


def teste_sugestoes_devolve_o_que_o_provedor_deu(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(
                    tipo=TipoElemento.PERSONAGEM, nome="Jon", descricao="Um bastardo do norte."
                )
            ]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["gerado_em"] is not None
    (elemento,) = corpo["elementos"]
    assert elemento["modelo"] == MODELO_FALSO
    del elemento["id"]
    assert elemento == {
        "tipo": "PERSONAGEM",
        "nome": "Jon",
        "descricao": "Um bastardo do norte.",
        "manter_estado_atual": False,
        "elemento_id": None,
        "casamento_automatico": False,
        "estado_id": None,
        "modelo": MODELO_FALSO,
    }


def teste_sugestoes_devolve_cenas_com_participantes_casados(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Cada participante casa com o elemento já cadastrado, igual à lista de elementos."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A vigília no Muro",
                    descricao="Jon observa a neve cair.",
                    horario="noite",
                    clima="neve",
                    humor="solidão",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    jon = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    ).json()

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 200
    (cena,) = resposta.json()["cenas"]
    assert cena["titulo"] == "A vigília no Muro"
    assert cena["horario"] == "noite"
    assert cena["modelo"] == MODELO_FALSO
    (participante,) = cena["participantes"]
    assert participante["tipo"] == "PERSONAGEM"
    assert participante["nome"] == "Jon"
    assert participante["elemento_id"] == jon["id"]
    assert isinstance(participante["sugestao_elemento_id"], int)


def teste_sugestoes_sem_cenas_devolve_lista_vazia(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.json()["cenas"] == []


def teste_sugestoes_repetida_devolve_o_que_foi_salvo_sem_chamar_a_ia_de_novo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Sem `forcar`, a segunda chamada usa o cache — a IA não é determinística,
    então rechamar a cada leitura daria respostas divergentes (item 4.4)."""
    provedor = usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    primeira = cliente.post(f"/capitulos/{capitulo_id}/sugestoes")
    segunda = cliente.post(f"/capitulos/{capitulo_id}/sugestoes")

    assert len(provedor.chamadas_de_extracao) == 1
    assert primeira.json() == segunda.json()


def teste_sugestoes_com_forcar_chama_a_ia_de_novo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    cliente.post(f"/capitulos/{capitulo_id}/sugestoes")
    cliente.post(f"/capitulos/{capitulo_id}/sugestoes?forcar=true")

    assert len(provedor.chamadas_de_extracao) == 2


def teste_sugestoes_do_cache_recalcula_elemento_id_casado_depois(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Cadastrar o elemento depois da sugestão não exige `forcar`: o casamento
    é recalculado a cada leitura, só o texto vem do cache."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    primeira = cliente.post(f"/capitulos/{capitulo_id}/sugestoes")
    assert primeira.json()["elementos"][0]["elemento_id"] is None

    jon = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    ).json()

    segunda = cliente.post(f"/capitulos/{capitulo_id}/sugestoes")
    assert segunda.json()["elementos"][0]["elemento_id"] == jon["id"]


def teste_sugestoes_manda_o_texto_e_os_estados_conhecidos_ao_provedor(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "estado_inicial": {
                "capitulo_id": livro["capitulos"][0]["id"],
                "descricao": "Veste preto da Patrulha da Noite.",
            },
        },
    )

    cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert len(provedor.chamadas_de_extracao) == 1
    chamada = provedor.chamadas_de_extracao[0]
    assert chamada["modelo"] == MODELO_FALSO
    assert TEXTO_LONGO in chamada["texto_capitulo"]
    assert chamada["estados_conhecidos"] == [
        "Jon (PERSONAGEM): Veste preto da Patrulha da Noite."
    ]


def teste_sugestoes_casa_com_elemento_existente_ignorando_caixa_e_acento(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="joão")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "João"},
    ).json()

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.json()["elementos"][0]["elemento_id"] == elemento["id"]


# --------------------------------------------------------------------------- #
# casamento_automatico e estado_id (item 4.6) — sinalização de confiança
# --------------------------------------------------------------------------- #


def teste_casamento_automatico_marca_true_quando_a_rota_casa_sozinha(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Um casamento por nome, sem o usuário ter revisado esta sugestão
    especificamente, fica sinalizado como não revisado (item 4.6)."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    )

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    elemento = resposta.json()["elementos"][0]
    assert elemento["elemento_id"] is not None
    assert elemento["casamento_automatico"] is True


def teste_estado_id_nulo_quando_casado_mas_sem_estado_neste_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Achado com um caso real: sugestão casada não significa que virou Estado
    *neste* capítulo — o campo calculado torna isso visível (item 3.4e)."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    cap1, cap2 = livro["capitulos"]

    # Jon só tem Estado registrado no capítulo 1.
    cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "estado_inicial": {"capitulo_id": cap1["id"], "descricao": "Manto negro."},
        },
    )

    # Sugestão do capítulo 2 casa com o Jon já cadastrado, mas nenhum Estado
    # foi criado no capítulo 2 ainda.
    resposta = cliente.post(f"/capitulos/{cap2['id']}/sugestoes")

    elemento = resposta.json()["elementos"][0]
    assert elemento["elemento_id"] is not None
    assert elemento["estado_id"] is None


def teste_estado_id_preenchido_quando_ja_existe_estado_no_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo = livro["capitulos"][0]

    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "estado_inicial": {"capitulo_id": capitulo["id"], "descricao": "Manto negro."},
        },
    ).json()

    resposta = cliente.post(f"/capitulos/{capitulo['id']}/sugestoes")

    sugerido = resposta.json()["elementos"][0]
    assert sugerido["estado_id"] == elemento["estados"][0]["id"]


# --------------------------------------------------------------------------- #
# sugestoes_pendentes_anteriores (item 4.6) — aviso não-bloqueante
# --------------------------------------------------------------------------- #


def teste_sugestoes_pendentes_anteriores_conta_elementos_e_cenas_nao_confirmados(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon"),
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Robb"),
            ],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A partida",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    cap1, cap2 = livro["capitulos"]

    # Capítulo 1 gera duas sugestões de elemento e uma de cena, nenhuma confirmada.
    cliente.post(f"/capitulos/{cap1['id']}/sugestoes")

    resposta = cliente.post(f"/capitulos/{cap2['id']}/sugestoes")

    assert resposta.json()["sugestoes_pendentes_anteriores"] == 3


def teste_sugestoes_pendentes_anteriores_zero_no_primeiro_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Sem capítulo anterior, não há o que contar."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.json()["sugestoes_pendentes_anteriores"] == 0


def teste_sugestoes_pendentes_anteriores_nao_conta_ja_confirmadas(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    cap1, cap2 = livro["capitulos"]

    cliente.post(f"/capitulos/{cap1['id']}/sugestoes")
    cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    )
    # Recasar via nova leitura marca elemento_id — deixa de ser "pendente".
    cliente.post(f"/capitulos/{cap1['id']}/sugestoes")

    resposta = cliente.post(f"/capitulos/{cap2['id']}/sugestoes")

    assert resposta.json()["sugestoes_pendentes_anteriores"] == 0


# --------------------------------------------------------------------------- #
# PATCH /sugestoes-elemento/{id} (item 4.6) — corrigir só o casamento
# --------------------------------------------------------------------------- #


def teste_corrigir_casamento_sem_criar_estado(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Resolve o caso raro de o casamento automático ter errado: o usuário
    corrige o vínculo sem que um Estado seja criado como efeito colateral."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Hospius")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    elemento_certo = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Hospius"}
    ).json()
    elemento_errado = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Hrolf"}
    ).json()

    sugestao_id = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes"
    ).json()["elementos"][0]["id"]

    resposta = cliente.patch(
        f"/sugestoes-elemento/{sugestao_id}", json={"elemento_id": elemento_errado["id"]}
    )
    assert resposta.status_code == 200
    assert resposta.json()["elemento_id"] == elemento_errado["id"]
    assert resposta.json()["casamento_automatico"] is False

    # Corrige para o elemento certo — sem nenhum Estado ter sido criado.
    resposta = cliente.patch(
        f"/sugestoes-elemento/{sugestao_id}", json={"elemento_id": elemento_certo["id"]}
    )
    assert resposta.status_code == 200
    assert resposta.json()["elemento_id"] == elemento_certo["id"]

    assert cliente.get(f"/elementos/{elemento_certo['id']}").json()["estados"] == []
    assert cliente.get(f"/elementos/{elemento_errado['id']}").json()["estados"] == []


def teste_corrigir_casamento_para_nulo_desfaz_o_vinculo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    )
    sugestao_id = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes"
    ).json()["elementos"][0]["id"]

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao_id}", json={"elemento_id": None})

    assert resposta.status_code == 200
    assert resposta.json()["elemento_id"] is None


def teste_corrigir_casamento_com_elemento_de_outro_livro_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro1 = _livro_importado(cliente)
    livro2 = _livro_importado(cliente, identificador="urn:isbn:2")
    _escolher_modelo_de_extracao(cliente)

    de_outro_livro = cliente.post(
        f"/livros/{livro2['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    ).json()
    sugestao_id = cliente.post(
        f"/capitulos/{livro1['capitulos'][0]['id']}/sugestoes"
    ).json()["elementos"][0]["id"]

    resposta = cliente.patch(
        f"/sugestoes-elemento/{sugestao_id}", json={"elemento_id": de_outro_livro["id"]}
    )

    assert resposta.status_code == 422


def teste_corrigir_casamento_de_sugestao_inexistente_responde_404(
    cliente: TestClient,
) -> None:
    resposta = cliente.patch("/sugestoes-elemento/999", json={"elemento_id": None})
    assert resposta.status_code == 404


def teste_corrigir_casamento_com_elemento_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    sugestao_id = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes"
    ).json()["elementos"][0]["id"]

    resposta = cliente.patch(f"/sugestoes-elemento/{sugestao_id}", json={"elemento_id": 999})

    assert resposta.status_code == 404


def teste_sugestoes_nao_casa_elemento_de_tipo_diferente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.OBJETO, nome="João")])
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "João"},
    )

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.json()["elementos"][0]["elemento_id"] is None


def teste_sugestoes_sem_modelo_escolhido_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 422


def teste_sugestoes_sem_chave_de_api_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ChaveDeApiAusente("sem chave")))
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 422


def teste_sugestoes_com_erro_de_rede_responde_502(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("o serviço caiu")))
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 502


def teste_sugestoes_texto_longo_demais_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente, repeticoes=60)
    _escolher_modelo_de_extracao(cliente, modelo="falso/modelo-apertado")

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.status_code == 422


def teste_sugestoes_de_capitulo_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    assert cliente.post("/capitulos/999/sugestoes").status_code == 404


# --------------------------------------------------------------------------- #
# Sugestões persistidas: forcar preserva confirmadas (item 3.4e)
# --------------------------------------------------------------------------- #


def teste_forcar_preserva_sugestao_ja_confirmada(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Confirmar um elemento a partir da sugestão, e depois forçar uma sugestão
    nova, não apaga a sugestão já confirmada — só as ainda soltas."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon"),
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Sam"),
            ]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    primeira = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()
    jon_sugerido = next(e for e in primeira["elementos"] if e["nome"] == "Jon")

    cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "sugestoes_elemento_ids": [jon_sugerido["id"]],
        },
    )

    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Ghost")])
    )
    segunda = cliente.post(f"/capitulos/{capitulo_id}/sugestoes?forcar=true").json()

    nomes = {e["nome"] for e in segunda["elementos"]}
    assert "Jon" in nomes, "a sugestão já confirmada não deveria sumir"
    assert "Ghost" in nomes, "a sugestão nova deveria ter entrado"
    assert "Sam" not in nomes, "a sugestão antiga e não confirmada deveria ter sido substituída"

    jon_ainda = next(e for e in segunda["elementos"] if e["nome"] == "Jon")
    assert jon_ainda["id"] == jon_sugerido["id"]
    assert jon_ainda["elemento_id"] is not None


# --------------------------------------------------------------------------- #
# Confirmação em lote de sugestões de elemento (item 3.4e)
# --------------------------------------------------------------------------- #


def teste_criar_elemento_a_partir_de_sugestoes_de_capitulos_diferentes(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O caso do Hospius: duas sugestões, capítulos diferentes, nomes
    diferentes — confirmadas juntas, um Estado por capítulo, numa chamada só."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(
                    tipo=TipoElemento.PERSONAGEM,
                    nome="Sextus Hospius",
                    descricao="Um agente da Hierarquia.",
                )
            ]
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    primeiro, segundo = livro["capitulos"][0]["id"], livro["capitulos"][1]["id"]

    sugestao_1 = cliente.post(f"/capitulos/{primeiro}/sugestoes").json()["elementos"][0]

    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(
                    tipo=TipoElemento.PERSONAGEM,
                    nome="Hospius",
                    descricao="Reconhecido de um encontro anterior.",
                )
            ]
        )
    )
    sugestao_2 = cliente.post(f"/capitulos/{segundo}/sugestoes").json()["elementos"][0]

    resposta = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Sextus Hospius",
            "sugestoes_elemento_ids": [sugestao_1["id"], sugestao_2["id"]],
        },
    )

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert len(corpo["estados"]) == 2
    descricoes = {estado["descricao"] for estado in corpo["estados"]}
    assert descricoes == {"Um agente da Hierarquia.", "Reconhecido de um encontro anterior."}

    novamente = cliente.post(f"/capitulos/{primeiro}/sugestoes").json()
    assert novamente["elementos"][0]["elemento_id"] == corpo["id"]


def teste_sugestoes_elemento_ids_de_outro_livro_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")])
    )
    livro_1 = _livro_importado(cliente, identificador="urn:isbn:1")
    _escolher_modelo_de_extracao(cliente)
    sugestao = cliente.post(
        f"/capitulos/{livro_1['capitulos'][0]['id']}/sugestoes"
    ).json()["elementos"][0]

    livro_2 = _livro_importado(cliente, identificador="urn:isbn:2")

    resposta = cliente.post(
        f"/livros/{livro_2['id']}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "sugestoes_elemento_ids": [sugestao["id"]],
        },
    )

    assert resposta.status_code == 422


def teste_estados_de_sugestoes_cria_varios_estados_no_elemento_existente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Hospius", descricao="Cap. 1")
            ]
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    primeiro, segundo = livro["capitulos"][0]["id"], livro["capitulos"][1]["id"]

    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos",
        json={"tipo": "PERSONAGEM", "nome": "Sextus Hospius"},
    ).json()

    sugestao_1 = cliente.post(f"/capitulos/{primeiro}/sugestoes").json()["elementos"][0]

    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Hospius", descricao="Cap. 2")
            ]
        )
    )
    sugestao_2 = cliente.post(f"/capitulos/{segundo}/sugestoes").json()["elementos"][0]

    resposta = cliente.post(
        f"/elementos/{elemento['id']}/estados-de-sugestoes",
        json={"sugestoes_elemento_ids": [sugestao_1["id"], sugestao_2["id"]]},
    )

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert len(corpo) == 2
    assert {e["descricao"] for e in corpo} == {"Cap. 1", "Cap. 2"}
    assert {e["elemento_id"] for e in corpo} == {elemento["id"]}


def teste_estados_de_sugestoes_com_id_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    elemento = cliente.post(
        f"/livros/{livro['id']}/elementos", json={"tipo": "PERSONAGEM", "nome": "Jon"}
    ).json()

    resposta = cliente.post(
        f"/elementos/{elemento['id']}/estados-de-sugestoes",
        json={"sugestoes_elemento_ids": [999]},
    )

    assert resposta.status_code == 404


# --------------------------------------------------------------------------- #
# Busca de sugestões de elemento por nome (item 3.4e)
# --------------------------------------------------------------------------- #


def teste_busca_sugestoes_de_elemento_por_nome_cruza_capitulos(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[
                ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Sextus Hospius")
            ]
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    primeiro, segundo = livro["capitulos"][0]["id"], livro["capitulos"][1]["id"]

    cliente.post(f"/capitulos/{primeiro}/sugestoes")

    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Hospius")])
    )
    cliente.post(f"/capitulos/{segundo}/sugestoes")

    resposta = cliente.get(f"/livros/{livro['id']}/sugestoes-elemento?nome=hospius")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 2
    nomes = {item["nome"] for item in corpo}
    assert nomes == {"Sextus Hospius", "Hospius"}
    assert {item["capitulo_id"] for item in corpo} == {primeiro, segundo}


def teste_busca_sugestoes_de_elemento_ignora_caixa_e_acento(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="José")])
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    resposta = cliente.get(f"/livros/{livro['id']}/sugestoes-elemento?nome=jose")

    assert len(resposta.json()) == 1


def teste_busca_sugestoes_de_elemento_sem_correspondencia_devolve_vazio(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")])
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    resposta = cliente.get(f"/livros/{livro['id']}/sugestoes-elemento?nome=hospius")

    assert resposta.json() == []


# --------------------------------------------------------------------------- #
# Confirmar um frame a partir de uma cena sugerida (item 3.4e)
# --------------------------------------------------------------------------- #


def _confirmar_elemento_da_sugestao(
    cliente: TestClient, livro_id: int, sugestao_elemento_id: int, tipo: str = "PERSONAGEM", nome: str = "Jon"
) -> dict:
    resposta = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={"tipo": tipo, "nome": nome, "sugestoes_elemento_ids": [sugestao_elemento_id]},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def teste_criar_frame_a_partir_de_sugestao_de_cena(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Confirmado o elemento, o frame nasce direto da sugestão de cena — sem
    repetir título, descrição nem escolher o estado na mão (item 3.4e)."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A vigília no Muro",
                    descricao="Jon observa a neve cair.",
                    horario="noite",
                    clima="neve",
                    humor="solidão",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    sugestoes = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()
    sugestao_elemento = sugestoes["elementos"][0]
    sugestao_cena = sugestoes["cenas"][0]

    _confirmar_elemento_da_sugestao(cliente, livro["id"], sugestao_elemento["id"])

    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames", json={"sugestao_cena_id": sugestao_cena["id"]}
    )

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["titulo"] == "A vigília no Muro"
    assert corpo["descricao"] == "Jon observa a neve cair."
    assert corpo["horario"] == "noite"
    assert corpo["tipo"] == "CENA"
    assert corpo["total_de_elementos"] == 1


def teste_criar_frame_de_sugestao_com_campo_explicito_vence(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A vigília no Muro",
                    descricao="Jon observa a neve cair.",
                    horario="noite",
                    clima="neve",
                    humor="solidão",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    sugestoes = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()
    _confirmar_elemento_da_sugestao(cliente, livro["id"], sugestoes["elementos"][0]["id"])

    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={
            "sugestao_cena_id": sugestoes["cenas"][0]["id"],
            "titulo": "Título escolhido à mão",
        },
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["titulo"] == "Título escolhido à mão"


def teste_criar_frame_de_sugestao_com_participante_nao_confirmado_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A vigília no Muro",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    sugestoes = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()

    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/frames",
        json={"sugestao_cena_id": sugestoes["cenas"][0]["id"]},
    )

    assert resposta.status_code == 422


def teste_criar_frame_de_sugestao_de_outro_capitulo_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A vigília no Muro",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    primeiro, segundo = livro["capitulos"][0]["id"], livro["capitulos"][1]["id"]

    sugestoes = cliente.post(f"/capitulos/{primeiro}/sugestoes").json()

    resposta = cliente.post(
        f"/capitulos/{segundo}/frames",
        json={"sugestao_cena_id": sugestoes["cenas"][0]["id"]},
    )

    assert resposta.status_code == 422


def teste_criar_frame_de_sugestao_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)

    resposta = cliente.post(
        f"/capitulos/{livro['capitulos'][0]['id']}/frames",
        json={"sugestao_cena_id": 999},
    )

    assert resposta.status_code == 404


def teste_confirmar_a_mesma_cena_sugerida_duas_vezes_responde_409(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Sem isto, cada chamada criava um Frame novo, sobrescrevendo
    `SugestaoDeCena.frame_id` sem aviso — o Frame anterior ficava órfão no
    banco (item 4.6/6.4). Mesmo padrão já usado para elemento duplicado
    (item 6.3): 409 com o id do registro existente."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas_sugeridas=[
                CenaSugerida(
                    titulo="A vigília no Muro",
                    participantes=[
                        ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")
                    ],
                )
            ],
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    sugestoes = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()
    _confirmar_elemento_da_sugestao(cliente, livro["id"], sugestoes["elementos"][0]["id"])
    sugestao_cena_id = sugestoes["cenas"][0]["id"]

    primeira = cliente.post(
        f"/capitulos/{capitulo_id}/frames", json={"sugestao_cena_id": sugestao_cena_id}
    )
    assert primeira.status_code == 201
    frame_id = primeira.json()["id"]

    segunda = cliente.post(
        f"/capitulos/{capitulo_id}/frames", json={"sugestao_cena_id": sugestao_cena_id}
    )

    assert segunda.status_code == 409
    assert str(frame_id) in segunda.json()["detail"]
    # Nenhum Frame novo foi criado — só o primeiro existe.
    assert len(cliente.get(f"/capitulos/{capitulo_id}/frames").json()) == 1


# --------------------------------------------------------------------------- #
# sugestoes_pendentes em GET /livros/{id} (item 4.6) — indicador por capítulo
# --------------------------------------------------------------------------- #


def teste_livro_traz_sugestoes_pendentes_por_capitulo(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_com_capitulos(cliente, capitulos=2)
    _escolher_modelo_de_extracao(cliente)
    cap1, cap2 = livro["capitulos"]

    cliente.post(f"/capitulos/{cap1['id']}/sugestoes")

    resposta = cliente.get(f"/livros/{livro['id']}")

    capitulos = {c["id"]: c for c in resposta.json()["capitulos"]}
    assert capitulos[cap1["id"]]["sugestoes_pendentes"] == 1
    assert capitulos[cap2["id"]]["sugestoes_pendentes"] == 0


def teste_livro_nao_conta_sugestao_ja_confirmada_como_pendente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")]
        )
    )
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)
    capitulo_id = livro["capitulos"][0]["id"]

    sugestao_id = cliente.post(f"/capitulos/{capitulo_id}/sugestoes").json()["elementos"][0]["id"]
    _confirmar_elemento_da_sugestao(cliente, livro["id"], sugestao_id)

    resposta = cliente.get(f"/livros/{livro['id']}")

    capitulo = next(c for c in resposta.json()["capitulos"] if c["id"] == capitulo_id)
    assert capitulo["sugestoes_pendentes"] == 0
