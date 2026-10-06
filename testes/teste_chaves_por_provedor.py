"""As chaves de IA da própria pessoa, uma por provedor (item CT24): a lista fixa, o header de cada um e a precedência sobre a chave do servidor."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.configuracao import obter_configuracoes
from imagineer.ia.provedores import PROVEDORES, Provedor
from imagineer.modelos import Usuario
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.acesso import definir_usuario
from imagineer.servicos.configuracao_ia import construir_provedor


@pytest.fixture
def chaves_do_servidor(monkeypatch):
    """O servidor tem chave dos três provedores (variáveis de ambiente); as configurações são lidas uma vez só, então limpa o cache."""
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "or-do-servidor")
    monkeypatch.setenv("FAL_KEY", "fal-do-servidor")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "rep-do-servidor")
    obter_configuracoes.cache_clear()
    try:
        yield
    finally:
        monkeypatch.undo()
        obter_configuracoes.cache_clear()


def _maria(sessao: Session) -> Usuario:
    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao.add(maria)
    sessao.commit()
    return maria


def teste_ct24_a_lista_e_fixa_e_cada_provedor_tem_o_seu_header() -> None:
    assert [p.value for p in Provedor] == ["OPENROUTER", "FAL", "REPLICATE"]
    assert {p: d.cabecalho for p, d in PROVEDORES.items()} == {
        Provedor.OPENROUTER: "X-Chave-API-OpenRouter",
        Provedor.FAL: "X-Chave-API-Fal",
        Provedor.REPLICATE: "X-Chave-API-Replicate",
    }
    assert len({d.cabecalho for d in PROVEDORES.values()}) == 3  # uma chave por provedor, sem dois no mesmo header


def teste_ct24_a_rota_lista_os_provedores_sem_nenhuma_chave(cliente: TestClient, chaves_do_servidor) -> None:
    resposta = cliente.get("/configuracao/provedores")

    assert resposta.status_code == 200
    assert [p["id"] for p in resposta.json()] == ["OPENROUTER", "FAL", "REPLICATE"]
    assert resposta.json()[1] == {"id": "FAL", "nome": "fal.ai", "cabecalho": "X-Chave-API-Fal", "usado_para": "imagem", "servidor_fornece": True}
    for chave in ("or-do-servidor", "fal-do-servidor", "rep-do-servidor"):
        assert chave not in resposta.text  # nunca devolve chave


def teste_ct24_quem_nao_usa_o_servidor_ve_servidor_fornece_falso(cliente: TestClient, sessao_com_tabelas: Session, chaves_do_servidor) -> None:
    definir_usuario(sessao_com_tabelas, _maria(sessao_com_tabelas).id)

    assert [p["servidor_fornece"] for p in cliente.get("/configuracao/provedores").json()] == [False, False, False]


def teste_ct24_provedor_que_o_servidor_nao_tem_nao_e_fornecido_nem_para_o_dono(cliente: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "or-do-servidor")
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    monkeypatch.delenv("CHAVE_API_FAL", raising=False)
    monkeypatch.delenv("CHAVE_API_REPLICATE", raising=False)
    monkeypatch.delenv("IMAGINEER_KEY_FAL_AI", raising=False)
    obter_configuracoes.cache_clear()
    try:
        assert [p["servidor_fornece"] for p in cliente.get("/configuracao/provedores").json()] == [True, False, False]
    finally:
        monkeypatch.undo()
        obter_configuracoes.cache_clear()


def teste_ct24_a_chave_propria_de_cada_provedor_vale_para_quem_nao_usa_o_servidor(sessao_com_tabelas: Session, chaves_do_servidor) -> None:
    maria = _maria(sessao_com_tabelas)

    sem_nada = construir_provedor(None, maria)
    assert sem_nada._chave_api is None and sem_nada._geradores_de_imagem == {}

    so_fal = construir_provedor(None, maria, chave_fal="fal-da-maria")
    assert set(so_fal._geradores_de_imagem) == {"fal"} and so_fal._geradores_de_imagem["fal"]._chave_api == "fal-da-maria"

    todas = construir_provedor("or-da-maria", maria, "fal-da-maria", "rep-da-maria")
    assert todas._chave_api == "or-da-maria"
    assert {k: g._chave_api for k, g in todas._geradores_de_imagem.items()} == {"fal": "fal-da-maria", "replicate": "rep-da-maria"}


def teste_ct24_a_chave_do_header_tem_precedencia_sobre_a_do_servidor_ate_para_o_dono(sessao_com_tabelas: Session, chaves_do_servidor) -> None:
    dono = sessao_com_tabelas.get(Usuario, 1)

    do_servidor = construir_provedor(None, dono)
    assert do_servidor._geradores_de_imagem["fal"]._chave_api == "fal-do-servidor"

    do_header = construir_provedor(None, dono, chave_fal="  fal-do-header  ")
    assert do_header._geradores_de_imagem["fal"]._chave_api == "fal-do-header"  # sem espaços nas pontas
    assert do_header._geradores_de_imagem["replicate"]._chave_api == "rep-do-servidor"  # as outras seguem no servidor


def teste_ct24_header_vazio_conta_como_ausente(sessao_com_tabelas: Session, chaves_do_servidor) -> None:
    maria = _maria(sessao_com_tabelas)

    provedor = construir_provedor("  ", maria, "", "   ")

    assert provedor._chave_api is None and provedor._geradores_de_imagem == {}


def teste_ct24_a_rota_repassa_os_tres_headers(cliente: TestClient, monkeypatch) -> None:
    """O nome de cada header e a ligação com ``obter_provedor``: um erro de digitação no nome do header passaria despercebido."""
    from imagineer.ia.falso import ProvedorFalso
    from imagineer.rotas import configuracao as rota

    recebidos: list[tuple] = []

    def falso(cabecalho=None, usuario=None, chave_fal=None, chave_replicate=None):
        recebidos.append((cabecalho, chave_fal, chave_replicate))
        return ProvedorFalso()

    monkeypatch.setattr(rota, "construir_provedor", falso)

    cliente.get(
        "/configuracao/modelos",
        headers={"X-Chave-API-OpenRouter": "or", "X-Chave-API-Fal": "fal", "X-Chave-API-Replicate": "rep"},
    )
    cliente.get("/configuracao/modelos")

    assert recebidos == [("or", "fal", "rep"), (None, None, None)]


def teste_ct24_pedir_modelo_de_um_provedor_sem_chave_diz_para_cadastrar_a_sua(sessao_com_tabelas: Session, chaves_do_servidor) -> None:
    from imagineer.ia.provedor import ChaveDeApiAusente

    maria = _maria(sessao_com_tabelas)
    provedor = construir_provedor(None, maria)

    with pytest.raises(ChaveDeApiAusente, match="Cadastre a sua em Configurações"):
        provedor.gerar_imagem("um prompt", "fal:fal-ai/flux/dev")
