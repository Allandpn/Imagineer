"""Mede, com IA real, se a citação de cena (``trecho_ancora``) vira uma posição no texto (item 3.4g).

Usa o prompt de PRODUÇÃO (``ProvedorOpenRouter.extrair_elementos``) em capítulos de livros reais do
corpus de validação (fora do repositório) e conta, para cada cena sugerida: se a IA citou, se a
citação é literal, se o servidor achou a posição e se um participante da cena aparece perto dela.

**Gasta cota do OpenRouter** e grava cada chamada em ``usos_ia`` (o mesmo caminho do servidor), o que
também valida o registro de custo. Não grava nada além disso: nenhum livro, capítulo ou sugestão.

Uso (na raiz do projeto, com o banco no ar):

    ./venv/Scripts/python.exe scripts/medir_citacao_de_cena.py [--pasta D:/Livros] [--capitulos 3] MODELO [MODELO...]
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imagineer.ia.openrouter import ProvedorOpenRouter  # noqa: E402
from imagineer.ia.provedor import ErroDoProvedorIA, UsoDaChamada  # noqa: E402
from imagineer.servicos.configuracao_ia import resolver_chave  # noqa: E402
from imagineer.servicos.importacao_epub import extrair_epub  # noqa: E402
from imagineer.servicos.posicao_no_texto import posicao_da_citacao  # noqa: E402
from imagineer.servicos.uso_de_ia import gravar_uso  # noqa: E402

LIVROS = ["A Musica do Silencio", "O Alienista", "Perdido em marte", "Mistborn O Imp"]
TAMANHO_MINIMO, TAMANHO_MAXIMO = 6_000, 45_000
JANELA_DO_PARTICIPANTE = 2_500


def escolher_capitulos(texto_do_livro: bytes, nome: str, quantos: int):
    """Capítulos de narrativa, de tamanho razoável, espalhados pelo livro (sempre os mesmos)."""
    livro = extrair_epub(texto_do_livro, nome)
    elegiveis = [
        c for c in livro.capitulos if not c.ignorado and TAMANHO_MINIMO <= len(c.texto) <= TAMANHO_MAXIMO
    ]
    if len(elegiveis) <= quantos:
        return livro, elegiveis
    passo = len(elegiveis) / (quantos + 1)
    return livro, [elegiveis[int(passo * (i + 1))] for i in range(quantos)]


def medir(modelo: str, capitulos, provedor: ProvedorOpenRouter, usos: list[UsoDaChamada]) -> dict:
    cenas = com_citacao = literal = achada = perto = 0
    tamanhos = []
    falhas = []
    for livro, capitulo in capitulos:
        try:
            extracao = provedor.extrair_elementos(capitulo.texto, [], modelo)
        except ErroDoProvedorIA as erro:
            falhas.append(f"{livro.titulo} cap. {capitulo.ordem}: {erro}")
            continue
        for cena in extracao.cenas:
            cenas += 1
            citacao = (cena.trecho_ancora or "").strip()
            if not citacao:
                continue
            com_citacao += 1
            tamanhos.append(len(citacao))
            if capitulo.texto.find(citacao) != -1:
                literal += 1
            posicao = posicao_da_citacao(capitulo.texto, citacao)
            if posicao is None:
                continue
            achada += 1
            trecho = capitulo.texto[posicao : posicao + JANELA_DO_PARTICIPANTE].lower()
            nomes = [p.nome.split()[0].lower() for p in cena.participantes if p.nome.strip()]
            if any(nome in trecho for nome in nomes):
                perto += 1
    return {
        "capitulos": len(capitulos), "cenas": cenas, "com_citacao": com_citacao, "literal": literal,
        "achada": achada, "participante_perto": perto, "falhas": falhas,
        "tamanho_medio": (sum(tamanhos) / len(tamanhos)) if tamanhos else 0,
    }


def pct(parte: int, todo: int) -> str:
    return f"{100 * parte / todo:.0f}%" if todo else "-"


def main() -> None:
    analisador = argparse.ArgumentParser()
    analisador.add_argument("modelos", nargs="+")
    analisador.add_argument("--pasta", default="D:/Livros")
    analisador.add_argument("--capitulos", type=int, default=3, help="por livro")
    argumentos = analisador.parse_args()

    chave = resolver_chave(None).valor
    if not chave:
        sys.exit("Sem chave do OpenRouter (.env: CHAVE_API_OPENROUTER).")

    capitulos = []
    for prefixo in LIVROS:
        arquivo = next(Path(argumentos.pasta).glob(f"{prefixo}*.epub"), None)
        if arquivo is None:
            print(f"(livro não achado: {prefixo})")
            continue
        capitulos.extend((livro, c) for livro, cs in [escolher_capitulos(arquivo.read_bytes(), arquivo.name, argumentos.capitulos)] for c in cs)
    print(f"{len(capitulos)} capítulos de {len(LIVROS)} livros.\n")

    for modelo in argumentos.modelos:
        usos: list[UsoDaChamada] = []

        def ao_usar(uso: UsoDaChamada) -> None:
            usos.append(uso)
            gravar_uso(uso)

        provedor = ProvedorOpenRouter(chave_api=chave, ao_usar=ao_usar)
        r = medir(modelo, capitulos, provedor, usos)
        custo = sum((u.custo for u in usos if u.custo is not None), Decimal(0))
        sem_custo = sum(1 for u in usos if u.custo is None)
        print(f"=== {modelo} ===")
        print(f"cenas sugeridas: {r['cenas']} em {r['capitulos']} capítulos ({len(r['falhas'])} falhas)")
        print(f"  a IA citou:                       {r['com_citacao']:>3} ({pct(r['com_citacao'], r['cenas'])} das cenas)")
        print(f"  citação literal no texto:         {r['literal']:>3} ({pct(r['literal'], r['com_citacao'])} das citações)")
        print(f"  posição achada pelo servidor:     {r['achada']:>3} ({pct(r['achada'], r['cenas'])} das cenas; {pct(r['achada'], r['com_citacao'])} das citações)")
        print(f"  participante perto da posição:    {r['participante_perto']:>3} ({pct(r['participante_perto'], r['achada'])} das achadas)")
        print(f"  tamanho médio da citação:         {r['tamanho_medio']:.0f} caracteres")
        print(f"  chamadas: {len(usos)}; tokens: {sum(u.tokens_entrada or 0 for u in usos)} entrada / {sum(u.tokens_saida or 0 for u in usos)} saída")
        print(f"  CUSTO: US$ {custo:.4f}" + (f" ({sem_custo} chamadas sem custo informado)" if sem_custo else ""))
        for falha in r["falhas"]:
            print(f"  FALHA: {falha}")
        print()


if __name__ == "__main__":
    main()
