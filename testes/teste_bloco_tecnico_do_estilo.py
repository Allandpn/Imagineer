"""O bloco técnico fixo por categoria de estilo (BT1 a BT8, item 4.5)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import blocos_tecnicos
from imagineer.ia.blocos_tecnicos import BLOCO_TECNICO_POR_CATEGORIA, com_bloco_tecnico
from imagineer.ia.falso import ProvedorFalso
from imagineer.modelos import CategoriaEstilo, PerfilRenderizacao
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _montar_frame_completo


# --------------------------------------------------------------------------- #
# O catálogo de blocos
# --------------------------------------------------------------------------- #


def teste_toda_categoria_tem_um_bloco() -> None:
    assert set(BLOCO_TECNICO_POR_CATEGORIA) == set(CategoriaEstilo)
    assert len(CategoriaEstilo) == 10  # as 6 de antes e ANIME, PIXEL_ART, GRAVURA_CLASSICA e ANIMACAO_3D


@pytest.mark.parametrize("categoria", list(CategoriaEstilo))
def teste_todo_bloco_segue_o_molde_validado(categoria: CategoriaEstilo) -> None:
    bloco = BLOCO_TECNICO_POR_CATEGORIA[categoria]

    assert bloco.endswith("no signature, no text.")  # o Gemini assinou um quadro sem isto
    assert "never" in bloco or "no " in bloco  # diz o que o estilo nunca é
    assert not any(c in bloco.lower() for c in "áéíóúãõçâêô")  # é inglês, para o modelo de imagem


def teste_nenhum_bloco_cita_estudio_ou_artista() -> None:
    proibidos = ("pixar", "disney", "ghibli", "dreamworks", "friedrich", "rembrandt", "deakins")
    for categoria, bloco in BLOCO_TECNICO_POR_CATEGORIA.items():
        assert not any(nome in bloco.lower() for nome in proibidos), categoria


def teste_com_bloco_cola_ao_fim_por_padrao() -> None:
    bloco = BLOCO_TECNICO_POR_CATEGORIA[CategoriaEstilo.PINTURA_A_OLEO]

    assert com_bloco_tecnico("Uma cena.", CategoriaEstilo.PINTURA_A_OLEO) == f"Uma cena. {bloco}"


def teste_sem_categoria_o_texto_nao_muda() -> None:
    assert com_bloco_tecnico("Uma cena.", None) == "Uma cena."


def teste_nao_repete_o_bloco_que_o_texto_ja_tem() -> None:
    bloco = BLOCO_TECNICO_POR_CATEGORIA[CategoriaEstilo.ANIME]
    texto = f"Uma cena. {bloco}"

    assert com_bloco_tecnico(texto, CategoriaEstilo.ANIME) == texto


def teste_a_posicao_do_bloco_e_uma_constante_facil_de_mudar(monkeypatch) -> None:
    monkeypatch.setattr(blocos_tecnicos, "POSICAO_DO_BLOCO", "inicio")

    assert com_bloco_tecnico("Uma cena.", CategoriaEstilo.PIXEL_ART).endswith(" Uma cena.")


# --------------------------------------------------------------------------- #
# O modelo e a migração
# --------------------------------------------------------------------------- #


def teste_modelo_guarda_a_categoria_e_nasce_nulo(sessao_com_tabelas: Session) -> None:
    sem = PerfilRenderizacao(nome="Sem categoria")
    com = PerfilRenderizacao(nome="Gravura", categoria_estilo=CategoriaEstilo.GRAVURA_CLASSICA)
    sessao_com_tabelas.add_all([sem, com])
    sessao_com_tabelas.commit()
    sessao_com_tabelas.expire_all()

    assert sessao_com_tabelas.get(PerfilRenderizacao, sem.id).categoria_estilo is None
    assert sessao_com_tabelas.get(PerfilRenderizacao, com.id).categoria_estilo is CategoriaEstilo.GRAVURA_CLASSICA


def teste_a_migracao_encadeia_depois_da_ultima_e_cria_a_coluna_nula() -> None:
    from pathlib import Path

    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "c3d4e5f6a7b8_categoria_do_estilo_no_perfil.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'" in texto
    assert 'sa.Column("categoria_estilo", sa.String(length=40), nullable=True)' in texto


# --------------------------------------------------------------------------- #
# A API de perfis
# --------------------------------------------------------------------------- #


def teste_api_cria_ajusta_e_desfaz_a_categoria(cliente: TestClient) -> None:
    criado = cliente.post("/perfis-renderizacao", json={"nome": "Anime noir", "categoria_estilo": "ANIME"}).json()
    assert criado["categoria_estilo"] == "ANIME"

    ajustado = cliente.patch(f"/perfis-renderizacao/{criado['id']}", json={"categoria_estilo": "ANIMACAO_3D"}).json()
    assert ajustado["categoria_estilo"] == "ANIMACAO_3D"

    # Só o que vem é aplicado: um PATCH sem a categoria não a perde.
    mantido = cliente.patch(f"/perfis-renderizacao/{criado['id']}", json={"paleta": "tons frios"}).json()
    assert mantido["categoria_estilo"] == "ANIMACAO_3D"

    desfeito = cliente.patch(f"/perfis-renderizacao/{criado['id']}", json={"categoria_estilo": None}).json()
    assert desfeito["categoria_estilo"] is None


def teste_api_recusa_categoria_desconhecida(cliente: TestClient) -> None:
    resposta = cliente.post("/perfis-renderizacao", json={"nome": "X", "categoria_estilo": "LILAS"})

    assert resposta.status_code == 422


def teste_perfil_sem_categoria_devolve_nulo(cliente: TestClient) -> None:
    criado = cliente.post("/perfis-renderizacao", json={"nome": "Antigo"}).json()

    assert criado["categoria_estilo"] is None
    assert cliente.get("/perfis-renderizacao").json()[0]["categoria_estilo"] is None


# --------------------------------------------------------------------------- #
# O prompt
# --------------------------------------------------------------------------- #


def teste_o_prompt_ganha_o_bloco_da_categoria_do_perfil_literalmente(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma pintura de teste"))
    perfil_id = cliente.get("/perfis-renderizacao").json()[0]["id"]
    cliente.patch(f"/perfis-renderizacao/{perfil_id}", json={"categoria_estilo": "PINTURA_A_OLEO"})

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    bloco = BLOCO_TECNICO_POR_CATEGORIA[CategoriaEstilo.PINTURA_A_OLEO]
    assert corpo["texto"] == f"uma pintura de teste {bloco}"


def teste_a_ia_nao_ve_o_bloco(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="uma pintura de teste")
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, provedor)
    perfil_id = cliente.get("/perfis-renderizacao").json()[0]["id"]
    cliente.patch(f"/perfis-renderizacao/{perfil_id}", json={"categoria_estilo": "ANIME"})

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    bloco = BLOCO_TECNICO_POR_CATEGORIA[CategoriaEstilo.ANIME]
    pedido_a_ia = str(provedor.chamadas_de_prompt[0])
    assert bloco not in pedido_a_ia and "Japanese anime" not in pedido_a_ia  # entra por código, depois da resposta


def teste_perfil_sem_categoria_nao_muda_o_prompt(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma pintura de teste"))

    corpo = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    assert corpo["texto"] == "uma pintura de teste"


def teste_o_bloco_fica_guardado_no_prompt_para_a_pessoa_copiar(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    perfil_id = cliente.get("/perfis-renderizacao").json()[0]["id"]
    cliente.patch(f"/perfis-renderizacao/{perfil_id}", json={"categoria_estilo": "GRAVURA_CLASSICA"})
    criado = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()

    aberto = cliente.get(f"/prompts/{criado['id']}").json()

    assert "Classical engraving" in aberto["texto"] and aberto["texto"].startswith("uma cena ")


def teste_sem_perfil_nenhum_o_prompt_nem_e_montado(cliente: TestClient, usar_provedor_falso) -> None:
    """Sem perfil (nem pedido, nem padrão do livro) não há prompt: o bloco não tem de onde vir, e nada muda nessa regra."""
    _, frame = _montar_frame_completo(cliente, usar_provedor_falso, ProvedorFalso(prompt="uma cena"))
    perfil_id = cliente.get("/perfis-renderizacao").json()[0]["id"]
    cliente.delete(f"/perfis-renderizacao/{perfil_id}")

    assert cliente.post(f"/frames/{frame['id']}/prompts", json={}).status_code == 422
