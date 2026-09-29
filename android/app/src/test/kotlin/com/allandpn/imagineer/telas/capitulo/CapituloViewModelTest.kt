package com.allandpn.imagineer.telas.capitulo

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
import com.allandpn.imagineer.rede.CapituloDetalhe
import com.allandpn.imagineer.rede.LivroDetalhe
import com.allandpn.imagineer.rede.LivroResumo
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
class CapituloViewModelTest {

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
    fun `com sucesso, o estado traz o capitulo com o texto`() {
        val capitulo = CapituloDetalhe(id = 10, ordem = 1, titulo = "Bran", texto = "O dia começou frio...")

        val viewModel = CapituloViewModel(
            capituloId = 10,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComCapitulo(capitulo) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoCapitulo.Sucesso)
        assertEquals(capitulo, (estado as EstadoDoCapitulo.Sucesso).capitulo)
    }

    @Test
    fun `sem endereco configurado, vira estado de erro`() {
        val viewModel = CapituloViewModel(
            capituloId = 10,
            preferencias = provedorFalso(null),
            criarApi = { error("não deveria ser chamado sem servidor configurado") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoCapitulo.Erro)
    }

    @Test
    fun `falha de rede vira estado de erro, com a mensagem da excecao`() {
        val viewModel = CapituloViewModel(
            capituloId = 10,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalha("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoCapitulo.Erro)
        assertEquals("sem conexão", (estado as EstadoDoCapitulo.Erro).mensagem)
    }

    private fun apiComCapitulo(capitulo: CapituloDetalhe) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
            error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int) = capitulo
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
            error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = throw RuntimeException(mensagem)
    }
}
