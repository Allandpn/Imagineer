"""Os pedidos do teste de 07/10/2026 que mexem no servidor (P2, P4 e P6): retrato em pose neutra, lista fechada de quem aparece na cena e a correção do
prompt pela IA. Os testes conferem o pedido que chega ao provedor, não a qualidade da resposta (que se vê em livro real)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ErroDoProvedorIA, PromptMontado, UsoDaChamada
from imagineer.modelos import Prompt, Usuario
from imagineer.servicos.acesso import definir_usuario
from imagineer.servicos.uso_de_ia import gravar_uso
from testes.teste_fidelidade_dos_prompts import _provedor_que_guarda_o_pedido
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_traducao_do_prompt import CRIADOR, _prompt


def _instrucao_de_montagem() -> str:
    provedor, pedidos = _provedor_que_guarda_o_pedido("a prompt")
    provedor.montar_prompt("cena", ["Jon: x"], "estilo", "m/x")
    return pedidos[0]["messages"][0]["content"]


# --------------------------------------------------------------------------- #
# P2: o retrato em pose neutra
# --------------------------------------------------------------------------- #


def teste_p2_o_retrato_e_sempre_em_pose_neutra() -> None:
    instrucao = _instrucao_de_montagem()

    # FL1 (08/10/2026) ampliou o P2: além da pose, o retrato é neutro no fundo e na luz.
    assert "Um retrato é uma imagem NEUTRA" in instrucao
    assert "standing in a neutral relaxed pose, arms at sides, facing the camera, neutral expression" in instrucao
    assert "SEM gesto, ação, emoção marcada nem objeto na mão" in instrucao


def teste_p2_a_roupa_e_o_penteado_continuam_vindo_do_instante_e_o_comentario_pode_pedir_outra_pose() -> None:
    instrucao = _instrucao_de_montagem()

    assert "dele use só a roupa e o penteado" in instrucao
    assert "Só o comentário do usuário pode pedir outra coisa (outra pose, outro fundo)" in instrucao
    assert "Num retrato a pose é a neutra (ver acima)" in instrucao  # o bloco 2 não manda mais uma pose específica no retrato
    assert "a roupa e o penteado do \"Neste instante:\"" in instrucao  # a regra do "um só instante" também


# --------------------------------------------------------------------------- #
# P4: lista fechada de quem aparece
# --------------------------------------------------------------------------- #


def teste_p4_so_aparece_quem_esta_na_lista_ou_na_descricao_da_cena() -> None:
    instrucao = _instrucao_de_montagem()

    assert "Lista fechada de quem aparece" in instrucao
    assert "nunca** para trazer mais pessoas, criaturas ou objetos de destaque" in instrucao
    assert "only these figures in the frame" in instrucao
    assert "sem multidões, figuras ao fundo ou animais que ninguém pediu" in instrucao


def teste_p4_o_trecho_do_livro_nao_traz_gente_nova() -> None:
    instrucao = _instrucao_de_montagem()

    assert "nem pessoas, criaturas ou objetos de destaque que não estejam na lista de elementos" in instrucao


# --------------------------------------------------------------------------- #
# P6: corrigir o prompt (o provedor)
# --------------------------------------------------------------------------- #


def teste_p6_o_pedido_leva_o_prompt_atual_e_a_instrucao_e_a_temperatura_e_baixa() -> None:
    provedor, pedidos = _provedor_que_guarda_o_pedido("  a knight, no sword  ")

    corrigido = provedor.corrigir_prompt("a knight with a sword", "tire a espada", "m/x")

    assert corrigido == PromptMontado(texto="a knight, no sword", modelo="m/x")
    assert pedidos[0]["temperature"] == 0.2
    assert pedidos[0]["messages"][1]["content"] == "PROMPT ATUAL:\na knight with a sword\n\nPEDIDO DE CORREÇÃO:\ntire a espada"


def teste_p6_a_instrucao_manda_mudar_so_o_que_o_pedido_diz() -> None:
    provedor, pedidos = _provedor_que_guarda_o_pedido("x")

    provedor.corrigir_prompt("a", "b", "m/x")

    regras = pedidos[0]["messages"][0]["content"]
    assert "Mude SÓ o que o pedido manda mudar" in regras and "IDÊNTICO" in regras
    assert "O pedido da pessoa vale mais" in regras
    assert "bloco final de estilo" in regras
    assert "Não acrescente elementos" in regras


def teste_p6_texto_ou_instrucao_vazios_e_resposta_vazia_viram_erro_em_portugues() -> None:
    provedor, pedidos = _provedor_que_guarda_o_pedido("   ")

    with pytest.raises(ErroDoProvedorIA, match="está vazio"):
        provedor.corrigir_prompt("  ", "tire a espada", "m/x")
    with pytest.raises(ErroDoProvedorIA, match="o que você quer mudar"):
        provedor.corrigir_prompt("a knight", "  ", "m/x")
    assert pedidos == []  # nada foi enviado
    with pytest.raises(ErroDoProvedorIA, match="prompt vazio"):
        provedor.corrigir_prompt("a knight", "tire a espada", "m/x")


# --------------------------------------------------------------------------- #
# P6: a rota
# --------------------------------------------------------------------------- #


def teste_p6_a_rota_devolve_a_proposta_e_nao_grava_nada(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_prompt": "m/prompt"})

    resposta = cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "tire o capuz"})

    assert resposta.status_code == 200, resposta.text
    # O texto guardado de um retrato termina com o bloco do retrato neutro (item 4.9, FL1): a correção parte do que está guardado.
    assert prompt["texto"].startswith("a hooded knight on a misty hill")
    assert resposta.json()["texto"] == f"{prompt['texto']} [corrigido: tire o capuz]"
    assert resposta.json()["modelo"] == "m/prompt" and resposta.json()["custo"] is None
    assert provedor.chamadas_de_correcao == [{"texto": prompt["texto"], "instrucao": "tire o capuz", "modelo": "m/prompt"}]
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Prompt, prompt["id"]).texto == prompt["texto"]  # é proposta: o gravado não mudou


def teste_p6_o_texto_da_tela_vale_mais_que_o_gravado(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_prompt": "m/prompt"})

    cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "mais luz", "texto": "um texto que a pessoa editou à mão"})

    assert provedor.chamadas_de_correcao[0]["texto"] == "um texto que a pessoa editou à mão"


def teste_p6_sem_modelo_de_prompt_usa_o_de_extracao_e_sem_nenhum_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)
    cliente.put("/configuracao", json={"modelo_prompt": None, "modelo_extracao": None})
    assert cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "x"}).status_code == 422

    cliente.put("/configuracao", json={"modelo_extracao": "m/extracao"})
    assert cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "x"}).json()["modelo"] == "m/extracao"


def teste_p6_instrucao_vazia_ou_grande_demais_da_422(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, _ = _prompt(cliente, usar_provedor_falso)

    assert cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": ""}).status_code == 422
    assert cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "x" * 1001}).status_code == 422
    assert cliente.post(f"/prompts/{prompt['id']}/corrigir", json={}).status_code == 422


def teste_p6_prompt_inexistente_da_404_e_de_outra_pessoa_tambem(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    prompt, _ = _prompt(cliente, usar_provedor_falso)
    assert cliente.post("/prompts/99999/corrigir", json={"instrucao": "x"}).status_code == 404

    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    definir_usuario(sessao_com_tabelas, maria.id)

    assert cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "x"}).status_code == 404


def teste_p6_o_custo_da_chamada_volta_e_o_gasto_vai_para_o_livro(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    class ProvedorQueCobraACorrecao(ProvedorFalso):
        def corrigir_prompt(self, texto: str, instrucao: str, modelo: str) -> PromptMontado:
            resultado = super().corrigir_prompt(texto, instrucao, modelo)
            gravar_uso(UsoDaChamada(operacao="correcao", modelo=modelo, custo=Decimal("0.002")), CRIADOR[0])
            return resultado

    from sqlalchemy.orm import sessionmaker

    CRIADOR[0] = sessionmaker(bind=sessao_com_tabelas.get_bind())
    prompt, _ = _prompt(cliente, usar_provedor_falso, ProvedorQueCobraACorrecao(prompt="a hooded knight on a misty hill"))
    cliente.put("/configuracao", json={"modelo_prompt": "m/prompt"})

    resposta = cliente.post(f"/prompts/{prompt['id']}/corrigir", json={"instrucao": "tire o capuz"})

    assert Decimal(resposta.json()["custo"]) == Decimal("0.002")
    from imagineer.modelos import UsoDeIA

    sessao_com_tabelas.expire_all()
    [uso] = sessao_com_tabelas.query(UsoDeIA).filter_by(operacao="correcao").all()
    assert uso.livro_id is not None  # o gasto é do livro do prompt (CU3)
