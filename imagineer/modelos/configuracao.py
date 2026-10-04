"""Modelo da Configuracao — a integração com IA (item 3.4d)."""

import enum

from sqlalchemy import JSON, CheckConstraint, Enum, String, Text
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


class MotorDeNarracao(enum.Enum):
    """Quem fala quando a pessoa toca em "Ouvir" (RL21)."""

    APARELHO = "APARELHO"
    """A voz do Android, como sempre foi: grátis, sem internet. É o padrão."""

    IA = "IA"
    """Voz de IA gerada pelo servidor (paga e só com servidor). **Ainda não implementado**: só o campo existe."""


class ModoDeNarracao(enum.Enum):
    """Quantas vozes a narração usa (RL25)."""

    UMA_VOZ = "UMA_VOZ"
    """Um narrador lê tudo. É o padrão."""

    POR_PERSONAGEM = "POR_PERSONAGEM"
    """Uma voz por personagem (uma IA identifica quem fala). **Ainda não implementado**: só o campo existe."""


class CategoriaEstilo(enum.Enum):
    """Uma família de estilo visual coerente, para guiar a sugestão de perfil.

    É um vocabulário compartilhado entre o pedido de `POST /livros/{id}/perfis-renderizacao/sugestao`
    (item 6.5) e a instrução que a IA recebe e, desde 04/10/2026, **também fica guardada no perfil**
    (`PerfilRenderizacao.categoria_estilo`): é ela que escolhe o bloco técnico fixo colado ao prompt
    (`imagineer/ia/blocos_tecnicos.py`). Existe porque, sem restringir a um vocabulário
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

    ANIME = "ANIME"
    """Contorno de tinta fino, cel-shading, olhos e traços estilizados."""

    PIXEL_ART = "PIXEL_ART"
    """Grade de pixel visível, paleta limitada, dithering, sem suavização."""

    GRAVURA_CLASSICA = "GRAVURA_CLASSICA"
    """Hachura cruzada à tinta, monocromático, frontispício de livro do século XIX."""

    ANIMACAO_3D = "ANIMACAO_3D"
    """Longa-metragem de animação 3D: formas esculpidas, olhos grandes, luz global."""


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

    modelos_com_referencia: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    """Os modelos de imagem que aceitam **imagens de referência**, e o **parâmetro** que recebe a lista (W1).

    Dicionário ``{id do modelo (com prefixo): nome do parâmetro}``, por exemplo ``{"replicate:bytedance/seedream-4.5":
    "image_input"}``. Mantido à mão por ``PUT /configuracao``; nasce **vazio**: nenhum modelo aceita referência até o
    usuário incluí-lo. Só parâmetros que recebem uma **lista** de imagens."""

    precos_informados: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    """O preço **por imagem**, em dólares, que a pessoa informou para um modelo de imagem (PD5); a chave é o id como o ``usos_ia`` o grava
    (OpenRouter sem prefixo; ``fal:`` e ``replicate:`` com). Vale mais que o preço do fornecedor (PD1)."""

    modelos_sem_filtro: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    """Os modelos de imagem em que o usuário **pode** pedir para desligar o filtro de segurança (F13).

    Mantida à mão por ``PUT /configuracao``, com o prefixo do fornecedor (``replicate:...``); nasce **vazia**: nenhum
    modelo permite desligar o filtro até o usuário incluí-lo. Só o parâmetro do próprio modelo é usado, e só depois
    de uma recusa, por pedido explícito (F12)."""

    modelo_suavizacao: Mapped[str | None] = mapped_column(String(200))
    """Modelo de **texto** que reescreve um prompt recusado pelo provedor (S6).

    Opcional: vazio significa "usa ``modelo_prompt``". Campo próprio porque é uma
    chamada curta e barata, que pode usar um modelo menor que o de montar o prompt.
    """

    modelo_traducao: Mapped[str | None] = mapped_column(String(200))
    """Modelo de **texto** que traduz os prompts entre português e inglês (PT2, PT3, MT1).

    Opcional: vazio significa "como antes" — ``modelo_suavizacao``, senão ``modelo_extracao``, senão ``modelo_prompt``.
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

    ordem_dos_dicionarios: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    """Os identificadores dos dicionários, do preferido ao último (RL29). Um dicionário que não está aqui vai para o fim."""

    dicionarios_desativados: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    """Os dicionários que a pessoa não quer ver (RL29): nunca são consultados, nem em "todos"."""

    narracao_motor: Mapped[MotorDeNarracao] = mapped_column(
        Enum(MotorDeNarracao, native_enum=False, length=20, create_constraint=False, values_callable=lambda tipo: [m.value for m in tipo]),
        default=MotorDeNarracao.APARELHO,
        server_default=MotorDeNarracao.APARELHO.value,
    )
    """Quem narra (RL21). Hoje só ``APARELHO`` toca; ``IA`` fica guardado para quando existir (RL26)."""

    narracao_modo: Mapped[ModoDeNarracao] = mapped_column(
        Enum(ModoDeNarracao, native_enum=False, length=20, create_constraint=False, values_callable=lambda tipo: [m.value for m in tipo]),
        default=ModoDeNarracao.UMA_VOZ,
        server_default=ModoDeNarracao.UMA_VOZ.value,
    )
    """Uma voz ou uma por personagem (RL25)."""

    narracao_voz: Mapped[str | None] = mapped_column(String(100))
    """A voz do motor de IA (RL24); nula = a padrão do fornecedor."""

    narracao_instrucoes: Mapped[str | None] = mapped_column(Text)
    """As instruções de tom da narração (RL23), em texto livre; nulas = sem instrução."""

    def __repr__(self) -> str:
        return (
            f"<Configuracao extracao={self.modelo_extracao!r} "
            f"prompt={self.modelo_prompt!r} perfil={self.modelo_perfil!r} "
            f"imagem={self.modelo_imagem!r} suavizacao={self.modelo_suavizacao!r}>"
        )
