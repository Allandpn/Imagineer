package com.allandpn.imagineer.telas.biblioteca

import com.allandpn.imagineer.rede.LivroResumo

/**
 * Os estados possíveis da tela de Biblioteca (item 7.2), incluindo o
 * "vazio" (convite a importar, não é erro) e a falta de servidor
 * configurado (item 7.0 — primeira vez que o app abre).
 */
sealed interface EstadoDaBiblioteca {
    data object Carregando : EstadoDaBiblioteca
    data object SemServidorConfigurado : EstadoDaBiblioteca
    data object Vazia : EstadoDaBiblioteca
    data class ComLivros(val livros: List<LivroResumo>) : EstadoDaBiblioteca
    data class Erro(val mensagem: String) : EstadoDaBiblioteca
}
