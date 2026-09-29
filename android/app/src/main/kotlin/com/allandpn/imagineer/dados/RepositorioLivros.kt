package com.allandpn.imagineer.dados

import com.allandpn.imagineer.rede.ApiImagineer
import com.allandpn.imagineer.rede.LivroDetalhe
import com.allandpn.imagineer.rede.LivroResumo

/**
 * Fica entre a tela (ViewModel) e a API — hoje só repassa a chamada, mas é
 * o lugar certo pra crescer regra de exibição sem misturar com a tela nem
 * com o cliente Retrofit. Recebe o [ApiImagineer] pronto em vez de montá-lo
 * sozinho, porque o endereço do servidor pode mudar em tempo de execução
 * (item 7.0) — quem decide qual API usar é a camada acima.
 */
class RepositorioLivros(private val api: ApiImagineer) {
    suspend fun listarLivros(): List<LivroResumo> = api.listarLivros()

    suspend fun obterLivro(livroId: Int): LivroDetalhe = api.obterLivro(livroId)
}
