package com.allandpn.imagineer.telas.biblioteca

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioLivros
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.LivroResumo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Testa só a lógica de estado do ViewModel — nunca toca DataStore nem rede
 * de verdade, por isso não precisa de Android nem de emulador (item de
 * teste do CLAUDE.md: "nenhum item é considerado concluído sem teste").
 */
@OptIn(ExperimentalCoroutinesApi::class)
class BibliotecaViewModelTest {

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
    fun `sem endereco configurado, o estado avisa que falta configurar`() {
        val viewModel = BibliotecaViewModel(
            preferencias = provedorFalso(null),
            criarRepositorio = { RepositorioLivros(apiQueNuncaDeveriaSerChamada()) },
        )

        assertEquals(EstadoDaBiblioteca.SemServidorConfigurado, viewModel.estado.value)
    }

    @Test
    fun `com livros na resposta, o estado traz a lista`() {
        val livro = LivroResumo(
            id = 1,
            titulo = "A Guerra dos Tronos",
            autor = "George R. R. Martin",
            idioma = "pt-BR",
            nomeArquivo = "a-guerra-dos-tronos.epub",
            totalDeCapitulos = 33,
            capitulosIgnorados = 4,
        )

        val viewModel = BibliotecaViewModel(
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarRepositorio = { RepositorioLivros(apiComLivros(listOf(livro))) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDaBiblioteca.ComLivros)
        assertEquals(listOf(livro), (estado as EstadoDaBiblioteca.ComLivros).livros)
    }

    @Test
    fun `lista vazia na resposta vira estado vazio, nao erro`() {
        val viewModel = BibliotecaViewModel(
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarRepositorio = { RepositorioLivros(apiComLivros(emptyList())) },
        )

        assertEquals(EstadoDaBiblioteca.Vazia, viewModel.estado.value)
    }

    @Test
    fun `falha de rede vira estado de erro, com a mensagem da excecao`() {
        val viewModel = BibliotecaViewModel(
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarRepositorio = { RepositorioLivros(apiComFalha("sem conexão")) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDaBiblioteca.Erro)
        assertEquals("sem conexão", (estado as EstadoDaBiblioteca.Erro).mensagem)
    }

    private fun apiComLivros(livros: List<LivroResumo>) = object : ApiImagineer {
        override suspend fun listarLivros() = livros
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = throw RuntimeException(mensagem)
    }

    private fun apiQueNuncaDeveriaSerChamada() = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> =
            error("Sem servidor configurado, a API nunca deveria ser chamada")
    }
}
