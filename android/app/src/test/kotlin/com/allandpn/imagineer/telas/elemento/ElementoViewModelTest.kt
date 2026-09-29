package com.allandpn.imagineer.telas.elemento

import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.rede.ApiImagineerFalsa
import com.allandpn.imagineer.rede.ElementoDetalhe
import com.allandpn.imagineer.rede.EstadoDoElemento
import com.allandpn.imagineer.rede.HistoricoIdentidadeResumo
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
class ElementoViewModelTest {

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
    fun `com sucesso, o estado traz o elemento com o historico completo`() {
        val elemento = ElementoDetalhe(
            id = 1,
            tipo = TipoElemento.PERSONAGEM,
            nome = "Bran Stark",
            descricao = "Filho mais novo de Eddard e Catelyn Stark.",
            estados = listOf(
                EstadoDoElemento(id = 1, descricao = "Menino magro, cabelo castanho bagunçado."),
                EstadoDoElemento(id = 2, descricao = "Mesma aparência, com um corte no braço."),
            ),
            historicoIdentidade = listOf(
                HistoricoIdentidadeResumo(descricao = "Descobre que consegue sonhar como o lobo."),
            ),
        )

        val viewModel = ElementoViewModel(
            elementoId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiCom(elemento) },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDaTelaDeElemento.Sucesso)
        assertEquals(elemento, (estado as EstadoDaTelaDeElemento.Sucesso).elemento)
    }

    @Test
    fun `falha de rede vira estado de erro`() {
        val viewModel = ElementoViewModel(
            elementoId = 1,
            preferencias = provedorFalso("http://100.87.12.4:8000"),
            criarApi = { apiComFalha("sem conexão") },
        )

        val estado = viewModel.estado.value
        assertTrue(estado is EstadoDaTelaDeElemento.Erro)
        assertEquals("sem conexão", (estado as EstadoDaTelaDeElemento.Erro).mensagem)
    }

    private fun apiCom(elemento: ElementoDetalhe) = object : ApiImagineerFalsa() {
        override suspend fun obterElemento(elementoId: Int) = elemento
    }

    private fun apiComFalha(mensagem: String) = object : ApiImagineerFalsa() {
        override suspend fun obterElemento(elementoId: Int): ElementoDetalhe = throw RuntimeException(mensagem)
    }
}
