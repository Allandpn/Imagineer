package com.allandpn.imagineer.navegacao

import kotlinx.serialization.Serializable

/**
 * Destinos do grafo de navegação, exatamente como especificado no item 7.1
 * da especificação — tipados via `kotlinx.serialization`, sem strings de
 * rota soltas. Cada objeto/classe aqui corresponde a uma tela da Etapa 7.
 */
@Serializable
object Biblioteca

@Serializable
data class Livro(val livroId: Int)

@Serializable
data class Capitulo(val capituloId: Int)

@Serializable
data class Frame(val frameId: Int)

@Serializable
data class Prompt(val frameId: Int, val promptId: Int? = null)

@Serializable
data class ElementosDoLivro(val livroId: Int)

@Serializable
object PerfisDeRenderizacao

@Serializable
object Configuracao
