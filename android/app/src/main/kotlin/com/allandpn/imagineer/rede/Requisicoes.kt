package com.allandpn.imagineer.rede

import kotlinx.serialization.Serializable

/**
 * Corpos de requisição de ajuste parcial (`PATCH`). Todos os campos são
 * opcionais e ficam de fora do JSON quando `null` (comportamento padrão do
 * `kotlinx.serialization`, sem precisar configurar nada) — o backend usa
 * `exclude_unset` (item 6.2/6.3): só o que veio no corpo é alterado, então
 * mandar `null` explícito apagaria o campo por engano.
 */
@Serializable
data class CapituloAjusteRequest(
    val ignorado: Boolean? = null,
)
