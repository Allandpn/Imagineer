"""Implementação de ``ProvedorIA`` sobre o OpenRouter (item 4.1).

O OpenRouter é um gateway único para muitos modelos, inclusive gratuitos, com uma
API compatível com a da OpenAI. Foi escolhido para não precisar de um adaptador
por fornecedor na v1 (Etapa 5).
"""

import json
import re

import httpx

from imagineer.ia.provedor import (
    CenaSugerida,
    ChaveDeApiAusente,
    ElementoSugerido,
    ErroDoProvedorIA,
    EstadoSugerido,
    ExtracaoDeElementos,
    FrameFundamentado,
    ModeloDisponivel,
    ModeloNaoEscolhido,
    ParticipanteSugerido,
    PromptMontado,
    ProvedorIA,
    TextoLongoDemais,
)
from imagineer.modelos import TipoElemento

ENDERECO_BASE = "https://openrouter.ai/api/v1"

CARACTERES_POR_TOKEN = 4
"""Estimativa grosseira de quantos caracteres cabem num token, em português.

Serve para dimensionar antes de chamar, não para cobrar. Errar por 20% aqui não
muda a decisão de "cabe" ou "não cabe", porque a folga é bem maior que isso.
"""

FOLGA_DE_TOKENS = 2000
"""Tokens reservados para a instrução e para a resposta do modelo.

O texto do capítulo não é a única coisa que ocupa contexto: a instrução, os
estados conhecidos e a resposta também. Reservar essa folga é o que evita passar
do limite por pouco.
"""

TEMPO_LIMITE = 180.0
"""Segundos de espera por uma resposta.

Generoso de propósito: modelos gratuitos ficam em fila, e um capítulo de 25 mil
tokens leva tempo. Um limite curto transformaria lentidão em erro.
"""

_INSTRUCAO_DE_EXTRACAO = """\
Você analisa um capítulo de livro e identifica os elementos visuais que aparecem \
nele, para que alguém possa depois gerar imagens das cenas. Nesta etapa você só \
IDENTIFICA — não descreva a aparência de ninguém ainda. Além dos elementos, você \
também sugere CENAS: recortes narrativos específicos, combinando elementos que \
interagem num mesmo momento — é isso que alguém efetivamente ilustraria, não uma \
lista solta de "quem existe no capítulo".

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "elementos": [
    {
      "tipo": "PERSONAGEM",
      "nome": "como o elemento é chamado no texto",
      "descricao": "quem ou o que é: papel na história, natureza, função",
      "manter_estado_atual": false
    }
  ],
  "cenas": [
    {
      "titulo": "título curto do momento, como 'A chegada de Hospius'",
      "descricao": "o que acontece nesse momento específico, em 1-2 frases",
      "horario": "período do dia, se o texto sugerir, senão nulo",
      "clima": "condição do ambiente, se o texto sugerir, senão nulo",
      "humor": "tom emocional da cena, se ficar claro, senão nulo",
      "participantes": [
        {"tipo": "PERSONAGEM", "nome": "nome exatamente como em elementos"}
      ]
    }
  ]
}

## Os tipos de elemento, e como não confundi-los

- **PERSONAGEM**: um ser humano ou humanoide com identidade própria (nome, \
papel na história) — inclui pessoas comuns, nobres, funcionários, qualquer \
gente do enredo.
- **CRIATURA**: um ser vivo não-humanoide com presença própria na cena (animal, \
monstro, criatura fantástica). Para os fins de sugerir cenas, PERSONAGEM e \
CRIATURA contam igualmente como "alguém" que pode protagonizar um momento.
- **AMBIENTE**: um espaço ou lugar amplo (uma floresta, uma rua, um cômodo) — \
o "onde" da cena, não um item dentro dele.
- **EDIFICACAO**: uma construção específica e nomeável, quando o foco é a \
estrutura em si (um castelo, uma torre, uma prisão inteira) — diferente de \
AMBIENTE, que é o espaço genérico onde a ação acontece.
- **OBJETO**: um item físico específico, portátil ou fixo — arma, livro, \
móvel, tabuleiro de jogo, porta, moeda, dispositivo. Portas, tabuleiros e \
lanternas são OBJETO, nunca AMBIENTE nem VEICULO.
- **VEICULO**: algo cuja função é **transportar** pessoas ou carga de um lugar \
a outro (carruagem, navio, montaria usada para viajar). Nunca uma porta, um \
móvel ou qualquer objeto fixo no lugar — isso é OBJETO.
- **GRUPO**: um coletivo mencionado sem que seus integrantes sejam \
individualizados ("os guardas", "a multidão").

## Regras

- Inclua apenas o que tem presença visual no capítulo. Ignore conceitos abstratos.
- "descricao" é a identidade do elemento (quem ou o que é), não a aparência dele \
neste capítulo — a aparência é analisada depois, um elemento por vez.
- Se um elemento da lista de estados conhecidos aparece no capítulo sem indício \
de mudança visível, marque "manter_estado_atual": true. Se parece ter mudado, \
marque false. Elementos novos (fora da lista) sempre são false.
- Use exatamente o nome que já está na lista de estados conhecidos, quando o \
elemento já for conhecido.
- **Objetos: seja seletivo.** Só inclua um objeto se ele tem peso visual \
memorável na cena — algo que o leitor lembraria de ver, um símbolo, algo \
central para uma ação marcante (a moeda entregue como pagamento, o tabuleiro \
em que a partida acontece). NÃO inclua cenário genérico de fundo (papelada, \
móveis comuns, ferramentas do dia a dia) a menos que a cena realmente gire em \
torno do objeto.
- **Cenas: pense em composição, não em lista.** Cada cena deve ter pelo menos \
um PERSONAGEM ou CRIATURA envolvido interagindo com outro elemento (outro \
personagem, um objeto, ou estar situado num ambiente/edificação) — não sugira \
uma "cena" que é só um ambiente vazio ou um objeto sozinho. Prefira poucas \
cenas bem compostas (os momentos que um leitor lembraria) a listar cada \
parágrafo do capítulo como uma cena.
- Todo nome em "participantes" deve corresponder exatamente a um nome que \
também está em "elementos".
- Escreva em português.
"""

_INSTRUCAO_DE_ESTADO = """\
Você lê um capítulo de livro inteiro, mas quer descrever a aparência de UM SÓ \
elemento — ignore todos os outros, mesmo que apareçam no texto.

O texto que você escrever vira, mais tarde, a matéria-prima de um prompt de \
imagem. Modelos de imagem não entendem metáfora literária ("olhar frio como o \
gelo", "silêncio ensurdecedor") — eles precisam de dado físico e sensorial \
concreto. Por isso, ao traduzir o que o texto sugere, prefira sempre o que se vê:

- Materialidade e textura: do que é feita a roupa, o objeto, a superfície \
(linho puído, couro rachado, seda ao luar) — não só "roupas simples" ou \
"roupas ricas".
- Estado físico e expressão como algo visível: idade aparente, porte, \
ferimentos, e a expressão como músculo e postura (sobrancelhas franzidas, \
ombros caídos), não como sentimento abstrato ("ele estava triste" vira "olhar \
baixo, ombros curvados").
- Um instante congelado, não uma ação contínua: descreva UMA pose ou gesto \
específico do capítulo, como se fosse um fotograma parado — não "ele entra, \
pega o livro e sai", mas o momento em que a mão toca a página.
- Luz e atmosfera **só quando o texto do capítulo realmente sustenta isso** \
para este elemento (uma vela, o sol poente, poeira no ar) — não invente uma \
fonte de luz que o texto não menciona; isso é papel da cena, não do elemento.

Regras de fidelidade ao texto (mais importantes que o estilo de escrita acima):
- Descreva só o que o texto diz ou implica com segurança. Não invente detalhes \
que o texto não sustenta, mesmo que pareçam plausíveis para o gênero da obra.
- Não confunda com outro elemento — releia com cuidado a quem cada detalhe \
pertence antes de escrever. Um detalhe de outro personagem nunca deve aparecer \
na descrição deste.
- Separe o que é identidade (rosto, cor e tipo de cabelo, altura, compleição — \
tende a não mudar de capítulo para capítulo) do que é situacional (roupas, \
ferimentos, sujeira, humor — muda com a cena). Preserve a identidade já \
registrada a menos que o texto diga explicitamente que ela mudou (idade que \
avança, um ferimento permanente); atualize a parte situacional com o que este \
capítulo mostra.
- Se o elemento pedido não aparecer de forma clara neste capítulo, ou se o \
texto não descrever sua aparência, devolva a descrição de estado já \
registrada, sem inventar nada novo e sem deduzir a partir do gênero ou tom do \
livro.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "descricao": "a aparência do elemento neste capítulo, seguindo as regras acima"
}

Escreva em português.
"""

_INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME = """\
Você lê um capítulo de livro para conferir uma cena que o usuário já descreveu \
com as próprias palavras — você é uma segunda opinião, não a palavra final.

Você recebe como o usuário descreveu a cena (título, descrição, horário, clima, \
humor) e quem participa dela, cada um já com a aparência estabelecida. Releia o \
capítulo e escreva um parágrafo curto (até 3 frases) confirmando, com base só \
no texto:
- Onde a cena acontece: o ambiente ou construção, com detalhes físicos que o \
texto sustente.
- O que fisicamente acontece nesse momento específico: uma ação ou gesto \
concreto, não uma sequência de eventos.
- Qualquer detalhe visual do ambiente (iluminação, clima, objetos presentes) \
que o texto mostre e a descrição do usuário não tenha coberto.

Regras:
- Você NÃO substitui a descrição do usuário. Se o que você lê parecer \
contradizer o que ele escreveu, não corrija — apenas registre o que o texto \
mostra; quem monta o prompt final decide, e a palavra do usuário vale mais que \
a sua (ele já leu o capítulo; você pode estar enganado ou lendo o trecho errado).
- Não invente. Se o capítulo não deixar algo claro, diga que não é claro em vez \
de supor.
- Não repita a aparência física dos participantes — isso já foi estabelecido \
em outra etapa. Foque em local, ação e ambiente.
- Escreva em português.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "contexto": "o parágrafo de confirmação, seguindo as regras acima"
}
"""

_INSTRUCAO_DE_PROMPT = """\
Você monta prompts para ferramentas de geração de imagem (Midjourney, DALL-E, \
Imagen e afins), a partir de um frame de livro já traduzido para descrições \
concretas de aparência. Um frame pode ser um RETRATO (um elemento só, sem \
nenhum outro) ou uma CENA (vários elementos interagindo) — a diferença fica \
clara pelo que foi preenchido abaixo. Produza UM prompt em inglês, numa linha \
só, pronto para colar na ferramenta.

Se não vier nenhuma descrição de cena (só um elemento na lista), monte um \
RETRATO: use exclusivamente a aparência desse elemento e o estilo pedido — não \
mencione, sugira ou implique a presença de mais ninguém.

Monte o prompt seguindo esta ordem de blocos, separados por vírgula (pule um \
bloco se não houver informação para ele — nunca invente para preencher):

1. Enquadramento e câmera: um tipo de plano (medium shot, close-up, wide shot, \
low-angle, over-the-shoulder) coerente com a cena ou o retrato.
2. Sujeito principal, num instante congelado: quem/o que é o foco, numa pose \
ou gesto específico e parado — nunca uma ação contínua ("ele caminha e olha \
para trás" vira "mid-stride, glancing back").
3. Vestuário, texturas e expressão física de cada elemento presente.
4. Cenário imediato e objetos ao redor (só se houver cena — num retrato, pule).
5. Ambiente de fundo, arquitetura e época (só se houver cena).
6. Iluminação e atmosfera: fonte de luz (candlelight, golden hour, cool \
moonlight, harsh neon) e o que há no ar (dust motes, mist, smoke) — derive isso \
do horário/clima informados e do estilo pedido, não invente uma fonte que \
contradiga o que foi dito.
7. Estética final: estilo, granulado de filme, qualidade — vindo do perfil de \
renderização indicado.

Regras:
- PROIBIDO usar adjetivos subjetivos de qualidade ou literários ("lindo", \
"incrível", "poderoso", "misterioso", "super detalhado", "épico"). Troque por \
material, textura, luz e enquadramento.
- PROIBIDO descrever emoção como palavra abstrata — traduza em expressão física \
e postura visíveis.
- Mantenha fielmente a aparência de cada elemento como foi descrita; não invente \
elementos que não estão na lista.
- Incorpore o estilo, a iluminação e a paleta do perfil indicado.

Ordem de prioridade quando houver conflito entre as fontes abaixo:
1. Comentário do usuário (se houver) — é uma correção de quem já viu o \
resultado anterior ou releu o capítulo com atenção. Vale mais que tudo.
2. A descrição da cena escrita pelo usuário — ele já leu o capítulo; é a conta \
oficial do que acontece.
3. O contexto do livro (se houver) — uma releitura automática, só para \
preencher o que a descrição do usuário não cobriu. Nunca use isso para \
contradizer o que o usuário escreveu.

Responda APENAS com o texto do prompt, sem aspas, sem explicação, sem título, \
sem numerar os blocos.
"""


class ProvedorOpenRouter(ProvedorIA):
    """Conversa com o OpenRouter.

    O cliente HTTP é recebido de fora para os testes poderem injetar um
    transporte falso, em vez de a classe criar a conexão por conta própria.
    """

    def __init__(self, chave_api: str | None = None, cliente: httpx.Client | None = None):
        self._chave_api = chave_api
        self._cliente = cliente or httpx.Client(base_url=ENDERECO_BASE, timeout=TEMPO_LIMITE)

    # ----------------------------------------------------------------------- #
    # Modelos
    # ----------------------------------------------------------------------- #

    def listar_modelos(self) -> list[ModeloDisponivel]:
        """Os modelos de texto do OpenRouter.

        Este endpoint é **público**: não precisa de chave. É o que permite a tela
        de configuração mostrar a lista antes de a chave estar cadastrada — o que
        é justamente a ordem em que o usuário faz as coisas.

        Modelos que não recebem e devolvem texto são descartados: a lista tem
        modelos de imagem, áudio e música, e nenhum deles serve aqui.
        """
        dados = self._pedir("GET", "/models")

        modelos = []
        for bruto in dados.get("data", []):
            if not _e_modelo_de_texto(bruto):
                continue
            modelos.append(
                ModeloDisponivel(
                    id=bruto.get("id", ""),
                    nome=bruto.get("name") or bruto.get("id", ""),
                    contexto=int(bruto.get("context_length") or 0),
                    gratuito=_e_gratuito(bruto),
                )
            )

        return sorted(modelos, key=lambda m: (not m.gratuito, m.nome.lower()))

    # ----------------------------------------------------------------------- #
    # As três operações do item 4.2
    # ----------------------------------------------------------------------- #

    def extrair_elementos(
        self, texto_capitulo: str, estados_conhecidos: list[str], modelo: str
    ) -> ExtracaoDeElementos:
        """Pede ao modelo os elementos visuais do capítulo — fase 1 (passo 6)."""
        conhecidos = (
            "\n".join(f"- {estado}" for estado in estados_conhecidos)
            if estados_conhecidos
            else "(nenhum elemento cadastrado ainda)"
        )
        pedido = (
            f"ESTADOS CONHECIDOS DOS ELEMENTOS JÁ CADASTRADOS:\n{conhecidos}\n\n"
            f"TEXTO DO CAPÍTULO:\n{texto_capitulo}"
        )

        resposta = self._conversar(modelo, _INSTRUCAO_DE_EXTRACAO, pedido)
        bruto = _extrair_json(resposta)
        if bruto is None:
            raise ErroDoProvedorIA(
                "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
                "pequenos não seguem bem instruções de formato."
            )
        return ExtracaoDeElementos(
            elementos=_interpretar_elementos(bruto),
            cenas=_interpretar_cenas_sugeridas(bruto),
            modelo=modelo,
        )

    def sugerir_estado(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        descricao_do_elemento: str | None,
        estado_atual: str | None,
        modelo: str,
    ) -> EstadoSugerido:
        """Pede ao modelo a aparência de UM elemento — fase 2 (item 4.4)."""
        pedido = (
            f"ELEMENTO A DESCREVER: {nome} ({tipo.name})\n"
            f"IDENTIDADE JÁ CONHECIDA: {descricao_do_elemento or '(nenhuma)'}\n"
            f"ESTADO JÁ REGISTRADO (pode estar desatualizado): "
            f"{estado_atual or '(nenhum ainda)'}\n\n"
            f"TEXTO DO CAPÍTULO:\n{texto_capitulo}"
        )

        resposta = self._conversar(modelo, _INSTRUCAO_DE_ESTADO, pedido)
        return EstadoSugerido(descricao=_interpretar_estado(resposta), modelo=modelo)

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
        """Pede ao modelo para conferir a cena contra o capítulo (item 4.4)."""
        lista = "\n".join(f"- {p}" for p in participantes) or "(nenhum)"
        pedido = (
            f"O QUE O USUÁRIO ESCREVEU SOBRE A CENA:\n"
            f"Título: {titulo}\n"
            f"Descrição: {descricao or '(nenhuma)'}\n"
            f"Horário: {horario or '(não informado)'}\n"
            f"Clima: {clima or '(não informado)'}\n"
            f"Humor: {humor or '(não informado)'}\n\n"
            f"PARTICIPANTES, COM A APARÊNCIA JÁ ESTABELECIDA:\n{lista}\n\n"
            f"TEXTO DO CAPÍTULO:\n{texto_capitulo}"
        )

        resposta = self._conversar(modelo, _INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME, pedido)
        return FrameFundamentado(
            contexto=_interpretar_contexto(resposta), modelo=modelo
        )

    def montar_prompt(
        self,
        descricao_do_frame: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
        contexto_do_livro: str | None = None,
        comentario_do_usuario: str | None = None,
    ) -> PromptMontado:
        """Pede ao modelo o prompt de imagem (passo 8)."""
        lista = "\n".join(f"- {elemento}" for elemento in elementos) or "(nenhum)"
        pedido = (
            f"CENA (escrita pelo usuário; vazio significa retrato solo):\n"
            f"{descricao_do_frame or '(nenhuma — monte um retrato)'}\n\n"
            f"ELEMENTOS QUE APARECEM, COM A APARÊNCIA DE CADA UM:\n{lista}\n\n"
            f"ESTILO VISUAL:\n{perfil_renderizacao}"
        )
        if contexto_do_livro:
            pedido += f"\n\nCONTEXTO DO LIVRO (apoio, não substitui a cena acima):\n{contexto_do_livro}"
        if comentario_do_usuario:
            pedido += f"\n\nCOMENTÁRIO DO USUÁRIO (prioridade máxima):\n{comentario_do_usuario}"

        resposta = self._conversar(modelo, _INSTRUCAO_DE_PROMPT, pedido)
        return PromptMontado(texto=resposta.strip(), modelo=modelo)

    # ----------------------------------------------------------------------- #
    # Funções internas
    # ----------------------------------------------------------------------- #

    def conferir_se_cabe(self, texto: str, contexto_do_modelo: int) -> None:
        """Levanta ``TextoLongoDemais`` se o texto não couber no modelo.

        Feito **antes** da chamada: descobrir isso pela recusa da API significaria
        ter gastado a chamada para nada.
        """
        conferir_se_cabe(texto, contexto_do_modelo)

    def _conversar(self, modelo: str, instrucao: str, pedido: str) -> str:
        """Faz uma chamada de conversa e devolve o texto da resposta."""
        if not modelo:
            raise ModeloNaoEscolhido(
                "Nenhum modelo foi escolhido. Configure um em /configuracao."
            )
        if not self._chave_api:
            raise ChaveDeApiAusente(
                "Não há chave de API do OpenRouter configurada. Defina a variável "
                "de ambiente CHAVE_API_OPENROUTER ou cadastre a chave em "
                "/configuracao."
            )

        dados = self._pedir(
            "POST",
            "/chat/completions",
            json={
                "model": modelo,
                "messages": [
                    {"role": "system", "content": instrucao},
                    {"role": "user", "content": pedido},
                ],
            },
            autenticado=True,
        )

        try:
            return dados["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as erro:
            raise ErroDoProvedorIA(
                f"O modelo {modelo} respondeu num formato inesperado."
            ) from erro

    def _pedir(
        self,
        metodo: str,
        caminho: str,
        json: dict | None = None,
        autenticado: bool = False,
    ) -> dict:
        """Faz a chamada HTTP, traduzindo qualquer falha em ``ErroDoProvedorIA``.

        Traduzir aqui é o que permite às rotas responderem com uma mensagem que dá
        para mostrar na tela, em vez de deixar escapar um erro de rede ou um JSON
        inesperado como erro 500.
        """
        cabecalhos = {}
        if autenticado:
            cabecalhos["Authorization"] = f"Bearer {self._chave_api}"

        try:
            resposta = self._cliente.request(
                metodo, caminho, json=json, headers=cabecalhos
            )
        except httpx.TimeoutException as erro:
            raise ErroDoProvedorIA(
                "O OpenRouter não respondeu no tempo esperado. Modelos gratuitos "
                "ficam em fila; vale tentar de novo."
            ) from erro
        except httpx.HTTPError as erro:
            raise ErroDoProvedorIA(
                f"Não foi possível falar com o OpenRouter: {erro}"
            ) from erro

        if resposta.status_code == 401:
            raise ChaveDeApiAusente(
                "O OpenRouter recusou a chave de API. Verifique se ela está certa."
            )
        if resposta.status_code >= 400:
            raise ErroDoProvedorIA(
                f"O OpenRouter respondeu {resposta.status_code}: "
                f"{_resumir(resposta.text)}"
            )

        try:
            return resposta.json()
        except ValueError as erro:
            raise ErroDoProvedorIA(
                "O OpenRouter respondeu algo que não é JSON."
            ) from erro


def estimar_tokens(texto: str) -> int:
    """Estima quantos tokens um texto ocupa.

    Estimativa e não contagem: contar de verdade exigiria o tokenizador de cada
    modelo, e a decisão que isto alimenta — "cabe ou não cabe" — tem folga
    suficiente para não depender dessa precisão.
    """
    return len(texto) // CARACTERES_POR_TOKEN


def conferir_se_cabe(texto: str, contexto_do_modelo: int) -> None:
    """Levanta ``TextoLongoDemais`` se o texto não couber no modelo.

    Função livre, e não só método de ``ProvedorOpenRouter``, porque a rota que
    processa um capítulo (item 6.7) precisa da mesma checagem antes de chamar
    **qualquer** provedor, inclusive o falso dos testes — a estimativa não depende
    de nenhum detalhe de um fornecedor específico.
    """
    if contexto_do_modelo <= 0:
        return

    estimados = estimar_tokens(texto)
    if estimados + FOLGA_DE_TOKENS > contexto_do_modelo:
        raise TextoLongoDemais(
            f"O texto tem cerca de {estimados} tokens e o modelo aceita "
            f"{contexto_do_modelo}. Escolha um modelo com janela de contexto "
            f"maior — dos modelos gratuitos, todos os testados aceitam pelo "
            f"menos 32 mil."
        )


def _e_modelo_de_texto(bruto: dict) -> bool:
    """Descarta modelos de imagem, áudio e música.

    O critério é a **saída**: um modelo serve aqui se produz texto e nada além de
    texto. A entrada pode incluir imagem ou vídeo sem problema — um modelo
    multimodal continua sabendo ler um capítulo.

    Olhar só para "produz texto" não basta, e isso apareceu numa chamada real:
    ``google/lyria-3-pro-preview`` é um modelo de música que declara
    ``output_modalities: ["text", "audio"]``. Ele produz texto, mas não é o que se
    quer numa lista de onde escolher quem vai ler um capítulo de livro.

    Um modelo que produz texto **e** imagem também fica de fora. Se algum dia
    fizer sentido usar um deles, o id pode ser cadastrado direto em
    ``/configuracao`` — o filtro governa a lista de escolha, não o que é aceito.
    """
    arquitetura = bruto.get("architecture") or {}
    saidas = set(arquitetura.get("output_modalities") or [])

    # Sem a informação, assume que é de texto. Medido na resposta real: os 458
    # modelos declaram modalidades, então este caminho não é exercitado hoje.
    # Fica como proteção: se o campo desaparecer da API, é melhor a lista vir
    # completa demais do que vazia, que deixaria o usuário sem como configurar.
    if not saidas:
        return True

    return saidas == {"text"}


def _e_gratuito(bruto: dict) -> bool:
    """Um modelo é gratuito quando o preço do prompt é zero."""
    preco = (bruto.get("pricing") or {}).get("prompt")
    try:
        return float(preco) == 0.0
    except (TypeError, ValueError):
        return False


def _interpretar_elementos(bruto: dict) -> list[ElementoSugerido]:
    """Lê a lista de elementos de dentro do JSON já interpretado.

    Elementos com tipo desconhecido ou sem nome são descartados em silêncio — é
    sugestão, e uma entrada malformada não deveria derrubar as outras vinte.
    """
    sugeridos = []
    for entrada in bruto.get("elementos") or []:
        if not isinstance(entrada, dict):
            continue
        nome = (entrada.get("nome") or "").strip()
        if not nome:
            continue
        try:
            tipo = TipoElemento[(entrada.get("tipo") or "").strip().upper()]
        except KeyError:
            continue

        sugeridos.append(
            ElementoSugerido(
                tipo=tipo,
                nome=nome,
                descricao=_texto_ou_nulo(entrada.get("descricao")),
                manter_estado_atual=bool(entrada.get("manter_estado_atual")),
            )
        )

    return sugeridos


def _interpretar_cenas_sugeridas(bruto: dict) -> list[CenaSugerida]:
    """Lê a lista de cenas sugeridas de dentro do JSON já interpretado.

    Cada uma vira uma ``CenaSugerida``. Mesma tolerância de
    ``_interpretar_elementos``: uma entrada malformada, ou sem nenhum
    participante, é descartada em silêncio em vez de derrubar as outras.
    """
    sugeridos = []
    for entrada in bruto.get("cenas") or []:
        if not isinstance(entrada, dict):
            continue
        titulo = (entrada.get("titulo") or "").strip()
        if not titulo:
            continue

        participantes = []
        for participante in entrada.get("participantes") or []:
            if not isinstance(participante, dict):
                continue
            nome = (participante.get("nome") or "").strip()
            if not nome:
                continue
            try:
                tipo = TipoElemento[(participante.get("tipo") or "").strip().upper()]
            except KeyError:
                continue
            participantes.append(ParticipanteSugerido(tipo=tipo, nome=nome))

        if not participantes:
            continue

        sugeridos.append(
            CenaSugerida(
                titulo=titulo,
                descricao=_texto_ou_nulo(entrada.get("descricao")),
                horario=_texto_ou_nulo(entrada.get("horario")),
                clima=_texto_ou_nulo(entrada.get("clima")),
                humor=_texto_ou_nulo(entrada.get("humor")),
                participantes=participantes,
            )
        )

    return sugeridos


def _interpretar_estado(resposta: str) -> str:
    """Lê o JSON da leitura profunda de um elemento (fase 2, item 4.4).

    Mesma leitura tolerante de ``_interpretar_elementos``: tira cerca de
    markdown e procura o primeiro objeto JSON do texto.
    """
    bruto = _extrair_json(resposta)
    if bruto is None:
        raise ErroDoProvedorIA(
            "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
            "pequenos não seguem bem instruções de formato."
        )

    descricao = _texto_ou_nulo(bruto.get("descricao"))
    if descricao is None:
        raise ErroDoProvedorIA(
            "O modelo devolveu um JSON sem o campo 'descricao'."
        )
    return descricao


def _interpretar_contexto(resposta: str) -> str:
    """Lê o JSON da fundamentação de um frame do tipo CENA (item 4.4).

    Mesma leitura tolerante das demais interpretações desta camada.
    """
    bruto = _extrair_json(resposta)
    if bruto is None:
        raise ErroDoProvedorIA(
            "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
            "pequenos não seguem bem instruções de formato."
        )

    contexto = _texto_ou_nulo(bruto.get("contexto"))
    if contexto is None:
        raise ErroDoProvedorIA(
            "O modelo devolveu um JSON sem o campo 'contexto'."
        )
    return contexto


def _extrair_json(resposta: str) -> dict | None:
    """Acha o objeto JSON dentro da resposta do modelo."""
    limpo = re.sub(r"^\s*```(?:json)?|```\s*$", "", resposta.strip(), flags=re.MULTILINE)

    try:
        carregado = json.loads(limpo)
    except ValueError:
        inicio, fim = limpo.find("{"), limpo.rfind("}")
        if inicio == -1 or fim <= inicio:
            return None
        try:
            carregado = json.loads(limpo[inicio : fim + 1])
        except ValueError:
            return None

    return carregado if isinstance(carregado, dict) else None


def _texto_ou_nulo(valor) -> str | None:
    """Normaliza um campo de texto opcional vindo do modelo."""
    if not isinstance(valor, str):
        return None
    limpo = valor.strip()
    return limpo or None


def _resumir(texto: str, limite: int = 200) -> str:
    """Encurta o corpo de uma resposta de erro para caber numa mensagem."""
    achatado = " ".join(texto.split())
    return achatado if len(achatado) <= limite else achatado[:limite] + "…"
