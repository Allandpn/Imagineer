"""As sugestões de IA de um capítulo: gerar, casar com os elementos já cadastrados e contar as pendentes (itens 3.4e, 4.6 e 6.7).

Era lógica de negócio dentro de `rotas/elementos.py`; agora mora num serviço, que não conhece HTTP: os erros do provedor (e a falta de modelo) sobem como exceções do domínio e o tratador global (`imagineer/erros.py`) as traduz."""

import unicodedata
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from imagineer.ia.openrouter import conferir_se_cabe
from imagineer.ia.provedor import ModeloNaoEscolhido, ProvedorIA
from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    SugestaoDeCena,
    SugestaoDeElemento,
    TipoElemento,
)
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento
from imagineer.servicos.identidade_de_elemento import identidade_vigente, resumir_texto
from imagineer.servicos.posicao_no_texto import posicao_da_citacao
from imagineer.servicos.uso_de_ia import gasto_do_livro


#: Quanto da identidade de cada elemento vai para a IA, e quanto o pedido inteiro pode ter
#: (item 7.5b, rodada 3): sem teto, a lista cresce com o livro e o pedido com ela.
LIMITE_DA_IDENTIDADE_NO_CONTEXTO = 200
TETO_DO_CONTEXTO_DA_IA = 8000


def estado_id_no_capitulo(sessao: Session, sugestao: SugestaoDeElemento) -> int | None:
    """O Estado já registrado para o elemento casado, neste capítulo específico.

    `elemento_id` preenchido só diz que a sugestão está ligada a um Elemento;
    não diz se aquele capítulo em particular já virou um `EstadoElemento`
    (item 3.4e) — achado com um caso real em que uma menção casada num
    capítulo posterior nunca tinha gerado Estado, e isso não aparecia em
    lugar nenhum da resposta. Campo calculado, não coluna no banco — mesmo
    princípio de `estado_vigente` (item 6.3).
    """
    if sugestao.elemento_id is None:
        return None
    return sessao.execute(
        select(EstadoElemento.id)
        .where(
            EstadoElemento.elemento_id == sugestao.elemento_id,
            EstadoElemento.capitulo_id == sugestao.capitulo_id,
        )
        .order_by(EstadoElemento.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def gerar_sugestoes(sessao: Session, provedor: ProvedorIA, capitulo: Capitulo) -> None:
    """Analisa o capítulo (ver ``_gerar_sugestoes``), anotando o gasto como **do livro** dele (CU3)."""
    with gasto_do_livro(capitulo.livro_id):
        _gerar_sugestoes(sessao, provedor, capitulo)


def _gerar_sugestoes(sessao: Session, provedor: ProvedorIA, capitulo: Capitulo) -> None:
    """Chama a IA e grava o resultado como linhas (item 3.4e).

    Só substitui as sugestões deste capítulo que ainda não foram confirmadas
    (`elemento_id`/`frame_id` nulos) **e não descartadas** — uma sugestão já virada
    Elemento ou Frame de verdade, ou descartada pelo usuário, sobrevive a uma rodada
    nova, mesmo com `forcar=true`. Uma sugestão nova que repete uma descartada (mesmo
    tipo e nome, ou mesmo título de cena) **não é criada de novo**.
    """
    configuracao = obter_ou_criar(sessao)
    modelo_extracao = configuracao.modelo_extracao

    if not modelo_extracao:
        raise ModeloNaoEscolhido("Nenhum modelo de extração foi escolhido. Configure um em /configuracao.")

    elementos_conhecidos = formatar_elementos_conhecidos(sessao, capitulo)

    # Os erros do provedor (chave ausente, texto longo demais, falha de rede...) sobem como estão: quem os
    # traduz para HTTP é o tratador global (imagineer/erros.py).
    contexto_do_modelo = next(
        (m.contexto for m in provedor.listar_modelos() if m.id == modelo_extracao), 0
    )
    conferir_se_cabe(capitulo.texto, contexto_do_modelo)
    extracao = provedor.extrair_elementos(
        capitulo.texto, elementos_conhecidos, modelo_extracao, capitulo.orientacao_da_analise
    )

    # PM2: a posição posta à mão sobrevive à reanálise; guarda-se antes de apagar e devolve-se a quem repetir o mesmo tipo e nome
    # (ou o mesmo título de cena).
    posicoes_manuais_de_elementos = {
        chave_normalizada(s.tipo, s.nome): s.posicao_manual
        for s in sessao.scalars(
            select(SugestaoDeElemento).where(
                SugestaoDeElemento.capitulo_id == capitulo.id,
                SugestaoDeElemento.elemento_id.is_(None),
                SugestaoDeElemento.descartada.is_(False),
                SugestaoDeElemento.posicao_manual.is_not(None),
            )
        )
    }
    posicoes_manuais_de_cenas = {
        texto_normalizado(c.titulo): c.posicao_manual
        for c in sessao.scalars(
            select(SugestaoDeCena).where(
                SugestaoDeCena.capitulo_id == capitulo.id,
                SugestaoDeCena.frame_id.is_(None),
                SugestaoDeCena.descartada.is_(False),
                SugestaoDeCena.posicao_manual.is_not(None),
            )
        )
    }
    sessao.execute(
        delete(SugestaoDeElemento).where(
            SugestaoDeElemento.capitulo_id == capitulo.id,
            SugestaoDeElemento.elemento_id.is_(None),
            SugestaoDeElemento.descartada.is_(False),
        )
    )
    sessao.execute(
        delete(SugestaoDeCena).where(
            SugestaoDeCena.capitulo_id == capitulo.id,
            SugestaoDeCena.frame_id.is_(None),
            SugestaoDeCena.descartada.is_(False),
        )
    )

    # As descartadas e as já confirmadas ficam; o que a IA repetir delas não vira sugestão nova
    # (era isso que duplicava os cartões a cada reanálise: a confirmada sobrevivia e a IA a listava de
    # novo), mas os participantes das cenas novas ainda podem apontar para elas.
    elementos_desta_rodada: dict[tuple[TipoElemento, str], SugestaoDeElemento] = {
        chave_normalizada(d.tipo, d.nome): d
        for d in sessao.scalars(
            select(SugestaoDeElemento).where(
                SugestaoDeElemento.capitulo_id == capitulo.id,
                or_(
                    SugestaoDeElemento.descartada.is_(True),
                    SugestaoDeElemento.elemento_id.is_not(None),
                ),
            )
        )
    }
    titulos_de_cenas_descartadas = {
        texto_normalizado(c.titulo)
        for c in sessao.scalars(
            select(SugestaoDeCena).where(
                SugestaoDeCena.capitulo_id == capitulo.id,
                SugestaoDeCena.descartada.is_(True),
            )
        )
    }
    for item in extracao.elementos:
        if chave_normalizada(item.tipo, item.nome) in elementos_desta_rodada:
            continue
        linha = SugestaoDeElemento(
            capitulo_id=capitulo.id,
            tipo=item.tipo,
            nome=item.nome,
            descricao=item.descricao,
            manter_estado_atual=item.manter_estado_atual,
            modelo=extracao.modelo,
            posicao_manual=posicoes_manuais_de_elementos.get(chave_normalizada(item.tipo, item.nome)),
        )
        sessao.add(linha)
        elementos_desta_rodada[chave_normalizada(item.tipo, item.nome)] = linha

    for cena in extracao.cenas:
        if texto_normalizado(cena.titulo) in titulos_de_cenas_descartadas:
            continue
        linha_cena = SugestaoDeCena(
            capitulo_id=capitulo.id,
            titulo=cena.titulo,
            descricao=cena.descricao,
            horario=cena.horario,
            clima=cena.clima,
            humor=cena.humor,
            modelo=extracao.modelo,
            trecho_ancora=cena.trecho_ancora[:300] if cena.trecho_ancora else None,
            # A posição vem da citação, calculada aqui — a IA nunca devolve número (item 3.4g).
            posicao_no_texto=posicao_da_citacao(capitulo.texto, cena.trecho_ancora),
            posicao_manual=posicoes_manuais_de_cenas.get(texto_normalizado(cena.titulo)),
        )
        for participante in cena.participantes:
            correspondente = elementos_desta_rodada.get(
                chave_normalizada(participante.tipo, participante.nome)
            )
            if correspondente is not None:
                linha_cena.participantes.append(correspondente)
        sessao.add(linha_cena)

    capitulo.sugestoes_geradas_em = datetime.now(timezone.utc)
    sessao.add(capitulo)
    sessao.commit()


def casar_sugestoes_pendentes(sessao: Session, capitulo_id: int, livro_id: int) -> None:
    """Tenta casar por nome as sugestões deste capítulo ainda sem `elemento_id`.

    Roda a cada leitura, não só na geração: se o usuário cadastrar um elemento
    entre uma chamada e outra, a próxima leitura já mostra o casamento novo,
    sem precisar de `forcar=true` (item 3.4e).
    """
    pendentes = list(
        sessao.scalars(
            select(SugestaoDeElemento).where(
                SugestaoDeElemento.capitulo_id == capitulo_id,
                SugestaoDeElemento.elemento_id.is_(None),
                # Descartada não se casa; casamento desfeito de propósito não religa sozinho.
                SugestaoDeElemento.descartada.is_(False),
                SugestaoDeElemento.casamento_desfeito.is_(False),
            )
        )
    )
    if not pendentes:
        return

    elementos_existentes = elementos_por_chave_normalizada(sessao, livro_id)
    mudou = False
    for sugestao in pendentes:
        correspondente = elementos_existentes.get(
            chave_normalizada(sugestao.tipo, sugestao.nome)
        )
        if correspondente is not None:
            sugestao.elemento_id = correspondente
            sugestao.casamento_automatico = True
            mudou = True

    if mudou:
        sessao.commit()


def sugestoes_pendentes_anteriores(sessao: Session, capitulo: Capitulo) -> int:
    """Quantas sugestões de capítulos anteriores deste livro ainda não foram
    confirmadas (item 4.6) — soma elementos e cenas, porque os dois tipos de
    confirmação pendente prejudicam igualmente o contexto que a IA recebe.
    """
    capitulos_anteriores = select(Capitulo.id).where(
        Capitulo.livro_id == capitulo.livro_id, Capitulo.ordem < capitulo.ordem
    )
    elementos_pendentes = sessao.scalar(
        select(func.count(SugestaoDeElemento.id)).where(
            SugestaoDeElemento.capitulo_id.in_(capitulos_anteriores),
            SugestaoDeElemento.elemento_id.is_(None),
            SugestaoDeElemento.descartada.is_(False),
        )
    )
    cenas_pendentes = sessao.scalar(
        select(func.count(SugestaoDeCena.id)).where(
            SugestaoDeCena.capitulo_id.in_(capitulos_anteriores),
            SugestaoDeCena.frame_id.is_(None),
            SugestaoDeCena.descartada.is_(False),
        )
    )
    return (elementos_pendentes or 0) + (cenas_pendentes or 0)


def formatar_elementos_conhecidos(sessao: Session, capitulo: Capitulo) -> list[str]:
    """Monta a lista "Nome (TIPO): identidade" que vai como contexto para a IA.

    Entram os elementos já cadastrados no livro, cada um com a sua **identidade vigente
    até o capítulo anterior** (item 3.4f) **resumida** — quem ou o que é —, e **nunca** o
    estado de aparência de um capítulo. Motivo (achado testando no tablet, 30/09/2026):
    quando recebia "Nome: aparência no capítulo 1", a IA copiava esse texto para a
    sugestão do capítulo 4, e a sugestão parecia descrever o capítulo errado. A lista serve
    a dois fins: a IA **usar o mesmo nome** de quem já existe e reconhecer apelidos pela
    identidade.

    **Tem teto** (``TETO_DO_CONTEXTO_DA_IA`` caracteres): vão primeiro os elementos que
    apareceram **mais recentemente** (o capítulo do estado vigente mais novo), e os sem estado
    por último. O que não cabe fica fora — o casamento automático é por nome, no servidor, e
    não depende desta lista.
    """
    elementos = list(
        sessao.scalars(select(Elemento).where(Elemento.livro_id == capitulo.livro_id, Elemento.apagado_em.is_(None)))
    )
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem - 1)

    def prioridade(elemento: Elemento) -> tuple[int, int, int]:
        vigente = vigentes.get(elemento.id)
        if vigente is None:
            return (1, 0, elemento.id)
        return (0, -vigente.capitulo.ordem, elemento.id)

    linhas: list[str] = []
    total = 0
    for elemento in sorted(elementos, key=prioridade):
        identidade = resumir_texto(
            identidade_vigente(sessao, elemento, capitulo.ordem - 1), LIMITE_DA_IDENTIDADE_NO_CONTEXTO
        )
        linha = f"{elemento.nome} ({elemento.tipo.name})"
        if identidade:
            linha = f"{linha}: {identidade}"
        if total + len(linha) + 1 > TETO_DO_CONTEXTO_DA_IA:
            break
        linhas.append(linha)
        total += len(linha) + 1
    return linhas


def texto_normalizado(texto: str) -> str:
    """Sem caixa nem acentuação — a base de toda comparação de nome do módulo.

    Usada tanto para casar sugestão com elemento (`chave_normalizada`) quanto
    para a busca por nome (`GET /livros/{id}/sugestoes-elemento`, item 3.4e).
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.strip().lower()


def chave_normalizada(tipo: TipoElemento, nome: str) -> tuple[TipoElemento, str]:
    """Normaliza tipo e nome para casar a sugestão da IA com um elemento existente.

    Ignora maiúsculas/minúsculas e acentuação: a IA foi instruída a repetir o nome
    exato de um elemento conhecido, mas variações de caixa e acento são comuns o
    suficiente para valer a pena tolerar, sem risco de casar elementos diferentes
    por engano — a comparação continua exigindo o mesmo tipo e (quase) o mesmo nome.
    """
    return (tipo, texto_normalizado(nome))


def elementos_por_chave_normalizada(
    sessao: Session, livro_id: int
) -> dict[tuple[TipoElemento, str], int]:
    """Mapeia (tipo, nome normalizado) -> id, para casar sugestões da IA."""
    elementos = sessao.scalars(select(Elemento).where(Elemento.livro_id == livro_id, Elemento.apagado_em.is_(None)))
    return {
        chave_normalizada(elemento.tipo, elemento.nome): elemento.id
        for elemento in elementos
    }
