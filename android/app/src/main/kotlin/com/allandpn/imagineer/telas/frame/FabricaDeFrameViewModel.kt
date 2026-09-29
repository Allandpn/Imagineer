package com.allandpn.imagineer.telas.frame

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor

class FabricaDeFrameViewModel(
    private val frameId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return FrameViewModel(frameId, preferencias) as T
    }
}
