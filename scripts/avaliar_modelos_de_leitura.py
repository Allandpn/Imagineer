"""Compara modelos na leitura do livro, com IA real e casos que o Allan escolheu (item 4.10, LM18 e LM19).

Para cada (modelo, tarefa, caso, repetição) chama a **função de produção** do ``ProvedorOpenRouter`` (``sugerir_estado``,
``fundamentar_frame``, ``extrair_elementos``): o que se mede é o **prompt e os parâmetros reais**, não uma imitação.

**Métricas por modelo e tarefa:** JSON válido (%); respostas cortadas (%); latência (mediana e p95); custo médio **real** (o ``usage.cost`` que o
OpenRouter informa) e tokens lidos do cache; e a **qualidade**, julgada por um modelo (``--juiz``, temperatura 0) contra o caso:

- ``estado``: fatos esperados presentes (recall), invenções, contradições, momentos achados (item 4.9, FL3) e coisas proibidas;
- ``dossie``: dos presentes esperados quantos vieram (recall), quantos **a mais** vieram, onde/luz/ação com os fatos esperados, e o que não devia aparecer;
- ``extracao``: as métricas de citação de ``medir_citacao_de_cena.py`` (a IA citou, a citação é literal, o servidor achou a posição).

**Saída:** uma tabela em Markdown (``--saida``) e um CSV ao lado, ordenados por **qualidade por dólar**, com a coluna "lento" quando o p95 passa de
15 s e o **preço do dia** de cada modelo, lido do catálogo ao vivo.

**Gasta cota do OpenRouter** e grava cada chamada em ``usos_ia`` (o mesmo caminho do servidor). Os casos ficam **fora do git** (``avaliacao/``,
trechos de livros têm direitos autorais); o repositório leva só ``scripts/exemplos/``, com texto inventado. Quem escreve os casos é o Allan.

Uso (na raiz do projeto, com o banco no ar):

    ./venv/Scripts/python.exe scripts/avaliar_modelos_de_leitura.py --casos avaliacao --epubs D:/Livros \\
        --tarefas estado,dossie,extracao --repeticoes 3 --juiz anthropic/claude-haiku-4.5 --saida relatorio.md \\
        google/gemini-2.5-flash-lite openai/gpt-4.1-mini

Formato dos casos (um por arquivo ``.json``): ver ``scripts/exemplos/``. O campo opcional ``texto`` traz o capítulo no próprio caso; sem ele, o
script o procura em ``--epubs`` pelo ``livro`` e pelo número do ``capitulo``.
"""

import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imagineer.ia.catalogo_de_texto import Capacidades, obter_capacidades  # noqa: E402
from imagineer.ia.openrouter import ProvedorOpenRouter, _extrair_json  # noqa: E402
from imagineer.ia.provedor import ErroDoProvedorIA, UsoDaChamada  # noqa: E402
from imagineer.modelos import TipoElemento  # noqa: E402
from imagineer.servicos.posicao_no_texto import posicao_da_citacao  # noqa: E402

TAREFAS = ("estado", "dossie", "extracao")
TIPOS_DO_SCRIPT_DE_FIDELIDADE = ("cena", "retrato")
"""Os casos de ``avaliar_fidelidade.py`` (item 4.9, FL13.3) podem estar na mesma pasta: este script os ignora."""
LIMITE_DE_LENTO = 15.0
"""Segundos de p95 acima dos quais o modelo é marcado "lento" (LM18, LM20)."""


# --------------------------------------------------------------------------- #
# Os casos (LM19)
# --------------------------------------------------------------------------- #


class CasoInvalido(ValueError):
    """Um caso com campo faltando ou do tipo errado. A mensagem diz o arquivo e o campo."""


@dataclass(frozen=True)
class Caso:
    arquivo: str
    tipo: str
    dados: dict


def _exigir(dados: dict, campo: str, tipo: type, onde: str) -> None:
    if campo not in dados:
        raise CasoInvalido(f"{onde}: falta o campo '{campo}'")
    if not isinstance(dados[campo], tipo) or (tipo is int and isinstance(dados[campo], bool)):
        nome = {str: "um texto", int: "um número inteiro", list: "uma lista", dict: "um objeto"}[tipo]
        raise CasoInvalido(f"{onde}: o campo '{campo}' deve ser {nome}")


def validar_caso(dados: object, arquivo: str) -> Caso:
    """Confere o caso e o devolve. Levanta ``CasoInvalido`` dizendo **qual** campo falta ou está errado."""
    if not isinstance(dados, dict):
        raise CasoInvalido(f"{arquivo}: o caso deve ser um objeto JSON")
    _exigir(dados, "tipo", str, arquivo)
    if dados["tipo"] not in TAREFAS:
        raise CasoInvalido(f"{arquivo}: o campo 'tipo' deve ser um de {', '.join(TAREFAS)} (veio '{dados['tipo']}')")
    _exigir(dados, "livro", str, arquivo)
    _exigir(dados, "capitulo", int, arquivo)
    if "texto" in dados:
        _exigir(dados, "texto", str, arquivo)

    if dados["tipo"] == "estado":
        _exigir(dados, "elemento", dict, arquivo)
        _exigir(dados["elemento"], "nome", str, f"{arquivo} (elemento)")
        _exigir(dados["elemento"], "tipo", str, f"{arquivo} (elemento)")
        if dados["elemento"]["tipo"] not in TipoElemento.__members__:
            raise CasoInvalido(f"{arquivo} (elemento): o campo 'tipo' deve ser um de {', '.join(TipoElemento.__members__)}")
        _exigir(dados, "esperado", dict, arquivo)
        _exigir(dados["esperado"], "fixos", list, f"{arquivo} (esperado)")
        _exigir(dados["esperado"], "momentos", list, f"{arquivo} (esperado)")
        for posicao, momento in enumerate(dados["esperado"]["momentos"], 1):
            if not isinstance(momento, dict):
                raise CasoInvalido(f"{arquivo} (esperado.momentos[{posicao}]): deve ser um objeto")
            _exigir(momento, "comeca_em", str, f"{arquivo} (esperado.momentos[{posicao}])")
            _exigir(momento, "fatos", list, f"{arquivo} (esperado.momentos[{posicao}])")
        _exigir(dados, "proibido", list, arquivo)
    elif dados["tipo"] == "dossie":
        _exigir(dados, "cena", dict, arquivo)
        for campo in ("titulo", "descricao", "trecho"):
            _exigir(dados["cena"], campo, str, f"{arquivo} (cena)")
        _exigir(dados, "participantes", list, arquivo)
        _exigir(dados, "esperado", dict, arquivo)
        _exigir(dados["esperado"], "presentes", list, f"{arquivo} (esperado)")
        for posicao, presente in enumerate(dados["esperado"]["presentes"], 1):
            if not isinstance(presente, dict):
                raise CasoInvalido(f"{arquivo} (esperado.presentes[{posicao}]): deve ser um objeto")
            _exigir(presente, "nome", str, f"{arquivo} (esperado.presentes[{posicao}])")
            _exigir(presente, "caracteristicas", list, f"{arquivo} (esperado.presentes[{posicao}])")
        for campo in ("onde", "luz", "acao"):
            _exigir(dados["esperado"], campo, list, f"{arquivo} (esperado)")
        _exigir(dados, "nao_deve_aparecer", list, arquivo)
    return Caso(arquivo=arquivo, tipo=dados["tipo"], dados=dados)


def carregar_casos(pasta: Path, tarefas: Sequence[str]) -> list[Caso]:
    """Os casos de ``pasta`` das ``tarefas`` pedidas, em ordem de nome. Um caso inválido interrompe tudo, dizendo qual."""
    casos = []
    for caminho in sorted(Path(pasta).glob("*.json")):
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            raise CasoInvalido(f"{caminho.name}: não é um JSON válido ({erro})") from erro
        if isinstance(dados, dict) and dados.get("tipo") in TIPOS_DO_SCRIPT_DE_FIDELIDADE:
            continue  # é caso do outro script
        caso = validar_caso(dados, caminho.name)
        if caso.tipo in tarefas:
            casos.append(caso)
    return casos


def texto_do_capitulo(caso: Caso, pasta_dos_epubs: Path | None, livros_abertos: dict) -> str:
    """O capítulo do caso: o ``texto`` do próprio caso, ou o capítulo ``capitulo`` do ``livro`` achado em ``pasta_dos_epubs``."""
    if caso.dados.get("texto"):
        return caso.dados["texto"]
    if pasta_dos_epubs is None:
        raise CasoInvalido(f"{caso.arquivo}: o caso não traz 'texto' e não foi informada a pasta dos livros (--epubs)")

    from imagineer.servicos.importacao_epub import extrair_epub

    nome = caso.dados["livro"]
    if nome not in livros_abertos:
        arquivo = next(Path(pasta_dos_epubs).glob(f"{nome}*.epub"), None)
        if arquivo is None:
            raise CasoInvalido(f"{caso.arquivo}: nenhum .epub começando por '{nome}' em {pasta_dos_epubs}")
        livros_abertos[nome] = extrair_epub(arquivo.read_bytes(), arquivo.name)
    for capitulo in livros_abertos[nome].capitulos:
        if capitulo.ordem == caso.dados["capitulo"]:
            return capitulo.texto
    raise CasoInvalido(f"{caso.arquivo}: o livro '{nome}' não tem o capítulo {caso.dados['capitulo']}")


# --------------------------------------------------------------------------- #
# O juiz
# --------------------------------------------------------------------------- #

Juiz = Callable[[str, str], str]
"""``juiz(instrucao, pedido) -> resposta``: um modelo, em temperatura 0, que confere o resultado contra o caso."""

_INSTRUCAO_DO_JUIZ_DE_ESTADO = """\
Você confere a descrição de aparência de um personagem, gerada por uma IA, contra fatos esperados. Seja literal: um fato só está "presente" \
se a descrição diz isso (com outras palavras, tudo bem). Responda APENAS com um objeto JSON neste formato:

{"fixos_presentes": [true, false], "fatos_dos_momentos_presentes": [true], "momentos_achados": [true], \
"invencoes": 0, "contradicoes": 0, "proibidos_presentes": 0}

- "fixos_presentes": um true/false para CADA fato fixo esperado, na ordem da lista.
- "fatos_dos_momentos_presentes": um true/false para CADA fato dos momentos, na ordem em que aparecem (momento 1, depois 2...).
- "momentos_achados": um true/false para CADA momento esperado: a descrição distingue esse momento (roupa e estado dele)?
- "invencoes": quantos detalhes visuais a descrição afirma que o capítulo NÃO sustenta.
- "contradicoes": quantas afirmações da descrição contradizem o capítulo.
- "proibidos_presentes": quantas das coisas PROIBIDAS aparecem na descrição.
"""

_INSTRUCAO_DO_JUIZ_DE_DOSSIE = """\
Você confere o contexto de uma cena, gerado por uma IA, contra o que deveria aparecer. Seja literal: algo só está "presente" se o contexto \
diz isso (com outras palavras, tudo bem). Responda APENAS com um objeto JSON neste formato:

{"presentes_achados": [true], "a_mais": 0, "onde_ok": [true], "luz_ok": [true], "acao_ok": [true], "proibidos_presentes": 0}

- "presentes_achados": um true/false para CADA presente esperado (quem ou o que está na cena, com as características dadas), na ordem.
- "a_mais": quantas pessoas, criaturas ou objetos o contexto cita que NÃO estão na lista de presentes esperados.
- "onde_ok", "luz_ok", "acao_ok": um true/false para CADA fato esperado de cada lista, na ordem.
- "proibidos_presentes": quantas das coisas que NÃO deviam aparecer aparecem no contexto.
"""


def _lista(titulo: str, itens: Sequence[str]) -> str:
    return f"{titulo}:\n" + ("\n".join(f"{n}. {item}" for n, item in enumerate(itens, 1)) if itens else "(nenhum)")


def _proporcao(valores: object) -> float | None:
    """Fração de ``true`` numa lista de booleanos; ``None`` se não há nada a contar ou o juiz não devolveu uma lista."""
    if not isinstance(valores, list) or not valores:
        return None
    return sum(1 for v in valores if v is True) / len(valores)


def _contagem(valor: object) -> float | None:
    return float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor >= 0 else None


def _julgar_estado(caso: Caso, texto: str, descricao: str, juiz: Juiz) -> dict[str, float]:
    esperado = caso.dados["esperado"]
    fatos_dos_momentos = [fato for momento in esperado["momentos"] for fato in momento["fatos"]]
    pedido = "\n\n".join(
        [
            f"CAPÍTULO:\n{texto}",
            f"DESCRIÇÃO GERADA PARA {caso.dados['elemento']['nome']}:\n{descricao}",
            _lista("FATOS FIXOS ESPERADOS", esperado["fixos"]),
            _lista("MOMENTOS ESPERADOS", [f"começa em: {m['comeca_em']}" for m in esperado["momentos"]]),
            _lista("FATOS DOS MOMENTOS (em ordem)", fatos_dos_momentos),
            _lista("COISAS PROIBIDAS", caso.dados["proibido"]),
        ]
    )
    bruto = _extrair_json(juiz(_INSTRUCAO_DO_JUIZ_DE_ESTADO, pedido))
    if bruto is None:
        return {}
    fixos, dos_momentos = bruto.get("fixos_presentes"), bruto.get("fatos_dos_momentos_presentes")
    esperados = len(esperado["fixos"]) + len(fatos_dos_momentos)
    achados = sum(1 for lista in (fixos, dos_momentos) if isinstance(lista, list) for v in lista if v is True)
    metricas = {
        "recall": achados / esperados if esperados else None,
        "momentos": _proporcao(bruto.get("momentos_achados")),
        "invencoes": _contagem(bruto.get("invencoes")),
        "contradicoes": _contagem(bruto.get("contradicoes")),
        "proibidos": _contagem(bruto.get("proibidos_presentes")),
    }
    return {nome: valor for nome, valor in metricas.items() if valor is not None}


def _julgar_dossie(caso: Caso, texto: str, contexto: str, juiz: Juiz) -> dict[str, float]:
    esperado = caso.dados["esperado"]
    presentes = [f"{p['nome']}: {'; '.join(p['caracteristicas'])}" for p in esperado["presentes"]]
    pedido = "\n\n".join(
        [
            f"CAPÍTULO:\n{texto}",
            f"CENA: {caso.dados['cena']['titulo']} — {caso.dados['cena']['descricao']}",
            f"CONTEXTO GERADO:\n{contexto}",
            _lista("PRESENTES ESPERADOS", presentes),
            _lista("FATOS ESPERADOS DO LUGAR", esperado["onde"]),
            _lista("FATOS ESPERADOS DA LUZ", esperado["luz"]),
            _lista("FATOS ESPERADOS DA AÇÃO", esperado["acao"]),
            _lista("O QUE NÃO DEVE APARECER", caso.dados["nao_deve_aparecer"]),
        ]
    )
    bruto = _extrair_json(juiz(_INSTRUCAO_DO_JUIZ_DE_DOSSIE, pedido))
    if bruto is None:
        return {}
    fatos = [v for chave in ("onde_ok", "luz_ok", "acao_ok") if isinstance(bruto.get(chave), list) for v in bruto[chave]]
    metricas = {
        "recall": _proporcao(bruto.get("presentes_achados")),
        "a_mais": _contagem(bruto.get("a_mais")),
        "fatos_da_cena": _proporcao(fatos),
        "proibidos": _contagem(bruto.get("proibidos_presentes")),
    }
    return {nome: valor for nome, valor in metricas.items() if valor is not None}


# --------------------------------------------------------------------------- #
# Uma tentativa
# --------------------------------------------------------------------------- #


@dataclass
class Tentativa:
    """O resultado de **uma** chamada de produção (um modelo, uma tarefa, um caso, uma repetição)."""

    modelo: str
    tarefa: str
    caso: str
    json_valido: bool = True
    cortada: bool = False
    erro: str | None = None
    """A mensagem, se a chamada falhou por qualquer motivo (inclusive JSON ruim e resposta cortada)."""
    latencia: float = 0.0
    custo: Decimal | None = None
    tokens_em_cache: int = 0
    chamadas: int = 0
    qualidade: dict[str, float] = field(default_factory=dict)
    julgada: bool = False
    """Se o juiz avaliou esta tentativa (falhou, ou não há ``--juiz``: ``False``)."""


def _chamar(caso: Caso, modelo: str, provedor, texto: str) -> tuple[str, dict]:
    """Chama a função de produção do ``caso.tipo``. Devolve ``(texto produzido, medidas próprias da tarefa)``."""
    if caso.tipo == "estado":
        elemento = caso.dados["elemento"]
        estado = provedor.sugerir_estado(
            texto, TipoElemento[elemento["tipo"]], elemento["nome"], elemento.get("identidade"), None, modelo
        )
        return estado.descricao, {}

    if caso.tipo == "dossie":
        cena = caso.dados["cena"]
        fundamentado = provedor.fundamentar_frame(
            texto, cena["titulo"], cena["descricao"], None, None, None, list(caso.dados["participantes"]), modelo, trecho=cena["trecho"]
        )
        return fundamentado.contexto, {}

    extracao = provedor.extrair_elementos(texto, [], modelo)
    cenas = len(extracao.cenas)
    citou = literal = achada = 0
    for cena in extracao.cenas:
        citacao = (cena.trecho_ancora or "").strip()
        if not citacao:
            continue
        citou += 1
        literal += texto.find(citacao) != -1
        achada += posicao_da_citacao(texto, citacao) is not None
    medidas = {
        "citou": citou / cenas if cenas else None,
        "literal": literal / citou if citou else None,
        "recall": achada / cenas if cenas else None,  # a "qualidade" da extração: cenas cuja posição o servidor achou
    }
    return "", {nome: valor for nome, valor in medidas.items() if valor is not None}


def executar(
    caso: Caso, modelo: str, provedor, usos: list[UsoDaChamada], texto: str, juiz: Juiz | None, relogio: Callable[[], float] = time.perf_counter
) -> Tentativa:
    """Uma chamada de produção, medida. ``usos`` é a lista em que o ``ao_usar`` do ``provedor`` anota cada resposta."""
    tentativa = Tentativa(modelo=modelo, tarefa=caso.tipo, caso=caso.arquivo)
    antes = len(usos)
    inicio = relogio()
    produzido, medidas = "", {}
    try:
        produzido, medidas = _chamar(caso, modelo, provedor, texto)
    except ErroDoProvedorIA as erro:
        tentativa.erro = str(erro)
        tentativa.cortada = "foi cortada" in tentativa.erro
        tentativa.json_valido = not (("JSON" in tentativa.erro) and not tentativa.cortada)
    tentativa.latencia = relogio() - inicio

    usadas = usos[antes:]
    tentativa.chamadas = len(usadas)
    custos = [u.custo for u in usadas if u.custo is not None]
    tentativa.custo = sum(custos, Decimal(0)) if custos else None
    tentativa.tokens_em_cache = sum(u.tokens_em_cache or 0 for u in usadas)

    tentativa.qualidade.update(medidas)
    if tentativa.erro is None and juiz is not None and caso.tipo in ("estado", "dossie"):
        julgar = _julgar_estado if caso.tipo == "estado" else _julgar_dossie
        try:
            julgado = julgar(caso, texto, produzido, juiz)
        except ErroDoProvedorIA:
            julgado = {}
        tentativa.qualidade.update(julgado)
        tentativa.julgada = bool(julgado)
    return tentativa


# --------------------------------------------------------------------------- #
# O relatório
# --------------------------------------------------------------------------- #


def _percentil(valores: Sequence[float], p: float) -> float:
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p * len(ordenados)) - 1)]


def _media(valores: Sequence[float]) -> float | None:
    return sum(valores) / len(valores) if valores else None


@dataclass
class Resumo:
    """As métricas de um (modelo, tarefa), somadas sobre todos os casos e repetições."""

    modelo: str
    tarefa: str
    chamadas: int
    json_valido: float
    cortadas: float
    erros: int
    mediana: float
    p95: float
    lento: bool
    custo_medio: Decimal | None
    tokens_em_cache: int
    qualidade: float | None
    detalhes: dict[str, float]
    qualidade_por_dolar: float | None
    preco_entrada: Decimal | None = None
    preco_saida: Decimal | None = None


def resumir(modelo: str, tarefa: str, tentativas: Sequence[Tentativa]) -> Resumo:
    """Junta as tentativas de um (modelo, tarefa) numa linha do relatório."""
    n = len(tentativas)
    latencias = [t.latencia for t in tentativas]
    custos = [t.custo for t in tentativas if t.custo is not None]
    custo_medio = sum(custos, Decimal(0)) / len(custos) if custos else None

    nomes = sorted({nome for t in tentativas for nome in t.qualidade})
    medias = {nome: _media([t.qualidade[nome] for t in tentativas if nome in t.qualidade]) for nome in nomes}
    qualidade = medias.get("recall")

    por_dolar = None
    if qualidade is not None and custo_medio:
        por_dolar = qualidade / float(custo_medio)

    return Resumo(
        modelo=modelo,
        tarefa=tarefa,
        chamadas=n,
        json_valido=sum(1 for t in tentativas if t.json_valido) / n,
        cortadas=sum(1 for t in tentativas if t.cortada) / n,
        erros=sum(1 for t in tentativas if t.erro is not None and t.json_valido and not t.cortada),
        mediana=statistics.median(latencias),
        p95=_percentil(latencias, 0.95),
        lento=_percentil(latencias, 0.95) > LIMITE_DE_LENTO,
        custo_medio=custo_medio,
        tokens_em_cache=sum(t.tokens_em_cache for t in tentativas),
        qualidade=qualidade,
        detalhes={nome: valor for nome, valor in medias.items() if nome != "recall" and valor is not None},
        qualidade_por_dolar=por_dolar,
    )


def ordenar(resumos: Sequence[Resumo]) -> list[Resumo]:
    """Por qualidade por dólar, a maior primeiro; sem custo informado (ou sem qualidade) vai para o fim, por qualidade."""
    return sorted(resumos, key=lambda r: (r.qualidade_por_dolar is None, -(r.qualidade_por_dolar or 0), -(r.qualidade or 0), r.modelo))


def _pct(valor: float | None) -> str:
    return "-" if valor is None else f"{100 * valor:.0f}%"


def _dolar(valor: Decimal | float | None) -> str:
    return "-" if valor is None else f"{valor:.4f}"


def _preco_por_milhao(preco: Decimal | None) -> str:
    return "-" if preco is None else f"{preco * 1_000_000:.2f}"


def _texto_dos_detalhes(detalhes: dict[str, float]) -> str:
    if not detalhes:
        return "-"
    return ", ".join(f"{nome} {_pct(valor) if nome in ('momentos', 'fatos_da_cena', 'citou', 'literal') else f'{valor:.1f}'}" for nome, valor in detalhes.items())


CABECALHO = [
    "Modelo", "Tarefa", "Preço do dia (US$/M entrada / saída)", "Chamadas", "JSON válido", "Cortadas", "Mediana (s)", "p95 (s)", "Lento",
    "Custo médio (US$)", "Tokens em cache", "Qualidade (recall)", "Detalhes", "Qualidade por US$",
]


def linhas_do_relatorio(resumos: Sequence[Resumo]) -> list[list[str]]:
    linhas = []
    for r in ordenar(resumos):
        linhas.append(
            [
                r.modelo, r.tarefa, f"{_preco_por_milhao(r.preco_entrada)} / {_preco_por_milhao(r.preco_saida)}", str(r.chamadas),
                _pct(r.json_valido), _pct(r.cortadas), f"{r.mediana:.1f}", f"{r.p95:.1f}", "lento" if r.lento else "", _dolar(r.custo_medio),
                str(r.tokens_em_cache), _pct(r.qualidade), _texto_dos_detalhes(r.detalhes),
                "-" if r.qualidade_por_dolar is None else f"{r.qualidade_por_dolar:.0f}",
            ]
        )
    return linhas


def tabela_em_markdown(resumos: Sequence[Resumo]) -> str:
    linhas = [CABECALHO, *linhas_do_relatorio(resumos)]
    corpo = ["| " + " | ".join(celula.replace("|", "\\|") for celula in linha) + " |" for linha in linhas]
    corpo.insert(1, "|" + "|".join(" --- " for _ in CABECALHO) + "|")
    return "\n".join(corpo) + "\n"


def escrever_csv(resumos: Sequence[Resumo], caminho: Path) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(CABECALHO)
        escritor.writerows(linhas_do_relatorio(resumos))


# --------------------------------------------------------------------------- #
# A avaliação inteira
# --------------------------------------------------------------------------- #


def avaliar(
    casos: Sequence[Caso],
    modelos: Sequence[str],
    texto_de: Callable[[Caso], str],
    fabricar_provedor: Callable[[Callable[[UsoDaChamada], None]], object],
    juiz: Juiz | None,
    repeticoes: int = 3,
    consultar_capacidades: Callable[[str], Capacidades | None] = obter_capacidades,
    relogio: Callable[[], float] = time.perf_counter,
    avisar: Callable[[str], None] = print,
) -> list[Resumo]:
    """Roda cada (modelo, tarefa, caso) ``repeticoes`` vezes e devolve um ``Resumo`` por (modelo, tarefa)."""
    resumos = []
    for modelo in modelos:
        usos: list[UsoDaChamada] = []
        provedor = fabricar_provedor(usos.append)
        capacidades = consultar_capacidades(modelo)
        for tarefa in TAREFAS:
            do_tipo = [caso for caso in casos if caso.tipo == tarefa]
            if not do_tipo:
                continue
            tentativas = []
            for caso in do_tipo:
                texto = texto_de(caso)
                for _ in range(repeticoes):
                    tentativas.append(executar(caso, modelo, provedor, usos, texto, juiz, relogio))
                avisar(f"  {modelo} / {tarefa} / {caso.arquivo}: {repeticoes} repetições")
            resumo = resumir(modelo, tarefa, tentativas)
            if capacidades is not None:
                resumo.preco_entrada, resumo.preco_saida = capacidades.preco_entrada, capacidades.preco_saida
            resumos.append(resumo)
    return resumos


def main(
    argumentos: Sequence[str] | None = None,
    *,
    fabricar_provedor: Callable[[Callable[[UsoDaChamada], None]], object] | None = None,
    juiz: Juiz | None = None,
    consultar_capacidades: Callable[[str], Capacidades | None] = obter_capacidades,
    avisar: Callable[[str], None] = print,
) -> list[Resumo]:
    analisador = argparse.ArgumentParser(description="Compara modelos na leitura do livro (item 4.10, LM18).")
    analisador.add_argument("modelos", nargs="+", metavar="MODELO")
    analisador.add_argument("--casos", required=True, help="pasta com os casos .json (ver scripts/exemplos/)")
    analisador.add_argument("--epubs", help="pasta dos livros, para os casos sem 'texto'")
    analisador.add_argument("--tarefas", default=",".join(TAREFAS), help=f"separadas por vírgula; de {', '.join(TAREFAS)}")
    analisador.add_argument("--repeticoes", type=int, default=3)
    analisador.add_argument("--juiz", help="modelo que julga a qualidade (temperatura 0); sem ele só se medem JSON, corte, latência e custo")
    analisador.add_argument("--saida", help="arquivo .md do relatório; o .csv sai ao lado")
    dados = analisador.parse_args(argumentos)

    tarefas = [t.strip() for t in dados.tarefas.split(",") if t.strip()]
    desconhecidas = [t for t in tarefas if t not in TAREFAS]
    if desconhecidas:
        analisador.error(f"tarefa desconhecida: {', '.join(desconhecidas)} (use {', '.join(TAREFAS)})")
    if dados.repeticoes < 1:
        analisador.error("--repeticoes deve ser pelo menos 1")

    try:
        casos = carregar_casos(Path(dados.casos), tarefas)
    except CasoInvalido as erro:
        sys.exit(f"Caso inválido — {erro}")
    if not casos:
        sys.exit(f"Nenhum caso das tarefas {', '.join(tarefas)} em {dados.casos}.")

    if fabricar_provedor is None:
        from imagineer.servicos.configuracao_ia import resolver_chave
        from imagineer.servicos.uso_de_ia import gravar_uso

        chave = resolver_chave(None).valor
        if not chave:
            sys.exit("Sem chave do OpenRouter (.env: CHAVE_API_OPENROUTER).")

        def fabricar_provedor(ao_usar):  # noqa: F811 - o padrão de produção: grava cada chamada em usos_ia, como o servidor
            def anotar(uso: UsoDaChamada) -> None:
                ao_usar(uso)
                gravar_uso(uso)

            return ProvedorOpenRouter(chave_api=chave, ao_usar=anotar)

        if dados.juiz and juiz is None:
            provedor_do_juiz = ProvedorOpenRouter(chave_api=chave, ao_usar=gravar_uso)

            def juiz(instrucao: str, pedido: str) -> str:  # noqa: F811
                return provedor_do_juiz._conversar(dados.juiz, instrucao, pedido, operacao="avaliacao", temperatura=0)

    livros_abertos: dict = {}
    pasta_dos_epubs = Path(dados.epubs) if dados.epubs else None
    try:
        for caso in casos:  # falha cedo, antes de gastar: todo caso precisa ter o seu texto
            texto_do_capitulo(caso, pasta_dos_epubs, livros_abertos)
    except CasoInvalido as erro:
        sys.exit(f"Caso inválido — {erro}")

    resumos = avaliar(
        casos,
        dados.modelos,
        lambda caso: texto_do_capitulo(caso, pasta_dos_epubs, livros_abertos),
        fabricar_provedor,
        juiz,
        repeticoes=dados.repeticoes,
        consultar_capacidades=consultar_capacidades,
        avisar=avisar,
    )

    tabela = tabela_em_markdown(resumos)
    avisar("\n" + tabela)
    if dados.saida:
        saida = Path(dados.saida)
        saida.write_text(tabela, encoding="utf-8")
        escrever_csv(resumos, saida.with_suffix(".csv"))
        avisar(f"Relatório em {saida} e {saida.with_suffix('.csv')}")
    return resumos


if __name__ == "__main__":
    main()
