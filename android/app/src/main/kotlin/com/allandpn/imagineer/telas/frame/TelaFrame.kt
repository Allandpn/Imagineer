package com.allandpn.imagineer.telas.frame

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.allandpn.imagineer.rede.EstadoComElemento
import com.allandpn.imagineer.rede.FrameDetalhe
import com.allandpn.imagineer.rede.TipoDeFrame

/**
 * Tela de Frame (item 7.6) — um retrato solo ou uma cena, distinção que
 * não é só cosmética (um retrato tem no máximo um elemento marcado, item
 * 6.4). Só leitura por enquanto: editar, marcar/desmarcar estados, apagar
 * e gerar prompt (tudo especificado no item 7.6) são a próxima fatia.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaFrame(
    estado: EstadoDoFrame,
    aoVoltar: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Frame") },
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
                is EstadoDoFrame.Carregando -> Carregando()
                is EstadoDoFrame.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                is EstadoDoFrame.Sucesso -> ConteudoDoFrame(estado.frame)
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
private fun ConteudoDoFrame(frame: FrameDetalhe) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            AssistChip(onClick = {}, enabled = false, label = { Text(rotuloDoTipo(frame.tipo)) })
        }
        item {
            Column {
                Text("TÍTULO", style = MaterialTheme.typography.labelSmall)
                Text(frame.titulo, style = MaterialTheme.typography.titleMedium)
            }
        }
        // Descrição e atributos situacionais só existem pra cena (item 7.6) —
        // um retrato não tem, de propósito, porque não há "cenário" pra descrever.
        if (frame.tipo == TipoDeFrame.CENA) {
            frame.descricao?.let { descricao ->
                item {
                    Column {
                        Text("DESCRIÇÃO", style = MaterialTheme.typography.labelSmall)
                        Text(descricao, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
            item { LinhaDeAtributos(frame.horario, frame.clima, frame.humor) }
        }
        item {
            Text(
                if (frame.tipo == TipoDeFrame.PERSONAGEM) "ELEMENTO DESTE RETRATO" else "ELEMENTOS NESTA CENA",
                style = MaterialTheme.typography.labelSmall,
            )
        }
        items(frame.elementos, key = { it.estadoId }) { estado -> LinhaDeEstado(estado) }
    }
}

@Composable
private fun LinhaDeAtributos(horario: String?, clima: String?, humor: String?) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        AtributoSituacional("Horário", horario, Modifier.weight(1f))
        AtributoSituacional("Clima", clima, Modifier.weight(1f))
        AtributoSituacional("Humor", humor, Modifier.weight(1f))
    }
}

@Composable
private fun AtributoSituacional(rotulo: String, valor: String?, modifier: Modifier = Modifier) {
    Column(modifier = modifier) {
        Text(rotulo, style = MaterialTheme.typography.labelSmall)
        Text(valor ?: "—", style = MaterialTheme.typography.bodySmall)
    }
}

private fun rotuloDoTipo(tipo: TipoDeFrame): String = when (tipo) {
    TipoDeFrame.PERSONAGEM -> "PERSONAGEM"
    TipoDeFrame.CENA -> "CENA"
}

@Composable
private fun LinhaDeEstado(estado: EstadoComElemento) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(estado.nome, style = MaterialTheme.typography.bodyLarge)
            Text(
                estado.descricao,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
