"""Sobe a `revisao` de um livro a cada mudança no que o leitor mostra (item 6.9).

**Por que um ouvinte do banco, e não uma chamada em cada rota.** Uma função chamada à mão em
cada rota que altera dados é fácil de esquecer numa rota nova — e esquecer faz o app mostrar
dados velhos **em silêncio**. Aqui, toda gravação passa por ``before_flush``, então nenhuma rota
precisa lembrar de nada.

**O que conta como mudança.** Qualquer objeto novo, alterado ou apagado que pertença a um livro
(capítulo, elemento, estado, frame, prompt, imagem, sugestões...), com duas exceções:

- mudar só um campo que **não aparece** para o leitor (o tamanho de uma imagem calculado pelo
  manifesto, o próprio contador): ver ``_CAMPOS_QUE_NAO_CONTAM``;
- livros criados ou apagados na mesma gravação: não há o que revisar.

**O ponto cego que o ORM não vê:** apagar um perfil de renderização faz o *banco* zerar
(``ON DELETE SET NULL``) o perfil padrão dos livros que o usavam e o perfil dos prompts — sem
nenhum evento do ORM, e com efeito visível. Por isso a exclusão de um perfil é tratada à parte,
subindo a revisão de cada livro atingido.

**Operações em massa** (``delete(...)`` direto) também não disparam eventos. Hoje só existem duas,
em ``_gerar_sugestoes``, e sempre seguidas de mudanças pelo ORM no mesmo fluxo (as sugestões novas
e ``sugestoes_geradas_em``). Uma operação em massa nova que altere dados visíveis **sem** nenhuma
mudança pelo ORM junto precisaria subir a revisão à mão.
"""

from sqlalchemy import event, inspect, select
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
    SugestaoDeCena,
    SugestaoDeElemento,
)
from imagineer.modelos.elemento import HistoricoIdentidadeElemento

_CAMPOS_QUE_NAO_CONTAM: dict[type, set[str]] = {
    Livro: {"revisao"},
    # O tamanho e as dimensões são calculados do disco numa leitura (manifesto de mídias, artefatos);
    # não mudam o que o leitor vê, e uma leitura que subisse a revisão faria o app reler para sempre.
    Imagem: {"tamanho_em_bytes", "largura", "altura"},
}
"""Campos cuja mudança, sozinha, **não** sobe a revisão."""


def _livro_do_capitulo(sessao: Session, capitulo_id: int | None, capitulo: Capitulo | None = None) -> int | None:
    if capitulo is not None and capitulo.livro_id is not None:
        return capitulo.livro_id
    if capitulo_id is None:
        return None
    capitulo = sessao.get(Capitulo, capitulo_id)
    return capitulo.livro_id if capitulo is not None else None


def _livro_do_frame(sessao: Session, frame_id: int | None, frame: Frame | None = None) -> int | None:
    if frame is None and frame_id is not None:
        frame = sessao.get(Frame, frame_id)
    if frame is None:
        return None
    return _livro_do_capitulo(sessao, frame.capitulo_id, frame.capitulo)


def livro_do_objeto(sessao: Session, objeto: object) -> int | None:
    """O id do livro a que um objeto pertence, ou `None` se ele não pertence a nenhum (ou se
    ainda não dá para saber, como uma chave estrangeira por preencher)."""
    if isinstance(objeto, Livro):
        return objeto.id
    if isinstance(objeto, Capitulo | Elemento):
        return objeto.livro_id
    if isinstance(objeto, EstadoElemento | HistoricoIdentidadeElemento | Frame | SugestaoDeElemento | SugestaoDeCena):
        return _livro_do_capitulo(sessao, objeto.capitulo_id, getattr(objeto, "capitulo", None))
    if isinstance(objeto, Prompt):
        return _livro_do_frame(sessao, objeto.frame_id, objeto.frame)
    if isinstance(objeto, Imagem):
        prompt = objeto.prompt if objeto.prompt is not None else sessao.get(Prompt, objeto.prompt_id)
        return livro_do_objeto(sessao, prompt) if prompt is not None else None
    return None


def _so_mudou_o_que_nao_conta(objeto: object) -> bool:
    ignorados = _CAMPOS_QUE_NAO_CONTAM.get(type(objeto))
    if not ignorados:
        return False
    mudados = {atributo.key for atributo in inspect(objeto).attrs if atributo.history.has_changes()}
    return bool(mudados) and mudados <= ignorados


def _livros_atingidos_pelo_perfil_apagado(sessao: Session, perfil_id: int) -> set[int]:
    """Os livros que mostravam o perfil: como padrão do livro ou num prompt de um frame seu."""
    como_padrao = sessao.scalars(select(Livro.id).where(Livro.perfil_renderizacao_padrao_id == perfil_id))
    em_prompts = sessao.scalars(
        select(Capitulo.livro_id)
        .join(Frame, Frame.capitulo_id == Capitulo.id)
        .join(Prompt, Prompt.frame_id == Frame.id)
        .where(Prompt.perfil_renderizacao_id == perfil_id)
    )
    return set(como_padrao) | set(em_prompts)


@event.listens_for(Session, "before_flush")
def subir_revisoes(sessao: Session, contexto, instancias) -> None:  # noqa: ARG001
    """Sobe a revisão de cada livro atingido por esta gravação — uma vez por livro."""
    com_mudanca = [*sessao.new, *sessao.deleted, *(o for o in sessao.dirty if sessao.is_modified(o))]
    if not com_mudanca:
        return

    livros: set[int] = set()
    # Sem isto, consultar aqui dentro dispararia outro flush, dentro deste.
    with sessao.no_autoflush:
        for objeto in com_mudanca:
            if isinstance(objeto, PerfilRenderizacao):
                if objeto in sessao.deleted and objeto.id is not None:
                    livros |= _livros_atingidos_pelo_perfil_apagado(sessao, objeto.id)
                continue
            if objeto in sessao.dirty and _so_mudou_o_que_nao_conta(objeto):
                continue
            livro_id = livro_do_objeto(sessao, objeto)
            if livro_id is not None:
                livros.add(livro_id)

        # Um livro criado ou apagado nesta mesma gravação não tem o que revisar.
        a_ignorar = {o.id for o in (*sessao.new, *sessao.deleted) if isinstance(o, Livro)}
        for livro_id in livros - a_ignorar:
            livro = sessao.get(Livro, livro_id)
            if livro is not None:
                # Expressão SQL, e não "livro.revisao + 1" em Python: o banco soma, então duas
                # gravações ao mesmo tempo não escrevem o mesmo número.
                livro.revisao = Livro.revisao + 1
