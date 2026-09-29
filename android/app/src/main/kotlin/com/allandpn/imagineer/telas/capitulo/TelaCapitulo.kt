package com.allandpn.imagineer.telas.capitulo

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * Tela de Capítulo (item 7.5) — só o texto completo, rolável, por
 * enquanto. "Analisar com IA", sugestões de elemento/cena, estados
 * vigentes e criação de frame (todos especificados no item 7.5) entram
 * nos próximos incrementos.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaCapitulo(
    estado: EstadoDoCapitulo,
    aoVoltar: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    val titulo = when (estado) {
        is EstadoDoCapitulo.Sucesso -> estado.capitulo.titulo ?: "Capítulo ${estado.capitulo.ordem}"
        else -> "Capítulo"
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(titulo, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    IconButton(onClick = aoVoltar) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Voltar")
                    }
                },
            )
        },
    ) { preenchimento ->
        Box(modifier = Modifier.fillMaxSize().padding(preenchimento)) {
            when (estado) {
                is EstadoDoCapitulo.Carregando -> Carregando()
                is EstadoDoCapitulo.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                is EstadoDoCapitulo.Sucesso -> TextoDoCapitulo(estado.capitulo.texto)
            }
        }
    }
}

@Composable
private fun Carregando() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun ErroDeConexao(mensagem: String, aoTentarDeNovo: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Não consegui falar com o servidor", style = MaterialTheme.typography.titleMedium)
        Text(mensagem, style = MaterialTheme.typography.bodyMedium)
        Button(onClick = aoTentarDeNovo, modifier = Modifier.padding(top = 16.dp)) {
            Text("Tentar de novo")
        }
    }
}

@Composable
private fun TextoDoCapitulo(texto: String) {
    Text(
        text = texto,
        style = MaterialTheme.typography.bodyLarge,
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    )
}
