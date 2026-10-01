"""Verifica, com IA real, como o modelo trata a orientação do usuário na reanálise (item 6.7, M1).

Roda a extração num capítulo de um livro do corpus **três vezes**: sem orientação, com uma orientação
**falsa** (algo que não está no capítulo) e com uma **verdadeira** (algo que está, escolhido por quem
roda). Mostra o que mudou. Serve para conferir que a IA trata a orientação como palpite e não inventa.

Gasta cota do OpenRouter (centavos); não grava nada no banco.

Uso: ./venv/Scripts/python.exe scripts/verificar_orientacao.py MODELO "orientação falsa" "orientação verdadeira" [--livro PREFIXO] [--capitulo N]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imagineer.ia.openrouter import ProvedorOpenRouter  # noqa: E402
from imagineer.servicos.configuracao_ia import resolver_chave  # noqa: E402
from imagineer.servicos.importacao_epub import extrair_epub  # noqa: E402


def resumo(extracao) -> str:
    elementos = ", ".join(f"{e.nome} ({e.tipo.name})" for e in extracao.elementos) or "(nenhum)"
    cenas = "; ".join(c.titulo for c in extracao.cenas) or "(nenhuma)"
    return f"  elementos ({len(extracao.elementos)}): {elementos}\n  cenas ({len(extracao.cenas)}): {cenas}"


def main() -> None:
    analisador = argparse.ArgumentParser()
    analisador.add_argument("modelo")
    analisador.add_argument("orientacao_falsa")
    analisador.add_argument("orientacao_verdadeira")
    analisador.add_argument("--pasta", default="D:/Livros")
    analisador.add_argument("--livro", default="O Alienista")
    analisador.add_argument("--capitulo", type=int, default=3, help="ordem do capítulo")
    a = analisador.parse_args()

    arquivo = next(Path(a.pasta).glob(f"{a.livro}*.epub"))
    livro = extrair_epub(arquivo.read_bytes(), arquivo.name)
    capitulo = next(c for c in livro.capitulos if c.ordem == a.capitulo)
    print(f"{livro.titulo}, capítulo {capitulo.ordem} ({len(capitulo.texto)} caracteres)\n")

    provedor = ProvedorOpenRouter(chave_api=resolver_chave(None).valor)
    for rotulo, orientacao in [
        ("SEM orientação", None),
        (f"orientação FALSA: {a.orientacao_falsa!r}", a.orientacao_falsa),
        (f"orientação VERDADEIRA: {a.orientacao_verdadeira!r}", a.orientacao_verdadeira),
    ]:
        print(f"=== {rotulo}")
        print(resumo(provedor.extrair_elementos(capitulo.texto, [], a.modelo, orientacao)))
        print()


if __name__ == "__main__":
    main()
