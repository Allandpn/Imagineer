package com.allandpn.imagineer.telas.biblioteca

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor

/** Sem Hilt (item 7.0) — cada ViewModel que precisa de dependências ganha sua própria fábrica simples. */
class FabricaDeBibliotecaViewModel(
    private val preferencias: ProvedorDeEnderecoDoServidor,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return BibliotecaViewModel(preferencias) as T
    }
}
