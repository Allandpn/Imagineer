"""Testes de Frame, PerfilRenderizacao, Prompt e Imagem (item 3.4c).

Além de cada entidade isolada, há um teste que percorre a cadeia inteira do
fluxo — livro, capítulo, elemento, estado, frame, prompt, imagem, âncora —
porque é a integração entre elas que o modelo existe para sustentar.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    Imagem,
    Livro,
    PerfilRenderizacao,
    Prompt,
    TipoDeFrame,
    TipoElemento,
)


def _livro_com_um_capitulo(sessao: Session) -> tuple[Livro, Capitulo]:
    """Cria um livro com um capítulo, já gravado."""
    livro = Livro(titulo="Livro de Teste", nome_arquivo="teste.epub")
    capitulo = Capitulo(ordem=1, titulo="Capítulo 1", texto="...")
    livro.capitulos = [capitulo]
    sessao.add(livro)
    sessao.commit()
    return livro, capitulo


def _perfil(sessao: Session, nome: str = "Aquarela sombria") -> PerfilRenderizacao:
    perfil = PerfilRenderizacao(
        nome=nome,
        estilo="aquarela",
        iluminacao="penumbra de vela",
        paleta="tons frios e dessaturados",
        formato="16:9",
    )
    sessao.add(perfil)
    sessao.commit()
    return perfil


def teste_perfil_de_renderizacao_nao_pertence_a_um_livro(
    sessao_com_tabelas: Session,
) -> None:
    """O mesmo perfil pode ser o padrão de dois livros diferentes.

    É o ponto do item 3.3: um perfil reutilizável entre obras, em vez de um
    campo "estilo" preso a cada livro.
    """
    perfil = _perfil(sessao_com_tabelas)
    primeiro = Livro(
        titulo="Livro A", nome_arquivo="a.epub", perfil_renderizacao_padrao_id=perfil.id
    )
    segundo = Livro(
        titulo="Livro B", nome_arquivo="b.epub", perfil_renderizacao_padrao_id=perfil.id
    )
    sessao_com_tabelas.add_all([primeiro, segundo])
    sessao_com_tabelas.commit()

    assert primeiro.perfil_renderizacao_padrao.nome == "Aquarela sombria"
    assert segundo.perfil_renderizacao_padrao is primeiro.perfil_renderizacao_padrao


def teste_nome_do_perfil_e_unico(sessao_com_tabelas: Session) -> None:
    """Dois perfis com o mesmo nome seriam indistinguíveis na tela de escolha."""
    _perfil(sessao_com_tabelas)
    sessao_com_tabelas.add(PerfilRenderizacao(nome="Aquarela sombria"))

    with pytest.raises(IntegrityError):
        sessao_com_tabelas.commit()


def teste_apagar_perfil_nao_apaga_o_livro(sessao_com_tabelas: Session) -> None:
    """O ON DELETE SET NULL protege o dado narrativo.

    Apagar um perfil de estilo desfaz a referência, mas o livro — e todo o
    trabalho de catalogação feito nele — permanece.
    """
    perfil = _perfil(sessao_com_tabelas)
    livro = Livro(
        titulo="Livro A", nome_arquivo="a.epub", perfil_renderizacao_padrao_id=perfil.id
    )
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(perfil)
    sessao_com_tabelas.commit()
    sessao_com_tabelas.expire(livro)

    assert sessao_com_tabelas.get(Livro, livro.id) is not None
    assert livro.perfil_renderizacao_padrao_id is None


def teste_frame_guarda_os_atributos_situacionais(sessao_com_tabelas: Session) -> None:
    """Horário, clima e humor ficam no próprio Frame, sem entidade "Contexto"."""
    _livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    frame = Frame(
        capitulo_id=capitulo.id,
        tipo=TipoDeFrame.CENA,
        titulo="A chegada do rei a Winterfell",
        descricao="A comitiva real atravessa o portão.",
        horario="fim de tarde",
        clima="neve fina",
        humor="tensão contida",
    )
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()

    assert frame.horario == "fim de tarde"
    assert frame.capitulo is capitulo


def teste_frame_padrao_e_do_tipo_cena(sessao_com_tabelas: Session) -> None:
    """O `server_default` existe para as linhas já criadas antes deste campo."""
    _livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()
    sessao_com_tabelas.refresh(frame)

    assert frame.tipo is TipoDeFrame.CENA
    assert frame.confirmado_pela_leitura_profunda is False


def teste_frame_referencia_o_estado_e_nao_apenas_o_elemento(
    sessao_com_tabelas: Session,
) -> None:
    """O frame sabe *como* o personagem estava, não só que ele estava lá.

    É a razão de a tabela de associação ligar Frame a EstadoElemento: ligado ao
    Elemento, o frame não saberia qual das versões do personagem usar no prompt.
    """
    livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    personagem = Elemento(
        livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Ned Stark"
    )
    estado = EstadoElemento(capitulo_id=capitulo.id, descricao="Capa de pele, barba grisalha.")
    personagem.estados = [estado]
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    frame.estados_elemento = [estado]
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()

    # O frame chega até a aparência, passando pelo estado.
    assert frame.estados_elemento[0].descricao == "Capa de pele, barba grisalha."
    # E até a identidade, passando pelo elemento.
    assert frame.estados_elemento[0].elemento.nome == "Ned Stark"
    # A navegação funciona no sentido inverso (item 3.2: muitos-para-muitos).
    assert estado.frames == [frame]


def teste_apagar_frame_nao_apaga_os_estados_que_ele_usava(
    sessao_com_tabelas: Session,
) -> None:
    """Um estado pertence ao elemento e à narrativa, não ao frame que o citou.

    Apagar um frame desfaz as ligações, mas o estado do personagem continua
    valendo para os outros frames e para os capítulos seguintes.
    """
    livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Ned")
    estado = EstadoElemento(capitulo_id=capitulo.id, descricao="Capa de pele.")
    personagem.estados = [estado]
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    frame.estados_elemento = [estado]
    sessao_com_tabelas.add_all([personagem, frame])
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(frame)
    sessao_com_tabelas.commit()

    assert sessao_com_tabelas.get(EstadoElemento, estado.id) is not None
    assert sessao_com_tabelas.scalars(select(Frame)).all() == []


def teste_um_prompt_pode_ter_varias_imagens(sessao_com_tabelas: Session) -> None:
    """O mesmo prompt gerado duas vezes rende duas imagens no catálogo.

    Divergência consciente do item 3.2, registrada no item 3.4c: na prática se
    gera o mesmo prompt mais de uma vez, ou em duas ferramentas diferentes.
    """
    _livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()

    prompt = Prompt(frame_id=frame.id, texto="aquarela, pátio nevado, ...")
    prompt.imagens = [
        Imagem(caminho_arquivo="livro-1/frame-1/tentativa-a.png"),
        Imagem(caminho_arquivo="livro-1/frame-1/tentativa-b.png"),
    ]
    sessao_com_tabelas.add(prompt)
    sessao_com_tabelas.commit()

    assert len(prompt.imagens) == 2
    assert prompt.imagens[0].prompt is prompt


def teste_caminho_do_arquivo_e_unico(sessao_com_tabelas: Session) -> None:
    """Dois registros apontando para o mesmo arquivo seriam duplicata no catálogo."""
    _livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()
    prompt = Prompt(frame_id=frame.id, texto="...")
    sessao_com_tabelas.add(prompt)
    sessao_com_tabelas.commit()

    sessao_com_tabelas.add_all([
        Imagem(prompt_id=prompt.id, caminho_arquivo="mesma.png"),
        Imagem(prompt_id=prompt.id, caminho_arquivo="mesma.png"),
    ])

    with pytest.raises(IntegrityError):
        sessao_com_tabelas.commit()


def teste_apagar_perfil_nao_apaga_o_historico_de_prompts(
    sessao_com_tabelas: Session,
) -> None:
    """Uma limpeza de perfis não pode destruir o registro do que foi gerado."""
    perfil = _perfil(sessao_com_tabelas)
    _livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()
    prompt = Prompt(
        frame_id=frame.id, texto="aquarela, ...", perfil_renderizacao_id=perfil.id
    )
    sessao_com_tabelas.add(prompt)
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(perfil)
    sessao_com_tabelas.commit()
    sessao_com_tabelas.expire(prompt)

    assert sessao_com_tabelas.get(Prompt, prompt.id) is not None
    assert prompt.texto == "aquarela, ..."
    assert prompt.perfil_renderizacao_id is None


def teste_apagar_imagem_ancora_nao_apaga_o_estado(sessao_com_tabelas: Session) -> None:
    """Apagar a imagem de referência não pode apagar a aparência do personagem."""
    livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()
    prompt = Prompt(frame_id=frame.id, texto="...")
    prompt.imagens = [Imagem(caminho_arquivo="ned.png")]
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Ned")
    estado = EstadoElemento(capitulo_id=capitulo.id, descricao="Capa de pele.")
    personagem.estados = [estado]
    sessao_com_tabelas.add_all([prompt, personagem])
    sessao_com_tabelas.commit()

    estado.imagem_ancora_id = prompt.imagens[0].id
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(prompt.imagens[0])
    sessao_com_tabelas.commit()
    sessao_com_tabelas.expire(estado)

    assert sessao_com_tabelas.get(EstadoElemento, estado.id) is not None
    assert estado.descricao == "Capa de pele."
    assert estado.imagem_ancora_id is None


def teste_fluxo_completo_do_livro_ate_a_imagem_ancorada(
    sessao_com_tabelas: Session,
) -> None:
    """Percorre a cadeia inteira do fluxo da Etapa 2, de ponta a ponta.

    Livro -> Capítulo -> Elemento -> Estado -> Frame -> Prompt -> Imagem, e a
    imagem voltando a ser a âncora visual do estado. É esta integração que
    justifica a modelagem toda.
    """
    perfil = _perfil(sessao_com_tabelas)

    livro = Livro(
        titulo="A Guerra dos Tronos",
        autor="George R. R. Martin",
        nome_arquivo="guerra.epub",
        perfil_renderizacao_padrao_id=perfil.id,
    )
    capitulo = Capitulo(ordem=1, titulo="Bran", texto="O rei chegou ao pátio...")
    livro.capitulos = [capitulo]
    sessao_com_tabelas.add(livro)
    sessao_com_tabelas.commit()

    personagem = Elemento(
        livro_id=livro.id,
        tipo=TipoElemento.PERSONAGEM,
        nome="Ned Stark",
        descricao="Senhor de Winterfell.",
    )
    estado = EstadoElemento(
        capitulo_id=capitulo.id, descricao="Capa de pele, barba grisalha."
    )
    personagem.estados = [estado]
    sessao_com_tabelas.add(personagem)
    sessao_com_tabelas.commit()

    frame = Frame(
        capitulo_id=capitulo.id,
        titulo="A chegada do rei",
        horario="fim de tarde",
        clima="neve fina",
    )
    frame.estados_elemento = [estado]
    sessao_com_tabelas.add(frame)
    sessao_com_tabelas.commit()

    prompt = Prompt(
        frame_id=frame.id,
        perfil_renderizacao_id=perfil.id,
        modelo_ia="algum-modelo-gratuito",
        texto="aquarela, pátio nevado ao fim da tarde, homem de capa de pele...",
        avaliacao="Acertou o clima, errou a idade do personagem.",
    )
    imagem = Imagem(caminho_arquivo="guerra/cap-1/chegada-do-rei.png")
    prompt.imagens = [imagem]
    sessao_com_tabelas.add(prompt)
    sessao_com_tabelas.commit()

    estado.imagem_ancora_id = imagem.id
    sessao_com_tabelas.commit()

    # A partir da imagem do catálogo, é possível voltar até o livro de origem.
    assert imagem.prompt.frame.capitulo.livro.titulo == "A Guerra dos Tronos"
    # E o estado do personagem agora tem uma referência visual aprovada.
    assert estado.imagem_ancora.caminho_arquivo == "guerra/cap-1/chegada-do-rei.png"
    # O perfil usado no prompt é recuperável para comparar modelos depois.
    assert prompt.perfil_renderizacao.nome == "Aquarela sombria"


def teste_apagar_livro_limpa_a_cadeia_inteira(sessao_com_tabelas: Session) -> None:
    """Apagar um livro desfaz tudo o que só existia por causa dele.

    O perfil de renderização é a exceção de propósito: ele não pertence ao
    livro e continua disponível para os outros.
    """
    perfil = _perfil(sessao_com_tabelas)
    livro, capitulo = _livro_com_um_capitulo(sessao_com_tabelas)
    livro.perfil_renderizacao_padrao_id = perfil.id
    personagem = Elemento(livro_id=livro.id, tipo=TipoElemento.PERSONAGEM, nome="Ned")
    estado = EstadoElemento(capitulo_id=capitulo.id, descricao="Capa de pele.")
    personagem.estados = [estado]
    frame = Frame(capitulo_id=capitulo.id, titulo="No pátio")
    frame.estados_elemento = [estado]
    # Ligar pelo relacionamento, e não por frame_id: o frame ainda não foi
    # gravado, então o id dele ainda é None. O SQLAlchemy resolve a ordem das
    # inserções e preenche a chave estrangeira sozinho.
    prompt = Prompt(texto="...", perfil_renderizacao_id=perfil.id)
    prompt.imagens = [Imagem(caminho_arquivo="ned.png")]
    frame.prompts = [prompt]
    sessao_com_tabelas.add_all([personagem, frame])
    sessao_com_tabelas.commit()

    sessao_com_tabelas.delete(livro)
    sessao_com_tabelas.commit()

    for modelo in (Livro, Capitulo, Elemento, EstadoElemento, Frame, Prompt, Imagem):
        assert sessao_com_tabelas.scalars(select(modelo)).all() == [], modelo.__name__

    # O perfil sobrevive: não era do livro.
    assert sessao_com_tabelas.get(PerfilRenderizacao, perfil.id) is not None
