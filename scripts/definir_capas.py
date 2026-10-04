"""Dá capa aos livros que **já estão no servidor**, a partir dos EPUBs originais (item 7.5b, CP3).

Os livros importados antes de a capa existir não guardaram o arquivo. Este script percorre uma pasta de EPUBs, acha para cada um o
livro correspondente no servidor (pelo identificador do EPUB e, se não bater, pelo título) e manda o próprio EPUB para
``POST /livros/{id}/capa``, que extrai a capa. Não reimporta nada e não mexe em capítulos.

Uso (com o servidor no ar)::

    python scripts/definir_capas.py D:\\Livros                       # servidor local (http://localhost:8000)
    python scripts/definir_capas.py D:\\Livros --url http://100.77.35.58:8000
    python scripts/definir_capas.py D:\\Livros --simular             # só mostra o que faria

Por padrão **não troca** a capa de quem já tem; ``--substituir`` troca.
"""

import argparse
import sys
import unicodedata
from pathlib import Path

import httpx
from ebooklib import epub

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from imagineer.servicos.importacao_epub import _identificador_unico, _primeiro_metadado  # noqa: E402


def _normalizar(texto: str | None) -> str:
    sem_acento = unicodedata.normalize("NFD", texto or "")
    return " ".join("".join(c for c in sem_acento if unicodedata.category(c) != "Mn").lower().split())


def principal() -> int:
    parser = argparse.ArgumentParser(description="Define a capa dos livros do servidor a partir dos EPUBs.")
    parser.add_argument("pasta", type=Path, help="A pasta com os .epub")
    parser.add_argument("--url", default="http://localhost:8000", help="O endereço do servidor")
    parser.add_argument("--simular", action="store_true", help="Só mostra o que faria")
    parser.add_argument("--substituir", action="store_true", help="Troca também a capa de livros que já têm")
    args = parser.parse_args()

    cliente = httpx.Client(base_url=args.url, timeout=120)
    livros = cliente.get("/livros").json()
    detalhes = [cliente.get(f"/livros/{livro['id']}").json() for livro in livros]
    por_identificador = {d["identificador_epub"]: d for d in detalhes if d.get("identificador_epub")}
    por_titulo = {_normalizar(d["titulo"]): d for d in detalhes}

    feitos = 0
    for arquivo in sorted(args.pasta.glob("*.epub")):
        try:
            lido = epub.read_epub(str(arquivo))
        except Exception as erro:  # noqa: BLE001
            print(f"- {arquivo.name[:60]}: não consegui ler ({erro})")
            continue
        livro = por_identificador.get(_identificador_unico(lido)) or por_titulo.get(_normalizar(_primeiro_metadado(lido, "title")))
        if livro is None:
            print(f"- {arquivo.name[:60]}: nenhum livro do servidor corresponde")
            continue
        if livro["tem_capa"] and not args.substituir:
            print(f"= {livro['titulo'][:60]}: já tem capa")
            continue
        if args.simular:
            print(f"? {livro['titulo'][:60]}: receberia a capa de {arquivo.name[:40]}")
            continue
        resposta = cliente.post(f"/livros/{livro['id']}/capa", files={"arquivo": (arquivo.name, arquivo.read_bytes(), "application/epub+zip")})
        if resposta.status_code == 200:
            feitos += 1
            print(f"+ {livro['titulo'][:60]}: capa definida")
        else:
            print(f"! {livro['titulo'][:60]}: {resposta.status_code} {resposta.json().get('detail', resposta.text)}")
    print(f"\n{feitos} capa(s) definida(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
