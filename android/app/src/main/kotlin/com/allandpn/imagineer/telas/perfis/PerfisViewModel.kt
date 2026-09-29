package com.allandpn.imagineer.telas.perfis

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioPerfis
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega a lista de perfis de renderização (item 7.9) — compartilhada
 * entre livros, sem depender de nenhum livro específico. Só leitura por
 * enquanto: criar, editar, apagar e sugerir com IA (todos especificados no
 * item 7.9) entram em incrementos seguintes.
 */
class PerfisViewModel(
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDosPerfis>(EstadoDosPerfis.Carregando)
    val estado: StateFlow<EstadoDosPerfis> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDosPerfis.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDosPerfis.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                val perfis = RepositorioPerfis(criarApi(endereco)).listarPerfis()
                _estado.value = if (perfis.isEmpty()) {
                    EstadoDosPerfis.Vazia
                } else {
                    EstadoDosPerfis.ComPerfis(perfis)
                }
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDosPerfis.Erro(erro.message ?: "Não consegui falar com o servidor.")
            }
        }
    }
}
