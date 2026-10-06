"""A narração por voz de IA (itens NA1 a NA10): dividir o capítulo, falar, guardar, estimar, registrar o gasto e servir o arquivo.

Nenhum teste fala com a OpenAI: o narrador é um falso (``NarradorFalso``) ou a OpenAI é um transporte falso do ``httpx``.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.configuracao import obter_configuracoes
from imagineer.ia.narradores import (
    CARACTERES_POR_MINUTO,
    LIMITE_DO_TRECHO,
    NarradorFalso,
    NarradorOpenAI,
    dividir_em_trechos,
)
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA
from imagineer.modelos import AudioDeCapitulo, Capitulo, Livro, SituacaoDoAudio, UsoDeIA
from imagineer.servicos import narracao
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _livro


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
# NA1 e NA3: a OpenAI
# --------------------------------------------------------------------------- #


def _openai(resposta: httpx.Response, pedidos: list | None = None) -> NarradorOpenAI:
    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedidos is not None:
            pedidos.append((pedido.url, dict(pedido.headers), json.loads(pedido.content)))
        return resposta

    return NarradorOpenAI("sk-teste", cliente=httpx.Client(transport=httpx.MockTransport(responder)))


def teste_a_openai_recebe_modelo_voz_instrucao_e_mp3() -> None:
    pedidos: list = []
    narrador = _openai(httpx.Response(200, content=b"MP3"), pedidos)

    assert narrador.narrar("Era uma vez.", "nova", "voz grave e calma") == b"MP3"

    (url, cabecalhos, corpo), = pedidos
    assert str(url) == "https://api.openai.com/v1/audio/speech"
    assert cabecalhos["authorization"] == "Bearer sk-teste"
    assert corpo == {"model": "gpt-4o-mini-tts", "input": "Era uma vez.", "voice": "nova", "response_format": "mp3", "instructions": "voz grave e calma"}


def teste_sem_voz_usa_a_padrao_e_sem_instrucao_nao_manda_o_campo() -> None:
    pedidos: list = []
    _openai(httpx.Response(200, content=b"MP3"), pedidos).narrar("Texto.", None, None)
    corpo = pedidos[0][2]
    assert corpo["voice"] == NarradorOpenAI.VOZ_PADRAO
    assert "instructions" not in corpo


def teste_chave_recusada_vira_chave_ausente_e_falhas_viram_erro_em_portugues() -> None:
    with pytest.raises(ChaveDeApiAusente, match="recusou a chave"):
        _openai(httpx.Response(401, text="no")).narrar("x", None, None)
    with pytest.raises(ErroDoProvedorIA, match="429"):
        _openai(httpx.Response(429, text="slow down")).narrar("x", None, None)
    with pytest.raises(ErroDoProvedorIA, match="500"):
        _openai(httpx.Response(500, text="boom")).narrar("x", None, None)
    with pytest.raises(ErroDoProvedorIA, match="vazio"):
        _openai(httpx.Response(200, content=b"")).narrar("x", None, None)


def teste_sem_chave_o_narrador_nao_esta_disponivel_e_nao_fala() -> None:
    narrador = NarradorOpenAI("")
    assert narrador.disponivel is False
    with pytest.raises(ChaveDeApiAusente, match="OPENAI_API_KEY"):
        narrador.narrar("x", None, None)


def teste_o_custo_estimado_e_proporcional_aos_minutos() -> None:
    narrador = NarradorOpenAI("k")
    assert narrador.custo_estimado(CARACTERES_POR_MINUTO) == Decimal("0.015")
    assert narrador.custo_estimado(CARACTERES_POR_MINUTO * 10) == Decimal("0.15")


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
    """Três parágrafos de 3.000 caracteres: nenhum par cabe junto no limite de 3.500, então são três trechos."""
    return "\n".join(f"{letra}" * 3000 for letra in "ABC")


def teste_estimativa_nao_precisa_de_chave_e_diz_caracteres_minutos_e_custo(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso(disponivel=False))
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "x" * 1800)

    resposta = cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["caracteres"] == 1800 and corpo["minutos"] == 2.0
    assert Decimal(corpo["custo_estimado"]) == Decimal("0.0018")
    assert corpo["modelo"] == "gpt-4o-mini-tts" and corpo["voz"] is None and corpo["ja_gerado"] is False


def teste_gerar_sem_chave_da_openai_responde_422_e_nao_cria_nada(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso(disponivel=False))
    capitulo_id = _capitulo(cliente, sessao_com_tabelas)

    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert resposta.status_code == 422 and "OPENAI_API_KEY" in resposta.json()["detail"]
    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_gerar_capitulo_sem_texto_responde_422(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "   \n ")

    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code == 422


def teste_gerar_conta_a_voz_e_o_tom_da_configuracao_e_deixa_o_audio_pronto(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    narrador = usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())
    cliente.put("/configuracao", json={"narracao_voz": "nova", "narracao_instrucoes": "voz grave e calma"})

    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert resposta.status_code == 202
    assert resposta.json()["situacao"] == "GERANDO"  # o que a rota respondeu na hora; o resto roda em segundo plano
    assert [(len(t), v, i) for t, v, i in narrador.pedidos] == [(3000, "nova", "voz grave e calma")] * 3

    estado = cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()
    assert estado["situacao"] == "PRONTO" and estado["voz"] == "nova" and estado["erro"] is None
    assert estado["caracteres"] == 9002 and estado["tamanho_em_bytes"] == len(b"MP3[1]MP3[2]MP3[3]")
    assert Decimal(estado["custo"]) == Decimal(9000) / 1_000_000


def teste_o_arquivo_e_a_juncao_dos_trechos_em_ordem_e_aceita_range(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())
    cliente.post(f"/capitulos/{capitulo_id}/audio")

    inteiro = cliente.get(f"/capitulos/{capitulo_id}/audio")
    assert inteiro.status_code == 200 and inteiro.headers["content-type"] == "audio/mpeg"
    assert inteiro.content == b"MP3[1]MP3[2]MP3[3]"
    assert inteiro.headers["cache-control"] == "no-cache"

    pedaco = cliente.get(f"/capitulos/{capitulo_id}/audio", headers={"Range": "bytes=6-11"})
    assert pedaco.status_code == 206 and pedaco.content == b"MP3[2]"


def teste_cada_trecho_concluido_e_registrado_como_gasto_estimado_do_livro(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso())
    livro = _livro(cliente)
    capitulo_id = livro["capitulos"][0]["id"]
    sessao_com_tabelas.get(Capitulo, capitulo_id).texto = _tres_trechos()
    sessao_com_tabelas.commit()

    cliente.post(f"/capitulos/{capitulo_id}/audio")

    usos = sessao_com_tabelas.scalars(select(UsoDeIA).where(UsoDeIA.operacao == "narracao")).all()
    assert len(usos) == 3
    assert {(u.provedor, u.modelo, u.estimado, u.livro_id) for u in usos} == {("openai", "gpt-4o-mini-tts", True, livro["id"])}
    assert [u.custo for u in usos] == [Decimal("0.003")] * 3


def teste_falha_no_meio_marca_falhou_sem_arquivo_e_registra_o_que_ja_foi_gasto(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso(falhar_no_trecho=2))
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())

    cliente.post(f"/capitulos/{capitulo_id}/audio")

    estado = cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()
    assert estado["situacao"] == "FALHOU" and "falha de teste" in estado["erro"]
    assert estado["tamanho_em_bytes"] is None
    assert Decimal(estado["custo"]) == Decimal("0.003")  # o primeiro trecho foi cobrado
    assert len(sessao_com_tabelas.scalars(select(UsoDeIA)).all()) == 1
    assert not any(caminho_absoluto("audios").rglob("*.mp3"))  # nunca há arquivo parcial (NA7)
    assert cliente.get(f"/capitulos/{capitulo_id}/audio").status_code == 404


def teste_ja_pronto_devolve_200_sem_gastar_e_refazer_gera_de_novo_e_substitui_o_antigo(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    narrador = usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    primeiro = cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert primeiro.status_code == 202 and len(narrador.pedidos) == 1
    arquivo_antigo = caminho_absoluto(sessao_com_tabelas.scalars(select(AudioDeCapitulo.arquivo)).one())
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estimativa").json()["ja_gerado"] is True

    de_novo = cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert de_novo.status_code == 200 and de_novo.json()["situacao"] == "PRONTO"
    assert len(narrador.pedidos) == 1  # nenhuma chamada nova, nenhum gasto

    refeito = cliente.post(f"/capitulos/{capitulo_id}/audio", json={"refazer": True})
    assert refeito.status_code == 202 and len(narrador.pedidos) == 2
    linhas = sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all()
    assert len(linhas) == 1 and linhas[0].situacao == SituacaoDoAudio.PRONTO  # o antigo saiu
    assert not arquivo_antigo.exists() and caminho_absoluto(linhas[0].arquivo).is_file()


def teste_ja_gerando_responde_409(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    narrador = usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas)
    sessao_com_tabelas.add(AudioDeCapitulo(capitulo_id=capitulo_id, modelo="gpt-4o-mini-tts", situacao=SituacaoDoAudio.GERANDO))
    sessao_com_tabelas.commit()

    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert resposta.status_code == 409 and narrador.pedidos == []


def teste_gerando_preso_ha_mais_de_30_minutos_vale_como_falhou_e_libera_uma_nova_geracao(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    preso = AudioDeCapitulo(
        capitulo_id=capitulo_id, modelo="gpt-4o-mini-tts", situacao=SituacaoDoAudio.GERANDO,
        criado_em=datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    sessao_com_tabelas.add(preso)
    sessao_com_tabelas.commit()

    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "FALHOU"
    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code == 202
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "PRONTO"


def teste_trocar_a_voz_ou_o_tom_gera_outro_audio_e_o_antigo_nao_conta(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    cliente.post(f"/capitulos/{capitulo_id}/audio")
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "PRONTO"

    cliente.put("/configuracao", json={"narracao_voz": "onyx"})
    assert cliente.get(f"/capitulos/{capitulo_id}/audio/estado").json()["situacao"] == "NAO_GERADO"
    assert cliente.get(f"/capitulos/{capitulo_id}/audio").status_code == 404

    assert cliente.post(f"/capitulos/{capitulo_id}/audio").status_code == 202
    assert len(sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all()) == 2  # os dois ficam (NA4)


def teste_apagar_remove_as_linhas_e_os_arquivos(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    usar_narrador_falso(NarradorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto curto.")
    cliente.post(f"/capitulos/{capitulo_id}/audio")
    arquivo = caminho_absoluto(sessao_com_tabelas.scalars(select(AudioDeCapitulo.arquivo)).one())
    assert arquivo.is_file()

    assert cliente.delete(f"/capitulos/{capitulo_id}/audio").status_code == 204

    assert not arquivo.exists()
    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_apagar_o_livro_de_vez_leva_os_arquivos_de_narracao(cliente: TestClient, sessao_com_tabelas, usar_narrador_falso) -> None:
    from imagineer.servicos.lixeira import apagar_livro_de_vez

    usar_narrador_falso(NarradorFalso())
    livro = _livro(cliente)
    cliente.post(f"/capitulos/{livro['capitulos'][0]['id']}/audio")
    arquivo = caminho_absoluto(sessao_com_tabelas.scalars(select(AudioDeCapitulo.arquivo)).one())
    assert arquivo.is_file()

    apagar_livro_de_vez(sessao_com_tabelas, sessao_com_tabelas.get(Livro, livro["id"]))
    sessao_com_tabelas.commit()

    assert not arquivo.exists()
    assert sessao_com_tabelas.scalars(select(AudioDeCapitulo)).all() == []


def teste_hash_das_instrucoes_ignora_espacos_nas_pontas_e_e_vazio_sem_instrucao() -> None:
    assert narracao.hash_das_instrucoes(None) == "" and narracao.hash_das_instrucoes("   ") == ""
    assert narracao.hash_das_instrucoes(" suspense ") == narracao.hash_das_instrucoes("suspense")
    assert narracao.hash_das_instrucoes("suspense") != narracao.hash_das_instrucoes("calma")


def teste_a_configuracao_diz_se_o_servidor_pode_narrar_com_ia(cliente: TestClient, monkeypatch) -> None:
    assert cliente.get("/configuracao").json()["narracao_ia_disponivel"] is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    obter_configuracoes.cache_clear()
    try:
        assert cliente.get("/configuracao").json()["narracao_ia_disponivel"] is True
    finally:
        monkeypatch.delenv("OPENAI_API_KEY")
        obter_configuracoes.cache_clear()
