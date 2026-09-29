package com.allandpn.imagineer.telas.elementos

import com.allandpn.imagineer.rede.ElementoResumo

/** Os estados possíveis da tela de Elementos do livro (item 7.8). */
sealed interface EstadoDosElementos {
    data object Carregando : EstadoDosElementos
    data object Vazia : EstadoDosElementos
    data class ComElementos(val elementos: List<ElementoResumo>) : EstadoDosElementos
    data class Erro(val mensagem: String) : EstadoDosElementos
}
