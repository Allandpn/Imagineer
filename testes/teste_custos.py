"""Custos de IA (item 7.5b, CU1 a CU4): o registro com provedor, livro e preço estimado, e `GET /custos`."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from imagineer.ia.provedor import UsoDaChamada
from imagineer.modelos import Livro, UsoDeIA
from imagineer.modelos import Configuracao
from imagineer.servicos import precos_de_imagem
from imagineer.servicos.precos_de_imagem import PrecoDoFal, preco_estimado_da_imagem
from imagineer.servicos.uso_de_ia import gasto_do_livro, gravar_uso


def _criador(sessao: Session) -> sessionmaker:
    return sessionmaker(bind=sessao.get_bind())


def _livro(sessao: Session, titulo: str = "A Guerra") -> Livro:
    livro = Livro(titulo=titulo, nome_arquivo="a.epub", identificador_epub=titulo)
    sessao.add(livro)
    sessao.commit()
    return livro


def _uso(sessao: Session, *, mes: str = "2026-10", **campos) -> None:
    ano, numero = mes.split("-")
    padrao = {"operacao": "prompt", "modelo": "modelo-x", "provedor": "openrouter"}
    sessao.add(UsoDeIA(criado_em=datetime(int(ano), int(numero), 15, tzinfo=timezone.utc), **{**padrao, **campos}))
    sessao.commit()


# --------------------------------------------------------------------------- #
# O registro (CU1 a CU3)
# --------------------------------------------------------------------------- #


def _fal_publica(monkeypatch, precos: dict) -> None:
    """Faz o fal.ai 'publicar' os preços dados (endpoint -> (valor, unidade)), sem rede."""
    monkeypatch.setattr(precos_de_imagem, "_chave_do_fal", lambda: "chave")
    monkeypatch.setattr(
        precos_de_imagem,
        "_get",
        lambda url, params=None, cabecalhos=None: {
            "prices": [
                {"endpoint_id": e, "unit_price": v, "unit": u, "currency": "USD"}
                for (_, e) in (params or [])
                if e in precos
                for v, u in [precos[e]]
            ]
        },
    )


def teste_cu2_imagem_do_fal_sem_custo_informado_e_estimada_pelo_preco_que_o_fal_publica(sessao_com_tabelas: Session, monkeypatch) -> None:
    _fal_publica(monkeypatch, {"fal-ai/flux/dev": (0.025, "megapixels")})

    gravar_uso(UsoDaChamada(operacao="imagem", modelo="fal:fal-ai/flux/dev", provedor="fal"), _criador(sessao_com_tabelas))

    uso = sessao_com_tabelas.query(UsoDeIA).one()
    assert (uso.provedor, uso.custo, uso.estimado) == ("fal", Decimal("0.025"), True)


def teste_pd3_o_preco_informado_pela_pessoa_vale_mais_que_o_do_fal(sessao_com_tabelas: Session, monkeypatch) -> None:
    _fal_publica(monkeypatch, {"fal-ai/flux/dev": (0.025, "megapixels")})
    sessao_com_tabelas.add(Configuracao(precos_informados={"replicate:dono/modelo": "0.04", "fal:fal-ai/flux/dev": "0.031"}))
    sessao_com_tabelas.commit()
    criador = _criador(sessao_com_tabelas)

    gravar_uso(UsoDaChamada(operacao="imagem", modelo="fal:fal-ai/flux/dev", provedor="fal"), criador)
    gravar_uso(UsoDaChamada(operacao="imagem", modelo="replicate:dono/modelo", provedor="replicate"), criador)

    assert [(u.custo, u.estimado) for u in sessao_com_tabelas.query(UsoDeIA).order_by(UsoDeIA.id)] == [(Decimal("0.031"), True), (Decimal("0.04"), True)]


def teste_cu2_sem_preco_do_fornecedor_nem_informado_fica_sem_custo_nunca_zero(sessao_com_tabelas: Session) -> None:
    gravar_uso(UsoDaChamada(operacao="imagem", modelo="replicate:dono/modelo-novo", provedor="replicate"), _criador(sessao_com_tabelas))

    uso = sessao_com_tabelas.query(UsoDeIA).one()
    assert (uso.custo, uso.estimado) == (None, False)


def teste_cu2_custo_informado_pelo_fornecedor_vale_e_nao_e_estimado(sessao_com_tabelas: Session) -> None:
    gravar_uso(
        UsoDaChamada(operacao="imagem", modelo="meta/muse-image", custo=Decimal("0.0123")),
        _criador(sessao_com_tabelas),
    )

    uso = sessao_com_tabelas.query(UsoDeIA).one()
    assert (uso.provedor, uso.custo, uso.estimado) == ("openrouter", Decimal("0.0123"), False)


def teste_cu2_so_imagem_e_estimada_uma_chamada_de_texto_sem_custo_continua_sem(sessao_com_tabelas: Session) -> None:
    gravar_uso(UsoDaChamada(operacao="prompt", modelo="fal:fal-ai/flux/dev"), _criador(sessao_com_tabelas))

    assert sessao_com_tabelas.query(UsoDeIA).one().custo is None


def teste_cu3_o_livro_do_contexto_vai_no_registro_e_fora_dele_fica_sem_livro(sessao_com_tabelas: Session) -> None:
    livro = _livro(sessao_com_tabelas)
    criador = _criador(sessao_com_tabelas)

    with gasto_do_livro(livro.id):
        gravar_uso(UsoDaChamada(operacao="prompt", modelo="m"), criador)
    gravar_uso(UsoDaChamada(operacao="prompt", modelo="m"), criador)

    assert [u.livro_id for u in sessao_com_tabelas.query(UsoDeIA).order_by(UsoDeIA.id)] == [livro.id, None]


def teste_pd1_o_preco_por_imagem_do_fal_conta_os_megapixels_e_outras_unidades_nao_valem() -> None:
    assert PrecoDoFal(Decimal("0.025"), "megapixels").por_imagem() == Decimal("0.0250")
    assert PrecoDoFal(Decimal("0.025"), "megapixels").por_imagem(2.0) == Decimal("0.0500")
    assert PrecoDoFal(Decimal("0.04"), "images").por_imagem(2.0) == Decimal("0.04")
    assert PrecoDoFal(Decimal("0.0007"), "seconds").por_imagem() is None


def teste_pd1_sem_chave_ou_sem_informacao_o_preco_e_nulo() -> None:
    assert preco_estimado_da_imagem(" replicate:dono/x ") is None
    assert preco_estimado_da_imagem("fal:fal-ai/flux/dev") is None  # sem chave do fal no teste
    assert preco_estimado_da_imagem("replicate:dono/x", {"replicate:dono/x": "0.05"}) == Decimal("0.05")
    assert preco_estimado_da_imagem("replicate:dono/x", {"replicate:dono/x": "zero"}) is None
    assert preco_estimado_da_imagem("replicate:dono/x", {"replicate:dono/x": "0"}) is None


def teste_pd1_o_preco_lido_do_fal_fica_guardado_e_a_falha_nao_e_guardada(monkeypatch) -> None:
    chamadas = []
    monkeypatch.setattr(precos_de_imagem, "_chave_do_fal", lambda: "chave")

    def ler(url, params=None, cabecalhos=None):
        chamadas.append(url)
        if len(chamadas) == 1:
            raise precos_de_imagem.httpx.ConnectError("fora")
        return {"prices": [{"endpoint_id": "a/b", "unit_price": 0.01, "unit": "images"}]}

    monkeypatch.setattr(precos_de_imagem, "_get", ler)

    assert precos_de_imagem.precos_do_fal(["a/b"]) == {}  # falhou: nada guardado
    assert precos_de_imagem.precos_do_fal(["a/b"])["a/b"].valor == Decimal("0.01")
    precos_de_imagem.precos_do_fal(["a/b"])
    assert len(chamadas) == 2  # a terceira veio do cache


# --------------------------------------------------------------------------- #
# A rota (CU4)
# --------------------------------------------------------------------------- #


def teste_cu4_soma_o_mes_e_quebra_por_provedor_operacao_livro_e_modelo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro = _livro(sessao_com_tabelas, "A Guerra")
    _uso(sessao_com_tabelas, operacao="prompt", modelo="gemini", custo=Decimal("0.02"), livro_id=livro.id)
    _uso(sessao_com_tabelas, operacao="imagem", modelo="fal:fal-ai/flux/dev", provedor="fal", custo=Decimal("0.025"), estimado=True, livro_id=livro.id)
    _uso(sessao_com_tabelas, operacao="imagem", modelo="replicate:dono/novo", provedor="replicate")  # sem custo, sem livro
    _uso(sessao_com_tabelas, operacao="extracao", modelo="gemini", custo=Decimal("0.005"))

    corpo = cliente.get("/custos", params={"mes": "2026-10"}).json()

    assert corpo["mes"] == "2026-10"
    assert Decimal(corpo["total"]) == Decimal("0.05")
    assert Decimal(corpo["estimado"]) == Decimal("0.025")
    assert (corpo["chamadas"], corpo["sem_custo"]) == (4, 1)
    assert [(g["nome"], Decimal(g["total"])) for g in corpo["por_provedor"]] == [
        ("fal", Decimal("0.025")), ("openrouter", Decimal("0.025")), ("replicate", Decimal("0")),  # empate: pelo nome
    ]
    assert {g["nome"]: g["chamadas"] for g in corpo["por_operacao"]} == {"prompt": 1, "imagem": 2, "extracao": 1}
    por_livro = {g["nome"]: (Decimal(g["total"]), g["livro_id"]) for g in corpo["por_livro"]}
    assert por_livro == {"A Guerra": (Decimal("0.045"), livro.id), "Sem livro": (Decimal("0.005"), None)}
    assert {g["nome"] for g in corpo["por_modelo"]} == {"gemini", "fal:fal-ai/flux/dev", "replicate:dono/novo"}


def teste_cu4_so_entra_o_mes_pedido_e_a_lista_de_meses_mostra_todos(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    _uso(sessao_com_tabelas, mes="2026-09", custo=Decimal("1"))
    _uso(sessao_com_tabelas, mes="2026-10", custo=Decimal("2"))
    _uso(sessao_com_tabelas, mes="2026-12", custo=Decimal("4"))  # dezembro: o fim do mês vira janeiro do ano seguinte

    setembro = cliente.get("/custos", params={"mes": "2026-09"}).json()
    dezembro = cliente.get("/custos", params={"mes": "2026-12"}).json()

    assert Decimal(setembro["total"]) == Decimal("1")
    assert Decimal(dezembro["total"]) == Decimal("4")
    assert setembro["meses_com_gasto"] == ["2026-12", "2026-10", "2026-09"]


def teste_cu4_mes_sem_gasto_devolve_zeros_e_mes_mal_escrito_e_422(cliente: TestClient) -> None:
    vazio = cliente.get("/custos", params={"mes": "2020-01"}).json()

    assert (Decimal(vazio["total"]), vazio["chamadas"], vazio["por_provedor"]) == (Decimal("0"), 0, [])
    assert cliente.get("/custos", params={"mes": "2026-13"}).status_code == 422
    assert cliente.get("/custos", params={"mes": "outubro"}).status_code == 422


def teste_cu4_sem_mes_vale_o_mes_atual(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    agora = datetime.now(timezone.utc)
    sessao_com_tabelas.add(UsoDeIA(operacao="prompt", modelo="m", custo=Decimal("0.5"), criado_em=agora))
    sessao_com_tabelas.commit()

    corpo = cliente.get("/custos").json()

    assert corpo["mes"] == agora.strftime("%Y-%m")
    assert Decimal(corpo["total"]) == Decimal("0.5")
