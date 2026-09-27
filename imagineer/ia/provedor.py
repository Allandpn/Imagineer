"""A fronteira com os provedores de IA (item 4.2 da especificação).

Define o contrato ``ProvedorIA`` e os tipos que ele devolve. Toda a aplicação
conversa com esta interface, não com a API de um fornecedor — é o que permite
trocar de fornecedor, ou usar um provedor falso nos testes, sem tocar nas rotas.

Os métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que
adivinhar o formato da resposta nem repetir o trabalho de interpretá-la.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from imagineer.modelos import TipoElemento


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


@dataclass
class ElementoSugerido:
    """Um elemento que a IA acha que aparece no capítulo.

    É **sugestão**: nada disso vai para o banco antes do usuário confirmar
    (item 4.4). O campo ``elemento_id`` vem preenchido quando a sugestão casa com
    um elemento já cadastrado, e é o que permite à tela oferecer "manter o estado
    atual" em vez de criar um elemento repetido.
    """

    tipo: TipoElemento
    nome: str
    descricao: str | None = None
    estado_sugerido: str | None = None
    """Como o elemento parece estar neste capítulo."""

    elemento_id: int | None = None
    """O elemento já cadastrado a que esta sugestão corresponde, se houver."""

    manter_estado_atual: bool = False
    """A IA acha que o estado conhecido continua valendo (item 4.4)."""


@dataclass
class ExtracaoDeElementos:
    """O resultado de uma extração, com o rastro do que foi usado."""

    elementos: list[ElementoSugerido] = field(default_factory=list)
    modelo: str = ""
    """O modelo que produziu isto. Guardado para o usuário saber a quem creditar
    um resultado bom ou ruim."""


@dataclass
class PromptMontado:
    """O prompt de imagem pronto para o usuário copiar."""

    texto: str
    modelo: str = ""


class ProvedorIA(ABC):
    """O que a aplicação espera de um provedor de IA de texto.

    Duas operações, que correspondem aos passos 6 e 8 do fluxo da Etapa 2.
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
        """Sugere os elementos do capítulo (passo 6).

        Args:
            texto_capitulo: o texto a ler.
            estados_conhecidos: o último estado conhecido de cada elemento já
                cadastrado, em texto. É o contexto que permite à IA responder
                "manter estado atual" em vez de inventar um estado novo a cada
                capítulo (item 4.4).
            modelo: o identificador do modelo a usar.
        """

    @abstractmethod
    def montar_prompt(
        self,
        descricao_da_cena: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
    ) -> PromptMontado:
        """Monta o prompt de imagem a partir do que foi escolhido (passo 8)."""
