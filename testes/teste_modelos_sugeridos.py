"""Os modelos sugeridos por item da configuração (item 4.10, SG1 a SG10): cada linha da tela de modelos ganha o botão **Sugeridos**.

Nada vai ao OpenRouter: o catálogo de texto é trocado por um de teste e o provedor é o falso (``ProvedorFalso``) com listas de imagem e de voz de teste.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import catalogo_de_texto
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ModeloDeImagemDisponivel, ModeloDeVoz
from imagineer.modelos.configuracao import MODELOS_DE_IMAGEM_PADRAO
from imagineer.servicos.modelos_recomendados import CAMPOS_DE_MODELO, RECOMENDACOES, Nivel, TipoDeCampo
from testes.teste_lm_presets_e_lista_de_modelos import _catalogo, _entrada
from testes.teste_rotas_prompts import _livro

ORDEM_DA_TELA = [
    "modelo_extracao", "modelo_leitura", "modelo_prompt", "modelo_traducao", "modelo_suavizacao", "modelo_video", "modelo_reserva",
    "modelo_perfil", "modelo_conferencia", "modelo_imagem", "modelo_narracao",
]


@pytest.fixture(autouse=True)
def _catalogo_limpo():
    catalogo_de_texto.limpar_cache_do_catalogo()
    yield
    catalogo_de_texto.limpar_cache_do_catalogo()


def _todos_os_modelos_de_texto() -> list[str]:
    ids = {rec.modelo for por_papel in RECOMENDACOES.values() for rec in por_papel.values()}
    for item in CAMPOS_DE_MODELO:
        ids |= {rec.modelo for rec in (item.sugestoes or {}).values()}
    return sorted(ids)


def _com_catalogo_cheio(monkeypatch, **extras_por_id) -> None:
    _catalogo(monkeypatch, *[_entrada(id_, **extras_por_id.get(id_, {})) for id_ in _todos_os_modelos_de_texto()])


def _provedor(usar_provedor_falso, modelos_de_imagem=None, modelos_de_voz=None) -> ProvedorFalso:
    """O provedor falso, com as listas de imagem e de voz trocadas pelas do teste (por padrão, **vazias**: o teste diz o que quer ver)."""
    provedor = ProvedorFalso()
    provedor.listar_modelos_de_imagem = lambda: list(modelos_de_imagem or [])
    provedor.listar_modelos_de_voz = lambda: list(modelos_de_voz or [])
    usar_provedor_falso(provedor)
    return provedor


def _item(corpo: list[dict], campo: str) -> dict:
    return next(i for i in corpo if i["campo"] == campo)


# --------------------------------------------------------------------------- #
# SG1: um item por linha da tela, na ordem da tela
# --------------------------------------------------------------------------- #


def teste_sg1_um_item_por_linha_da_tela_na_ordem_da_tela(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)

    resposta = cliente.get("/configuracao/modelos-sugeridos")

    assert resposta.status_code == 200, resposta.text
    assert [i["campo"] for i in resposta.json()] == ORDEM_DA_TELA
    assert all(i["rotulo"] and i["descricao"] for i in resposta.json())
    assert {i["campo"]: i["tipo"] for i in resposta.json()}["modelo_imagem"] == "imagem"
    assert {i["campo"]: i["tipo"] for i in resposta.json()}["modelo_narracao"] == "voz"


def teste_sg1_todo_campo_da_tabela_e_um_campo_que_a_configuracao_grava() -> None:
    from imagineer.modelos import Configuracao

    for item in CAMPOS_DE_MODELO:
        assert hasattr(Configuracao, item.campo), item.campo
    assert [i.campo for i in CAMPOS_DE_MODELO] == ORDEM_DA_TELA


# --------------------------------------------------------------------------- #
# SG2, SG3: os itens de texto
# --------------------------------------------------------------------------- #


def teste_sg2_cada_item_de_texto_traz_uma_sugestao_por_nivel_com_o_que_o_catalogo_diz(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)

    leitura = _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_leitura")

    assert leitura["tipo"] == "texto" and [s["nivel"] for s in leitura["sugestoes"]] == ["ECONOMICO", "EQUILIBRADO", "QUALIDADE"]
    economica = leitura["sugestoes"][0]
    assert economica["modelo"] == RECOMENDACOES[Nivel.ECONOMICO][next(p for p in RECOMENDACOES[Nivel.ECONOMICO] if p.name == "LEITURA")].modelo
    assert economica["disponivel"] is True and economica["motivo"]
    assert economica["preco_entrada"] == 1.0 and economica["preco_saida"] == 2.0  # US$ por milhão (o catálogo de teste: 0,000001 e 0,000002 por token)
    assert economica["rapido"] is True and economica["contexto"] == 1_000_000
    assert economica["custo_do_capitulo_tipico"] is not None and economica["custo_do_capitulo_tipico"] > 0


def teste_sg2_modelo_que_sumiu_do_catalogo_vem_indisponivel_e_sem_numeros(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    ids = [i for i in _todos_os_modelos_de_texto() if i != "google/gemini-2.5-flash-lite"]
    _catalogo(monkeypatch, *[_entrada(i) for i in ids])
    _provedor(usar_provedor_falso)

    sugestoes = _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_traducao")["sugestoes"]

    sumida = next(s for s in sugestoes if s["modelo"] == "google/gemini-2.5-flash-lite")
    assert sumida["disponivel"] is False and sumida["preco_entrada"] is None and sumida["custo_do_capitulo_tipico"] is None
    assert any(s["disponivel"] for s in sugestoes)  # as outras seguem valendo


def teste_sg3_perfil_e_conferencia_tem_a_propria_tabela_e_a_conferencia_avisa_se_nao_le_imagem(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(
        monkeypatch,
        **{"google/gemini-2.5-flash-lite": {"architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
           "google/gemini-2.5-flash": {"architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}}},
    )
    _provedor(usar_provedor_falso)

    corpo = cliente.get("/configuracao/modelos-sugeridos").json()
    perfil, conferencia = _item(corpo, "modelo_perfil"), _item(corpo, "modelo_conferencia")

    assert [s["modelo"] for s in perfil["sugestoes"]] == ["openai/gpt-4o-mini", "google/gemini-2.5-flash", "anthropic/claude-haiku-4.5"]
    assert all(s["aceita_imagem"] is None for s in perfil["sugestoes"])  # só a conferência olha imagens
    por_modelo = {s["modelo"]: s for s in conferencia["sugestoes"]}
    assert por_modelo["google/gemini-2.5-flash-lite"]["aceita_imagem"] is False  # um modelo de texto puro não serve
    assert por_modelo["google/gemini-2.5-flash"]["aceita_imagem"] is True


def teste_sg3_os_itens_extras_nao_mudam_o_preset_dos_niveis() -> None:
    """Perfil e conferência não são papéis de nível: aplicar um nível continua só nos sete papéis de antes."""
    from imagineer.servicos.modelos_recomendados import CAMPO_DA_CONFIGURACAO

    assert "modelo_perfil" not in CAMPO_DA_CONFIGURACAO.values() and "modelo_conferencia" not in CAMPO_DA_CONFIGURACAO.values()


# --------------------------------------------------------------------------- #
# SG4: o que está em uso
# --------------------------------------------------------------------------- #


def teste_sg4_o_modelo_em_uso_vem_marcado_e_o_atual_diz_qual(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)
    assert cliente.put("/configuracao", json={"modelo_prompt": "google/gemini-2.5-flash"}).status_code == 200

    prompt = _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_prompt")

    assert prompt["atual"] == "google/gemini-2.5-flash"
    assert [s["em_uso"] for s in prompt["sugestoes"]] == [False, True, False]  # só a do nível Equilibrado
    assert _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_leitura")["atual"] is None


def teste_sg4_com_livro_vale_a_troca_do_livro_e_sem_troca_o_global(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)
    livro = _livro(cliente)
    cliente.put("/configuracao", json={"modelo_prompt": "openai/gpt-4o-mini", "modelo_leitura": "google/gemini-2.5-flash"})
    assert cliente.put(f"/livros/{livro['id']}/modelos", json={"modelo_prompt": "anthropic/claude-haiku-4.5"}).status_code == 200

    corpo = cliente.get("/configuracao/modelos-sugeridos", params={"livro_id": livro["id"]}).json()

    assert _item(corpo, "modelo_prompt")["atual"] == "anthropic/claude-haiku-4.5"  # a troca do livro
    assert _item(corpo, "modelo_leitura")["atual"] == "google/gemini-2.5-flash"  # sem troca: o global
    assert cliente.get("/configuracao/modelos-sugeridos", params={"livro_id": 99999}).status_code == 404


def teste_sg4_cada_pessoa_ve_a_propria_configuracao(cliente: TestClient, sessao_com_tabelas: Session, monkeypatch, usar_provedor_falso) -> None:
    from imagineer.modelos import Usuario
    from imagineer.servicos.acesso import definir_usuario

    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_prompt": "openai/gpt-4o-mini"})
    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    definir_usuario(sessao_com_tabelas, maria.id)

    assert _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_prompt")["atual"] is None


# --------------------------------------------------------------------------- #
# SG5: imagem
# --------------------------------------------------------------------------- #


def teste_sg5_imagem_sugere_os_modelos_do_sistema_com_a_disponibilidade_do_catalogo(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(
        usar_provedor_falso,
        modelos_de_imagem=[ModeloDeImagemDisponivel(id=m, nome=m, preco_por_token=None, moderado=False) for m in MODELOS_DE_IMAGEM_PADRAO[:2]],
    )

    imagem = _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_imagem")

    assert [s["modelo"] for s in imagem["sugestoes"]] == MODELOS_DE_IMAGEM_PADRAO
    assert [s["disponivel"] for s in imagem["sugestoes"]] == [True, True, False]  # o terceiro sumiu do catálogo de imagem de teste
    assert all(s["nivel"] is None for s in imagem["sugestoes"])
    assert imagem["atual"] == MODELOS_DE_IMAGEM_PADRAO[0] and imagem["sugestoes"][0]["em_uso"] is True  # o padrão que a configuração já traz


# --------------------------------------------------------------------------- #
# SG6: voz
# --------------------------------------------------------------------------- #


def _voz(id_: str, preco: str | None, vozes: list[str] | None = None, gratuito: bool = False) -> ModeloDeVoz:
    return ModeloDeVoz(id=id_, nome=id_, vozes=vozes if vozes is not None else ["pt-BR-Ana"], preco_por_caractere=None if preco is None else Decimal(preco), gratuito=gratuito)


def teste_sg6_voz_sugere_os_tres_mais_baratos_que_falam_portugues_e_um_gratuito(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(
        usar_provedor_falso,
        modelos_de_voz=[
            _voz("a/caro", "0.0003"), _voz("a/barato", "0.00001"), _voz("a/medio", "0.0001"), _voz("a/quase", "0.0002"),
            _voz("a/ingles", "0.000001", vozes=["en-US-Joe"]),  # mais barato de todos, mas não fala português
            _voz("a/sem-preco", None),  # cobra por token ou segundo: sem estimativa, não entra no ranking
            _voz("a/gratis", "0", gratuito=True),
        ],
    )
    assert cliente.put("/configuracao", json={"modelo_narracao": "a/medio"}).status_code == 200

    voz = _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_narracao")

    assert [s["modelo"] for s in voz["sugestoes"]] == ["a/barato", "a/medio", "a/quase", "a/gratis"]
    assert all(s["fala_portugues"] is True for s in voz["sugestoes"])
    assert "o mais barato" in voz["sugestoes"][0]["motivo"] and "gratuito" in voz["sugestoes"][3]["motivo"]
    assert voz["sugestoes"][0]["preco_por_caractere"] == 0.00001 and voz["sugestoes"][3]["gratuito"] is True
    assert [s["em_uso"] for s in voz["sugestoes"]] == [False, True, False, False] and voz["atual"] == "a/medio"


def teste_sg6_sem_catalogo_de_voz_a_lista_vem_vazia_e_nao_quebra_a_tela(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)  # o provedor falso não lista vozes

    voz = _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_narracao")

    assert voz["sugestoes"] == []


# --------------------------------------------------------------------------- #
# SG7: o que a rota não faz
# --------------------------------------------------------------------------- #


def teste_sg7_a_rota_nao_grava_nada_e_aplicar_e_o_put_de_sempre(cliente: TestClient, monkeypatch, usar_provedor_falso) -> None:
    _com_catalogo_cheio(monkeypatch)
    _provedor(usar_provedor_falso)
    antes = cliente.get("/configuracao").json()

    sugestoes = cliente.get("/configuracao/modelos-sugeridos").json()
    assert cliente.get("/configuracao").json() == antes  # olhar as sugestões não muda a configuração

    escolhida = _item(sugestoes, "modelo_leitura")["sugestoes"][1]["modelo"]
    assert cliente.put("/configuracao", json={"modelo_leitura": escolhida}).json()["modelo_leitura"] == escolhida
    assert _item(cliente.get("/configuracao/modelos-sugeridos").json(), "modelo_leitura")["sugestoes"][1]["em_uso"] is True


def teste_sg7_nenhuma_sugestao_e_variante_em_lote_nem_gratuita() -> None:
    """A tabela curada nunca traz um id ``:batch`` (a conversa o recusa) nem um modelo gratuito de texto (fila e JSON irregular)."""
    for item in CAMPOS_DE_MODELO:
        if item.tipo != TipoDeCampo.TEXTO:
            continue
        for rec in ({n: r for n, por in RECOMENDACOES.items() for r in [por[item.papel]]} if item.papel else item.sugestoes).values():
            assert not rec.modelo.endswith(":batch") and not rec.modelo.endswith(":free"), (item.campo, rec.modelo)
