package com.allandpn.imagineer.telas.configuracao

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * Versão mínima da tela de Configuração (item 7.10) — só o endereço do
 * servidor por enquanto, porque é o único dado sem o qual o app não
 * funciona (item 7.0). Chave de API, modelos e prioridade de IA entram
 * quando as telas que os usam existirem de verdade.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaConfiguracao(
    enderecoAtual: String,
    aoVoltar: () -> Unit,
    aoSalvar: (String) -> Unit,
) {
    var endereco by remember { mutableStateOf(enderecoAtual) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Configuração") },
                navigationIcon = {
                    IconButton(onClick = aoVoltar) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Voltar")
                    }
                },
            )
        },
    ) { preenchimento ->
        Column(modifier = Modifier.fillMaxSize().padding(preenchimento).padding(16.dp)) {
            Text("Endereço do servidor")
            OutlinedTextField(
                value = endereco,
                onValueChange = { endereco = it },
                placeholder = { Text("ex.: http://100.87.12.4:8000") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 16.dp),
                singleLine = true,
            )
            Button(onClick = { aoSalvar(endereco) }, modifier = Modifier.fillMaxWidth()) {
                Text("Salvar")
            }
        }
    }
}
