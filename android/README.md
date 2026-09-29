# Imagineer — app Android

Cliente mobile do Imagineer (Kotlin + Jetpack Compose), especificado na Etapa 7 do
`ESPECIFICACAO.md` (raiz do repositório). Arquitetura decidida no item 7.0: MVVM sem
Hilt, Retrofit + `kotlinx.serialization`, Navigation Compose com destinos tipados,
DataStore, Material 3 puro.

## Como abrir

Abra a pasta `android/` (esta, não a raiz do repositório) no Android Studio. O
Gradle wrapper já está commitado — o Studio baixa o resto sozinho.

## Como rodar sem Android Studio

```bash
cd android
./gradlew :app:testDebugUnitTest   # testes de unidade (JVM puro, sem SDK)
./gradlew :app:assembleDebug       # gera o APK de debug (precisa do Android SDK)
```

Sem o Android SDK instalado, `assembleDebug` falha — os testes de unidade não
precisam dele. Para instalar o mínimo necessário sem o Android Studio:

```bash
sdkmanager --sdk_root=<algum diretório> "platform-tools" "platforms;android-35" "build-tools;34.0.0"
echo "sdk.dir=<esse diretório>" > android/local.properties
```

## O que já existe

- Grafo de navegação inteiro (item 7.1), com todos os destinos da Etapa 7 já
  declarados — a maioria ainda mostra só "ainda não implementada".
- Tela de **Biblioteca** (7.2) completa, com os cinco estados do protótipo
  (carregando, vazia, com livros, sem servidor configurado, erro).
- Versão mínima da tela de **Configuração** (7.10) — só o endereço do servidor,
  o suficiente pra Biblioteca funcionar.

O que falta está listado na Etapa 8 do `ESPECIFICACAO.md`.

## Antes de testar num aparelho

Configure o endereço do servidor na tela de Configuração (ícone de engrenagem na
Biblioteca) com a URL onde o backend do Imagineer está rodando — por exemplo,
`http://100.x.x.x:8000` (endereço Tailscale) ou `http://10.0.2.2:8000` se o
backend estiver rodando no seu computador e você testar num emulador Android.
