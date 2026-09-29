package com.allandpn.imagineer.rede

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit

/**
 * Monta um [ApiImagineer] apontando para o endereço do servidor configurado
 * pelo usuário (tela de Configuração, item 7.10) — o endereço pode mudar em
 * tempo de execução, então esta fábrica é chamada de novo sempre que ele muda,
 * em vez de guardar um cliente único global.
 */
object FabricaDeApi {
    private val json = Json { ignoreUnknownKeys = true }

    fun criar(enderecoDoServidor: String): ApiImagineer {
        val urlBase = if (enderecoDoServidor.endsWith("/")) {
            enderecoDoServidor
        } else {
            "$enderecoDoServidor/"
        }

        val cliente = OkHttpClient.Builder().build()

        return Retrofit.Builder()
            .baseUrl(urlBase)
            .client(cliente)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(ApiImagineer::class.java)
    }
}
