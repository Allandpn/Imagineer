package com.allandpn.imagineer.telas.biblioteca

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioLivros
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega a lista de livros. Sem injeção de dependência automática (item
 * 7.0 decidiu MVVM sem Hilt) — recebe o endereço do servidor pronto e monta
 * o repositório sozinho a cada chamada, porque o endereço pode ter mudado
 * desde a última vez (tela de Configuração, item 7.10). [criarRepositorio]
 * tem um padrão real, mas pode ser trocado por um repositório falso no
 * teste, sem precisar de rede nem de Android de verdade.
 */
class BibliotecaViewModel(
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarRepositorio: (String) -> RepositorioLivros = { RepositorioLivros(FabricaDeApi.criar(it)) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDaBiblioteca>(EstadoDaBiblioteca.Carregando)
    val estado: StateFlow<EstadoDaBiblioteca> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDaBiblioteca.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDaBiblioteca.SemServidorConfigurado
                return@launch
            }

            try {
                val livros = criarRepositorio(endereco).listarLivros()
                _estado.value = if (livros.isEmpty()) {
                    EstadoDaBiblioteca.Vazia
                } else {
                    EstadoDaBiblioteca.ComLivros(livros)
                }
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDaBiblioteca.Erro(
                    erro.message ?: "Não consegui falar com o servidor."
                )
            }
        }
    }
}
