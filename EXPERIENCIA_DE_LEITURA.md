# Imagineer — Experiência de Leitura de EPUB

## Sobre este documento

Este documento **não é especificação fechada**. É material de pesquisa e comparação de mercado, separado da `ESPECIFICACAO.md` porque é grande demais pra viver dentro dela sem atrapalhar a leitura do resto.

Ele existe para orientar uma sessão futura (Allan ou uma sessão do Claude Code) a decidir **quando** e **o quê** discutir primeiro, à medida que o Imagineer deixa de ser só um gerador de prompts/imagens e passa a mirar ser um **leitor de EPUB completo**, com a geração de imagens como uma camada em cima da leitura, não o produto inteiro.

Nada aqui vira código sem passar pelo fluxo normal do projeto (`CLAUDE.md` → Especificar → Documentar em `ESPECIFICACAO.md` → Implementar → Testar). Este arquivo é o "antes de especificar": o levantamento que sustenta a conversa, não a decisão em si.

Formato do EPUB continua sendo o único suportado (decisão já tomada — é o que permite extrair texto estruturado por capítulo pra alimentar a IA; PDF, MOBI etc. não entram em consideração).

Registrado na `ESPECIFICACAO.md` (Etapa 8) um ponteiro pra este documento, junto com a mudança de visão do produto.

---

## 1. Contexto da mudança de visão

O Imagineer nasceu como uma ferramenta pra resolver um problema específico (afantasia: gerar imagens de cenas/personagens de um livro que o usuário já está lendo em outro lugar — Kindle, papel, outro app). Isso significa que, até agora, **a experiência de leitura em si nunca foi projetada** — o EPUB é importado só como fonte de texto pra IA processar; a tela de Capítulo (item 7.5 da especificação) é hoje um texto corrido rolável, sem nenhuma das convenções que um leitor de verdade tem.

A mudança de visão: o Imagineer passa a ser o lugar onde o livro é **lido**, não só catalogado. Isso muda o que "completo" significa pro MVP — hoje o MVP é Elemento + EstadoElemento + Frame + Prompt + Imagem (escopo do `CLAUDE.md`); uma leitura de verdade (tipografia, retomar posição, navegação) passa a ser tão essencial quanto esse núcleo, porque sem ela o app não compete como leitor, só como ferramenta auxiliar.

---

## 2. Apps analisados

**Leitores de EPUB "puros" (a barra de comparação principal deste documento):**
- **Kindle** (Amazon) — paginação, sincronização de posição entre dispositivos, X-Ray (informação sobre personagens/lugares), dicionário integrado, ajuste de fonte/tema.
- **Moon+ Reader (Pro)** — um dos leitores Android mais configuráveis: temas ilimitados, múltiplos motores de rolagem/paginação, controle de brilho por toque lateral, TTS, estatísticas de leitura, backup de anotações.
- **ReadEra** — minimalista, foco em biblioteca grande e busca rápida, estatísticas de leitura (tempo, páginas, sequência de dias lidos).
- **Apple Books** — paginação suave, temas (incluindo "papel"), destaques com cores, notas vinculadas ao destaque, estrutura de coleções.
- **Libby/OverDrive** — biblioteca pública, não é o foco de comparação de funcionalidade de leitura em si (modelo de empréstimo não se aplica), mas tem boa UX de "continuar lendo" e progresso.
- **FBReader** — open source, referência de customização tipográfica extrema (fontes embutidas do próprio EPUB, hifenização, kerning).

**Concorrentes de IA já pesquisados (comparação cruzada, ver `ESPECIFICACAO.md` → "Análise de mercado e diferenciação"):**
- **Book2Life, Bookworm, Lira, dokkei** — nenhum deles é, antes de tudo, um leitor: são camadas de geração de imagem sobre texto que o usuário cola ou importa. Nenhum tem as funcionalidades de leitura listadas abaixo com profundidade de um leitor dedicado — **isso é uma lacuna do mercado inteiro de "IA + livro"**, não só do Imagineer. Se o Imagineer virar um leitor completo primeiro, isso é diferencial novo, não só paridade.

---

## 3. Comparação funcionalidade a funcionalidade

| Funcionalidade | Kindle | Moon+ Reader | ReadEra | Apple Books | Imagineer hoje | Lacuna? |
|---|---|---|---|---|---|---|
| Retomar de onde parou | Sim (sincronizado) | Sim | Sim | Sim | **Não existe** | **Crítica** |
| Ajuste de fonte/tamanho/espaçamento | Sim | Sim (extremo) | Sim | Sim | **Não existe** | **Crítica** |
| Temas claro/escuro/sépia | Sim | Sim (ilimitado) | Sim | Sim | Só o tema do sistema (Material 3 dinâmico, item 7.0) | **Crítica** |
| Sumário navegável (ir pro capítulo X) | Sim | Sim | Sim | Sim | Dados existem (`Capitulo.titulo`/`ordem`), falta UI | Alta |
| Indicador de progresso (% lido, cap. X de Y) | Sim | Sim | Sim | Sim | **Não existe** | Alta |
| Busca dentro do texto do livro | Sim | Sim | Sim | Sim | **Não existe** (diferente da busca em listas, já pendente) | Alta |
| Marcadores/destaques (highlights) | Sim | Sim | Sim | Sim | **Não existe** | Alta |
| Anotações vinculadas a um trecho | Sim | Sim | Limitado | Sim | **Não existe** | Média |
| Manter tela acesa durante leitura | Sim | Sim | Sim | Sim | **Não existe** | Média |
| Controle de brilho dentro do app | Sim | Sim | Não | Não | **Não existe** | Baixa |
| Paginação (efeito de virar página) | Sim | Opcional | Opcional | Sim | Rolagem contínua simples | Baixa (decisão de estilo, não lacuna grave) |
| Estatísticas de leitura (tempo, sequência) | Parcial | Sim | Sim | Não | **Não existe** | Baixa |
| Texto-pra-voz (TTS) | Sim | Sim | Sim | Sim (Siri) | **Não existe** | Avaliar com cautela (foge do propósito visual/afantasia — só priorizar se pedido explícito) |
| Fontes customizadas/embutidas do EPUB | Parcial | Sim | Parcial | Parcial | **Não existe** (texto extraído, sem preservar fonte) | Baixa, nicho |
| Dicionário/tradução por seleção de palavra | Sim | Sim | Sim | Sim | **Não existe** | Baixa, mas Allan já tem arquivos `.dict` prontos — ver seção 8 |
| Catalogação de elementos/personagens por capítulo com evolução temporal | Não (X-Ray é estático) | Não | Não | Não | **Sim — já é o core do Imagineer** | **Diferencial nosso, nenhum concorrente tem** |
| Geração de imagem de cena/personagem | Não | Não | Não | Não | **Sim — já é o core do Imagineer** | **Diferencial nosso** |

---

## 4. Lacunas priorizadas (da mais crítica pra menos)

1. **Retomar de onde parou.** Sem isso o app não é usável como leitor principal — ninguém troca de app de leitura sem essa garantia básica.
2. **Tipografia e tema ajustáveis.** Leitura prolongada em texto cru, sem controle de tamanho/tema, cansa e afasta o uso diário.
3. **Sumário navegável + indicador de progresso.** Dado já existe (`Capitulo.ordem`/`titulo`), é majoritariamente trabalho de UI — custo baixo, impacto alto.
4. **Busca dentro do texto do capítulo.** Diferente da busca em listas (já registrada como prioridade em `ESPECIFICACAO.md`), mas do mesmo espírito: livro de fantasia típico passa de 300 páginas, sem busca o app fica difícil de usar pra reler um trecho.
5. **Marcadores e destaques.** Aqui mora a maior oportunidade de diferenciação (ver seção 5) — não é só "ter paridade com Kindle", é a ponte entre ler e catalogar.
6. **Manter tela acesa / controle de brilho.** Baixo custo de implementação (APIs padrão do Android), alto incômodo quando falta.
7. Resto da lista (estatísticas, TTS, dicionário, fontes customizadas): nice-to-have, não bloqueiam a experiência central.

---

## 5. Onde a leitura se cruza com o que o Imagineer já faz (a maior oportunidade)

O ponto mais valioso de virar um leitor completo não é só alcançar paridade com Kindle/Moon+ Reader — é que **nenhum concorrente, nem leitor genérico nem IA de imagem, liga o ato de ler com o rastreamento de elementos que o Imagineer já faz**.

Ideia concreta a explorar (ainda sem especificação, registrar como tópico de discussão quando chegar a vez):
- Destacar um trecho do texto durante a leitura e, dali, criar ou vincular diretamente a um `Elemento`/`EstadoElemento`/`SugestaoDeElemento` existente — hoje esse fluxo só existe via "Analisar com IA" no capítulo inteiro (item 4.4), nunca a partir de um trecho específico escolhido pelo usuário.
- Ao tocar num nome já catalogado dentro do texto (ex.: "Bran" aparece destacado, estilo link), abrir direto a ficha do `Elemento` (tela 7.8) sem sair da leitura.
- Retomar a leitura já mostrando, de forma discreta, quais elementos têm estado/aparência atualizados desde a última vez que o capítulo foi lido.

Nenhuma dessas é uma decisão tomada — são direções que valem a conversa quando a prioridade 5 da lista acima (marcadores/destaques) for discutida de verdade.

---

## 6. Perguntas em aberto por funcionalidade (não decisões)

- **Retomar de onde parou**: granularidade da posição salva — por capítulo (`Capitulo.id` + rolagem em `%` ou em caracteres) ou por sentença/parágrafo? Onde isso é persistido (novo campo em `Livro`, ou entidade própria tipo `ProgressoDeLeitura`, pensando em eventualmente ter mais de um "marcador" por livro)?
- **Tipografia/tema**: preferências são globais (uma config pro app inteiro) ou por livro? Ficam no `PreferenciasApp`/DataStore (igual ao endereço do servidor, item 7.0) já que são só do dispositivo, sem precisar ir ao backend?
- **Sumário navegável**: abre como modal/bottom sheet sobre a tela de Capítulo, ou é uma tela própria?
- **Busca no texto**: busca client-side simples (o texto do capítulo já está carregado) ou precisa de endpoint novo no backend pra buscar em todos os capítulos de um livro de uma vez?
- **Marcadores/destaques**: nova entidade no backend (persistido, sincronizável entre reinstalações do app) ou só local no dispositivo? Se for entidade nova, qual o nome em português (`Marcador`? `Destaque`?) e que campos (trecho de texto, posição de início/fim, capítulo, cor, nota opcional)?
- **Manter tela acesa**: configurável (liga/desliga) ou sempre ativo durante a leitura, sem opção?

---

## 7. Modo dicionário/tradutor offline com arquivos `.dict` (02/10/2026)

Ideia levantada por Allan: ele já tem vários arquivos `.dict` e quer incorporá-los ao app como um modo dicionário/tradutor, consultado por seleção de palavra durante a leitura.

**Viabilidade (avaliação inicial, sem compromisso de implementação):** parece viável. `.dict` é normalmente parte do formato **StarDict/dictd** (o mesmo usado por GoldenDict, Aard, etc.), composto por um conjunto de arquivos junto do `.dict`:
- `.ifo` — metadados em texto puro (nome do dicionário, idioma, quantidade de entradas).
- `.idx` (às vezes `.idx.gz`) — índice ordenado alfabeticamente, palavra → posição/tamanho no arquivo `.dict`.
- `.dict` (às vezes `.dict.dz`, comprimido) — o conteúdo das definições em si.

É um formato aberto, bem documentado publicamente, sem necessidade de biblioteca de terceiros pesada — leitura binária simples + busca binária no índice (já vem ordenado), o que funciona bem mesmo com dicionários grandes. Funciona **inteiramente offline**, sem custo de API nem dependência de internet — compatível com a filosofia self-hosted/privada já registrada como diferencial do Imagineer (`ESPECIFICACAO.md` → "Análise de mercado e diferenciação").

**Atualização (02/10/2026):** Allan confirmou que os arquivos que ele tem, na prática, são `.cdi`, `.idx` e `.syn` — não exatamente o trio clássico `.ifo`/`.idx`/`.dict` do StarDict que eu tinha assumido. `.idx` (índice) e `.syn` (sinônimos) batem com StarDict/dictd, mas `.cdi` no lugar de `.ifo`+`.dict` é diferente do que eu descrevi acima — pode ser uma variante/ferramenta derivada do StarDict que empacota metadados+conteúdo num arquivo só (`.cdi`), ou um formato distinto que só reaproveita a convenção de índice/sinônimo. **Não dá pra confirmar o formato exato sem inspecionar os arquivos de verdade** (abrir o `.cdi` em editor hex pra ver se começa com um cabeçalho de texto tipo `StarDict's dict ifo file` — identificaria StarDict na hora — ou é binário desde o primeiro byte).

**Perguntas em aberto, ainda sem decisão:**
- Confirmar o formato exato do `.cdi` antes de especificar o parser — idealmente inspecionando um arquivo pequeno de exemplo (os primeiros bytes/cabeçalho já dizem bastante). Pode ser necessário Allan compartilhar um arquivo de amostra (ou só a extensão/nome do programa que os gerou/usa, o que já ajudaria a identificar o formato por pesquisa).
- Como os arquivos entram no app: importados pelo usuário via seletor de arquivo (mesmo padrão já usado pra importar imagem — item 7.7) ou embutidos como asset do próprio APK?
- Um dicionário por idioma, ou vários simultâneos com prioridade/fallback entre eles (útil se Allan tiver, por ex., um `.dict` inglês-português e outro de sinônimos)?
- A consulta é só definição/tradução "dicionário clássico" (parecido com o item já listado na seção 3, "dicionário por seleção de palavra") ou ele imagina algo mais parecido com tradução de frase inteira — isso muda bastante o escopo, porque StarDict é fundamentalmente palavra/expressão curta, não tradução de frase.
- Onde os arquivos ficam armazenados no dispositivo (mesma pasta de dados do app, ou local escolhido pelo usuário) e o que acontece se o arquivo for grande (alguns dicionários StarDict passam de 100MB).
- Isso se conecta à funcionalidade de seleção de texto que a leitura completa (seção 4, item "marcadores e destaques") também vai precisar — faz sentido especificar os dois juntos, já que ambos dependem do mesmo mecanismo de "usuário seleciona um trecho do texto durante a leitura".

Prioridade: hoje listado como "baixa" na tabela da seção 3 (não bloqueia a experiência central de leitura), mas sobe de interesse por já ter o material (arquivos `.dict`) em mãos — custo de aquisição de conteúdo já pago, resta só o custo de implementação.

---

## 8. Como usar este documento

Quando Allan (ou uma sessão futura do Claude Code) quiser avançar num desses pontos:
1. Ler a seção 4 (lacunas priorizadas) pra saber por onde começar.
2. Discutir as perguntas em aberto da seção 6 pro item escolhido.
3. Registrar a decisão na `ESPECIFICACAO.md`, criando a seção/Etapa correspondente (provavelmente uma nova subseção dentro da Etapa 7, ou uma Etapa 9 — "Experiência de Leitura" — se o volume justificar uma etapa própria).
4. Só então implementar, seguindo o fluxo normal do `CLAUDE.md`.

Este documento pode ser atualizado livremente (sem o rigor de "registrar decisão" da `ESPECIFICACAO.md`) à medida que mais apps forem pesquisados ou mais ideias surgirem — é rascunho vivo, não contrato.
