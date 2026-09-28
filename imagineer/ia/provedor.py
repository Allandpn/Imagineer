"""A fronteira com os provedores de IA (item 4.2 da especificação).

Define o contrato ``ProvedorIA`` e os tipos que ele devolve. Toda a aplicação
conversa com esta interface, não com a API de um fornecedor — é o que permite
trocar de fornecedor, ou usar um provedor falso nos testes, sem tocar nas rotas.

Os métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que
adivinhar o formato da resposta nem repetir o trabalho de interpretá-la.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from imagineer.modelos import CategoriaEstilo, TipoElemento


class ErroDoProvedorIA(Exception):
    """A chamada ao provedor de IA não deu certo.

    Existe para que as rotas possam responder com uma mensagem que dá para
    mostrar na tela, em vez de deixar escapar um erro de rede ou um JSON
    inesperado. Guarda o motivo em linguagem comum.
    """


class ChaveDeApiAusente(ErroDoProvedorIA):
    """Não há chave de API configurada — nem no ambiente, nem no banco."""


class ModeloNaoEscolhido(ErroDoProvedorIA):
    """Nenhum modelo foi escolhido para esta operação (item 4.3)."""


class TextoLongoDemais(ErroDoProvedorIA):
    """O texto não cabe na janela de contexto do modelo escolhido.

    Levantado **antes** da chamada, não depois: descobrir isso pela recusa da API
    significaria ter gastado a chamada para nada.
    """


@dataclass
class ModeloDisponivel:
    """Um modelo oferecido pelo provedor, como a tela de configuração o mostra."""

    id: str
    nome: str
    contexto: int
    """Janela de contexto em tokens. É o que diz se um capítulo cabe."""

    gratuito: bool

    suporta_json: bool = True
    """Se o modelo aceita resposta estruturada/JSON (``supported_parameters``
    do OpenRouter contendo ``response_format``/``structured_outputs``, item
    4.3). Ataca direto o erro "O modelo não devolveu JSON", mais comum em
    modelos pequenos/gratuitos. Padrão ``True`` para não quebrar um provedor
    (como o falso, nos testes) que não modela esse detalhe."""

    custo_saida: float = 0.0
    """Preço por token de saída (``pricing.completion`` do OpenRouter),
    sempre presente na resposta — não só quando filtrado, porque é
    informação útil mesmo sem filtrar por ela (item 4.3)."""

    moderado: bool = False
    """Se o modelo é moderado pelo provedor (``top_provider.is_moderated``).
    Texto narrativo (violência, fantasia) pode ser rejeitado por modelos
    mais restritivos — item 4.3."""


@dataclass
class ElementoSugerido:
    """Um elemento que a IA acha que aparece no capítulo — só identificação.

    É **sugestão**: nada disso vai para o banco antes do usuário confirmar
    (item 4.4, fase 1). O campo ``elemento_id`` vem preenchido quando a sugestão
    casa com um elemento já cadastrado, e é o que permite à tela oferecer "manter
    o estado atual" em vez de criar um elemento repetido.

    Não traz descrição de aparência: pedir isso de vários elementos na mesma
    resposta misturou atributos entre personagens num teste com IA real (item
    4.2). Essa parte é a leitura profunda (fase 2, ``sugerir_estado``), que
    processa um elemento por vez.
    """

    tipo: TipoElemento
    nome: str
    descricao: str | None = None
    """Identidade do elemento: quem ou o que é, papel na história. Não muda."""

    elemento_id: int | None = None
    """O elemento já cadastrado a que esta sugestão corresponde, se houver."""

    manter_estado_atual: bool = False
    """A IA acha que o estado conhecido continua valendo (item 4.4, fase 1).

    É um julgamento leve — comparação com o contexto de estados conhecidos — e
    não descreve a aparência nova; isso fica para a fase 2."""


@dataclass
class ParticipanteSugerido:
    """Um elemento que participa de uma cena sugerida — referenciado por nome.

    Não por ``elemento_id``: nesta fase o elemento pode ainda não estar
    cadastrado (é só sugestão, ver ``ElementoSugerido``). A rota casa o nome
    contra os elementos já existentes do livro, do mesmo jeito que já faz para
    a lista de elementos (item 6.7).
    """

    tipo: TipoElemento
    nome: str


@dataclass
class CenaSugerida:
    """Uma cena que a IA identificou como digna de virar imagem.

    Ao contrário de ``ElementoSugerido`` (um elemento isolado), isto é uma
    combinação de elementos interagindo num momento específico do capítulo —
    o que faltava quando a extração só listava elementos soltos, sem sugerir
    quais combinações formam uma cena (item 4.4). Não é um ``Frame``: a IA
    sugere a cena, o usuário decide se e quando ela vira um Frame de verdade
    (`tipo=CENA`, item 3.4e) — misturar os dois nomes foi o que causou a
    confusão registrada na Etapa 5.
    """

    titulo: str
    descricao: str | None = None
    horario: str | None = None
    clima: str | None = None
    humor: str | None = None
    participantes: list[ParticipanteSugerido] = field(default_factory=list)


@dataclass
class ExtracaoDeElementos:
    """O resultado de uma extração, com o rastro do que foi usado."""

    elementos: list[ElementoSugerido] = field(default_factory=list)
    cenas: list[CenaSugerida] = field(default_factory=list)
    """Cenas sugeridas, combinando elementos identificados acima."""

    modelo: str = ""
    """O modelo que produziu isto. Guardado para o usuário saber a quem creditar
    um resultado bom ou ruim."""


@dataclass
class EstadoSugerido:
    """O resultado da leitura profunda de um elemento (item 4.4, fase 2).

    Ao contrário de ``ElementoSugerido``, esta é a descrição de aparência —
    obtida relendo o capítulo de origem do estado, focado num elemento só. É o
    que sobrescreve ``EstadoElemento.descricao`` antes de montar um prompt.
    """

    descricao: str
    modelo: str = ""


@dataclass
class IdentidadeSugerida:
    """O resultado da leitura profunda de identidade (item 4.4, fase 2b).

    Ao contrário de ``EstadoSugerido`` (que sobrescreve a descrição do
    estado), isto **não é** a identidade inteira — só o incremento que este
    capítulo especificamente acrescenta, ou ``None`` quando nada de novo.
    Vira uma linha nova em ``HistoricoIdentidadeElemento`` (item 3.4f) em vez
    de sobrescrever ``Elemento.descricao``: identidade é cumulativa, não um
    retrato de um só ponto da narrativa.
    """

    descricao: str | None
    modelo: str = ""


@dataclass
class FrameFundamentado:
    """O contexto que a leitura profunda de um frame do tipo CENA confirmou.

    Ao contrário de ``EstadoSugerido`` (que sobrescreve a descrição do
    elemento), isto **não substitui** o que o usuário escreveu no frame — é
    contexto de apoio. Quem decide o texto final é ``montar_prompt``, e a
    prioridade é do usuário: ele já leu o capítulo; esta leitura é uma segunda
    conferência, não a palavra final (item 4.4).
    """

    contexto: str
    modelo: str = ""


@dataclass
class PromptMontado:
    """O prompt de imagem pronto para o usuário copiar."""

    texto: str
    modelo: str = ""


@dataclass
class PerfilRenderizacaoSugerido:
    """Um perfil de estilo sugerido a partir só dos metadados do livro.

    Rascunho de validação (pendência da Etapa 8, ainda sem especificação
    fechada): ao contrário das outras operações desta interface, esta não lê
    nenhum texto do livro — só título/autor/idioma — porque não há como saber
    de antemão em que capítulo a narrativa realmente começa. Depende de o
    modelo ter (ou buscar na internet) conhecimento sobre a obra citada; sem
    isso, o resultado tende a ser genérico para o gênero informado.
    """

    estilo: str | None = None
    artista_referencia: str | None = None
    iluminacao: str | None = None
    paleta: str | None = None
    formato: str | None = None
    categoria_estilo: CategoriaEstilo | None = None
    """A categoria usada — a informada no pedido, ou a que a IA escolheu
    sozinha quando nenhuma veio. Devolvida para o usuário saber qual foi,
    mesmo sem ter escolhido explicitamente."""
    modelo: str = ""


class ProvedorIA(ABC):
    """O que a aplicação espera de um provedor de IA de texto.

    Quatro operações: identificação e montagem de prompt (passos 6 e 8 do fluxo
    da Etapa 2), e as duas leituras profundas entre elas (item 4.4) — de um
    elemento (``sugerir_estado``) e de um frame do tipo CENA (``fundamentar_frame``).
    """

    @abstractmethod
    def listar_modelos(self) -> list[ModeloDisponivel]:
        """Os modelos que o provedor oferece, para a tela de configuração."""

    @abstractmethod
    def extrair_elementos(
        self,
        texto_capitulo: str,
        estados_conhecidos: list[str],
        modelo: str,
    ) -> ExtracaoDeElementos:
        """Identifica os elementos do capítulo — fase 1 do item 4.4 (passo 6).

        Também sugere cenas: combinações de elementos interagindo num momento
        específico do capítulo, para o usuário não ter que pensar em cada
        recorte narrativo sozinho.

        Args:
            texto_capitulo: o texto a ler.
            estados_conhecidos: o último estado conhecido de cada elemento já
                cadastrado, em texto. É o contexto que permite à IA responder
                "manter estado atual" em vez de inventar um estado novo a cada
                capítulo.
            modelo: o identificador do modelo a usar.

        Não pede descrição de aparência — só identificação. Ver
        ``sugerir_estado`` para a leitura profunda de um elemento específico.
        """

    @abstractmethod
    def sugerir_estado(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        descricao_do_elemento: str | None,
        estado_atual: str | None,
        modelo: str,
    ) -> EstadoSugerido:
        """A leitura profunda de UM elemento num capítulo — fase 2 do item 4.4.

        Relê o capítulo inteiro, mas focado só neste elemento — é essa
        concentração que evita a mistura de atributos entre elementos que a
        fase 1 antiga produzia. Chamado dentro de ``POST /frames/{id}/prompts``,
        antes de montar o prompt (item 6.6).

        Args:
            texto_capitulo: o capítulo onde este estado foi registrado — não
                necessariamente o capítulo da cena que está sendo montada.
            tipo, nome: identificam o elemento no texto.
            descricao_do_elemento: a identidade do elemento (``Elemento.descricao``),
                de contexto.
            estado_atual: a descrição de aparência já registrada, se houver —
                de contexto; o texto do capítulo tem precedência sobre ela.
            modelo: o identificador do modelo a usar.
        """

    @abstractmethod
    def sugerir_identidade(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        identidade_vigente: str | None,
        modelo: str,
    ) -> IdentidadeSugerida:
        """A leitura profunda de *identidade* de UM elemento — fase 2b (item 4.4).

        Roda no mesmo ponto que ``sugerir_estado`` (dentro de
        ``POST /frames/{id}/prompts``), relendo a mesma chamada — sem chamada
        de IA extra. Ao contrário de ``sugerir_estado``, o resultado **não
        sobrescreve** nada: quando há algo genuinamente novo, vira uma linha
        em ``HistoricoIdentidadeElemento`` (item 3.4f); quando não há nada
        novo (o caso comum), a resposta vem com ``descricao=None`` e nenhuma
        linha é criada.

        Args:
            texto_capitulo: o capítulo sendo relido — o mesmo de ``sugerir_estado``.
            tipo, nome: identificam o elemento no texto.
            identidade_vigente: a identidade já conhecida até este ponto da
                narrativa (``Elemento.descricao`` mais os incrementos
                anteriores, em ordem — ver ``servicos/identidade_de_elemento.py``),
                de contexto para a IA não repetir o que já sabe.
            modelo: o identificador do modelo a usar.
        """

    @abstractmethod
    def fundamentar_frame(
        self,
        texto_capitulo: str,
        titulo: str,
        descricao: str | None,
        horario: str | None,
        clima: str | None,
        humor: str | None,
        participantes: list[str],
        modelo: str,
    ) -> FrameFundamentado:
        """A leitura profunda de um frame do tipo CENA — item 4.4.

        Relê o capítulo do frame para confirmar quem, onde e o quê, com base no
        que o usuário já escreveu e em quem participa. **Não sobrescreve** o
        que o usuário escreveu — devolve um contexto de apoio que
        ``montar_prompt`` usa com prioridade menor que a descrição do usuário
        (item 4.4: a palavra de quem já leu o capítulo vale mais que uma nova
        leitura automática, para não deixar uma alucinação ou ambiguidade da
        IA divergir do que o usuário confirmou).

        Args:
            texto_capitulo: o capítulo do frame.
            titulo, descricao, horario, clima, humor: o que o usuário escreveu.
            participantes: "Nome (identidade): descrição do estado" de cada
                elemento ligado ao frame, já com a aparência estabelecida — a
                identidade (entre parênteses) só aparece quando o elemento
                tem uma registrada.
            modelo: o identificador do modelo a usar.
        """

    @abstractmethod
    def montar_prompt(
        self,
        descricao_do_frame: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
        contexto_do_livro: str | None = None,
        comentario_do_usuario: str | None = None,
    ) -> PromptMontado:
        """Monta o prompt de imagem a partir do que foi escolhido (passo 8).

        Args:
            descricao_do_frame: o que o usuário escreveu sobre o frame — vazio
                para um frame do tipo PERSONAGEM (item 4.4: um retrato não
                referencia nada além do próprio elemento).
            elementos: "Nome (identidade): descrição do estado" de cada
                elemento do frame — mesmo formato de ``fundamentar_frame.participantes``.
            contexto_do_livro: a leitura profunda do frame (``fundamentar_frame``),
                só para frames do tipo CENA — contexto de apoio, prioridade
                menor que ``descricao_do_frame``.
            comentario_do_usuario: uma correção pontual do usuário, com
                prioridade sobre tudo o mais (item 4.4).
        """

    @abstractmethod
    def sugerir_perfil_renderizacao(
        self,
        titulo: str,
        autor: str | None,
        idioma: str | None,
        categoria_estilo: CategoriaEstilo | None,
        modelo: str,
    ) -> PerfilRenderizacaoSugerido:
        """Sugere um estilo visual para o livro, a partir só dos metadados.

        Rascunho de validação (pendência da Etapa 8) — não lê o texto do
        livro, só título/autor/idioma. A ideia é o modelo reconhecer a obra
        (de conhecimento próprio ou buscando na internet) e sugerir um estilo
        coerente com gênero/tom/época, antes de o usuário criar o perfil à
        mão sem ainda ter lido o livro.

        Args:
            titulo: obrigatório — sem título não há o que identificar.
            autor: de contexto; ausente, a identificação fica mais fraca
                (muitos livros têm título comum a mais de uma obra).
            idioma: de contexto, ajuda a desambiguar edições/traduções.
            categoria_estilo: quando o usuário escolhe uma (ex.: pintura a
                óleo, cartoon), a IA detalha os atributos **dentro** dela, em
                vez de escolher livremente. Sem isso, a IA escolhe uma
                categoria sozinha — mas ainda restrita ao mesmo vocabulário
                fechado, nunca uma mistura livre. Achado com IA real: sem essa
                restrição, uma sugestão livre misturou movimentos artísticos
                incompatíveis ("oil on canvas" com "expressionist shadows")
                e saiu confusa quando virou prompt de imagem.
            modelo: o identificador do modelo a usar.
        """
