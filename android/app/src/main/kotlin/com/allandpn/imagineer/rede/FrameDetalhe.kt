package com.allandpn.imagineer.rede

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Espelha o enum Python `TipoDeFrame` (item 4.4) — retrato solo de um
 * elemento ou cena com um ou mais. Não editável depois de criado.
 */
@Serializable
enum class TipoDeFrame { PERSONAGEM, CENA }

/**
 * Espelha o schema Pydantic `EstadoComElemento` (item 6.4) — um estado de
 * elemento já com a identidade de quem ele descreve, pra tela não ter que
 * remontar isso.
 */
@Serializable
data class EstadoComElemento(
    @SerialName("estado_id") val estadoId: Int,
    @SerialName("elemento_id") val elementoId: Int,
    val tipo: TipoElemento,
    val nome: String,
    val descricao: String,
)

/**
 * Espelha o schema Pydantic `FrameDetalhe` (item 6.4) — só os campos que a
 * tela de Frame (7.6) mostra hoje.
 */
@Serializable
data class FrameDetalhe(
    val id: Int,
    val tipo: TipoDeFrame,
    val titulo: String,
    val descricao: String?,
    val horario: String?,
    val clima: String?,
    val humor: String?,
    val elementos: List<EstadoComElemento>,
)
