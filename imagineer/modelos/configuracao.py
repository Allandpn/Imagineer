"""Modelo da Configuracao — a integração com IA (item 3.4d)."""

import enum

from sqlalchemy import JSON, CheckConstraint, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base

ID_UNICO = 1
"""O único id que a tabela de configuração aceita."""

MODELO_DE_IMAGEM_PADRAO = "meta/muse-image"
"""O modelo que gera a imagem enquanto o usuário não escolher outro (decisão do Allan, 01/10/2026)."""

MODELOS_DE_IMAGEM_PADRAO = [MODELO_DE_IMAGEM_PADRAO, "bytedance-seed/seedream-5-0-flash", "google/gemini-2.5-flash-image"]
"""Os modelos que o usuário pode escolher, até ele mudar a lista (Z2): o padrão e os dois que aceitaram, em 02/10/2026,
um prompt que o padrão recusou."""


class PrioridadeIA(enum.Enum):
    """Custo vs. qualidade nas decisões que usam IA (item 4.3).

    Hoje controla só a releitura da fase 2 do item 4.4, mas o campo é pensado
    para valer também em futuras decisões parecidas no sistema — por isso mora
    na configuração geral, e não como um parâmetro isolado daquela rota.
    """

    ECONOMIA = "ECONOMIA"
    """Reaproveita o resultado já obtido; só gasta uma chamada de IA nova
    quando ainda não há um resultado salvo."""

    QUALIDADE = "QUALIDADE"
    """Sempre gasta uma chamada de IA nova, mesmo que já exista um resultado
    salvo — prioriza a leitura mais recente do texto sobre o custo."""


class CategoriaEstilo(enum.Enum):
    """Uma família de estilo visual coerente, para guiar a sugestão de perfil.

    Não é uma coluna do banco — é um vocabulário compartilhado entre o pedido
    de `POST /livros/{id}/perfis-renderizacao/sugestao` (item 6.5) e a
    instrução que a IA recebe. Existe porque, sem restringir a um vocabulário
    fechado, a IA já misturou movimentos artísticos incompatíveis na mesma
    sugestão ("oil on canvas... expressionist shadows") e usou linguagem
    temática em vez de visual ("atmosfera de conspiração e revelação") —
    achado testando com um livro real, prompt gerado a partir do perfil saiu
    visualmente confuso. Cada categoria aqui é internamente coerente; a IA
    detalha os atributos (`iluminacao`, `paleta`, `artista_referencia`...)
    dentro da categoria escolhida (pelo usuário, ou por ela mesma sem
    indicação), em vez de inventar uma combinação livre.
    """

    FOTORREALISTA_CINEMATOGRAFICO = "FOTORREALISTA_CINEMATOGRAFICO"
    """Still de cinema: lente, profundidade de campo, grão de filme."""

    PINTURA_A_OLEO = "PINTURA_A_OLEO"
    """Pincelada visível, textura de tela, tradição da pintura clássica."""

    AQUARELA = "AQUARELA"
    """Traços soltos, transparência, bordas que sangram."""

    ARTE_DIGITAL_CONCEITUAL = "ARTE_DIGITAL_CONCEITUAL"
    """"Concept art" de jogos/cinema: pintura digital, luz dramática, sem
    textura de tela nem grão de filme."""

    QUADRINHOS = "QUADRINHOS"
    """Contorno de tinta, cores chapadas ou tramadas, estética de graphic novel."""

    CARTOON_ANIMACAO = "CARTOON_ANIMACAO"
    """Formas simplificadas, cores vivas, estética de animação — não
    fotorrealista nem pintura tradicional."""


class Configuracao(Base):
    """A configuração da integração com IA, numa linha só.

    Não é a modelagem mais elegante, mas é a mais honesta para o que é: não
    existem "duas configurações" num sistema pessoal de um usuário. A alternativa
    — uma tabela de pares chave/valor — perderia a tipagem de cada campo e
    ganharia só flexibilidade que não vai ser usada.
    """

    __tablename__ = "configuracao"
    __table_args__ = (
        # Impede uma segunda linha aparecer por acidente. Sem isto, dois registros
        # de configuração conviveriam e o sistema leria um deles sem avisar.
        CheckConstraint("id = 1", name="linha_unica"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=ID_UNICO)

    # Não há coluna para a chave de API, de propósito (item 4.3): a chave do
    # servidor vem só da variável de ambiente, e a de cada usuário chega por
    # header a cada chamada, sem nunca ser guardada.

    modelo_extracao: Mapped[str | None] = mapped_column(String(200))
    """Modelo usado para sugerir elementos e estados (passo 6 do fluxo)."""

    modelo_prompt: Mapped[str | None] = mapped_column(String(200))
    """Modelo usado para montar o prompt de imagem (passo 8 do fluxo)."""

    modelo_perfil: Mapped[str | None] = mapped_column(String(200))
    """Modelo usado para sugerir um perfil de renderização (item 6.5).

    Campo próprio, separado de ``modelo_extracao``, porque o caso de uso é bem
    diferente: essa chamada acontece **uma vez por livro** (não uma vez por
    capítulo), então vale a pena pagar por um modelo mais caro e melhor —
    testado na prática: ``claude-haiku-4.5`` custou cerca de 55% a mais que
    ``gpt-4o-mini`` na mesma chamada, mas devolveu uma sugestão bem mais rica.
    Amarrar isso a ``modelo_extracao`` obrigaria a mesma escolha de custo para
    as duas coisas, mesmo elas tendo frequências de uso completamente diferentes.
    """

    modelo_imagem: Mapped[str] = mapped_column(
        String(200),
        default=MODELO_DE_IMAGEM_PADRAO,
        server_default=MODELO_DE_IMAGEM_PADRAO,
    )
    """Modelo que **gera a imagem** a partir do prompt (incremento 12).

    Diferente dos outros três, não aceita nulo: sem ele a geração não tem o que
    chamar. Nasce ``meta/muse-image``. É um modelo de **imagem** do OpenRouter,
    chamado por ``POST /api/v1/images``, e não um modelo de texto.
    """

    modelos_de_imagem: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: list(MODELOS_DE_IMAGEM_PADRAO),
        server_default='["meta/muse-image", "bytedance-seed/seedream-5-0-flash", "google/gemini-2.5-flash-image"]',
    )
    """Os modelos de imagem que o usuário pode escolher no app (Z2), mantidos à mão por ``PUT /configuracao``.

    O ``modelo_imagem`` é o padrão e aparece na escolha mesmo que não esteja nesta lista."""

    modelo_suavizacao: Mapped[str | None] = mapped_column(String(200))
    """Modelo de **texto** que reescreve um prompt recusado pelo provedor (S6).

    Opcional: vazio significa "usa ``modelo_prompt``". Campo próprio porque é uma
    chamada curta e barata, que pode usar um modelo menor que o de montar o prompt.
    """

    prioridade_ia: Mapped[PrioridadeIA] = mapped_column(
        Enum(
            PrioridadeIA,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="prioridade_ia",
            values_callable=lambda tipo: [membro.value for membro in tipo],
        ),
        default=PrioridadeIA.ECONOMIA,
        server_default=PrioridadeIA.ECONOMIA.value,
    )
    """Custo vs. qualidade nas chamadas de IA que podem ser reaproveitadas
    (item 4.4). ``ECONOMIA`` por padrão — não gasta chamada de IA à toa."""

    def __repr__(self) -> str:
        return (
            f"<Configuracao extracao={self.modelo_extracao!r} "
            f"prompt={self.modelo_prompt!r} perfil={self.modelo_perfil!r} "
            f"imagem={self.modelo_imagem!r} suavizacao={self.modelo_suavizacao!r}>"
        )
