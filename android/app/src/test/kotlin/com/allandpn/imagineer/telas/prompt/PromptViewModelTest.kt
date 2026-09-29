package com.allandpn.imagineer.telas.prompt

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
import com.allandpn.imagineer.rede.CapituloDetalhe
import com.allandpn.imagineer.rede.CapituloResumo
import com.allandpn.imagineer.rede.ElementoResumo
import com.allandpn.imagineer.rede.FrameDetalhe
import com.allandpn.imagineer.rede.ImagemResumo
import com.allandpn.imagineer.rede.LivroDetalhe
import com.allandpn.imagineer.rede.LivroResumo
import com.allandpn.imagineer.rede.PerfilRenderizacao
import com.allandpn.imagineer.rede.PromptDetalhe
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PromptViewModelTest {

    @Before
    fun antesDeCada() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @After
    fun depoisDeCada() {
        Dispatchers.resetMain()
    }

    private fun provedorFalso(endereco: String?) = object : ProvedorDeEnderecoDoServidor {
        override val enderecoDoServidor = MutableStateFlow(endereco)
    }

    @Test
    fun `com sucesso, o estado traz o prompt com as imagens e referencias`() {
        val prompt = PromptDetalhe(
            id = 1,
            texto = "wide shot, Bran Stark...",
            avaliacao = null,
            imagens = listOf(ImagemResumo(id = 1)),
            referenciasVisuais = emptyList(),
        )

        val viewModel = PromptViewModel(
            promptId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(prompt) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoPrompt.Sucesso)
        assertEquals(prompt, (estado as EstadoDoPrompt.Sucesso).prompt)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = PromptViewModel(
            promptId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalha("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoPrompt.Erro)
        assertEquals("sem conexão", (estado as EstadoDoPrompt.Erro).mensagem)
    }

    private fun apiCom(prompt: PromptDetalhe) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = error("não usado neste teste")
        override suspend fun listarPerfis(): List<PerfilRenderizacao> = error("não usado neste teste")
        override suspend fun obterFrame(frameId: Int): FrameDetalhe = error("não usado neste teste")
        override suspend fun obterPrompt(promptId: Int) = prompt
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = error("não usado neste teste")
        override suspend fun listarPerfis(): List<PerfilRenderizacao> = error("não usado neste teste")
        override suspend fun obterFrame(frameId: Int): FrameDetalhe = error("não usado neste teste")
        override suspend fun obterPrompt(promptId: Int): PromptDetalhe = throw RuntimeException(mensagem)
    }
}
