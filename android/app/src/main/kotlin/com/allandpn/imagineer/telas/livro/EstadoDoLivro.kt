package com.allandpn.imagineer.telas.livro

import com.allandpn.imagineer.rede.LivroDetalhe

/** Os estados possíveis da tela de Livro (item 7.4). */
sealed interface EstadoDoLivro {
    data object Carregando : EstadoDoLivro
    data class Sucesso(val livro: LivroDetalhe) : EstadoDoLivro
    data class Erro(val mensagem: String) : EstadoDoLivro
}
