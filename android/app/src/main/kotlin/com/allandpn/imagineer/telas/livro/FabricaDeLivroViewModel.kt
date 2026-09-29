package com.allandpn.imagineer.telas.livro

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor

class FabricaDeLivroViewModel(
    private val livroId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return LivroViewModel(livroId, preferencias) as T
    }
}
