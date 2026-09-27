"""Um provedor de IA falso, para testes e para experimentar sem gastar chamadas.

Existe por dois motivos práticos:

1. Os testes precisam exercitar as rotas que usam IA sem depender de rede, de
   chave de API e de um modelo remoto que pode estar em fila ou fora do ar.
2. Dá para percorrer o sistema inteiro antes de ter uma chave cadastrada, o que é
   justamente a ordem em que as coisas acontecem.

Ele não tenta imitar a inteligência de um modelo: devolve o que foi combinado de
antemão. O que ele imita fielmente é o **contrato** — os mesmos tipos, os mesmos
erros.
"""

from imagineer.ia.provedor import (
    ElementoSugerido,
    ExtracaoDeElementos,
    ModeloDisponivel,
    PromptMontado,
    ProvedorIA,
)

MODELO_FALSO = "falso/modelo-de-teste"

MODELOS_FALSOS = [
    ModeloDisponivel(
        id=MODELO_FALSO, nome="Modelo de teste", contexto=128_000, gratuito=True
    ),
    ModeloDisponivel(
        id="falso/modelo-apertado",
        nome="Modelo de contexto apertado",
        contexto=4_000,
        gratuito=True,
    ),
]


class ProvedorFalso(ProvedorIA):
    """Devolve respostas combinadas de antemão, e registra o que foi pedido.

    Os atributos ``chamadas_de_extracao`` e ``chamadas_de_prompt`` guardam os
    argumentos recebidos, para os testes poderem afirmar **o que** foi mandado ao
    modelo — que é metade do que importa numa integração de IA.
    """

    def __init__(
        self,
        elementos: list[ElementoSugerido] | None = None,
        prompt: str = "watercolor painting of a snowy courtyard at dusk",
        erro: Exception | None = None,
    ):
        self._elementos = elementos if elementos is not None else []
        self._prompt = prompt
        self._erro = erro
        self.chamadas_de_extracao: list[dict] = []
        self.chamadas_de_prompt: list[dict] = []

    def listar_modelos(self) -> list[ModeloDisponivel]:
        if self._erro is not None:
            raise self._erro
        return list(MODELOS_FALSOS)

    def extrair_elementos(
        self, texto_capitulo: str, estados_conhecidos: list[str], modelo: str
    ) -> ExtracaoDeElementos:
        self.chamadas_de_extracao.append(
            {
                "texto_capitulo": texto_capitulo,
                "estados_conhecidos": estados_conhecidos,
                "modelo": modelo,
            }
        )
        if self._erro is not None:
            raise self._erro
        return ExtracaoDeElementos(elementos=list(self._elementos), modelo=modelo)

    def montar_prompt(
        self,
        descricao_da_cena: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
    ) -> PromptMontado:
        self.chamadas_de_prompt.append(
            {
                "descricao_da_cena": descricao_da_cena,
                "elementos": elementos,
                "perfil_renderizacao": perfil_renderizacao,
                "modelo": modelo,
            }
        )
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=self._prompt, modelo=modelo)
