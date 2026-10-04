"""Os 10 perfis de renderização de fábrica (PF1 a PF8, item 4.5)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.ia.blocos_tecnicos import BLOCO_TECNICO_POR_CATEGORIA
from imagineer.ia.falso import ProvedorFalso
from imagineer.modelos import CategoriaEstilo, PerfilRenderizacao
from imagineer.servicos.perfis_de_fabrica import PERFIS_DE_FABRICA, garantir_perfis_de_fabrica
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _montar_frame_completo


def _semear(sessao: Session) -> None:
    garantir_perfis_de_fabrica(sessao.connection())
    sessao.commit()


def _de_fabrica(cliente: TestClient, categoria: str) -> dict:
    return next(p for p in cliente.get("/perfis-renderizacao").json() if p["de_fabrica"] and p["categoria_estilo"] == categoria)


# --------------------------------------------------------------------------- #
# Os dados e a semeadura
# --------------------------------------------------------------------------- #


def teste_ha_um_perfil_de_fabrica_para_cada_categoria() -> None:
    assert {p.categoria for p in PERFIS_DE_FABRICA} == set(CategoriaEstilo)
    assert len(PERFIS_DE_FABRICA) == len(CategoriaEstilo) == 10
    assert len({p.nome for p in PERFIS_DE_FABRICA}) == 10


def teste_os_textos_cabem_nas_colunas_e_estao_completos() -> None:
    for p in PERFIS_DE_FABRICA:
        assert p.estilo.strip() and p.iluminacao.strip() and p.paleta.strip(), p.nome
        assert len(p.nome) <= 100 and len(p.iluminacao) <= 200 and len(p.paleta) <= 200, p.nome


def teste_a_semeadura_cria_os_dez_travados_com_a_categoria(sessao_com_tabelas: Session) -> None:
    _semear(sessao_com_tabelas)

    perfis = sessao_com_tabelas.scalars(select(PerfilRenderizacao)).all()
    assert len(perfis) == 10
    assert all(p.de_fabrica for p in perfis)
    assert {p.categoria_estilo for p in perfis} == set(CategoriaEstilo)


def teste_a_semeadura_e_idempotente_e_reescreve_os_textos(sessao_com_tabelas: Session) -> None:
    _semear(sessao_com_tabelas)
    anime = sessao_com_tabelas.scalars(select(PerfilRenderizacao).where(PerfilRenderizacao.categoria_estilo == CategoriaEstilo.ANIME)).one()
    id_antes = anime.id
    anime.estilo = "texto adulterado"
    sessao_com_tabelas.commit()

    _semear(sessao_com_tabelas)
    sessao_com_tabelas.expire_all()

    assert sessao_com_tabelas.scalar(select(func.count()).select_from(PerfilRenderizacao)) == 10
    anime = sessao_com_tabelas.get(PerfilRenderizacao, id_antes)  # o mesmo perfil: quem usa o id não perde o vínculo
    assert anime.estilo != "texto adulterado" and "anime" in anime.estilo.lower()


def teste_perfil_proprio_com_o_mesmo_nome_cede_o_nome(sessao_com_tabelas: Session) -> None:
    sessao_com_tabelas.add(PerfilRenderizacao(nome="Anime", estilo="o meu"))
    sessao_com_tabelas.commit()

    _semear(sessao_com_tabelas)

    nomes = set(sessao_com_tabelas.scalars(select(PerfilRenderizacao.nome)))
    assert {"Anime", "Anime (próprio)"} <= nomes
    proprio = sessao_com_tabelas.scalars(select(PerfilRenderizacao).where(PerfilRenderizacao.nome == "Anime (próprio)")).one()
    assert proprio.de_fabrica is False and proprio.estilo == "o meu"


def teste_a_migracao_encadeia_e_religa_antes_de_apagar() -> None:
    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "d4e5f6a7b8c9_perfis_de_fabrica.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'" in texto
    assert texto.index("UPDATE {tabela} SET") < texto.index("DELETE FROM perfis_renderizacao")  # religa e só então apaga
    assert "garantir_perfis_de_fabrica(conexao)" in texto


# --------------------------------------------------------------------------- #
# A API
# --------------------------------------------------------------------------- #


def teste_a_lista_traz_a_marca_de_fabrica_e_o_bloco_tecnico(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    _semear(sessao_com_tabelas)

    perfis = cliente.get("/perfis-renderizacao").json()

    assert len(perfis) == 10
    for perfil in perfis:
        categoria = CategoriaEstilo(perfil["categoria_estilo"])
        assert perfil["de_fabrica"] is True
        assert perfil["bloco_tecnico"] == BLOCO_TECNICO_POR_CATEGORIA[categoria]


def teste_perfil_proprio_sem_categoria_nao_tem_bloco_e_nao_e_de_fabrica(cliente: TestClient) -> None:
    criado = cliente.post("/perfis-renderizacao", json={"nome": "Meu"}).json()

    assert criado["de_fabrica"] is False
    assert criado["bloco_tecnico"] is None


def teste_o_corpo_nao_consegue_criar_um_perfil_de_fabrica(cliente: TestClient) -> None:
    criado = cliente.post("/perfis-renderizacao", json={"nome": "Esperto", "de_fabrica": True}).json()

    assert criado["de_fabrica"] is False


def teste_perfil_de_fabrica_nao_pode_ser_editado_nem_apagado(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    _semear(sessao_com_tabelas)
    anime = _de_fabrica(cliente, "ANIME")

    editado = cliente.patch(f"/perfis-renderizacao/{anime['id']}", json={"estilo": "óleo"})
    apagado = cliente.delete(f"/perfis-renderizacao/{anime['id']}")

    assert editado.status_code == 403 and "já vem com o Imagineer" in editado.json()["detail"]
    assert apagado.status_code == 403
    assert _de_fabrica(cliente, "ANIME")["estilo"] == anime["estilo"]  # nada mudou


def teste_perfil_proprio_continua_editavel_e_apagavel(cliente: TestClient) -> None:
    proprio = cliente.post("/perfis-renderizacao", json={"nome": "Meu", "categoria_estilo": "ANIME"}).json()

    assert cliente.patch(f"/perfis-renderizacao/{proprio['id']}", json={"estilo": "novo"}).status_code == 200
    assert cliente.delete(f"/perfis-renderizacao/{proprio['id']}").status_code == 204


# --------------------------------------------------------------------------- #
# O prompt
# --------------------------------------------------------------------------- #


def teste_escolher_o_perfil_de_fabrica_basta_para_o_prompt_ganhar_o_bloco(
    cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso
) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    _semear(sessao_com_tabelas)
    gravura = _de_fabrica(cliente, "GRAVURA_CLASSICA")

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json={"perfil_renderizacao_id": gravura["id"]}).json()

    assert corpo["texto"] == f"uma cena {BLOCO_TECNICO_POR_CATEGORIA[CategoriaEstilo.GRAVURA_CLASSICA]}"
