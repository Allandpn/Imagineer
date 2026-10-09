"""O script que mede a fidelidade de cenas e retratos (item 4.9, FL13.3; etapa 6).

Nenhum teste fala com o OpenRouter: o provedor e o juiz são falsos e entram por injeção. O que se confere é a **mecânica** do script (casos, caminho de
produção, conferência, tabela de acertos); a fidelidade dos modelos de verdade só se mede rodando-o com chave e casos reais.
"""

import importlib.util
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from imagineer.ia.blocos_tecnicos import BLOCO_DO_RETRATO_NEUTRO
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import ErroDoProvedorIA, UsoDaChamada
from imagineer.modelos import TipoElemento

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "scripts" / "exemplos"


def _carregar(nome: str):
    caminho = RAIZ / "scripts" / f"{nome}.py"
    especificacao = importlib.util.spec_from_file_location(nome, caminho)
    modulo = importlib.util.module_from_spec(especificacao)
    sys.modules[nome] = modulo
    especificacao.loader.exec_module(modulo)
    return modulo


script = _carregar("avaliar_fidelidade")
avaliacao_de_modelos = sys.modules["avaliar_modelos_de_leitura"]  # o irmão que o script importa


def _exemplo(nome: str) -> dict:
    return json.loads((EXEMPLOS / nome).read_text(encoding="utf-8"))


DOSSIE = {
    "momento_incerto": False,
    "presentes": [
        {"nome": "Maren", "tipo": "PESSOA", "elemento": "Maren", "caracteristicas": "green wool cloak, damp", "incerto": False, "incluir": True},
        {"nome": "o cão", "tipo": "CRIATURA", "elemento": None, "caracteristicas": "grey dog lying under the table", "incerto": False, "incluir": True},
        {"nome": "a mesa", "tipo": "OBJETO", "elemento": None, "caracteristicas": "round oak table", "incerto": False, "incluir": True},
    ],
    "onde": "a tavern", "luz_e_clima": "one candle", "acao": "Maren waits", "faltou": [],
}

CENA = {
    "livro": "Livro de Teste", "capitulo": 1, "tipo": "cena", "texto": "O texto do capítulo, inventado.",
    "cena": {"titulo": "A espera", "descricao": "Maren espera na taverna.", "trecho": "Maren esperava."},
    "participantes": [{"nome": "Maren", "tipo": "PERSONAGEM", "aparencia": "Aparência fixa: mulher alta\nNeste instante: manto verde\nOnde está: a taverna"}],
    "deve_aparecer": ["green wool cloak", "round oak table", "grey dog"],
    "nao_deve_aparecer": ["innkeeper", "sword"],
}

RETRATO = {
    "livro": "Livro de Teste", "capitulo": 1, "tipo": "retrato", "texto": "O texto do capítulo, inventado.",
    "elemento": {"nome": "Maren", "tipo": "PERSONAGEM", "identidade": "uma aldeã", "aparencia": "Aparência fixa: mulher alta\nNeste instante: camisola cinza\nOnde está: a cabana"},
    "deve_aparecer": ["tall woman", "plain uniform light-gray studio background"],
    "nao_deve_aparecer": ["cabin", "river"],
}

PROMPT_FIEL = "Maren in a green wool cloak at a round oak table, a grey dog lying under it, exactly one person"
PROMPT_COM_ERRO = "Maren in a green wool cloak at a round oak table, the innkeeper behind the bar, a sword on the table"


class ProvedorMedido(ProvedorFalso):
    """O provedor falso que, como o de verdade, avisa o consumo de cada chamada por ``ao_usar``."""

    def __init__(self, ao_usar, custo: Decimal | None = Decimal("0.002"), **argumentos) -> None:
        super().__init__(**argumentos)
        self._ao_usar_medido = ao_usar
        self._custo = custo

    def fundamentar_frame(self, *argumentos, **nomeados):
        resposta = super().fundamentar_frame(*argumentos, **nomeados)
        self._ao_usar_medido(UsoDaChamada(operacao="fundamentacao", modelo="m", custo=self._custo))
        return resposta

    def montar_prompt(self, *argumentos, **nomeados):
        resposta = super().montar_prompt(*argumentos, **nomeados)
        self._ao_usar_medido(UsoDaChamada(operacao="prompt", modelo="m", custo=self._custo))
        return resposta


def juiz_literal(instrucao: str, pedido: str) -> str:
    """Um juiz que confere por substring: o item "aparece" se o texto o contém (maiúsculas à parte)."""
    texto = re.search(r"TEXTO A CONFERIR:\n(.*?)\n\nDEVE APARECER:", pedido, re.S).group(1).lower()
    deve = re.search(r"DEVE APARECER:\n(.*?)\n\nNÃO DEVE APARECER:", pedido, re.S).group(1)
    nao_deve = re.search(r"NÃO DEVE APARECER:\n(.*)$", pedido, re.S).group(1)

    def itens(bloco: str) -> list[str]:
        return [re.sub(r"^\d+\.\s*", "", linha).lower() for linha in bloco.splitlines() if re.match(r"^\d+\.", linha)]

    return json.dumps({"deve": [i in texto for i in itens(deve)], "nao_deve": [i in texto for i in itens(nao_deve)]})


def _caso(dados: dict, nome: str = "caso.json"):
    return script.validar_caso(dados, nome)


def _executar(dados: dict, prompt: str = PROMPT_FIEL, juiz=juiz_literal, **argumentos_do_provedor):
    usos: list[UsoDaChamada] = []
    argumentos_do_provedor.setdefault("dossie", json.loads(json.dumps(DOSSIE)))
    provedor = ProvedorMedido(usos.append, prompt=prompt, **argumentos_do_provedor)
    caso = _caso(dados)
    ticks = iter([0.0, 3.5])
    resultado = script.executar(caso, "leitura/m", "prompt/m", provedor, usos, caso.dados.get("texto", ""), juiz, lambda: next(ticks))
    return resultado, provedor


# --------------------------------------------------------------------------- #
# Os casos
# --------------------------------------------------------------------------- #


def teste_fl13_os_casos_de_exemplo_de_fidelidade_sao_validos() -> None:
    assert _caso(_exemplo("caso_de_fidelidade_cena.json")).tipo == "cena"
    assert _caso(_exemplo("caso_de_fidelidade_retrato.json")).tipo == "retrato"


def teste_fl13_os_exemplos_tem_texto_inventado() -> None:
    for nome in ("caso_de_fidelidade_cena.json", "caso_de_fidelidade_retrato.json"):
        assert "inventado" in _exemplo(nome)["livro"]


@pytest.mark.parametrize(
    "arquivo, apagar, campo",
    [
        ("caso_de_fidelidade_cena.json", ("tipo",), "tipo"),
        ("caso_de_fidelidade_cena.json", ("livro",), "livro"),
        ("caso_de_fidelidade_cena.json", ("capitulo",), "capitulo"),
        ("caso_de_fidelidade_cena.json", ("deve_aparecer",), "deve_aparecer"),
        ("caso_de_fidelidade_cena.json", ("nao_deve_aparecer",), "nao_deve_aparecer"),
        ("caso_de_fidelidade_cena.json", ("cena",), "cena"),
        ("caso_de_fidelidade_cena.json", ("cena", "trecho"), "trecho"),
        ("caso_de_fidelidade_cena.json", ("participantes",), "participantes"),
        ("caso_de_fidelidade_cena.json", ("participantes", 0, "aparencia"), "aparencia"),
        ("caso_de_fidelidade_retrato.json", ("elemento",), "elemento"),
        ("caso_de_fidelidade_retrato.json", ("elemento", "nome"), "nome"),
        ("caso_de_fidelidade_retrato.json", ("elemento", "aparencia"), "aparencia"),
    ],
)
def teste_fl13_caso_com_campo_faltando_e_recusado_dizendo_qual(arquivo: str, apagar: tuple, campo: str) -> None:
    dados = _exemplo(arquivo)
    alvo = dados
    for chave in apagar[:-1]:
        alvo = alvo[chave]
    del alvo[apagar[-1]]

    with pytest.raises(script.CasoInvalido) as erro:
        script.validar_caso(dados, "meu_caso.json")

    assert "meu_caso.json" in str(erro.value) and f"falta o campo '{campo}'" in str(erro.value)


def teste_fl13_tipo_desconhecido_e_tipo_de_elemento_desconhecido_sao_recusados() -> None:
    dados = _exemplo("caso_de_fidelidade_cena.json")
    dados["tipo"] = "estado"
    with pytest.raises(script.CasoInvalido, match="'tipo' deve ser um de cena, retrato"):
        script.validar_caso(dados, "x.json")

    dados = _exemplo("caso_de_fidelidade_retrato.json")
    dados["elemento"]["tipo"] = "MONSTRO"
    with pytest.raises(script.CasoInvalido, match="PERSONAGEM"):
        script.validar_caso(dados, "x.json")


def teste_fl13_caso_sem_nada_a_conferir_e_recusado() -> None:
    dados = _exemplo("caso_de_fidelidade_cena.json")
    dados["deve_aparecer"], dados["nao_deve_aparecer"] = [], []

    with pytest.raises(script.CasoInvalido, match="não tem nada a conferir"):
        script.validar_caso(dados, "x.json")


def teste_fl13_basta_ter_so_a_lista_do_que_nao_deve_aparecer() -> None:
    dados = _exemplo("caso_de_fidelidade_cena.json")
    dados["deve_aparecer"] = []

    assert script.validar_caso(dados, "x.json").tipo == "cena"


def teste_fl13_carregar_casos_ignora_os_casos_do_outro_script(tmp_path: Path) -> None:
    for origem, destino in (
        ("caso_de_exemplo.json", "a_estado.json"),
        ("caso_de_fidelidade_cena.json", "b_cena.json"),
        ("caso_de_exemplo_dossie.json", "c_dossie.json"),
        ("caso_de_fidelidade_retrato.json", "d_retrato.json"),
    ):
        (tmp_path / destino).write_text((EXEMPLOS / origem).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "leia-me.txt").write_text("nada", encoding="utf-8")

    todos = script.carregar_casos(tmp_path)
    so_retrato = script.carregar_casos(tmp_path, ["retrato"])

    assert [c.arquivo for c in todos] == ["b_cena.json", "d_retrato.json"]
    assert [c.arquivo for c in so_retrato] == ["d_retrato.json"]


def teste_fl13_o_script_de_avaliacao_de_modelos_ignora_os_casos_de_fidelidade(tmp_path: Path) -> None:
    """As duas ferramentas podem dividir a pasta ``avaliacao/``."""
    (tmp_path / "estado.json").write_text((EXEMPLOS / "caso_de_exemplo.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "cena.json").write_text((EXEMPLOS / "caso_de_fidelidade_cena.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "retrato.json").write_text((EXEMPLOS / "caso_de_fidelidade_retrato.json").read_text(encoding="utf-8"), encoding="utf-8")

    casos = avaliacao_de_modelos.carregar_casos(tmp_path, ["estado", "dossie", "extracao"])

    assert [c.arquivo for c in casos] == ["estado.json"]


def teste_fl13_caso_invalido_na_pasta_diz_o_arquivo(tmp_path: Path) -> None:
    dados = _exemplo("caso_de_fidelidade_cena.json")
    del dados["cena"]
    (tmp_path / "ruim.json").write_text(json.dumps(dados), encoding="utf-8")

    with pytest.raises(script.CasoInvalido, match="ruim.json.*falta o campo 'cena'"):
        script.carregar_casos(tmp_path)


# --------------------------------------------------------------------------- #
# O caminho de produção de uma cena
# --------------------------------------------------------------------------- #


def teste_fl13_a_cena_le_o_dossie_e_monta_o_prompt_com_a_lista_fechada() -> None:
    resultado, provedor = _executar(CENA)

    (leitura,) = provedor.chamadas_de_fundamentacao
    assert leitura["titulo"] == "A espera" and leitura["trecho"] == "Maren esperava." and leitura["modelo"] == "leitura/m"
    assert leitura["participantes"] == ["Maren: Aparência fixa: mulher alta\nNeste instante: manto verde\nOnde está: a taverna"]  # na cena o lugar fica
    (montagem,) = provedor.chamadas_de_prompt
    assert montagem["modelo"] == "prompt/m" and [p["nome"] for p in montagem["dossie"]["presentes"]] == ["Maren", "o cão", "a mesa"]
    assert montagem["contexto_do_livro"] is None and montagem["trecho_do_livro"] == "Maren esperava."
    assert resultado.prompt == PROMPT_FIEL and resultado.presentes_no_dossie == 3 and resultado.momento_incerto is False


def teste_fl13_cena_sem_dossie_segue_com_o_contexto() -> None:
    usos: list[UsoDaChamada] = []
    provedor = ProvedorMedido(usos.append, prompt=PROMPT_FIEL, contexto="é numa taverna")
    caso = _caso(CENA)

    resultado = script.executar(caso, "l", "p", provedor, usos, "texto", juiz_literal)

    montagem = provedor.chamadas_de_prompt[0]
    assert montagem["contexto_do_livro"] == "é numa taverna" and "dossie" not in montagem
    assert resultado.dossie_deve is None and resultado.presentes_no_dossie is None and resultado.julgado is True


def teste_fl13_a_cena_fiel_acerta_no_dossie_e_no_prompt() -> None:
    resultado, _ = _executar(CENA)

    assert resultado.dossie_deve == [True, True, True]  # o dossiê traz o manto, a mesa e o cão (na ordem da lista "deve")
    assert resultado.dossie_nao_deve == [False, False]
    assert resultado.prompt_deve == [True, True, True] and resultado.prompt_nao_deve == [False, False]
    assert script.acertou(resultado) is True


def teste_fl13_a_cena_com_gente_e_objeto_a_mais_erra() -> None:
    resultado, _ = _executar(CENA, prompt=PROMPT_COM_ERRO)

    assert resultado.prompt_deve == [True, True, False] and resultado.prompt_nao_deve == [True, True]
    assert script.acertou(resultado) is False


def teste_fl13_um_so_item_proibido_ja_basta_para_errar() -> None:
    resultado, _ = _executar(CENA, prompt=PROMPT_FIEL + ", and a sword")

    assert resultado.prompt_deve == [True, True, True] and resultado.prompt_nao_deve == [False, True]
    assert script.acertou(resultado) is False


def teste_fl13_o_dossie_e_conferido_a_parte_do_prompt() -> None:
    dossie = json.loads(json.dumps(DOSSIE))
    dossie["presentes"] = dossie["presentes"][:1]  # o dossiê perdeu a mesa e o cão; o prompt, não

    resultado, _ = _executar(CENA, dossie=dossie)

    assert resultado.dossie_deve == [True, False, False] and resultado.prompt_deve == [True, True, True]


def teste_fl13_o_que_a_pessoa_tirou_da_lista_nao_conta_no_dossie_conferido() -> None:
    dossie = json.loads(json.dumps(DOSSIE))
    dossie["presentes"][1]["incluir"] = False

    resultado, _ = _executar(CENA, dossie=dossie)

    # "deve": manto, mesa, cão. O cão foi tirado da lista: o dossiê conferido (como a montagem o recebe) não o traz.
    assert resultado.dossie_deve == [True, True, False] and resultado.presentes_no_dossie == 2


# --------------------------------------------------------------------------- #
# O caminho de produção de um retrato
# --------------------------------------------------------------------------- #


def teste_fl13_o_retrato_vai_sem_o_onde_esta_e_sem_dossie() -> None:
    resultado, provedor = _executar(RETRATO, prompt="a tall woman in a gray linen nightgown")

    (montagem,) = provedor.chamadas_de_prompt
    assert montagem["elementos"] == ["Maren (uma aldeã): Aparência fixa: mulher alta\nNeste instante: camisola cinza"]
    assert montagem["descricao_do_frame"] == "" and "dossie" not in montagem
    assert provedor.chamadas_de_fundamentacao == []
    assert resultado.dossie_deve is None


def teste_fl13_o_retrato_leva_o_bloco_neutro_colado_por_codigo() -> None:
    resultado, _ = _executar(RETRATO, prompt="a tall woman in a gray linen nightgown")

    assert resultado.prompt == f"a tall woman in a gray linen nightgown {BLOCO_DO_RETRATO_NEUTRO[TipoElemento.PERSONAGEM]}"
    assert resultado.prompt_deve == [True, True] and resultado.prompt_nao_deve == [False, False]
    assert script.acertou(resultado) is True


def teste_fl13_retrato_que_vazou_o_cenario_erra() -> None:
    resultado, _ = _executar(RETRATO, prompt="a tall woman by the river, in front of the cabin")

    assert resultado.prompt_nao_deve == [True, True] and script.acertou(resultado) is False


def teste_fl13_o_retrato_usa_o_perfil_do_caso_quando_ha() -> None:
    dados = {**RETRATO, "perfil": "aquarela; formato: 2:3"}

    _, provedor = _executar(dados, prompt="x")

    assert provedor.chamadas_de_prompt[0]["perfil_renderizacao"] == "aquarela; formato: 2:3"


def teste_fl13_sem_perfil_no_caso_vale_o_formato_vertical() -> None:
    _, provedor = _executar(RETRATO, prompt="x")

    assert provedor.chamadas_de_prompt[0]["perfil_renderizacao"] == "formato: 2:3, portrait orientation"


# --------------------------------------------------------------------------- #
# Custo, tempo, erros e juiz
# --------------------------------------------------------------------------- #


def teste_fl13_soma_o_custo_das_chamadas_e_mede_o_tempo() -> None:
    resultado, _ = _executar(CENA)

    assert resultado.custo == Decimal("0.004") and resultado.chamadas == 2 and resultado.latencia == 3.5


def teste_fl13_custo_nao_informado_fica_nulo() -> None:
    usos: list[UsoDaChamada] = []
    provedor = ProvedorMedido(usos.append, custo=None, prompt=PROMPT_FIEL, dossie=json.loads(json.dumps(DOSSIE)))

    resultado = script.executar(_caso(CENA), "l", "p", provedor, usos, "t", juiz_literal)

    assert resultado.custo is None


def teste_fl13_sem_juiz_so_se_mede_custo_e_tempo() -> None:
    resultado, _ = _executar(CENA, juiz=None)

    assert resultado.julgado is False and resultado.prompt_deve is None and script.acertou(resultado) is None
    assert resultado.custo == Decimal("0.004")


def teste_fl13_erro_do_provedor_fica_no_resultado_e_o_juiz_nao_e_chamado() -> None:
    chamadas = []
    resultado, _ = _executar(CENA, juiz=lambda i, p: chamadas.append(1) or "{}", erro=ErroDoProvedorIA("o serviço caiu"))

    assert resultado.erro == "o serviço caiu" and chamadas == [] and script.acertou(resultado) is None


def teste_fl13_juiz_que_nao_devolve_json_deixa_o_caso_sem_veredito() -> None:
    resultado, _ = _executar(CENA, juiz=lambda instrucao, pedido: "não sei")

    assert resultado.julgado is False and script.acertou(resultado) is None and resultado.erro is None


def teste_fl13_juiz_que_falha_nao_derruba_a_avaliacao() -> None:
    def quebrado(instrucao: str, pedido: str) -> str:
        raise ErroDoProvedorIA("juiz fora do ar")

    resultado, _ = _executar(CENA, juiz=quebrado)

    assert resultado.julgado is False and any("o juiz falhou" in n for n in resultado.notas)


def teste_fl13_lista_do_juiz_mais_curta_conta_o_que_faltou_como_nao_apareceu() -> None:
    resultado, _ = _executar(CENA, juiz=lambda i, p: json.dumps({"deve": [True], "nao_deve": []}))

    assert resultado.prompt_deve == [True, False, False] and resultado.prompt_nao_deve == [False, False]


def teste_fl13_o_pedido_ao_juiz_leva_o_texto_e_as_duas_listas_numeradas() -> None:
    vistos = []

    def juiz(instrucao: str, pedido: str) -> str:
        vistos.append((instrucao, pedido))
        return juiz_literal(instrucao, pedido)

    _executar(CENA, juiz=juiz)

    assert len(vistos) == 2  # o dossiê e o prompt
    instrucao, pedido = vistos[1]
    assert "Seja literal" in instrucao and '"deve"' in instrucao and '"nao_deve"' in instrucao
    assert PROMPT_FIEL in pedido and "DEVE APARECER:\n1. green wool cloak\n2. round oak table\n3. grey dog" in pedido
    assert "NÃO DEVE APARECER:\n1. innkeeper\n2. sword" in pedido
    assert "O QUE APARECE NA CENA" in vistos[0][1]  # o dossiê é conferido na forma em que a montagem o recebe


# --------------------------------------------------------------------------- #
# O relatório
# --------------------------------------------------------------------------- #


def _tres_resultados():
    certo, _ = _executar(CENA)
    errado, _ = _executar(CENA, prompt=PROMPT_COM_ERRO)
    retrato, _ = _executar(RETRATO, prompt="a tall woman")
    return [certo, errado, retrato]


def teste_fl13_a_linha_do_caso_diz_acertou_ou_errou() -> None:
    certo, errado, _ = _tres_resultados()

    assert script.linha_do_resultado(certo)[CABECALHO_POSICAO["Veredito"]] == "ACERTOU"
    assert script.linha_do_resultado(errado)[CABECALHO_POSICAO["Veredito"]] == "ERROU"
    assert script.linha_do_resultado(certo)[CABECALHO_POSICAO["Prompt: deve"]] == "3/3"
    assert script.linha_do_resultado(errado)[CABECALHO_POSICAO["Prompt: não deve"]] == "2/2"


CABECALHO_POSICAO = {nome: i for i, nome in enumerate(script.CABECALHO)}


def teste_fl13_caso_sem_veredito_mostra_traco_e_o_erro_aparece_nas_observacoes() -> None:
    sem_juiz, _ = _executar(CENA, juiz=None)
    com_erro, _ = _executar(CENA, erro=ErroDoProvedorIA("caiu"))

    assert script.linha_do_resultado(sem_juiz)[CABECALHO_POSICAO["Veredito"]] == "-"
    assert "ERRO: caiu" in script.linha_do_resultado(com_erro)[CABECALHO_POSICAO["Observações"]]


def teste_fl13_o_resumo_por_modelo_conta_casos_obrigatorios_e_proibidos() -> None:
    (linha,) = script.resumo_por_modelo(_tres_resultados())

    assert linha[:2] == ["leitura/m", "prompt/m"]
    assert linha[2] == "2/3 casos"  # acertou a cena fiel e o retrato; errou a cena com gente a mais
    assert linha[3] == "7/8 obrigatórios no prompt"  # 3 + 2 + 2 de 3 + 3 + 2
    assert linha[4] == "2/6 proibidos que apareceram"
    assert linha[5].startswith("US$ ")


def teste_fl13_a_tabela_tem_o_resumo_e_a_lista_por_caso() -> None:
    tabela = script.tabela_em_markdown(_tres_resultados())

    assert tabela.startswith("## Resumo") and "## Por caso" in tabela
    assert "| Modelo de leitura | Modelo do prompt | Acertos |" in tabela
    assert "| leitura/m | prompt/m | caso.json | cena |" in tabela and tabela.count("ACERTOU") == 2 and tabela.count("ERROU") == 1


def teste_fl13_o_csv_tem_o_cabecalho_e_uma_linha_por_resultado(tmp_path: Path) -> None:
    import csv

    caminho = tmp_path / "f.csv"
    script.escrever_csv(_tres_resultados(), caminho)

    with open(caminho, encoding="utf-8", newline="") as arquivo:
        linhas = list(csv.reader(arquivo))
    assert linhas[0] == script.CABECALHO and len(linhas) == 4


# --------------------------------------------------------------------------- #
# A avaliação inteira e a linha de comando
# --------------------------------------------------------------------------- #


def _fabricar(**argumentos):
    return lambda ao_usar: ProvedorMedido(ao_usar, prompt=PROMPT_FIEL, dossie=json.loads(json.dumps(DOSSIE)), **argumentos)


def teste_fl13_a_avaliacao_roda_cada_modelo_caso_e_repeticao() -> None:
    casos = [_caso(CENA, "a.json"), _caso(RETRATO, "b.json")]

    resultados = script.avaliar(
        casos, ["m/um", "m/dois"], "p/prompt", lambda caso: "texto", _fabricar(), juiz_literal, repeticoes=2, avisar=lambda *_: None
    )

    assert len(resultados) == 2 * 2 * 2
    assert [(r.modelo_de_leitura, r.caso) for r in resultados[:4]] == [("m/um", "a.json")] * 2 + [("m/um", "b.json")] * 2
    assert {r.modelo_de_prompt for r in resultados} == {"p/prompt"}


def teste_fl13_sem_modelo_de_prompt_vale_o_mesmo_da_leitura() -> None:
    resultados = script.avaliar([_caso(CENA)], ["m/um"], None, lambda caso: "t", _fabricar(), None, avisar=lambda *_: None)

    assert resultados[0].modelo_de_prompt == "m/um"


def _pasta(tmp_path: Path, **arquivos) -> Path:
    pasta = tmp_path / "casos"
    pasta.mkdir()
    for nome, dados in arquivos.items():
        (pasta / f"{nome}.json").write_text(json.dumps(dados), encoding="utf-8")
    return pasta


def teste_fl13_o_script_roda_com_provedor_e_juiz_falsos_e_gera_a_tabela(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path, a_cena=CENA, b_retrato=RETRATO)
    saida = tmp_path / "fidelidade.md"
    avisos: list[str] = []

    resultados = script.main(
        ["--casos", str(pasta), "--juiz", "j/juiz", "--saida", str(saida), "--prompt", "p/prompt", "m/um"],
        fabricar_provedor=_fabricar(), juiz=juiz_literal, avisar=avisos.append,
    )

    assert len(resultados) == 2
    assert saida.read_text(encoding="utf-8").startswith("## Resumo") and saida.with_suffix(".csv").exists()
    assert any("Relatório em" in a for a in avisos)


def teste_fl13_a_opcao_tipos_limita_o_que_roda(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path, a_cena=CENA, b_retrato=RETRATO)

    resultados = script.main(["--casos", str(pasta), "--tipos", "retrato", "m/um"], fabricar_provedor=_fabricar(), avisar=lambda *_: None)

    assert [r.tipo for r in resultados] == ["retrato"]


def teste_fl13_tipo_desconhecido_e_repeticoes_invalidas_sao_recusados(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path, a_cena=CENA)

    for argumentos in (["--tipos", "estado"], ["--repeticoes", "0"]):
        with pytest.raises(SystemExit) as saida:
            script.main(["--casos", str(pasta), *argumentos, "m/um"], fabricar_provedor=_fabricar())
        assert saida.value.code == 2


def teste_fl13_caso_invalido_para_tudo_antes_de_gastar_e_diz_o_campo(tmp_path: Path) -> None:
    ruim = {k: v for k, v in CENA.items() if k != "participantes"}
    pasta = _pasta(tmp_path, a_cena=CENA, ruim=ruim)
    criados = []

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(pasta), "m/um"], fabricar_provedor=lambda ao_usar: criados.append(1) or ProvedorMedido(ao_usar))

    assert "ruim.json" in str(saida.value) and "falta o campo 'participantes'" in str(saida.value) and criados == []


def teste_fl13_sem_casos_de_fidelidade_para_com_mensagem(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path, so_estado=_exemplo("caso_de_exemplo.json"))

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(pasta), "m/um"], fabricar_provedor=_fabricar())

    assert "Nenhum caso de fidelidade" in str(saida.value)


def teste_fl13_caso_sem_texto_e_sem_epubs_para_antes_de_gastar(tmp_path: Path) -> None:
    sem_texto = {k: v for k, v in CENA.items() if k != "texto"}
    pasta = _pasta(tmp_path, sem_texto=sem_texto)

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(pasta), "m/um"], fabricar_provedor=_fabricar())

    assert "--epubs" in str(saida.value)


def teste_fl13_nenhum_teste_fala_com_o_openrouter(tmp_path: Path, monkeypatch) -> None:
    def proibido(*args, **kwargs):
        raise AssertionError("o script tentou falar com o OpenRouter")

    monkeypatch.setattr(script, "ProvedorOpenRouter", proibido)
    pasta = _pasta(tmp_path, a_cena=CENA)

    assert script.main(["--casos", str(pasta), "m/um"], fabricar_provedor=_fabricar(), avisar=lambda *_: None)


def teste_fl13_sem_chave_do_openrouter_o_script_para_com_mensagem(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path, a_cena=CENA)

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(pasta), "m/um"], avisar=lambda *_: None)

    assert "Sem chave do OpenRouter" in str(saida.value)
