package com.allandpn.imagineer.telas.capitulo

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioCapitulos
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega o texto de um capítulo (item 7.5) — primeira fatia desta tela,
 * só leitura. "Analisar com IA", sugestões, estados vigentes e criar frame
 * (todos já especificados no item 7.5) entram em incrementos seguintes.
 */
class CapituloViewModel(
    private val capituloId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDoCapitulo>(EstadoDoCapitulo.Carregando)
    val estado: StateFlow<EstadoDoCapitulo> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDoCapitulo.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDoCapitulo.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                val capitulo = RepositorioCapitulos(criarApi(endereco)).obterCapitulo(capituloId)
                _estado.value = EstadoDoCapitulo.Sucesso(capitulo)
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDoCapitulo.Erro(
                    erro.message ?: "Não consegui falar com o servidor."
                )
            }
        }
    }
}
