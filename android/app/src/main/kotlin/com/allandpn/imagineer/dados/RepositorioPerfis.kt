package com.allandpn.imagineer.dados

import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.PerfilRenderizacao

class RepositorioPerfis(private val api: ApiImagineer) {
    suspend fun listarPerfis(): List<PerfilRenderizacao> = api.listarPerfis()
}
