"""Implementação de ``ProvedorIA`` sobre o OpenRouter (item 4.1).

O OpenRouter é um gateway único para muitos modelos, inclusive gratuitos, com uma
API compatível com a da OpenAI. Foi escolhido para não precisar de um adaptador
por fornecedor na v1 (Etapa 5).
"""

import json
import re

import httpx

from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ElementoSugerido,
    ErroDoProvedorIA,
    ExtracaoDeElementos,
    ModeloDisponivel,
    ModeloNaoEscolhido,
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
nele, para que alguém possa depois gerar imagens das cenas.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "elementos": [
    {
      "tipo": "PERSONAGEM",
      "nome": "como o elemento é chamado no texto",
      "descricao": "quem ou o que é: papel na história, natureza, função",
      "estado_sugerido": "como aparenta estar NESTE capítulo: roupas, ferimentos, condição",
      "manter_estado_atual": false
    }
  ]
}

Os tipos possíveis são: PERSONAGEM, AMBIENTE, OBJETO, CRIATURA, GRUPO, VEICULO, \
EDIFICACAO.

Regras:
- Inclua apenas o que tem presença visual no capítulo. Ignore conceitos abstratos.
- Se um elemento da lista de estados conhecidos aparece no capítulo SEM mudança \
visível, repita o nome dele e marque "manter_estado_atual": true, deixando \
"estado_sugerido" nulo.
- Se houver mudança visível, marque "manter_estado_atual": false e descreva o \
estado novo.
- Use exatamente o nome que já está na lista de estados conhecidos, quando o \
elemento já for conhecido.
- Escreva em português.
"""

_INSTRUCAO_DE_PROMPT = """\
Você monta prompts para ferramentas de geração de imagem.

Receba a descrição de uma cena, a lista de elementos que aparecem nela com a \
aparência de cada um, e o estilo visual desejado. Produza UM prompt em inglês, \
numa linha só, pronto para colar na ferramenta.

Responda APENAS com o texto do prompt, sem aspas, sem explicação, sem título.

Regras:
- Descreva o que se vê, não o que se sente ou se conclui.
- Mantenha fielmente a aparência de cada elemento como foi descrita.
- Incorpore o estilo, a iluminação e a paleta indicados.
- Não invente elementos que não estão na lista.
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
    # As duas operações do item 4.2
    # ----------------------------------------------------------------------- #

    def extrair_elementos(
        self, texto_capitulo: str, estados_conhecidos: list[str], modelo: str
    ) -> ExtracaoDeElementos:
        """Pede ao modelo os elementos visuais do capítulo (passo 6)."""
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
        return ExtracaoDeElementos(
            elementos=_interpretar_elementos(resposta), modelo=modelo
        )

    def montar_prompt(
        self,
        descricao_da_cena: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
    ) -> PromptMontado:
        """Pede ao modelo o prompt de imagem (passo 8)."""
        lista = "\n".join(f"- {elemento}" for elemento in elementos) or "(nenhum)"
        pedido = (
            f"CENA:\n{descricao_da_cena}\n\n"
            f"ELEMENTOS QUE APARECEM, COM A APARÊNCIA DE CADA UM:\n{lista}\n\n"
            f"ESTILO VISUAL:\n{perfil_renderizacao}"
        )

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


def _interpretar_elementos(resposta: str) -> list[ElementoSugerido]:
    """Lê o JSON de elementos que o modelo devolveu.

    Modelos costumam embrulhar o JSON em cerca de markdown, ou escrever uma frase
    antes dele, mesmo quando a instrução pede o contrário. Por isso a leitura é
    tolerante: tira a cerca e procura o primeiro objeto JSON do texto.

    Elementos com tipo desconhecido ou sem nome são descartados em silêncio — é
    sugestão, e uma entrada malformada não deveria derrubar as outras vinte.
    """
    bruto = _extrair_json(resposta)
    if bruto is None:
        raise ErroDoProvedorIA(
            "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
            "pequenos não seguem bem instruções de formato."
        )

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
                estado_sugerido=_texto_ou_nulo(entrada.get("estado_sugerido")),
                manter_estado_atual=bool(entrada.get("manter_estado_atual")),
            )
        )

    return sugeridos


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
