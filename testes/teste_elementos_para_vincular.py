"""O seletor de elementos e imagens: a rota `GET /frames/{id}/elementos-para-vincular` (item 7.5b, EV1 a EV7)."""

from fastapi.testclient import TestClient

from imagineer.modelos import SugestaoDeCena, SugestaoDeElemento
from testes.teste_rotas_prompts import _frame, _importar_imagem
from testes.teste_vinculos_do_retrato import _cenario, _elemento, _preparar_prompt, _retrato
from imagineer.ia.falso import ProvedorFalso


def _montar(cliente: TestClient, usar_provedor_falso):
    provedor = ProvedorFalso(prompt="um prompt")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    return capitulo, e


def _sugerir(sessao, capitulo_id: int, elemento: dict, tipo: str, descartada: bool = False) -> SugestaoDeElemento:
    sugestao = SugestaoDeElemento(
        capitulo_id=capitulo_id, tipo=tipo, nome=elemento["nome"], modelo="x", elemento_id=elemento["id"], descartada=descartada
    )
    sessao.add(sugestao)
    sessao.commit()
    return sugestao


def _consultar(cliente: TestClient, frame_id: int) -> dict:
    resposta = cliente.get(f"/frames/{frame_id}/elementos-para-vincular")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _nomes(lista: list[dict]) -> list[str]:
    return [x["nome"] for x in lista]


def teste_ev2_identificados_sao_as_sugestoes_do_capitulo_e_outros_os_que_so_tem_estado_aqui(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["criatura"], "CRIATURA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["objeto"], "OBJETO")

    corpo = _consultar(cliente, cena["id"])

    assert _nomes(corpo["identificados"]) == ["Foxen", "Prato"]
    # Manto, Auri e Xícara têm estado neste capítulo mas a IA não os sugeriu.
    assert sorted(_nomes(corpo["outros"])) == ["Auri", "Manto", "Xícara"]


def teste_ev2_sugestao_descartada_ou_sem_elemento_nao_e_identificada(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["objeto"], "OBJETO", descartada=True)
    sessao_com_tabelas.add(SugestaoDeElemento(capitulo_id=capitulo["id"], tipo="OBJETO", nome="Sem elemento", modelo="x"))
    sessao_com_tabelas.commit()

    corpo = _consultar(cliente, cena["id"])

    assert corpo["identificados"] == []
    assert "Prato" in _nomes(corpo["outros"])  # descartada na IA, mas tem estado aqui: continua disponível


def teste_ev6_cada_elemento_traz_o_estado_a_ligar_e_se_ja_esta_no_frame(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"]], tipo="CENA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["criatura"], "CRIATURA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["ambiente"], "AMBIENTE")

    corpo = _consultar(cliente, cena["id"])

    por_nome = {x["nome"]: x for x in corpo["identificados"] + corpo["outros"]}
    assert por_nome["Foxen"]["estado_id"] == e["criatura"]["estado_id"] and por_nome["Foxen"]["no_frame"] is True
    assert por_nome["Manto"]["no_frame"] is False and por_nome["Manto"]["estado_id"] == e["ambiente"]["estado_id"]
    assert por_nome["Prato"]["no_frame"] is True  # participa mas não foi sugerido: aparece em "outros"


def teste_ev5_na_cena_o_participante_da_sugestao_nunca_sai_e_o_acrescentado_a_mao_sai(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    s_criatura = _sugerir(sessao_com_tabelas, capitulo["id"], e["criatura"], "CRIATURA")
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"], e["objeto"]["estado_id"]], tipo="CENA")
    sessao_com_tabelas.add(SugestaoDeCena(capitulo_id=capitulo["id"], titulo="No pátio", modelo="x", frame_id=cena["id"], participantes=[s_criatura]))
    sessao_com_tabelas.commit()

    corpo = _consultar(cliente, cena["id"])

    por_nome = {x["nome"]: x for x in corpo["identificados"] + corpo["outros"]}
    assert por_nome["Foxen"]["removivel"] is False  # veio da sugestão da cena
    assert por_nome["Prato"]["removivel"] is True  # acrescentado à mão
    assert por_nome["Manto"]["removivel"] is False  # nem está no frame


def teste_ev5_na_cena_entram_todos_os_tipos_inclusive_personagem(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["personagem"], "PERSONAGEM")

    corpo = _consultar(cliente, cena["id"])

    assert "Auri" in _nomes(corpo["identificados"])


def teste_ev5_no_retrato_so_o_sujeito_fica_de_fora_e_o_personagem_aparece(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"]).json()
    for nome in ("criatura", "objeto", "personagem"):
        _sugerir(sessao_com_tabelas, capitulo["id"], e[nome], e[nome].get("tipo", "OBJETO"))

    corpo = _consultar(cliente, retrato["id"])

    assert sorted(_nomes(corpo["identificados"])) == ["Auri", "Prato"]  # sem o sujeito (Foxen), mas com a personagem (Auri)
    assert sorted(_nomes(corpo["outros"])) == ["Manto", "Xícara"]


def teste_ev5_retrato_de_personagem_nao_oferece_nada(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["personagem"]).json()
    _sugerir(sessao_com_tabelas, capitulo["id"], e["objeto"], "OBJETO")

    assert _consultar(cliente, retrato["id"]) == {"identificados": [], "outros": [], "de_outros_capitulos": []}


def teste_ev5_no_retrato_os_vinculados_aparecem_como_no_frame_e_removiveis(cliente: TestClient, usar_provedor_falso) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    retrato = _retrato(cliente, capitulo, e["criatura"], [e["objeto"]]).json()

    corpo = _consultar(cliente, retrato["id"])

    por_nome = {x["nome"]: x for x in corpo["identificados"] + corpo["outros"]}
    assert por_nome["Prato"]["no_frame"] is True and por_nome["Prato"]["removivel"] is True
    assert por_nome["Manto"]["no_frame"] is False


def teste_ev3_cada_elemento_traz_as_imagens_do_retrato_dele_com_a_ancora(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas
) -> None:
    capitulo, e = _montar(cliente, usar_provedor_falso)
    do_objeto = _retrato(cliente, capitulo, e["objeto"]).json()
    prompt = cliente.post(f"/frames/{do_objeto['id']}/prompts", json={}).json()
    primeira = _importar_imagem(cliente, prompt["id"])
    segunda = _importar_imagem(cliente, prompt["id"])
    cliente.patch(f"/elementos/{e['objeto']['id']}", json={"imagem_ancora_padrao_id": primeira["id"]})
    cena = _frame(cliente, capitulo["id"], [e["criatura"]["estado_id"]], tipo="CENA")
    _sugerir(sessao_com_tabelas, capitulo["id"], e["objeto"], "OBJETO")

    corpo = _consultar(cliente, cena["id"])

    [prato] = [x for x in corpo["identificados"] if x["nome"] == "Prato"]
    assert [i["id"] for i in prato["imagens"]] == [segunda["id"], primeira["id"]]  # mais recente primeiro
    assert [i["ancora"] for i in prato["imagens"]] == [False, True]
    [foxen] = [x for x in corpo["outros"] if x["nome"] == "Foxen"]
    assert foxen["imagens"] == []  # elemento sem imagem vem com a lista vazia


def teste_ev2_outros_sao_so_os_que_tem_estado_neste_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    aqui = _elemento(cliente, livro["id"], primeiro["id"], "Prato", "OBJETO")
    la = _elemento(cliente, livro["id"], segundo["id"], "Escudo", "OBJETO")
    sujeito = _elemento(cliente, livro["id"], primeiro["id"], "Foxen", "CRIATURA")
    cena = _frame(cliente, primeiro["id"], [sujeito["estado_id"]], tipo="CENA")

    corpo = _consultar(cliente, cena["id"])

    assert "Prato" in _nomes(corpo["outros"])
    assert "Escudo" not in _nomes(corpo["outros"]) + _nomes(corpo["identificados"])  # só tem estado em outro capítulo
    assert aqui and la


def teste_ev6_frame_inexistente_da_404(cliente: TestClient) -> None:
    assert cliente.get("/frames/99999/elementos-para-vincular").status_code == 404


def teste_ev6_quem_ja_esta_no_frame_sempre_aparece_mesmo_com_estado_de_outro_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    """O app grava o conjunto inteiro dos participantes: quem está na cena não pode sumir da lista."""
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    de_antes = _elemento(cliente, livro["id"], primeiro["id"], "Escudo", "OBJETO")  # só tem estado no capítulo 1
    cena = _frame(cliente, segundo["id"], [de_antes["estado_id"]], tipo="CENA")  # mas participa de uma cena do capítulo 2

    corpo = _consultar(cliente, cena["id"])

    [escudo] = [x for x in corpo["identificados"] + corpo["outros"] if x["nome"] == "Escudo"]
    assert escudo["no_frame"] is True and escudo["estado_id"] == de_antes["estado_id"]


def teste_vm7_elementos_sem_estado_neste_capitulo_vem_em_de_outros_capitulos_com_o_estado_vigente(
    cliente: TestClient, usar_provedor_falso
) -> None:
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    de_antes = _elemento(cliente, livro["id"], primeiro["id"], "Escudo", "OBJETO")  # só tem estado no capítulo 1
    cena = _frame(cliente, segundo["id"], [], tipo="CENA")  # a cena do capítulo 2 não o cita

    corpo = _consultar(cliente, cena["id"])

    [escudo] = corpo["de_outros_capitulos"]
    assert escudo["nome"] == "Escudo" and escudo["estado_id"] == de_antes["estado_id"]
    assert escudo["no_frame"] is False
    assert all(x["nome"] != "Escudo" for x in corpo["identificados"] + corpo["outros"])


def teste_vm7_elemento_que_so_aparece_depois_usa_o_primeiro_estado_dele(cliente: TestClient, usar_provedor_falso) -> None:
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    do_futuro = _elemento(cliente, livro["id"], segundo["id"], "Rei", "PERSONAGEM")  # só tem estado no capítulo 2
    cena = _frame(cliente, primeiro["id"], [], tipo="CENA")

    [rei] = _consultar(cliente, cena["id"])["de_outros_capitulos"]

    assert rei["nome"] == "Rei" and rei["estado_id"] == do_futuro["estado_id"]


def teste_vm7_a_cena_aceita_participante_de_outro_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    from testes.teste_rotas_sugestoes import _livro_com_capitulos

    usar_provedor_falso(ProvedorFalso(prompt="um prompt"))
    livro = _livro_com_capitulos(cliente)
    primeiro, segundo = livro["capitulos"][0], livro["capitulos"][1]
    escudo = _elemento(cliente, livro["id"], primeiro["id"], "Escudo", "OBJETO")
    cena = _frame(cliente, segundo["id"], [], tipo="CENA")

    resposta = cliente.put(f"/frames/{cena['id']}/estados", json={"estados_ids": [escudo["estado_id"]]})

    assert resposta.status_code == 200, resposta.text
    assert [x["nome"] for x in resposta.json()["elementos"]] == ["Escudo"]
    [escudo_na_cena] = [x for x in _consultar(cliente, cena["id"])["outros"] if x["nome"] == "Escudo"]  # agora está no frame
    assert escudo_na_cena["no_frame"] is True
