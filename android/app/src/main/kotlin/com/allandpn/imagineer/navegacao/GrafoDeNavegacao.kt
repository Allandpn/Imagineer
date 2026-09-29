package com.allandpn.imagineer.navegacao

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.allandpn.imagineer.armazenamento.PreferenciasApp
import com.allandpn.imagineer.telas.biblioteca.BibliotecaViewModel
import com.allandpn.imagineer.telas.biblioteca.FabricaDeBibliotecaViewModel
import com.allandpn.imagineer.telas.biblioteca.TelaBiblioteca
import com.allandpn.imagineer.telas.configuracao.TelaConfiguracao
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
        composable<Biblioteca> {
            val viewModel: BibliotecaViewModel = viewModel(
                factory = FabricaDeBibliotecaViewModel(preferencias),
            )
            val estado by viewModel.estado.collectAsState()

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

        composable<Livro> { EmConstrucao("Livro") }
        composable<Capitulo> { EmConstrucao("Capítulo") }
        composable<Frame> { EmConstrucao("Frame") }
        composable<Prompt> { EmConstrucao("Prompt") }
        composable<ElementosDoLivro> { EmConstrucao("Elementos do livro") }
        composable<PerfisDeRenderizacao> { EmConstrucao("Perfis de renderização") }
    }
}

@Composable
private fun EmConstrucao(nomeDaTela: String) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("$nomeDaTela — ainda não implementada")
    }
}
