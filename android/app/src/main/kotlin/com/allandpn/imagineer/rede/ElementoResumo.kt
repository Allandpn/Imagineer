package com.allandpn.imagineer.rede

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Espelha o enum Python `TipoElemento` (item 3.3) — mesmos nomes, então nenhum `@SerialName` é preciso. */
@Serializable
enum class TipoElemento {
    PERSONAGEM, AMBIENTE, OBJETO, CRIATURA, GRUPO, VEICULO, EDIFICACAO
}

/**
 * Espelha o schema Pydantic `EstadoResumo` (item 6.3) — só `descricao`
 * (a aparência em si, o que entra no prompt) é usado nesta tela; os
 * outros campos crescem quando a tela de Elemento (detalhe) precisar.
 */
@Serializable
data class EstadoResumo(
    val descricao: String,
)

/**
 * Espelha o schema Pydantic `ElementoResumo` (item 6.3) — um elemento na
 * listagem (item 7.8), com o estado vigente no ponto consultado.
 * `descricao` aqui é a **identidade** (quem/o que é) — diferente de
 * `estado_vigente.descricao`, que é a **aparência** (o que entra no
 * prompt); a lista mostra a aparência, por isso o campo de identidade
 * ainda não é usado nesta tela.
 */
@Serializable
data class ElementoResumo(
    val id: Int,
    val tipo: TipoElemento,
    val nome: String,
    @SerialName("estado_vigente") val estadoVigente: EstadoResumo?,
)
