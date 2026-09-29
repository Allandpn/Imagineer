package com.allandpn.imagineer.armazenamento

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "preferencias_imagineer")

/**
 * Só a leitura do endereço do servidor, como interface — é a costura que
 * deixa o [com.allandpn.imagineer.telas.biblioteca.BibliotecaViewModel]
 * testável em JVM puro (sem `Context`/DataStore de verdade), trocando esta
 * interface por uma versão falsa no teste.
 */
interface ProvedorDeEnderecoDoServidor {
    val enderecoDoServidor: Flow<String?>
}

/**
 * Guarda o endereço do servidor localmente (item 7.0 — "Armazenamento
 * local"). É um dado comum, sem sensibilidade, por isso usa DataStore
 * normal (texto plano) — diferente da chave de API do OpenRouter, que é um
 * segredo e vai para `EncryptedSharedPreferences` quando essa tela existir
 * (ainda não implementada, ver item 7.10).
 */
class PreferenciasApp(private val contexto: Context) : ProvedorDeEnderecoDoServidor {
    private val chaveEnderecoDoServidor = stringPreferencesKey("endereco_do_servidor")

    override val enderecoDoServidor: Flow<String?> =
        contexto.dataStore.data.map { preferencias -> preferencias[chaveEnderecoDoServidor] }

    suspend fun salvarEnderecoDoServidor(endereco: String) {
        contexto.dataStore.edit { preferencias -> preferencias[chaveEnderecoDoServidor] = endereco }
    }
}
