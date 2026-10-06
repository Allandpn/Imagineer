"""As contas de usuário (itens CT1 a CT14): identidade do pedido, isolamento entre pessoas, chaves e custos por pessoa."""

import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imagineer.configuracao import obter_configuracoes
from imagineer.ia.provedor import UsoDaChamada
from imagineer.modelos import (
    DONO_ID,
    Capitulo,
    Configuracao,
    Destaque,
    Elemento,
    EstadoElemento,
    Favorito,
    Frame,
    Imagem,
    Livro,
    PerfilRenderizacao,
    Pin,
    Prompt,
    UsoDeIA,
    Usuario,
)
from imagineer.principal import aplicacao
from imagineer.servicos.acesso import buscar_visivel, definir_usuario, livro_id_de, pertence
from imagineer.servicos.configuracao_ia import construir_provedor, obter_ou_criar, resolver_chave
from imagineer.servicos.identidade import origem_confiavel, redes_confiaveis, resolver_usuario
from imagineer.servicos.uso_de_ia import gravar_uso
from testes.teste_imagem_canonica import _retrato_com_duas_imagens
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)

# --------------------------------------------------------------------------- #
# Identidade do pedido (CT2 a CT4)
# --------------------------------------------------------------------------- #


@pytest.fixture
def modo(monkeypatch):
    """Troca o modo de autenticação pelo ambiente (as configurações são lidas uma vez só, então limpa o cache antes e depois)."""

    def definir(autenticacao: str, dono: str = "", proxies: str | None = None) -> None:
        monkeypatch.setenv("IMAGINEER_AUTENTICACAO", autenticacao)
        monkeypatch.setenv("IMAGINEER_DONO", dono)
        if proxies is not None:
            monkeypatch.setenv("IMAGINEER_PROXIES_CONFIAVEIS", proxies)
        obter_configuracoes.cache_clear()

    try:
        yield definir
    finally:
        monkeypatch.undo()
        obter_configuracoes.cache_clear()


def _pedido(ip: str | None = "127.0.0.1", **cabecalhos: str) -> SimpleNamespace:
    """Um pedido de mentira: só o que ``resolver_usuario`` lê (endereço de quem chamou e cabeçalhos)."""
    return SimpleNamespace(client=SimpleNamespace(host=ip) if ip else None, headers={k.replace("_", "-"): v for k, v in cabecalhos.items()})


def _criador(sessao: Session) -> sessionmaker:
    return sessionmaker(bind=sessao.get_bind(), expire_on_commit=False)


def teste_ct2_modo_pessoal_ignora_o_cabecalho_e_devolve_o_dono(sessao_com_tabelas: Session, modo) -> None:
    modo("pessoal")

    usuario = resolver_usuario(_pedido("8.8.8.8", tailscale_user_login="intruso@x.com"), _criador(sessao_com_tabelas))

    assert usuario.id == DONO_ID and usuario.dono


def teste_ct4_o_dono_reivindica_a_conta_1_no_primeiro_pedido(sessao_com_tabelas: Session, modo) -> None:
    modo("tailscale", dono="Allan@Exemplo.com")

    usuario = resolver_usuario(_pedido(tailscale_user_login="allan@exemplo.com", tailscale_user_name="Allan"), _criador(sessao_com_tabelas))

    assert usuario.id == DONO_ID and usuario.login == "allan@exemplo.com"
    assert sessao_com_tabelas.scalar(select(Usuario.id).where(Usuario.login == "allan@exemplo.com")) == DONO_ID


def teste_ct4_outra_pessoa_ganha_conta_propria_sem_chaves_do_servidor(sessao_com_tabelas: Session, modo) -> None:
    modo("tailscale", dono="allan@exemplo.com")
    criador = _criador(sessao_com_tabelas)

    maria = resolver_usuario(_pedido(tailscale_user_login="Maria@Exemplo.com", tailscale_user_name="Maria"), criador)
    de_novo = resolver_usuario(_pedido(tailscale_user_login="maria@exemplo.com"), criador)

    assert maria.id != DONO_ID and not maria.dono and not maria.usa_chaves_do_servidor
    assert de_novo.id == maria.id  # mesma pessoa, mesma conta (o login é comparado em minúsculas)
    assert sessao_com_tabelas.query(Usuario).count() == 2


def teste_ct3_sem_cabecalho_ou_de_fora_do_proxy_confiavel_e_401(sessao_com_tabelas: Session, modo) -> None:
    modo("tailscale", dono="allan@exemplo.com")
    criador = _criador(sessao_com_tabelas)

    for pedido in (
        _pedido(),  # do proxy, mas sem a identidade
        _pedido("8.8.8.8", tailscale_user_login="allan@exemplo.com"),  # alguém tentando falsificar o cabeçalho
        _pedido("100.64.0.7", tailscale_user_login="allan@exemplo.com"),  # direto da tailnet, sem passar pelo `serve`
        _pedido(None, tailscale_user_login="allan@exemplo.com"),  # sem endereço
    ):
        with pytest.raises(HTTPException) as erro:
            resolver_usuario(pedido, criador)
        assert erro.value.status_code == 401
    assert sessao_com_tabelas.query(Usuario).count() == 1  # ninguém foi criado


def teste_ct3_faixa_cidr_do_docker_e_aceita(sessao_com_tabelas: Session, modo) -> None:
    modo("tailscale", dono="allan@exemplo.com", proxies="172.16.0.0/12")

    usuario = resolver_usuario(_pedido("172.18.0.1", tailscale_user_login="allan@exemplo.com"), _criador(sessao_com_tabelas))

    assert usuario.id == DONO_ID
    with pytest.raises(HTTPException):
        resolver_usuario(_pedido("127.0.0.1", tailscale_user_login="allan@exemplo.com"), _criador(sessao_com_tabelas))


def teste_ct3_origem_confiavel_e_redes() -> None:
    assert origem_confiavel("127.0.0.1", "127.0.0.1,::1") and origem_confiavel("::1", "127.0.0.1,::1")
    assert not origem_confiavel("testclient", "127.0.0.1") and not origem_confiavel(None, "127.0.0.1")
    assert not origem_confiavel("::1", "127.0.0.1")  # versões diferentes não se comparam
    with pytest.raises(ValueError, match="CIDR"):
        redes_confiaveis("127.0.0.1, banana")


def teste_ct4_modo_tailscale_sem_dono_nao_sobe(monkeypatch) -> None:
    monkeypatch.setenv("IMAGINEER_AUTENTICACAO", "tailscale")
    monkeypatch.setenv("IMAGINEER_DONO", " ")
    obter_configuracoes.cache_clear()
    try:
        with pytest.raises(ValueError, match="IMAGINEER_DONO"):
            obter_configuracoes()
    finally:
        monkeypatch.undo()
        obter_configuracoes.cache_clear()


def teste_ct12_eu_devolve_o_usuario_do_pedido(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    assert cliente.get("/eu").json() == {"id": DONO_ID, "login": None, "nome": "Dono", "dono": True, "usa_chaves_do_servidor": True}

    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    definir_usuario(sessao_com_tabelas, maria.id)

    assert cliente.get("/eu").json()["id"] == maria.id and cliente.get("/eu").json()["dono"] is False


def teste_ct2_na_aplicacao_o_modo_tailscale_recusa_pedido_sem_identidade(sessao_com_tabelas: Session, modo) -> None:
    """Fim a fim, sem trocar ``obter_usuario``: o TestClient não vem de um proxy confiável, então tudo é 401 (menos ``/saude``)."""
    modo("tailscale", dono="allan@exemplo.com")
    aplicacao.dependency_overrides.clear()
    try:
        cliente = TestClient(aplicacao)
        assert cliente.get("/livros", headers={"Tailscale-User-Login": "allan@exemplo.com"}).status_code == 401
        assert cliente.get("/eu").status_code == 401
        assert cliente.get("/saude").status_code == 200
    finally:
        aplicacao.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Isolamento (CT5, CT6)
# --------------------------------------------------------------------------- #


def _pessoa(sessao: Session, login: str, servidor: bool = False) -> Usuario:
    pessoa = Usuario(login=login, nome=login.split("@")[0], usa_chaves_do_servidor=servidor)
    sessao.add(pessoa)
    sessao.commit()
    return pessoa


def _como(sessao: Session, usuario_id: int) -> None:
    definir_usuario(sessao, usuario_id)


def _cenario_do_dono(cliente: TestClient, sessao: Session, usar_provedor_falso) -> dict:
    """O dono com uma cadeia completa: livro, capítulo, elemento, estado, cena, prompt, imagem, pin, destaque, favorito e perfil."""
    capitulo, elementos, retrato, imagem, _ = _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    livro_id = sessao.get(Capitulo, capitulo["id"]).livro_id
    elemento = elementos["criatura"]
    pin = cliente.post(f"/livros/{livro_id}/pins", json={"capitulo_id": capitulo["id"], "posicao_no_texto": 0})
    destaque = cliente.post(f"/livros/{livro_id}/destaques", json={"capitulo_id": capitulo["id"], "inicio": 0, "fim": 3})
    favorito = cliente.post(f"/livros/{livro_id}/favoritos", json={"tipo": "LIVRO"})
    perfil = cliente.post("/perfis-renderizacao", json={"nome": "Meu perfil", "categoria_estilo": "ANIME", "estilo": "x"})
    assert (pin.status_code, destaque.status_code, favorito.status_code) == (201, 201, 201), (pin.text, destaque.text, favorito.text)
    assert perfil.status_code == 201, perfil.text
    return {
        "livro_id": livro_id,
        "capitulo_id": capitulo["id"],
        "elemento_id": elemento["id"],
        "estado_id": elemento["estado_id"],
        "frame_id": retrato["id"],
        "prompt_id": imagem["prompt_id"],
        "imagem_id": imagem["id"],
        "pin_id": pin.json()["id"],
        "destaque_id": destaque.json()["id"],
        "favorito_id": favorito.json()["id"],
        "perfil_id": perfil.json()["id"],
    }


def teste_ct5_o_dono_de_tudo_e_o_dono_do_livro(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    ids = _cenario_do_dono(cliente, sessao_com_tabelas, usar_provedor_falso)
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    sessao = sessao_com_tabelas

    objetos = [
        sessao.get(Livro, ids["livro_id"]),
        sessao.get(Capitulo, ids["capitulo_id"]),
        sessao.get(Elemento, ids["elemento_id"]),
        sessao.get(EstadoElemento, ids["estado_id"]),
        sessao.get(Frame, ids["frame_id"]),
        sessao.get(Prompt, ids["prompt_id"]),
        sessao.get(Imagem, ids["imagem_id"]),
        sessao.get(Pin, ids["pin_id"]),
        sessao.get(Destaque, ids["destaque_id"]),
        sessao.get(Favorito, ids["favorito_id"]),
    ]
    assert all(o is not None and livro_id_de(sessao, o) == ids["livro_id"] for o in objetos)
    assert all(pertence(sessao, o) for o in objetos)

    _como(sessao, maria.id)
    assert not any(pertence(sessao, o) for o in objetos)
    assert buscar_visivel(sessao, Livro, ids["livro_id"]) is None


def teste_ct5_tipo_desconhecido_e_negado_para_quem_tem_escopo(sessao_com_tabelas: Session) -> None:
    """Falha fechada: um objeto que ``livro_id_de`` não sabe ligar a um livro não aparece para ninguém com escopo."""
    assert pertence(sessao_com_tabelas, object()) is False
    definir_usuario(sessao_com_tabelas, None)
    assert pertence(sessao_com_tabelas, object()) is True  # sem escopo (segundo plano, testes antigos): tudo vale


_PARAMETROS = {
    "livro_id": "livro_id",
    "capitulo_id": "capitulo_id",
    "elemento_id": "elemento_id",
    "estado_id": "estado_id",
    "frame_id": "frame_id",
    "prompt_id": "prompt_id",
    "imagem_id": "imagem_id",
    "pin_id": "pin_id",
    "destaque_id": "destaque_id",
    "favorito_id": "favorito_id",
    "perfil_id": "perfil_id",
}
_SEM_ID_DO_CENARIO = {"/eu", "/saude"}


def teste_ct6_nenhuma_rota_com_id_deixa_outra_pessoa_ver_ou_mexer(
    cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso
) -> None:
    """Percorre **todas** as rotas com id do OpenAPI como outra pessoa: GET e DELETE têm que dar 404; as que levam corpo, nunca 2xx.

    Uma rota nova com id de livro/capítulo/etc. entra aqui sozinha: se esquecer a conferência do dono, este teste quebra."""
    ids = _cenario_do_dono(cliente, sessao_com_tabelas, usar_provedor_falso)
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    _como(sessao_com_tabelas, maria.id)

    cobertas = 0
    for caminho, metodos in aplicacao.openapi()["paths"].items():
        nomes = re.findall(r"{(\w+)}", caminho)
        if not nomes:
            continue
        desconhecidos = [n for n in nomes if n not in _PARAMETROS]
        if desconhecidos:
            continue  # sem id no cenário (sugestões, acréscimos de identidade...): coberto pelos testes de cadeia abaixo
        url = caminho.format(**{n: ids[_PARAMETROS[n]] for n in nomes})
        # Parâmetros de consulta obrigatórios (ex.: `nome`) recebem um valor qualquer, para o pedido chegar à conferência do dono.
        obrigatorios = {
            p["name"]: 1 if p.get("schema", {}).get("type") == "integer" else "x"
            for metodo_ in metodos.values()
            for p in metodo_.get("parameters", [])
            if p["in"] == "query" and p.get("required")
        }
        for metodo in metodos:
            if metodo in ("get", "delete"):
                resposta = cliente.request(metodo.upper(), url, params=obrigatorios)
                assert resposta.status_code == 404, f"{metodo.upper()} {caminho} deixou outra pessoa passar: {resposta.status_code} {resposta.text[:200]}"
            else:
                resposta = cliente.request(metodo.upper(), url, params=obrigatorios, json={})
                assert resposta.status_code in (404, 405, 422), f"{metodo.upper()} {caminho}: {resposta.status_code} {resposta.text[:200]}"
            cobertas += 1
    assert cobertas > 40  # a varredura realmente passou por rotas

    # E nada do dono foi tocado.
    _como(sessao_com_tabelas, DONO_ID)
    assert cliente.get(f"/livros/{ids['livro_id']}").status_code == 200
    assert cliente.get(f"/prompts/{ids['prompt_id']}").status_code == 200
    assert cliente.get(f"/imagens/{ids['imagem_id']}/arquivo").status_code == 200


def teste_ct6_corpos_com_ids_de_outra_pessoa_sao_recusados(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    """Ids que vão no **corpo** (e não no caminho) também passam pela conferência: Maria no livro dela não referencia coisas do dono."""
    ids = _cenario_do_dono(cliente, sessao_com_tabelas, usar_provedor_falso)
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    _como(sessao_com_tabelas, maria.id)
    livro_dela = Livro(titulo="Dela", usuario_id=maria.id, nome_arquivo="dela.epub")
    sessao_com_tabelas.add(livro_dela)
    sessao_com_tabelas.commit()

    pin = cliente.post(f"/livros/{livro_dela.id}/pins", json={"capitulo_id": ids["capitulo_id"], "posicao_no_texto": 0})
    destaque = cliente.post(f"/livros/{livro_dela.id}/destaques", json={"capitulo_id": ids["capitulo_id"], "inicio": 0, "fim": 2})
    favorito = cliente.post(f"/livros/{livro_dela.id}/favoritos", json={"tipo": "ELEMENTO", "elemento_id": ids["elemento_id"]})
    favorito_imagem = cliente.post(f"/livros/{livro_dela.id}/favoritos", json={"tipo": "IMAGEM", "imagem_id": ids["imagem_id"]})

    for resposta in (pin, destaque, favorito, favorito_imagem):
        assert resposta.status_code in (404, 422), resposta.text
    assert sessao_com_tabelas.query(Pin).filter_by(livro_id=livro_dela.id).count() == 0


def teste_ct6_listagens_de_outra_pessoa_vem_vazias(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    ids = _cenario_do_dono(cliente, sessao_com_tabelas, usar_provedor_falso)
    assert cliente.get("/livros").json()  # o dono vê o livro dele
    assert cliente.delete(f"/imagens/{ids['imagem_id']}").status_code == 204  # e a lixeira dele tem uma imagem

    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    _como(sessao_com_tabelas, maria.id)

    assert cliente.get("/livros").json() == []
    assert cliente.get("/lixeira/imagens").json() == {"imagens": [], "total_em_bytes": 0}
    for lixeira in ("livros", "frames", "elementos"):
        corpo = cliente.get(f"/lixeira/{lixeira}").json()
        assert not corpo.get(lixeira, corpo if isinstance(corpo, list) else []), lixeira
    assert cliente.get("/busca", params={"q": "a"}).status_code in (200, 422)
    custos = cliente.get("/custos").json()
    assert not custos.get("gastos") and not custos.get("por_livro")


def teste_ct6_esvaziar_a_lixeira_so_apaga_a_da_propria_pessoa(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    ids = _cenario_do_dono(cliente, sessao_com_tabelas, usar_provedor_falso)
    assert cliente.delete(f"/imagens/{ids['imagem_id']}").status_code == 204
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")

    _como(sessao_com_tabelas, maria.id)
    for lixeira in ("imagens", "livros", "frames", "elementos"):
        assert cliente.delete(f"/lixeira/{lixeira}").status_code in (200, 204)

    _como(sessao_com_tabelas, DONO_ID)
    assert [i["id"] for i in cliente.get("/lixeira/imagens").json()["imagens"]] == [ids["imagem_id"]]
    assert sessao_com_tabelas.get(Livro, ids["livro_id"]) is not None


def teste_ct6_importar_o_mesmo_livro_nao_acusa_duplicado_para_outra_pessoa(sessao_com_tabelas: Session) -> None:
    from imagineer.servicos.importacao_epub import livros_com_mesmo_identificador

    sessao_com_tabelas.add(Livro(titulo="Do dono", identificador_epub="urn:isbn:1", nome_arquivo="a.epub", usuario_id=DONO_ID))
    sessao_com_tabelas.commit()
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")

    assert len(livros_com_mesmo_identificador(sessao_com_tabelas, "urn:isbn:1")) == 1
    _como(sessao_com_tabelas, maria.id)
    assert livros_com_mesmo_identificador(sessao_com_tabelas, "urn:isbn:1") == []


def teste_ct7_perfil_de_fabrica_e_de_todos_e_o_proprio_so_do_criador(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    sessao_com_tabelas.add(PerfilRenderizacao(nome="Fábrica", de_fabrica=True, usuario_id=None, categoria_estilo="ANIME", estilo="x"))
    sessao_com_tabelas.commit()
    dono_perfil = cliente.post("/perfis-renderizacao", json={"nome": "Igual", "categoria_estilo": "ANIME", "estilo": "x"})
    assert dono_perfil.status_code == 201
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    _como(sessao_com_tabelas, maria.id)

    nomes = [p["nome"] for p in cliente.get("/perfis-renderizacao").json()]
    assert nomes == ["Fábrica"]  # o de fábrica aparece, o do dono não
    assert cliente.get(f"/perfis-renderizacao/{dono_perfil.json()['id']}").status_code == 404
    # O nome é único **por pessoa**: Maria pode ter um "Igual" também.
    assert cliente.post("/perfis-renderizacao", json={"nome": "Igual", "categoria_estilo": "ANIME", "estilo": "y"}).status_code == 201
    # E o de fábrica é travado para todos, inclusive para ela.
    fabrica = sessao_com_tabelas.scalar(select(PerfilRenderizacao.id).where(PerfilRenderizacao.nome == "Fábrica"))
    assert cliente.delete(f"/perfis-renderizacao/{fabrica}").status_code in (403, 409, 422)


# --------------------------------------------------------------------------- #
# Configuração, chaves e custos por pessoa (CT7, CT9, CT10)
# --------------------------------------------------------------------------- #


def teste_ct8_cada_pessoa_tem_a_propria_configuracao(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    assert cliente.put("/configuracao", json={"modelo_prompt": "do/dono"}).status_code == 200
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    _como(sessao_com_tabelas, maria.id)

    assert cliente.get("/configuracao").json()["modelo_prompt"] is None  # a dela nasce vazia
    assert cliente.put("/configuracao", json={"modelo_prompt": "da/maria"}).json()["modelo_prompt"] == "da/maria"

    _como(sessao_com_tabelas, DONO_ID)
    assert cliente.get("/configuracao").json()["modelo_prompt"] == "do/dono"
    assert {c.id for c in sessao_com_tabelas.query(Configuracao)} == {DONO_ID, maria.id}


def teste_ct8_sessao_sem_usuario_usa_a_configuracao_do_dono(sessao_com_tabelas: Session) -> None:
    definir_usuario(sessao_com_tabelas, None)
    assert obter_ou_criar(sessao_com_tabelas).id == DONO_ID


def teste_ct9_chave_do_servidor_so_para_quem_pode_usar(monkeypatch, sessao_com_tabelas: Session) -> None:
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-servidor")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8-do-servidor")
    obter_configuracoes.cache_clear()
    try:
        dono = sessao_com_tabelas.get(Usuario, DONO_ID)
        maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")

        assert resolver_chave(None, dono).origem == "ambiente"
        assert resolver_chave(None, maria).origem == "ausente"
        assert resolver_chave("sk-dela", maria).origem == "cabecalho"  # a chave dela, pelo header, vale
        assert resolver_chave(None).origem == "ambiente"  # sem usuário = como antes das contas

        assert construir_provedor(None, maria)._chave_api is None
        assert construir_provedor("sk-dela", maria)._chave_api == "sk-dela"
        assert construir_provedor(None, maria)._geradores_de_imagem == {}  # fal e Replicate são do dono
        assert "replicate" in construir_provedor(None, dono)._geradores_de_imagem
    finally:
        monkeypatch.undo()
        obter_configuracoes.cache_clear()


def teste_ct9_a_configuracao_nao_diz_que_ha_chave_do_servidor_para_quem_nao_pode_usar(
    cliente: TestClient, sessao_com_tabelas: Session, monkeypatch
) -> None:
    monkeypatch.setenv("CHAVE_API_OPENROUTER", "sk-do-servidor")
    monkeypatch.setenv("FAL_KEY", "fal-do-servidor")
    obter_configuracoes.cache_clear()
    try:
        dono = cliente.get("/configuracao").json()
        assert dono["tem_chave_api"] and dono["origem_da_chave"] == "ambiente" and dono["fornecedores_de_imagem"]["fal"]

        _como(sessao_com_tabelas, _pessoa(sessao_com_tabelas, "maria@exemplo.com").id)
        maria = cliente.get("/configuracao").json()
        assert not maria["tem_chave_api"] and maria["origem_da_chave"] == "ausente"
        assert maria["fornecedores_de_imagem"] == {"openrouter": False, "fal": False, "replicate": False}
    finally:
        monkeypatch.undo()
        obter_configuracoes.cache_clear()


def teste_ct10_o_gasto_fica_no_nome_de_quem_gastou(sessao_com_tabelas: Session, cliente: TestClient) -> None:
    criador = _criador(sessao_com_tabelas)
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")

    gravar_uso(UsoDaChamada(operacao="prompt", modelo="m", custo=1), criador, usuario_id=maria.id)
    gravar_uso(UsoDaChamada(operacao="prompt", modelo="m", custo=2), criador, usuario_id=DONO_ID)
    gravar_uso(UsoDaChamada(operacao="prompt", modelo="m", custo=4), criador)  # sem dono informado = do dono

    assert sorted(u.usuario_id or 0 for u in sessao_com_tabelas.query(UsoDeIA)) == [0, DONO_ID, maria.id]
    assert construir_provedor("k", maria)._ao_usar.keywords == {"usuario_id": maria.id}
    assert construir_provedor("k")._ao_usar is gravar_uso

    _como(sessao_com_tabelas, maria.id)
    assert str(cliente.get("/custos").json()).count("1") >= 1
    from imagineer.servicos.acesso import gastos_da_pessoa

    assert [float(u.custo) for u in sessao_com_tabelas.scalars(select(UsoDeIA).where(gastos_da_pessoa(sessao_com_tabelas)))] == [1.0]
    _como(sessao_com_tabelas, DONO_ID)
    assert sorted(float(u.custo) for u in sessao_com_tabelas.scalars(select(UsoDeIA).where(gastos_da_pessoa(sessao_com_tabelas)))) == [2.0, 4.0]


def teste_ct6_imagem_de_outra_pessoa_nao_serve_de_referencia(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    """Se servisse, a imagem do dono seguiria para o provedor de IA e reapareceria na imagem gerada por outra pessoa."""
    from testes.teste_rotas_prompts import MODELO_COM_REFERENCIA, _cena_com_referencia, _imagem_importada

    _, _, cena, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    do_dono = _imagem_importada(cliente, prompt["id"])
    maria = _pessoa(sessao_com_tabelas, "maria@exemplo.com")
    _como(sessao_com_tabelas, maria.id)

    # A cena nem é dela (404); e, na geração, um prompt dela não aceitaria o id (a conferência está na busca da referência).
    assert cliente.put(f"/frames/{cena['id']}/referencias", json={"imagens_ids": [do_dono["id"]]}).status_code == 404
    from imagineer.servicos.geracao_de_imagem import ReferenciasNaoPermitidas, _preparar_referencias

    configuracao = obter_ou_criar(sessao_com_tabelas)
    configuracao.modelos_com_referencia = {MODELO_COM_REFERENCIA: "image_input"}
    with pytest.raises(ReferenciasNaoPermitidas, match="Não existe imagem"):
        _preparar_referencias(sessao_com_tabelas, configuracao, MODELO_COM_REFERENCIA, [do_dono["id"]])


def teste_ct6_estatisticas_de_leitura_so_somam_a_propria_pessoa(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    """Sem id na URL, a varredura de rotas não pega esta: o tempo e os títulos de outra pessoa não podem entrar na soma."""
    dono_livro = Livro(titulo="Do dono", nome_arquivo="a.epub", usuario_id=DONO_ID)
    sessao_com_tabelas.add(dono_livro)
    sessao_com_tabelas.commit()
    assert cliente.post(f"/livros/{dono_livro.id}/leitura/tempo", json={"dia": "2026-10-06", "segundos": 60}).status_code in (200, 201)

    _como(sessao_com_tabelas, _pessoa(sessao_com_tabelas, "maria@exemplo.com").id)
    assert cliente.get("/estatisticas/leitura").json() == {"dias": [], "livros": []}

    _como(sessao_com_tabelas, DONO_ID)
    assert [l["titulo"] for l in cliente.get("/estatisticas/leitura").json()["livros"]] == ["Do dono"]
