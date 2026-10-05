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
| Texto-pra-voz (TTS) | Sim | Sim | Sim | Sim (Siri) | **Não existe** | Pedido explícito do Allan (05/10/2026) — ver seção 8; o diferencial é voz por personagem |
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

## 8. Leitura por IA — narração (05/10/2026)

Ideia levantada por Allan: uma opção de o livro ser lido em voz alta por IA, para a leitura ficar "vívida e realista". Muda a avaliação da tabela da seção 3, onde TTS estava como "avaliar com cautela": agora é pedido explícito.

**Os preços citados nesta seção e na 9 são de referência até meados de 2026 e mudam rápido — conferir antes de decidir.**

**Tamanho do problema.** Pelos números do item 4.3 da `ESPECIFICACAO.md` (mediana de ~3.400 tokens por capítulo, ~41 capítulos por livro nos dezoito livros de validação), um livro típico tem entre 0,5 e 1 milhão de caracteres — algo como 10 horas de áudio.

| Opção | Qualidade | Custo por livro | Observação |
|---|---|---|---|
| TTS nativo do Android (`TextToSpeech`) | Boa, um pouco "robótica" | Zero | Offline; `UtteranceProgressListener.onRangeStart` dá a posição de cada palavra, o que permite destacar o texto enquanto lê |
| Piper rodando no Raspberry Pi | Boa, natural, tem voz pt-BR | Zero (só energia) | Gera o áudio por capítulo no servidor e guarda em cache; coerente com o self-hosted |
| TTS na nuvem (Google Cloud TTS, OpenAI) | Muito boa | ~US$ 8–30 | Cobrança por caractere; marcação de tempo por palavra exige pedido à parte |
| ElevenLabs e similares | Excelente, expressiva | ~US$ 50–150+ | Caro para livro inteiro |

**O diferencial possível: uma voz por personagem.** Narração com uma voz só, todo leitor de mercado já tem. O que nenhum tem é o banco de `Elemento`s do Imagineer: o sistema já sabe quem é cada PERSONAGEM e, pela identidade, o gênero de cada um. Dá para atribuir uma voz por personagem nos diálogos. O custo é descobrir quem fala cada fala: uma chamada de IA por capítulo, que erra com alguma frequência — precisaria do mesmo esquema já usado no projeto, "a IA sugere, o usuário corrige" (item 4.6). Depende também da identidade acumulada chegar onde é usada (achado da revisão de fidelidade de 05/10/2026: hoje `identidade_vigente` não é repassada às chamadas que montam o prompt).

**Implicações:**
- Ler acompanhando (destacar o trecho sendo narrado) precisa da marcação de tempo de cada palavra. O TTS do Android entrega de graça.
- Uso pessoal com o próprio EPUB: sem problema de direitos autorais. Distribuir o áudio gerado seria outra questão.
- Foge um pouco do propósito original (afantasia é visual), mas reforça a visão de leitor completo do item 1.1.

**Recomendação registrada (não decidida):** começar com o TTS nativo do Android — custo zero, valida se o recurso é usado de verdade. Se for, migrar para Piper no Pi. Voz por personagem como passo seguinte, o que diferencia.

**Perguntas em aberto:**
- Áudio gerado no celular (TTS nativo, nada no backend) ou no servidor (Piper, com cache por capítulo — nova entidade ou só arquivos em disco)?
- A atribuição de falas a personagens é persistida (nova entidade, ligada a `Capitulo` e `Elemento`) ou recalculada a cada leitura?
- Como escolher a voz de cada personagem: automática por gênero/idade da identidade, ou escolhida pelo usuário na ficha do elemento (tela 7.8)?
- Narração em segundo plano (tela apagada, como um audiobook) exige um serviço Android em primeiro plano — escopo maior que só "tocar áudio na tela de leitura".

---

## 9. Vídeo curto de uma cena especial (05/10/2026)

Ideia levantada por Allan: gerar um pequeno vídeo de uma cena marcante.

**Previsão.** Vídeo por IA está hoje onde imagem estava uns dois anos atrás: qualidade impressionante, mas clipes curtos (~8 s), consistência do mesmo personagem entre clipes ainda fraca, e preço caindo rápido.

**Custos:**
- **API (Veo 3, Sora 2 e similares):** entre ~US$ 0,10 e 0,50 por segundo — uns US$ 1 a 6 por clipe de 8 s.
- **Rodar localmente:** fora de questão. Modelos abertos (Wan e similares) precisam de GPU forte; o Raspberry Pi não roda.
- **Pelo plano Gemini Pro do Allan:** o app do Gemini dá acesso ao Veo com cota diária pequena, sem custo extra. Mesmo raciocínio da decisão do item 7.7 da `ESPECIFICACAO.md`: o Imagineer gera o prompt e abre no Gemini (`Intent.ACTION_SEND`).

**Implicações técnicas:**
- **O prompt é o contrário do de imagem.** A instrução atual (`_INSTRUCAO_DE_PROMPT`, item 4.5) proíbe ação contínua — "instante congelado". Vídeo precisa de uma ação curta, movimento de câmera e, no Veo, até som. Seria um tipo de prompt novo, com instrução própria (provável campo de tipo em `Prompt`, ou entidade separada — decidir ao especificar).
- **Quase todo o resto se reaproveita:** `Frame`, estados, fundamentação e perfil de renderização. O trabalho de fidelidade ao livro já está feito.
- **Melhor técnica: vídeo a partir da imagem.** Usar a imagem da cena já aprovada (catálogo do item 6.6) como primeiro quadro. Resolve boa parte da consistência do personagem e faz do fluxo de imagem a base do vídeo.
- **Guardrails:** o guardrail de crianças e adolescentes registrado na Etapa 8 da `ESPECIFICACAO.md` vale aqui também. Provedores de vídeo tendem a ser ainda mais restritivos com pessoas realistas.
- **Armazenamento:** se o vídeo for importado de volta para o app (como a imagem hoje), são alguns MB a dezenas de MB por clipe no disco do Pi — aceitável para uso pessoal.

**Recomendação registrada (não decidida):** fazer como variação do fluxo de imagem — cena com imagem aprovada → "Gerar prompt de vídeo" → "Abrir no Gemini" com a imagem anexada. Geração dentro do app via API paga só se um dia o uso justificar.

**Perguntas em aberto:**
- O `Intent.ACTION_SEND` consegue mandar texto **e** imagem juntos para o app do Gemini, já posicionados no modo de vídeo? Precisa ser testado no aparelho; se não, o fluxo vira "copiar prompt + compartilhar imagem" em dois passos.
- Importar o vídeo de volta para o app: estende o catálogo de `Imagem` (item 6.6) para aceitar vídeo, ou entidade própria?
- Quais cenas são "especiais": qualquer `Frame` do tipo CENA, ou uma marcação explícita do usuário?

---

## Prioridade relativa das seções 8 e 9

Nenhuma das duas deveria passar na frente de:
1. os problemas de fidelidade achados na revisão de 05/10/2026 (identidade de fase 1 gravada como aparência do estado; identidade acumulada que não chega ao prompt; aparência de capítulos anteriores que não chega à releitura) — imagem, vídeo e voz por personagem herdam esses erros;
2. o básico de leitor da seção 4 (retomar de onde parou, tipografia, sumário).

Depois disso: narração com TTS nativo é barata e rápida de validar; vídeo via Gemini é um incremento pequeno sobre o fluxo de imagem.

---

## 10. Como usar este documento

Quando Allan (ou uma sessão futura do Claude Code) quiser avançar num desses pontos:
1. Ler a seção 4 (lacunas priorizadas) pra saber por onde começar.
2. Discutir as perguntas em aberto da seção 6 pro item escolhido.
3. Registrar a decisão na `ESPECIFICACAO.md`, criando a seção/Etapa correspondente (provavelmente uma nova subseção dentro da Etapa 7, ou uma Etapa 9 — "Experiência de Leitura" — se o volume justificar uma etapa própria).
4. Só então implementar, seguindo o fluxo normal do `CLAUDE.md`.

Este documento pode ser atualizado livremente (sem o rigor de "registrar decisão" da `ESPECIFICACAO.md`) à medida que mais apps forem pesquisados ou mais ideias surgirem — é rascunho vivo, não contrato.
