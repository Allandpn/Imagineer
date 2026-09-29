package com.allandpn.imagineer.dados

import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.CapituloAjusteRequest
import com.allandpn.imagineer.rede.CapituloDetalhe
import com.allandpn.imagineer.rede.CapituloResumo

class RepositorioCapitulos(private val api: ApiImagineer) {
    suspend fun obterCapitulo(capituloId: Int): CapituloDetalhe = api.obterCapitulo(capituloId)

    suspend fun alternarIgnorado(capituloId: Int, ignorado: Boolean): CapituloResumo =
        api.ajustarCapitulo(capituloId, CapituloAjusteRequest(ignorado = ignorado))
}
