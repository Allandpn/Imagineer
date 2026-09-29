package com.allandpn.imagineer.telas.perfis

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor

class FabricaDePerfisViewModel(
    private val preferencias: ProvedorDeEnderecoDoServidor,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return PerfisViewModel(preferencias) as T
    }
}
