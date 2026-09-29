package com.allandpn.imagineer.telas.perfis

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
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
import com.allandpn.imagineer.rede.PerfilRenderizacao

/**
 * Tela de Perfis de renderização (item 7.9) — lista compartilhada entre
 * livros. Só leitura por enquanto; criar, editar, apagar e sugerir com IA
 * (todos especificados no item 7.9) são a próxima fatia.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaPerfis(
    estado: EstadoDosPerfis,
    aoVoltar: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Perfis de renderização") },
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
                is EstadoDosPerfis.Carregando -> Carregando()
                is EstadoDosPerfis.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                is EstadoDosPerfis.Vazia -> PerfisVazia()
                is EstadoDosPerfis.ComPerfis -> ListaDePerfis(estado.perfis)
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
private fun PerfisVazia() {
    Box(modifier = Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text("Nenhum perfil criado ainda.", style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun ListaDePerfis(perfis: List<PerfilRenderizacao>) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(perfis, key = { it.id }) { perfil -> CardDePerfil(perfil) }
    }
}

@Composable
private fun CardDePerfil(perfil: PerfilRenderizacao) {
    val subtitulo = listOfNotNull(perfil.estilo, perfil.paleta).joinToString(" — ")

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(perfil.nome, style = MaterialTheme.typography.titleSmall)
            if (subtitulo.isNotBlank()) {
                Text(
                    subtitulo,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
