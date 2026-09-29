package com.allandpn.imagineer.telas.elemento

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
import androidx.compose.material3.AssistChip
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
import androidx.compose.ui.unit.dp
import com.allandpn.imagineer.rede.ElementoDetalhe
import com.allandpn.imagineer.rede.EstadoDoElemento

/**
 * Tela de Elemento — detalhe (item 7.8): a "ficha" do personagem, com
 * identidade e o histórico completo de estados em ordem narrativa. Editar
 * identidade e apagar (especificados no mesmo item) entram na próxima
 * fatia; por isso a tela ainda não junta `descricao` (identidade inicial)
 * com `historicoIdentidade` (acréscimos por capítulo) numa "identidade
 * vigente" só — mostra os dois separados.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaElemento(
    estado: EstadoDaTelaDeElemento,
    aoVoltar: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Elemento") },
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
                is EstadoDaTelaDeElemento.Carregando -> Carregando()
                is EstadoDaTelaDeElemento.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                is EstadoDaTelaDeElemento.Sucesso -> ConteudoDoElemento(estado.elemento)
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
private fun ConteudoDoElemento(elemento: ElementoDetalhe) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(elemento.nome, style = MaterialTheme.typography.titleMedium)
                AssistChip(onClick = {}, enabled = false, label = { Text(elemento.tipo.name) })
            }
        }
        elemento.descricao?.let { identidade ->
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Text("IDENTIDADE", style = MaterialTheme.typography.labelSmall)
                        Text(identidade, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
        if (elemento.historicoIdentidade.isNotEmpty()) {
            item { Text("IDENTIDADE — ACRÉSCIMOS POR CAPÍTULO", style = MaterialTheme.typography.labelSmall) }
            items(elemento.historicoIdentidade) { registro ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(registro.descricao, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(12.dp))
                }
            }
        }
        item { Text("HISTÓRICO DE ESTADOS (APARÊNCIA)", style = MaterialTheme.typography.labelSmall) }
        items(elemento.estados, key = { it.id }) { estado -> LinhaDeEstado(estado) }
    }
}

@Composable
private fun LinhaDeEstado(estado: EstadoDoElemento) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Text(estado.descricao, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(12.dp))
    }
}
