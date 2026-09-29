package com.allandpn.imagineer.telas.elemento

import com.allandpn.imagineer.rede.ElementoDetalhe

/** Os estados possíveis da tela de Elemento — detalhe (item 7.8). */
sealed interface EstadoDaTelaDeElemento {
    data object Carregando : EstadoDaTelaDeElemento
    data class Sucesso(val elemento: ElementoDetalhe) : EstadoDaTelaDeElemento
    data class Erro(val mensagem: String) : EstadoDaTelaDeElemento
}
