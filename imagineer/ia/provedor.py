"""A fronteira com os provedores de IA (item 4.2 da especificação).

Define o contrato ``ProvedorIA`` e os tipos que ele devolve. Toda a aplicação
conversa com esta interface, não com a API de um fornecedor — é o que permite
trocar de fornecedor, ou usar um provedor falso nos testes, sem tocar nas rotas.

Os métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que
adivinhar o formato da resposta nem repetir o trabalho de interpretá-la.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

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


class ConteudoRecusado(ErroDoProvedorIA):
    """O provedor de imagem recusou o **conteúdo** do prompt (moderação, S4).

    Diferente de qualquer outro erro do provedor (rede, 503, chave): quem recebe sabe que
    vale **suavizar o prompt** e tentar de novo. Guarda a mensagem do provedor em ``motivo``.
    """

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


@dataclass
class ImagemDeReferencia:
    """Uma imagem a enviar **como referência visual** junto do prompt (W4): os bytes e o tipo."""

    conteudo: bytes
    tipo_de_midia: str

    def como_data_url(self) -> str:
        """A imagem como ``data:image/jpeg;base64,...``, o formato que os fornecedores aceitam num campo de imagem."""
        import base64

        return f"data:{self.tipo_de_midia};base64,{base64.b64encode(self.conteudo).decode()}"


@dataclass
class ReferenciasParaGerar:
    """As imagens de referência de uma geração e o **parâmetro** do modelo que as recebe (W1, W4)."""

    imagens: list[ImagemDeReferencia]
    parametro: str


@dataclass
class ImagemGerada:
    """Uma imagem que o provedor gerou: os bytes e o tipo, para gravar como qualquer imagem do catálogo."""

    conteudo: bytes
    tipo_de_midia: str
    """Como ``image/webp`` ou ``image/png``; a extensão do arquivo sai daqui."""

    modelo: str = ""


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

    # Item 4.10, LM16: o que decide a escolha de um modelo para **ler** um livro. Todos com padrão seguro, para um provedor que não
    # modela esses detalhes (o falso, nos testes) continuar valendo.
    preco_entrada: float = 0.0
    """Preço por token de entrada (``pricing.prompt``), em US$. É o que pesa na leitura: o capítulo inteiro entra a cada chamada."""

    preco_cache_leitura: float | None = None
    """Preço por token de entrada **lido do cache** (``pricing.input_cache_read``). Nulo = o modelo não informa (ou não tem cache)."""

    raciocinio_obrigatorio: bool = False
    """O modelo sempre raciocina e não dá para desligar: lento e caro para uma rajada de leituras."""

    esforcos: list[str] = field(default_factory=list)
    """Os esforços de raciocínio que o modelo aceita (``minimal`` a ``max``). Vazia = o catálogo não diz."""

    rapido: bool = True
    """Se responde rápido: sem raciocínio, ou com um que se desliga ou fica no mínimo (``catalogo_de_texto.e_rapido``)."""

    saida_maxima: int | None = None
    """O teto de tokens de saída do modelo (``top_provider.max_completion_tokens``). Nulo = o catálogo não diz."""


@dataclass
class ModeloDeVoz:
    """Um modelo de **voz** do provedor, como a tela de configuração o mostra (NA1)."""

    id: str
    nome: str
    vozes: list[str] = field(default_factory=list)
    """As vozes que o modelo aceita (``voice``). Vazia = o modelo não lista vozes (clona de uma amostra, ou tem uma só)."""
    preco_por_caractere: Decimal | None = None
    """Dólares por caractere de texto narrado, **quando o modelo cobra assim**. Nulo = não dá para estimar: o modelo cobra por token
    ou por segundo (Gemini TTS, Seed Audio), ou é gratuito sem preço informado. Nunca um valor inventado."""
    gratuito: bool = False


@dataclass
class AudioNarrado:
    """O áudio de um trecho falado, com o que ele custou (NA6)."""

    conteudo: bytes
    """O MP3."""
    custo: Decimal | None = None
    """O custo **estimado** em dólares: caracteres do trecho × o preço por caractere do catálogo. Nulo = não se sabe (NA3)."""
    id_da_geracao: str | None = None
    """O ``X-Generation-Id`` do OpenRouter, para conferir a cobrança no painel dele."""


@dataclass
class ModeloDeImagemDisponivel:
    """Um modelo de **imagem** oferecido pelo provedor, como o catálogo (MI1) o mostra."""

    id: str
    nome: str
    preco_por_token: float | None = None
    """O preço de um token de imagem, em dólares (``pricing.image_output`` ou ``image_token`` do OpenRouter). **Não é o preço por
    imagem**: quantos tokens uma imagem tem depende da resolução (MI2). Nulo = o provedor não informou."""

    moderado: bool = False
    """``top_provider.is_moderated``: o provedor modera o que o modelo gera (MI3)."""


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
    trecho_ancora: str | None = None
    """Citação literal do começo do momento, copiada do texto; o servidor a converte em
    posição (item 3.4g). Nulo quando a IA não tem certeza."""
    trecho: str | None = None
    """Citação literal de 1 a 3 frases que narra o momento (FD7); o servidor confere que está no capítulo e descarta se não está."""


@dataclass
class UsoDaChamada:
    """O que uma chamada de conversa consumiu, como o provedor informou (item 4.3).

    ``custo`` é em dólares e fica ``None`` quando o provedor não informa (nunca um zero inventado).
    Quem usa o provedor recebe isto por ``ao_usar`` e decide o que fazer — o provedor não conhece o banco.
    """

    operacao: str
    modelo: str
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    custo: Decimal | None = None
    id_da_geracao: str | None = None
    provedor: str = "openrouter"
    """Quem cobrou (CU1): ``openrouter``, ``fal``, ``replicate`` ou ``openai`` (a narração, NA6)."""
    estimado: bool = False
    """O ``custo`` já vem como **estimativa** de quem chamou (a narração: a OpenAI não informa o custo), e não do fornecedor (CU2)."""
    tokens_em_cache: int | None = None
    """Dos ``tokens_entrada``, quantos o provedor leu do **cache de prompt** (4.10, LM7). ``None`` = ele não informou (nunca um zero inventado)."""
    tokens_de_raciocinio: int | None = None
    """Dos ``tokens_saida``, quantos foram de **raciocínio** do modelo (4.10, LM7). ``None`` = ele não informou."""


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
class MomentoSugerido:
    """Um momento do elemento dentro do capítulo (item 4.9, FL3): o que mudou e onde começa.

    Todos os campos de conteúdo são ``None`` quando o texto não os sustenta (nunca inventados). ``ancora`` é a citação **literal** de onde o
    momento começa; é com ela que o servidor calcula a posição (``EstadoElemento.momentos``).
    """

    ancora: str | None = None
    roupa: str | None = None
    estado_fisico: str | None = None
    """Ferimentos, sujeira, cansaço."""
    expressao_e_postura: str | None = None
    humor: str | None = None
    """O humor que **se vê**."""
    lugar: str | None = None


@dataclass
class EstadoSugerido:
    """O resultado da leitura profunda de um elemento (item 4.4, fase 2).

    Ao contrário de ``ElementoSugerido``, esta é a descrição de aparência —
    obtida relendo o capítulo de origem do estado, focado num elemento só. É o
    que sobrescreve ``EstadoElemento.descricao`` antes de montar um prompt.
    """

    descricao: str
    modelo: str = ""
    momentos: list[MomentoSugerido] | None = None
    """A linha do tempo do elemento no capítulo, em ordem do texto (item 4.9, FL3). ``None`` = o modelo devolveu o formato antigo (um instante só)."""


@dataclass
class ImagemConferida:
    """O resultado de conferir uma imagem gerada contra a lista do que deveria aparecer (item 4.9, FL13.1)."""

    divergencias: list[str] = field(default_factory=list)
    """O que a imagem mostra de diferente do que a lista pedia, uma frase por item, em português. Vazia = nada a apontar."""
    modelo: str = ""

    @property
    def conforme(self) -> bool:
        return not self.divergencias


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
    dossie: dict | None = None
    """O dossiê da cena (item 4.9, FL5): ``momento_incerto``, ``presentes`` (cada um com ``nome``, ``tipo``, ``elemento``, ``caracteristicas``, ``incerto``
    e ``incluir``), ``onde``, ``luz_e_clima``, ``acao`` e ``faltou``. ``contexto`` é o texto dele (lugar, luz e ação). ``None`` = o modelo respondeu no
    formato antigo, de um parágrafo só."""


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
    reconheceu_a_obra: bool = True
    """Se a IA identificou o livro com confiança razoável (item 6.5).

    `True` mesmo que algum campo específico (ex.: artista de referência)
    tenha ficado nulo por falta de informação — isso é diferente de não
    reconhecer a obra. Só `False` quando a IA genuinamente não sabe de que
    livro se trata; nesse caso todos os campos de estilo vêm nulos, e o app
    deveria avisar o usuário em vez de mostrar um formulário em branco sem
    explicação."""
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
        elementos_conhecidos: list[str],
        modelo: str,
        orientacao: str | None = None,
    ) -> ExtracaoDeElementos:
        """Identifica os elementos do capítulo — fase 1 do item 4.4 (passo 6).

        Também sugere cenas: combinações de elementos interagindo num momento
        específico do capítulo, para o usuário não ter que pensar em cada
        recorte narrativo sozinho.

        Args:
            texto_capitulo: o texto a ler.
            elementos_conhecidos: cada elemento já cadastrado, em texto, com a
                **identidade** vigente ("Nome (TIPO): quem é"), e nunca a
                aparência de um capítulo. Serve para a IA usar o mesmo nome de
                quem já existe e reconhecer apelidos; mandar a aparência fazia a
                IA copiá-la para a sugestão de outro capítulo.
            modelo: o identificador do modelo a usar.
            orientacao: o que o usuário pediu para procurar além da primeira análise (item 6.7,
                M1). É um **palpite dele**, não um fato: a IA só inclui o que o texto mostra.

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
        aparencia_anterior: str | None = None,
        id_do_capitulo: int | None = None,
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
                **Nulo** quando o que há é só o rascunho de identidade (FD1).
            modelo: o identificador do modelo a usar.
            aparencia_anterior: a "Aparência fixa" do estado anterior já lido
                do mesmo elemento (FD2): os traços que não mudam, para
                completar o que este capítulo não repete.
            id_do_capitulo: o id do capítulo em ``texto_capitulo`` (4.10, LM11). Serve para o provedor
                reaproveitar o **cache** do capítulo entre as leituras de uma mesma rajada; um provedor que não
                conhece cache o ignora, e sem ele a chamada é como era antes.
        """

    @abstractmethod
    def sugerir_identidade(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        identidade_vigente: str | None,
        modelo: str,
        id_do_capitulo: int | None = None,
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
            id_do_capitulo: como em ``sugerir_estado`` (4.10, LM11).
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
        trecho: str | None = None,
        id_do_capitulo: int | None = None,
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
            id_do_capitulo: como em ``sugerir_estado`` (4.10, LM11).
        """

    @abstractmethod
    def montar_prompt_de_video(
        self,
        descricao_do_frame: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
        contexto_do_livro: str | None = None,
        comentario_do_usuario: str | None = None,
        elementos_vinculados: list[str] | None = None,
        trecho_do_livro: str | None = None,
        prompt_da_imagem: str | None = None,
        eh_retrato: bool = False,
    ) -> PromptMontado:
        """Monta o prompt de **vídeo** (~8 s, item 4.8) a partir do mesmo que o de imagem recebe.

        Args:
            prompt_da_imagem: o texto do prompt que gerou a **imagem de partida** (o primeiro quadro). Com ele, o prompt de
                vídeo só descreve movimento, câmera e som; sem ele, descreve tudo (modo texto para vídeo, VD1).
            eh_retrato: o frame é um retrato (``PERSONAGEM``): vira "retrato vivo", sem ação narrativa (VD4).
        Os demais argumentos são os de ``montar_prompt``.
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
        elementos_vinculados: list[str] | None = None,
        trecho_do_livro: str | None = None,
        dossie: dict | None = None,
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
            elementos_vinculados: só num retrato (V5): as linhas "Nome (identidade): aparência" dos elementos que
                aparecem **junto** do sujeito (o objeto que ele carrega, o lugar onde está).
            trecho_do_livro: o trecho literal do capítulo em que a cena acontece (FD7).
            dossie: só numa cena (item 4.9, FL9, FL12): o dossiê **confirmado**. A lista de presentes que ele traz é a lista fechada de quem e do
                que aparece, e o prompt é escrito uma frase por figura. Com ele, o ``contexto_do_livro`` não vai (o dossiê já o substitui).
        """

    @abstractmethod
    def conferir_imagem(
        self,
        imagem: bytes,
        tipo_de_midia: str,
        titulo_da_cena: str,
        dossie: dict,
        modelo: str,
    ) -> ImagemConferida:
        """Compara a ``imagem`` gerada com a lista do que deveria aparecer (item 4.9, FL13.1) e devolve as divergências.

        Args:
            imagem, tipo_de_midia: os bytes e o tipo (``image/png``...). Quem chama os reduz antes (a conferência não precisa da imagem inteira).
            titulo_da_cena: para a IA saber de que cena se trata.
            dossie: ``presentes`` (os que a pessoa deixou na cena), ``onde``, ``luz_e_clima`` e ``acao``.
            modelo: um modelo **com visão**.
        """

    @abstractmethod
    def suavizar_prompt(self, texto: str, modelo: str) -> PromptMontado:
        """Reescreve um prompt que o provedor de imagem recusou (S6, item 6.6).

        Mantém a cena e troca o explícito pelo sugerido: nudez vira cobertura parcial,
        violência fica sem sangue, menores sempre vestidos. Chamada **só** depois de uma
        recusa de conteúdo.

        Args:
            texto: o prompt recusado.
            modelo: o modelo de texto que reescreve (``modelo_suavizacao`` ou ``modelo_prompt``).
        """

    def traduzir_prompt(self, texto: str, para: str, modelo: str) -> PromptMontado:
        """Traduz um prompt entre inglês e português (PT2, PT3). ``para`` é ``"pt"`` ou ``"en"``.

        Não é abstrata: um provedor que não traduz herda esta, que recusa com uma mensagem clara (nenhum quebra por falta dela).
        """
        raise ErroDoProvedorIA("Este provedor não sabe traduzir prompts.")

    def corrigir_prompt(self, texto: str, instrucao: str, modelo: str) -> PromptMontado:
        """Corrige o prompt de imagem como a pessoa pediu (P6): muda só o que ``instrucao`` manda e deixa o resto idêntico.

        Não é abstrata: um provedor que não corrige recusa com uma mensagem clara (nenhum quebra por falta dela)."""
        raise ErroDoProvedorIA("Este provedor não sabe corrigir prompts.")

    def listar_modelos_de_imagem(self) -> list[ModeloDeImagemDisponivel]:
        """Os modelos de **imagem** do OpenRouter, para o catálogo (MI1). Não é abstrata: um provedor que não lista devolve vazio."""
        return []

    def listar_modelos_de_voz(self) -> list[ModeloDeVoz]:
        """Os modelos de **voz** do provedor, para a tela de Narração (NA1). Não é abstrata: um provedor que não lista devolve vazio."""
        return []

    @property
    def pode_narrar(self) -> bool:
        """``True`` se este provedor tem o que a narração exige (a chave). Sem isso, gerar nem começa (NA5, 422). Não é abstrata."""
        return False

    def narrar(self, texto: str, modelo: str, voz: str | None) -> AudioNarrado:
        """Fala ``texto`` com a voz de IA e devolve o MP3 (NA1). Não é abstrata: um provedor que não fala levanta o erro abaixo.

        ``voz`` nula = a padrão do modelo (alguns modelos exigem uma voz). O texto é falado **como está** (NA1: os modelos de voz leem o
        ``input`` palavra por palavra). Levanta ``ChaveDeApiAusente`` se a chave for recusada e ``ErroDoProvedorIA`` para qualquer outra
        falha, sempre com a mensagem em português."""
        raise ErroDoProvedorIA("Este provedor não narra.")

    @abstractmethod
    def gerar_imagem(
        self,
        prompt: str,
        modelo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        """Gera a imagem a partir do prompt (item 6.6, "Gerar a imagem").

        ``referencias`` são imagens enviadas **junto** como referência visual (W1 a W4); no fal.ai não existem.

        ``sem_filtro_de_seguranca`` desliga o filtro opcional do modelo, **só no Replicate** (F12 a F14); em outro
        fornecedor é um erro de programação (``ErroDoProvedorIA``), porque o serviço já o barra antes.

        Raises:
            ConteudoRecusado: o provedor recusou o conteúdo (moderação). A recusa não cobra.
            ErroDoProvedorIA: qualquer outro problema (rede, 503, resposta fora do formato).
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
