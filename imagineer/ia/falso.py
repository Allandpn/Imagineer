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
    CenaSugerida,
    ElementoSugerido,
    EstadoSugerido,
    ExtracaoDeElementos,
    FrameFundamentado,
    ModeloDisponivel,
    PerfilRenderizacaoSugerido,
    PromptMontado,
    ProvedorIA,
)
from imagineer.modelos import CategoriaEstilo, TipoElemento

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
        cenas_sugeridas: list[CenaSugerida] | None = None,
        estado: str = "watercolor-ready appearance description",
        contexto: str = "the book confirms this happens in the guard room",
        prompt: str = "watercolor painting of a snowy courtyard at dusk",
        perfil_sugerido: PerfilRenderizacaoSugerido | None = None,
        erro: Exception | None = None,
    ):
        self._elementos = elementos if elementos is not None else []
        self._cenas_sugeridas = cenas_sugeridas if cenas_sugeridas is not None else []
        self._estado = estado
        self._contexto = contexto
        self._prompt = prompt
        self._perfil_sugerido = perfil_sugerido or PerfilRenderizacaoSugerido(
            estilo="aquarela, traços soltos", iluminacao="luz de vela", paleta="tons terrosos"
        )
        self._erro = erro
        self.chamadas_de_extracao: list[dict] = []
        self.chamadas_de_estado: list[dict] = []
        self.chamadas_de_fundamentacao: list[dict] = []
        self.chamadas_de_prompt: list[dict] = []
        self.chamadas_de_sugestao_de_perfil: list[dict] = []

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
        return ExtracaoDeElementos(
            elementos=list(self._elementos),
            cenas=list(self._cenas_sugeridas),
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
        self.chamadas_de_estado.append(
            {
                "texto_capitulo": texto_capitulo,
                "tipo": tipo,
                "nome": nome,
                "descricao_do_elemento": descricao_do_elemento,
                "estado_atual": estado_atual,
                "modelo": modelo,
            }
        )
        if self._erro is not None:
            raise self._erro
        return EstadoSugerido(descricao=self._estado, modelo=modelo)

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
        self.chamadas_de_fundamentacao.append(
            {
                "texto_capitulo": texto_capitulo,
                "titulo": titulo,
                "descricao": descricao,
                "horario": horario,
                "clima": clima,
                "humor": humor,
                "participantes": participantes,
                "modelo": modelo,
            }
        )
        if self._erro is not None:
            raise self._erro
        return FrameFundamentado(contexto=self._contexto, modelo=modelo)

    def montar_prompt(
        self,
        descricao_do_frame: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
        contexto_do_livro: str | None = None,
        comentario_do_usuario: str | None = None,
    ) -> PromptMontado:
        self.chamadas_de_prompt.append(
            {
                "descricao_do_frame": descricao_do_frame,
                "elementos": elementos,
                "perfil_renderizacao": perfil_renderizacao,
                "modelo": modelo,
                "contexto_do_livro": contexto_do_livro,
                "comentario_do_usuario": comentario_do_usuario,
            }
        )
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=self._prompt, modelo=modelo)

    def sugerir_perfil_renderizacao(
        self,
        titulo: str,
        autor: str | None,
        idioma: str | None,
        categoria_estilo: CategoriaEstilo | None,
        modelo: str,
    ) -> PerfilRenderizacaoSugerido:
        self.chamadas_de_sugestao_de_perfil.append(
            {
                "titulo": titulo,
                "autor": autor,
                "idioma": idioma,
                "categoria_estilo": categoria_estilo,
                "modelo": modelo,
            }
        )
        if self._erro is not None:
            raise self._erro
        sugestao = self._perfil_sugerido
        sugestao.modelo = modelo
        sugestao.categoria_estilo = categoria_estilo or sugestao.categoria_estilo
        return sugestao
