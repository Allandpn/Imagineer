package com.allandpn.imagineer.telas.elementos

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioElementos
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.ElementoResumo
import com.allandpn.imagineer.rede.FabricaDeApi
import com.allandpn.imagineer.rede.TipoElemento
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega os elementos de um livro (item 7.8) e filtra por tipo. O filtro
 * é local (a lista inteira já veio do servidor) — separar por tipo é
 * exibição, não justifica uma chamada de rede por aba. Isso muda quando a
 * busca (pendência de prioridade da Etapa 8) entrar nesta tela.
 */
class ElementosViewModel(
    private val livroId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private var todosOsElementos: List<ElementoResumo> = emptyList()

    private val _estado = MutableStateFlow<EstadoDosElementos>(EstadoDosElementos.Carregando)
    val estado: StateFlow<EstadoDosElementos> = _estado

    private val _tipoSelecionado = MutableStateFlow<TipoElemento?>(null)
    val tipoSelecionado: StateFlow<TipoElemento?> = _tipoSelecionado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDosElementos.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDosElementos.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                todosOsElementos = RepositorioElementos(criarApi(endereco)).listarElementos(livroId)
                aplicarFiltro()
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDosElementos.Erro(erro.message ?: "Não consegui falar com o servidor.")
            }
        }
    }

    fun filtrarPorTipo(tipo: TipoElemento?) {
        _tipoSelecionado.value = tipo
        aplicarFiltro()
    }

    private fun aplicarFiltro() {
        val filtrados = todosOsElementos.filter { elemento ->
            _tipoSelecionado.value == null || elemento.tipo == _tipoSelecionado.value
        }
        _estado.value = if (filtrados.isEmpty()) {
            EstadoDosElementos.Vazia
        } else {
            EstadoDosElementos.ComElementos(filtrados)
        }
    }
}
