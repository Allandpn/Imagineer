package com.allandpn.imagineer.telas.frame

import com.allandpn.imagineer.rede.FrameDetalhe

/** Os estados possíveis da tela de Frame (item 7.6). */
sealed interface EstadoDoFrame {
    data object Carregando : EstadoDoFrame
    data class Sucesso(val frame: FrameDetalhe) : EstadoDoFrame
    data class Erro(val mensagem: String) : EstadoDoFrame
}
