package com.allandpn.imagineer.telas.perfis

import com.allandpn.imagineer.rede.PerfilRenderizacao

/** Os estados possíveis da tela de Perfis de renderização (item 7.9). */
sealed interface EstadoDosPerfis {
    data object Carregando : EstadoDosPerfis
    data object Vazia : EstadoDosPerfis
    data class ComPerfis(val perfis: List<PerfilRenderizacao>) : EstadoDosPerfis
    data class Erro(val mensagem: String) : EstadoDosPerfis
}
