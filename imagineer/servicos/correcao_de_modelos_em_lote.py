"""Troca, nos dados já salvos, o id de modelo ``:batch`` pelo mesmo modelo sem o sufixo (achado de 15/10/2026).

**Por que existe.** Antes de o servidor recusar a variante ``:batch`` ao gravar (``google/gemini-4-argon:batch`` deu 404 na tela do app), a pessoa
podia tê-la escolhido na configuração, na configuração de um livro ou na lista de modelos de imagem. Um id assim **nunca funcionou** na conversa, então
trocá-lo pelo id sem o sufixo (o mesmo modelo, que custa cerca do dobro) só põe a configuração a funcionar: não desfaz nenhuma escolha que valesse.

**Por que SQL "cru".** Como ``perfis_de_fabrica``: é chamada pela migração, que não pode depender dos modelos de hoje, e pelos testes. É idempotente
(rodar de novo não acha mais nada) e **só mexe** na configuração e nas trocas por livro; o histórico (``usos_ia``, prompts e imagens) guarda o modelo que
**de fato** foi usado e não é reescrito.
"""

import sqlalchemy as sa
from sqlalchemy.engine import Connection

SUFIXO = ":batch"

CAMPOS_DE_TEXTO = (
    "modelo_extracao", "modelo_prompt", "modelo_leitura", "modelo_conferencia", "modelo_reserva", "modelo_perfil", "modelo_imagem",
    "modelo_suavizacao", "modelo_traducao", "modelo_video", "modelo_narracao",
)

_CONFIGURACAO = sa.table(
    "configuracao",
    sa.column("id", sa.Integer),
    *[sa.column(campo, sa.String) for campo in CAMPOS_DE_TEXTO],
    sa.column("modelos_de_imagem", sa.JSON),
)
_LIVROS = sa.table("livros", sa.column("id", sa.Integer), sa.column("modelos", sa.JSON))


def _sem_sufixo(valor):
    """O id sem o ``:batch`` (ignora caixa e espaços); qualquer outra coisa volta como veio."""
    if isinstance(valor, str) and valor.strip().lower().endswith(SUFIXO):
        return valor.strip()[: -len(SUFIXO)]
    return valor


def corrigir_modelos_em_lote(conexao: Connection) -> int:
    """Troca os ids ``:batch`` da configuração (por pessoa) e das trocas por livro. Devolve quantos valores mudaram."""
    trocados = 0

    for linha in conexao.execute(sa.select(_CONFIGURACAO)).mappings():
        mudancas = {}
        for campo in CAMPOS_DE_TEXTO:
            novo = _sem_sufixo(linha[campo])
            if novo != linha[campo]:
                mudancas[campo] = novo
        lista = linha["modelos_de_imagem"]
        if isinstance(lista, list):
            nova = list(dict.fromkeys(_sem_sufixo(m) for m in lista))  # sem repetir, se o modelo já estava na lista sem o sufixo
            if nova != lista:
                mudancas["modelos_de_imagem"] = nova
        if mudancas:
            conexao.execute(_CONFIGURACAO.update().where(_CONFIGURACAO.c.id == linha["id"]).values(**mudancas))
            trocados += len(mudancas)

    for livro in conexao.execute(sa.select(_LIVROS).where(_LIVROS.c.modelos.is_not(None))).mappings():
        trocas = livro["modelos"]
        if not isinstance(trocas, dict):
            continue
        novas = {campo: _sem_sufixo(valor) for campo, valor in trocas.items()}
        if novas != trocas:
            conexao.execute(_LIVROS.update().where(_LIVROS.c.id == livro["id"]).values(modelos=novas))
            trocados += sum(1 for campo in trocas if novas[campo] != trocas[campo])

    return trocados
