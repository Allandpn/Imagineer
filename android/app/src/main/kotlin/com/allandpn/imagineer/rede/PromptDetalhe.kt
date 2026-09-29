package com.allandpn.imagineer.rede

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Espelha o schema Pydantic `ImagemResumo` (item 6.6) — uma imagem do
 * catálogo. O arquivo em si vem por `GET /imagens/{id}/arquivo`, só o id
 * é usado por enquanto (exibir a imagem de verdade é a próxima fatia,
 * precisa de biblioteca de carregamento de imagem, ainda não adicionada).
 */
@Serializable
data class ImagemResumo(
    val id: Int,
)

/**
 * Espelha o schema Pydantic `PromptDetalhe` (item 6.6) — só os campos que
 * a tela de Prompt (7.7) usa hoje.
 */
@Serializable
data class PromptDetalhe(
    val id: Int,
    val texto: String,
    val avaliacao: String?,
    val imagens: List<ImagemResumo>,
    @SerialName("referencias_visuais") val referenciasVisuais: List<ImagemResumo>,
)
