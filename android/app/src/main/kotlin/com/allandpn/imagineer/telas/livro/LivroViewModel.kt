package com.allandpn.imagineer.telas.livro

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
 * Carrega o detalhe de um livro (item 7.4). Mesma ideia da
 * [com.allandpn.imagineer.telas.biblioteca.BibliotecaViewModel]: sem Hilt
 * (item 7.0), [criarRepositorio] tem um padrão real mas pode ser trocado
 * por um repositório falso no teste.
 *
 * Não trata "sem servidor configurado" como estado próprio, diferente da
 * Biblioteca — pra chegar nesta tela o usuário já passou pela Biblioteca,
 * que só deixa navegar quando o servidor já respondeu.
 */
class LivroViewModel(
    private val livroId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarRepositorio: (String) -> RepositorioLivros = { RepositorioLivros(FabricaDeApi.criar(it)) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDoLivro>(EstadoDoLivro.Carregando)
    val estado: StateFlow<EstadoDoLivro> = _estado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDoLivro.Carregando

            val endereco = preferencias.enderecoDoServidor.first()
            if (endereco.isNullOrBlank()) {
                _estado.value = EstadoDoLivro.Erro("Servidor não configurado.")
                return@launch
            }

            try {
                val livro = criarRepositorio(endereco).obterLivro(livroId)
                _estado.value = EstadoDoLivro.Sucesso(livro)
            } catch (erro: CancellationException) {
                throw erro
            } catch (erro: Exception) {
                _estado.value = EstadoDoLivro.Erro(
                    erro.message ?: "Não consegui falar com o servidor."
                )
            }
        }
    }
}
