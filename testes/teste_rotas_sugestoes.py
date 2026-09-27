"""Testes de `POST /capitulos/{id}/sugestoes` (Etapa 6.7).

A rota não grava nada no banco — é consulta pura, fiel ao item 4.4: a IA
sugere, o usuário confirma depois pelas rotas de cadastro da Etapa 6.3.
"""

import io

from ebooklib import epub
from fastapi.testclient import TestClient

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import (
    CenaSugerida,
    ChaveDeApiAusente,
    ElementoSugerido,
    ErroDoProvedorIA,
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


def _livro_importado(cliente: TestClient, **kwargs) -> dict:
    resposta = cliente.post(
        "/livros", files={"arquivo": ("livro.epub", _epub(**kwargs), "application/epub+zip")}
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
    assert corpo["modelo"] == MODELO_FALSO
    assert corpo["elementos"] == [
        {
            "tipo": "PERSONAGEM",
            "nome": "Jon",
            "descricao": "Um bastardo do norte.",
            "manter_estado_atual": False,
            "elemento_id": None,
        }
    ]


def teste_sugestoes_devolve_cenas_com_participantes_casados(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """Cada participante casa com o elemento já cadastrado, igual à lista de elementos."""
    usar_provedor_falso(
        ProvedorFalso(
            elementos=[ElementoSugerido(tipo=TipoElemento.PERSONAGEM, nome="Jon")],
            cenas=[
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
    assert cena["participantes"] == [
        {"tipo": "PERSONAGEM", "nome": "Jon", "elemento_id": jon["id"]}
    ]


def teste_sugestoes_sem_cenas_devolve_lista_vazia(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro_importado(cliente)
    _escolher_modelo_de_extracao(cliente)

    resposta = cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/sugestoes")

    assert resposta.json()["cenas"] == []


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
