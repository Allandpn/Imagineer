"""O vídeo no app (item 4.8, VD12 a VD20): esconder e editar o prompt de vídeo, importar o vídeo, escolher o que o texto mostra e servir o arquivo."""

from fastapi.testclient import TestClient

from imagineer.ia.falso import ProvedorFalso
from imagineer.servicos import catalogo_de_videos
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _importar_imagem, _montar_frame_completo

# Um MP4 de mentira: o que o servidor confere é só o começo ("ftyp" nos bytes 4 a 8).
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
WEBM = bytes([0x1A, 0x45, 0xDF, 0xA3]) + b"\x00" * 64


def _cena(cliente: TestClient, usar_provedor_falso):
    provedor = ProvedorFalso(prompt="a pintura da cena")
    return _montar_frame_completo(cliente, usar_provedor_falso, provedor)


def _prompt_de_video(cliente: TestClient, frame_id: int) -> dict:
    resposta = cliente.post(f"/frames/{frame_id}/prompts", json={"tipo": "VIDEO"})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _importar_video(cliente: TestClient, frame_id: int, conteudo: bytes = MP4, nome: str = "cena.mp4", **dados):
    return cliente.post(f"/frames/{frame_id}/videos", files={"arquivo": (nome, conteudo, "video/mp4")}, data=dados)


def _artefato_do_frame(cliente: TestClient, frame: dict) -> dict:
    artefatos = cliente.get(f"/capitulos/{frame['capitulo_id']}/artefatos").json()["artefatos"]
    return next(a for a in artefatos if a["frame_id"] == frame["id"])


# --------------------------------------------------------------------------- #
# VD12: esconder
# --------------------------------------------------------------------------- #


def teste_o_prompt_de_video_nasce_visivel_e_se_esconde_e_se_mostra(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _prompt_de_video(cliente, frame["id"])
    assert video["oculto"] is False

    escondido = cliente.patch(f"/prompts/{video['id']}", json={"oculto": True})
    assert escondido.status_code == 200 and escondido.json()["oculto"] is True
    # continua na listagem de vídeos (quem recolhe é o app) e não foi apagado
    lista = cliente.get(f"/frames/{frame['id']}/prompts", params={"tipo": "VIDEO"}).json()
    assert [(p["id"], p["oculto"]) for p in lista] == [(video["id"], True)]

    assert cliente.patch(f"/prompts/{video['id']}", json={"oculto": False}).json()["oculto"] is False


def teste_esconder_e_editar_o_texto_so_valem_no_prompt_de_video(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    de_imagem = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    for corpo in ({"oculto": True}, {"texto": "outro texto"}, {"texto_pt": "outro texto"}):
        resposta = cliente.patch(f"/prompts/{de_imagem['id']}", json=corpo)
        assert resposta.status_code == 422, corpo
    # a avaliação, que sempre valeu, continua valendo
    assert cliente.patch(f"/prompts/{de_imagem['id']}", json={"avaliacao": "boa"}).json()["avaliacao"] == "boa"


def teste_o_ajuste_sem_nenhum_campo_e_recusado(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _prompt_de_video(cliente, frame["id"])

    assert cliente.patch(f"/prompts/{video['id']}", json={}).status_code == 422


# --------------------------------------------------------------------------- #
# VD13: editar
# --------------------------------------------------------------------------- #


def teste_editar_o_texto_do_video_troca_o_texto_e_apaga_o_portugues_guardado(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _prompt_de_video(cliente, frame["id"])
    cliente.patch(f"/prompts/{video['id']}", json={"texto_pt": "empurrão lento"})

    editado = cliente.patch(f"/prompts/{video['id']}", json={"texto": "a slow pull-back"}).json()

    assert editado["texto"] == "a slow pull-back"
    assert editado["texto_pt"] is None  # o inglês mudou: o português guardado já não o descreve


def teste_editar_o_texto_com_o_portugues_guarda_os_dois(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _prompt_de_video(cliente, frame["id"])

    editado = cliente.patch(f"/prompts/{video['id']}", json={"texto": "a slow pull-back", "texto_pt": "um recuo lento"}).json()

    assert (editado["texto"], editado["texto_pt"]) == ("a slow pull-back", "um recuo lento")


def teste_o_texto_vazio_ou_enorme_e_recusado(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _prompt_de_video(cliente, frame["id"])

    assert cliente.patch(f"/prompts/{video['id']}", json={"texto": ""}).status_code == 422
    assert cliente.patch(f"/prompts/{video['id']}", json={"texto": "x" * 4001}).status_code == 422


def teste_o_portugues_do_prompt_de_video_traduz_e_guarda(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _prompt_de_video(cliente, frame["id"])

    primeira = cliente.post(f"/prompts/{video['id']}/traducao-pt")

    assert primeira.status_code == 200, primeira.text
    segunda = cliente.post(f"/prompts/{video['id']}/traducao-pt").json()
    assert segunda["reaproveitada"] is True  # traduz uma vez e guarda: já funciona para o vídeo (VD14)


# --------------------------------------------------------------------------- #
# VD16: importar e servir
# --------------------------------------------------------------------------- #


def teste_importar_um_video_grava_o_arquivo_e_lista(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)

    resposta = _importar_video(cliente, frame["id"])

    assert resposta.status_code == 201, resposta.text
    video = resposta.json()
    assert video["frame_id"] == frame["id"] and video["prompt_id"] is None
    assert video["tamanho_em_bytes"] == len(MP4) and video["nome_original"] == "cena.mp4" and video["no_texto"] is False
    arquivos = list((_diretorio_de_imagens / "videos").rglob("*.mp4"))
    assert len(arquivos) == 1 and arquivos[0].read_bytes() == MP4
    assert [v["id"] for v in cliente.get(f"/frames/{frame['id']}/videos").json()] == [video["id"]]


def teste_a_lista_vem_do_mais_novo_ao_mais_antigo(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    primeiro = _importar_video(cliente, frame["id"], nome="a.mp4").json()
    segundo = _importar_video(cliente, frame["id"], nome="b.webm", conteudo=WEBM).json()

    assert [v["id"] for v in cliente.get(f"/frames/{frame['id']}/videos").json()] == [segundo["id"], primeiro["id"]]


def teste_o_video_pode_dizer_de_qual_prompt_de_video_veio(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    prompt = _prompt_de_video(cliente, frame["id"])

    video = _importar_video(cliente, frame["id"], prompt_id=str(prompt["id"])).json()

    assert video["prompt_id"] == prompt["id"]
    # apagar o prompt de vídeo não apaga o vídeo: o vínculo só some
    cliente.delete(f"/prompts/{prompt['id']}")
    assert cliente.get(f"/frames/{frame['id']}/videos").json()[0]["prompt_id"] is None


def teste_o_prompt_de_origem_tem_de_ser_de_video_e_do_mesmo_frame(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    de_imagem = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    assert _importar_video(cliente, frame["id"], prompt_id=str(de_imagem["id"])).status_code == 422
    assert _importar_video(cliente, frame["id"], prompt_id="99999").status_code == 422


def teste_extensao_ou_conteudo_errados_sao_recusados_e_nao_deixam_arquivo(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)

    assert _importar_video(cliente, frame["id"], nome="cena.avi").status_code == 422  # extensão fora da lista
    assert _importar_video(cliente, frame["id"], nome="cena.mp4", conteudo=b"isto nao e um video de verdade").status_code == 422
    assert _importar_video(cliente, frame["id"], nome="cena.webm", conteudo=MP4).status_code == 422  # extensão de um, conteúdo de outro
    assert _importar_video(cliente, frame["id"], conteudo=b"").status_code == 422
    assert list((_diretorio_de_imagens / "videos").rglob("*.*")) == []
    assert cliente.get(f"/frames/{frame['id']}/videos").json() == []


def teste_acima_do_limite_da_413_e_apaga_o_parcial(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens, monkeypatch) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    monkeypatch.setattr(catalogo_de_videos, "TAMANHO_MAXIMO_DO_VIDEO", 32)

    resposta = _importar_video(cliente, frame["id"], conteudo=MP4)  # 76 bytes

    assert resposta.status_code == 413
    assert list((_diretorio_de_imagens / "videos").rglob("*.*")) == []


def teste_o_frame_inexistente_da_404(cliente: TestClient) -> None:
    assert _importar_video(cliente, 99999).status_code == 404
    assert cliente.get("/frames/99999/videos").status_code == 404


def teste_o_arquivo_sai_com_o_tipo_certo_e_aceita_pedaco(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()

    inteiro = cliente.get(f"/videos/{video['id']}/arquivo")
    assert inteiro.status_code == 200 and inteiro.content == MP4
    assert inteiro.headers["content-type"] == "video/mp4"
    assert "immutable" in inteiro.headers["cache-control"]

    pedaco = cliente.get(f"/videos/{video['id']}/arquivo", headers={"Range": "bytes=4-7"})
    assert pedaco.status_code == 206  # o que o player precisa para tocar em fluxo e pular no meio
    assert pedaco.content == b"ftyp"


def teste_video_sem_arquivo_no_disco_da_404_e_o_desconhecido_tambem(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    for arquivo in (_diretorio_de_imagens / "videos").rglob("*.mp4"):
        arquivo.unlink()

    assert cliente.get(f"/videos/{video['id']}/arquivo").status_code == 404
    assert cliente.get("/videos/99999/arquivo").status_code == 404


def teste_apagar_o_video_apaga_o_arquivo(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()

    assert cliente.delete(f"/videos/{video['id']}").status_code == 204

    assert list((_diretorio_de_imagens / "videos").rglob("*.mp4")) == []
    assert cliente.get(f"/frames/{frame['id']}/videos").json() == []
    assert cliente.delete(f"/videos/{video['id']}").status_code == 404


def teste_apagar_o_frame_de_vez_apaga_os_arquivos_de_video(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})
    assert cliente.delete(f"/frames/{frame['id']}").status_code == 204  # vai para a lixeira

    assert cliente.delete(f"/lixeira/frames/{frame['id']}").status_code == 204  # apaga de vez

    assert list((_diretorio_de_imagens / "videos").rglob("*.mp4")) == []


# --------------------------------------------------------------------------- #
# VD17: o que o texto mostra
# --------------------------------------------------------------------------- #


def teste_por_padrao_o_texto_mostra_a_imagem_e_o_artefato_nao_tem_video(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])
    _importar_video(cliente, frame["id"])

    artefato = _artefato_do_frame(cliente, frame)

    assert artefato["video_id"] is None and artefato["imagem_id"] == imagem["id"]


def teste_escolher_o_video_poe_o_video_no_artefato_e_voltar_a_imagem_tira(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])
    video = _importar_video(cliente, frame["id"]).json()

    escolhido = cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    assert escolhido.status_code == 200 and escolhido.json()["video_do_texto_id"] == video["id"]
    artefato = _artefato_do_frame(cliente, frame)
    assert artefato["video_id"] == video["id"]
    assert artefato["imagem_id"] == imagem["id"]  # a imagem continua lá: o app a usa de capa do vídeo
    assert cliente.get(f"/frames/{frame['id']}/videos").json()[0]["no_texto"] is True

    volta = cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": None}).json()
    assert volta["video_do_texto_id"] is None
    assert _artefato_do_frame(cliente, frame)["video_id"] is None


def teste_so_um_video_do_proprio_frame_pode_ir_para_o_texto(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)

    assert cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": 99999}).status_code == 422


def teste_o_video_ilustra_a_cena_mesmo_sem_nenhuma_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    assert _artefato_do_frame(cliente, frame)["situacao"] != "ILUSTRADO"

    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    artefato = _artefato_do_frame(cliente, frame)
    assert artefato["situacao"] == "ILUSTRADO" and artefato["video_id"] == video["id"] and artefato["imagem_id"] is None


def teste_apagar_o_video_do_texto_devolve_o_texto_a_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    cliente.delete(f"/videos/{video['id']}")

    assert _artefato_do_frame(cliente, frame)["video_id"] is None


def teste_ocultar_a_midia_do_capitulo_esconde_tambem_o_video(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    cliente.put(f"/frames/{frame['id']}/imagem-oculta", json={"oculta": True})

    assert _artefato_do_frame(cliente, frame)["video_id"] is None
    # escolher o vídeo de novo é querer vê-lo (como a canônica, OC3)
    escolhido = cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]}).json()
    assert escolhido["imagem_oculta"] is False
    assert _artefato_do_frame(cliente, frame)["video_id"] == video["id"]


def teste_mudar_o_video_do_texto_sobe_a_revisao_do_livro(cliente: TestClient, usar_provedor_falso) -> None:
    livro, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] > antes  # o capítulo mostra outra coisa: o app precisa reler
