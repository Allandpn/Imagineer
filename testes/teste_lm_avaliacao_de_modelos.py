"""O script que compara modelos na leitura do livro (item 4.10, LM18 e LM19; etapa E8).

Nenhum teste fala com o OpenRouter: o provedor e o juiz são falsos e entram por injeção (``fabricar_provedor``, ``juiz``). O que se confere é a
**mecânica** do script (casos, métricas, ordenação, relatório); a qualidade dos modelos de verdade só se mede rodando-o com chave e casos reais.
"""

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from imagineer.ia.catalogo_de_texto import Capacidades
from imagineer.ia.falso import ProvedorFalso
from imagineer.ia.provedor import CenaSugerida, ErroDoProvedorIA, ParticipanteSugerido, UsoDaChamada
from imagineer.modelos import TipoElemento

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "scripts" / "exemplos"


def _carregar_o_script():
    caminho = RAIZ / "scripts" / "avaliar_modelos_de_leitura.py"
    especificacao = importlib.util.spec_from_file_location("avaliar_modelos_de_leitura", caminho)
    modulo = importlib.util.module_from_spec(especificacao)
    sys.modules["avaliar_modelos_de_leitura"] = modulo
    especificacao.loader.exec_module(modulo)
    return modulo


script = _carregar_o_script()


def _exemplo(nome: str) -> dict:
    return json.loads((EXEMPLOS / nome).read_text(encoding="utf-8"))


def _caso_de_extracao() -> dict:
    return {"livro": "Livro de Exemplo", "capitulo": 1, "tipo": "extracao", "texto": _exemplo("caso_de_exemplo.json")["texto"]}


class RelogioPorChamada:
    """Mede uma duração por chamada: a 1ª leitura (o início) devolve 0 e a 2ª (o fim), a duração da vez."""

    def __init__(self, duracoes: list[float]) -> None:
        self.duracoes = list(duracoes)
        self._inicio = True

    def __call__(self) -> float:
        if self._inicio:
            self._inicio = False
            return 0.0
        self._inicio = True
        return self.duracoes.pop(0)


class ProvedorMedido(ProvedorFalso):
    """O provedor falso que, como o de verdade, avisa o consumo de cada chamada por ``ao_usar``."""

    def __init__(self, ao_usar, custo: Decimal | None = Decimal("0.001"), em_cache: int | None = 100, **argumentos) -> None:
        super().__init__(**argumentos)
        self._ao_usar_medido = ao_usar
        self._custo = custo
        self._em_cache = em_cache

    def _avisar(self, operacao: str, modelo: str) -> None:
        self._ao_usar_medido(UsoDaChamada(operacao=operacao, modelo=modelo, custo=self._custo, tokens_em_cache=self._em_cache))

    def sugerir_estado(self, texto_capitulo, tipo, nome, descricao_do_elemento, estado_atual, modelo, aparencia_anterior=None, id_do_capitulo=None):
        resposta = super().sugerir_estado(texto_capitulo, tipo, nome, descricao_do_elemento, estado_atual, modelo, aparencia_anterior)
        self._avisar("estado", modelo)
        return resposta

    def fundamentar_frame(self, texto_capitulo, titulo, descricao, horario, clima, humor, participantes, modelo, trecho=None, id_do_capitulo=None):
        resposta = super().fundamentar_frame(texto_capitulo, titulo, descricao, horario, clima, humor, participantes, modelo, trecho)
        self._avisar("fundamentacao", modelo)
        return resposta

    def extrair_elementos(self, texto_capitulo, elementos_conhecidos, modelo, orientacao=None):
        resposta = super().extrair_elementos(texto_capitulo, elementos_conhecidos, modelo, orientacao)
        self._avisar("extracao", modelo)
        return resposta


def _juiz_de_exemplo(instrucao: str, pedido: str) -> str:
    """Um juiz bem comportado, que devolve as listas no tamanho dos dois casos de exemplo."""
    if "aparência" in instrucao:
        return json.dumps(
            {
                "fixos_presentes": [True, True, False],
                "fatos_dos_momentos_presentes": [True, True, True, True],
                "momentos_achados": [True, False],
                "invencoes": 1,
                "contradicoes": 0,
                "proibidos_presentes": 0,
            }
        )
    return json.dumps(
        {
            "presentes_achados": [True, True, False],
            "a_mais": 1,
            "onde_ok": [True, True],
            "luz_ok": [True, False],
            "acao_ok": [True],
            "proibidos_presentes": 0,
        }
    )


def _provedor_com_cena() -> dict:
    """Os argumentos de um provedor cuja extração cita uma frase que existe no texto de exemplo."""
    return {
        "cenas_sugeridas": [
            CenaSugerida(
                titulo="A saída",
                participantes=[ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Maren")],
                trecho_ancora="Maren acordou antes do sol",
            ),
            CenaSugerida(titulo="Sem citação", participantes=[ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Maren")]),
        ]
    }


def _fabricar(**argumentos):
    return lambda ao_usar: ProvedorMedido(ao_usar, **argumentos)


# --------------------------------------------------------------------------- #
# LM19: os casos
# --------------------------------------------------------------------------- #


def teste_lm19_os_dois_casos_de_exemplo_sao_validos() -> None:
    for nome, tipo in (("caso_de_exemplo.json", "estado"), ("caso_de_exemplo_dossie.json", "dossie")):
        caso = script.validar_caso(_exemplo(nome), nome)

        assert caso.tipo == tipo and caso.arquivo == nome


def teste_lm19_o_exemplo_tem_texto_inventado_e_nao_de_livro_real() -> None:
    for nome in ("caso_de_exemplo.json", "caso_de_exemplo_dossie.json"):
        assert "inventado" in _exemplo(nome)["livro"]


def teste_lm19_a_pasta_de_casos_reais_nao_vai_para_o_git() -> None:
    linhas = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "avaliacao/" in [linha.strip() for linha in linhas]


@pytest.mark.parametrize(
    "arquivo, apagar, campo",
    [
        ("caso_de_exemplo.json", ("elemento",), "elemento"),
        ("caso_de_exemplo.json", ("livro",), "livro"),
        ("caso_de_exemplo.json", ("capitulo",), "capitulo"),
        ("caso_de_exemplo.json", ("tipo",), "tipo"),
        ("caso_de_exemplo.json", ("esperado",), "esperado"),
        ("caso_de_exemplo.json", ("proibido",), "proibido"),
        ("caso_de_exemplo.json", ("esperado", "fixos"), "fixos"),
        ("caso_de_exemplo.json", ("esperado", "momentos"), "momentos"),
        ("caso_de_exemplo.json", ("elemento", "nome"), "nome"),
        ("caso_de_exemplo.json", ("elemento", "tipo"), "tipo"),
        ("caso_de_exemplo_dossie.json", ("cena",), "cena"),
        ("caso_de_exemplo_dossie.json", ("cena", "trecho"), "trecho"),
        ("caso_de_exemplo_dossie.json", ("participantes",), "participantes"),
        ("caso_de_exemplo_dossie.json", ("esperado", "presentes"), "presentes"),
        ("caso_de_exemplo_dossie.json", ("esperado", "luz"), "luz"),
        ("caso_de_exemplo_dossie.json", ("nao_deve_aparecer",), "nao_deve_aparecer"),
    ],
)
def teste_lm19_o_script_recusa_caso_com_campo_faltando_e_diz_qual(arquivo: str, apagar: tuple[str, ...], campo: str) -> None:
    dados = _exemplo(arquivo)
    alvo = dados
    for chave in apagar[:-1]:
        alvo = alvo[chave]
    del alvo[apagar[-1]]

    with pytest.raises(script.CasoInvalido) as erro:
        script.validar_caso(dados, "meu_caso.json")

    assert "meu_caso.json" in str(erro.value)
    assert f"falta o campo '{campo}'" in str(erro.value)


def teste_lm19_campo_do_tipo_errado_e_recusado() -> None:
    dados = _exemplo("caso_de_exemplo.json")
    dados["capitulo"] = "três"

    with pytest.raises(script.CasoInvalido, match="o campo 'capitulo' deve ser um número inteiro"):
        script.validar_caso(dados, "x.json")


def teste_lm19_momento_sem_fatos_diz_qual_momento() -> None:
    dados = _exemplo("caso_de_exemplo.json")
    del dados["esperado"]["momentos"][1]["fatos"]

    with pytest.raises(script.CasoInvalido, match=r"esperado\.momentos\[2\].*falta o campo 'fatos'"):
        script.validar_caso(dados, "x.json")


def teste_lm19_tipo_de_tarefa_desconhecido_e_recusado() -> None:
    dados = _exemplo("caso_de_exemplo.json")
    dados["tipo"] = "adivinhacao"

    with pytest.raises(script.CasoInvalido, match="'tipo' deve ser um de estado, dossie, extracao"):
        script.validar_caso(dados, "x.json")


def teste_lm19_tipo_de_elemento_desconhecido_e_recusado() -> None:
    dados = _exemplo("caso_de_exemplo.json")
    dados["elemento"]["tipo"] = "MONSTRO"

    with pytest.raises(script.CasoInvalido, match="PERSONAGEM"):
        script.validar_caso(dados, "x.json")


def teste_lm19_o_que_nao_e_objeto_e_recusado() -> None:
    with pytest.raises(script.CasoInvalido, match="deve ser um objeto JSON"):
        script.validar_caso(["lista"], "x.json")


def teste_lm19_a_extracao_so_exige_livro_capitulo_e_tipo() -> None:
    assert script.validar_caso(_caso_de_extracao(), "e.json").tipo == "extracao"
    with pytest.raises(script.CasoInvalido, match="falta o campo 'livro'"):
        script.validar_caso({"capitulo": 1, "tipo": "extracao"}, "e.json")


def teste_lm19_carregar_casos_le_a_pasta_em_ordem_e_filtra_pela_tarefa(tmp_path: Path) -> None:
    (tmp_path / "b_dossie.json").write_text((EXEMPLOS / "caso_de_exemplo_dossie.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "a_estado.json").write_text((EXEMPLOS / "caso_de_exemplo.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "leia-me.txt").write_text("não é caso", encoding="utf-8")

    todos = script.carregar_casos(tmp_path, ["estado", "dossie", "extracao"])
    so_estado = script.carregar_casos(tmp_path, ["estado"])

    assert [c.arquivo for c in todos] == ["a_estado.json", "b_dossie.json"]
    assert [c.arquivo for c in so_estado] == ["a_estado.json"]


def teste_lm19_um_caso_invalido_na_pasta_interrompe_e_diz_o_arquivo(tmp_path: Path) -> None:
    dados = _exemplo("caso_de_exemplo.json")
    del dados["proibido"]
    (tmp_path / "ruim.json").write_text(json.dumps(dados), encoding="utf-8")

    with pytest.raises(script.CasoInvalido, match="ruim.json.*falta o campo 'proibido'"):
        script.carregar_casos(tmp_path, ["estado"])


def teste_lm19_json_quebrado_e_recusado_com_o_nome_do_arquivo(tmp_path: Path) -> None:
    (tmp_path / "quebrado.json").write_text("{ não é json", encoding="utf-8")

    with pytest.raises(script.CasoInvalido, match="quebrado.json: não é um JSON válido"):
        script.carregar_casos(tmp_path, ["estado"])


def teste_lm19_o_texto_vem_do_proprio_caso() -> None:
    caso = script.validar_caso(_exemplo("caso_de_exemplo.json"), "x.json")

    assert script.texto_do_capitulo(caso, None, {}).startswith("Maren acordou antes do sol")


def teste_lm19_sem_texto_e_sem_pasta_dos_livros_o_erro_diz_o_que_fazer() -> None:
    dados = _exemplo("caso_de_exemplo.json")
    del dados["texto"]

    with pytest.raises(script.CasoInvalido, match="--epubs"):
        script.texto_do_capitulo(script.validar_caso(dados, "x.json"), None, {})


def teste_lm19_sem_texto_o_capitulo_vem_do_epub(tmp_path: Path) -> None:
    from imagineer.servicos.importacao_epub import extrair_epub
    from testes.teste_rotas_sugestoes import _epub

    conteudo = _epub(titulo="Livro de Teste")
    (tmp_path / "Livro de Teste (edicao 2).epub").write_bytes(conteudo)
    esperado = next(c.texto for c in extrair_epub(conteudo, "x.epub").capitulos if c.ordem == 1)
    dados = _exemplo("caso_de_exemplo.json")
    dados.update({"livro": "Livro de Teste", "capitulo": 1})
    del dados["texto"]
    caso = script.validar_caso(dados, "x.json")
    abertos: dict = {}

    assert script.texto_do_capitulo(caso, tmp_path, abertos) == esperado
    assert "Livro de Teste" in abertos  # o livro fica aberto para os próximos casos


def teste_lm19_livro_ou_capitulo_que_nao_existe_e_recusado(tmp_path: Path) -> None:
    from testes.teste_rotas_sugestoes import _epub

    (tmp_path / "Livro de Teste.epub").write_bytes(_epub(titulo="Livro de Teste"))
    dados = _exemplo("caso_de_exemplo.json")
    del dados["texto"]

    with pytest.raises(script.CasoInvalido, match="nenhum .epub começando por 'Livro Fantasma'"):
        script.texto_do_capitulo(script.validar_caso({**dados, "livro": "Livro Fantasma"}, "x.json"), tmp_path, {})
    with pytest.raises(script.CasoInvalido, match="não tem o capítulo 99"):
        script.texto_do_capitulo(script.validar_caso({**dados, "livro": "Livro de Teste", "capitulo": 99}, "x.json"), tmp_path, {})


# --------------------------------------------------------------------------- #
# LM18: uma tentativa
# --------------------------------------------------------------------------- #


def _executar(nome_do_caso: str = "caso_de_exemplo.json", provedor=None, juiz=_juiz_de_exemplo, relogio=None):
    usos: list[UsoDaChamada] = []
    provedor = provedor or ProvedorMedido(usos.append)
    caso = script.validar_caso(_exemplo(nome_do_caso), nome_do_caso)
    tentativa = script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], juiz, relogio or RelogioPorChamada([2.5]))
    return tentativa, usos


def teste_lm18_a_tentativa_de_estado_mede_custo_cache_latencia_e_qualidade() -> None:
    tentativa, _ = _executar()

    assert tentativa.erro is None and tentativa.json_valido and not tentativa.cortada
    assert tentativa.latencia == 2.5
    assert tentativa.custo == Decimal("0.001") and tentativa.tokens_em_cache == 100 and tentativa.chamadas == 1
    assert tentativa.julgada is True
    assert tentativa.qualidade["recall"] == pytest.approx(6 / 7)  # 2 de 3 fixos + 4 de 4 fatos dos momentos
    assert tentativa.qualidade["momentos"] == pytest.approx(0.5)
    assert tentativa.qualidade["invencoes"] == 1 and tentativa.qualidade["contradicoes"] == 0 and tentativa.qualidade["proibidos"] == 0


def teste_lm18_a_tentativa_de_dossie_mede_presentes_a_mais_e_fatos_da_cena() -> None:
    tentativa, _ = _executar("caso_de_exemplo_dossie.json")

    assert tentativa.qualidade["recall"] == pytest.approx(2 / 3)
    assert tentativa.qualidade["a_mais"] == 1
    assert tentativa.qualidade["fatos_da_cena"] == pytest.approx(4 / 5)  # onde 2/2, luz 1/2, ação 1/1
    assert tentativa.qualidade["proibidos"] == 0


def teste_lm18_o_script_chama_a_funcao_de_producao_com_o_que_o_caso_diz() -> None:
    usos: list[UsoDaChamada] = []
    provedor = ProvedorMedido(usos.append)
    caso = script.validar_caso(_exemplo("caso_de_exemplo.json"), "x.json")

    script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], None)

    chamada = provedor.chamadas_de_estado[0]
    assert (chamada["nome"], chamada["tipo"], chamada["descricao_do_elemento"], chamada["modelo"]) == (
        "Maren", TipoElemento.PERSONAGEM, "uma aldeã que mora sozinha perto do rio", "x/modelo",
    )
    assert chamada["texto_capitulo"] == caso.dados["texto"]


def teste_lm18_o_dossie_leva_a_cena_os_participantes_e_o_trecho() -> None:
    usos: list[UsoDaChamada] = []
    provedor = ProvedorMedido(usos.append)
    caso = script.validar_caso(_exemplo("caso_de_exemplo_dossie.json"), "x.json")

    script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], None)

    chamada = provedor.chamadas_de_fundamentacao[0]
    assert chamada["titulo"] == "A espera na taverna" and chamada["participantes"] == ["Maren"]
    assert chamada["trecho"].startswith("À mesa, Maren esperava")


def teste_lm18_sem_juiz_so_se_medem_json_corte_latencia_e_custo() -> None:
    tentativa, _ = _executar(juiz=None)

    assert tentativa.qualidade == {} and tentativa.julgada is False
    assert tentativa.custo == Decimal("0.001")


def teste_lm18_o_juiz_nao_e_chamado_quando_a_chamada_falhou() -> None:
    chamadas = []
    provedor = ProvedorMedido(lambda uso: None, erro=ErroDoProvedorIA("O modelo não devolveu JSON."))

    tentativa, _ = _executar(provedor=provedor, juiz=lambda i, p: chamadas.append(1) or "{}")

    assert chamadas == [] and tentativa.julgada is False


def teste_lm18_resposta_sem_json_conta_como_json_invalido() -> None:
    provedor = ProvedorMedido(lambda uso: None, erro=ErroDoProvedorIA("O modelo não devolveu JSON. Tente outro modelo."))

    tentativa, _ = _executar(provedor=provedor)

    assert tentativa.json_valido is False and tentativa.cortada is False and tentativa.erro


def teste_lm18_json_sem_os_campos_tambem_conta_como_json_invalido() -> None:
    provedor = ProvedorMedido(lambda uso: None, erro=ErroDoProvedorIA("O modelo devolveu um JSON sem os campos 'aparencia_fixa' e 'instante'."))

    tentativa, _ = _executar(provedor=provedor)

    assert tentativa.json_valido is False


def teste_lm18_resposta_cortada_e_contada_a_parte() -> None:
    provedor = ProvedorMedido(
        lambda uso: None, erro=ErroDoProvedorIA("A resposta do modelo x/modelo foi cortada por passar do limite de 2250 tokens.")
    )

    tentativa, _ = _executar(provedor=provedor)

    assert tentativa.cortada is True and tentativa.json_valido is True


def teste_lm18_outra_falha_nao_e_json_nem_corte() -> None:
    provedor = ProvedorMedido(lambda uso: None, erro=ErroDoProvedorIA("Não foi possível falar com o OpenRouter: caiu"))

    tentativa, _ = _executar(provedor=provedor)

    assert tentativa.erro and tentativa.json_valido is True and tentativa.cortada is False


def teste_lm18_juiz_que_nao_devolve_json_deixa_a_tentativa_sem_qualidade() -> None:
    tentativa, _ = _executar(juiz=lambda instrucao, pedido: "não sei")

    assert tentativa.qualidade == {} and tentativa.julgada is False and tentativa.erro is None


def teste_lm18_juiz_que_falha_nao_derruba_a_avaliacao() -> None:
    def juiz_quebrado(instrucao: str, pedido: str) -> str:
        raise ErroDoProvedorIA("juiz fora do ar")

    tentativa, _ = _executar(juiz=juiz_quebrado)

    assert tentativa.erro is None and tentativa.julgada is False


def teste_lm18_o_pedido_ao_juiz_leva_o_capitulo_a_descricao_e_os_fatos() -> None:
    vistos = []

    def juiz(instrucao: str, pedido: str) -> str:
        vistos.append(pedido)
        return _juiz_de_exemplo(instrucao, pedido)

    _executar(juiz=juiz)

    (pedido,) = vistos
    assert "CAPÍTULO:" in pedido and "Maren acordou antes do sol" in pedido
    assert "DESCRIÇÃO GERADA PARA Maren" in pedido and "watercolor-ready appearance description" in pedido
    assert "1. mulher alta" in pedido and "1. olhos azuis" in pedido  # fixos e proibidos, numerados


def teste_lm18_a_extracao_mede_as_metricas_de_citacao() -> None:
    usos: list[UsoDaChamada] = []
    provedor = ProvedorMedido(usos.append, **_provedor_com_cena())
    caso = script.validar_caso(_caso_de_extracao(), "e.json")

    tentativa = script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], _juiz_de_exemplo)

    assert tentativa.qualidade["citou"] == pytest.approx(0.5)  # 1 das 2 cenas citou
    assert tentativa.qualidade["literal"] == 1.0
    assert tentativa.qualidade["recall"] == pytest.approx(0.5)  # posição achada em 1 das 2 cenas
    assert tentativa.julgada is False  # a extração não precisa de juiz


def teste_lm18_citacao_que_nao_esta_no_texto_nao_e_literal_nem_achada() -> None:
    usos: list[UsoDaChamada] = []
    cena = CenaSugerida(
        titulo="Inventada", participantes=[ParticipanteSugerido(tipo=TipoElemento.PERSONAGEM, nome="Maren")], trecho_ancora="frase que não existe"
    )
    provedor = ProvedorMedido(usos.append, cenas_sugeridas=[cena])
    caso = script.validar_caso(_caso_de_extracao(), "e.json")

    tentativa = script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], None)

    assert tentativa.qualidade["citou"] == 1.0 and tentativa.qualidade["literal"] == 0.0 and tentativa.qualidade["recall"] == 0.0


def teste_lm18_o_custo_da_tentativa_soma_so_as_chamadas_dela() -> None:
    usos: list[UsoDaChamada] = []
    provedor = ProvedorMedido(usos.append)
    caso = script.validar_caso(_exemplo("caso_de_exemplo.json"), "x.json")

    primeira = script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], None)
    segunda = script.executar(caso, "x/modelo", provedor, usos, caso.dados["texto"], None)

    assert len(usos) == 2
    assert primeira.custo == segunda.custo == Decimal("0.001")


def teste_lm18_custo_nao_informado_fica_nulo_e_nunca_zero() -> None:
    tentativa, _ = _executar(provedor=ProvedorMedido(lambda uso: None, custo=None, em_cache=None))

    assert tentativa.custo is None and tentativa.tokens_em_cache == 0


# --------------------------------------------------------------------------- #
# LM18: o resumo e o relatório
# --------------------------------------------------------------------------- #


def _tentativa(tarefa="estado", latencia=1.0, custo="0.001", recall=0.8, json_valido=True, cortada=False, erro=None, **qualidade):
    return script.Tentativa(
        modelo="x/m", tarefa=tarefa, caso="c.json", json_valido=json_valido, cortada=cortada, erro=erro, latencia=latencia,
        custo=None if custo is None else Decimal(custo), tokens_em_cache=10, chamadas=1,
        qualidade={"recall": recall, **qualidade} if recall is not None else dict(qualidade), julgada=recall is not None,
    )


def teste_lm18_o_resumo_calcula_percentuais_mediana_e_p95() -> None:
    tentativas = [_tentativa(latencia=n) for n in range(1, 21)]  # 1 a 20 segundos
    tentativas[0] = _tentativa(latencia=1.0, json_valido=False, erro="O modelo não devolveu JSON")
    tentativas[1] = _tentativa(latencia=2.0, cortada=True, erro="foi cortada")

    resumo = script.resumir("x/m", "estado", tentativas)

    assert resumo.chamadas == 20
    assert resumo.json_valido == pytest.approx(19 / 20) and resumo.cortadas == pytest.approx(1 / 20)
    assert resumo.mediana == pytest.approx(10.5) and resumo.p95 == 19.0
    assert resumo.lento is True  # p95 acima de 15 s
    assert resumo.tokens_em_cache == 200


def teste_lm18_lento_so_quando_o_p95_passa_de_15_segundos() -> None:
    assert script.resumir("x/m", "estado", [_tentativa(latencia=15.0)] * 5).lento is False
    assert script.resumir("x/m", "estado", [_tentativa(latencia=15.1)] * 5).lento is True


def teste_lm18_o_custo_medio_ignora_o_que_nao_tem_custo() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(custo="0.002"), _tentativa(custo="0.004"), _tentativa(custo=None)])

    assert resumo.custo_medio == Decimal("0.003")


def teste_lm18_erro_que_nao_e_json_nem_corte_vai_para_a_contagem_de_erros() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(), _tentativa(erro="rede caiu"), _tentativa(json_valido=False, erro="JSON")])

    assert resumo.erros == 1


def teste_lm18_qualidade_por_dolar_e_o_recall_dividido_pelo_custo_medio() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(custo="0.002", recall=0.8)] * 3)

    assert resumo.qualidade == pytest.approx(0.8)
    assert resumo.qualidade_por_dolar == pytest.approx(0.8 / 0.002)


def teste_lm18_sem_juiz_nao_ha_qualidade_nem_qualidade_por_dolar() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(recall=None)] * 2)

    assert resumo.qualidade is None and resumo.qualidade_por_dolar is None


def teste_lm18_custo_zero_nao_divide_por_zero() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(custo="0", recall=0.9)])

    assert resumo.qualidade_por_dolar is None


def teste_lm18_os_detalhes_trazem_as_outras_metricas_do_juiz() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(invencoes=2.0, momentos=0.5), _tentativa(invencoes=0.0, momentos=1.0)])

    assert resumo.detalhes == {"invencoes": 1.0, "momentos": 0.75}


def _resumo(modelo: str, qualidade: float | None, custo: str | None) -> "script.Resumo":
    tentativas = [_tentativa(custo=custo, recall=qualidade)]
    resumo = script.resumir(modelo, "estado", tentativas)
    return resumo


def teste_lm18_a_tabela_sai_ordenada_por_qualidade_por_dolar() -> None:
    barato = _resumo("barato", 0.8, "0.001")  # 800 por dólar
    caro = _resumo("caro", 0.9, "0.010")  # 90 por dólar
    medio = _resumo("medio", 0.8, "0.004")  # 200 por dólar

    assert [r.modelo for r in script.ordenar([caro, barato, medio])] == ["barato", "medio", "caro"]


def teste_lm18_sem_custo_ou_sem_qualidade_vai_para_o_fim_por_qualidade() -> None:
    bom = _resumo("bom", 0.8, "0.001")
    gratis = _resumo("gratis", 0.95, None)
    sem_nota = _resumo("sem_nota", None, "0.001")
    gratis_pior = _resumo("gratis_pior", 0.5, None)

    assert [r.modelo for r in script.ordenar([sem_nota, gratis_pior, gratis, bom])] == ["bom", "gratis", "gratis_pior", "sem_nota"]


def teste_lm18_a_tabela_em_markdown_tem_cabecalho_preco_do_dia_e_marca_de_lento() -> None:
    resumo = script.resumir("x/m", "estado", [_tentativa(latencia=20.0)] * 3)
    resumo.preco_entrada, resumo.preco_saida = Decimal("0.0000001"), Decimal("0.0000004")

    tabela = script.tabela_em_markdown([resumo])
    linhas = tabela.strip().splitlines()

    assert linhas[0].startswith("| Modelo | Tarefa | Preço do dia")
    assert set(linhas[1]) <= set("| -")
    assert "| x/m | estado | 0.10 / 0.40 | 3 |" in linhas[2]
    assert "| lento |" in linhas[2]


def teste_lm18_sem_preco_no_catalogo_o_relatorio_mostra_traco() -> None:
    linha = script.linhas_do_relatorio([script.resumir("x/m", "estado", [_tentativa()])])[0]

    assert linha[2] == "- / -"


def teste_lm18_o_csv_tem_o_mesmo_cabecalho_e_as_mesmas_linhas(tmp_path: Path) -> None:
    import csv

    resumos = [_resumo("barato", 0.8, "0.001"), _resumo("caro", 0.9, "0.010")]
    caminho = tmp_path / "r.csv"

    script.escrever_csv(resumos, caminho)

    with open(caminho, encoding="utf-8", newline="") as arquivo:
        linhas = list(csv.reader(arquivo))
    assert linhas[0] == script.CABECALHO
    assert [linha[0] for linha in linhas[1:]] == ["barato", "caro"]


# --------------------------------------------------------------------------- #
# LM18: a avaliação inteira
# --------------------------------------------------------------------------- #


def _casos() -> list:
    return [
        script.validar_caso(_exemplo("caso_de_exemplo.json"), "a_estado.json"),
        script.validar_caso(_exemplo("caso_de_exemplo_dossie.json"), "b_dossie.json"),
        script.validar_caso(_caso_de_extracao(), "c_extracao.json"),
    ]


def _capacidades(id_: str, entrada: str, saida: str) -> Capacidades:
    return Capacidades(
        id=id_, contexto=1000, saida_maxima=None, estruturado=False, raciocinio_suportado=False, raciocinio_obrigatorio=False, esforcos=(),
        preco_entrada=Decimal(entrada), preco_saida=Decimal(saida), preco_cache_leitura=None, preco_cache_escrita=None, gratuito=False, moderado=False,
    )


def teste_lm18_a_avaliacao_roda_cada_modelo_tarefa_caso_e_repeticao() -> None:
    provedores: list[ProvedorMedido] = []

    def fabricar(ao_usar):
        provedores.append(ProvedorMedido(ao_usar, **_provedor_com_cena()))
        return provedores[-1]

    resumos = script.avaliar(
        _casos(), ["m/um", "m/dois"], lambda caso: caso.dados["texto"], fabricar, _juiz_de_exemplo, repeticoes=3,
        consultar_capacidades=lambda m: None, avisar=lambda *_: None,
    )

    assert sorted((r.modelo, r.tarefa) for r in resumos) == sorted(
        (m, t) for m in ("m/um", "m/dois") for t in ("estado", "dossie", "extracao")
    )
    assert all(r.chamadas == 3 for r in resumos)
    assert len(provedores) == 2  # um provedor por modelo
    assert [len(p.chamadas_de_estado) for p in provedores] == [3, 3]
    assert [len(p.chamadas_de_fundamentacao) for p in provedores] == [3, 3]
    assert [len(p.chamadas_de_extracao) for p in provedores] == [3, 3]


def teste_lm18_so_aparece_a_tarefa_que_tem_caso() -> None:
    resumos = script.avaliar(
        _casos()[:1], ["m/um"], lambda caso: caso.dados["texto"], _fabricar(), _juiz_de_exemplo, repeticoes=1,
        consultar_capacidades=lambda m: None, avisar=lambda *_: None,
    )

    assert [(r.modelo, r.tarefa) for r in resumos] == [("m/um", "estado")]


def teste_lm18_o_preco_do_dia_vem_do_catalogo_ao_vivo() -> None:
    consultados = []

    def consultar(modelo: str):
        consultados.append(modelo)
        return _capacidades(modelo, "0.0000003", "0.0000025")

    resumos = script.avaliar(
        _casos()[:1], ["m/um"], lambda caso: caso.dados["texto"], _fabricar(), None, repeticoes=1,
        consultar_capacidades=consultar, avisar=lambda *_: None,
    )

    assert consultados == ["m/um"]
    assert (resumos[0].preco_entrada, resumos[0].preco_saida) == (Decimal("0.0000003"), Decimal("0.0000025"))


def teste_lm18_a_avaliacao_conta_o_custo_real_de_cada_modelo() -> None:
    def fabricar_pelo_modelo(ao_usar):
        return ProvedorMedido(ao_usar, custo=Decimal("0.002"))

    resumos = script.avaliar(
        _casos()[:1], ["m/um"], lambda caso: caso.dados["texto"], fabricar_pelo_modelo, _juiz_de_exemplo, repeticoes=2,
        consultar_capacidades=lambda m: None, avisar=lambda *_: None,
    )

    assert resumos[0].custo_medio == Decimal("0.002")


# --------------------------------------------------------------------------- #
# A linha de comando
# --------------------------------------------------------------------------- #


def _pasta_com_os_exemplos(tmp_path: Path) -> Path:
    pasta = tmp_path / "casos"
    pasta.mkdir()
    for nome in ("caso_de_exemplo.json", "caso_de_exemplo_dossie.json"):
        (pasta / nome).write_text((EXEMPLOS / nome).read_text(encoding="utf-8"), encoding="utf-8")
    return pasta


def teste_lm18_o_script_roda_com_provedor_falso_e_caso_de_exemplo_e_gera_a_tabela(tmp_path: Path) -> None:
    pasta = _pasta_com_os_exemplos(tmp_path)
    saida = tmp_path / "relatorio.md"
    avisos: list[str] = []

    resumos = script.main(
        ["--casos", str(pasta), "--repeticoes", "2", "--juiz", "j/juiz", "--saida", str(saida), "m/um", "m/dois"],
        fabricar_provedor=_fabricar(), juiz=_juiz_de_exemplo, consultar_capacidades=lambda m: _capacidades(m, "0.0000001", "0.0000004"),
        avisar=avisos.append,
    )

    assert len(resumos) == 4  # 2 modelos x (estado, dossiê)
    tabela = saida.read_text(encoding="utf-8")
    assert tabela.startswith("| Modelo | Tarefa |")
    assert "m/um" in tabela and "m/dois" in tabela and "0.10 / 0.40" in tabela
    assert saida.with_suffix(".csv").exists()
    assert any("Relatório em" in aviso for aviso in avisos)


def teste_lm18_a_opcao_tarefas_limita_o_que_roda(tmp_path: Path) -> None:
    pasta = _pasta_com_os_exemplos(tmp_path)

    resumos = script.main(
        ["--casos", str(pasta), "--tarefas", "dossie", "--repeticoes", "1", "m/um"],
        fabricar_provedor=_fabricar(), consultar_capacidades=lambda m: None, avisar=lambda *_: None,
    )

    assert [r.tarefa for r in resumos] == ["dossie"]


def teste_lm18_tarefa_desconhecida_na_linha_de_comando_e_recusada(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(_pasta_com_os_exemplos(tmp_path)), "--tarefas", "adivinhar", "m/um"], fabricar_provedor=_fabricar())

    assert saida.value.code == 2


def teste_lm18_repeticoes_menor_que_um_e_recusada(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(_pasta_com_os_exemplos(tmp_path)), "--repeticoes", "0", "m/um"], fabricar_provedor=_fabricar())

    assert saida.value.code == 2


def teste_lm18_caso_invalido_para_tudo_antes_de_gastar_e_diz_o_campo(tmp_path: Path) -> None:
    pasta = _pasta_com_os_exemplos(tmp_path)
    dados = _exemplo("caso_de_exemplo.json")
    del dados["elemento"]
    (pasta / "ruim.json").write_text(json.dumps(dados), encoding="utf-8")
    provedores = []

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(pasta), "m/um"], fabricar_provedor=lambda ao_usar: provedores.append(1) or ProvedorMedido(ao_usar))

    assert "ruim.json" in str(saida.value) and "falta o campo 'elemento'" in str(saida.value)
    assert provedores == []  # nenhum provedor foi criado: nada foi gasto


def teste_lm18_pasta_sem_casos_da_tarefa_pedida_para_com_mensagem(tmp_path: Path) -> None:
    vazia = tmp_path / "vazia"
    vazia.mkdir()

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(vazia), "m/um"], fabricar_provedor=_fabricar())

    assert "Nenhum caso" in str(saida.value)


def teste_lm18_caso_sem_texto_e_sem_epubs_para_antes_de_gastar(tmp_path: Path) -> None:
    pasta = tmp_path / "casos"
    pasta.mkdir()
    dados = _exemplo("caso_de_exemplo.json")
    del dados["texto"]
    (pasta / "sem_texto.json").write_text(json.dumps(dados), encoding="utf-8")

    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(pasta), "m/um"], fabricar_provedor=_fabricar())

    assert "--epubs" in str(saida.value)


def teste_lm18_nenhum_teste_fala_com_o_openrouter(tmp_path: Path, monkeypatch) -> None:
    """Com o provedor injetado, o script nunca cria o ``ProvedorOpenRouter``, nem pede a chave."""

    def proibido(*args, **kwargs):
        raise AssertionError("o script tentou falar com o OpenRouter")

    monkeypatch.setattr(script, "ProvedorOpenRouter", proibido)

    resumos = script.main(
        ["--casos", str(_pasta_com_os_exemplos(tmp_path)), "--repeticoes", "1", "m/um"],
        fabricar_provedor=_fabricar(), consultar_capacidades=lambda m: None, avisar=lambda *_: None,
    )

    assert resumos


def teste_lm18_sem_chave_do_openrouter_o_script_para_com_mensagem(tmp_path: Path) -> None:
    """Sem provedor injetado, o script de verdade pede a chave (os testes zeram as variáveis de ambiente)."""
    with pytest.raises(SystemExit) as saida:
        script.main(["--casos", str(_pasta_com_os_exemplos(tmp_path)), "m/um"], avisar=lambda *_: None)

    assert "Sem chave do OpenRouter" in str(saida.value)
