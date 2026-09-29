package com.allandpn.imagineer.ui.tema

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/**
 * Material 3 puro, sem paleta customizada (item 7.0: "Design visual").
 * Cor dinâmica (Material You) quando o Android suporta (12+); claro/escuro
 * seguindo a preferência do sistema. Nenhuma decisão de marca aqui de
 * propósito.
 */
@Composable
fun TemaImagineer(conteudo: @Composable () -> Unit) {
    val escuro = isSystemInDarkTheme()
    val contexto = LocalContext.current

    val esquemaDeCores = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        if (escuro) dynamicDarkColorScheme(contexto) else dynamicLightColorScheme(contexto)
    } else {
        if (escuro) androidx.compose.material3.darkColorScheme() else androidx.compose.material3.lightColorScheme()
    }

    MaterialTheme(colorScheme = esquemaDeCores, content = conteudo)
}
