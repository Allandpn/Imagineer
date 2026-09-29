package com.allandpn.imagineer.telas.elemento

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioElementos
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega o histórico completo de um elemento (item 7.8) — a "ficha" do
 * personagem ao longo do livro. Só leitura por enquanto: editar identidade
 * e apagar (especificados no mesmo item) entram na próxima fatia.
 */
class ElementoViewModel(
    private val elementoId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDaTelaDeElemento>(EstadoDaTelaDeElemento.Carregando)
    val estado: StateFlow<EstadoDaTelaDeElemento> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDaTelaDeElemento.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDaTelaDeElemento.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                val elemento = RepositorioElementos(criarApi(endereco)).obterElemento(elementoId)
                _estado.value = EstadoDaTelaDeElemento.Sucesso(elemento)
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDaTelaDeElemento.Erro(erro.message ?: "Não consegui falar com o servidor.")
            }
        }
    }
}
