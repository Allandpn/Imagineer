"""O catálogo dos modelos de imagem, o preço dinâmico e o teste de resolução (item 7.5b, MI1 a MI5 e PD1 a PD5)."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ErroDoProvedorIA
from imagineer.modelos import Imagem, UsoDeIA
from imagineer.servicos import precos_de_imagem
from testes.teste_lixeira_de_frames import _frame_com_imagem


def _fornecedores(monkeypatch, *, fal=True, replicate=True, falha_do_fal=False) -> None:
    """Faz o fal.ai e o Replicate 'responderem' (lista de modelos, preços do fal e a coleção do Replicate), sem rede."""

    def ler(url, params=None, cabecalhos=None):
        if falha_do_fal and "fal.ai" in url:
            raise precos_de_imagem.httpx.ConnectError("fora")
        if url.endswith("/models/pricing"):
            tabela = {"fal-ai/flux/dev": (0.025, "megapixels"), "fal-ai/flux/schnell": (0.003, "megapixels")}
            return {"prices": [{"endpoint_id": e, "unit_price": tabela[e][0], "unit": tabela[e][1]} for _, e in (params or []) if e in tabela]}
        if url.endswith("fal.ai/v1/models"):
            return {
                "models": [
                    {"endpoint_id": "fal-ai/flux/dev", "metadata": {"display_name": "FLUX.1 [dev]", "status": "active"}},
                    {"endpoint_id": "fal-ai/flux/schnell", "metadata": {"display_name": "FLUX.1 [schnell]", "status": "active"}},
                    {"endpoint_id": "fal-ai/velho", "metadata": {"display_name": "Velho", "status": "deprecated"}},
                ],
                "has_more": False,
            }
        if "collections/text-to-image" in url:
            return {"models": [{"owner": "black-forest-labs", "name": "flux-dev"}, {"owner": "black-forest-labs", "name": "flux-schnell"}]}
        return {}

    monkeypatch.setattr(precos_de_imagem, "_get", ler)
    monkeypatch.setattr(precos_de_imagem, "_chave_do_fal", lambda: "k" if fal else "")
    monkeypatch.setattr(precos_de_imagem, "_chave_do_replicate", lambda: "k" if replicate else "")


def _catalogo(cliente: TestClient) -> dict:
    resposta = cliente.get("/configuracao/modelos-de-imagem")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _por_id(catalogo: dict) -> dict:
    return {m["id"]: m for m in catalogo["modelos"]}


def teste_mi1_o_catalogo_junta_openrouter_fal_e_replicate(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)

    modelos = _por_id(_catalogo(cliente))

    assert modelos["meta/muse-image"]["fornecedor"] == "OpenRouter"
    assert modelos["meta/muse-image"]["preco_por_milhao_de_tokens"] == "2.40"
    assert modelos["fal:fal-ai/flux/dev"]["fornecedor"] == "fal.ai"
    assert modelos["fal:fal-ai/flux/dev"]["nome"] == "FLUX.1 [dev]"
    assert modelos["replicate:black-forest-labs/flux-schnell"]["fornecedor"] == "Replicate"
    assert "fal:fal-ai/velho" not in modelos  # só os ativos


def teste_mi1_o_padrao_vem_primeiro_e_marcado_em_uso_e_disponivel(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)

    catalogo = _catalogo(cliente)

    primeiro = catalogo["modelos"][0]
    assert (primeiro["id"], primeiro["em_uso"], primeiro["disponivel"]) == ("meta/muse-image", True, True)
    assert _por_id(catalogo)["bytedance-seed/seedream-5-0-flash"]["disponivel"] is True  # está na lista padrão de escolha
    assert _por_id(catalogo)["fal:fal-ai/flux/dev"]["disponivel"] is False


def teste_pd1_o_preco_do_fal_vem_da_api_dele_estimado_e_os_outros_sem_informacao_ficam_sem_preco(
    cliente: TestClient, usar_provedor_falso, monkeypatch
) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)

    modelos = _por_id(_catalogo(cliente))

    flux = modelos["fal:fal-ai/flux/dev"]
    assert (Decimal(flux["preco_por_imagem"]), flux["origem_do_preco"]) == (Decimal("0.025"), "fornecedor")
    muse = modelos["meta/muse-image"]
    assert (muse["preco_por_imagem"], muse["origem_do_preco"]) == (None, None)  # nunca um valor inventado
    replicate = modelos["replicate:black-forest-labs/flux-dev"]
    assert (replicate["preco_por_imagem"], replicate["origem_do_preco"]) == (None, None)  # o Replicate não publica preço


def teste_pd1_o_preco_do_fal_usa_a_resolucao_do_modelo_quando_ela_e_conhecida(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session, monkeypatch
) -> None:
    _, _, imagem, _, _ = _frame_com_imagem(cliente, usar_provedor_falso)
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)
    registro = sessao_com_tabelas.get(Imagem, imagem["id"])
    registro.modelo = "fal:fal-ai/flux/dev"
    registro.largura, registro.altura = 2000, 1000  # 2 megapixels
    sessao_com_tabelas.commit()

    flux = _por_id(_catalogo(cliente))["fal:fal-ai/flux/dev"]

    assert flux["resolucao_tipica"] == "2000×1000"
    assert Decimal(flux["preco_por_imagem"]) == Decimal("0.05")


def teste_mi2_o_preco_medido_e_a_media_do_que_ja_custou_e_ignora_o_estimado(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    usar_provedor_falso(ProvedorFalso())
    for custo, estimado in (("0.01", False), ("0.03", False), ("0.50", True)):
        sessao_com_tabelas.add(UsoDeIA(operacao="imagem", modelo="meta/muse-image", custo=Decimal(custo), estimado=estimado))
    sessao_com_tabelas.add(UsoDeIA(operacao="prompt", modelo="meta/muse-image", custo=Decimal("9")))  # não é imagem
    sessao_com_tabelas.commit()

    muse = _por_id(_catalogo(cliente))["meta/muse-image"]

    assert Decimal(muse["preco_por_imagem"]) == Decimal("0.02")
    assert muse["origem_do_preco"] == "medido"


def teste_mi2_o_medido_vale_mais_que_o_do_fornecedor(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)
    sessao_com_tabelas.add(UsoDeIA(operacao="imagem", modelo="fal:fal-ai/flux/dev", custo=Decimal("0.031"), estimado=False))
    sessao_com_tabelas.commit()

    flux = _por_id(_catalogo(cliente))["fal:fal-ai/flux/dev"]

    assert (Decimal(flux["preco_por_imagem"]), flux["origem_do_preco"]) == (Decimal("0.031"), "medido")


def teste_pd5_o_preco_informado_vale_mais_que_o_do_fornecedor_e_limpar_volta(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)

    resposta = cliente.put("/configuracao/modelos-de-imagem/preco", json={"modelo": "replicate:black-forest-labs/flux-dev", "preco": "0,04"})
    fal = cliente.put("/configuracao/modelos-de-imagem/preco", json={"modelo": "fal:fal-ai/flux/dev", "preco": "0.031"})

    assert resposta.status_code == 200, resposta.text
    modelos = _por_id(fal.json())
    replicate = modelos["replicate:black-forest-labs/flux-dev"]
    assert (Decimal(replicate["preco_por_imagem"]), replicate["origem_do_preco"]) == (Decimal("0.04"), "informado")
    flux = modelos["fal:fal-ai/flux/dev"]
    assert (Decimal(flux["preco_por_imagem"]), flux["origem_do_preco"]) == (Decimal("0.031"), "informado")

    limpo = cliente.put("/configuracao/modelos-de-imagem/preco", json={"modelo": "fal:fal-ai/flux/dev", "preco": ""})
    assert _por_id(limpo.json())["fal:fal-ai/flux/dev"]["origem_do_preco"] == "fornecedor"  # volta ao que o fal.ai publica


def teste_pd5_o_medido_continua_valendo_mais_que_o_informado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    usar_provedor_falso(ProvedorFalso())
    sessao_com_tabelas.add(UsoDeIA(operacao="imagem", modelo="meta/muse-image", custo=Decimal("0.02"), estimado=False))
    sessao_com_tabelas.commit()

    saida = cliente.put("/configuracao/modelos-de-imagem/preco", json={"modelo": "meta/muse-image", "preco": "0.5"}).json()

    muse = _por_id(saida)["meta/muse-image"]
    assert (Decimal(muse["preco_por_imagem"]), muse["origem_do_preco"]) == (Decimal("0.02"), "medido")


def teste_pd5_preco_invalido_e_422(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())

    for ruim in ("abc", "0", "-1", "NaN", "Infinity"):
        resposta = cliente.put("/configuracao/modelos-de-imagem/preco", json={"modelo": "meta/muse-image", "preco": ruim})
        assert resposta.status_code == 422, ruim


def teste_pd4_se_a_leitura_do_fal_falha_o_catalogo_traz_um_aviso_e_segue(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch, falha_do_fal=True)

    catalogo = _catalogo(cliente)

    assert "fal.ai" in catalogo["aviso"]
    ids = _por_id(catalogo)
    assert "meta/muse-image" in ids and "replicate:black-forest-labs/flux-dev" in ids
    assert not any(i.startswith("fal:") for i in ids)


def teste_pd4_sem_chave_de_um_fornecedor_ele_nao_aparece_e_nao_ha_aviso(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch, fal=False, replicate=False)

    catalogo = _catalogo(cliente)

    assert catalogo["aviso"] is None
    assert not any(i.startswith(("fal:", "replicate:")) for i in _por_id(catalogo))


def teste_mi3_a_moderacao_de_cada_fornecedor(cliente: TestClient, usar_provedor_falso, monkeypatch) -> None:
    usar_provedor_falso(ProvedorFalso())
    _fornecedores(monkeypatch)
    cliente.put("/configuracao", json={"modelos_sem_filtro": ["replicate:black-forest-labs/flux-dev"]})

    modelos = _por_id(_catalogo(cliente))

    assert modelos["meta/muse-image"]["moderacao"] == "moderado"
    assert modelos["bytedance-seed/seedream-5-0-flash"]["moderacao"] == "sem moderação"
    assert modelos["fal:fal-ai/flux/dev"]["moderacao"] == "filtro sempre ligado"
    assert modelos["replicate:black-forest-labs/flux-dev"]["moderacao"] == "filtro pode ser desligado"


def teste_mi1_um_modelo_da_configuracao_fora_do_catalogo_aparece_e_aceita_referencia(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())
    cliente.put(
        "/configuracao",
        json={"modelos_de_imagem": ["replicate:outro/modelo-novo"], "modelos_com_referencia": {"replicate:outro/modelo-novo": "image_input"}},
    )

    novo = _por_id(_catalogo(cliente))["replicate:outro/modelo-novo"]

    assert (novo["disponivel"], novo["aceita_referencia"], novo["preco_por_imagem"]) == (True, True, None)


def teste_mi4_a_resolucao_tipica_e_a_da_imagem_mais_recente_do_modelo(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    _, _, imagem, _, _ = _frame_com_imagem(cliente, usar_provedor_falso)  # 20×30, sem modelo
    usar_provedor_falso(ProvedorFalso())
    registro = sessao_com_tabelas.get(Imagem, imagem["id"])
    registro.modelo = "meta/muse-image"
    registro.largura, registro.altura = 1024, 1536
    sessao_com_tabelas.commit()

    modelos = _por_id(_catalogo(cliente))

    assert modelos["meta/muse-image"]["resolucao_tipica"] == "1024×1536"
    assert modelos["bytedance-seed/seedream-5-0-flash"]["resolucao_tipica"] is None


def teste_mi1_se_o_openrouter_falha_vem_o_resto_com_um_aviso(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("fora do ar")))

    catalogo = _catalogo(cliente)

    assert "fora do ar" in catalogo["aviso"]
    ids = _por_id(catalogo)
    assert "meta/muse-image" in ids  # o padrão continua (vem da configuração)
    assert ids["meta/muse-image"]["nome"] == "meta/muse-image"


def teste_mi5_testar_devolve_resolucao_tamanho_e_previa_e_usa_um_prompt_neutro(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = usar_provedor_falso(ProvedorFalso())

    resposta = cliente.post("/configuracao/modelos-de-imagem/testar", json={"modelo": "meta/muse-image"})

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert (corpo["largura"], corpo["altura"]) == (20, 30)
    assert corpo["tamanho_em_bytes"] > 0 and corpo["previa_base64"] and corpo["modelo"] == "meta/muse-image"
    [chamada] = provedor.chamadas_de_imagem
    assert chamada["modelo"] == "meta/muse-image" and "apple" in chamada["prompt"]


def teste_mi5_o_teste_recusado_ou_com_erro_nao_devolve_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso(recusas_de_imagem=1))

    resposta = cliente.post("/configuracao/modelos-de-imagem/testar", json={"modelo": "meta/muse-image"})

    assert resposta.status_code == 502


def teste_mi5_modelo_vazio_e_recusado(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())

    assert cliente.post("/configuracao/modelos-de-imagem/testar", json={"modelo": ""}).status_code == 422
