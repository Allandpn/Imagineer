"""As narrações guardadas e o teste de voz (item 7.5g, AU3 e AU4).

Nenhum teste fala com o OpenRouter de verdade: o provedor é o ``ProvedorFalso`` (``MP3[n]`` por trecho, US$ 0,000001 por caractere).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ErroDoProvedorIA
from imagineer.modelos import AudioDeCapitulo, SituacaoDoAudio
from imagineer.rotas.audio import FRASE_DO_TESTE_DE_VOZ
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from testes.teste_narracao_por_ia import MODELO, VOZ, _capitulo, _escolher, narrar_com  # noqa: F401  (a fixture e os auxiliares)
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)


def _gerar(cliente: TestClient, capitulo_id: int, modelo: str = MODELO, voz: str | None = VOZ) -> None:
    _escolher(cliente, modelo, voz)
    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code in (200, 202)


# --------------------------------------------------------------------------- #
# AU3: listar, tocar e apagar uma narração guardada
# --------------------------------------------------------------------------- #


def teste_o_capitulo_sem_narracao_tem_lista_vazia(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")

    assert cliente.get(f"/capitulos/{capitulo_id}/audios").json() == []


def teste_a_lista_traz_as_narracoes_prontas_de_todos_os_modelos_e_vozes_da_mais_nova_para_a_mais_antiga(
    cliente: TestClient, sessao_com_tabelas, narrar_com
) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _gerar(cliente, capitulo_id, MODELO, VOZ)
    _gerar(cliente, capitulo_id, "fish-audio/s2.1-pro-free:free", None)

    lista = cliente.get(f"/capitulos/{capitulo_id}/audios").json()

    assert [(a["modelo"], a["voz"]) for a in lista] == [("fish-audio/s2.1-pro-free:free", None), (MODELO, VOZ)]
    assert lista[0]["id"] > lista[1]["id"]
    assert lista[0]["caracteres"] == len("Um texto curto.") and lista[0]["tamanho_em_bytes"] > 0
    assert Decimal(lista[1]["custo"]) > 0


def teste_de_agora_marca_so_a_feita_com_o_modelo_e_a_voz_escolhidos_agora(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _gerar(cliente, capitulo_id, MODELO, VOZ)
    _gerar(cliente, capitulo_id, "fish-audio/s2.1-pro-free:free", None)

    _escolher(cliente, MODELO, VOZ)
    de_agora = {a["modelo"]: a["de_agora"] for a in cliente.get(f"/capitulos/{capitulo_id}/audios").json()}

    assert de_agora == {MODELO: True, "fish-audio/s2.1-pro-free:free": False}


def teste_a_lista_nao_mostra_a_que_esta_sendo_gerada_nem_a_que_falhou(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _gerar(cliente, capitulo_id)
    sessao_com_tabelas.add(AudioDeCapitulo(capitulo_id=capitulo_id, modelo="outro/modelo", voz="", situacao=SituacaoDoAudio.GERANDO))
    sessao_com_tabelas.add(AudioDeCapitulo(capitulo_id=capitulo_id, modelo="mais/um", voz="", situacao=SituacaoDoAudio.FALHOU, erro="x"))
    sessao_com_tabelas.commit()

    assert [a["modelo"] for a in cliente.get(f"/capitulos/{capitulo_id}/audios").json()] == [MODELO]


def teste_listar_de_um_capitulo_que_nao_existe_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/capitulos/9999/audios").status_code == 404


def teste_o_arquivo_de_uma_narracao_antiga_toca_pelo_id_e_aceita_range(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _gerar(cliente, capitulo_id, MODELO, VOZ)
    antigo = cliente.get(f"/capitulos/{capitulo_id}/audios").json()[0]["id"]
    _gerar(cliente, capitulo_id, "fish-audio/s2.1-pro-free:free", None)  # agora o de "agora" é outro; o antigo continua tocável

    inteiro = cliente.get(f"/audios/{antigo}/arquivo")
    assert inteiro.status_code == 200 and inteiro.headers["content-type"] == "audio/mpeg"
    assert inteiro.content.startswith(b"MP3[")
    assert inteiro.headers["cache-control"] == "no-cache"

    pedaco = cliente.get(f"/audios/{antigo}/arquivo", headers={"Range": "bytes=0-2"})
    assert pedaco.status_code == 206 and pedaco.content == b"MP3"


def teste_o_arquivo_de_um_audio_que_nao_existe_ou_nao_esta_pronto_responde_404(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    gerando = AudioDeCapitulo(capitulo_id=capitulo_id, modelo="x/y", voz="", situacao=SituacaoDoAudio.GERANDO)
    sessao_com_tabelas.add(gerando)
    sessao_com_tabelas.commit()

    assert cliente.get("/audios/9999/arquivo").status_code == 404
    assert cliente.get(f"/audios/{gerando.id}/arquivo").status_code == 404


def teste_o_arquivo_que_sumiu_do_disco_responde_404_com_o_aviso(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _gerar(cliente, capitulo_id)
    audio = sessao_com_tabelas.scalar(select(AudioDeCapitulo))
    caminho_absoluto(audio.arquivo).unlink()

    resposta = cliente.get(f"/audios/{audio.id}/arquivo")

    assert resposta.status_code == 404 and "Gere de novo" in resposta.json()["detail"]


def teste_apagar_uma_narracao_tira_a_linha_e_o_arquivo_e_deixa_as_outras(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _gerar(cliente, capitulo_id, MODELO, VOZ)
    _gerar(cliente, capitulo_id, "fish-audio/s2.1-pro-free:free", None)
    sessao_com_tabelas.expire_all()
    a_apagar = sessao_com_tabelas.scalar(select(AudioDeCapitulo).where(AudioDeCapitulo.modelo == MODELO))
    caminho = caminho_absoluto(a_apagar.arquivo)
    assert caminho.is_file()

    resposta = cliente.delete(f"/audios/{a_apagar.id}")

    assert resposta.status_code == 204
    assert not caminho.exists()
    assert [a["modelo"] for a in cliente.get(f"/capitulos/{capitulo_id}/audios").json()] == ["fish-audio/s2.1-pro-free:free"]
    assert cliente.delete(f"/audios/{a_apagar.id}").status_code == 404


def teste_nao_se_apaga_uma_narracao_que_ainda_esta_sendo_gerada(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    gerando = AudioDeCapitulo(capitulo_id=capitulo_id, modelo="x/y", voz="", situacao=SituacaoDoAudio.GERANDO)
    sessao_com_tabelas.add(gerando)
    sessao_com_tabelas.commit()

    resposta = cliente.delete(f"/audios/{gerando.id}")

    assert resposta.status_code == 409 and "sendo gerada" in resposta.json()["detail"]
    assert sessao_com_tabelas.get(AudioDeCapitulo, gerando.id) is not None


# --------------------------------------------------------------------------- #
# AU4: testar a voz
# --------------------------------------------------------------------------- #


def teste_a_estimativa_do_teste_diz_a_frase_os_caracteres_e_o_custo_pelo_preco_do_catalogo(cliente: TestClient, narrar_com) -> None:
    narrar_com()
    _escolher(cliente)

    corpo = cliente.get("/configuracao/narracao/teste").json()

    assert corpo["frase"] == FRASE_DO_TESTE_DE_VOZ and corpo["caracteres"] == len(FRASE_DO_TESTE_DE_VOZ)
    assert Decimal(corpo["custo_estimado"]) == (Decimal("0.000015") * len(FRASE_DO_TESTE_DE_VOZ)).quantize(Decimal("0.0001"))
    assert corpo["modelo"] == MODELO and corpo["voz"] == VOZ
    assert len(FRASE_DO_TESTE_DE_VOZ) < 150  # curta de propósito: custa uma fração de centavo


def teste_a_estimativa_aceita_outro_modelo_e_outra_voz_sem_mexer_na_configuracao(cliente: TestClient, narrar_com) -> None:
    narrar_com()
    _escolher(cliente)

    corpo = cliente.get("/configuracao/narracao/teste", params={"modelo": "fish-audio/s2.1-pro-free:free", "voz": "x"}).json()

    assert corpo["modelo"] == "fish-audio/s2.1-pro-free:free" and corpo["voz"] == "x"
    assert Decimal(corpo["custo_estimado"]) == 0  # modelo gratuito
    assert cliente.get("/configuracao").json()["modelo_narracao"] == MODELO  # a configuração não mudou


def teste_a_estimativa_sem_preco_ou_sem_catalogo_vem_nula_e_sem_modelo_responde_422(cliente: TestClient, narrar_com) -> None:
    provedor = narrar_com()
    assert cliente.get("/configuracao/narracao/teste").status_code == 422  # nenhum modelo escolhido

    _escolher(cliente, "google/gemini-3.8-flash-tts", "Zephyr")
    assert cliente.get("/configuracao/narracao/teste").json()["custo_estimado"] is None  # cobra por token

    _escolher(cliente)
    provedor._erro = ErroDoProvedorIA("fora do ar")
    assert cliente.get("/configuracao/narracao/teste").json()["custo_estimado"] is None  # o catálogo não respondeu


def teste_testar_a_voz_devolve_o_mp3_da_frase_e_o_custo_no_cabecalho_sem_guardar_nada(cliente: TestClient, narrar_com) -> None:
    provedor = narrar_com()
    _escolher(cliente)

    resposta = cliente.post("/configuracao/narracao/teste")

    assert resposta.status_code == 200 and resposta.headers["content-type"] == "audio/mpeg"
    assert resposta.content == b"MP3[1]"
    assert provedor.chamadas_de_narracao == [(FRASE_DO_TESTE_DE_VOZ, MODELO, VOZ)]
    assert Decimal(resposta.headers["x-custo-estimado"]) == Decimal(len(FRASE_DO_TESTE_DE_VOZ)) / 1_000_000


def teste_testar_a_voz_nao_cria_linha_de_audio_nem_arquivo(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    _escolher(cliente)

    cliente.post("/configuracao/narracao/teste")

    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_testar_com_outro_modelo_e_voz_usa_os_do_pedido(cliente: TestClient, narrar_com) -> None:
    provedor = narrar_com()
    _escolher(cliente)

    cliente.post("/configuracao/narracao/teste", json={"modelo": "fish-audio/s2.1-pro-free:free", "voz": "v1"})

    assert provedor.chamadas_de_narracao == [(FRASE_DO_TESTE_DE_VOZ, "fish-audio/s2.1-pro-free:free", "v1")]


def teste_testar_outro_modelo_nao_herda_a_voz_do_modelo_da_configuracao(cliente: TestClient, narrar_com) -> None:
    provedor = narrar_com()
    _escolher(cliente)  # a voz da configuração é a do modelo da Microsoft

    cliente.post("/configuracao/narracao/teste", json={"modelo": "fish-audio/s2.1-pro-free:free"})

    assert provedor.chamadas_de_narracao == [(FRASE_DO_TESTE_DE_VOZ, "fish-audio/s2.1-pro-free:free", None)]


def teste_testar_sem_modelo_sem_chave_ou_com_falha_do_provedor_responde_com_o_erro_certo(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())
    resposta = cliente.post("/configuracao/narracao/teste")
    assert resposta.status_code == 422 and "Configurações → Narração" in resposta.json()["detail"]

    _escolher(cliente)
    usar_provedor_falso(ProvedorFalso(pode_narrar=False))
    resposta = cliente.post("/configuracao/narracao/teste")
    assert resposta.status_code == 422 and "CHAVE_API_OPENROUTER" in resposta.json()["detail"]

    usar_provedor_falso(ProvedorFalso(narracao_falha_no_trecho=1))
    resposta = cliente.post("/configuracao/narracao/teste")
    assert resposta.status_code == 502 and "falha de teste" in resposta.json()["detail"]
