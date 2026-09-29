package com.allandpn.imagineer.dados

import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.ElementoDetalhe
import com.allandpn.imagineer.rede.ElementoResumo

class RepositorioElementos(private val api: ApiImagineer) {
    suspend fun listarElementos(livroId: Int): List<ElementoResumo> = api.listarElementos(livroId)

    suspend fun obterElemento(elementoId: Int): ElementoDetalhe = api.obterElemento(elementoId)
}
