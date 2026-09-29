package com.allandpn.imagineer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.allandpn.imagineer.armazenamento.PreferenciasApp
import com.allandpn.imagineer.navegacao.GrafoDeNavegacao
import com.allandpn.imagineer.ui.tema.TemaImagineer

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val preferencias = PreferenciasApp(applicationContext)

        setContent {
            TemaImagineer {
                Surface(modifier = Modifier.fillMaxSize()) {
                    GrafoDeNavegacao(preferencias = preferencias)
                }
            }
        }
    }
}
