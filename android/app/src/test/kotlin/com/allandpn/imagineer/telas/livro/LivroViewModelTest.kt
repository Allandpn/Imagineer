package com.allandpn.imagineer.telas.livro

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioLivros
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloResumo
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
class LivroViewModelTest {

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
    fun `com sucesso, o estado traz o livro com os capitulos`() {
        val livro = LivroDetalhe(
            id = 1,
            titulo = "A Guerra dos Tronos",
            autor = "George R. R. Martin",
            idioma = "pt-BR",
            perfilRenderizacaoPadraoId = null,
            capitulos = listOf(
                CapituloResumo(id = 10, ordem = 1, titulo = "Bran", ignorado = false, sugestoesPendentes = 3),
                CapituloResumo(id = 11, ordem = 2, titulo = null, ignorado = false, sugestoesPendentes = 0),
            ),
        )

        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarRepositorio = { RepositorioLivros(apiComLivro(livro)) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoLivro.Sucesso)
        assertEquals(livro, (estado as EstadoDoLivro.Sucesso).livro)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarRepositorio = { RepositorioLivros(apiComFalha("sem conexão")) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoLivro.Erro)
        assertEquals("sem conexão", (estado as EstadoDoLivro.Erro).mensagem)
    }

    private fun apiComLivro(livro: LivroDetalhe) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int) = livro
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = throw RuntimeException(mensagem)
    }
}
