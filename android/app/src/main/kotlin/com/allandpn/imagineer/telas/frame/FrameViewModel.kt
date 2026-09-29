package com.allandpn.imagineer.telas.frame

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioFrames
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega o detalhe de um frame (item 7.6) — retrato ou cena, distinção
 * que a tela usa pra decidir o que mostrar (`TelaFrame`). Só leitura por
 * enquanto: editar título/campos situacionais, marcar/desmarcar estados
 * de elemento, apagar o frame e gerar prompt (tudo especificado no item
 * 7.6) entram em incrementos seguintes.
 */
class FrameViewModel(
    private val frameId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDoFrame>(EstadoDoFrame.Carregando)
    val estado: StateFlow<EstadoDoFrame> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDoFrame.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDoFrame.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                val frame = RepositorioFrames(criarApi(endereco)).obterFrame(frameId)
                _estado.value = EstadoDoFrame.Sucesso(frame)
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDoFrame.Erro(erro.message ?: "Não consegui falar com o servidor.")
            }
        }
    }
}
