"""A conferência da imagem gerada (item 4.9, FL13.1; etapa 7).

Um modelo **com visão** compara a imagem com a lista do que deveria aparecer (a que valeu para o prompt) e devolve as divergências: gente a mais ou a menos, uma
roupa errada, a luz que não bate. Gasta IA e não grava nada. Nenhum teste fala com o OpenRouter.
"""

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from imagineer.ia import catalogo_de_texto
from imagineer.ia.catalogo_de_texto import capacidades_de
from imagineer.ia.esquemas_json import ESQUEMAS
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, _interpretar_conferencia
from imagineer.ia.provedor import ErroDoProvedorIA, ImagemConferida
from imagineer.ia.tarefas import PERFIS
from imagineer.modelos import Imagem, Prompt
from imagineer.servicos.uso_de_ia import gravar_uso

from testes.teste_fl_referencias import DOSSIE, _cena_com_ancoras
from testes.teste_rotas_prompts import _imagem_importada

MODELO_COM_VISAO = "google/gemini-2.5-flash"
PNG = b"\x89PNG\r\n\x1a\nxx"

LISTA = {
    "presentes": [
        {"nome": "Auri", "tipo": "PESSOA", "elemento": "Auri", "caracteristicas": "descalça", "incerto": False, "incluir": True},
        {"nome": "o prato", "tipo": "OBJETO", "elemento": "Prato", "caracteristicas": "de barro", "incerto": False, "incluir": True},
    ],
    "onde": "uma sala de pedra", "luz_e_clima": "uma vela", "acao": "Auri serve o prato",
}


# --------------------------------------------------------------------------- #
# O catálogo: o modelo lê imagem?
# --------------------------------------------------------------------------- #


def teste_fl13_o_catalogo_diz_se_o_modelo_le_imagens() -> None:
    com_visao = capacidades_de({"id": "a/b", "architecture": {"input_modalities": ["text", "image"]}})
    so_texto = capacidades_de({"id": "a/c", "architecture": {"input_modalities": ["text"]}})

    assert com_visao.aceita_imagem is True and so_texto.aceita_imagem is False


def teste_fl13_catalogo_que_nao_diz_nao_bloqueia() -> None:
    assert capacidades_de({"id": "a/b"}).aceita_imagem is True
    assert capacidades_de({"id": "a/b", "architecture": {}}).aceita_imagem is True
    assert capacidades_de({"id": "a/b", "architecture": {"input_modalities": []}}).aceita_imagem is True
    assert capacidades_de({"id": "a/b", "architecture": "lixo"}).aceita_imagem is True


# --------------------------------------------------------------------------- #
# A configuração
# --------------------------------------------------------------------------- #


def teste_fl13_a_configuracao_nasce_sem_modelo_de_conferencia(cliente: TestClient) -> None:
    assert cliente.get("/configuracao").json()["modelo_conferencia"] is None


def teste_fl13_o_put_grava_apaga_e_normaliza_o_modelo_de_conferencia(cliente: TestClient) -> None:
    assert cliente.put("/configuracao", json={"modelo_conferencia": "  google/gemini-2.5-flash "}).json()["modelo_conferencia"] == "google/gemini-2.5-flash"
    assert cliente.put("/configuracao", json={"modelo_prompt": "x/y"}).json()["modelo_conferencia"] == "google/gemini-2.5-flash"  # outro campo não apaga
    assert cliente.put("/configuracao", json={"modelo_conferencia": ""}).json()["modelo_conferencia"] is None
    assert cliente.put("/configuracao", json={"modelo_conferencia": "x" * 201}).status_code == 422


def teste_fl13_o_preset_nao_mexe_no_modelo_de_conferencia(cliente: TestClient, monkeypatch) -> None:
    entrada = {"id": "google/gemini-2.5-flash-lite", "context_length": 1000, "pricing": {"prompt": "0.1"}, "supported_parameters": []}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [entrada]})
    cliente.put("/configuracao", json={"modelo_conferencia": MODELO_COM_VISAO})

    depois = cliente.put("/configuracao/preset", json={"nivel": "ECONOMICO"}).json()

    assert depois["modelo_conferencia"] == MODELO_COM_VISAO


# --------------------------------------------------------------------------- #
# O provedor
# --------------------------------------------------------------------------- #


def _provedor(conteudo: str, corpos: list[dict] | None = None, ao_usar=None) -> ProvedorOpenRouter:
    def responder(pedido: httpx.Request) -> httpx.Response:
        if corpos is not None:
            corpos.append(json.loads(pedido.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": conteudo}, "finish_reason": "stop"}], "usage": {"cost": 0.0123}, "id": "gen-1"},
        )

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="c", cliente=cliente, ao_usar=ao_usar)


def teste_fl13_o_pedido_leva_o_texto_da_lista_e_a_imagem_em_base64() -> None:
    corpos: list[dict] = []

    _provedor(json.dumps({"conforme": True, "divergencias": []}), corpos).conferir_imagem(PNG, "image/png", "A espera", LISTA, MODELO_COM_VISAO)

    sistema, usuario = corpos[0]["messages"]
    assert "Você confere uma imagem gerada por IA" in sistema["content"]
    texto, imagem = usuario["content"]
    assert texto["type"] == "text" and texto["text"].startswith("CENA: A espera\n\nO QUE APARECE NA CENA")
    assert "1. Auri [pessoa]" in texto["text"] and "Pessoas e criaturas no quadro: 1" in texto["text"] and "LUGAR: uma sala de pedra" in texto["text"]
    assert imagem == {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")}}


def teste_fl13_a_instrucao_so_aponta_o_que_se_ve_e_nao_julga_estilo() -> None:
    corpos: list[dict] = []
    _provedor(json.dumps({"conforme": True, "divergencias": []}), corpos).conferir_imagem(PNG, "image/png", "A espera", LISTA, MODELO_COM_VISAO)

    instrucao = corpos[0]["messages"][0]["content"]

    assert "CONTE as pessoas e criaturas" in instrucao
    assert "atributos misturados entre as figuras" in instrucao
    assert "Não julgue estilo, qualidade nem beleza" in instrucao
    assert "Se você não tem certeza do que vê, não aponte" in instrucao
    assert '"conforme" só é verdadeiro se "divergencias" está vazia' in instrucao


def teste_fl13_devolve_as_divergencias_e_diz_se_confere() -> None:
    conferida = _provedor(json.dumps({"conforme": False, "divergencias": ["Deveria: uma pessoa / A imagem mostra: duas"]})).conferir_imagem(
        PNG, "image/png", "A espera", LISTA, MODELO_COM_VISAO
    )
    limpa = _provedor(json.dumps({"conforme": True, "divergencias": []})).conferir_imagem(PNG, "image/png", "A espera", LISTA, MODELO_COM_VISAO)

    assert conferida.divergencias == ["Deveria: uma pessoa / A imagem mostra: duas"] and conferida.conforme is False and conferida.modelo == MODELO_COM_VISAO
    assert limpa.divergencias == [] and limpa.conforme is True


def teste_fl13_a_conferencia_usa_o_perfil_proprio_e_o_esquema_estrito(monkeypatch) -> None:
    modelo = {"id": MODELO_COM_VISAO, "context_length": 1000, "pricing": {"prompt": "1"}, "supported_parameters": ["structured_outputs", "max_tokens"]}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [modelo]})
    corpos: list[dict] = []

    _provedor(json.dumps({"conforme": True, "divergencias": []}), corpos).conferir_imagem(PNG, "image/png", "A espera", LISTA, MODELO_COM_VISAO)

    assert PERFIS["conferencia"].temperatura == 0.0 and PERFIS["conferencia"].esquema == "conferencia"
    assert corpos[0]["temperature"] == 0.0 and corpos[0]["response_format"]["json_schema"]["name"] == "conferencia"
    assert corpos[0]["response_format"]["json_schema"]["schema"] == ESQUEMAS["conferencia"]


def teste_fl13_o_esquema_da_conferencia_aceita_a_resposta_de_exemplo() -> None:
    esquema = ESQUEMAS["conferencia"]

    assert set(esquema["properties"]) == {"conforme", "divergencias"} and esquema["required"] == ["conforme", "divergencias"]
    assert esquema["additionalProperties"] is False and esquema["properties"]["divergencias"]["items"] == {"type": "string"}


def teste_fl13_item_que_nao_e_texto_ou_esta_vazio_e_descartado() -> None:
    resposta = json.dumps({"conforme": False, "divergencias": ["uma", 3, None, "  ", "null", "outra"]})

    assert _interpretar_conferencia(resposta) == ["uma", "outra"]


@pytest.mark.parametrize("resposta", ["Claro, a imagem está ótima.", json.dumps({"conforme": True}), json.dumps({"divergencias": "lixo"})])
def teste_fl13_resposta_fora_do_formato_e_erro_em_portugues(resposta: str) -> None:
    with pytest.raises(ErroDoProvedorIA, match="não devolveu a conferência no formato esperado"):
        _interpretar_conferencia(resposta)


def teste_fl13_sem_imagem_nao_ha_o_que_conferir() -> None:
    with pytest.raises(ErroDoProvedorIA, match="Não há imagem para conferir"):
        _provedor("{}").conferir_imagem(b"", "image/png", "A espera", LISTA, MODELO_COM_VISAO)


def teste_fl13_a_resposta_em_prosa_ganha_uma_segunda_tentativa() -> None:
    respostas = ["Parece tudo certo!", json.dumps({"conforme": True, "divergencias": []})]
    chamadas: list[int] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        chamadas.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": respostas.pop(0)}, "finish_reason": "stop"}]})

    provedor = ProvedorOpenRouter(chave_api="c", cliente=httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder)))

    assert provedor.conferir_imagem(PNG, "image/png", "A espera", LISTA, MODELO_COM_VISAO).conforme is True
    assert len(chamadas) == 2


def teste_fl13_imagem_conferida_sem_divergencias_confere() -> None:
    assert ImagemConferida().conforme is True and ImagemConferida(divergencias=["x"]).conforme is False


# --------------------------------------------------------------------------- #
# A rota
# --------------------------------------------------------------------------- #


def _imagem_da_cena(cliente: TestClient, usar_provedor_falso, divergencias=None, **mudancas):
    """Uma cena com prompt (e ficha com a lista) e uma imagem nele, com o modelo de conferência escolhido. Devolve (provedor, prompt, imagem, frame)."""
    provedor, prompt, _, frame = _cena_com_ancoras(cliente, usar_provedor_falso)
    provedor._divergencias = divergencias or []
    imagem = _imagem_importada(cliente, prompt["id"])
    cliente.put("/configuracao", json={"modelo_conferencia": MODELO_COM_VISAO})
    return provedor, prompt, imagem, frame


def teste_fl13_a_rota_confere_e_devolve_as_divergencias(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso, divergencias=["Deveria: 2 pessoas / A imagem mostra: 3"])

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["conforme"] is False and corpo["divergencias"] == ["Deveria: 2 pessoas / A imagem mostra: 3"]
    assert corpo["itens_conferidos"] == 4 and corpo["modelo"] == MODELO_COM_VISAO and corpo["custo"] is None


def teste_fl13_imagem_que_confere_volta_conforme_e_sem_divergencias(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/imagens/{imagem['id']}/conferir").json()

    assert corpo["conforme"] is True and corpo["divergencias"] == []


def teste_fl13_a_conferencia_leva_a_lista_do_prompt_e_o_lugar_a_luz_e_a_acao_do_dossie(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)

    cliente.post(f"/imagens/{imagem['id']}/conferir")

    (chamada,) = provedor.chamadas_de_conferencia
    assert chamada["titulo_da_cena"] == "O prato" and chamada["modelo"] == MODELO_COM_VISAO and chamada["tamanho_da_imagem"] > 0
    assert chamada["tipo_de_midia"].startswith("image/")
    assert [p["nome"] for p in chamada["dossie"]["presentes"]] == ["Auri", "Foxen", "o Manto", "o prato"]
    assert chamada["dossie"]["onde"] == DOSSIE["onde"] and chamada["dossie"]["acao"] == DOSSIE["acao"]


def teste_fl13_so_confere_o_que_a_pessoa_deixou_na_lista(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, _, frame = _imagem_da_cena(cliente, usar_provedor_falso)
    lista = cliente.get(f"/frames/{frame['id']}/dossie").json()["presentes"]
    for presente in lista:
        presente["incluir"] = presente["nome"] == "Auri"
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lista})
    novo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _imagem_importada(cliente, novo["id"])

    corpo = cliente.post(f"/imagens/{imagem['id']}/conferir").json()

    assert corpo["itens_conferidos"] == 1 and [p["nome"] for p in provedor.chamadas_de_conferencia[-1]["dossie"]["presentes"]] == ["Auri"]


def teste_fl13_nao_grava_nada(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, prompt, imagem, frame = _imagem_da_cena(cliente, usar_provedor_falso, divergencias=["x"])
    antes = (sessao_com_tabelas.query(Imagem).count(), sessao_com_tabelas.query(Prompt).count(), json.dumps(cliente.get(f"/frames/{frame['id']}/dossie").json()))

    cliente.post(f"/imagens/{imagem['id']}/conferir")

    sessao_com_tabelas.expire_all()
    depois = (sessao_com_tabelas.query(Imagem).count(), sessao_com_tabelas.query(Prompt).count(), json.dumps(cliente.get(f"/frames/{frame['id']}/dossie").json()))
    assert depois == antes and cliente.get(f"/prompts/{prompt['id']}").json()["texto"] == prompt["texto"]


def teste_fl13_sem_modelo_de_conferencia_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_conferencia": ""})

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 422 and "modelo de conferência" in resposta.json()["detail"] and "leia imagens" in resposta.json()["detail"]


def teste_fl13_modelo_de_texto_puro_da_422_antes_de_gastar(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    provedor, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    entrada = {"id": MODELO_COM_VISAO, "context_length": 1000, "pricing": {"prompt": "1"}, "architecture": {"input_modalities": ["text"]}}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [entrada]})

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 422 and "não lê imagens" in resposta.json()["detail"]
    assert provedor.chamadas_de_conferencia == []


def teste_fl13_modelo_que_le_imagem_no_catalogo_passa(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    _, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    entrada = {"id": MODELO_COM_VISAO, "context_length": 1000, "pricing": {"prompt": "1"}, "architecture": {"input_modalities": ["text", "image"]}}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [entrada]})

    assert cliente.post(f"/imagens/{imagem['id']}/conferir").status_code == 200


def teste_fl13_imagem_de_retrato_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, _, frame = _imagem_da_cena(cliente, usar_provedor_falso)
    retrato = cliente.post(f"/capitulos/{cliente.capitulo_id}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [cliente.estados_por_nome["Auri"]]}).json()
    prompt = cliente.post(f"/frames/{retrato['id']}/prompts", json={}).json()
    imagem = _imagem_importada(cliente, prompt["id"])

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 422 and "Só dá para conferir a imagem de uma cena" in resposta.json()["detail"]


def teste_fl13_prompt_sem_a_lista_da_cena_da_422_e_diz_como_resolver(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, prompt, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    sessao_com_tabelas.get(Prompt, prompt["id"]).ficha = {"dossie": None, "presentes": [], "momentos": [], "referencias": []}
    sessao_com_tabelas.commit()

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 422 and "não guardou a lista do que deveria aparecer" in resposta.json()["detail"] and "dossiê" in resposta.json()["detail"]


def teste_fl13_prompt_antigo_sem_ficha_da_422(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, prompt, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    sessao_com_tabelas.get(Prompt, prompt["id"]).ficha = None
    sessao_com_tabelas.commit()

    assert cliente.post(f"/imagens/{imagem['id']}/conferir").status_code == 422


def teste_fl13_imagem_que_nao_existe_da_404(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())

    assert cliente.post("/imagens/999/conferir").status_code == 404


def teste_fl13_imagem_na_lixeira_da_404(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    sessao_com_tabelas.get(Imagem, imagem["id"]).apagada_em = datetime.now(timezone.utc)
    sessao_com_tabelas.commit()

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 404 and "lixeira" in resposta.json()["detail"]


def teste_fl13_arquivo_que_sumiu_do_disco_da_422(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    provedor, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    sessao_com_tabelas.get(Imagem, imagem["id"]).caminho_arquivo = "nao/existe.png"
    sessao_com_tabelas.commit()

    resposta = cliente.post(f"/imagens/{imagem['id']}/conferir")

    assert resposta.status_code == 422 and "não está mais no disco" in resposta.json()["detail"] and provedor.chamadas_de_conferencia == []


def teste_fl13_erro_do_provedor_vira_502(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    provedor._erro = ErroDoProvedorIA("o serviço caiu")

    assert cliente.post(f"/imagens/{imagem['id']}/conferir").status_code == 502


def teste_fl13_o_custo_da_conferencia_vem_do_consumo_informado_e_vai_para_o_livro(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """Pelo provedor de verdade (com transporte falso): o custo que o OpenRouter informou aparece na resposta e é gravado em ``usos_ia``."""
    _, _, imagem, _ = _imagem_da_cena(cliente, usar_provedor_falso)
    criador = sessionmaker(bind=sessao_com_tabelas.get_bind())
    provedor = _provedor(json.dumps({"conforme": False, "divergencias": ["Deveria: x / A imagem mostra: y"]}), ao_usar=partial(gravar_uso, criador=criador))
    usar_provedor_falso(provedor)

    corpo = cliente.post(f"/imagens/{imagem['id']}/conferir").json()

    assert corpo["custo"] == "0.0123" or Decimal(str(corpo["custo"])) == Decimal("0.0123")
    assert corpo["divergencias"] == ["Deveria: x / A imagem mostra: y"]
    from imagineer.modelos import UsoDeIA

    sessao_com_tabelas.expire_all()
    (uso,) = sessao_com_tabelas.query(UsoDeIA).filter(UsoDeIA.operacao == "conferencia").all()
    assert uso.modelo == MODELO_COM_VISAO and uso.livro_id is not None and uso.custo == Decimal("0.0123")


# --------------------------------------------------------------------------- #
# A migração
# --------------------------------------------------------------------------- #


def teste_fl13_a_migracao_adiciona_e_remove_a_coluna() -> None:
    import importlib.util

    import sqlalchemy as sa
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    from testes.teste_lm_migracao_do_uso import RAIZ

    arquivo = RAIZ / "migracoes" / "versions" / "c0d1e2f3a4b6_modelo_de_conferencia.py"
    especificacao = importlib.util.spec_from_file_location("migracao_c0d1e2f3a4b6", arquivo)
    migracao = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(migracao)
    motor = sa.create_engine("sqlite://")
    with motor.begin() as conexao:
        conexao.execute(sa.text("CREATE TABLE configuracao (id INTEGER PRIMARY KEY, modelo_extracao VARCHAR(200))"))
        conexao.execute(sa.text("INSERT INTO configuracao (id, modelo_extracao) VALUES (1, 'a/b')"))

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.aplicar()
    with motor.connect() as conexao:
        assert tuple(conexao.execute(sa.text("SELECT modelo_extracao, modelo_conferencia FROM configuracao")).one()) == ("a/b", None)
    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        migracao.reverter()
    assert {c["name"] for c in sa.inspect(motor).get_columns("configuracao")} == {"id", "modelo_extracao"}

    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)
    assert diretorio.get_revision("c0d1e2f3a4b6").down_revision == "b9c0d1e2f3a5" and len(diretorio.get_heads()) == 1
