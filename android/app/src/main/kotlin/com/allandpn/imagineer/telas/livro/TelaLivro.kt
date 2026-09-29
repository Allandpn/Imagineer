package com.allandpn.imagineer.telas.livro

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
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Palette
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
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.allandpn.imagineer.rede.CapituloResumo
import com.allandpn.imagineer.rede.LivroDetalhe

/**
 * Tela de Livro (item 7.4) — estrutura de capítulos e ponto de entrada
 * pro que pertence ao livro. Só leitura e navegação por enquanto: editar
 * metadados, apagar o livro e alternar "ignorado" por capítulo (menu de
 * três pontos e ícones por linha, já desenhados no wireframe) entram num
 * próximo incremento, pra este ficar pequeno e revisável.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaLivro(
    estado: EstadoDoLivro,
    aoVoltar: () -> Unit,
    aoTocarCapitulo: (Int) -> Unit,
    aoTocarElementos: () -> Unit,
    aoTocarPerfis: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    val titulo = (estado as? EstadoDoLivro.Sucesso)?.livro?.titulo ?: "Livro"

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(titulo, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    IconButton(onClick = aoVoltar) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Voltar")
                    }
                },
                actions = {
                    IconButton(onClick = aoTocarElementos) {
                        Icon(Icons.Filled.AccountCircle, contentDescription = "Elementos do livro")
                    }
                    IconButton(onClick = aoTocarPerfis) {
                        Icon(Icons.Filled.Palette, contentDescription = "Perfis de renderização")
                    }
                },
            )
        },
    ) { preenchimento ->
        Box(modifier = Modifier.fillMaxSize().padding(preenchimento)) {
            when (estado) {
                is EstadoDoLivro.Carregando -> Carregando()
                is EstadoDoLivro.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                is EstadoDoLivro.Sucesso -> ConteudoDoLivro(estado.livro, aoTocarCapitulo)
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
private fun ConteudoDoLivro(livro: LivroDetalhe, aoTocarCapitulo: (Int) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { CardDeMetadados(livro) }
        item {
            Text(
                "CAPÍTULOS",
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        items(livro.capitulos, key = { it.id }) { capitulo ->
            LinhaDeCapitulo(capitulo, onClick = { aoTocarCapitulo(capitulo.id) })
        }
    }
}

@Composable
private fun CardDeMetadados(livro: LivroDetalhe) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(livro.titulo, style = MaterialTheme.typography.titleMedium)
            livro.autor?.let {
                LinhaDeMetadado("Autor", it)
            }
            livro.idioma?.let {
                LinhaDeMetadado("Idioma", it)
            }
            LinhaDeMetadado(
                "Perfil padrão",
                if (livro.perfilRenderizacaoPadraoId == null) "nenhum definido" else "definido",
            )
        }
    }
}

@Composable
private fun LinhaDeMetadado(rotulo: String, valor: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(rotulo, style = MaterialTheme.typography.bodySmall)
        Text(valor, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun LinhaDeCapitulo(capitulo: CapituloResumo, onClick: () -> Unit) {
    val tituloDeExibicao = capitulo.titulo ?: "Capítulo ${capitulo.ordem}"
    val ehReserva = capitulo.titulo == null

    Card(
        onClick = onClick,
        enabled = !capitulo.ignorado,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("${capitulo.ordem}", style = MaterialTheme.typography.bodySmall)
            Text(
                tituloDeExibicao,
                style = if (ehReserva) {
                    MaterialTheme.typography.bodyLarge.copy(fontStyle = FontStyle.Italic)
                } else {
                    MaterialTheme.typography.bodyLarge
                },
                modifier = Modifier.weight(1f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (capitulo.ignorado) {
                Text("ignorado", style = MaterialTheme.typography.labelSmall)
            } else if (capitulo.sugestoesPendentes > 0) {
                Text("${capitulo.sugestoesPendentes} pendentes", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}
