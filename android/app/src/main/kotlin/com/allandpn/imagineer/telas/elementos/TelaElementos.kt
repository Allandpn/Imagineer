package com.allandpn.imagineer.telas.elementos

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
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
import com.allandpn.imagineer.rede.ElementoResumo
import com.allandpn.imagineer.rede.TipoElemento

/**
 * Tela de Elementos do livro (item 7.8) — consulta geral, fora do fluxo
 * capítulo a capítulo. Só listagem e filtro por tipo por enquanto; abrir
 * um elemento (histórico de estados, editar, apagar) é a próxima fatia.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaElementos(
    estado: EstadoDosElementos,
    tipoSelecionado: TipoElemento?,
    aoVoltar: () -> Unit,
    aoFiltrar: (TipoElemento?) -> Unit,
    aoTentarDeNovo: () -> Unit,
    aoTocarElemento: (Int) -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Elementos do livro") },
                navigationIcon = {
                    IconButton(onClick = aoVoltar) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Voltar")
                    }
                },
            )
        },
    ) { preenchimento ->
        Column(modifier = Modifier.fillMaxSize().padding(preenchimento)) {
            ChipsDeTipo(tipoSelecionado, aoFiltrar)

            Box(modifier = Modifier.fillMaxSize()) {
                when (estado) {
                    is EstadoDosElementos.Carregando -> Carregando()
                    is EstadoDosElementos.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                    is EstadoDosElementos.Vazia -> ElementosVazia()
                    is EstadoDosElementos.ComElementos -> ListaDeElementos(estado.elementos, aoTocarElemento)
                }
            }
        }
    }
}

private val TIPOS_EM_ORDEM = listOf(
    TipoElemento.PERSONAGEM,
    TipoElemento.AMBIENTE,
    TipoElemento.OBJETO,
    TipoElemento.CRIATURA,
    TipoElemento.GRUPO,
    TipoElemento.VEICULO,
    TipoElemento.EDIFICACAO,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChipsDeTipo(tipoSelecionado: TipoElemento?, aoFiltrar: (TipoElemento?) -> Unit) {
    LazyRow(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        item {
            FilterChip(selected = tipoSelecionado == null, onClick = { aoFiltrar(null) }, label = { Text("Todos") })
        }
        items(TIPOS_EM_ORDEM) { tipo ->
            FilterChip(
                selected = tipoSelecionado == tipo,
                onClick = { aoFiltrar(tipo) },
                label = { Text(rotuloDoTipo(tipo)) },
            )
        }
    }
}

private fun rotuloDoTipo(tipo: TipoElemento): String = when (tipo) {
    TipoElemento.PERSONAGEM -> "Personagem"
    TipoElemento.AMBIENTE -> "Ambiente"
    TipoElemento.OBJETO -> "Objeto"
    TipoElemento.CRIATURA -> "Criatura"
    TipoElemento.GRUPO -> "Grupo"
    TipoElemento.VEICULO -> "Veículo"
    TipoElemento.EDIFICACAO -> "Edificação"
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
private fun ElementosVazia() {
    Box(modifier = Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text("Nenhum elemento encontrado.", style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun ListaDeElementos(elementos: List<ElementoResumo>, aoTocarElemento: (Int) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(elementos, key = { it.id }) { elemento ->
            LinhaDeElemento(elemento, onClick = { aoTocarElemento(elemento.id) })
        }
    }
}

@Composable
private fun LinhaDeElemento(elemento: ElementoResumo, onClick: () -> Unit) {
    Card(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "${elemento.nome} · ${rotuloDoTipo(elemento.tipo)}",
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    elemento.estadoVigente?.descricao ?: "Ainda não apareceu.",
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
