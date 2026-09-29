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

/**
 * Não está no snippet original do item 7.1 (que só lista os destinos de
 * topo) — mas o item 7.8 descreve "abrir um elemento" como sua própria
 * tela, então precisa de um destino aqui.
 */
@Serializable
data class ElementoDetalhe(val elementoId: Int)

@Serializable
object PerfisDeRenderizacao

@Serializable
object Configuracao
