package com.allandpn.imagineer.rede

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Espelha o schema Pydantic `EstadoResumo` (item 6.3) na visão da tela de
 * Elemento — aqui com `id`, pra servir de chave de lista; a versão usada
 * na listagem de elementos (`ElementoResumo.estadoVigente`) não precisa
 * dele e por isso não o tem.
 */
@Serializable
data class EstadoDoElemento(
    val id: Int,
    val descricao: String,
)

/**
 * Espelha o schema Pydantic `HistoricoIdentidadeResumo` (item 3.4f) — o que
 * um capítulo específico acrescentou sobre a identidade do elemento.
 */
@Serializable
data class HistoricoIdentidadeResumo(
    val descricao: String,
)

/**
 * Espelha o schema Pydantic `ElementoDetalhe` (item 6.3) — o elemento com
 * todo o histórico de estados e identidade, em ordem narrativa (item
 * 3.4f). A tela ainda não junta `descricao` (identidade inicial) com
 * `historicoIdentidade` (acréscimos) numa "identidade vigente" só —
 * mostra os dois separados por enquanto.
 */
@Serializable
data class ElementoDetalhe(
    val id: Int,
    val tipo: TipoElemento,
    val nome: String,
    val descricao: String?,
    val estados: List<EstadoDoElemento>,
    @SerialName("historico_identidade") val historicoIdentidade: List<HistoricoIdentidadeResumo> = emptyList(),
)
