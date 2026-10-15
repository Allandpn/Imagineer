"""A correção dos ids ``:batch`` já salvos (migração ``c5d6e7f8a9b1``): a configuração, a lista de imagens e as trocas por livro passam a usar o
modelo sem o sufixo, e o resto fica como estava."""

from sqlalchemy.orm import Session

from imagineer.modelos import Configuracao, Livro, Usuario
from imagineer.servicos.correcao_de_modelos_em_lote import corrigir_modelos_em_lote


def _corrigir(sessao: Session) -> int:
    sessao.commit()
    trocados = corrigir_modelos_em_lote(sessao.connection())
    sessao.commit()
    sessao.expire_all()
    return trocados


def teste_a_configuracao_salva_com_batch_passa_a_usar_o_modelo_sem_o_sufixo(sessao_com_tabelas: Session) -> None:
    sessao_com_tabelas.add(
        Configuracao(
            id=1,
            modelo_extracao="google/gemini-4-argon:batch",
            modelo_prompt="openai/gpt-4o-mini",
            modelo_leitura="  Google/Gemini-4-Argon:BATCH ",
            modelo_narracao="a/voz:batch",
        )
    )

    trocados = _corrigir(sessao_com_tabelas)

    configuracao = sessao_com_tabelas.get(Configuracao, 1)
    assert configuracao.modelo_extracao == "google/gemini-4-argon"
    assert configuracao.modelo_leitura == "Google/Gemini-4-Argon"  # caixa e espaços das pontas: só o sufixo sai
    assert configuracao.modelo_narracao == "a/voz"
    assert configuracao.modelo_prompt == "openai/gpt-4o-mini"  # o que não é lote fica como está
    assert trocados == 3


def teste_a_lista_de_modelos_de_imagem_troca_e_nao_repete(sessao_com_tabelas: Session) -> None:
    sessao_com_tabelas.add(Configuracao(id=1, modelos_de_imagem=["a/b", "c/d:batch", "a/b:batch", "e/f"]))

    _corrigir(sessao_com_tabelas)

    assert sessao_com_tabelas.get(Configuracao, 1).modelos_de_imagem == ["a/b", "c/d", "e/f"]  # "a/b:batch" virou "a/b", que já estava


def teste_a_configuracao_de_cada_pessoa_e_corrigida(sessao_com_tabelas: Session) -> None:
    maria = Usuario(login="maria@exemplo.com", nome="maria")
    sessao_com_tabelas.add(maria)
    sessao_com_tabelas.commit()
    sessao_com_tabelas.add_all([Configuracao(id=1, modelo_video="x/y:batch"), Configuracao(id=maria.id, modelo_reserva="z/w:batch")])

    _corrigir(sessao_com_tabelas)

    assert sessao_com_tabelas.get(Configuracao, 1).modelo_video == "x/y"
    assert sessao_com_tabelas.get(Configuracao, maria.id).modelo_reserva == "z/w"


def teste_as_trocas_por_livro_sao_corrigidas_e_as_sem_lote_ficam(sessao_com_tabelas: Session) -> None:
    com_lote = Livro(titulo="A", nome_arquivo="a.epub", modelos={"modelo_prompt": "x/y:batch", "modelo_leitura": "k/l"})
    sem_troca = Livro(titulo="B", nome_arquivo="b.epub")
    sessao_com_tabelas.add_all([com_lote, sem_troca])

    trocados = _corrigir(sessao_com_tabelas)

    assert com_lote.modelos == {"modelo_prompt": "x/y", "modelo_leitura": "k/l"}
    assert sem_troca.modelos is None
    assert trocados == 1


def teste_e_idempotente_e_sem_nada_a_corrigir_devolve_zero(sessao_com_tabelas: Session) -> None:
    sessao_com_tabelas.add(Configuracao(id=1, modelo_extracao="google/gemini-4-argon:batch"))
    assert _corrigir(sessao_com_tabelas) == 1

    assert _corrigir(sessao_com_tabelas) == 0  # rodar de novo não acha mais nada
    assert sessao_com_tabelas.get(Configuracao, 1).modelo_extracao == "google/gemini-4-argon"
