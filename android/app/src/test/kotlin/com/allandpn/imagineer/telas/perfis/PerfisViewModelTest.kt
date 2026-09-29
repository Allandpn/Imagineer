package com.allandpn.imagineer.telas.perfis

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
import com.allandpn.imagineer.rede.CapituloDetalhe
import com.allandpn.imagineer.rede.CapituloResumo
import com.allandpn.imagineer.rede.ElementoResumo
import com.allandpn.imagineer.rede.LivroDetalhe
import com.allandpn.imagineer.rede.LivroResumo
import com.allandpn.imagineer.rede.PerfilRenderizacao
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
class PerfisViewModelTest {

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
    fun `com perfis, o estado traz a lista`() {
        val perfil = PerfilRenderizacao(
            id = 1,
            nome = "Aquarela sombria",
            estilo = "aquarela, traços soltos",
            iluminacao = "difusa",
            paleta = "tons terrosos",
        )

        val viewModel = PerfisViewModel(
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(listOf(perfil)) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDosPerfis.ComPerfis)
        assertEquals(listOf(perfil), (estado as EstadoDosPerfis.ComPerfis).perfis)
    }

    @Test
    fun `lista vazia vira estado vazio`() {
        val viewModel = PerfisViewModel(
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(emptyList()) },
        )

        assertEquals(EstadoDosPerfis.Vazia, viewModel.estado.value)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = PerfisViewModel(
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalha("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDosPerfis.Erro)
        assertEquals("sem conexão", (estado as EstadoDosPerfis.Erro).mensagem)
    }

    private fun apiCom(perfis: List<PerfilRenderizacao>) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = error("não usado neste teste")
        override suspend fun listarPerfis(): List<PerfilRenderizacao> = perfis
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = error("não usado neste teste")
        override suspend fun listarPerfis(): List<PerfilRenderizacao> = throw RuntimeException(mensagem)
    }
}
