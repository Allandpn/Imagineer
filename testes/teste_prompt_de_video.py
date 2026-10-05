"""O prompt de vídeo (item 4.8, VD1 a VD8): imagem de partida, separação do prompt de imagem e o que a IA recebe."""

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import openrouter
from imagineer.ia.blocos_tecnicos import BLOCO_TECNICO_POR_CATEGORIA
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.modelos import CategoriaEstilo, Prompt, TipoDePrompt
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _frame, _importar_imagem, _montar_frame_completo

VIDEO = {"tipo": "VIDEO"}


def _cena(cliente: TestClient, usar_provedor_falso, **kwargs):
    provedor = ProvedorFalso(prompt="a pintura da cena", **kwargs)
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    return provedor, livro, frame


def _prompt_de_imagem_com_imagem(cliente: TestClient, frame_id: int) -> tuple[dict, dict]:
    prompt = cliente.post(f"/frames/{frame_id}/prompts", json={}).json()
    return prompt, _importar_imagem(cliente, prompt["id"])


# --------------------------------------------------------------------------- #
# Os dois modos
# --------------------------------------------------------------------------- #


def teste_sem_nenhuma_imagem_e_o_modo_texto_para_video(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, frame = _cena(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO)

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["tipo"] == "VIDEO" and corpo["imagem_partida_id"] is None
    assert corpo["texto"] == "slow push-in, the subject breathes slowly. No on-screen text."
    assert provedor.chamadas_de_video[0]["prompt_da_imagem"] is None
    assert provedor.chamadas_de_prompt == []  # não passou pela montagem do prompt de imagem


def teste_com_imagem_a_partida_e_a_canonica_e_a_ia_recebe_o_prompt_que_a_gerou(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, frame = _cena(cliente, usar_provedor_falso)
    prompt, imagem = _prompt_de_imagem_com_imagem(cliente, frame["id"])
    cliente.put(f"/frames/{frame['id']}/imagem-canonica", json={"imagem_id": imagem["id"]})

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()

    assert corpo["imagem_partida_id"] == imagem["id"]
    assert provedor.chamadas_de_video[0]["prompt_da_imagem"] == prompt["texto"]


def teste_sem_canonica_vale_a_imagem_mais_recente(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    _importar_imagem(cliente, prompt["id"], "a.png")
    ultima = _importar_imagem(cliente, prompt["id"], "b.png")

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()

    assert corpo["imagem_partida_id"] == ultima["id"]


def teste_a_pessoa_escolhe_a_imagem_de_partida(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    primeira = _importar_imagem(cliente, prompt["id"], "a.png")
    _importar_imagem(cliente, prompt["id"], "b.png")

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO | {"imagem_partida_id": primeira["id"]}).json()

    assert corpo["imagem_partida_id"] == primeira["id"]


def teste_retrato_vira_retrato_vivo_e_cena_nao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, livro, cena = _cena(cliente, usar_provedor_falso)
    retrato = _frame(cliente, cena["capitulo_id"], [e["estado_id"] for e in cena["elementos"]], tipo="PERSONAGEM")

    cliente.post(f"/frames/{cena['id']}/prompts", json=VIDEO)
    cliente.post(f"/frames/{retrato['id']}/prompts", json=VIDEO)

    assert [c["eh_retrato"] for c in provedor.chamadas_de_video] == [False, True]


# --------------------------------------------------------------------------- #
# O bloco técnico (VD5)
# --------------------------------------------------------------------------- #


def teste_o_bloco_tecnico_so_entra_sem_imagem_de_partida(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, livro, frame = _cena(cliente, usar_provedor_falso)
    perfil_id = cliente.get(f"/livros/{livro['id']}").json()["perfil_renderizacao_padrao_id"]
    cliente.patch(f"/perfis-renderizacao/{perfil_id}", json={"categoria_estilo": "PINTURA_A_OLEO"})
    bloco = BLOCO_TECNICO_POR_CATEGORIA[CategoriaEstilo.PINTURA_A_OLEO]

    sem = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()
    _prompt_de_imagem_com_imagem(cliente, frame["id"])
    com = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()

    assert sem["texto"].endswith(bloco)  # sem imagem, o texto carrega o estilo
    assert bloco not in com["texto"]  # com imagem, quem carrega o estilo é a imagem


# --------------------------------------------------------------------------- #
# A imagem de partida é conferida antes de gastar IA (VD8)
# --------------------------------------------------------------------------- #


def teste_imagem_de_outro_frame_da_422_e_nao_gasta_ia(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, frame = _cena(cliente, usar_provedor_falso)
    outro = _frame(cliente, frame["capitulo_id"], [e["estado_id"] for e in frame["elementos"]], tipo="CENA")
    prompt_do_outro = cliente.post(f"/frames/{outro['id']}/prompts", json={}).json()
    imagem_do_outro = _importar_imagem(cliente, prompt_do_outro["id"])

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO | {"imagem_partida_id": imagem_do_outro["id"]})

    assert resposta.status_code == 422 and "imagem deste frame" in resposta.json()["detail"]
    assert provedor.chamadas_de_video == []


def teste_imagem_na_lixeira_ou_inexistente_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    _, imagem = _prompt_de_imagem_com_imagem(cliente, frame["id"])
    cliente.delete(f"/imagens/{imagem['id']}")

    assert cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO | {"imagem_partida_id": imagem["id"]}).status_code == 422
    assert cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO | {"imagem_partida_id": 99999}).status_code == 422


def teste_imagem_de_partida_num_prompt_de_imagem_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    _, imagem = _prompt_de_imagem_com_imagem(cliente, frame["id"])

    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={"imagem_partida_id": imagem["id"]})

    assert resposta.status_code == 422 and "prompt de vídeo" in resposta.json()["detail"]


def teste_apagar_a_imagem_de_vez_deixa_o_prompt_de_video_sem_partida(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    _, imagem = _prompt_de_imagem_com_imagem(cliente, frame["id"])
    video = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()
    cliente.delete(f"/imagens/{imagem['id']}")
    assert cliente.delete(f"/lixeira/imagens/{imagem['id']}").status_code == 204  # apaga de vez

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Prompt, video["id"]).imagem_partida_id is None  # SET NULL: o prompt de vídeo continua


# --------------------------------------------------------------------------- #
# O vídeo não se mistura com a imagem (VD7)
# --------------------------------------------------------------------------- #


def teste_a_listagem_so_traz_os_de_imagem_a_menos_que_se_peca_video(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    de_imagem = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    de_video = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()

    padrao = cliente.get(f"/frames/{frame['id']}/prompts").json()
    videos = cliente.get(f"/frames/{frame['id']}/prompts", params={"tipo": "VIDEO"}).json()

    assert [p["id"] for p in padrao] == [de_imagem["id"]] and padrao[0]["tipo"] == "IMAGEM"
    assert [p["id"] for p in videos] == [de_video["id"]] and videos[0]["tipo"] == "VIDEO"


def teste_imagem_importada_no_frame_vai_para_o_prompt_de_imagem_e_nao_para_o_de_video(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    de_imagem = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO)  # o mais recente é o de vídeo

    resposta = cliente.post(f"/frames/{frame['id']}/imagens", files={"arquivo": ("x.png", b"conteudo-fake-da-imagem", "image/png")})

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["prompt_id"] == de_imagem["id"]


def teste_so_com_prompt_de_video_o_artefato_nao_vira_prompt_pronto(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)

    def situacao() -> str:
        artefatos = cliente.get(f"/capitulos/{frame['capitulo_id']}/artefatos").json()["artefatos"]
        return next(a["situacao"] for a in artefatos if a["frame_id"] == frame["id"])

    cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO)
    assert situacao() == "CONFIRMADO"

    cliente.post(f"/frames/{frame['id']}/prompts", json={})
    assert situacao() == "PROMPT_PRONTO"


def teste_gerar_imagem_de_um_prompt_de_video_e_recusado(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, frame = _cena(cliente, usar_provedor_falso)
    video = cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO).json()

    resposta = cliente.post(f"/prompts/{video['id']}/gerar-imagem", json={})

    assert resposta.status_code == 422 and "prompt de vídeo" in resposta.json()["detail"]


def teste_o_prompt_de_imagem_de_sempre_nao_muda(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, frame = _cena(cliente, usar_provedor_falso)

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    assert corpo["tipo"] == "IMAGEM" and corpo["imagem_partida_id"] is None
    assert provedor.chamadas_de_video == []


# --------------------------------------------------------------------------- #
# A migração e a IA
# --------------------------------------------------------------------------- #


def teste_a_migracao_encadeia_e_cria_as_duas_colunas() -> None:
    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "b8c9d0e1f2a3_prompt_de_video.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'" in texto
    assert '"tipo"' in texto and '"imagem_partida_id"' in texto and 'server_default="IMAGEM"' in texto
    assert TipoDePrompt.IMAGEM.value == "IMAGEM"


def teste_a_instrucao_do_video_tem_as_regras_do_guia() -> None:
    instrucao = " ".join(openrouter._INSTRUCAO_DE_PROMPT_DE_VIDEO.replace("\\\n", "").split())

    assert "UMA ação contínua" in instrucao and "UM movimento só" in instrucao
    assert "No on-screen text, no subtitles, no scene cuts, no additional people." in instrucao
    assert "Poeira, névoa, fumaça e partículas no ar NÃO se acrescentam" in instrucao  # FD10
    assert "PROIBIDO fala" in instrucao and "Música NÃO" in instrucao
    assert "retrato" in instrucao.lower() and "CONTEMPLAÇÃO" in instrucao


def _provedor_que_guarda_o_pedido():
    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "  a video prompt  "}}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave-de-teste", cliente=cliente), pedidos


def teste_o_pedido_a_ia_leva_a_imagem_de_partida_ou_diz_que_nao_ha() -> None:
    provedor, pedidos = _provedor_que_guarda_o_pedido()

    com = provedor.montar_prompt_de_video("cena", ["Ned: x"], "estilo", "m/x", prompt_da_imagem="o prompt da imagem", trecho_do_livro="Ned ergueu a espada.")
    sem = provedor.montar_prompt_de_video("", ["Ned: x"], "estilo", "m/x", eh_retrato=True)

    assert com.texto == "a video prompt"  # sem os espaços das pontas
    pedido_com, pedido_sem = (p["messages"][1]["content"] for p in pedidos)
    assert "IMAGEM DE PARTIDA (o texto do prompt que gerou a imagem usada como primeiro quadro" in pedido_com and "o prompt da imagem" in pedido_com
    assert "TRECHO DO LIVRO" in pedido_com and "Ned ergueu a espada." in pedido_com
    assert "IMAGEM DE PARTIDA: (nenhuma" in pedido_sem
    assert "RETRATO (retrato vivo" in pedido_sem and "TIPO DO FRAME: CENA" in pedido_com
    assert pedidos[0]["temperature"] == 0.4


def teste_os_gastos_do_video_aparecem_como_operacao_propria(cliente: TestClient) -> None:
    # A tela de Custos agrupa por operação: "prompt_de_video" é o nome que o provedor informa (o app lhe dá um rótulo).
    assert 'operacao="prompt_de_video"' in Path(openrouter.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# O modelo do prompt de vídeo (VD11)
# --------------------------------------------------------------------------- #


def teste_sem_modelo_de_video_vale_o_do_prompt_de_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, frame = _cena(cliente, usar_provedor_falso)

    cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO)

    assert provedor.chamadas_de_video[0]["modelo"] == cliente.get("/configuracao").json()["modelo_prompt"]
    assert cliente.get("/configuracao").json()["modelo_video"] is None


def teste_o_modelo_de_video_vale_so_para_o_video_e_o_pedido_pode_sobrepor(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, frame = _cena(cliente, usar_provedor_falso)
    modelo_de_imagem = cliente.get("/configuracao").json()["modelo_prompt"]
    assert cliente.put("/configuracao", json={"modelo_video": "anthropic/claude-sonnet-5.5"}).json()["modelo_video"] == "anthropic/claude-sonnet-5.5"

    cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})  # o de imagem continua com o dele
    cliente.post(f"/frames/{frame['id']}/prompts", json=VIDEO | {"modelo": "outro/modelo"})

    assert [c["modelo"] for c in provedor.chamadas_de_video] == ["anthropic/claude-sonnet-5.5", "outro/modelo"]
    assert provedor.chamadas_de_prompt[0]["modelo"] == modelo_de_imagem


def teste_limpar_o_modelo_de_video_volta_ao_padrao(cliente: TestClient) -> None:
    cliente.put("/configuracao", json={"modelo_video": "x/y"})

    assert cliente.put("/configuracao", json={"modelo_video": ""}).json()["modelo_video"] is None


def teste_a_instrucao_manda_o_estilo_do_perfil_e_nao_o_da_imagem() -> None:
    instrucao = " ".join(openrouter._INSTRUCAO_DE_PROMPT_DE_VIDEO.replace("\\n", "").split())

    assert "NUNCA do texto da imagem de partida" in instrucao and "vale o ESTILO VISUAL" in instrucao


def teste_a_migracao_do_modelo_de_video_encadeia() -> None:
    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "c9d0e1f2a3b4_modelo_do_prompt_de_video.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'" in texto and '"modelo_video"' in texto
