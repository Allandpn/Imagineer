package com.allandpn.imagineer.telas.elementos

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
import com.allandpn.imagineer.rede.CapituloDetalhe
import com.allandpn.imagineer.rede.CapituloResumo
import com.allandpn.imagineer.rede.ElementoResumo
import com.allandpn.imagineer.rede.EstadoResumo
import com.allandpn.imagineer.rede.LivroDetalhe
import com.allandpn.imagineer.rede.LivroResumo
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
class ElementosViewModelTest {

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

    private val bran = ElementoResumo(
        id = 1,
        tipo = TipoElemento.PERSONAGEM,
        nome = "Bran Stark",
        estadoVigente = EstadoResumo(descricao = "Menino magro, cabelo castanho bagunçado"),
    )
    private val winterfell = ElementoResumo(
        id = 2,
        tipo = TipoElemento.EDIFICACAO,
        nome = "Winterfell",
        estadoVigente = null,
    )

    @Test
    fun `com elementos, o estado traz a lista inteira sem filtro`() {
        val viewModel = ElementosViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(listOf(bran, winterfell)) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDosElementos.ComElementos)
        assertEquals(listOf(bran, winterfell), (estado as EstadoDosElementos.ComElementos).elementos)
    }

    @Test
    fun `filtrar por tipo mostra so os elementos daquele tipo`() {
        val viewModel = ElementosViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(listOf(bran, winterfell)) },
        )

        viewModel.filtrarPorTipo(TipoElemento.EDIFICACAO)

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDosElementos.ComElementos)
        assertEquals(listOf(winterfell), (estado as EstadoDosElementos.ComElementos).elementos)
    }

    @Test
    fun `filtro sem resultado vira estado vazio`() {
        val viewModel = ElementosViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(listOf(bran)) },
        )

        viewModel.filtrarPorTipo(TipoElemento.OBJETO)

        assertEquals(EstadoDosElementos.Vazia, viewModel.estado.value)
    }

    @Test
    fun `voltar pro filtro Todos restaura a lista inteira`() {
        val viewModel = ElementosViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(listOf(bran, winterfell)) },
        )

        viewModel.filtrarPorTipo(TipoElemento.EDIFICACAO)
        viewModel.filtrarPorTipo(null)

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDosElementos.ComElementos)
        assertEquals(2, (estado as EstadoDosElementos.ComElementos).elementos.size)
    }

    @Test
    fun `lista vazia do servidor vira estado vazio`() {
        val viewModel = ElementosViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(emptyList()) },
        )

        assertEquals(EstadoDosElementos.Vazia, viewModel.estado.value)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = ElementosViewModel(
            livroId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalha("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDosElementos.Erro)
        assertEquals("sem conexão", (estado as EstadoDosElementos.Erro).mensagem)
    }

    private fun apiCom(elementos: List<ElementoResumo>) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int) = elementos
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineer {
        override suspend fun listarLivros(): List<LivroResumo> = error("não usado neste teste")
        override suspend fun obterLivro(livroId: Int): LivroDetalhe = error("não usado neste teste")
        override suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = error("não usado neste teste")
        override suspend fun apagarLivro(livroId: Int) = error("não usado neste teste")
        override suspend fun ajustarCapitulo(capituloId: Int, ajuste: CapituloAjusteRequest): CapituloResumo =
            error("não usado neste teste")
        override suspend fun listarElementos(livroId: Int): List<ElementoResumo> = throw RuntimeException(mensagem)
    }
}
