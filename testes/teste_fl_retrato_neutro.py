"""O retrato neutro e a frase de contexto das referências (item 4.9, FL1, FL2 e FL11; etapa 1).

O retrato de um elemento é a imagem de **identidade** que vai de referência para as cenas: pose, fundo e luz nela são copiados para a cena. Por isso é
neutro (fundo liso, luz uniforme, sem pose, sem lugar). A instrução da IA pede só o sujeito; o enquadramento, o fundo e a luz entram **por código**
depois da resposta da IA, como o bloco técnico do estilo. Nenhum teste fala com o OpenRouter.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.blocos_tecnicos import (
    BLOCO_DO_RETRATO_COM_VINCULADOS,
    BLOCO_DO_RETRATO_NEUTRO,
    FUNDO_NEUTRO,
    LUZ_NEUTRA,
    com_bloco_de_retrato,
    com_bloco_tecnico,
)
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.modelos import CategoriaEstilo, EstadoElemento, TipoElemento
from imagineer.servicos.aparencia_de_elemento import sem_o_lugar
from imagineer.servicos.geracao_de_imagem import _frase_de_contexto

from testes.teste_pedidos_de_07_10 import _instrucao_de_montagem
from testes.teste_rotas_prompts import _frame, _livro, _perfil
from testes.teste_vinculos_do_retrato import _cenario, _elemento

ESTADO_COM_LUGAR = "Aparência fixa: cabelo preto, pele clara\nNeste instante: capa escura\nOnde está: na torre de pedra, ao anoitecer"


# --------------------------------------------------------------------------- #
# O bloco do retrato neutro (FL1, FL2)
# --------------------------------------------------------------------------- #


def teste_fl1_todo_tipo_de_elemento_tem_o_seu_bloco() -> None:
    assert set(BLOCO_DO_RETRATO_NEUTRO) == set(TipoElemento)


def teste_fl1_quem_tem_corpo_fica_de_pe_de_frente_em_fundo_liso_com_luz_uniforme() -> None:
    bloco = BLOCO_DO_RETRATO_NEUTRO[TipoElemento.PERSONAGEM]

    assert "standing" in bloco and "knees up (American shot)" in bloco and "facing the camera" in bloco
    assert "arms at the sides" in bloco and "neutral expression" in bloco and "nothing held in the hands" in bloco
    assert FUNDO_NEUTRO in bloco and LUZ_NEUTRA in bloco
    assert "plain uniform light-gray" in FUNDO_NEUTRO and "soft even lighting" in LUZ_NEUTRA
    assert "a single figure in the frame" in bloco  # "sem mais ninguém"


def teste_fl1_a_criatura_tambem_e_neutra_e_sozinha() -> None:
    bloco = BLOCO_DO_RETRATO_NEUTRO[TipoElemento.CRIATURA]

    assert FUNDO_NEUTRO in bloco and LUZ_NEUTRA in bloco and "a single creature in the frame" in bloco


@pytest.mark.parametrize("tipo", [TipoElemento.OBJETO, TipoElemento.VEICULO])
def teste_fl1_objeto_e_isolado_em_tres_quartos_no_fundo_liso(tipo: TipoElemento) -> None:
    bloco = BLOCO_DO_RETRATO_NEUTRO[tipo]

    assert "three-quarter view" in bloco and FUNDO_NEUTRO in bloco and "nothing else in the frame" in bloco


@pytest.mark.parametrize("tipo", [TipoElemento.AMBIENTE, TipoElemento.EDIFICACAO])
def teste_fl1_ambiente_e_edificacao_vem_em_vista_de_apresentacao_sem_pessoas(tipo: TipoElemento) -> None:
    bloco = BLOCO_DO_RETRATO_NEUTRO[tipo]

    assert "no people" in bloco and "soft diffuse lighting" in bloco
    assert FUNDO_NEUTRO not in bloco  # o lugar É o assunto: não tem fundo liso


def teste_fl1_o_bloco_com_vinculados_nao_diz_figura_unica_nem_nada_nas_maos() -> None:
    assert "single" not in BLOCO_DO_RETRATO_COM_VINCULADOS and "hands" not in BLOCO_DO_RETRATO_COM_VINCULADOS
    assert FUNDO_NEUTRO in BLOCO_DO_RETRATO_COM_VINCULADOS and LUZ_NEUTRA in BLOCO_DO_RETRATO_COM_VINCULADOS


def teste_fl1_o_bloco_e_colado_ao_fim_e_nao_se_repete() -> None:
    uma_vez = com_bloco_de_retrato("a woman in a dark cloak", TipoElemento.PERSONAGEM)
    duas_vezes = com_bloco_de_retrato(uma_vez, TipoElemento.PERSONAGEM)

    assert uma_vez == f"a woman in a dark cloak {BLOCO_DO_RETRATO_NEUTRO[TipoElemento.PERSONAGEM]}"
    assert duas_vezes == uma_vez


def teste_fl1_o_bloco_do_retrato_vem_antes_do_bloco_tecnico_do_estilo() -> None:
    texto = com_bloco_tecnico(com_bloco_de_retrato("a woman", TipoElemento.PERSONAGEM), CategoriaEstilo.AQUARELA)

    assert texto.index("a woman") < texto.index("Neutral reference portrait") < texto.index("Watercolor painting")


# --------------------------------------------------------------------------- #
# Sem o lugar do elemento
# --------------------------------------------------------------------------- #


def teste_fl1_sem_o_lugar_tira_so_a_parte_onde_esta() -> None:
    assert sem_o_lugar(ESTADO_COM_LUGAR) == "Aparência fixa: cabelo preto, pele clara\nNeste instante: capa escura"


def teste_fl1_sem_o_lugar_tira_tambem_as_linhas_que_continuam_o_lugar() -> None:
    texto = "Aparência fixa: a\nOnde está: na torre,\ncom vento forte\nNeste instante: b"

    assert sem_o_lugar(texto) == "Aparência fixa: a\nNeste instante: b"


def teste_fl1_estado_sem_lugar_ou_no_formato_antigo_volta_como_veio() -> None:
    assert sem_o_lugar("Aparência fixa: a\nNeste instante: b") == "Aparência fixa: a\nNeste instante: b"
    assert sem_o_lugar("um texto solto, sem rótulos") == "um texto solto, sem rótulos"
    assert sem_o_lugar(None) is None and sem_o_lugar("") == ""


# --------------------------------------------------------------------------- #
# A instrução da IA
# --------------------------------------------------------------------------- #


def teste_fl1_a_instrucao_diz_que_o_retrato_e_neutro_e_que_o_fundo_e_a_luz_vem_do_sistema() -> None:
    instrucao = _instrucao_de_montagem()

    assert "Um retrato é uma imagem NEUTRA" in instrucao
    assert "COPIA para a cena a pose, o fundo e a luz" in instrucao
    assert "Num retrato NÃO escreva fundo, cenário, luz nem enquadramento" in instrucao
    assert 'não use o "Onde está:"' in instrucao
    assert "fundo liso cinza-claro e a luz suave e uniforme" in instrucao


def teste_fl1_a_instrucao_nao_manda_mais_o_retrato_acontecer_no_lugar_do_elemento() -> None:
    instrucao = _instrucao_de_montagem()

    assert "ele acontece no lugar onde o elemento está" not in instrucao
    assert "o fundo seja o do livro, nunca um fundo genérico ou neutro" not in instrucao
    assert 'Num retrato, o "Onde está:" é o cenário' not in instrucao
    assert "Num retrato não há lugar: o fundo é liso e neutro" in instrucao


def teste_fl1_os_blocos_de_cenario_enquadramento_e_luz_mandam_pular_no_retrato() -> None:
    instrucao = _instrucao_de_montagem()

    assert "Num retrato, pule: o sistema acrescenta." in instrucao
    assert "Num retrato, pule (o fundo é liso e vem do sistema)." in instrucao
    assert "Num retrato, pule (a luz suave e uniforme vem do sistema)." in instrucao


def teste_fl1_com_comentario_o_sistema_nao_acrescenta_o_bloco_e_a_ia_escreve_o_neutro() -> None:
    instrucao = _instrucao_de_montagem()

    assert "Quando VIER um COMENTÁRIO DO USUÁRIO, o sistema NÃO acrescenta esse bloco" in instrucao
    assert "a menos que o comentário peça outra coisa" in instrucao


def teste_fl1_a_cena_continua_com_o_lugar_e_a_luz_da_cena() -> None:
    instrucao = _instrucao_de_montagem()

    assert "O lugar vem da cena." in instrucao
    assert "a **fonte de luz vem sempre da cena**" in instrucao


# --------------------------------------------------------------------------- #
# A rota: o que a IA recebe e o que fica guardado
# --------------------------------------------------------------------------- #


def _retrato_de(cliente, usar_provedor_falso, tipo_do_elemento="PERSONAGEM", com_vinculado=False, **argumentos_do_provedor):
    """Um retrato (frame do tipo PERSONAGEM) do elemento, com o modelo configurado. Devolve (provedor, frame)."""
    provedor = usar_provedor_falso(ProvedorFalso(prompt="a woman in a dark cloak", estado=ESTADO_COM_LUGAR, **argumentos_do_provedor))
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    sujeito = _elemento(cliente, livro["id"], capitulo["id"], "Sujeito", tipo_do_elemento)
    corpo = {"tipo": "PERSONAGEM", "estados_ids": [sujeito["estado_id"]]}
    if com_vinculado:
        objeto = _elemento(cliente, livro["id"], capitulo["id"], "Prato", "OBJETO")
        corpo["estados_vinculados_ids"] = [objeto["estado_id"]]
    frame = cliente.post(f"/capitulos/{capitulo['id']}/frames", json=corpo)
    assert frame.status_code == 201, frame.text
    perfil = _perfil(cliente, iluminacao="luz de vela, contraste alto", paleta="tons terrosos")
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    return provedor, frame.json()


def teste_fl1_o_retrato_guardado_termina_com_o_bloco_neutro_do_tipo_do_sujeito(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _retrato_de(cliente, usar_provedor_falso, "PERSONAGEM")

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert texto == f"a woman in a dark cloak {BLOCO_DO_RETRATO_NEUTRO[TipoElemento.PERSONAGEM]}"


@pytest.mark.parametrize("tipo", ["CRIATURA", "OBJETO", "AMBIENTE"])
def teste_fl1_cada_tipo_de_sujeito_recebe_o_seu_bloco(cliente: TestClient, usar_provedor_falso, tipo: str) -> None:
    _, frame = _retrato_de(cliente, usar_provedor_falso, tipo)

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert texto.endswith(BLOCO_DO_RETRATO_NEUTRO[TipoElemento[tipo]])


def teste_fl1_a_ia_nao_recebe_o_onde_esta_no_retrato(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    elementos = provedor.chamadas_de_prompt[0]["elementos"]
    assert "Onde está" not in " ".join(elementos) and "torre de pedra" not in " ".join(elementos)
    assert "Aparência fixa: cabelo preto, pele clara" in elementos[0] and "Neste instante: capa escura" in elementos[0]


def teste_fl1_a_ia_nao_recebe_a_iluminacao_do_perfil_no_retrato(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    perfil = provedor.chamadas_de_prompt[0]["perfil_renderizacao"]
    assert "iluminação" not in perfil and "luz de vela" not in perfil
    assert "paleta: tons terrosos" in perfil and "aquarela" in perfil and "formato: 2:3, portrait orientation" in perfil


def teste_fl1_o_estado_gravado_continua_com_o_onde_esta(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    """O lugar só sai do que vai à IA no retrato: o estado do elemento (que a cena usa) não perde nada."""
    _, frame = _retrato_de(cliente, usar_provedor_falso)
    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    sessao_com_tabelas.expire_all()
    (estado,) = sessao_com_tabelas.query(EstadoElemento).all()
    assert "Onde está: na torre de pedra" in estado.descricao


def teste_fl1_o_bloco_vai_antes_do_bloco_tecnico_da_categoria_do_perfil(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = usar_provedor_falso(ProvedorFalso(prompt="a woman in a dark cloak", estado=ESTADO_COM_LUGAR))
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    sujeito = _elemento(cliente, livro["id"], capitulo["id"], "Sujeito", "PERSONAGEM")
    frame = cliente.post(f"/capitulos/{capitulo['id']}/frames", json={"tipo": "PERSONAGEM", "estados_ids": [sujeito["estado_id"]]}).json()
    perfil = _perfil(cliente, categoria_estilo="AQUARELA")
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert texto.index("a woman in a dark cloak") < texto.index("Neutral reference portrait") < texto.index("Watercolor painting")
    assert provedor.chamadas_de_prompt  # a IA foi chamada: o bloco veio depois


def teste_fl1_com_vinculados_o_bloco_deixa_de_dizer_figura_unica(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _retrato_de(cliente, usar_provedor_falso, "CRIATURA", com_vinculado=True)

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert texto.endswith(BLOCO_DO_RETRATO_COM_VINCULADOS)
    assert "single" not in texto


def teste_fl1_os_vinculados_tambem_ficam_sem_o_onde_esta(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso, "CRIATURA", com_vinculado=True)

    cliente.post(f"/frames/{frame['id']}/prompts", json={})

    vinculados = provedor.chamadas_de_prompt[0]["elementos_vinculados"]
    assert vinculados and "Onde está" not in " ".join(vinculados)


def teste_fl1_com_comentario_do_usuario_o_codigo_nao_cola_o_bloco(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso)

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={"comentario": "com um fundo de floresta"}).json()["texto"]

    assert texto == "a woman in a dark cloak"  # o que a IA devolveu, sem o bloco que contradiria o comentário
    assert provedor.chamadas_de_prompt[0]["comentario_do_usuario"] == "com um fundo de floresta"


def teste_fl1_comentario_so_de_espacos_nao_conta_como_comentario(cliente: TestClient, usar_provedor_falso) -> None:
    _, frame = _retrato_de(cliente, usar_provedor_falso)

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={"comentario": "   "}).json()["texto"]

    assert texto.endswith(BLOCO_DO_RETRATO_NEUTRO[TipoElemento.PERSONAGEM])


def teste_fl1_a_cena_nao_leva_bloco_de_retrato_e_mantem_o_lugar_e_a_iluminacao(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = usar_provedor_falso(ProvedorFalso(prompt="two people at a table", estado=ESTADO_COM_LUGAR))
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    sujeito = _elemento(cliente, livro["id"], capitulo["id"], "Sujeito", "PERSONAGEM")
    frame = _frame(cliente, capitulo["id"], [sujeito["estado_id"]], tipo="CENA")
    perfil = _perfil(cliente, iluminacao="luz de vela")
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})

    texto = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()["texto"]

    assert texto == "two people at a table"
    chamada = provedor.chamadas_de_prompt[0]
    assert "Onde está: na torre de pedra" in chamada["elementos"][0]
    assert "iluminação: luz de vela" in chamada["perfil_renderizacao"]


def teste_fl1_o_prompt_de_video_do_retrato_nao_muda(cliente: TestClient, usar_provedor_falso) -> None:
    provedor, frame = _retrato_de(cliente, usar_provedor_falso)

    video = cliente.post(f"/frames/{frame['id']}/prompts", json={"tipo": "VIDEO"})

    assert video.status_code == 201, video.text
    assert "Neutral reference portrait" not in video.json()["texto"]
    assert "Onde está: na torre de pedra" in provedor.chamadas_de_video[0]["elementos"][0]


# --------------------------------------------------------------------------- #
# FL11: a frase de contexto das referências
# --------------------------------------------------------------------------- #


def teste_fl11_a_frase_trava_a_referencia_como_so_identidade() -> None:
    frase = _frase_de_contexto(["Auri", "Hospius"])

    assert frase == (
        "Reference images are for IDENTITY ONLY (face, hair, skin, build) of: image 1 is Auri; image 2 is Hospius. "
        "Do NOT copy pose, expression, clothing, background, lighting, camera angle or any object or person from the reference images. "
        "Clothing, pose, setting and everything else come only from the text below. "
        "Anything not described in the text must not appear."
    )


def teste_fl11_imagem_sem_dono_conhecido_so_e_numerada() -> None:
    assert "of: image 1 is Auri; image 2." in _frase_de_contexto(["Auri", None])


def teste_fl11_uma_so_imagem() -> None:
    assert "of: image 1 is Auri. Do NOT copy" in _frase_de_contexto(["Auri"])


def teste_fl11_imagem_de_cena_e_referencia_de_composicao_e_nao_de_identidade() -> None:
    frase = _frase_de_contexto(['the scene "A partida"'])

    assert "IDENTITY ONLY" not in frase
    assert frase == (
        'Image 1 is an earlier illustration of the scene "A partida": use it only as a reference for composition and mood, '
        "and do not copy any figure or object from it that the text below does not describe."
    )


def teste_fl11_cena_e_personagem_juntos_mantem_a_numeracao_das_imagens() -> None:
    frase = _frase_de_contexto(["Auri", 'the scene "A partida"', "Hospius"])

    assert "of: image 1 is Auri; image 3 is Hospius." in frase
    assert 'Image 2 is an earlier illustration of the scene "A partida"' in frase
    assert frase.index("IDENTITY ONLY") < frase.index("Image 2 is")
