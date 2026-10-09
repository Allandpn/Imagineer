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

import copy
import io
from decimal import Decimal

from PIL import Image

from imagineer.ia.provedor import (
    AudioNarrado,
    ErroDoProvedorIA,
    ModeloDeImagemDisponivel,
    ModeloDeVoz,
    ReferenciasParaGerar,
    CenaSugerida,
    ConteudoRecusado,
    ElementoSugerido,
    EstadoSugerido,
    ExtracaoDeElementos,
    FrameFundamentado,
    IdentidadeSugerida,
    ImagemConferida,
    ImagemGerada,
    ModeloDisponivel,
    MomentoSugerido,
    PerfilRenderizacaoSugerido,
    PromptMontado,
    ProvedorIA,
)
from imagineer.modelos import CategoriaEstilo, TipoElemento

MODELO_FALSO = "falso/modelo-de-teste"

MOTIVO_DE_RECUSA_FALSO = "The response was filtered due to the prompt triggering our content management policy."


def imagem_falsa(largura: int = 20, altura: int = 30) -> bytes:
    """Um PNG de verdade (o Pillow lê as dimensões), pequeno, para os testes de geração."""
    saida = io.BytesIO()
    Image.new("RGB", (largura, altura), (120, 80, 40)).save(saida, format="PNG")
    return saida.getvalue()

MODELOS_DE_VOZ_FALSOS = [
    ModeloDeVoz(id="microsoft/mai-voice-2.1-flash", nome="Microsoft: MAI-Voice 2.1 Flash", vozes=["pt-BR-Caio:MAI-Voice-2.1-Flash", "pt-BR-Luana:MAI-Voice-2.1-Flash"], preco_por_caractere=Decimal("0.000015")),
    ModeloDeVoz(id="google/gemini-3.8-flash-tts", nome="Google: Gemini 3.8 Flash TTS", vozes=["Zephyr", "Puck"], preco_por_caractere=None),
    ModeloDeVoz(id="fish-audio/s2.1-pro-free:free", nome="Fish Audio: S2.1 Pro Free", preco_por_caractere=Decimal(0), gratuito=True),
]

MODELOS_DE_IMAGEM_FALSOS = [
    ModeloDeImagemDisponivel(id="meta/muse-image", nome="Muse Image", preco_por_token=0.0000024, moderado=True),
    ModeloDeImagemDisponivel(id="bytedance-seed/seedream-5-0-flash", nome="Seedream Flash", preco_por_token=0.0000043, moderado=False),
]
"""O catálogo de imagem do provedor falso (MI1)."""

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
        modelos: list[ModeloDisponivel] | None = None,
        estado: str = "watercolor-ready appearance description",
        momentos: list[MomentoSugerido] | None = None,
        identidade: str | None = None,
        contexto: str = "the book confirms this happens in the guard room",
        dossie: dict | None = None,
        divergencias: list[str] | None = None,
        prompt: str = "watercolor painting of a snowy courtyard at dusk",
        perfil_sugerido: PerfilRenderizacaoSugerido | None = None,
        erro: Exception | None = None,
        recusas_de_imagem: int = 0,
        prompt_suavizado: str = "a softer version of the prompt",
        prompt_de_video: str = "slow push-in, the subject breathes slowly. No on-screen text.",
        pode_narrar: bool = True,
        narracao_falha_no_trecho: int | None = None,
    ):
        self._pode_narrar = pode_narrar
        self._narracao_falha_no_trecho = narracao_falha_no_trecho
        self.chamadas_de_narracao: list[tuple[str, str, str | None]] = []
        """O que a narração recebeu, por trecho: ``(texto, modelo, voz)``."""
        self._prompt_de_video = prompt_de_video
        self.chamadas_de_video: list[dict] = []
        self._recusas_de_imagem = recusas_de_imagem
        """Quantas das **primeiras** gerações de imagem o provedor recusa (``ConteudoRecusado``)."""
        self._prompt_suavizado = prompt_suavizado
        self.chamadas_de_traducao: list[dict] = []
        self.chamadas_de_correcao: list[dict] = []
        self._elementos = elementos if elementos is not None else []
        self._cenas_sugeridas = cenas_sugeridas if cenas_sugeridas is not None else []
        self._modelos = list(MODELOS_FALSOS) if modelos is None else modelos
        self._estado = estado
        self._momentos = momentos
        """A linha do tempo que ``sugerir_estado`` devolve (item 4.9, FL3); ``None`` por padrão: o formato antigo, de um instante só."""
        self._identidade = identidade
        """O incremento de identidade a devolver — ``None`` por padrão (o
        caso comum: nada de novo), como ``sugerir_identidade`` documenta."""
        self._contexto = contexto
        self._dossie = dossie
        self._divergencias = divergencias or []
        """O que ``conferir_imagem`` aponta; vazio por padrão: a imagem confere."""
        """O dossiê que ``fundamentar_frame`` devolve (item 4.9, FL5); ``None`` por padrão: o formato antigo, de um parágrafo só."""
        self._prompt = prompt
        self._perfil_sugerido = perfil_sugerido or PerfilRenderizacaoSugerido(
            estilo="aquarela, traços soltos", iluminacao="luz de vela", paleta="tons terrosos"
        )
        self._erro = erro
        self.chamadas_de_extracao: list[dict] = []
        self.chamadas_de_conferencia: list[dict] = []
        self.chamadas_de_estado: list[dict] = []
        self.chamadas_de_identidade: list[dict] = []
        self.chamadas_de_fundamentacao: list[dict] = []
        self.chamadas_de_prompt: list[dict] = []
        self.chamadas_de_sugestao_de_perfil: list[dict] = []
        self.chamadas_de_suavizacao: list[dict] = []
        self.chamadas_de_imagem: list[dict] = []

    def listar_modelos(self) -> list[ModeloDisponivel]:
        if self._erro is not None:
            raise self._erro
        return list(self._modelos)

    def listar_modelos_de_imagem(self) -> list[ModeloDeImagemDisponivel]:
        if self._erro is not None:
            raise self._erro
        return list(MODELOS_DE_IMAGEM_FALSOS)

    def listar_modelos_de_voz(self) -> list[ModeloDeVoz]:
        if self._erro is not None:
            raise self._erro
        return list(MODELOS_DE_VOZ_FALSOS)

    @property
    def pode_narrar(self) -> bool:
        return self._pode_narrar

    def narrar(self, texto: str, modelo: str, voz: str | None) -> AudioNarrado:
        """Devolve ``MP3[n]`` (o n-ésimo trecho) e o custo de US$ 0,000001 por caractere; o trecho ``narracao_falha_no_trecho`` falha."""
        self.chamadas_de_narracao.append((texto, modelo, voz))
        numero = len(self.chamadas_de_narracao)
        if self._narracao_falha_no_trecho == numero:
            raise ErroDoProvedorIA("O OpenRouter respondeu 500: falha de teste.")
        return AudioNarrado(conteudo=f"MP3[{numero}]".encode(), custo=Decimal(len(texto)) / 1_000_000, id_da_geracao=f"gen-{numero}")

    def extrair_elementos(
        self,
        texto_capitulo: str,
        elementos_conhecidos: list[str],
        modelo: str,
        orientacao: str | None = None,
    ) -> ExtracaoDeElementos:
        self.chamadas_de_extracao.append(
            {
                "texto_capitulo": texto_capitulo,
                "elementos_conhecidos": elementos_conhecidos,
                "modelo": modelo,
                "orientacao": orientacao,
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
        aparencia_anterior: str | None = None,
        id_do_capitulo: int | None = None,
    ) -> EstadoSugerido:
        chamada = {
            "texto_capitulo": texto_capitulo,
            "tipo": tipo,
            "nome": nome,
            "descricao_do_elemento": descricao_do_elemento,
            "estado_atual": estado_atual,
            "aparencia_anterior": aparencia_anterior,
            "modelo": modelo,
        }
        if id_do_capitulo is not None:  # só aparece quando a rota o passa, para os testes de antes não mudarem
            chamada["id_do_capitulo"] = id_do_capitulo
        self.chamadas_de_estado.append(chamada)
        if self._erro is not None:
            raise self._erro
        return EstadoSugerido(descricao=self._estado, modelo=modelo, momentos=self._momentos)

    def sugerir_identidade(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        identidade_vigente: str | None,
        modelo: str,
        id_do_capitulo: int | None = None,
    ) -> IdentidadeSugerida:
        chamada = {
            "texto_capitulo": texto_capitulo,
            "tipo": tipo,
            "nome": nome,
            "identidade_vigente": identidade_vigente,
            "modelo": modelo,
        }
        if id_do_capitulo is not None:
            chamada["id_do_capitulo"] = id_do_capitulo
        self.chamadas_de_identidade.append(chamada)
        if self._erro is not None:
            raise self._erro
        return IdentidadeSugerida(descricao=self._identidade, modelo=modelo)

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
        chamada = {
            "texto_capitulo": texto_capitulo,
            "titulo": titulo,
            "descricao": descricao,
            "horario": horario,
            "clima": clima,
            "humor": humor,
            "participantes": participantes,
            "modelo": modelo,
        }
        if trecho:  # só aparece quando há trecho, para os testes de antes não mudarem
            chamada["trecho"] = trecho
        if id_do_capitulo is not None:
            chamada["id_do_capitulo"] = id_do_capitulo
        self.chamadas_de_fundamentacao.append(chamada)
        if self._erro is not None:
            raise self._erro
        return FrameFundamentado(contexto=self._contexto, modelo=modelo, dossie=copy.deepcopy(self._dossie) if self._dossie is not None else None)

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
        chamada = {
            "descricao_do_frame": descricao_do_frame,
            "elementos": elementos,
            "perfil_renderizacao": perfil_renderizacao,
            "modelo": modelo,
            "contexto_do_livro": contexto_do_livro,
            "comentario_do_usuario": comentario_do_usuario,
        }
        if elementos_vinculados:  # só aparece quando há vinculados, para os testes de antes não mudarem
            chamada["elementos_vinculados"] = elementos_vinculados
        if trecho_do_livro:
            chamada["trecho_do_livro"] = trecho_do_livro
        if dossie is not None:  # só aparece quando a rota o passa, para os testes de antes não mudarem
            chamada["dossie"] = dossie
        self.chamadas_de_prompt.append(chamada)
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=self._prompt, modelo=modelo)

    def conferir_imagem(self, imagem: bytes, tipo_de_midia: str, titulo_da_cena: str, dossie: dict, modelo: str) -> ImagemConferida:
        self.chamadas_de_conferencia.append(
            {"tamanho_da_imagem": len(imagem), "tipo_de_midia": tipo_de_midia, "titulo_da_cena": titulo_da_cena, "dossie": dossie, "modelo": modelo}
        )
        if self._erro is not None:
            raise self._erro
        return ImagemConferida(divergencias=list(self._divergencias), modelo=modelo)

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
        self.chamadas_de_video.append(
            {
                "descricao_do_frame": descricao_do_frame,
                "elementos": elementos,
                "perfil_renderizacao": perfil_renderizacao,
                "modelo": modelo,
                "contexto_do_livro": contexto_do_livro,
                "comentario_do_usuario": comentario_do_usuario,
                "elementos_vinculados": elementos_vinculados,
                "trecho_do_livro": trecho_do_livro,
                "prompt_da_imagem": prompt_da_imagem,
                "eh_retrato": eh_retrato,
            }
        )
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=self._prompt_de_video, modelo=modelo)

    def traduzir_prompt(self, texto: str, para: str, modelo: str) -> PromptMontado:
        """A tradução de mentira: põe um rótulo na frente, e guarda o pedido para os testes."""
        self.chamadas_de_traducao.append({"texto": texto, "para": para, "modelo": modelo})
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=f"[{para}] {texto}", modelo=modelo)

    def corrigir_prompt(self, texto: str, instrucao: str, modelo: str) -> PromptMontado:
        """A correção de mentira: devolve o texto com a instrução anexada, e guarda o pedido para os testes."""
        self.chamadas_de_correcao.append({"texto": texto, "instrucao": instrucao, "modelo": modelo})
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=f"{texto} [corrigido: {instrucao}]", modelo=modelo)

    def suavizar_prompt(self, texto: str, modelo: str) -> PromptMontado:
        self.chamadas_de_suavizacao.append({"texto": texto, "modelo": modelo})
        if self._erro is not None:
            raise self._erro
        return PromptMontado(texto=self._prompt_suavizado, modelo=modelo)

    def gerar_imagem(
        self,
        prompt: str,
        modelo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        chamada = {"prompt": prompt, "modelo": modelo}
        if referencias is not None:  # só aparece quando há referências, para os testes de antes não mudarem
            chamada["referencias"] = {"parametro": referencias.parametro, "quantidade": len(referencias.imagens)}
        if sem_filtro_de_seguranca:  # só aparece quando é verdadeiro, para os testes de antes não mudarem
            chamada["sem_filtro_de_seguranca"] = True
        self.chamadas_de_imagem.append(chamada)
        if self._erro is not None:
            raise self._erro
        if len(self.chamadas_de_imagem) <= self._recusas_de_imagem:
            raise ConteudoRecusado(MOTIVO_DE_RECUSA_FALSO)
        return ImagemGerada(conteudo=imagem_falsa(), tipo_de_midia="image/png", modelo=modelo)

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
