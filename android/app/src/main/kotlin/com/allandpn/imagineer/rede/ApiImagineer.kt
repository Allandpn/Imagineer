package com.allandpn.imagineer.rede

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.Path

/**
 * Interface Retrofit da API do Imagineer. Cresce uma rota por vez, junto
 * com a tela que a usa — sem adiantar rotas que nenhuma tela ainda chama.
 */
interface ApiImagineer {
    @GET("livros")
    suspend fun listarLivros(): List<LivroResumo>

    @GET("livros/{id}")
    suspend fun obterLivro(@Path("id") livroId: Int): LivroDetalhe

    @GET("capitulos/{id}")
    suspend fun obterCapitulo(@Path("id") capituloId: Int): CapituloDetalhe

    @DELETE("livros/{id}")
    suspend fun apagarLivro(@Path("id") livroId: Int)

    @PATCH("capitulos/{id}")
    suspend fun ajustarCapitulo(
        @Path("id") capituloId: Int,
        @Body ajuste: CapituloAjusteRequest,
    ): CapituloResumo

    @GET("livros/{id}/elementos")
    suspend fun listarElementos(@Path("id") livroId: Int): List<ElementoResumo>
}
