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
    assert cliente.patch(f"/prompts/{video['id']}", json={"texto": "x" * 8001}).status_code == 422


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


def teste_acima_do_limite_da_413_e_apaga_o_parcial(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    assert cliente.put("/admin/limites", json={"tamanho_maximo_do_video_mb": 1}).status_code == 200  # CT15: o limite é do banco

    resposta = _importar_video(cliente, frame["id"], conteudo=MP4 + b"\x00" * (1024 * 1024))  # um pouco mais de 1 MB

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


def teste_escolher_o_video_tira_a_imagem_do_artefato_e_voltar_a_traz(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])
    video = _importar_video(cliente, frame["id"]).json()

    escolhido = cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    assert escolhido.status_code == 200 and escolhido.json()["video_do_texto_id"] == video["id"]
    artefato = _artefato_do_frame(cliente, frame)
    assert artefato["video_id"] == video["id"]
    assert artefato["imagem_id"] is None  # VD17: o vídeo ocupa o lugar da imagem no texto
    assert cliente.get(f"/frames/{frame['id']}/videos").json()[0]["no_texto"] is True
    # a imagem continua canônica e no catálogo: só o capítulo deixa de mostrá-la
    assert cliente.get(f"/prompts/{prompt['id']}").json()["imagens"][0]["id"] == imagem["id"]

    volta = cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": None}).json()
    assert volta["video_do_texto_id"] is None
    voltou = _artefato_do_frame(cliente, frame)
    assert voltou["video_id"] is None and voltou["imagem_id"] == imagem["id"]


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


def teste_ocultar_a_imagem_do_capitulo_nao_esconde_o_video_e_escolher_o_video_nao_mexe_nisso(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()

    cliente.put(f"/frames/{frame['id']}/imagem-oculta", json={"oculta": True})
    escolhido = cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]}).json()

    assert escolhido["imagem_oculta"] is True  # escolher o vídeo não desfaz o ocultar da imagem
    assert _artefato_do_frame(cliente, frame)["video_id"] == video["id"]  # e a imagem oculta não esconde o vídeo


def teste_mudar_o_video_do_texto_sobe_a_revisao_do_livro(cliente: TestClient, usar_provedor_falso) -> None:
    livro, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"]).json()
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] > antes  # o capítulo mostra outra coisa: o app precisa reler


# --------------------------------------------------------------------------- #
# VD17: o tamanho do vídeo
# --------------------------------------------------------------------------- #


def _atom(nome: bytes, conteudo: bytes) -> bytes:
    import struct

    return struct.pack(">I4s", 8 + len(conteudo), nome) + conteudo


def _mp4(largura: int, altura: int, girado: bool = False, versao: int = 0) -> bytes:
    """Um MP4 mínimo, só o suficiente para o servidor ler o ``tkhd``: ``ftyp``, e ``moov > trak > tkhd`` (e uma trilha de áudio sem tamanho antes)."""
    import struct

    matriz = struct.pack(">9i", 0, 0x10000, 0, -0x10000, 0, 0, 0, 0, 0x40000000) if girado else struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    if versao == 1:
        cabecalho = struct.pack(">B3xQQIIQ", 1, 0, 0, 1, 0, 0)
    else:
        cabecalho = struct.pack(">B3xIIIII", 0, 0, 0, 1, 0, 0)
    fim = struct.pack(">8x hhhh", 0, 0, 0, 0) + matriz
    def tkhd(l, a):
        return _atom(b"tkhd", cabecalho + fim + struct.pack(">II", l << 16, a << 16))
    audio = _atom(b"trak", tkhd(0, 0))
    video = _atom(b"trak", tkhd(largura, altura))
    return _atom(b"ftyp", b"mp42" + b"\x00" * 4 + b"mp42") + _atom(b"moov", audio + video) + _atom(b"mdat", b"\x00" * 32)


def teste_o_tamanho_do_mp4_vem_do_tkhd_com_a_rotacao(tmp_path) -> None:
    from imagineer.servicos.dimensoes_de_video import ler_dimensoes_do_video

    def ler(conteudo: bytes):
        arquivo = tmp_path / "v.mp4"
        arquivo.write_bytes(conteudo)
        return ler_dimensoes_do_video(arquivo)

    assert ler(_mp4(1280, 720)) == (1280, 720)  # pula a trilha de áudio, sem tamanho
    assert ler(_mp4(1280, 720, versao=1)) == (1280, 720)  # tkhd de 64 bits
    assert ler(_mp4(1920, 1080, girado=True)) == (1080, 1920)  # girado 90 graus: os lados se trocam
    assert ler(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64) is None  # sem moov
    assert ler(b"lixo") is None
    assert ler(bytes([0x1A, 0x45, 0xDF, 0xA3]) + b"\x00" * 64) is None  # WebM: sem tamanho


def teste_importar_um_mp4_grava_o_tamanho_e_o_artefato_traz_a_orientacao(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)

    paisagem = _importar_video(cliente, frame["id"], conteudo=_mp4(1280, 720)).json()
    retrato = _importar_video(cliente, frame["id"], conteudo=_mp4(720, 1280)).json()
    sem_tamanho = _importar_video(cliente, frame["id"], conteudo=WEBM, nome="a.webm").json()

    assert (paisagem["largura"], paisagem["altura"]) == (1280, 720)
    assert (retrato["largura"], retrato["altura"]) == (720, 1280)
    assert sem_tamanho["largura"] is None and sem_tamanho["altura"] is None
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": paisagem["id"]})
    artefato = _artefato_do_frame(cliente, frame)
    assert (artefato["video_largura"], artefato["video_altura"], artefato["video_orientacao"]) == (1280, 720, "PAISAGEM")
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": retrato["id"]})
    assert _artefato_do_frame(cliente, frame)["video_orientacao"] == "RETRATO"
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": sem_tamanho["id"]})
    assert _artefato_do_frame(cliente, frame)["video_orientacao"] is None  # o app trata como paisagem


def teste_o_video_importado_antes_do_tamanho_o_ganha_na_leitura_dos_artefatos(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas) -> None:
    _, frame = _cena(cliente, usar_provedor_falso)
    video = _importar_video(cliente, frame["id"], conteudo=_mp4(720, 1280)).json()
    from imagineer.modelos import Video

    sessao = sessao_com_tabelas
    registro = sessao.get(Video, video["id"])
    registro.largura = registro.altura = None  # como os vídeos importados antes da migração
    sessao.commit()
    cliente.put(f"/frames/{frame['id']}/video-no-texto", json={"video_id": video["id"]})

    artefato = _artefato_do_frame(cliente, frame)

    assert (artefato["video_largura"], artefato["video_altura"], artefato["video_orientacao"]) == (720, 1280, "RETRATO")
