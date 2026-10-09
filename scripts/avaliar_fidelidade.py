"""Mede, com IA real, se cenas e retratos saem FIÉIS ao que o autor escreveu (item 4.9, FL13.3).

Os testes automáticos conferem só o **pedido enviado ao provedor**; esta é a única forma de medir a qualidade do que a IA devolve. Para cada caso do
**conjunto de ouro** (3 a 5 cenas por livro, as que já falharam, cada uma com a lista do que **deve** e do que **não deve** aparecer), o script roda o
caminho de produção:

- **cena:** a leitura do capítulo (o dossiê: ``fundamentar_frame``) e a montagem do prompt (``montar_prompt``, com a lista de presentes como lista fechada);
- **retrato:** a montagem do prompt neutro, com o bloco de retrato colado por código como no servidor.

Depois um modelo-juiz (temperatura 0) confere, **no dossiê** e **no prompt final**, quais itens de ``deve_aparecer`` estão presentes e quais de
``nao_deve_aparecer`` aparecem. A saída é uma tabela de acertos: por caso (e por modelo), o dossiê e o prompt, o custo e o veredito.

**Gasta cota do OpenRouter** e grava cada chamada em ``usos_ia`` (o mesmo caminho do servidor). Os casos ficam **fora do git** (``avaliacao/``): trechos de
livros têm direitos autorais. O repositório leva só ``scripts/exemplos/``, com texto inventado. **Quem escolhe os casos é o Allan** (os que já falharam).

Uso (na raiz do projeto, com o banco no ar):

    ./venv/Scripts/python.exe scripts/avaliar_fidelidade.py --casos avaliacao --epubs D:/Livros --repeticoes 2 \\
        --juiz anthropic/claude-haiku-4.5 --saida fidelidade.md  google/gemini-2.5-flash  [--prompt openai/gpt-4o-mini]

Cada ``MODELO`` é o de **leitura** (o dossiê); o do **prompt** é o ``--prompt`` (senão o mesmo). Formato dos casos: ``scripts/exemplos/caso_de_fidelidade_*.json``.
"""

import argparse
import csv
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # a pasta scripts/: o script de avaliação de modelos é irmão deste

import avaliar_modelos_de_leitura as base  # noqa: E402

from imagineer.ia.blocos_tecnicos import com_bloco_de_retrato  # noqa: E402
from imagineer.ia.openrouter import ProvedorOpenRouter, _extrair_json, presentes_incluidos, texto_dos_presentes  # noqa: E402
from imagineer.ia.provedor import ErroDoProvedorIA, UsoDaChamada  # noqa: E402
from imagineer.modelos import TipoElemento  # noqa: E402
from imagineer.servicos.aparencia_de_elemento import sem_o_lugar  # noqa: E402

TIPOS = ("cena", "retrato")
CasoInvalido = base.CasoInvalido
Caso = base.Caso
Juiz = base.Juiz
PERFIL_PADRAO = "formato: 2:3, portrait orientation"


# --------------------------------------------------------------------------- #
# Os casos
# --------------------------------------------------------------------------- #


def validar_caso(dados: object, arquivo: str) -> Caso:
    """Confere o caso e o devolve. Levanta ``CasoInvalido`` dizendo **qual** campo falta ou está errado."""
    if not isinstance(dados, dict):
        raise CasoInvalido(f"{arquivo}: o caso deve ser um objeto JSON")
    base._exigir(dados, "tipo", str, arquivo)
    if dados["tipo"] not in TIPOS:
        raise CasoInvalido(f"{arquivo}: o campo 'tipo' deve ser um de {', '.join(TIPOS)} (veio '{dados['tipo']}')")
    base._exigir(dados, "livro", str, arquivo)
    base._exigir(dados, "capitulo", int, arquivo)
    if "texto" in dados:
        base._exigir(dados, "texto", str, arquivo)
    base._exigir(dados, "deve_aparecer", list, arquivo)
    base._exigir(dados, "nao_deve_aparecer", list, arquivo)
    if not dados["deve_aparecer"] and not dados["nao_deve_aparecer"]:
        raise CasoInvalido(f"{arquivo}: o caso não tem nada a conferir: preencha 'deve_aparecer' ou 'nao_deve_aparecer'")

    if dados["tipo"] == "cena":
        base._exigir(dados, "cena", dict, arquivo)
        for campo in ("titulo", "descricao", "trecho"):
            base._exigir(dados["cena"], campo, str, f"{arquivo} (cena)")
        base._exigir(dados, "participantes", list, arquivo)
        for posicao, participante in enumerate(dados["participantes"], 1):
            onde = f"{arquivo} (participantes[{posicao}])"
            if not isinstance(participante, dict):
                raise CasoInvalido(f"{onde}: deve ser um objeto")
            for campo in ("nome", "tipo", "aparencia"):
                base._exigir(participante, campo, str, onde)
            if participante["tipo"] not in TipoElemento.__members__:
                raise CasoInvalido(f"{onde}: o campo 'tipo' deve ser um de {', '.join(TipoElemento.__members__)}")
    else:
        base._exigir(dados, "elemento", dict, arquivo)
        for campo in ("nome", "tipo", "aparencia"):
            base._exigir(dados["elemento"], campo, str, f"{arquivo} (elemento)")
        if dados["elemento"]["tipo"] not in TipoElemento.__members__:
            raise CasoInvalido(f"{arquivo} (elemento): o campo 'tipo' deve ser um de {', '.join(TipoElemento.__members__)}")
    return Caso(arquivo=arquivo, tipo=dados["tipo"], dados=dados)


def carregar_casos(pasta: Path, tipos: Sequence[str] = TIPOS) -> list[Caso]:
    """Os casos de fidelidade de ``pasta`` (``tipo`` ``cena`` ou ``retrato``), em ordem de nome. Arquivo de outro script (``estado``, ``dossie``...) é ignorado."""
    casos = []
    for caminho in sorted(Path(pasta).glob("*.json")):
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            raise CasoInvalido(f"{caminho.name}: não é um JSON válido ({erro})") from erro
        if not isinstance(dados, dict) or dados.get("tipo") not in TIPOS:
            continue  # é caso do outro script (avaliar_modelos_de_leitura) ou não é caso
        caso = validar_caso(dados, caminho.name)
        if caso.tipo in tipos:
            casos.append(caso)
    return casos


# --------------------------------------------------------------------------- #
# O juiz
# --------------------------------------------------------------------------- #

_INSTRUCAO_DO_JUIZ = """\
Você confere se um texto é FIEL a uma lista do que deve e do que não deve aparecer numa imagem. Seja literal: um item só "aparece" se o texto o diz ou \
o implica claramente (com outras palavras, tudo bem); o que o texto não menciona NÃO aparece. Responda APENAS com um objeto JSON neste formato:

{"deve": [true, false], "nao_deve": [false]}

- "deve": um true/false para CADA item de DEVE APARECER, na ordem: o texto o traz?
- "nao_deve": um true/false para CADA item de NÃO DEVE APARECER, na ordem: o texto o traz (isto é um ERRO)?
"""


def _lista(titulo: str, itens: Sequence[str]) -> str:
    return f"{titulo}:\n" + ("\n".join(f"{n}. {item}" for n, item in enumerate(itens, 1)) if itens else "(nenhum)")


def _conferir(juiz: Juiz, caso: Caso, texto_do_nivel: str) -> tuple[list[bool], list[bool]] | None:
    """Pede ao juiz que confira ``texto_do_nivel`` contra o caso. ``None`` se ele não devolveu um JSON utilizável."""
    pedido = "\n\n".join(
        [
            f"TEXTO A CONFERIR:\n{texto_do_nivel}",
            _lista("DEVE APARECER", caso.dados["deve_aparecer"]),
            _lista("NÃO DEVE APARECER", caso.dados["nao_deve_aparecer"]),
        ]
    )
    bruto = _extrair_json(juiz(_INSTRUCAO_DO_JUIZ, pedido))
    if bruto is None:
        return None

    def alinhar(valores: object, esperado: int) -> list[bool]:
        lista = valores if isinstance(valores, list) else []
        return [lista[i] is True if i < len(lista) else False for i in range(esperado)]

    return alinhar(bruto.get("deve"), len(caso.dados["deve_aparecer"])), alinhar(bruto.get("nao_deve"), len(caso.dados["nao_deve_aparecer"]))


# --------------------------------------------------------------------------- #
# Uma tentativa
# --------------------------------------------------------------------------- #


@dataclass
class Resultado:
    """O desfecho de rodar **um** caso uma vez, com um par de modelos."""

    caso: str
    tipo: str
    modelo_de_leitura: str
    modelo_de_prompt: str
    erro: str | None = None
    prompt: str = ""
    dossie_deve: list[bool] | None = None
    """Dos itens de ``deve_aparecer``, quais o **dossiê** traz (só cena)."""
    dossie_nao_deve: list[bool] | None = None
    prompt_deve: list[bool] | None = None
    prompt_nao_deve: list[bool] | None = None
    julgado: bool = False
    custo: Decimal | None = None
    latencia: float = 0.0
    chamadas: int = 0
    momento_incerto: bool | None = None
    presentes_no_dossie: int | None = None
    notas: list[str] = field(default_factory=list)


def _linha_do_participante(participante: dict) -> str:
    return f"{participante['nome']}: {participante['aparencia']}"


def _montar_a_cena(caso: Caso, texto: str, modelo_de_leitura: str, modelo_de_prompt: str, provedor) -> tuple[dict | None, str]:
    """O caminho de produção de uma cena: o dossiê e o prompt montado com ele. Devolve ``(dossiê, prompt)``."""
    cena = caso.dados["cena"]
    participantes = [_linha_do_participante(p) for p in caso.dados["participantes"]]
    fundamentado = provedor.fundamentar_frame(
        texto, cena["titulo"], cena["descricao"], None, None, None, participantes, modelo_de_leitura, trecho=cena["trecho"]
    )
    dossie = fundamentado.dossie
    montado = provedor.montar_prompt(
        cena["descricao"],
        participantes,
        PERFIL_PADRAO.replace("2:3, portrait orientation", "16:9, landscape orientation"),
        modelo_de_prompt,
        contexto_do_livro=None if dossie else fundamentado.contexto,
        trecho_do_livro=cena["trecho"],
        dossie=dossie,
    )
    return dossie, montado.texto


def _montar_o_retrato(caso: Caso, modelo_de_prompt: str, provedor) -> str:
    """O caminho de produção de um retrato: sem o "Onde está:", com o bloco do retrato neutro colado por código."""
    elemento = caso.dados["elemento"]
    identidade = elemento.get("identidade")
    descricao = sem_o_lugar(elemento["aparencia"])
    linha = f"{elemento['nome']} ({identidade}): {descricao}" if identidade else f"{elemento['nome']}: {descricao}"
    montado = provedor.montar_prompt("", [linha], caso.dados.get("perfil") or PERFIL_PADRAO, modelo_de_prompt)
    return com_bloco_de_retrato(montado.texto, TipoElemento[elemento["tipo"]])


def executar(
    caso: Caso,
    modelo_de_leitura: str,
    modelo_de_prompt: str,
    provedor,
    usos: list[UsoDaChamada],
    texto: str,
    juiz: Juiz | None,
    relogio: Callable[[], float] = time.perf_counter,
) -> Resultado:
    """Roda o caso uma vez pelo caminho de produção e o confere. ``usos`` é a lista em que o ``ao_usar`` do ``provedor`` anota cada resposta."""
    resultado = Resultado(caso=caso.arquivo, tipo=caso.tipo, modelo_de_leitura=modelo_de_leitura, modelo_de_prompt=modelo_de_prompt)
    antes = len(usos)
    inicio = relogio()
    dossie = None
    try:
        if caso.tipo == "cena":
            dossie, resultado.prompt = _montar_a_cena(caso, texto, modelo_de_leitura, modelo_de_prompt, provedor)
        else:
            resultado.prompt = _montar_o_retrato(caso, modelo_de_prompt, provedor)
    except ErroDoProvedorIA as erro:
        resultado.erro = str(erro)
    resultado.latencia = relogio() - inicio

    usadas = usos[antes:]
    resultado.chamadas = len(usadas)
    custos = [u.custo for u in usadas if u.custo is not None]
    resultado.custo = sum(custos, Decimal(0)) if custos else None

    if dossie is not None:
        resultado.momento_incerto = bool(dossie.get("momento_incerto"))
        resultado.presentes_no_dossie = len(presentes_incluidos(dossie))
    if resultado.erro is None and juiz is not None:
        try:
            if dossie is not None:
                conferido = _conferir(juiz, caso, texto_dos_presentes(dossie))
                if conferido is not None:
                    resultado.dossie_deve, resultado.dossie_nao_deve = conferido
            conferido = _conferir(juiz, caso, resultado.prompt)
            if conferido is not None:
                resultado.prompt_deve, resultado.prompt_nao_deve = conferido
                resultado.julgado = True
        except ErroDoProvedorIA as erro:
            resultado.notas.append(f"o juiz falhou: {erro}")
    return resultado


# --------------------------------------------------------------------------- #
# O relatório
# --------------------------------------------------------------------------- #


def _fracao(lista: list[bool] | None) -> str:
    return "-" if lista is None else f"{sum(lista)}/{len(lista)}"


def acertou(resultado: Resultado) -> bool | None:
    """O veredito do caso: todo item de ``deve_aparecer`` está no prompt e nenhum de ``nao_deve_aparecer``. ``None`` se não foi julgado."""
    if not resultado.julgado:
        return None
    return all(resultado.prompt_deve or []) and not any(resultado.prompt_nao_deve or [])


CABECALHO = [
    "Modelo de leitura", "Modelo do prompt", "Caso", "Tipo", "Dossiê: deve", "Dossiê: não deve", "Prompt: deve", "Prompt: não deve",
    "Veredito", "Custo (US$)", "Latência (s)", "Observações",
]


def linha_do_resultado(r: Resultado) -> list[str]:
    veredito = acertou(r)
    observacoes = list(r.notas)
    if r.erro:
        observacoes.append(f"ERRO: {r.erro}")
    if r.momento_incerto:
        observacoes.append("momento incerto")
    if r.presentes_no_dossie is not None:
        observacoes.append(f"{r.presentes_no_dossie} presentes")
    return [
        r.modelo_de_leitura, r.modelo_de_prompt, r.caso, r.tipo, _fracao(r.dossie_deve), _fracao(r.dossie_nao_deve), _fracao(r.prompt_deve),
        _fracao(r.prompt_nao_deve), "-" if veredito is None else ("ACERTOU" if veredito else "ERROU"),
        "-" if r.custo is None else f"{r.custo:.4f}", f"{r.latencia:.1f}", "; ".join(observacoes) or "-",
    ]


def resumo_por_modelo(resultados: Sequence[Resultado]) -> list[list[str]]:
    """Uma linha por par de modelos: quantos casos acertou, quantos itens obrigatórios o prompt trouxe, quantos proibidos apareceram e o custo."""
    grupos: dict[tuple[str, str], list[Resultado]] = {}
    for r in resultados:
        grupos.setdefault((r.modelo_de_leitura, r.modelo_de_prompt), []).append(r)
    linhas = []
    for (leitura, prompt), do_par in grupos.items():
        julgados = [r for r in do_par if r.julgado]
        deve = [v for r in julgados for v in (r.prompt_deve or [])]
        nao_deve = [v for r in julgados for v in (r.prompt_nao_deve or [])]
        acertos = sum(1 for r in julgados if acertou(r))
        custos = [r.custo for r in do_par if r.custo is not None]
        linhas.append(
            [
                leitura, prompt, f"{acertos}/{len(julgados)} casos", f"{sum(deve)}/{len(deve)} obrigatórios no prompt",
                f"{sum(nao_deve)}/{len(nao_deve)} proibidos que apareceram", f"US$ {sum(custos, Decimal(0)):.4f}" if custos else "-",
                f"{len(do_par) - len(julgados)} sem julgamento" if len(do_par) != len(julgados) else "-",
            ]
        )
    return linhas


CABECALHO_DO_RESUMO = ["Modelo de leitura", "Modelo do prompt", "Acertos", "Obrigatórios", "Proibidos", "Custo total", "Observações"]


def tabela_em_markdown(resultados: Sequence[Resultado]) -> str:
    def tabela(cabecalho: list[str], linhas: list[list[str]]) -> str:
        corpo = ["| " + " | ".join(c.replace("|", "\\|") for c in linha) + " |" for linha in [cabecalho, *linhas]]
        corpo.insert(1, "|" + "|".join(" --- " for _ in cabecalho) + "|")
        return "\n".join(corpo)

    return (
        "## Resumo\n\n" + tabela(CABECALHO_DO_RESUMO, resumo_por_modelo(resultados))
        + "\n\n## Por caso\n\n" + tabela(CABECALHO, [linha_do_resultado(r) for r in resultados]) + "\n"
    )


def escrever_csv(resultados: Sequence[Resultado], caminho: Path) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(CABECALHO)
        escritor.writerows(linha_do_resultado(r) for r in resultados)


# --------------------------------------------------------------------------- #
# A avaliação inteira
# --------------------------------------------------------------------------- #


def avaliar(
    casos: Sequence[Caso],
    modelos_de_leitura: Sequence[str],
    modelo_de_prompt: str | None,
    texto_de: Callable[[Caso], str],
    fabricar_provedor: Callable[[Callable[[UsoDaChamada], None]], object],
    juiz: Juiz | None,
    repeticoes: int = 1,
    relogio: Callable[[], float] = time.perf_counter,
    avisar: Callable[[str], None] = print,
) -> list[Resultado]:
    """Roda cada caso ``repeticoes`` vezes com cada modelo de leitura. Devolve um ``Resultado`` por rodada, em ordem."""
    resultados = []
    for modelo in modelos_de_leitura:
        usos: list[UsoDaChamada] = []
        provedor = fabricar_provedor(usos.append)
        for caso in casos:
            texto = texto_de(caso)
            for _ in range(repeticoes):
                resultados.append(executar(caso, modelo, modelo_de_prompt or modelo, provedor, usos, texto, juiz, relogio))
            avisar(f"  {modelo} / {caso.arquivo}: {repeticoes} rodada(s)")
    return resultados


def main(
    argumentos: Sequence[str] | None = None,
    *,
    fabricar_provedor: Callable[[Callable[[UsoDaChamada], None]], object] | None = None,
    juiz: Juiz | None = None,
    avisar: Callable[[str], None] = print,
) -> list[Resultado]:
    analisador = argparse.ArgumentParser(description="Mede a fidelidade de cenas e retratos com IA real (item 4.9, FL13.3).")
    analisador.add_argument("modelos", nargs="+", metavar="MODELO", help="o(s) modelo(s) de leitura (o dossiê)")
    analisador.add_argument("--casos", required=True, help="pasta com os casos .json (ver scripts/exemplos/)")
    analisador.add_argument("--epubs", help="pasta dos livros, para os casos sem 'texto'")
    analisador.add_argument("--prompt", help="o modelo que monta o prompt; sem ele, o mesmo da leitura")
    analisador.add_argument("--repeticoes", type=int, default=1)
    analisador.add_argument("--tipos", default=",".join(TIPOS), help=f"separados por vírgula; de {', '.join(TIPOS)}")
    analisador.add_argument("--juiz", help="modelo que confere o dossiê e o prompt (temperatura 0); sem ele só se mede o custo e a latência")
    analisador.add_argument("--saida", help="arquivo .md do relatório; o .csv sai ao lado")
    dados = analisador.parse_args(argumentos)

    tipos = [t.strip() for t in dados.tipos.split(",") if t.strip()]
    desconhecidos = [t for t in tipos if t not in TIPOS]
    if desconhecidos:
        analisador.error(f"tipo desconhecido: {', '.join(desconhecidos)} (use {', '.join(TIPOS)})")
    if dados.repeticoes < 1:
        analisador.error("--repeticoes deve ser pelo menos 1")

    try:
        casos = carregar_casos(Path(dados.casos), tipos)
    except CasoInvalido as erro:
        sys.exit(f"Caso inválido — {erro}")
    if not casos:
        sys.exit(f"Nenhum caso de fidelidade ({', '.join(tipos)}) em {dados.casos}.")

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
            base.texto_do_capitulo(caso, pasta_dos_epubs, livros_abertos)
    except CasoInvalido as erro:
        sys.exit(f"Caso inválido — {erro}")

    resultados = avaliar(
        casos,
        dados.modelos,
        dados.prompt,
        lambda caso: base.texto_do_capitulo(caso, pasta_dos_epubs, livros_abertos),
        fabricar_provedor,
        juiz,
        repeticoes=dados.repeticoes,
        avisar=avisar,
    )

    tabela = tabela_em_markdown(resultados)
    avisar("\n" + tabela)
    if dados.saida:
        saida = Path(dados.saida)
        saida.write_text(tabela, encoding="utf-8")
        escrever_csv(resultados, saida.with_suffix(".csv"))
        avisar(f"Relatório em {saida} e {saida.with_suffix('.csv')}")
    return resultados


if __name__ == "__main__":
    main()
