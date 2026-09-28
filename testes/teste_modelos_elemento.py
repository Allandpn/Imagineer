"""Testes dos modelos Elemento e EstadoElemento (item 3.4b).

O foco está na separação identidade/estado — a ideia central da modelagem — e
na consulta que descobre o "último estado conhecido", de que o item 4.4 depende.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    HistoricoIdentidadeElemento,
    Livro,
    TipoElemento,
)
from imagineer.servicos.identidade_de_elemento import identidade_vigente


def _livro_com_capitulos(sessao: Session, quantidade: int = 3) -> Livro:
    """Cria um livro com N capítulos numerados de 1 a N, já gravado."""
    livro = Livro(titulo="Livro de Teste", nome_arquivo="teste.epub")
    livro.capitulos = [
        Capitulo(ordem=i, titulo=f"Capítulo {i}", texto="...")
        for i in range(1, quantidade + 1)
    ]
    sessao.add(livro)
    sessao.commit()
    return livro


def _buscar_ultimo_estado(
    sessao: Session, elemento: Elemento, capitulo: Capitulo
) -> EstadoElemento | None:
    """Descobre o estado vigente de um elemento em um ponto da narrativa.

    É a consulta descrita no item 3.4b, que o item 4.4 vai usar para dar
    contexto à IA. Reproduzida aqui para provar que o modelo a suporta; a
    implementação definitiva morará em ``imagineer/servicos/``.

    A ordenação é por ``Capitulo.ordem`` — e não por ``data_criacao`` ou pelo
    id do estado — porque o usuário pode processar capítulos fora de ordem.
    """
    return sessao.scalars(
        select(EstadoElemento)
        .join(Capitulo, EstadoElemento.capitulo_id == Capitulo.id)
        .where(
            EstadoElemento.elemento_id == elemento.id,
            Capitulo.ordem <= capitulo.ordem,
        )
        .order_by(Capitulo.ordem.desc(), EstadoElemento.id.desc())
        .limit(1)
    ).first()


def teste_elemento_guarda_identidade_e_estado_guarda_aparencia(
    sessao_com_tabelas: Session,
) -> None:
    """A identidade fica no Elemento; a aparência, em cada EstadoElemento.

    É o que permite ao capítulo 40 usar a aparência do capítulo 40, sem perder
    a do capítulo 3 nem sobrescrevê-la.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas)
    personagem = Elemento(
        livro_id=livro.id,
        tipo=TipoElemento.PERSONAGEM,
        nome="Arya",
        descricao="A filha mais nova dos Stark.",
    )
    personagem.estados = [
        EstadoElemento(
            capitulo_id=livro.capitulos[0].id, descricao="Menina, vestido azul."
        ),
        EstadoElemento(
            capitulo_id=livro.capitulos[2].id, descricao="Cabelo raspado, roupas de rua."
        ),
    ]
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    # A identidade não mudou; a aparência tem duas versões, ambas preservadas.
    assert personagem.descricao == "A filha mais nova dos Stark."
    assert len(personagem.estados) == 2


def teste_tipo_invalido_e_recusado(sessao_com_tabelas: Session) -> None:
    """Um tipo fora do enum falha — a validação existe em Python e no banco."""
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    sessao_com_tabelas.add(
        Elemento(livro_id=livro.id, tipo="DRAGAO_VOADOR", nome="Ilegal")
    )

    with pytest.raises((StatementError, LookupError)):
        sessao_com_tabelas.commit()


def teste_nao_permite_o_mesmo_elemento_duas_vezes_no_livro(
    sessao_com_tabelas: Session,
) -> None:
    """A unicidade (livro_id, tipo, nome) barra cadastro duplicado.

    É a proteção contra a extração automática sugerir o mesmo personagem em
    dois capítulos e criá-lo duas vezes.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    sessao_com_tabelas.add_all(
        [
            Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Jon"),
            Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Jon"),
        ]
    )

    with pytest.raises(IntegrityError):
        sessao_com_tabelas.commit()


def teste_mesmo_nome_e_permitido_em_tipos_diferentes(
    sessao_com_tabelas: Session,
) -> None:
    """A região Winterfell e o castelo Winterfell são registros distintos."""
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    sessao_com_tabelas.add_all(
        [
            Elemento(livro_id=livro.id, tipo=TipoElemento.AMBIENTE, nome="Winterfell"),
            Elemento(
                livro_id=livro.id, tipo=TipoElemento.EDIFICACAO, nome="Winterfell"
            ),
        ]
    )
    sessao_com_tabelas.commit()

    assert len(sessao_com_tabelas.scalars(select(Elemento)).all()) == 2


def teste_ultimo_estado_conhecido_respeita_a_ordem_narrativa(
    sessao_com_tabelas: Session,
) -> None:
    """O estado vigente é o do último capítulo *até* o ponto consultado.

    No capítulo 2 vale o estado criado no capítulo 1, porque o do capítulo 3
    ainda não aconteceu na história.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=3)
    cap1, cap2, cap3 = livro.capitulos

    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Jon")
    personagem.estados = [
        EstadoElemento(capitulo_id=cap1.id, descricao="Manto negro, sem cicatrizes."),
        EstadoElemento(capitulo_id=cap3.id, descricao="Cicatriz no rosto."),
    ]
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    assert (
        _buscar_ultimo_estado(sessao_com_tabelas, personagem, cap1).descricao
        == "Manto negro, sem cicatrizes."
    )
    assert (
        _buscar_ultimo_estado(sessao_com_tabelas, personagem, cap2).descricao
        == "Manto negro, sem cicatrizes."
    )
    assert (
        _buscar_ultimo_estado(sessao_com_tabelas, personagem, cap3).descricao
        == "Cicatriz no rosto."
    )


def teste_ultimo_estado_ignora_a_ordem_em_que_foi_cadastrado(
    sessao_com_tabelas: Session,
) -> None:
    """Processar capítulos fora de ordem não confunde a consulta.

    Aqui o estado do capítulo 3 é cadastrado **antes** do estado do capítulo 1
    — o que acontece se o usuário revisitar um capítulo antigo. Ordenar por
    data de criação ou por id do estado daria a resposta errada; ordenar por
    ``Capitulo.ordem`` dá a certa.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=3)
    cap1, _cap2, cap3 = livro.capitulos
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Jon")
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    estado_tardio = EstadoElemento(
        elemento_id=personagem.id, capitulo_id=cap3.id, descricao="Cicatriz no rosto."
    )
    sessao_com_tabelas.add(estado_tardio)
    sessao_com_tabelas.commit()

    estado_inicial = EstadoElemento(
        elemento_id=personagem.id, capitulo_id=cap1.id, descricao="Sem cicatrizes."
    )
    sessao_com_tabelas.add(estado_inicial)
    sessao_com_tabelas.commit()

    # O estado inicial tem id MAIOR, mas pertence a um capítulo anterior.
    assert estado_inicial.id > estado_tardio.id
    assert (
        _buscar_ultimo_estado(sessao_com_tabelas, personagem, cap1).descricao
        == "Sem cicatrizes."
    )


def teste_dois_estados_no_mesmo_capitulo_sao_permitidos(
    sessao_com_tabelas: Session,
) -> None:
    """Um personagem pode entrar ferido e sair curado no mesmo capítulo.

    Por isso não existe unicidade em (elemento_id, capitulo_id). O desempate
    entre os dois é o id: o maior é o mais adiante na narrativa.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    capitulo = livro.capitulos[0]
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Jon")
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    for descricao in ("Ferido, sangrando.", "Curado, cicatriz nova."):
        sessao_com_tabelas.add(
            EstadoElemento(
                elemento_id=personagem.id, capitulo_id=capitulo.id, descricao=descricao
            )
        )
        sessao_com_tabelas.commit()

    assert (
        _buscar_ultimo_estado(sessao_com_tabelas, personagem, capitulo).descricao
        == "Curado, cicatriz nova."
    )


def teste_sem_estado_cadastrado_a_consulta_devolve_nada(
    sessao_com_tabelas: Session,
) -> None:
    """Um elemento recém-descoberto não tem estado anterior.

    O item 4.4 precisa lidar com este caso: é a primeira aparição, e não há
    "último estado conhecido" para mandar de contexto à IA.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Novo")
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    assert (
        _buscar_ultimo_estado(sessao_com_tabelas, personagem, livro.capitulos[0]) is None
    )


def teste_apagar_livro_apaga_elementos_e_seus_estados(
    sessao_com_tabelas: Session,
) -> None:
    """O cascade percorre a cadeia inteira: Livro -> Elemento -> Estado."""
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Jon")
    personagem.estados = [
        EstadoElemento(capitulo_id=livro.capitulos[0].id, descricao="Manto negro.")
    ]
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(livro)
    sessao_com_tabelas.commit()

    assert sessao_com_tabelas.scalars(select(Elemento)).all() == []
    assert sessao_com_tabelas.scalars(select(EstadoElemento)).all() == []


# --------------------------------------------------------------------------- #
# HistoricoIdentidadeElemento (item 3.4f) — identidade evolutiva, cumulativa
# --------------------------------------------------------------------------- #


def teste_identidade_vigente_soma_identidade_inicial_com_incrementos(
    sessao_com_tabelas: Session,
) -> None:
    """Ao contrário da aparência, identidade **acumula** — não é "última vale"."""
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=3)
    cap1, cap2, cap3 = livro.capitulos

    personagem = Elemento(
        livro_id=livro.id,
        tipo=TipoElemento.PERSONAGEM,
        nome="Vis",
        descricao="Um jovem aprendiz de ferreiro.",
    )
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    sessao_com_tabelas.add_all(
        [
            HistoricoIdentidadeElemento(
                elemento_id=personagem.id,
                capitulo_id=cap2.id,
                descricao="É filho adotivo do ferreiro, não o filho de sangue.",
            ),
            HistoricoIdentidadeElemento(
                elemento_id=personagem.id,
                capitulo_id=cap3.id,
                descricao="Guarda um segredo: já matou um homem.",
            ),
        ]
    )
    sessao_com_tabelas.commit()

    assert identidade_vigente(sessao_com_tabelas, personagem, cap1.ordem) == (
        "Um jovem aprendiz de ferreiro."
    )
    assert identidade_vigente(sessao_com_tabelas, personagem, cap2.ordem) == (
        "Um jovem aprendiz de ferreiro. "
        "É filho adotivo do ferreiro, não o filho de sangue."
    )
    assert identidade_vigente(sessao_com_tabelas, personagem, cap3.ordem) == (
        "Um jovem aprendiz de ferreiro. "
        "É filho adotivo do ferreiro, não o filho de sangue. "
        "Guarda um segredo: já matou um homem."
    )


def teste_identidade_vigente_nao_vaza_revelacao_de_capitulo_posterior(
    sessao_com_tabelas: Session,
) -> None:
    """Processar capítulos fora de ordem não deve vazar spoiler retroativo.

    Se o capítulo 10 é processado antes do capítulo 4, a identidade vigente
    consultada no capítulo 4 nunca deveria incluir o que só o capítulo 10
    revelou — mesmo princípio de ``Capitulo.ordem`` já usado pela aparência.
    """
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=10)
    cap4, cap10 = livro.capitulos[3], livro.capitulos[9]

    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Vis")
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    # Processado fora de ordem: capítulo 10 antes do capítulo 4.
    sessao_com_tabelas.add(
        HistoricoIdentidadeElemento(
            elemento_id=personagem.id,
            capitulo_id=cap10.id,
            descricao="Revelação: é o herdeiro perdido do reino.",
        )
    )
    sessao_com_tabelas.commit()

    assert identidade_vigente(sessao_com_tabelas, personagem, cap4.ordem) is None


def teste_identidade_vigente_sem_nada_devolve_nulo(
    sessao_com_tabelas: Session,
) -> None:
    """Sem identidade inicial nem incrementos, não há o que devolver."""
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Sem Nome")
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    assert (
        identidade_vigente(sessao_com_tabelas, personagem, livro.capitulos[0].ordem)
        is None
    )


def teste_apagar_elemento_apaga_seu_historico_de_identidade(
    sessao_com_tabelas: Session,
) -> None:
    """O cascade percorre a cadeia: Elemento -> HistoricoIdentidadeElemento."""
    livro = _livro_com_capitulos(sessao_com_tabelas, quantidade=1)
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Vis")
    personagem.historico_identidade = [
        HistoricoIdentidadeElemento(
            capitulo_id=livro.capitulos[0].id, descricao="Algo novo."
        )
    ]
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(personagem)
    sessao_com_tabelas.commit()

    assert sessao_com_tabelas.scalars(select(HistoricoIdentidadeElemento)).all() == []
