package com.allandpn.imagineer.rede

/**
 * Fake de [ApiImagineer] pros testes de ViewModel: cada método dispara erro
 * por padrão — cada teste sobrescreve só o(s) que realmente usa.
 *
 * Existe porque, antes dela, cada arquivo de teste reimplementava a
 * interface inteira à mão — e quando `ApiImagineer` ganhava um método novo,
 * era fácil esquecer de atualizar um teste antigo (aconteceu de verdade,
 * 29/09/2026: um bug de cache incremental do Gradle escondeu esse erro de
 * compilação em vários testes por várias rodadas, até um build limpo expor
 * todos de uma vez). Agora um método novo entra só aqui.
 */
open class ApiImagineerFalsa : ApiImagineer {
    override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
    override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
    override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
    override suspend fun apagarLivro(livroId: Int): Unit = error("não usado neste teste")
    override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
        error("não usado neste teste")
    override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = error("não usado neste teste")
    override suspend fun listarPerfis(): List<PerfilRenderizacao> = error("não usado neste teste")
    override suspend fun obterFrame(frameId: Int): FrameDetalhe = error("não usado neste teste")
    override suspend fun obterPrompt(promptId: Int): PromptDetalhe = error("não usado neste teste")
    override suspend fun obterElemento(elementoId: Int): ElementoDetalhe = error("não usado neste teste")
}
