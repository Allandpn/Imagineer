"""Que aparência o elemento já tem, para a leitura profunda e para o prompt (FD1, FD2 — item 4.5 da especificação).

A leitura profunda (fase 2) devolve a descrição de um estado em até três linhas rotuladas ("Aparência fixa:", "Neste instante:",
"Onde está:"). Daqui saem duas perguntas que a releitura de um capítulo precisa saber responder:

- **Este estado é só o rascunho de identidade?** Ao confirmar uma sugestão, o estado nasce com a *identidade* da sugestão
  ("filho de Eddard...") no lugar da aparência. Entregue à IA como "estado já registrado", esse texto voltava como aparência
  quando o capítulo não descrevia a pessoa (FD1).
- **O que o elemento já tinha de fixo num capítulo anterior?** Cor do cabelo dita no capítulo 1 continua valendo no 5 (FD2).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.ia.openrouter import ROTULO_DA_APARENCIA_FIXA, ROTULO_DO_AMBIENTE, ROTULO_DO_INSTANTE
from imagineer.modelos import Capitulo, EstadoElemento, SugestaoDeElemento

_ROTULOS = (ROTULO_DA_APARENCIA_FIXA, ROTULO_DO_INSTANTE, ROTULO_DO_AMBIENTE)


def _normalizado(texto: str | None) -> str:
    """O texto sem diferença de espaços ou quebras de linha, para comparar dois textos que são o mesmo."""
    return " ".join((texto or "").split())


def aparencia_fixa_de(descricao: str | None) -> str | None:
    """Só a parte "Aparência fixa:" de uma descrição de estado, sem o rótulo; ``None`` se a descrição não tem essa parte.

    Estados do formato antigo (um campo só, sem rótulos) não têm como separar o que é fixo do que é do instante: devolvem ``None``
    em vez de arriscar mandar roupa e pose como se fossem traços permanentes.
    """
    if not descricao:
        return None
    coletando = False
    partes: list[str] = []
    for linha in descricao.splitlines():
        if linha.startswith(ROTULO_DA_APARENCIA_FIXA):
            coletando = True
            partes.append(linha.removeprefix(ROTULO_DA_APARENCIA_FIXA).strip())
        elif coletando and any(linha.startswith(rotulo) for rotulo in _ROTULOS):
            break
        elif coletando:
            partes.append(linha.strip())
    texto = _normalizado(" ".join(partes))
    return texto or None


def aparencia_fixa_anterior(sessao: Session, estado: EstadoElemento) -> str | None:
    """A "Aparência fixa" do estado **mais recente de um capítulo anterior** do mesmo elemento que já passou pela leitura profunda.

    Só vale estado já lido (``confirmado_pela_leitura_profunda``): um rascunho de identidade não é aparência. Capítulo **posterior**
    ou o próprio capítulo do estado não entram: o que o livro ainda não mostrou não pode orientar a leitura.
    """
    capitulo = sessao.get(Capitulo, estado.capitulo_id)
    anteriores = sessao.scalars(
        select(EstadoElemento)
        .join(Capitulo, Capitulo.id == EstadoElemento.capitulo_id)
        .where(
            EstadoElemento.elemento_id == estado.elemento_id,
            EstadoElemento.confirmado_pela_leitura_profunda.is_(True),
            Capitulo.ordem < capitulo.ordem,
        )
        .order_by(Capitulo.ordem.desc(), EstadoElemento.id.desc())
    )
    for anterior in anteriores:
        fixa = aparencia_fixa_de(anterior.descricao)
        if fixa:
            return fixa
    return None


def e_rascunho_de_identidade(sessao: Session, estado: EstadoElemento) -> bool:
    """Se o texto do estado ainda é a **identidade** copiada na criação, e não uma aparência.

    Verdadeiro quando o estado **não** passou pela leitura profunda **e** o texto é igual (sem diferença de espaços) à identidade do
    elemento ou à de uma sugestão dele. Um estado **digitado à mão** não bate com nenhuma identidade e continua valendo.
    """
    if estado.confirmado_pela_leitura_profunda:
        return False
    texto = _normalizado(estado.descricao)
    if not texto:
        return False
    if texto == _normalizado(estado.elemento.descricao):
        return True
    identidades = sessao.scalars(
        select(SugestaoDeElemento.descricao).where(
            SugestaoDeElemento.elemento_id == estado.elemento_id, SugestaoDeElemento.descricao.is_not(None)
        )
    )
    return any(texto == _normalizado(identidade) for identidade in identidades)


def sem_o_lugar(descricao: str | None) -> str | None:
    """A descrição de estado **sem** a parte "Onde está:" (e sem as linhas que a continuam); o resto fica idêntico.

    O retrato é a âncora de identidade e vai de **fundo liso** (item 4.9, FL1): o lugar do elemento pertence à *cena*, não ao retrato. Estados
    do formato antigo (sem rótulos) não têm parte de lugar: voltam como vieram.
    """
    if not descricao:
        return descricao
    mantidas: list[str] = []
    pulando = False
    for linha in descricao.splitlines():
        if linha.startswith(ROTULO_DO_AMBIENTE):
            pulando = True
            continue
        if pulando and not any(linha.startswith(rotulo) for rotulo in _ROTULOS):
            continue  # continuação do lugar, em outra linha
        pulando = False
        mantidas.append(linha)
    return "\n".join(mantidas)
