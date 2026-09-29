package com.allandpn.imagineer.dados

import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FrameDetalhe

class RepositorioFrames(private val api: ApiImagineer) {
    suspend fun obterFrame(frameId: Int): FrameDetalhe = api.obterFrame(frameId)
}
