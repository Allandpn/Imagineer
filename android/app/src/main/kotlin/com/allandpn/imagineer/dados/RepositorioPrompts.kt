package com.allandpn.imagineer.dados

import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.PromptDetalhe

class RepositorioPrompts(private val api: ApiImagineer) {
    suspend fun obterPrompt(promptId: Int): PromptDetalhe = api.obterPrompt(promptId)
}
