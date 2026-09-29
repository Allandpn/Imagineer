package com.allandpn.imagineer.telas.capitulo

import com.allandpn.imagineer.rede.CapituloDetalhe

/** Os estados possíveis da tela de Capítulo (item 7.5). */
sealed interface EstadoDoCapitulo {
    data object Carregando : EstadoDoCapitulo
    data class Sucesso(val capitulo: CapituloDetalhe) : EstadoDoCapitulo
    data class Erro(val mensagem: String) : EstadoDoCapitulo
}
