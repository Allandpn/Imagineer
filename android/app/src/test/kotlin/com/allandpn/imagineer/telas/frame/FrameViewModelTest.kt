package com.allandpn.imagineer.telas.frame

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
import com.allandpn.imagineer.rede.CapituloDetalhe
import com.allandpn.imagineer.rede.CapituloResumo
import com.allandpn.imagineer.rede.ElementoResumo
import com.allandpn.imagineer.rede.EstadoComElemento
import com.allandpn.imagineer.rede.FrameDetalhe
import com.allandpn.imagineer.rede.LivroDetalhe
import com.allandpn.imagineer.rede.LivroResumo
import com.allandpn.imagineer.rede.PerfilRenderizacao
import com.allandpn.imagineer.rede.TipoDeFrame
import com.allandpn.imagineer.rede.TipoElemento
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
class FrameViewModelTest {

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
    fun `com sucesso, o estado traz o frame com os elementos`() {
        val frame = FrameDetalhe(
            id = 1,
            tipo = TipoDeFrame.CENA,
            titulo = "A caçada pela manhã",
            descricao = "Bran acompanha o pai numa caçada fria ao amanhecer.",
            horario = "manhã",
            clima = "frio",
            humor = "tensão",
            elementos = listOf(
                EstadoComElemento(
                    estadoId = 1,
                    elementoId = 1,
                    tipo = TipoElemento.PERSONAGEM,
                    nome = "Bran Stark",
                    descricao = "Menino magro, cabelo castanho bagunçado",
                ),
            ),
        )

        val viewModel = FrameViewModel(
            frameId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(frame) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoFrame.Sucesso)
        assertEquals(frame, (estado as EstadoDoFrame.Sucesso).frame)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = FrameViewModel(
            frameId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalha("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoFrame.Erro)
        assertEquals("sem conexão", (estado as EstadoDoFrame.Erro).mensagem)
    }

    private fun apiCom(frame: FrameDetalhe) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = error("não usado neste teste")
        override suspend fun listarPerfis(): List<PerfilRenderizacao> = error("não usado neste teste")
        override suspend fun obterFrame(frameId: Int) = frame
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
        override suspend fun obterFrame(frameId: Int): FrameDetalhe = throw RuntimeException(mensagem)
    }
}
