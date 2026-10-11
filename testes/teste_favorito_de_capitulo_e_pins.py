"""O favorito de CAPÍTULO e a migração dos pins para favoritos de parágrafo (item 7.5g, FV2 e FV4)."""

import importlib.util
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo
from testes.teste_favoritos import PARAGRAFOS, _favoritar, _lista, _livro_com_texto
from testes.teste_lm_migracao_do_uso import RAIZ
from testes.teste_rotas_sugestoes import _livro_com_capitulos

# --------------------------------------------------------------------------- #
# FV2: favoritar o capítulo
# --------------------------------------------------------------------------- #


def teste_favoritar_um_capitulo_devolve_o_rotulo_com_a_ordem_e_o_titulo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)

    criado = _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=capitulo["id"])

    assert criado.status_code == 201, criado.text
    corpo = criado.json()
    assert corpo["tipo"] == "CAPITULO" and corpo["capitulo_id"] == capitulo["id"]
    assert corpo["rotulo"].startswith(f"Capítulo {corpo['ordem_do_capitulo']}")
    assert corpo["posicao"] is None and corpo["elemento_id"] is None and corpo["frame_id"] is None and corpo["imagem_id"] is None


def teste_favoritar_o_mesmo_capitulo_de_novo_devolve_o_que_existe_com_200(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)

    primeira = _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=capitulo["id"])
    segunda = _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=capitulo["id"])

    assert primeira.status_code == 201 and segunda.status_code == 200
    assert segunda.json()["id"] == primeira.json()["id"]
    assert len(_lista(cliente, livro["id"], tipo="CAPITULO")) == 1


def teste_dois_capitulos_sao_dois_favoritos_e_o_filtro_por_tipo_separa_dos_paragrafos(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, primeiro = _livro_com_texto(cliente, sessao_com_tabelas)
    segundo = livro["capitulos"][1]
    _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=primeiro["id"])
    _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=segundo["id"])
    _favoritar(cliente, livro["id"], tipo="PARAGRAFO", capitulo_id=primeiro["id"], posicao=0)

    assert {f["capitulo_id"] for f in _lista(cliente, livro["id"], tipo="CAPITULO")} == {primeiro["id"], segundo["id"]}
    assert len(_lista(cliente, livro["id"], tipo="PARAGRAFO")) == 1
    assert len(_lista(cliente, livro["id"])) == 3


def teste_o_favorito_de_capitulo_nao_leva_posicao_nem_outro_alvo(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)

    assert _favoritar(cliente, livro["id"], tipo="CAPITULO").status_code == 422  # falta o capitulo_id
    assert _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=capitulo["id"], posicao=0).status_code == 422
    assert _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=capitulo["id"], elemento_id=1).status_code == 422


def teste_o_capitulo_de_outro_livro_ou_inexistente_nao_se_favorita(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, _ = _livro_com_texto(cliente, sessao_com_tabelas)
    outro = _livro_com_capitulos(cliente, capitulos=1)

    assert _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=outro["capitulos"][0]["id"]).status_code == 422
    assert _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=99999).status_code in (404, 422)


def teste_desfavoritar_o_capitulo_tira_da_lista(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    livro, capitulo = _livro_com_texto(cliente, sessao_com_tabelas)
    criado = _favoritar(cliente, livro["id"], tipo="CAPITULO", capitulo_id=capitulo["id"]).json()

    assert cliente.delete(f"/favoritos/{criado['id']}").status_code == 204
    assert _lista(cliente, livro["id"], tipo="CAPITULO") == []


# --------------------------------------------------------------------------- #
# FV4: os pins viram favoritos de parágrafo
# --------------------------------------------------------------------------- #


def _migracao():
    arquivo = RAIZ / "migracoes" / "versions" / "d1e2f3a4b5c7_pins_viram_favoritos_de_paragrafo.py"
    especificacao = importlib.util.spec_from_file_location("migracao_d1e2f3a4b5c7", arquivo)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def _banco_com_pins() -> sa.Engine:
    """Um SQLite só com as tabelas que a migração lê e escreve, com um capítulo de dois parágrafos e três pins."""
    motor = sa.create_engine("sqlite://")
    with motor.begin() as c:
        c.execute(sa.text("CREATE TABLE capitulos (id INTEGER PRIMARY KEY, texto TEXT)"))
        c.execute(sa.text(
            "CREATE TABLE pins (id INTEGER PRIMARY KEY, livro_id INTEGER, capitulo_id INTEGER, posicao_no_texto INTEGER, nota VARCHAR(1000), criado_em DATETIME)"
        ))
        c.execute(sa.text(
            "CREATE TABLE favoritos (id INTEGER PRIMARY KEY AUTOINCREMENT, livro_id INTEGER, tipo VARCHAR(12), capitulo_id INTEGER, posicao INTEGER, "
            "trecho TEXT, elemento_id INTEGER, frame_id INTEGER, imagem_id INTEGER, criado_em DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
        c.execute(sa.text("INSERT INTO capitulos (id, texto) VALUES (10, :t)"), {"t": PARAGRAFOS})
        momento = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc).isoformat()
        inicio_do_segundo = len("Primeiro parágrafo do capítulo.\n\n")
        for pin_id, posicao, nota in [(1, 0, None), (2, inicio_do_segundo, "voltar aqui"), (3, 9999, "nota que sobra")]:
            c.execute(
                sa.text("INSERT INTO pins VALUES (:i, 1, 10, :p, :n, :m)"), {"i": pin_id, "p": posicao, "n": nota, "m": momento}
            )
    return motor


def _aplicar(motor: sa.Engine) -> None:
    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        _migracao().aplicar()


def teste_cada_pin_vira_um_favorito_de_paragrafo_no_mesmo_lugar_com_o_trecho_calculado() -> None:
    motor = _banco_com_pins()

    _aplicar(motor)

    with motor.connect() as c:
        linhas = c.execute(sa.text("SELECT livro_id, tipo, capitulo_id, posicao, trecho FROM favoritos ORDER BY posicao")).all()
    assert [(l.tipo, l.capitulo_id, l.posicao) for l in linhas][:2] == [("PARAGRAFO", 10, 0), ("PARAGRAFO", 10, len("Primeiro parágrafo do capítulo.\n\n"))]
    assert linhas[0].trecho == "Primeiro parágrafo do capítulo."
    assert linhas[1].trecho == "Segundo parágrafo, mais longo, com quebra de linha dentro dele."  # a quebra de linha vira espaço
    assert len(linhas) == 3


def teste_a_posicao_que_nao_tem_texto_usa_a_nota_do_pin_como_trecho() -> None:
    motor = _banco_com_pins()

    _aplicar(motor)

    with motor.connect() as c:
        assert c.execute(sa.text("SELECT trecho FROM favoritos WHERE posicao = 9999")).scalar_one() == "nota que sobra"


def teste_o_paragrafo_que_ja_era_favorito_nao_e_duplicado() -> None:
    motor = _banco_com_pins()
    with motor.begin() as c:
        c.execute(sa.text("INSERT INTO favoritos (livro_id, tipo, capitulo_id, posicao, trecho) VALUES (1, 'PARAGRAFO', 10, 0, 'Primeiro parágrafo do capítulo.')"))

    _aplicar(motor)

    with motor.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM favoritos WHERE posicao = 0")).scalar_one() == 1
        assert c.execute(sa.text("SELECT COUNT(*) FROM favoritos")).scalar_one() == 3  # o antigo + os 2 pins que faltavam


def teste_aplicar_duas_vezes_nao_duplica_nada() -> None:
    motor = _banco_com_pins()

    _aplicar(motor)
    _aplicar(motor)

    with motor.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM favoritos")).scalar_one() == 3


def teste_os_pins_continuam_na_tabela_e_reverter_nao_apaga_nada() -> None:
    motor = _banco_com_pins()
    _aplicar(motor)

    with motor.begin() as conexao, Operations.context(MigrationContext.configure(conexao)):
        _migracao().reverter()

    with motor.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM pins")).scalar_one() == 3
        assert c.execute(sa.text("SELECT COUNT(*) FROM favoritos")).scalar_one() == 3


def teste_sem_pins_a_migracao_nao_faz_nada() -> None:
    motor = _banco_com_pins()
    with motor.begin() as c:
        c.execute(sa.text("DELETE FROM pins"))

    _aplicar(motor)

    with motor.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM favoritos")).scalar_one() == 0


def teste_o_pin_guarda_o_momento_em_que_foi_marcado() -> None:
    motor = _banco_com_pins()

    _aplicar(motor)

    with motor.connect() as c:
        assert str(c.execute(sa.text("SELECT criado_em FROM favoritos WHERE posicao = 0")).scalar_one()).startswith("2026-10-01")


def teste_a_migracao_vem_depois_da_do_modelo_de_conferencia_e_e_a_unica_cabeca() -> None:
    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)

    assert diretorio.get_revision("d1e2f3a4b5c7").down_revision == "c0d1e2f3a4b6"
    assert diretorio.get_heads() == ["d1e2f3a4b5c7"]
