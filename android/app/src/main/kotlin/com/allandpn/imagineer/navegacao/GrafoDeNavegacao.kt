package com.allandpn.imagineer.navegacao

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.allandpn.imagineer.armazenamento.PreferenciasApp
import com.allandpn.imagineer.telas.biblioteca.BibliotecaViewModel
import com.allandpn.imagineer.telas.biblioteca.FabricaDeBibliotecaViewModel
import com.allandpn.imagineer.telas.biblioteca.TelaBiblioteca
import com.allandpn.imagineer.telas.capitulo.CapituloViewModel
import com.allandpn.imagineer.telas.capitulo.FabricaDeCapituloViewModel
import com.allandpn.imagineer.telas.capitulo.TelaCapitulo
import com.allandpn.imagineer.telas.configuracao.TelaConfiguracao
import com.allandpn.imagineer.telas.elementos.ElementosViewModel
import com.allandpn.imagineer.telas.elementos.FabricaDeElementosViewModel
import com.allandpn.imagineer.telas.elementos.TelaElementos
import com.allandpn.imagineer.telas.frame.FabricaDeFrameViewModel
import com.allandpn.imagineer.telas.frame.FrameViewModel
import com.allandpn.imagineer.telas.frame.TelaFrame
import com.allandpn.imagineer.telas.perfis.FabricaDePerfisViewModel
import com.allandpn.imagineer.telas.perfis.PerfisViewModel
import com.allandpn.imagineer.telas.perfis.TelaPerfis
import com.allandpn.imagineer.telas.livro.FabricaDeLivroViewModel
import com.allandpn.imagineer.telas.livro.LivroViewModel
import com.allandpn.imagineer.telas.livro.TelaLivro
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * O grafo de navegação inteiro do app, montado de uma vez (item 7.1: pilha
 * hierárquica Biblioteca → Livro → Capítulo → Frame → Prompt). Só
 * Biblioteca e Configuração têm tela de verdade por enquanto — as demais
 * são um placeholder "em construção", pra a navegação já existir por
 * inteiro antes de cada tela ser implementada, uma de cada vez.
 */
@Composable
fun GrafoDeNavegacao(
    preferencias: PreferenciasApp,
    controlador: NavHostController = rememberNavController(),
) {
    val escopo = rememberCoroutineScope()

    NavHost(navController = controlador, startDestination = Biblioteca) {
        composable<Biblioteca> { entrada ->
            val viewModel: BibliotecaViewModel = viewModel(
                factory = FabricaDeBibliotecaViewModel(preferencias),
            )
            val estado by viewModel.estado.collectAsState()

            // Recarrega sempre que esta tela volta a ficar visível — por
            // exemplo, depois de apagar um livro na tela de Livro (7.4) e
            // voltar pra cá. `entrada.lifecycle` é o ciclo de vida deste
            // destino específico na pilha, não da Activity inteira.
            DisposableEffect(entrada) {
                val observador = LifecycleEventObserver { _, evento ->
                    if (evento == Lifecycle.Event.ON_RESUME) viewModel.carregar()
                }
                entrada.lifecycle.addObserver(observador)
                onDispose { entrada.lifecycle.removeObserver(observador) }
            }

            TelaBiblioteca(
                estado = estado,
                aoTocarLivro = { livroId -> controlador.navigate(Livro(livroId)) },
                aoTocarImportar = { /* tela de importação, ainda não implementada */ },
                aoTocarConfiguracao = { controlador.navigate(Configuracao) },
                aoTentarDeNovo = { viewModel.carregar() },
            )
        }

        composable<Configuracao> {
            var enderecoAtual by remember { mutableStateOf("") }
            LaunchedEffect(Unit) {
                enderecoAtual = preferencias.enderecoDoServidor.first() ?: ""
            }

            TelaConfiguracao(
                enderecoAtual = enderecoAtual,
                aoVoltar = { controlador.popBackStack() },
                aoSalvar = { novoEndereco ->
                    escopo.launch {
                        preferencias.salvarEnderecoDoServidor(novoEndereco)
                        controlador.popBackStack()
                    }
                },
            )
        }

        composable<Livro> { entrada ->
            val livro: Livro = entrada.toRoute()
            val viewModel: LivroViewModel = viewModel(
                factory = FabricaDeLivroViewModel(livro.livroId, preferencias),
            )
            val estado by viewModel.estado.collectAsState()
            val apagado by viewModel.apagado.collectAsState()

            LaunchedEffect(apagado) {
                if (apagado) controlador.popBackStack()
            }

            TelaLivro(
                estado = estado,
                aoVoltar = { controlador.popBackStack() },
                aoTocarCapitulo = { capituloId -> controlador.navigate(Capitulo(capituloId)) },
                aoTocarElementos = { controlador.navigate(ElementosDoLivro(livro.livroId)) },
                aoTocarPerfis = { controlador.navigate(PerfisDeRenderizacao) },
                aoTentarDeNovo = { viewModel.carregar() },
                aoAlternarIgnorado = { capituloId, ignoradoAtual ->
                    viewModel.alternarIgnorado(capituloId, ignoradoAtual)
                },
                aoConfirmarApagar = { viewModel.apagarLivro() },
            )
        }
        composable<Capitulo> { entrada ->
            val capitulo: Capitulo = entrada.toRoute()
            val viewModel: CapituloViewModel = viewModel(
                factory = FabricaDeCapituloViewModel(capitulo.capituloId, preferencias),
            )
            val estado by viewModel.estado.collectAsState()

            TelaCapitulo(
                estado = estado,
                aoVoltar = { controlador.popBackStack() },
                aoTentarDeNovo = { viewModel.carregar() },
            )
        }
        composable<Frame> { entrada ->
            val frame: Frame = entrada.toRoute()
            val viewModel: FrameViewModel = viewModel(
                factory = FabricaDeFrameViewModel(frame.frameId, preferencias),
            )
            val estado by viewModel.estado.collectAsState()

            TelaFrame(
                estado = estado,
                aoVoltar = { controlador.popBackStack() },
                aoTentarDeNovo = { viewModel.carregar() },
            )
        }
        composable<Prompt> { EmConstrucao("Prompt") }
        composable<ElementosDoLivro> { entrada ->
            val destino: ElementosDoLivro = entrada.toRoute()
            val viewModel: ElementosViewModel = viewModel(
                factory = FabricaDeElementosViewModel(destino.livroId, preferencias),
            )
            val estado by viewModel.estado.collectAsState()
            val tipoSelecionado by viewModel.tipoSelecionado.collectAsState()

            TelaElementos(
                estado = estado,
                tipoSelecionado = tipoSelecionado,
                aoVoltar = { controlador.popBackStack() },
                aoFiltrar = { tipo -> viewModel.filtrarPorTipo(tipo) },
                aoTentarDeNovo = { viewModel.carregar() },
                aoTocarElemento = { elementoId -> controlador.navigate(ElementoDetalhe(elementoId)) },
            )
        }
        composable<ElementoDetalhe> { EmConstrucao("Elemento") }
        composable<PerfisDeRenderizacao> {
            val viewModel: PerfisViewModel = viewModel(factory = FabricaDePerfisViewModel(preferencias))
            val estado by viewModel.estado.collectAsState()

            TelaPerfis(
                estado = estado,
                aoVoltar = { controlador.popBackStack() },
                aoTentarDeNovo = { viewModel.carregar() },
            )
        }
    }
}

@Composable
private fun EmConstrucao(nomeDaTela: String) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("$nomeDaTela — ainda não implementada")
    }
}
