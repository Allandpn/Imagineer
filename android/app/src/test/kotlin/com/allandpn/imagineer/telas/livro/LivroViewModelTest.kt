package com.allandpn.imagineer.telas.livro

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
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

    private val livroDeExemplo = LivroDetalhe(
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

    @Test
    fun `com sucesso, o estado traz o livro com os capitulos`() {
        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComLivro(livroDeExemplo) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoLivro.Sucesso)
        assertEquals(livroDeExemplo, (estado as EstadoDoLivro.Sucesso).livro)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalhaAoObter("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoLivro.Erro)
        assertEquals("sem conexão", (estado as EstadoDoLivro.Erro).mensagem)
    }

    @Test
    fun `alternar ignorado atualiza so aquele capitulo, sem recarregar o livro inteiro`() {
        val capituloAtualizado = livroDeExemplo.capitulos[0].copy(ignorado = true)
        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiQueRetornaAoAjustarCapitulo(livroDeExemplo, capituloAtualizado) },
        )

        viewModel.alternarIgnorado(capituloId = 10, ignoradoAtual = false)

        val estado = viewModel.estado.value as EstadoDoLivro.Sucesso
        assertEquals(true, estado.livro.capitulos.first { it.id == 10 }.ignorado)
        // o outro capítulo não muda
        assertEquals(false, estado.livro.capitulos.first { it.id == 11 }.ignorado)
    }

    @Test
    fun `apagar livro com sucesso marca o estado de apagado`() {
        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiQueApagaComSucesso() },
        )

        viewModel.apagarLivro()

        assertEquals(true, viewModel.apagado.value)
    }

    @Test
    fun `falha ao apagar nao marca como apagado, vira erro`() {
        val viewModel = LivroViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiQueFalhaAoApagar(livroDeExemplo, "servidor fora do ar") },
        )

        // carregar() do init{} já deu certo (a API sabe responder obterLivro)
        assertTrue(viewModel.estado.value is EstadoDoLivro.Sucesso)

        viewModel.apagarLivro()

        assertEquals(false, viewModel.apagado.value)
        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDoLivro.Erro)
        assertEquals("servidor fora do ar", (estado as EstadoDoLivro.Erro).mensagem)
    }

    private fun apiComLivro(livro: LivroDetalhe) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int) = livro
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
            error("não usado neste teste")
    }

    private fun apiComFalhaAoObter(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = throw RuntimeException(mensagem)
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
            error("não usado neste teste")
    }

    private fun apiQueRetornaAoAjustarCapitulo(livro: LivroDetalhe, capituloAtualizado: CapituloResumo) =
        object : ApiImagineer {
            override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
            override suspend fun obterLivro(livroId: Int) = livro
            override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
            override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
                capituloAtualizado
        }

    private fun apiQueApagaComSucesso() = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) {}
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
            error("não usado neste teste")
    }

    private fun apiQueFalhaAoApagar(livro: LivroDetalhe, mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int) = livro
        override suspend fun apagarLivro(livroId: Int): Unit = throw RuntimeException(mensagem)
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest) =
            error("não usado neste teste")
    }
}
