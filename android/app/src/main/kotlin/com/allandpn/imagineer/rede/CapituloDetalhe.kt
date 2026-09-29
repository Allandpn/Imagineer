package com.allandpn.imagineer.rede

import kotlinx.serialization.Serializable

/**
 * Espelha o schema Pydantic `CapituloDetalhe` (item 6.2) — o capítulo com o
 * texto completo, só usado nesta tela (as listagens usam `CapituloResumo`,
 * sem o texto, porque um livro inteiro em JSON chegaria a megabytes).
 */
@Serializable
data class CapituloDetalhe(
    val id: Int,
    val ordem: Int,
    val titulo: String?,
    val texto: String,
)
