package com.allandpn.imagineer.rede

import kotlinx.serialization.Serializable

/**
 * Espelha o schema Pydantic `PerfilRenderizacao` (item 6.5) — todos os
 * campos de estilo são opcionais menos `nome`, porque cada ferramenta de
 * imagem externa entende um subconjunto diferente (item 3.4c).
 */
@Serializable
data class PerfilRenderizacao(
    val id: Int,
    val nome: String,
    val estilo: String?,
    val iluminacao: String?,
    val paleta: String?,
)
