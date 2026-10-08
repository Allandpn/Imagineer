"""A migração dos tokens de cache e de raciocínio em ``usos_ia`` (item 4.10, LM7; etapa E2).

O critério completo da especificação (``alembic upgrade head``, ``downgrade -1``, ``upgrade head`` e ``alembic check`` num PostgreSQL de
verdade) é feito à mão. Este teste cobre o que dá para automatizar sem o PostgreSQL: **executa** ``aplicar`` e ``reverter`` de verdade
(num SQLite) e confere que a corrente de revisões do Alembic tem uma cabeça só.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from alembic.config import Config

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "migracoes" / "versions" / "e6f7a8b9c0d2_cache_e_raciocinio_no_uso_de_ia.py"


def _carregar_migracao():
    especificacao = importlib.util.spec_from_file_location("migracao_e6f7a8b9c0d2", ARQUIVO)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def _colunas(motor: sa.Engine) -> set[str]:
    return {coluna["name"] for coluna in sa.inspect(motor).get_columns("usos_ia")}


@pytest.fixture
def motor_com_usos_antigos() -> sa.Engine:
    """Um banco com a tabela ``usos_ia`` como era antes da migração, e uma linha antiga."""
    motor = sa.create_engine("sqlite://")
    with motor.begin() as conexao:
        conexao.execute(sa.text("CREATE TABLE usos_ia (id INTEGER PRIMARY KEY, operacao VARCHAR(40), modelo VARCHAR(200))"))
        conexao.execute(sa.text("INSERT INTO usos_ia (operacao, modelo) VALUES ('estado', 'm')"))
    return motor


def teste_lm7_a_migracao_adiciona_as_duas_colunas_nulas_e_nao_mexe_nas_linhas_antigas(motor_com_usos_antigos: sa.Engine) -> None:
    migracao = _carregar_migracao()

    with motor_com_usos_antigos.begin() as conexao:
        with Operations.context(MigrationContext.configure(conexao)):
            migracao.aplicar()

    assert {"tokens_em_cache", "tokens_de_raciocinio"} <= _colunas(motor_com_usos_antigos)
    with motor_com_usos_antigos.connect() as conexao:
        linha = conexao.execute(sa.text("SELECT operacao, tokens_em_cache, tokens_de_raciocinio FROM usos_ia")).one()
    assert tuple(linha) == ("estado", None, None)  # linha antiga: nulo, nunca zero


def teste_lm7_reverter_tira_as_colunas_e_guarda_o_resto(motor_com_usos_antigos: sa.Engine) -> None:
    migracao = _carregar_migracao()
    with motor_com_usos_antigos.begin() as conexao:
        with Operations.context(MigrationContext.configure(conexao)):
            migracao.aplicar()
    with motor_com_usos_antigos.begin() as conexao:
        with Operations.context(MigrationContext.configure(conexao)):
            migracao.reverter()

    assert _colunas(motor_com_usos_antigos) == {"id", "operacao", "modelo"}
    with motor_com_usos_antigos.connect() as conexao:
        assert conexao.execute(sa.text("SELECT COUNT(*) FROM usos_ia")).scalar() == 1


def teste_lm7_upgrade_e_downgrade_sao_os_nomes_que_o_alembic_procura() -> None:
    migracao = _carregar_migracao()

    assert migracao.upgrade is migracao.aplicar
    assert migracao.downgrade is migracao.reverter


def teste_lm7_a_corrente_de_revisoes_tem_uma_cabeca_so_e_a_migracao_vem_depois_da_d4e5f6a7b8c0() -> None:
    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    diretorio = ScriptDirectory.from_config(configuracao)

    assert len(diretorio.get_heads()) == 1  # duas cabeças = duas migrações paralelas, que o ``upgrade head`` recusa
    assert diretorio.get_revision("e6f7a8b9c0d2").down_revision == "d4e5f6a7b8c0"
