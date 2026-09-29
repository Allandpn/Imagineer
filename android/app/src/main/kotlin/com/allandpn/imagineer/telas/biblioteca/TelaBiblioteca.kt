package com.allandpn.imagineer.telas.biblioteca

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.allandpn.imagineer.rede.LivroResumo

/**
 * Tela inicial do app (item 7.2). Cobre os estados já desenhados no
 * protótipo (Bloco A, revisão de 29/09/2026): carregando, vazia, com
 * livros, sem servidor configurado e erro — este último ainda genérico,
 * sem distinguir timeout/sem-conexão/Pi-desligado (item 7.0 pede isso, fica
 * pra quando a tela de erro for refinada).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaBiblioteca(
    estado: EstadoDaBiblioteca,
    aoTocarLivro: (Int) -> Unit,
    aoTocarImportar: () -> Unit,
    aoTocarConfiguracao: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Imagineer") },
                actions = {
                    IconButton(onClick = aoTocarConfiguracao) {
                        Icon(Icons.Filled.Settings, contentDescription = "Configuração")
                    }
                },
            )
        },
        floatingActionButton = {
            if (estado is EstadoDaBiblioteca.ComLivros || estado is EstadoDaBiblioteca.Vazia) {
                FloatingActionButton(onClick = aoTocarImportar) {
                    Icon(Icons.Filled.Add, contentDescription = "Importar livro")
                }
            }
        },
    ) { preenchimento ->
        Box(modifier = Modifier.fillMaxSize().padding(preenchimento)) {
            when (estado) {
                is EstadoDaBiblioteca.Carregando -> Carregando()
                is EstadoDaBiblioteca.SemServidorConfigurado -> SemServidorConfigurado(aoTocarConfiguracao)
                is EstadoDaBiblioteca.Vazia -> BibliotecaVazia(aoTocarImportar)
                is EstadoDaBiblioteca.ComLivros -> ListaDeLivros(estado.livros, aoTocarLivro)
                is EstadoDaBiblioteca.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
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
private fun SemServidorConfigurado(aoTocarConfiguracao: () -> Unit) {
    MensagemComBotao(
        titulo = "Configure o endereço do servidor",
        texto = "Antes de usar o app, informe onde o servidor do Imagineer está rodando.",
        textoBotao = "Configurar",
        aoTocarBotao = aoTocarConfiguracao,
    )
}

@Composable
private fun BibliotecaVazia(aoTocarImportar: () -> Unit) {
    MensagemComBotao(
        titulo = "Nenhum livro ainda",
        texto = "Importe seu primeiro EPUB pra começar a catalogar elementos, cenas e prompts.",
        textoBotao = "Importar meu primeiro livro",
        aoTocarBotao = aoTocarImportar,
    )
}

@Composable
private fun ErroDeConexao(mensagem: String, aoTentarDeNovo: () -> Unit) {
    MensagemComBotao(
        titulo = "Não consegui falar com o servidor",
        texto = mensagem,
        textoBotao = "Tentar de novo",
        aoTocarBotao = aoTentarDeNovo,
    )
}

@Composable
private fun MensagemComBotao(
    titulo: String,
    texto: String,
    textoBotao: String,
    aoTocarBotao: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(text = titulo, style = androidx.compose.material3.MaterialTheme.typography.titleMedium)
        Text(text = texto, style = androidx.compose.material3.MaterialTheme.typography.bodyMedium)
        Button(onClick = aoTocarBotao, modifier = Modifier.padding(top = 16.dp)) {
            Text(textoBotao)
        }
    }
}

@Composable
private fun ListaDeLivros(livros: List<LivroResumo>, aoTocarLivro: (Int) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(livros, key = { it.id }) { livro ->
            CardDeLivro(livro, onClick = { aoTocarLivro(livro.id) })
        }
    }
}

@Composable
private fun CardDeLivro(livro: LivroResumo, onClick: () -> Unit) {
    Card(onClick = onClick, modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(text = livro.titulo, style = androidx.compose.material3.MaterialTheme.typography.titleSmall)
            livro.autor?.let { Text(text = it, style = androidx.compose.material3.MaterialTheme.typography.bodySmall) }
            val sufixoIgnorados = if (livro.capitulosIgnorados > 0) {
                " · ${livro.capitulosIgnorados} ignorados"
            } else {
                ""
            }
            Text(
                text = "${livro.totalDeCapitulos} capítulos$sufixoIgnorados",
                style = androidx.compose.material3.MaterialTheme.typography.bodySmall,
            )
        }
    }
}
