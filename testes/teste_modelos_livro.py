"""Testes dos modelos Livro e Capitulo (item 3.4a).

Cada teste prova uma decisão de modelagem registrada na especificação — não
apenas que o código roda, mas que a regra que ele deveria garantir vale mesmo.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro


def _livro_de_exemplo(**ajustes) -> Livro:
    """Monta um Livro válido, permitindo trocar campos pontualmente."""
    dados = {
        "titulo": "A Guerra dos Tronos",
        "autor": "George R. R. Martin",
        "idioma": "pt-BR",
        "identificador_epub": "urn:isbn:9788580410150",
        "nome_arquivo": "guerra_dos_tronos.epub",
    }
    dados.update(ajustes)
    return Livro(**dados)


def teste_data_importacao_e_preenchida_pelo_banco(sessao_com_tabelas: Session) -> None:
    """O horário da importação vem do banco, não do Python.

    Por isso nem passamos o campo ao criar o livro: quem preenche é o
    ``server_default``, garantindo um horário consistente entre registros.
    """
    livro = _livro_de_exemplo()
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()
    sessao_com_tabelas.refresh(livro)

    assert livro.id is not None
    assert livro.data_importacao is not None


def teste_campos_opcionais_aceitam_nulo(sessao_com_tabelas: Session) -> None:
    """Muitos EPUBs não trazem autor nem idioma — importar não pode falhar por isso."""
    livro = _livro_de_exemplo(autor=None, idioma=None, identificador_epub=None)
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()

    assert livro.autor is None
    assert livro.idioma is None


def teste_capitulos_vem_ordenados_pela_ordem_e_nao_pelo_id(
    sessao_com_tabelas: Session,
) -> None:
    """A sequência de leitura é a do campo ``ordem``, não a de inserção.

    Inserimos de propósito na ordem 3, 1, 2 — que é o que aconteceria se o
    parsing do EPUB processasse os arquivos fora de sequência. Os ids saem
    nessa ordem, mas a leitura precisa sair 1, 2, 3.
    """
    livro = _livro_de_exemplo()
    livro.capitulos = [
        Capitulo(ordem=3, titulo="Terceiro", texto="..."),
        Capitulo(ordem=1, titulo="Primeiro", texto="..."),
        Capitulo(ordem=2, titulo="Segundo", texto="..."),
    ]
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()

    # expire faz o próximo acesso recarregar do banco, aplicando o order_by
    # declarado no relationship — em vez de devolver a lista que montamos.
    sessao_com_tabelas.expire(livro)

    assert [c.ordem for c in livro.capitulos] == [1, 2, 3]
    assert [c.titulo for c in livro.capitulos] == ["Primeiro", "Segundo", "Terceiro"]


def teste_nao_permite_dois_capitulos_na_mesma_posicao(
    sessao_com_tabelas: Session,
) -> None:
    """A restrição de unicidade (livro_id, ordem) é garantida pelo banco.

    Um erro no parsing poderia gerar dois "capítulo 1" no mesmo livro. Sem a
    restrição, o banco aceitaria em silêncio e a inconsistência só apareceria
    muito depois, na tela do app.
    """
    livro = _livro_de_exemplo()
    livro.capitulos = [
        Capitulo(ordem=1, titulo="Primeiro", texto="..."),
        Capitulo(ordem=1, titulo="Duplicado", texto="..."),
    ]
    sessao_com_tabelas.add(livro)

    with pytest.raises(IntegrityError):
        sessao_com_tabelas.commit()


def teste_mesma_ordem_e_permitida_em_livros_diferentes(
    sessao_com_tabelas: Session,
) -> None:
    """A unicidade é por livro: todo livro tem o seu capítulo 1."""
    primeiro = _livro_de_exemplo(titulo="Livro A", nome_arquivo="a.epub")
    primeiro.capitulos = [Capitulo(ordem=1, titulo="Abertura", texto="...")]
    segundo = _livro_de_exemplo(titulo="Livro B", nome_arquivo="b.epub")
    segundo.capitulos = [Capitulo(ordem=1, titulo="Prólogo", texto="...")]

    sessao_com_tabelas.add_all([primeiro, segundo])
    sessao_com_tabelas.commit()

    capitulos = sessao_com_tabelas.scalars(select(Capitulo)).all()
    assert len(capitulos) == 2
    assert {c.ordem for c in capitulos} == {1}
    assert len({c.livro_id for c in capitulos}) == 2


def teste_apagar_livro_apaga_seus_capitulos(sessao_com_tabelas: Session) -> None:
    """Um capítulo não existe sem o livro a que pertence.

    Sem o cascade, sobrariam capítulos órfãos apontando para um livro que não
    existe mais — e a chave estrangeira recusaria o DELETE do livro.
    """
    livro = _livro_de_exemplo()
    livro.capitulos = [
        Capitulo(ordem=1, titulo="Primeiro", texto="..."),
        Capitulo(ordem=2, titulo="Segundo", texto="..."),
    ]
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()

    assert len(sessao_com_tabelas.scalars(select(Capitulo)).all()) == 2

    sessao_com_tabelas.delete(livro)
    sessao_com_tabelas.commit()

    assert sessao_com_tabelas.scalars(select(Capitulo)).all() == []
    assert sessao_com_tabelas.scalars(select(Livro)).all() == []


def teste_capitulo_conhece_o_livro_a_que_pertence(sessao_com_tabelas: Session) -> None:
    """O relacionamento funciona nos dois sentidos (``back_populates``)."""
    livro = _livro_de_exemplo()
    capitulo = Capitulo(ordem=1, titulo="Primeiro", texto="...")
    livro.capitulos = [capitulo]
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()

    assert capitulo.livro is livro
    assert capitulo.livro.titulo == "A Guerra dos Tronos"
