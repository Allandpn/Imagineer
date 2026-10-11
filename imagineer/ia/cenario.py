"""O cenário e a fotografia de uma cena ou de um elemento que não é pessoa (item 4.11, AF1 a AF9).

Funções puras: normalizam o que a IA devolve, juntam os campos para as telas antigas e escrevem as linhas que o prompt recebe. Não falam com a IA
nem com o banco.
"""

CAMPOS_DO_CENARIO: tuple[tuple[str, str], ...] = (
    ("ambiente", "Ambiente"),
    ("clima", "Clima"),
    ("iluminacao", "Iluminação"),
    ("hora_e_estacao", "Hora do dia e estação"),
    ("atmosfera", "Paleta e atmosfera"),
    ("enquadramento", "Enquadramento e ângulo"),
    ("lente", "Lente e profundidade de campo"),
)
"""Os 7 campos do cenário (AF1), na ordem em que aparecem, com o nome que a pessoa lê."""

CAMPOS_SUGERIDOS = ("enquadramento", "lente")
"""Não existem no livro: a IA os sugere a partir da ação (AF2). Os outros cinco vêm do texto ou do anterior."""

ORIGENS = ("texto", "anterior", "sugerido")

ROTULOS_DA_ORIGEM = {"texto": "do texto", "anterior": "herdado do anterior", "sugerido": "sugerido"}

TAMANHO_DO_FIM_DO_CAPITULO_ANTERIOR = 3000
"""Quantos caracteres do fim do capítulo anterior vão na leitura, para herdar o cenário (AF3.b)."""

TIPOS_QUE_LEEM_CENARIO = frozenset({"OBJETO", "AMBIENTE", "EDIFICACAO", "CRIATURA", "VEICULO"})
"""Os tipos de elemento cujo retrato mostra o cenário (AF5, AF6). Pessoa e grupo continuam com o retrato neutro (FL1)."""


def fim_do_capitulo(texto: str | None, tamanho: int = TAMANHO_DO_FIM_DO_CAPITULO_ANTERIOR) -> str | None:
    """Os últimos ``tamanho`` caracteres do capítulo, começando numa quebra de parágrafo quando dá (para não abrir no meio de uma frase)."""
    if not texto or not texto.strip():
        return None
    texto = texto.strip()
    if len(texto) <= tamanho:
        return texto
    corte = texto[-tamanho:]
    quebra = corte.find("\n")
    if 0 <= quebra < tamanho // 2:
        corte = corte[quebra + 1 :]
    return corte.strip()


def _texto_ou_nulo(valor) -> str | None:
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    return valor or None


def normalizar_cenario(bruto) -> dict | None:
    """O ``cenario`` como a IA devolveu, arrumado (AF1): os 7 campos, cada um ``{"texto", "origem"}``.

    Campo sem texto vira ``{"texto": None, "origem": "texto"}`` (a origem de um campo vazio não diz nada). Origem desconhecida ou ausente num campo com
    texto vale ``texto`` para os cinco que vêm do livro e ``sugerido`` para o enquadramento e a lente. Texto solto (``"noite"``) no lugar do objeto
    também é aceito. ``None`` se ``bruto`` não é um objeto ou se nenhum campo tem texto (nada foi lido).
    """
    if not isinstance(bruto, dict):
        return None
    cenario: dict[str, dict] = {}
    algum = False
    for campo, _ in CAMPOS_DO_CENARIO:
        entrada = bruto.get(campo)
        if isinstance(entrada, dict):
            texto = _texto_ou_nulo(entrada.get("texto"))
            origem = str(entrada.get("origem") or "").strip().lower()
        else:
            texto, origem = _texto_ou_nulo(entrada), ""
        if origem not in ORIGENS:
            origem = "sugerido" if campo in CAMPOS_SUGERIDOS else "texto"
        if texto is None:
            origem = "texto"
        else:
            algum = True
        cenario[campo] = {"texto": texto, "origem": origem}
    return cenario if algum else None


def texto_do_campo(cenario: dict | None, campo: str) -> str | None:
    """O texto de um campo do cenário, ou ``None``."""
    if not cenario:
        return None
    entrada = cenario.get(campo)
    return _texto_ou_nulo(entrada.get("texto")) if isinstance(entrada, dict) else None


def onde_do_cenario(cenario: dict | None) -> str | None:
    """O ``onde`` das telas antigas (AF4): o ambiente."""
    return texto_do_campo(cenario, "ambiente")


def luz_e_clima_do_cenario(cenario: dict | None) -> str | None:
    """O ``luz_e_clima`` das telas antigas (AF4): o clima, a iluminação e a hora/estação, juntos."""
    partes = [texto_do_campo(cenario, campo) for campo in ("clima", "iluminacao", "hora_e_estacao")]
    return ". ".join(parte.rstrip(".") for parte in partes if parte) or None


def aplicar_edicao(atual: dict | None, novo: dict | None) -> dict | None:
    """O cenário depois de a pessoa editar (AF8): o que ela mudou vira ``origem: "texto"`` (a palavra dela); o que ficou igual mantém a origem.

    ``novo`` é o que o app mandou (``{campo: {"texto", "origem"}}``); campo ausente ou nulo fica como estava; ``{"texto": null}`` **apaga** o campo.
    """
    if novo is None:
        return atual
    base = normalizar_cenario(atual) or {campo: {"texto": None, "origem": "texto"} for campo, _ in CAMPOS_DO_CENARIO}
    resultado = {campo: dict(valor) for campo, valor in base.items()}
    for campo, _ in CAMPOS_DO_CENARIO:
        if novo.get(campo) is None:  # ausente (ou nulo, como o esquema da API manda): fica como estava
            continue
        entrada = novo[campo]
        texto = _texto_ou_nulo(entrada.get("texto") if isinstance(entrada, dict) else entrada)
        antes = resultado[campo]["texto"]
        if texto is None:
            resultado[campo] = {"texto": None, "origem": "texto"}
        elif texto != antes:
            resultado[campo] = {"texto": texto, "origem": "texto"}
        else:
            origem = str(entrada.get("origem") or "") if isinstance(entrada, dict) else ""
            resultado[campo] = {"texto": texto, "origem": origem if origem in ORIGENS else resultado[campo]["origem"]}
    return resultado


def linhas_do_cenario(cenario: dict | None) -> list[str]:
    """As linhas "Rótulo: texto (origem)" que o prompt recebe (AF7), só dos campos com texto. Vazia se não há cenário."""
    linhas = []
    for campo, rotulo in CAMPOS_DO_CENARIO:
        texto = texto_do_campo(cenario, campo)
        if texto is None:
            continue
        origem = cenario[campo].get("origem", "texto")
        marca = "" if origem == "texto" else f" [{ROTULOS_DA_ORIGEM[origem]}]"
        linhas.append(f"- {rotulo}: {texto}{marca}")
    return linhas


def bloco_do_cenario(cenario: dict | None) -> str | None:
    """O bloco "CENÁRIO E FOTOGRAFIA" do pedido de montagem do prompt (AF7); ``None`` se não há nada a dizer."""
    linhas = linhas_do_cenario(cenario)
    if not linhas:
        return None
    return (
        "CENÁRIO E FOTOGRAFIA (ambiente, clima, luz, hora, atmosfera, enquadramento e lente; vale o que a descrição da cena e o comentário do usuário "
        "não contradizem; o que vem marcado [herdado do anterior] ou [sugerido] também entra):\n" + "\n".join(linhas)
    )
