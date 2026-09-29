package com.allandpn.imagineer.telas.prompt

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.allandpn.imagineer.rede.PromptDetalhe

/**
 * Tela de Prompt (item 7.7), modo "ver resultado existente" — o texto já
 * gerado, com "Copiar" e "Abrir no Gemini" (decisão registrada no item 7.7:
 * `Intent.ACTION_SEND`, sem API paga — ver ESPECIFICACAO.md, 29/09/2026).
 * Gerar um prompt novo, o indicador de carregamento, e ver as imagens de
 * verdade (precisa de biblioteca de carregamento de imagem) são a próxima
 * fatia.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaPrompt(
    estado: EstadoDoPrompt,
    aoVoltar: () -> Unit,
    aoTentarDeNovo: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Prompt") },
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
                is EstadoDoPrompt.Carregando -> Carregando()
                is EstadoDoPrompt.Erro -> ErroDeConexao(estado.mensagem, aoTentarDeNovo)
                is EstadoDoPrompt.Sucesso -> ConteudoDoPrompt(estado.prompt)
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
private fun ConteudoDoPrompt(prompt: PromptDetalhe) {
    val contexto = LocalContext.current

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("PROMPT GERADO", style = MaterialTheme.typography.labelSmall)
                Text(prompt.texto, style = MaterialTheme.typography.bodyMedium, fontFamily = FontFamily.Monospace)

                if (prompt.referenciasVisuais.isEmpty()) {
                    Text(
                        "⚠ Nenhum dos elementos desta cena tem referência visual ainda — a " +
                            "consistência entre gerações pode variar mais.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    Text(
                        "⚠ ${prompt.referenciasVisuais.size} referência(s) visual(is) disponível(is) — " +
                            "anexe também na ferramenta externa, pra manter a aparência consistente.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }

                Button(onClick = { copiarParaAreaDeTransferencia(contexto, prompt.texto) }) {
                    Text("Copiar")
                }

                OutlinedButton(onClick = { abrirNoGemini(contexto, prompt.texto) }) {
                    Text("Abrir no Gemini")
                }
            }
        }

        Text(
            "${prompt.imagens.size} imagem(ns) importada(s)",
            style = MaterialTheme.typography.labelSmall,
        )

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(14.dp)) {
                Text("AVALIAÇÃO", style = MaterialTheme.typography.labelSmall)
                Text(
                    prompt.avaliacao ?: "Ainda não avaliada.",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

private fun copiarParaAreaDeTransferencia(contexto: Context, textoDoPrompt: String) {
    val gerenciador = contexto.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    gerenciador.setPrimaryClip(ClipData.newPlainText("Prompt", textoDoPrompt))
}

/** Decisão registrada no item 7.7: compartilhamento nativo, sem API do Gemini. */
private fun abrirNoGemini(contexto: Context, textoDoPrompt: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, textoDoPrompt)
    }
    contexto.startActivity(Intent.createChooser(intent, "Abrir com"))
}
