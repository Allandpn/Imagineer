package com.allandpn.imagineer.rede

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Espelha o schema Pydantic `LivroResumo` do backend (item 6.2 da
 * especificação) — um livro na listagem da Biblioteca (tela 7.2).
 *
 * Os nomes dos campos na API vêm em `snake_case` (convenção Python); aqui
 * usamos `camelCase` (convenção Kotlin) e mapeamos com `@SerialName`.
 */
@Serializable
data class LivroResumo(
    val id: Int,
    val titulo: String,
    val autor: String?,
    val idioma: String?,
    @SerialName("nome_arquivo") val nomeArquivo: String,
    @SerialName("total_de_capitulos") val totalDeCapitulos: Int,
    @SerialName("capitulos_ignorados") val capitulosIgnorados: Int,
)
