package com.allandpn.imagineer.telas.prompt

import com.allandpn.imagineer.rede.PromptDetalhe

/** Os estados possíveis da tela de Prompt (item 7.7), modo "ver resultado existente". */
sealed interface EstadoDoPrompt {
    data object Carregando : EstadoDoPrompt
    data class Sucesso(val prompt: PromptDetalhe) : EstadoDoPrompt
    data class Erro(val mensagem: String) : EstadoDoPrompt
}
