package com.allandpn.imagineer.telas.livro

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.allandpn.imagineer.armazenamento.ProvedorDeEnderecoDoServidor
import com.allandpn.imagineer.dados.RepositorioCapitulos
import com.allandpn.imagineer.dados.RepositorioLivros
import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.FabricaDeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Carrega o detalhe de um livro (item 7.4) e as ações da tela: alternar
 * "ignorado" por capítulo e apagar o livro. Sem Hilt (item 7.0) —
 * [criarApi] tem um padrão real mas pode ser trocado por uma API falsa no
 * teste, sem precisar de rede nem de Android de verdade.
 *
 * Não trata "sem servidor configurado" como estado próprio, diferente da
 * Biblioteca — pra chegar nesta tela o usuário já passou pela Biblioteca,
 * que só deixa navegar quando o servidor já respondeu.
 */
class LivroViewModel(
    private val livroId: Int,
    private val preferencias: ProvedorDeEnderecoDoServidor,
    private val criarApi: (String) -> ApiImagineer = { FabricaDeApi.criar(it) },
) : ViewModel() {
    private val _estado = MutableStateFlow<EstadoDoLivro>(EstadoDoLivro.Carregando)
    val estado: StateFlow<EstadoDoLivro> = _estado

    private val _apagado = MutableStateFlow(false)
    val apagado: StateFlow<Boolean> = _apagado

    init {
        carregar()
    }

    fun carregar() {
        viewModelScope.launch {
            _estado.value = EstadoDoLivro.Carregando
            executarComApi { api -> RepositorioLivros(api).obterLivro(livroId) }
                ?.let { livro -> _estado.value = EstadoDoLivro.Sucesso(livro) }
        }
    }

    /** Atualiza a linha do capítulo na hora, sem recarregar o livro inteiro. */
    fun alternarIgnorado(capituloId: Int, ignoradoAtual: Boolean) {
        val atual = _estado.value
        if (atual !is EstadoDoLivro.Sucesso) return

        viewModelScope.launch {
            val capituloAtualizado = executarComApi { api ->
                RepositorioCapitulos(api).alternarIgnorado(capituloId, !ignoradoAtual)
            } ?: return@launch

            val capitulosAtualizados = atual.livro.capitulos.map {
                if (it.id == capituloId) capituloAtualizado else it
            }
            _estado.value = EstadoDoLivro.Sucesso(atual.livro.copy(capitulos = capitulosAtualizados))
        }
    }

    /** Apaga o livro (item 3.4 — leva capítulos, elementos, frames, prompts e imagens junto). */
    fun apagarLivro() {
        viewModelScope.launch {
            executarComApi { api -> RepositorioLivros(api).apagarLivro(livroId) }
                ?.let { _apagado.value = true }
        }
    }

    /** Resolve o endereço do servidor, chama [chamada] e converte falha em [EstadoDoLivro.Erro]. */
    private suspend fun <T> executarComApi(chamada: suspend (ApiImagineer) -> T): T? {
        val endereco = preferencias.enderecoDoServidor.first()
        if (endereco.isNullOrBlank()) {
            _estado.value = EstadoDoLivro.Erro("Servidor não configurado.")
            return null
        }

        return try {
            chamada(criarApi(endereco))
        } catch (erro: CancellationException) {
            throw erro
        } catch (erro: Exception) {
            _estado.value = EstadoDoLivro.Erro(erro.message ?: "Não consegui falar com o servidor.")
            null
        }
    }
}
