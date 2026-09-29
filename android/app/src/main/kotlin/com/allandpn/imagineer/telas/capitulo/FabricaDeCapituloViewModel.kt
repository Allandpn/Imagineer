package com.allandpn.imagineer.telas.capitulo

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor

class FabricaDeCapituloViewModel(
    private val capituloId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return CapituloViewModel(capituloId, preferencias) as T
    }
}
