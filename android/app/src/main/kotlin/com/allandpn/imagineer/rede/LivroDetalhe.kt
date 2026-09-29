package com.allandpn.imagineer.rede

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Espelha o schema Pydantic `CapituloResumo` (item 6.2) — só os campos que
 * a tela de Livro (7.4) mostra na lista, sem o texto do capítulo.
 */
@Serializable
data class CapituloResumo(
    val id: Int,
    val ordem: Int,
    val titulo: String?,
    val ignorado: Boolean,
    @SerialName("sugestoes_pendentes") val sugestoesPendentes: Int,
)

/**
 * Espelha o schema Pydantic `LivroDetalhe` (item 6.2) — só os campos que a
 * tela de Livro (7.4) usa hoje. `LivroDetalhe` tem mais campos que este
 * (item 3.1/6.2); crescem aqui quando alguma tela precisar deles, não antes.
 */
@Serializable
data class LivroDetalhe(
    val id: Int,
    val titulo: String,
    val autor: String?,
    val idioma: String?,
    @SerialName("perfil_renderizacao_padrao_id") val perfilRenderizacaoPadraoId: Int?,
    val capitulos: List<CapituloResumo>,
)
