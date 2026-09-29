package com.allandpn.imagineer.telas.prompt

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioPrompts
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega um prompt já gerado (item 7.7, modo "ver resultado existente" —
 * quando `promptId` vem preenchido no destino de navegação, item 7.1).
 * Gerar um prompt novo (`POST /frames/{id}/prompts`, com o indicador de
 * carregamento especificado no item 7.7) é a próxima fatia; hoje o app só
 * chega aqui a partir do histórico de tentativas de um frame.
 */
class PromptViewModel(
    private val promptId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDoPrompt>(EstadoDoPrompt.Carregando)
    val estado: StateFlow<EstadoDoPrompt> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDoPrompt.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDoPrompt.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                val prompt = RepositorioPrompts(criarApi(endereco)).obterPrompt(promptId)
                _estado.value = EstadoDoPrompt.Sucesso(prompt)
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDoPrompt.Erro(erro.message ?: "Não consegui falar com o servidor.")
            }
        }
    }
}
