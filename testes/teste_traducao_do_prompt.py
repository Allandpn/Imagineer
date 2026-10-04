"""A camada em português dos prompts (item 7.5b, PT1 a PT6): ver em português, editar em português e o custo da tradução."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import PromptMontado
from imagineer.modelos import Prompt, UsoDeIA
from imagineer.servicos.uso_de_ia import gravar_uso
from imagineer.ia.provedor import UsoDaChamada
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401
from testes.teste_vinculos_do_retrato import MODELO_FALSO, _preparar_prompt, _retrato


class ProvedorQueTraduzComCusto(ProvedorFalso):
    """O provedor falso, mas a tradução **anota um custo** (como o OpenRouter faz), para a rota poder devolvê-lo."""

    def traduzir_prompt(self, texto: str, para: str, modelo: str) -> PromptMontado:
        resultado = super().traduzir_prompt(texto, para, modelo)
        gravar_uso(UsoDaChamada(operacao="traducao", modelo=modelo, custo=Decimal("0.0004")), CRIADOR[0])
        return resultado


CRIADOR: list = [None]
"""O criador de sessão do banco de teste (preenchido por cada teste), para o ``gravar_uso`` do provedor acima."""


def _prompt(cliente: TestClient, usar_provedor_falso, provedor: ProvedorFalso | None = None) -> tuple[dict, ProvedorFalso]:
    provedor = provedor or ProvedorFalso(prompt="a hooded knight on a misty hill")
    capitulo, e = _preparar_prompt(cliente, usar_provedor_falso, provedor)
    frame = _retrato(cliente, capitulo, e["criatura"], []).json()
    resposta = cliente.post(f"/frames/{frame['id']}/prompts", json={})
    assert resposta.status_code == 201, resposta.text
    return resposta.json(), provedor


def teste_pt2_ver_em_portugues_traduz_uma_vez_e_guarda(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)
    assert prompt["texto_pt"] is None

    primeira = cliente.post(f"/prompts/{prompt['id']}/traducao-pt")

    assert primeira.status_code == 200, primeira.text
    assert primeira.json()["texto"] == "[pt] a hooded knight on a misty hill"
    assert primeira.json()["reaproveitada"] is False
    assert [c["para"] for c in provedor.chamadas_de_traducao] == ["pt"]
    sessao_com_tabelas.expire_all()
    assert sessao_com_tabelas.get(Prompt, prompt["id"]).texto_pt == "[pt] a hooded knight on a misty hill"


def teste_pt2_a_segunda_vez_nao_chama_a_ia(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)
    cliente.post(f"/prompts/{prompt['id']}/traducao-pt")

    segunda = cliente.post(f"/prompts/{prompt['id']}/traducao-pt").json()

    assert segunda["reaproveitada"] is True and segunda["custo"] is None and segunda["modelo"] is None
    assert len(provedor.chamadas_de_traducao) == 1  # só a primeira chamou
    assert cliente.get(f"/prompts/{prompt['id']}").json()["texto_pt"] == segunda["texto"]


def teste_pt3_traduzir_para_ingles_e_so_previa_nao_grava_nada(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/traduzir-para-ingles", json={"texto": "um cavaleiro de capuz numa colina com névoa"})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["texto"] == "[en] um cavaleiro de capuz numa colina com névoa"
    assert provedor.chamadas_de_traducao[-1]["para"] == "en"
    sessao_com_tabelas.expire_all()
    guardado = sessao_com_tabelas.get(Prompt, prompt["id"])
    assert (guardado.texto, guardado.texto_pt) == ("a hooded knight on a misty hill", None)  # nada mudou


def teste_pt3_texto_vazio_e_recusado(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, _ = _prompt(cliente, usar_provedor_falso)

    assert cliente.post(f"/prompts/{prompt['id']}/traduzir-para-ingles", json={"texto": ""}).status_code == 422


def teste_pt5_usa_o_modelo_barato_da_suavizacao_e_cai_no_de_extracao_ou_prompt(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, provedor = _prompt(cliente, usar_provedor_falso)

    cliente.post(f"/prompts/{prompt['id']}/traduzir-para-ingles", json={"texto": "oi"})
    assert provedor.chamadas_de_traducao[-1]["modelo"] == MODELO_FALSO  # sem modelo_suavizacao: cai no de extração

    cliente.put("/configuracao", json={"modelo_suavizacao": "barato/modelo"})
    cliente.post(f"/prompts/{prompt['id']}/traduzir-para-ingles", json={"texto": "oi de novo"})
    assert provedor.chamadas_de_traducao[-1]["modelo"] == "barato/modelo"


def teste_pt6_a_tradução_devolve_o_custo_e_o_registra_como_traducao_do_livro(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    from sqlalchemy.orm import sessionmaker

    CRIADOR[0] = sessionmaker(bind=sessao_com_tabelas.get_bind())
    prompt, _ = _prompt(cliente, usar_provedor_falso, ProvedorQueTraduzComCusto(prompt="a hooded knight"))

    resposta = cliente.post(f"/prompts/{prompt['id']}/traduzir-para-ingles", json={"texto": "um cavaleiro"}).json()

    assert Decimal(resposta["custo"]) == Decimal("0.0004")
    sessao_com_tabelas.expire_all()
    uso = sessao_com_tabelas.query(UsoDeIA).filter(UsoDeIA.operacao == "traducao").one()
    assert uso.livro_id is not None  # do livro do prompt (CU3)
    assert uso.custo == Decimal("0.0004")


def teste_pt4_o_portugues_escrito_vai_junto_do_prompt_editado(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    prompt, _ = _prompt(cliente, usar_provedor_falso)

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/gerar-imagem",
        json={"texto": "a hooded knight on a foggy hill at dawn", "texto_pt": "um cavaleiro de capuz numa colina com névoa ao amanhecer"},
    )

    assert resposta.status_code == 200, resposta.text
    novo = resposta.json()["prompt"]
    assert novo["id"] != prompt["id"]
    assert novo["texto"] == "a hooded knight on a foggy hill at dawn"
    assert novo["texto_pt"] == "um cavaleiro de capuz numa colina com névoa ao amanhecer"  # "Ver em português" mostra o dela, sem nova chamada


def teste_pt4_sem_texto_editado_o_portugues_nao_cria_nada(cliente: TestClient, usar_provedor_falso) -> None:
    prompt, _ = _prompt(cliente, usar_provedor_falso)

    resposta = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem", json={"texto_pt": "ignorado"})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["prompt"]["id"] == prompt["id"]  # o prompt original, sem derivar
    assert resposta.json()["prompt"]["texto_pt"] is None


def teste_prompt_inexistente_e_404(cliente: TestClient) -> None:
    assert cliente.post("/prompts/999/traducao-pt").status_code == 404
    assert cliente.post("/prompts/999/traduzir-para-ingles", json={"texto": "oi"}).status_code == 404
