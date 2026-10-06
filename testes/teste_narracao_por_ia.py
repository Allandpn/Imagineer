"""A narração por voz de IA (itens NA1 a NA10): dividir o capítulo, falar pelo OpenRouter, guardar, estimar, registrar o gasto e servir o arquivo.

Nenhum teste fala com o OpenRouter de verdade: o provedor é o ``ProvedorFalso`` ou o ``ProvedorOpenRouter`` com um transporte falso do ``httpx``.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, ModeloNaoEscolhido, UsoDaChamada
from imagineer.modelos import AudioDeCapitulo, Capitulo, Livro, SituacaoDoAudio
from imagineer.servicos import narracao, uso_de_ia
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from imagineer.servicos.trechos_da_narracao import CARACTERES_POR_MINUTO, LIMITE_DO_TRECHO, dividir_em_trechos
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _livro

MODELO = "microsoft/mai-voice-2.1-flash"
VOZ = "pt-BR-Luana:MAI-Voice-2.1-Flash"


# --------------------------------------------------------------------------- #
# NA2: dividir em trechos
# --------------------------------------------------------------------------- #


def teste_texto_curto_vira_um_trecho_so() -> None:
    assert dividir_em_trechos("Um parágrafo.\nOutro parágrafo.") == ["Um parágrafo.\n\nOutro parágrafo."]


def teste_paragrafos_que_nao_cabem_juntos_viram_trechos_separados_em_fim_de_paragrafo() -> None:
    a, b, c = "A" * 60, "B" * 60, "C" * 60
    assert dividir_em_trechos(f"{a}\n{b}\n{c}", limite=130) == [f"{a}\n\n{b}", c]


def teste_paragrafo_gigante_corta_em_fim_de_frase() -> None:
    frases = [f"Frase número {i}." for i in range(40)]
    trechos = dividir_em_trechos(" ".join(frases), limite=120)
    assert len(trechos) > 1
    assert all(len(trecho) <= 120 for trecho in trechos)
    assert all(trecho.endswith(".") for trecho in trechos)  # nunca no meio de uma frase
    assert " ".join(trechos) == " ".join(frases)


def teste_frase_gigante_corta_no_ultimo_espaco_e_sem_espaco_corta_no_limite() -> None:
    palavras = " ".join(["palavra"] * 50)
    trechos = dividir_em_trechos(palavras, limite=100)
    assert all(len(t) <= 100 and not t.startswith(" ") for t in trechos)
    assert " ".join(trechos) == palavras

    assert dividir_em_trechos("x" * 250, limite=100) == ["x" * 100, "x" * 100, "x" * 50]


def teste_nenhum_caractere_se_perde_e_nenhum_trecho_passa_do_limite() -> None:
    texto = "\n".join(("Era uma vez um capítulo. " * n).strip() for n in (3, 400, 7, 900, 1))
    trechos = dividir_em_trechos(texto)
    assert all(len(t) <= LIMITE_DO_TRECHO for t in trechos)
    assert "".join(trechos).replace("\n", "").replace(" ", "") == texto.replace("\n", "").replace(" ", "")


# --------------------------------------------------------------------------- #
# NA1 e NA3: o OpenRouter (provedor com transporte falso)
# --------------------------------------------------------------------------- #

CATALOGO = {
    "data": [
        {"id": MODELO, "name": "Microsoft: MAI-Voice 2.1 Flash", "pricing": {"prompt": "0.000015"}, "supported_voices": [VOZ, "pt-BR-Caio:MAI-Voice-2.1-Flash"]},
        {"id": "google/gemini-3.8-flash-tts", "name": "Gemini TTS", "pricing": {"prompt": "0.0000005", "completion": "0.000009"}, "supported_voices": ["Zephyr"]},
        {"id": "bytedance-seed/seed-audio-1-0", "name": "Seed Audio", "pricing": {"prompt": "0", "completion": "0.0025"}},
        {"id": "fish-audio/s2.1-pro-free:free", "name": "Fish Free", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "sem/preco", "name": "Sem preço", "pricing": {}},
        {"name": "sem id"},
    ]
}


def _openrouter(
    audio: httpx.Response | None = None, avisos: list | None = None, pedidos: list | None = None, catalogo: httpx.Response | None = None, chave: str | None = "sk-teste"
) -> ProvedorOpenRouter:
    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path.endswith("/models"):
            return catalogo or httpx.Response(200, json=CATALOGO)
        if pedidos is not None:
            pedidos.append((pedido.url.path, dict(pedido.headers), json.loads(pedido.content)))
        return audio or httpx.Response(200, content=b"MP3", headers={"content-type": "audio/mpeg", "x-generation-id": "gen-voz-1"})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api=chave, cliente=cliente, ao_usar=avisos.append if avisos is not None else None)


def teste_o_catalogo_de_voz_traz_vozes_e_o_preco_por_caractere_so_quando_da_para_estimar() -> None:
    modelos = {m.id: m for m in _openrouter().listar_modelos_de_voz()}

    assert set(modelos) == {MODELO, "google/gemini-3.8-flash-tts", "bytedance-seed/seed-audio-1-0", "fish-audio/s2.1-pro-free:free", "sem/preco"}
    assert modelos[MODELO].preco_por_caractere == Decimal("0.000015") and modelos[MODELO].vozes == [VOZ, "pt-BR-Caio:MAI-Voice-2.1-Flash"]
    assert modelos["google/gemini-3.8-flash-tts"].preco_por_caractere is None  # entrada + saída por token: não dá para estimar
    assert modelos["bytedance-seed/seed-audio-1-0"].preco_por_caractere is None and not modelos["bytedance-seed/seed-audio-1-0"].gratuito  # por segundo
    assert modelos["fish-audio/s2.1-pro-free:free"].gratuito and modelos["fish-audio/s2.1-pro-free:free"].preco_por_caractere == 0
    assert modelos["sem/preco"].preco_por_caractere is None and not modelos["sem/preco"].gratuito  # sem preço ≠ gratuito


def teste_o_catalogo_vem_com_os_gratuitos_primeiro() -> None:
    assert _openrouter().listar_modelos_de_voz()[0].id == "fish-audio/s2.1-pro-free:free"


def teste_narrar_envia_modelo_voz_texto_e_mp3_e_devolve_audio_custo_e_id() -> None:
    pedidos: list = []
    audio = _openrouter(pedidos=pedidos).narrar("Era uma vez.", MODELO, VOZ)

    assert audio.conteudo == b"MP3" and audio.id_da_geracao == "gen-voz-1"
    assert audio.custo == Decimal("0.00018000")  # 12 caracteres × 0,000015
    (caminho, cabecalhos, corpo), = pedidos
    assert caminho.endswith("/audio/speech") and cabecalhos["authorization"] == "Bearer sk-teste"
    assert corpo == {"model": MODELO, "input": "Era uma vez.", "response_format": "mp3", "voice": VOZ}


def teste_sem_voz_o_campo_nao_vai_no_pedido() -> None:
    pedidos: list = []
    _openrouter(pedidos=pedidos).narrar("Texto.", MODELO, None)
    assert "voice" not in pedidos[0][2]


def teste_cada_trecho_falado_e_avisado_como_gasto_estimado_com_o_id_da_geracao() -> None:
    avisos: list[UsoDaChamada] = []
    _openrouter(avisos=avisos).narrar("Era uma vez.", MODELO, VOZ)

    (uso,) = avisos
    assert (uso.operacao, uso.modelo, uso.provedor, uso.estimado, uso.id_da_geracao) == ("narracao", MODELO, "openrouter", True, "gen-voz-1")
    assert uso.custo == Decimal("0.00018000")


def teste_modelo_que_nao_cobra_por_caractere_fala_mas_fica_sem_custo_e_nao_estimado() -> None:
    avisos: list[UsoDaChamada] = []
    audio = _openrouter(avisos=avisos).narrar("Texto.", "google/gemini-3.8-flash-tts", "Zephyr")

    assert audio.custo is None
    assert avisos[0].custo is None and avisos[0].estimado is False  # nunca um zero inventado


def teste_catalogo_fora_do_ar_nao_derruba_a_narracao_so_deixa_o_custo_em_branco() -> None:
    audio = _openrouter(catalogo=httpx.Response(503, text="fora")).narrar("Texto.", MODELO, VOZ)
    assert audio.conteudo == b"MP3" and audio.custo is None


def teste_falhas_viram_erros_em_portugues() -> None:
    with pytest.raises(ChaveDeApiAusente, match="recusou a chave"):
        _openrouter(audio=httpx.Response(401, text="no")).narrar("x", MODELO, VOZ)
    with pytest.raises(ErroDoProvedorIA, match="saldo"):
        _openrouter(audio=httpx.Response(402, text="pay")).narrar("x", MODELO, VOZ)
    with pytest.raises(ErroDoProvedorIA, match="500"):
        _openrouter(audio=httpx.Response(500, text="boom")).narrar("x", MODELO, VOZ)
    with pytest.raises(ErroDoProvedorIA, match="não devolveu um áudio"):
        _openrouter(audio=httpx.Response(200, content=b"")).narrar("x", MODELO, VOZ)
    with pytest.raises(ErroDoProvedorIA, match="não devolveu um áudio"):
        _openrouter(audio=httpx.Response(200, json={"erro": "x"})).narrar("x", MODELO, VOZ)


def teste_erro_de_voz_do_modelo_aponta_para_a_tela_de_narracao() -> None:
    with pytest.raises(ErroDoProvedorIA, match="Configurações → Narração"):
        _openrouter(audio=httpx.Response(400, json={"error": {"message": "voice is required"}})).narrar("x", MODELO, None)


def teste_sem_chave_ou_sem_modelo_a_narracao_nem_sai() -> None:
    sem_chave = _openrouter(chave=None)
    assert sem_chave.pode_narrar is False
    with pytest.raises(ChaveDeApiAusente):
        sem_chave.narrar("x", MODELO, VOZ)
    with pytest.raises(ModeloNaoEscolhido):
        _openrouter().narrar("x", "", VOZ)


# --------------------------------------------------------------------------- #
# As rotas
# --------------------------------------------------------------------------- #


def _capitulo(cliente: TestClient, sessao: Session, texto: str | None = None) -> int:
    capitulo_id = _livro(cliente)["capitulos"][0]["id"]
    if texto is not None:
        sessao.get(Capitulo, capitulo_id).texto = texto
        sessao.commit()
    return capitulo_id


def _tres_trechos() -> str:
    """Três parágrafos de 2.000 caracteres: nenhum par cabe junto no limite de 2.500, então são três trechos."""
    return "\n".join(f"{letra}" * 2000 for letra in "ABC")


def _escolher(cliente: TestClient, modelo: str | None = MODELO, voz: str | None = VOZ) -> None:
    resposta = cliente.put("/configuracao", json={"modelo_narracao": modelo, "narracao_voz": voz})
    assert resposta.status_code == 200, resposta.text


@pytest.fixture
def narrar_com(usar_provedor_falso, usar_criador_de_sessao_de_teste):
    """``narrar_com(**opcoes)`` põe um ``ProvedorFalso`` no lugar do provedor e liga o segundo plano ao banco de teste."""

    def preparar(**opcoes) -> ProvedorFalso:
        return usar_provedor_falso(ProvedorFalso(**opcoes))

    return preparar


def teste_escolher_o_modelo_de_voz_grava_e_apagar_com_vazio_desfaz(cliente: TestClient) -> None:
    assert cliente.get("/configuracao").json()["modelo_narracao"] is None
    _escolher(cliente)
    corpo = cliente.get("/configuracao").json()
    assert corpo["modelo_narracao"] == MODELO and corpo["narracao_voz"] == VOZ

    cliente.put("/configuracao", json={"modelo_narracao": "  "})
    assert cliente.get("/configuracao").json()["modelo_narracao"] is None


def teste_a_lista_de_modelos_de_voz_traz_vozes_preco_e_gratuito(cliente: TestClient, narrar_com) -> None:
    narrar_com()

    resposta = cliente.get("/configuracao/modelos-de-narracao")

    assert resposta.status_code == 200
    por_id = {m["id"]: m for m in resposta.json()}
    assert por_id[MODELO]["vozes"][0].startswith("pt-BR-") and Decimal(por_id[MODELO]["preco_por_caractere"]) == Decimal("0.000015")
    assert por_id["google/gemini-3.8-flash-tts"]["preco_por_caractere"] is None
    assert por_id["fish-audio/s2.1-pro-free:free"]["gratuito"] is True


def teste_a_lista_de_modelos_de_voz_com_o_servico_fora_do_ar_responde_502(cliente: TestClient, narrar_com) -> None:
    narrar_com(erro=ErroDoProvedorIA("fora do ar"))
    assert cliente.get("/configuracao/modelos-de-narracao").status_code == 502


def teste_estimativa_diz_caracteres_minutos_e_custo_pelo_preco_do_catalogo(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "x" * (CARACTERES_POR_MINUTO * 2))
    _escolher(cliente)

    corpo = cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa").json()

    assert corpo["caracteres"] == 1800 and corpo["minutos"] == 2.0
    assert Decimal(corpo["custo_estimado"]) == Decimal("0.0270")  # 1800 × 0,000015
    assert corpo["modelo"] == MODELO and corpo["voz"] == VOZ and corpo["ja_gerado"] is False


def teste_estimativa_sem_preco_por_caractere_ou_sem_catalogo_vem_nula_e_sem_modelo_responde_422(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "x" * 100)
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa").status_code == 422  # nenhum modelo escolhido

    _escolher(cliente, "google/gemini-3.8-flash-tts", "Zephyr")
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa").json()["custo_estimado"] is None  # cobra por token

    _escolher(cliente)
    provedor._erro = ErroDoProvedorIA("fora do ar")
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa").json()["custo_estimado"] is None  # o catálogo não respondeu


def teste_gerar_sem_modelo_sem_chave_ou_sem_texto_responde_422_e_nao_cria_nada(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas)
    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")  # nenhum modelo escolhido
    assert resposta.status_code == 422 and "Configurações → Narração" in resposta.json()["detail"]

    _escolher(cliente)
    narrar_com(pode_narrar=False)
    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert resposta.status_code == 422 and "CHAVE_API_OPENROUTER" in resposta.json()["detail"]

    narrar_com()
    sessao_com_tabelas.get(Capitulo, capitulo_id).texto = "   \n "
    sessao_com_tabelas.commit()
    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code == 422

    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_gerar_usa_o_modelo_e_a_voz_da_configuracao_e_deixa_o_audio_pronto(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())
    _escolher(cliente)

    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert resposta.status_code == 202
    assert resposta.json()["situacao"] == "GERANDO"  # o que a rota respondeu na hora; o resto roda em segundo plano
    assert [(len(t), m, v) for t, m, v in provedor.chamadas_de_narracao] == [(2000, MODELO, VOZ)] * 3

    estado = cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()
    assert estado["situacao"] == "PRONTO" and estado["modelo"] == MODELO and estado["voz"] == VOZ and estado["erro"] is None
    assert estado["caracteres"] == 6002 and estado["tamanho_em_bytes"] == len(b"MP3[1]MP3[2]MP3[3]")
    assert Decimal(estado["custo"]) == Decimal(6000) / 1_000_000


def teste_sem_voz_escolhida_a_narracao_vai_com_a_voz_padrao_do_modelo(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _escolher(cliente, voz=None)

    cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert provedor.chamadas_de_narracao == [("Um texto curto.", MODELO, None)]


def teste_o_arquivo_e_a_juncao_dos_trechos_em_ordem_e_aceita_range(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())
    _escolher(cliente)
    cliente.post(f"/capitulos/{capitulo_id}/audio")

    inteiro = cliente.get(f"/capitulos/{capitulo_id}/audio")
    assert inteiro.status_code == 200 and inteiro.headers["content-type"] == "audio/mpeg"
    assert inteiro.content == b"MP3[1]MP3[2]MP3[3]"
    assert inteiro.headers["cache-control"] == "no-cache"

    pedaco = cliente.get(f"/capitulos/{capitulo_id}/audio", headers={"Range": "bytes=6-11"})
    assert pedaco.status_code == 206 and pedaco.content == b"MP3[2]"


def teste_o_gasto_de_cada_trecho_e_anotado_com_o_livro_do_capitulo(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    class ProvedorQueConfereOLivro(ProvedorFalso):
        livros_vistos: list = []

        def narrar(self, texto, modelo, voz):
            self.livros_vistos.append(uso_de_ia._livro_do_gasto.get())
            return super().narrar(texto, modelo, voz)

    from imagineer.rotas.configuracao import obter_provedor
    from imagineer.principal import aplicacao

    aplicacao.dependency_overrides[obter_provedor] = lambda: ProvedorQueConfereOLivro()
    livro = _livro(cliente)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao_com_tabelas.get(Capitulo, capitulo_id).texto = _tres_trechos()
    sessao_com_tabelas.commit()
    _escolher(cliente)

    cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert ProvedorQueConfereOLivro.livros_vistos == [livro["id"]] * 3  # o provedor anota dentro de gasto_do_livro (NA6)


def teste_falha_no_meio_marca_falhou_sem_arquivo_e_guarda_o_custo_dos_trechos_feitos(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com(narracao_falha_no_trecho=2)
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())
    _escolher(cliente)

    cliente.post(f"/capitulos/{capitulo_id}/audio")

    estado = cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()
    assert estado["situacao"] == "FALHOU" and "falha de teste" in estado["erro"]
    assert estado["tamanho_em_bytes"] is None
    assert Decimal(estado["custo"]) == Decimal("0.002")  # o primeiro trecho foi cobrado
    assert not any(caminho_absoluto("audios").rglob("*.mp3"))  # nunca há arquivo parcial (NA7)
    assert cliente.get(f"/capitulos/{capitulo_id}/audio").status_code == 404


def teste_ja_pronto_devolve_200_sem_gastar_e_refazer_gera_de_novo_e_substitui_o_antigo(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _escolher(cliente)
    primeiro = cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert primeiro.status_code == 202 and len(provedor.chamadas_de_narracao) == 1
    arquivo_antigo = caminho_absoluto(sessao_com_tabelas.scalars(select(AudioDeCapitulo.arquivo)).one())
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa").json()["ja_gerado"] is True

    de_novo = cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert de_novo.status_code == 200 and de_novo.json()["situacao"] == "PRONTO"
    assert len(provedor.chamadas_de_narracao) == 1  # nenhuma chamada nova, nenhum gasto

    refeito = cliente.post(f"/capitulos/{capitulo_id}/audio", json={"refazer": True})
    assert refeito.status_code == 202 and len(provedor.chamadas_de_narracao) == 2
    linhas = sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all()
    assert len(linhas) == 1 and linhas[0].situacao == SituacaoDoAudio.PRONTO  # o antigo saiu
    assert not arquivo_antigo.exists() and caminho_absoluto(linhas[0].arquivo).is_file()


def teste_ja_gerando_responde_409(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    provedor = narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas)
    _escolher(cliente)
    sessao_com_tabelas.add(AudioDeCapitulo(capitulo_id=capitulo_id, modelo=MODELO, voz=VOZ, situacao=SituacaoDoAudio.GERANDO))
    sessao_com_tabelas.commit()

    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert resposta.status_code == 409 and provedor.chamadas_de_narracao == []


def teste_gerando_preso_ha_mais_de_30_minutos_vale_como_falhou_e_libera_uma_nova_geracao(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _escolher(cliente)
    sessao_com_tabelas.add(
        AudioDeCapitulo(
            capitulo_id=capitulo_id, modelo=MODELO, voz=VOZ, situacao=SituacaoDoAudio.GERANDO,
            criado_em=datetime.now(timezone.utc) - timedelta(minutes=31),
        )
    )
    sessao_com_tabelas.commit()

    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "FALHOU"
    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code == 202
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "PRONTO"


def teste_trocar_a_voz_ou_o_modelo_gera_outro_audio_e_o_antigo_nao_conta(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _escolher(cliente)
    cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "PRONTO"

    _escolher(cliente, voz="pt-BR-Caio:MAI-Voice-2.1-Flash")
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "NAO_GERADO"
    assert cliente.get(f"/capitulos/{capitulo_id}/audio").status_code == 404
    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code == 202

    _escolher(cliente, modelo="google/gemini-3.8-flash-tts", voz="Zephyr")
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "NAO_GERADO"
    assert len(sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all()) == 2  # os dois ficam (NA4)


def teste_apagar_remove_as_linhas_e_os_arquivos(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    narrar_com()
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    _escolher(cliente)
    cliente.post(f"/capitulos/{capitulo_id}/audio")
    arquivo = caminho_absoluto(sessao_com_tabelas.scalars(select(AudioDeCapitulo.arquivo)).one())
    assert arquivo.is_file()

    assert cliente.delete(f"/capitulos/{capitulo_id}/audio").status_code == 204

    assert not arquivo.exists()
    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_apagar_o_livro_de_vez_leva_os_arquivos_de_narracao(cliente: TestClient, sessao_com_tabelas, narrar_com) -> None:
    from imagineer.servicos.lixeira import apagar_livro_de_vez

    narrar_com()
    livro = _livro(cliente)
    _escolher(cliente)
    cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/audio")
    arquivo = caminho_absoluto(sessao_com_tabelas.scalars(select(AudioDeCapitulo.arquivo)).one())
    assert arquivo.is_file()

    apagar_livro_de_vez(sessao_com_tabelas, sessao_com_tabelas.get(Livro, livro["id"]))
    sessao_com_tabelas.commit()

    assert not arquivo.exists()
    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_parametros_da_narracao_sem_modelo_ficam_nulos_e_a_voz_vazia_e_a_padrao() -> None:
    from imagineer.modelos import Configuracao

    assert narracao.parametros_da_narracao(Configuracao()) == (None, "")
    assert narracao.parametros_da_narracao(Configuracao(modelo_narracao=" a/b ", narracao_voz=" v ")) == ("a/b", "v")
