"""As referências que a cena leva sozinha, só como identidade (item 4.9, FL10 e FL11; etapa 4).

Se o modelo de imagem aceita referências, a âncora de cada elemento **que está na lista da cena** vai por padrão, no máximo 4, o sujeito principal primeiro. A
pessoa pode tirar qualquer uma. Nenhum teste fala com o OpenRouter nem com um fornecedor de imagem.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.modelos import Imagem, Prompt, TipoElemento
from imagineer.servicos import referencias_da_cena
from imagineer.servicos.referencias_da_cena import ancoras_da_cena, presentes_do_dossie, referencias_automaticas

from testes.teste_rotas_prompts import MODELO_COM_REFERENCIA, _imagem_importada, _perfil
from testes.teste_vinculos_do_retrato import _cenario

DOSSIE = {
    "momento_incerto": False,
    "presentes": [
        {"nome": "Auri", "tipo": "PESSOA", "elemento": "Auri", "caracteristicas": "descalça", "incerto": False, "incluir": True},
        {"nome": "Foxen", "tipo": "CRIATURA", "elemento": "Foxen", "caracteristicas": "uma luz azul", "incerto": False, "incluir": True},
        {"nome": "o Manto", "tipo": "LUGAR", "elemento": "Manto", "caracteristicas": "sala de pedra", "incerto": False, "incluir": True},
        {"nome": "o prato", "tipo": "OBJETO", "elemento": "Prato", "caracteristicas": "de barro", "incerto": False, "incluir": True},
    ],
    "onde": "uma sala de pedra", "luz_e_clima": None, "acao": "Auri serve o prato", "faltou": [],
}


# --------------------------------------------------------------------------- #
# A escolha, sem banco (FL10)
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _arquivos_existem(monkeypatch):
    """Nos testes sem disco, toda imagem com ``caminho_arquivo`` "existe"."""
    monkeypatch.setattr(referencias_da_cena, "caminho_absoluto", lambda caminho: SimpleNamespace(is_file=lambda: caminho != "sumiu.png"))


def _imagem(id_: int, caminho: str = "ok.png", apagada=None) -> SimpleNamespace:
    return SimpleNamespace(id=id_, caminho_arquivo=caminho, apagada_em=apagada)


def _estado(id_: int, nome: str, tipo: TipoElemento = TipoElemento.PERSONAGEM, ancora=None, padrao=None) -> SimpleNamespace:
    return SimpleNamespace(id=id_, elemento=SimpleNamespace(nome=nome, tipo=tipo, imagem_ancora_padrao=padrao), imagem_ancora=ancora)


def _frame(*estados, dossie=None) -> SimpleNamespace:
    return SimpleNamespace(estados_elemento=list(estados), dossie=dossie)


def _lista(*nomes: str) -> list[dict]:
    return [{"elemento": n} for n in nomes]


def teste_fl10_cada_elemento_da_lista_manda_a_ancora_dele_na_ordem_da_lista() -> None:
    frame = _frame(_estado(1, "Auri", ancora=_imagem(10)), _estado(2, "Foxen", ancora=_imagem(20)), _estado(3, "Hospius", ancora=_imagem(30)))

    assert ancoras_da_cena(frame, _lista("Hospius", "Auri", "Foxen")) == [30, 10, 20]  # a ordem é a da lista: o sujeito principal primeiro


def teste_fl10_sem_dossie_valem_os_elementos_ligados_ao_frame_na_ordem_dos_estados() -> None:
    frame = _frame(_estado(2, "Foxen", ancora=_imagem(20)), _estado(1, "Auri", ancora=_imagem(10)))

    assert ancoras_da_cena(frame, None) == [10, 20]


def teste_fl10_elemento_ligado_ao_frame_mas_fora_da_lista_nao_manda_imagem() -> None:
    frame = _frame(_estado(1, "Auri", ancora=_imagem(10)), _estado(2, "Foxen", ancora=_imagem(20)))

    assert ancoras_da_cena(frame, _lista("Auri")) == [10]


def teste_fl10_presente_sem_elemento_cadastrado_ou_com_nome_que_nao_e_do_frame_e_ignorado() -> None:
    frame = _frame(_estado(1, "Auri", ancora=_imagem(10)))

    assert ancoras_da_cena(frame, [{"elemento": None}, {"elemento": "Fantasma"}, {"elemento": "auri"}]) == [10]  # sem diferença de maiúsculas


def teste_fl10_ambiente_e_edificacao_nao_vao_como_referencia() -> None:
    frame = _frame(
        _estado(1, "Auri", ancora=_imagem(10)),
        _estado(2, "Manto", TipoElemento.AMBIENTE, ancora=_imagem(20)),
        _estado(3, "Torre", TipoElemento.EDIFICACAO, ancora=_imagem(30)),
        _estado(4, "Prato", TipoElemento.OBJETO, ancora=_imagem(40)),
    )

    assert ancoras_da_cena(frame, None) == [10, 40]


def teste_fl10_elemento_sem_ancora_nao_manda_nada() -> None:
    frame = _frame(_estado(1, "Auri"), _estado(2, "Foxen", ancora=_imagem(20)))

    assert ancoras_da_cena(frame, None) == [20]


def teste_fl10_a_ancora_do_estado_vale_mais_que_a_padrao_do_elemento() -> None:
    frame = _frame(_estado(1, "Auri", ancora=_imagem(10), padrao=_imagem(99)), _estado(2, "Foxen", padrao=_imagem(77)))

    assert ancoras_da_cena(frame, None) == [10, 77]


def teste_fl10_ancora_na_lixeira_ou_sem_arquivo_e_pulada_sem_quebrar() -> None:
    from datetime import datetime

    frame = _frame(
        _estado(1, "Auri", ancora=_imagem(10, apagada=datetime(2026, 1, 1))),
        _estado(2, "Foxen", ancora=_imagem(20, caminho="sumiu.png")),
        _estado(3, "Hospius", ancora=_imagem(30)),
    )

    assert ancoras_da_cena(frame, None) == [30]


def teste_fl10_no_maximo_quatro_e_sem_repetir_a_mesma_imagem() -> None:
    frame = _frame(*[_estado(i, f"E{i}", ancora=_imagem(100 + i)) for i in range(1, 7)])
    assert ancoras_da_cena(frame, None) == [101, 102, 103, 104]

    mesma = _imagem(5)
    assert ancoras_da_cena(_frame(_estado(1, "A", ancora=mesma), _estado(2, "B", ancora=mesma)), None) == [5]


def teste_fl10_dois_estados_do_mesmo_elemento_nao_repetem_o_elemento() -> None:
    frame = _frame(_estado(1, "Auri", ancora=_imagem(10)), _estado(2, "Auri", ancora=_imagem(11)))

    assert ancoras_da_cena(frame, _lista("Auri", "Auri")) == [10]


def teste_fl10_so_entram_na_lista_os_presentes_que_a_pessoa_deixou() -> None:
    frame = SimpleNamespace(dossie={"presentes": [{"elemento": "Auri", "incluir": True}, {"elemento": "Foxen", "incluir": False}, {"elemento": "Hospius"}]})

    assert [p["elemento"] for p in presentes_do_dossie(frame)] == ["Auri", "Hospius"]
    assert presentes_do_dossie(SimpleNamespace(dossie=None)) is None


# --------------------------------------------------------------------------- #
# Com banco: a geração e o seletor
# --------------------------------------------------------------------------- #


def _cena_com_ancoras(cliente: TestClient, usar_provedor_falso, dossie: dict | None = DOSSIE, com_dossie_no_provedor: bool = True):
    """Uma cena com Auri, Foxen, Manto (ambiente) e Prato, cada um com uma âncora que veio do **retrato** dele.

    Devolve ``(provedor, prompt da cena, ancoras por nome, frame da cena)``; os estados ficam em ``cliente.estados_por_nome``.
    """
    provedor = usar_provedor_falso(ProvedorFalso(prompt="two figures", dossie=dossie if com_dossie_no_provedor else None))
    livro, capitulo, e = _cenario(cliente)
    estados = [e["personagem"], e["criatura"], e["ambiente"], e["objeto"]]  # Auri, Foxen, Manto, Prato
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put(
        "/configuracao",
        json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO, "modelos_com_referencia": {MODELO_COM_REFERENCIA: "image_input"}},
    )

    ancoras = {}
    for elemento in estados:  # a âncora de cada um é uma imagem do retrato dele, como na vida real
        retrato = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [elemento["estado_id"]]}).json()
        prompt_do_retrato = cliente.post(f"/frames/{retrato['id']}/prompts", json={}).json()
        imagem = _imagem_importada(cliente, prompt_do_retrato["id"])
        assert cliente.patch(f"/estados/{elemento['estado_id']}", json={"imagem_ancora_id": imagem["id"]}).status_code == 200
        ancoras[elemento["nome"]] = imagem["id"]

    frame = cliente.post(
        f"/capitulos/{capitulo['id']}/frames", json={"tipo": "CENA", "titulo": "O prato", "estados_ids": [x["estado_id"] for x in estados]}
    ).json()
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    cliente.estados_por_nome = {x["nome"]: x["estado_id"] for x in estados}
    cliente.capitulo_id = capitulo["id"]
    return provedor, prompt, ancoras, frame


def _gerar(cliente: TestClient, prompt_id: int, **corpo) -> dict:
    resposta = cliente.post(f"/prompts/{prompt_id}/gerar-imagem", json={"modelo": MODELO_COM_REFERENCIA, **corpo})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def teste_fl10_sem_dizer_as_referencias_a_cena_leva_as_ancoras_da_lista(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)

    corpo = _gerar(cliente, prompt["id"])

    # Auri, Foxen e Prato, na ordem da lista; o Manto (ambiente) não vai.
    assert corpo["prompt"]["imagens_de_referencia"] == [ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]]
    assert provedor.chamadas_de_imagem[-1]["referencias"] == {"parametro": "image_input", "quantidade": 3}


def teste_fl10_o_pedido_sem_corpo_tambem_usa_o_padrao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_imagem": MODELO_COM_REFERENCIA})

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert resposta.status_code == 200 and resposta.json()["prompt"]["imagens_de_referencia"] == [ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]]


def teste_fl10_lista_vazia_mandada_de_proposito_e_nenhuma_referencia(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, _, _ = _cena_com_ancoras(cliente, usar_provedor_falso)

    corpo = _gerar(cliente, prompt["id"], imagens_de_referencia=[])

    assert corpo["prompt"]["imagens_de_referencia"] == []
    assert "referencias" not in provedor.chamadas_de_imagem[-1]


def teste_fl10_a_pessoa_pode_tirar_e_mandar_so_algumas(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)

    corpo = _gerar(cliente, prompt["id"], imagens_de_referencia=[ancoras["Foxen"]])

    assert corpo["prompt"]["imagens_de_referencia"] == [ancoras["Foxen"]]


def teste_fl10_elemento_que_a_pessoa_tirou_da_lista_nao_manda_imagem(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, frame = _cena_com_ancoras(cliente, usar_provedor_falso)
    lista = cliente.get(f"/frames/{frame['id']}/dossie").json()["presentes"]
    for presente in lista:
        presente["incluir"] = presente["nome"] != "o prato"
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lista})
    novo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()  # a lista nova vale para o prompt novo

    corpo = _gerar(cliente, novo["id"])

    assert corpo["prompt"]["imagens_de_referencia"] == [ancoras["Auri"], ancoras["Foxen"]]


def teste_fl10_regerar_um_prompt_antigo_usa_a_lista_que_ele_usava(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, antigo, ancoras, frame = _cena_com_ancoras(cliente, usar_provedor_falso)
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": []})  # a pessoa esvazia a lista depois

    corpo = _gerar(cliente, antigo["id"])

    assert corpo["prompt"]["imagens_de_referencia"] == [ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]]  # a ficha do prompt antigo guardou a dele


def teste_fl10_sem_dossie_valem_os_elementos_ligados_a_cena(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso, com_dossie_no_provedor=False)

    corpo = _gerar(cliente, prompt["id"])

    # Na ordem dos estados do frame: Auri, Foxen, Manto (fora, é ambiente), Prato.
    assert set(corpo["prompt"]["imagens_de_referencia"]) == {ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]}


def teste_fl10_modelo_que_nao_aceita_referencias_segue_sem_elas_e_sem_erro(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, _, _ = _cena_com_ancoras(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "outro/modelo-sem-referencia"})

    assert resposta.status_code == 200 and resposta.json()["resultado"] == "GERADA"
    assert resposta.json()["prompt"]["imagens_de_referencia"] == []


def teste_fl10_no_fal_nao_se_manda_referencia_sozinha(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, _, _ = _cena_com_ancoras(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelos_com_referencia": {"fal:fal-ai/flux": "image_urls"}})

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "fal:fal-ai/flux"})

    assert resposta.status_code == 200 and resposta.json()["prompt"]["imagens_de_referencia"] == []


def teste_fl10_mandar_a_referencia_a_mao_num_modelo_que_nao_aceita_continua_dando_422(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"modelo": "outro/modelo", "imagens_de_referencia": [ancoras["Auri"]]})

    assert resposta.status_code == 422


def teste_fl10_elemento_sem_ancora_nao_manda_nada(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)
    cliente.patch(f"/estados/{cliente.estados_por_nome['Foxen']}", json={"imagem_ancora_id": None})

    corpo = _gerar(cliente, prompt["id"])

    assert corpo["prompt"]["imagens_de_referencia"] == [ancoras["Auri"], ancoras["Prato"]]


def teste_fl10_ancora_na_lixeira_nao_impede_a_geracao(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    from datetime import datetime, timezone

    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)
    sessao_com_tabelas.get(Imagem, ancoras["Auri"]).apagada_em = datetime.now(timezone.utc)
    sessao_com_tabelas.commit()

    corpo = _gerar(cliente, prompt["id"])

    assert corpo["resultado"] == "GERADA" and corpo["prompt"]["imagens_de_referencia"] == [ancoras["Foxen"], ancoras["Prato"]]


def teste_fl10_um_retrato_nao_leva_referencia_sozinho(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, _, ancoras, frame = _cena_com_ancoras(cliente, usar_provedor_falso)
    retrato = cliente.post(f"/capitulos/{cliente.capitulo_id}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [cliente.estados_por_nome["Auri"]]}).json()
    prompt = cliente.post(f"/frames/{retrato['id']}/prompts", json={}).json()

    corpo = _gerar(cliente, prompt["id"])

    assert corpo["prompt"]["imagens_de_referencia"] == []


def teste_fl10_a_frase_de_contexto_trava_as_referencias_como_so_identidade(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, _, _ = _cena_com_ancoras(cliente, usar_provedor_falso)

    _gerar(cliente, prompt["id"])

    enviado = provedor.chamadas_de_imagem[-1]["prompt"]
    assert enviado.startswith("Reference images are for IDENTITY ONLY (face, hair, skin, build) of: ")
    assert "Anything not described in the text must not appear." in enviado and enviado.endswith("two figures")


def teste_fl10_o_historico_da_imagem_e_a_ficha_guardam_as_referencias(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    _, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)
    esperadas = [ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]]

    corpo = _gerar(cliente, prompt["id"])

    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Imagem, corpo["imagem"]["id"]).imagens_de_referencia == esperadas
    assert sessao_com_tabelas.get(Prompt, prompt["id"]).ficha["referencias"] == esperadas
    assert cliente.get(f"/prompts/{prompt['id']}").json()["ficha"]["referencias"] == esperadas


def teste_fl10_depois_de_recusa_a_segunda_tentativa_mantem_as_mesmas_referencias(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, prompt, ancoras, _ = _cena_com_ancoras(cliente, usar_provedor_falso)
    provedor._recusas_de_imagem = 1  # a 1ª tentativa é recusada; a suavizada passa

    corpo = _gerar(cliente, prompt["id"])

    assert corpo["suavizado"] is True and corpo["prompt"]["imagens_de_referencia"] == [ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]]
    assert [c["referencias"]["quantidade"] for c in provedor.chamadas_de_imagem] == [3, 3]


def teste_fl10_o_seletor_ja_traz_as_marcadas_por_padrao(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, ancoras, frame = _cena_com_ancoras(cliente, usar_provedor_falso)

    corpo = cliente.get(f"/frames/{frame['id']}/referencias-candidatas").json()

    assert corpo["marcadas"] == [ancoras["Auri"], ancoras["Foxen"], ancoras["Prato"]]
    assert {e["nome"] for e in corpo["elementos"]} == {"Auri", "Foxen", "Manto", "Prato"}  # o Manto continua na lista, só não vem marcado


def teste_fl10_o_seletor_respeita_a_lista_confirmada(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, ancoras, frame = _cena_com_ancoras(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/dossie")
    lista = cliente.get(f"/frames/{frame['id']}/dossie").json()["presentes"]
    for presente in lista:
        presente["incluir"] = presente["nome"] == "Auri"
    cliente.put(f"/frames/{frame['id']}/dossie", json={"presentes": lista})

    assert cliente.get(f"/frames/{frame['id']}/referencias-candidatas").json()["marcadas"] == [ancoras["Auri"]]


def teste_fl10_o_seletor_de_um_retrato_nao_marca_nada(cliente: TestClient, usar_provedor_falso) -> None:
    _cena_com_ancoras(cliente, usar_provedor_falso)
    retrato = cliente.post(f"/capitulos/{cliente.capitulo_id}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [cliente.estados_por_nome["Auri"]]}).json()

    assert cliente.get(f"/frames/{retrato['id']}/referencias-candidatas").json()["marcadas"] == []


# --------------------------------------------------------------------------- #
# referencias_automaticas, sem rota
# --------------------------------------------------------------------------- #


def _prompt(frame, ficha=None, tipo="IMAGEM", so_imagem=False) -> SimpleNamespace:
    from imagineer.modelos.prompt import TipoDePrompt

    return SimpleNamespace(frame=frame, ficha=ficha, tipo=TipoDePrompt(tipo), so_imagem=so_imagem)


def _frame_de_cena(*estados) -> SimpleNamespace:
    from imagineer.modelos import TipoDeFrame

    return SimpleNamespace(tipo=TipoDeFrame.CENA, estados_elemento=list(estados), dossie=None)


CONFIGURACAO = SimpleNamespace(modelos_com_referencia={MODELO_COM_REFERENCIA: "image_input"})


def teste_fl10_so_uma_cena_de_imagem_leva_referencia_automatica() -> None:
    from imagineer.modelos import TipoDeFrame

    estado = _estado(1, "Auri", ancora=_imagem(10))
    cena = _frame_de_cena(estado)
    retrato = SimpleNamespace(tipo=TipoDeFrame.PERSONAGEM, estados_elemento=[estado], dossie=None)

    assert referencias_automaticas(_prompt(cena), CONFIGURACAO, MODELO_COM_REFERENCIA) == [10]
    assert referencias_automaticas(_prompt(retrato), CONFIGURACAO, MODELO_COM_REFERENCIA) == []
    assert referencias_automaticas(_prompt(cena, tipo="VIDEO"), CONFIGURACAO, MODELO_COM_REFERENCIA) == []
    assert referencias_automaticas(_prompt(cena, so_imagem=True), CONFIGURACAO, MODELO_COM_REFERENCIA) == []
    assert referencias_automaticas(_prompt(None), CONFIGURACAO, MODELO_COM_REFERENCIA) == []


def teste_fl10_a_ficha_sem_dossie_manda_valer_todos_os_ligados_e_com_dossie_so_a_lista() -> None:
    cena = _frame_de_cena(_estado(1, "Auri", ancora=_imagem(10)), _estado(2, "Foxen", ancora=_imagem(20)))

    sem_dossie = {"dossie": None, "presentes": []}
    com_dossie = {"dossie": {"confirmado": True}, "presentes": [{"elemento": "Foxen"}]}

    assert referencias_automaticas(_prompt(cena, sem_dossie), CONFIGURACAO, MODELO_COM_REFERENCIA) == [10, 20]
    assert referencias_automaticas(_prompt(cena, com_dossie), CONFIGURACAO, MODELO_COM_REFERENCIA) == [20]
    assert referencias_automaticas(_prompt(cena, None), CONFIGURACAO, MODELO_COM_REFERENCIA) == [10, 20]  # prompt de antes da ficha


def teste_fl10_modelo_sem_referencia_ou_do_fal_nao_leva_nada() -> None:
    cena = _frame_de_cena(_estado(1, "Auri", ancora=_imagem(10)))
    configuracao = SimpleNamespace(modelos_com_referencia={MODELO_COM_REFERENCIA: "image_input", "fal:fal-ai/flux": "image_urls"})

    assert referencias_automaticas(_prompt(cena), configuracao, "outro/modelo") == []
    assert referencias_automaticas(_prompt(cena), configuracao, "fal:fal-ai/flux") == []
    assert referencias_automaticas(_prompt(cena), SimpleNamespace(modelos_com_referencia=None), MODELO_COM_REFERENCIA) == []
