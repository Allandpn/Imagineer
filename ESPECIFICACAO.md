# Imagineer — Especificação do Sistema

## Sobre este documento

Este documento reúne as definições de arquitetura, modelagem de dados e fluxo do sistema Imagineer. Ele é um **documento vivo**: conforme cada item for implementado, a seção correspondente deve ser atualizada com uma explicação, em linguagem simples, do que foi feito e por quê — não apenas o plano original, mas o resultado real.

A estrutura segue o padrão **Etapa → Item**. Cada etapa representa uma fase lógica do sistema; cada item dentro dela é uma decisão ou funcionalidade específica que pode ser especificada, documentada, implementada e testada de forma independente.

**Idioma do sistema**: todo o sistema — nomes de entidades, campos, classes, endpoints, mensagens de log, textos de interface — é em português. Termos técnicos já naturalizados no vocabulário de desenvolvimento em português (ex: *prompt*, *backend*, *endpoint*, *deploy*, *docker*) são mantidos como estão, por não terem equivalente melhor e já serem de uso corrente. Assumindo essa interpretação (código e nomes de domínio em português, termos técnicos genéricos mantidos); ajuste se a intenção era outra.

---

## Etapa 1 — Visão Geral e Arquitetura

### 1.1 Objetivo do projeto

Sistema pessoal (não comercial) chamado **Imagineer**, que gera prompts de imagem a partir da leitura de e-books (EPUB), pensado para pessoas com afantasia (dificuldade de visualizar mentalmente cenas, personagens e ambientes durante a leitura).

### 1.2 Arquitetura geral

Modelo cliente-servidor:

- **Servidor (Raspberry Pi, rodando 24/7)**: recebe o EPUB, faz o parsing e estruturação em capítulos, guarda todos os dados em banco, chama as IAs de texto (extração de elementos e montagem de prompt), expõe uma API REST, e armazena as imagens do catálogo.
- **App mobile (cliente)**: importa o EPUB e envia ao servidor, exibe a estrutura do livro, permite ao usuário selecionar/ajustar personagens, ambientes, objetos, criaturas e cenas por capítulo, exibe o prompt gerado para cópia manual, e permite importar de volta a imagem gerada externamente para compor o catálogo.

### 1.3 Stack tecnológica

- **Backend**: Python + FastAPI (assíncrono, adequado para chamadas de IA que dependem de I/O externo).
- **Parsing de EPUB**: `ebooklib` (extração de capítulos via TOC/spine e texto).
- **Banco de dados**: PostgreSQL, rodando em container próprio.
- **ORM**: SQLAlchemy.
- **Mobile**: **assumido** Kotlin + Jetpack Compose (Android nativo), aproveitando a familiaridade com JVM. **Ainda não confirmado formalmente** — ver Etapa 8 (Pendências). Telas esboçadas na Etapa 7.

### 1.4 Infraestrutura

- Backend e banco rodando via `docker-compose` no Raspberry Pi (serviços `api`, `db`, e um volume dedicado para armazenamento das imagens do catálogo — imagens não ficam no banco, só a referência ao arquivo).
- Exposição do servidor para acesso fora da rede local via Tailscale (VPN) ou reverse proxy (Caddy/Nginx) com HTTPS.
### 1.5 Estrutura de pastas e módulos do backend

O backend é organizado por **responsabilidade**, não por entidade. Cada pasta responde a uma pergunta diferente sobre o sistema:

```
Imagineer/
├── README.md              # como subir o projeto (dev local e Raspberry Pi)
├── requirements.txt       # dependências Python com versões fixas
├── pytest.ini             # configuração de testes
├── .env.exemplo           # modelo das variáveis de ambiente, sem valores reais
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── migracoes/             # migrations do banco (Alembic)
├── imagineer/             # o pacote da aplicação
│   ├── principal.py       # cria a instância FastAPI e registra as rotas
│   ├── configuracao.py    # leitura das variáveis de ambiente
│   ├── banco/             # conexão, sessão e base declarativa do SQLAlchemy
│   ├── modelos/           # tabelas do banco (Etapa 3)
│   ├── esquemas/          # contratos de entrada e saída da API (Pydantic)
│   ├── rotas/             # endpoints HTTP
│   ├── servicos/          # regras de negócio
│   └── ia/                # integração com provedores de IA (Etapa 4)
└── testes/
```

**Por que separar assim:**

- **`modelos`** — como o dado é guardado no banco.
- **`esquemas`** — o que entra e sai pela API. É deliberadamente separado de `modelos`: o formato que o app mobile envia não precisa ser igual ao formato da tabela, e a API não deve expor colunas internas sem querer.
- **`rotas`** — qual URL aciona o quê. Só cuidam de HTTP: recebem o pedido, chamam um serviço, devolvem a resposta.
- **`servicos`** — a regra de negócio (estruturar o EPUB, montar o prompt, salvar a imagem no catálogo). Não conhece HTTP. É essa separação que permite testar a lógica sem subir a API.
- **`ia`** — a fronteira com o mundo externo, isolada atrás da interface da Etapa 4.2.

As pastas `modelos`, `esquemas`, `servicos` e `ia` nascem **vazias**, contendo apenas o `__init__.py`. Elas existem para que cada item seguinte tenha um destino óbvio, sem que nada seja implementado antes da hora.

**O que foi entregue neste item:** o esqueleto acima, subindo em Docker e respondendo em `GET /saude` — um endpoint que confirma que a API está no ar *e* conversando com o PostgreSQL. Nenhuma entidade de domínio foi implementada ainda.

---

## Etapa 2 — Fluxo do Sistema

### 2.1 Fluxo passo a passo

1. Usuário importa o EPUB no app.
2. App envia o EPUB para o servidor.
3. Servidor faz a estruturação em capítulos.
4. Servidor devolve a estrutura para o app.
5. Usuário escolhe um capítulo.
6. Servidor chama a IA para sugerir personagens, ambientes, objetos, criaturas e cenas daquele capítulo — usando como contexto o **último estado conhecido** de cada elemento já cadastrado (ver item 4.4).
7. Usuário revisa as sugestões: confirma, ajusta ou descarta cada uma; decide se cada elemento mantém o estado atual ou ganha um novo estado.
8. Servidor usa o histórico (estado atual dos elementos escolhidos) para montar o prompt de geração de imagem.
9. Usuário copia o prompt e gera a imagem numa IA de imagem gratuita externa.
10. Usuário importa a imagem gerada de volta para o app.
11. Imagem é enviada e salva no servidor, associada ao capítulo/elementos/cena de origem, compondo o catálogo.

### 2.2 Importação e estruturação do EPUB

Detalha os passos 1 a 4 do fluxo: como o arquivo enviado pelo app se transforma em um Livro com Capítulos no banco.

A responsabilidade é dividida em duas funções, em `imagineer/servicos/importacao_epub.py`:

| Função | O que faz |
|---|---|
| `extrair_epub(conteudo, nome_arquivo)` | Lê os bytes do EPUB e devolve a estrutura encontrada, **sem tocar no banco** |
| `importar_epub(sessao, conteudo, nome_arquivo)` | Chama a extração e grava o Livro com seus Capítulos |

A extração é separada da gravação porque são coisas diferentes: o parsing de EPUB é onde mora a complexidade e onde os testes precisam variar muito (arquivo sem índice, sem autor, com capítulo vazio), e testar isso não deveria exigir um banco no ar.

O EPUB é lido direto da memória (`BytesIO`), sem arquivo temporário — o `read_epub` do `ebooklib` aceita um objeto de arquivo, então os bytes que chegam do upload são passados adiante como estão.

#### De onde vem cada dado

**Metadados do Livro** — dos campos Dublin Core do EPUB:

| Campo do modelo | Metadado | Se faltar |
|---|---|---|
| `titulo` | `dc:title` | usa o nome do arquivo, sem a extensão |
| `autor` | `dc:creator` | fica nulo |
| `idioma` | `dc:language` | fica nulo |
| `identificador_epub` | o `dc:identifier` **declarado** pelo pacote | fica nulo |

Só o `titulo` tem valor de reserva, porque é obrigatório no modelo e é o que identifica o livro na tela do app. Um livro sem título na lista seria inutilizável; um livro sem autor, não.

Um EPUB pode listar **vários** `dc:identifier` — ASIN, ISBN, id do Calibre, UUID — e o pacote aponta, pelo atributo `unique-identifier`, qual deles identifica a obra. Não é necessariamente o primeiro da lista. Usar o primeiro faria a detecção de livro repetido depender da ordem em que o arquivo foi escrito.

**Capítulos** — a ordem e o conteúdo vêm do **spine**; os títulos vêm do **índice (TOC)**.

Essa combinação é deliberada, porque cada fonte resolve metade do problema:

- O **spine** é a ordem de leitura declarada pelo EPUB. Está sempre presente e contém todos os documentos do livro, mas não traz títulos.
- O **TOC** traz os títulos, mas é opcional, pode estar incompleto, pode ser aninhado em seções e pode apontar para uma âncora dentro de um arquivo em vez do arquivo todo.

Então percorremos o spine para definir `ordem` e `texto`, e consultamos o TOC para preencher `titulo` — casando pelo caminho do arquivo. O TOC é achatado (seções aninhadas são percorridas por inteiro) e a âncora é descartada: `capitulo3.xhtml#inicio` casa com `capitulo3.xhtml`. Um capítulo sem entrada no TOC fica com `titulo` nulo, que o modelo já aceita (item 3.4a).

**Texto** — o HTML de cada documento é convertido em texto simples preservando as quebras de parágrafo, porque é esse texto que a IA vai ler. Blocos (`p`, `div`, títulos, `li`, `blockquote`) passam a ser separados por linha em branco, `<br>` por quebra simples, e `script`/`style` são descartados. Espaços repetidos e linhas em branco excedentes são normalizados, e as quebras de linha do Windows (`
`) são convertidas — sem isso, um `
` solto sobra no meio dos parágrafos e iria assim para o prompt.

#### O que é descartado

- **Documentos de navegação** (`nav.xhtml`, `toc.ncx`): fazem parte da mecânica do formato, não da obra. Aparecem no spine e seriam importados como se fossem capítulos.
- **Sumários disfarçados de capítulo**: muitos EPUBs trazem uma página "Sumário" como documento XHTML comum, que o formato não marca como navegação. O critério é a proporção do texto que está dentro de links — uma página de sumário é quase só links, um capítulo praticamente não tem nenhum. Descarta-se acima de 60% do texto em links, e só se houver pelo menos 5 links, para não confundir com um capítulo que cita notas de rodapé.
- **Documentos sem texto útil**: menos de 100 caracteres depois da extração. Na prática são capas, folhas de rosto e páginas de créditos, que todo EPUB tem em quantidade.

O limite de 100 caracteres é baixo de propósito: é o suficiente para pegar páginas praticamente vazias sem risco de descartar um capítulo curto de verdade. A alternativa — importar tudo — deixaria o app com meia dúzia de "capítulos" que não são capítulos, e o usuário teria de filtrar à mão em cada livro.

A `ordem` dos capítulos é atribuída **depois** do descarte, começando em 1 e sem lacunas. O que importa é a sequência de leitura do conteúdo, não a posição original no arquivo.

#### Livro já importado

A função `livros_com_mesmo_identificador(sessao, identificador)` devolve os livros já cadastrados com aquele `dc:identifier`. Serve para o app **avisar** que o livro parece já ter sido importado — não para impedir, conforme o item 3.4a.

#### Quando o arquivo não é um EPUB válido

`extrair_epub` levanta `ArquivoEpubInvalido` com uma mensagem em português, em vez de deixar escapar o erro cru do `ebooklib` ou do `zipfile`. A rota que receber o upload traduz isso numa resposta de erro clara; sem esse tratamento, um arquivo corrompido viraria um erro 500 sem explicação.

Um EPUB válido mas **sem nenhum capítulo aproveitável** também é erro: importar um livro vazio não serviria para nada e o problema só apareceria depois, na tela do app.

#### O que foi implementado

Tudo acima, em `imagineer/servicos/importacao_epub.py`, coberto por testes que
constroem EPUBs em memória com o próprio `ebooklib` — nenhum arquivo binário
entra no repositório.

#### Como a implementação foi validada

O caminho foi em três etapas, e cada uma achou coisa que a anterior não acharia.

**1. EPUBs sintéticos.** Montados sob medida para cada situação: sem índice, sem
autor, com capítulo vazio, com página de navegação. Uma constatação veio daqui: o
`ebooklib` **inventa** um identificador UUID ao escrever um EPUB sem
`dc:identifier`, porque o formato exige o elemento. O caso real não é "sem
identificador", e sim "identificador vazio" — o que se vê em arquivos
convertidos. O teste precisou ser reescrito sobre o caso certo.

**2. Um EPUB sintético "realista"**, com documentos em subpasta, capa, folha de
rosto, créditos, índice aninhado em partes e uma entrada apontando para âncora no
meio de um capítulo. É onde um parsing ingênuo produz capítulo duplicado, título
trocado ou capa virada capítulo.

**3. Dezoito livros publicados de verdade.** Alguns são EPUB 3, outros EPUB 2,
vários passaram por conversão no Calibre. Esta etapa foi a que mais valeu, e a
variedade de formato é que fez o trabalho:

| Tipo | Livros |
|---|---|
| Romance | *A Vontade de Muitos*, *Mistborn: O Império Final*, *O Poço da Ascensão*, *Tress, a garota do Mar Esmeralda*, *Devoradores de Estrelas*, *Perdido em Marte*, *O apanhador no campo de centeio*, *O estrangeiro*, *O Processo*, *Treasure Island* |
| Romance epistolar | *Flores para Algernon* |
| Novela com aparato crítico | *O Alienista* |
| Poema épico com notas do tradutor | *Odisseia* |
| Coletânea de poemas | *Robert Frost: Selected Early Poems* |
| Coletânea de contos | *Os 100 Melhores Contos de Humor*, *Os 100 Melhores Contos de Crime e Mistério* |
| Livro técnico, em inglês | *The Sherlock Holmes Handbook* |
| História em quadrinhos | *Persépolis 2* |

#### Os defeitos que só os livros reais mostraram

Nenhum deles apareceria em EPUB gerado em teste. Todos viraram teste de
regressão, reproduzidos com EPUBs sintéticos equivalentes.

1. **O identificador errado.** Um arquivo declarava cinco `dc:identifier` e o
   código pegava o primeiro (`asin:...`), quando o declarado pelo pacote no
   atributo `unique-identifier` era o último (`urn:asin:...`). Isso quebraria a
   detecção de livro repetido, que passaria a depender da ordem em que o arquivo
   foi escrito.

2. **Retorno de carro sobrando.** O HTML usava quebras de linha do Windows e a
   normalização só tratava as de Unix, deixando um caractere de retorno solto no
   meio dos parágrafos — que iria assim para o prompt da IA.

3. **Sumário virando capítulo.** Um livro trazia, depois do último capítulo, uma
   página de sumário em XHTML comum: 86 links, 99,3% do texto dentro deles. Não
   sendo um `nav.xhtml` declarado, passava pelo filtro de tipo.

4. **Capítulos no lugar errado das fronteiras.** Em *Flores para Algernon*, as
   fronteiras de capítulo são âncoras dentro dos arquivos, não os arquivos: 13
   documentos para 23 entradas de índice, com um arquivo contendo 11 relatórios de
   progresso. A importação produzia 4 capítulos gigantes, um com 131 mil
   caracteres, em vez dos 17 relatórios.

5. **Divisão que não acontecia.** Em *O Processo*, o documento de fragmentos
   estava inteiro dentro de um único `<div>`, então todas as âncoras caíam no mesmo
   filho do corpo e o corte degenerava numa fatia só.

6. **O romance inteiro escondido.** Ainda em *O Processo*, o índice tem uma única
   seção aninhada — "Fragmentos", o apêndice — e os doze capítulos estão na raiz.
   O critério de posição no índice, que valia em três dos livros, se invertia aqui
   e sugeria ignorar todos os capítulos do livro.

7. **Contos escondidos numa coletânea.** Em *Os 100 Melhores Contos de Humor*, as
   fábulas de Esopo têm 600 caracteres e a mediana da antologia é 9 mil — 7%, bem
   abaixo do limite. Três fábulas e um conto eram sugeridos como ignorados. O que
   os salva é a forma do título: coletâneas numeram as histórias
   ("3 - AS MÃOS, OS PÉS E O VENTRE", "36. O NÚMERO TRÊS"), e um título que começa
   com número e separador é item de uma sequência.

8. **Rótulos só em português.** No *Sherlock Holmes Handbook*, que é em inglês,
   "Introduction", "About the Author" e "Acknowledgments" passavam como capítulos.
   A lista de rótulos ganhou os equivalentes em inglês, e a proteção por título
   narrativo ganhou `chapter`, `prologue`, `part` e companhia.

9. **Capítulos sem nome.** Em *Tress, a garota do Mar Esmeralda*, 80 dos 84
   capítulos não têm entrada no índice — o livro tem 106 documentos e 15 entradas.
   Eram importados sem título, e a lista no app ficaria com 80 linhas em branco.
   Na coletânea de Robert Frost acontecia algo parecido: o índice aponta para a
   nota editorial que precede cada poema, e o poema em si ficava sem rótulo.

10. **Mensagem inútil para livro de imagem.** *Persépolis 2* é uma história em
    quadrinhos: 192 páginas, 192 imagens, zero caractere de texto — o texto está
    desenhado dentro dos quadros. A importação recusava o arquivo, o que é
    correto, mas dizia apenas "nenhum capítulo com texto foi encontrado", o que
    deixaria o usuário procurando um defeito que não existe.

#### Os quatro sinais testados para separar narrativa de apêndice

| Sinal | Situação |
|---|---|
| **Título conhecido** (`Créditos`, `Glossário`, `Notas`…) | **Usado.** O mais confiável, e o que pega a maioria dos casos |
| **Tamanho relativo à mediana do livro** | **Usado**, a 10%. Ver a varredura abaixo |
| **ISBN no texto** | **Usado.** Reconhece as páginas de "compre agora e leia", que não têm título nenhum |
| **Posição no índice** (raiz vs. aninhado) | **Descartado.** Vale em três livros e se inverte em três; contribuía com exatamente um item e escondia o *Processo* inteiro |

A varredura do limite de tamanho, sobre os nove primeiros livros — aqueles cuja classificação entre narrativa e apêndice foi feita à mão:

| Limite | Narrativa escondida | Apêndice mantido |
|---|---|---|
| 5% | 0 | 19 |
| **10%** | **0** | **14** |
| 12% | 1 | 11 |
| 15% | 2 | 10 |
| 25% | 2 | 5 |

Subir de 10% para 25% trocaria nove incômodos por dois fragmentos de *O Processo*
escondidos. Como esconder narrativa é muito pior que deixar um item para o
usuário desmarcar, o limite ficou em 10%. Os seis livros acrescentados depois
confirmaram a escolha: com esse limite, nenhum dos quinze esconde narrativa.

Os marcadores padrão do formato (`guide`, `landmarks`) também foram examinados e
**não servem**: em dois dos livros o marcador `type=text`, que significa "o corpo
do livro começa aqui", aponta para a própria capa.

#### Divisão por âncoras

Quando o índice aponta para **várias âncoras do mesmo arquivo**, o arquivo é cortado nesses pontos.

O corte acontece entre os filhos de um **contêiner**, que é o ancestral comum mais profundo de todas as âncoras. Na maioria dos livros esse contêiner é o próprio `<body>`, mas em *O Processo* o documento inteiro estava embrulhado num único `<div>`: cortar entre os filhos do corpo daria uma fatia só, e os onze fragmentos não se separariam. O que estiver fora do contêiner entra na primeira fatia (se vier antes) ou na última (se vier depois), para que nada de texto se perca.

Duas situações de borda, resolvidas no sentido de nunca perder texto:

- **Texto antes da primeira âncora.** O Calibre parte arquivos grandes em pedaços numerados, e o corte cai no meio de um capítulo — o arquivo seguinte começa com o resto do capítulo anterior. Em *Flores para Algernon* eram 42 mil caracteres. Esse trecho é marcado como continuação e **colado de volta** no capítulo anterior, em vez de virar um capítulo sem título.
- **Duas âncoras no mesmo filho do corpo.** Não há onde cortar, então as duas entradas viram um pedaço só, com o título da primeira. Juntar é preferível a arriscar perder texto.

#### Título de reserva, tirado do texto

Quando um capítulo não tem entrada no índice, o título é tirado da **primeira linha do próprio texto** — porque muitos livros põem o nome do capítulo no corpo e não no índice.

Duas condições evitam transformar a primeira frase da narrativa em título: a linha precisa ter no máximo 80 caracteres e não pode terminar em pontuação de frase. É o que separa "A GAROTA" de "— Levante-se." ou do parágrafo que abre a história.

Medido nos dezoito livros: dos 116 capítulos sem título no índice, **103 (89%) ganham um título sensato**. Em *Tress* são 73 de 80, recuperando os nomes reais dos capítulos; na coletânea de Frost, todos os 79 poemas ficam nomeados.

O título de reserva é resolvido **antes** da sugestão de ignorar, de propósito: se o texto começa com "Créditos", essa informação vale tanto quanto se viesse do índice. Verificado que isso não mudou nenhuma sugestão nos dezoito livros já validados.

#### Sugestão de capítulo ignorado

Um capítulo é **sugerido** como ignorado quando qualquer um destes vale:

1. O título começa com um rótulo conhecido de material não-narrativo (`Créditos`, `Glossário`, `Notas`, `Sobre o autor`, `Apêndice`, `Índice`, `Cronologia`…), comparado sem acento e em minúsculas.
2. O texto contém um **ISBN** — um número de 13 dígitos começando em 978 ou 979. É o que reconhece as páginas de "compre agora e leia" que os e-books comerciais trazem no fim: elas não têm título nenhum, então nenhum outro critério as pega, e um ISBN não aparece em prosa narrativa.
3. O texto tem menos de **10%** da mediana do próprio livro. O critério é relativo porque a mediana variou de **mil** caracteres (*Robert Frost*, poemas curtos) a **89 mil** (*Treasure Island*, um capítulo só) entre os dezoito livros — um limite fixo serviria para um e falharia nos outros.

E um critério **protege**, vencendo o de tamanho: um título claramente narrativo. Vale para:

- as palavras de estrutura, em português e em inglês: `Capítulo`, `Canto`, `Prólogo`, `Epílogo`, `Interlúdio`, `Parte`, `Livro`, `Relatório de Progresso`, `Chapter`, `Prologue`, `Epilogue`, `Part`, `Book`;
- um número ou numeral romano isolado (`15`, `XIV`);
- um título que **começa** com número e separador (`3 - AS MÃOS, OS PÉS E O VENTRE`, `36. O NÚMERO TRÊS`), que é como as coletâneas numeram os contos.

É o que salva o capítulo 26 de *O apanhador no campo de centeio*, com 11% da mediana do livro, e as fábulas de Esopo nas coletâneas, com 7%.

A ordem dos critérios é rótulo, ISBN, proteção, tamanho — do mais confiável ao mais frouxo. Na prática rótulo e proteção não colidem, porque a comparação de rótulo é por prefixo: um título que começa com número não casa com nenhum rótulo, então um hipotético "1. Prefácio" acaba mantido. É o erro seguro.

#### Resultado nos dezoito livros

| Livro | Capítulos | Sugeridos como ignorados |
|---|---|---|
| A Vontade de Muitos | 84 | 8 |
| Odisseia | 56 | 31 |
| Mistborn: O Império Final | 48 | 8 |
| O Poço da Ascensão | 67 | 7 |
| Tress, a garota do Mar Esmeralda | 84 | 12 |
| Flores para Algernon | 21 | 3 |
| Devoradores de Estrelas | 38 | 8 |
| Perdido em Marte | 31 | 5 |
| O apanhador no campo de centeio | 33 | 7 |
| O estrangeiro | 20 | 9 |
| O Processo | 23 | 2 |
| O Alienista | 19 | 5 |
| The Sherlock Holmes Handbook | 52 | 5 |
| Robert Frost: Selected Early Poems | 79 | 0 |
| Os 100 Melhores Contos de Humor | 105 | 4 |
| Os 100 Melhores Contos de Crime e Mistério | 104 | 4 |
| Treasure Island | 1 | 0 |
| Persépolis 2 | — | recusado, por ser livro de imagem |

**Nenhum capítulo narrativo é escondido em nenhum dos dezoito livros.** Alguns acertos que valem registro:

- *Flores para Algernon*: os 17 relatórios de progresso, remontados a partir de 13 arquivos em que as fronteiras eram âncoras.
- *Odisseia*: os 24 cantos limpos, com os 24 documentos de "Notas ao Canto" sugeridos.
- *O Processo*: os 12 capítulos do romance e os 11 fragmentos.
- *O apanhador no campo de centeio*: os 26 capítulos, inclusive o de número 26, com 1.523 caracteres — 11% da mediana — salvo pela proteção de título.
- *As duas coletâneas de contos*: os 100 contos de cada uma, inclusive fábulas de Esopo de 600 caracteres.
- *Robert Frost*: os 79 poemas, todos nomeados, nenhum sugerido — o mais curto tem 215 caracteres.
- *Tress*: os 75 capítulos, que não têm título no índice, agora nomeados a partir do texto.

#### Limitações conhecidas

**Livro num único documento.** *Treasure Island* empacota o romance inteiro num só arquivo de 88 mil caracteres, sem âncoras no índice e sem uma única tag de cabeçalho: sai como **um capítulo**, o que é pouco útil para o fluxo do sistema.

Dividir pelos marcadores de capítulo que existem no texto foi testado e **descartado com medição**. A heurística seria destrutiva nos outros livros: em *A Vontade de Muitos* e *Perdido em Marte* ela encontra 74 e 26 marcadores na página de sumário; nas duas coletâneas de contos, os marcadores `I`, `II`, `III` são divisões internas de um mesmo conto, e dividir ali quebraria contos em pedaços de 300 caracteres. E no próprio *Treasure Island* ela não dispara, porque os parágrafos estão aninhados em `div` em vez de soltos no corpo. Um capítulo grande de menos é melhor que contos estraçalhados; o caminho, se a necessidade voltar, é deixar o usuário dividir um capítulo à mão no app.

Esse mesmo arquivo também traz metadados de **outro livro** — declara-se *Death and the Afterlife in Ancient Egypt*, de John H. Taylor. Não há o que fazer: a importação é fiel ao que o arquivo declara.

**Livro de imagem.** Uma história em quadrinhos ou um livro digitalizado não tem texto para extrair, e é recusado com mensagem explicando isso. O Imagineer trabalha a partir do texto.

**Material não-narrativo que sobra.** Menos de um item por livro, em média — cada um a um toque de ser desmarcado.

---

## Etapa 3 — Modelagem de Dados

### 3.1 Entidades principais

- **Livro**: metadados do EPUB importado; possui um `PerfilRenderizacao` padrão.
- **Capítulo**: pertence a um Livro; contém o texto extraído do EPUB.
- **Elemento**: entidade genérica com campo `tipo` (enum: `PERSONAGEM`, `AMBIENTE`, `OBJETO`, `CRIATURA`, `GRUPO`, `VEICULO`, `EDIFICACAO`). Representa a *identidade* de algo recorrente na história (quem/o que é), não sua aparência num momento específico.
- **EstadoElemento**: como um Elemento está em um ponto específico da narrativa (aparência, roupas, ferimentos, condição). Pode referenciar uma imagem já gerada como âncora visual para gerações futuras daquele estado.
- **Frame**: recorte de um capítulo que vai virar uma imagem — um retrato solo de um Elemento (`tipo=PERSONAGEM`) ou uma cena com vários Elementos interagindo (`tipo=CENA`); referencia um ou mais Elementos (com seus Estados na ocasião); guarda atributos situacionais próprios (horário, clima, humor) diretamente nele — sem entidade "Contexto" separada. Chamava-se `Cena`; ver a divergência registrada no item 3.4c.
- **PerfilRenderizacao**: perfil de estilo visual (estilo, artista de referência, iluminação, paleta, formato, modelo alvo). Configurado por padrão a nível de Livro, com possibilidade de override pontual ao gerar um prompt específico.
- **Prompt**: registro de cada prompt gerado (modelo de IA usado, texto, data, resultado, imagem associada), permitindo regenerar ou comparar modelos depois.
- **Imagem**: arquivo final importado pelo usuário, com referência ao Prompt/Frame/Elementos de origem, compondo o catálogo.

### 3.2 Relacionamentos

- Um Elemento pode aparecer em vários Frames de vários Capítulos (muitos-para-muitos).
- Um Elemento tem vários EstadoElemento ao longo da história (um por "momento narrativo relevante").
- Um Frame referencia um ou mais Elementos (com o Estado vigente de cada um naquele ponto) — exatamente um, se `tipo=PERSONAGEM`.
- Um Prompt está associado a um Frame (e, por meio dele, aos Elementos/Estados usados como contexto) e a uma Imagem.

### 3.3 Decisões de modelagem (justificativas)

- **Elemento genérico em vez de tabelas por tipo**: personagens, ambientes, objetos, criaturas etc. compartilham a mesma necessidade — manter consistência visual ao longo da narrativa. Um enum `tipo` evita duplicação de schema e lógica.
- **EstadoElemento separado da identidade do Elemento**: personagens envelhecem, se ferem, trocam de roupa; objetos quebram; ambientes são destruídos/reconstruídos. Fixar uma única "descrição visual" no Elemento geraria inconsistência entre capítulos distantes da história.
- **Frame com atributos situacionais embutidos**: evita criar uma entidade "Contexto" isolada para informações (horário, clima) que já são naturalmente parte do próprio frame.
- **PerfilRenderizacao em vez de campo único de "estilo"**: permite reutilizar combinações de estilo/iluminação/paleta entre livros, e adaptar à ferramenta de geração de imagem usada (cada uma tem sintaxe própria).
- **Relações entre elementos e Grupos com membros explícitos**: ideia boa, mas adiada para uma v2 — exige tabela de relacionamento tipo grafo e telas extras no app; não é essencial para o MVP (Elemento + Estado + Frame + Prompt + Imagem).

### 3.4 Campos das entidades

Esta seção detalha as colunas de cada tabela. Foi preenchida em três partes, todas **implementadas**:

- **(a)** `Livro` e `Capitulo` — a base da importação do EPUB.
- **(b)** `Elemento` e `EstadoElemento` — o coração da consistência visual.
- **(c)** `Frame`, `PerfilRenderizacao`, `Prompt` e `Imagem` — a geração e o catálogo.

O modelo do MVP está completo: 9 tabelas, criadas por três migrations que encadeiam a partir de um banco vazio.

Decisões que valem para todas as tabelas:

- **Chave primária**: inteiro autoincremento. Legível na depuração ("capítulo 5 do livro 2"), índices menores — o que conta num Raspberry Pi — e suficiente porque só o servidor cria registros. UUID só faria sentido se o app precisasse criar registros offline, o que não está no escopo.
- **Nomes de tabela no plural** (`livros`, `capitulos`): a tabela guarda muitos; a classe, que representa um, fica no singular.

#### (a) Livro

Metadados do EPUB importado.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `titulo` | texto (500) | não | do metadado `dc:title` do EPUB |
| `autor` | texto (300) | **sim** | muitos EPUBs não preenchem |
| `idioma` | texto (20) | sim | código do metadado `dc:language` (ex: `pt-BR`) |
| `identificador_epub` | texto (200) | sim | o `dc:identifier` do arquivo (ISBN ou UUID) |
| `nome_arquivo` | texto (500) | não | nome original do arquivo enviado |
| `data_importacao` | data/hora com fuso | não | preenchido pelo banco na inserção |

`identificador_epub` é **indexado, mas não único**: serve para avisar que um livro já foi importado antes, e não para impedir. Muitos EPUBs pirateados ou convertidos repetem identificadores genéricos, e uma restrição de unicidade bloquearia importações legítimas.

`data_importacao` é preenchido pelo próprio banco (`NOW()`), não pelo Python. Assim o horário é o do servidor, consistente entre registros, independente do relógio de quem chamou a API.

**Pendente da parte (c):** o campo `perfil_renderizacao_padrao_id` previsto no item 3.1 só pode existir depois de a tabela `perfis_renderizacao` existir. Será acrescentado por uma migration na parte (c) — é exatamente esse tipo de evolução incremental que justifica o Alembic.

#### (a) Capitulo

Um capítulo de um Livro, com o texto extraído do EPUB.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `livro_id` | inteiro | não | referência ao Livro; indexado |
| `ordem` | inteiro | não | posição no livro, começando em 1 |
| `titulo` | texto (500) | **sim** | o índice do EPUB nem sempre nomeia o capítulo |
| `texto` | texto longo | não | conteúdo textual, sem limite de tamanho |
| `ignorado` | booleano | não | se este "capítulo" fica de fora do trabalho de catalogação; padrão falso |

Restrição de unicidade em (`livro_id`, `ordem`): dois capítulos não podem ocupar a mesma posição no mesmo livro. É o banco garantindo uma regra que um erro no parsing poderia violar silenciosamente.

`ordem` existe porque a sequência de leitura é definida pelo índice (TOC) do EPUB, e não pelo `id` — reprocessar um livro pode gerar ids em outra ordem. Toda listagem de capítulos ordena por este campo.

Apagar um Livro apaga seus Capítulos (`ON DELETE CASCADE`), em dois níveis: no banco e no ORM. Um capítulo não existe sozinho, sem o livro a que pertence.

`ignorado` existe porque todo EPUB traz, misturado aos capítulos, material que não é narrativa: créditos, glossário, agradecimentos, notas do tradutor, anúncios da editora. A importação **sugere** marcando este campo (ver item 2.2) e o usuário confirma — nada é descartado no parsing. Acrescentado depois da validação contra dezoito livros reais, que mostrou que nenhum critério automático separa os dois com segurança.

#### (b) Elemento

A **identidade** de algo recorrente na história: quem ou o que é. Não descreve aparência — isso é papel do EstadoElemento.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `livro_id` | inteiro | não | referência ao Livro; indexado |
| `tipo` | texto (20) + restrição | não | um dos valores do enum `TipoElemento` |
| `nome` | texto (200) | não | como o elemento é chamado na obra |
| `descricao` | texto longo | sim | quem/o que é: papel na história, natureza, função |

Valores de `tipo`: `PERSONAGEM`, `AMBIENTE`, `OBJETO`, `CRIATURA`, `GRUPO`, `VEICULO`, `EDIFICACAO`.

`GRUPO` existe como rótulo desde já (serve para agrupar "os Stark", "a Patrulha da Noite"), mas **sem membros explícitos** — a tabela de relacionamento que ligaria um grupo aos seus integrantes continua adiada para a v2, conforme o item 3.3.

Restrição de unicidade em (`livro_id`, `tipo`, `nome`): impede que a extração automática cadastre duas vezes o mesmo personagem no mesmo livro. Inclui o `tipo` porque um nome pode legitimamente designar coisas diferentes — a cidade *Winterfell* e a edificação *Winterfell* são registros distintos.

`descricao` aceita nulo: no momento em que o usuário confirma uma sugestão da IA, pode ainda não haver descrição de identidade definida.

#### (b) EstadoElemento

Como um Elemento **está** em um ponto específico da narrativa: aparência, roupas, ferimentos, condição.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `elemento_id` | inteiro | não | referência ao Elemento; indexado |
| `capitulo_id` | inteiro | não | capítulo em que este estado passa a valer; indexado |
| `descricao` | texto longo | não | a aparência em si — o que entra no prompt |
| `data_criacao` | data/hora com fuso | não | preenchido pelo banco |

`capitulo_id` é obrigatório porque todo estado nasce de um capítulo: é lá que o usuário confirma "possível novo estado" (passo 7 do fluxo). Se um dia surgir a necessidade de um estado sem capítulo de origem, tornar a coluna opcional é uma migration trivial — o caminho inverso é que seria difícil.

**Não** há unicidade em (`elemento_id`, `capitulo_id`): um personagem pode mudar duas vezes no mesmo capítulo (entra ferido, sai curado), e cada mudança é um estado.

##### Como se descobre o "último estado conhecido"

O item 4.4 depende de buscar o estado vigente de um elemento ao processar um capítulo. A ordenação **não** é por `data_criacao` nem por `id` do estado: o usuário pode processar os capítulos fora de ordem, ou revisitar um capítulo antigo. A ordem que importa é a **narrativa**, que vem de `Capitulo.ordem`.

A consulta, portanto, junta `EstadoElemento` com `Capitulo` e busca o estado mais recente entre os capítulos até o ponto atual:

```
estados do elemento X
  onde Capitulo.ordem <= ordem do capítulo sendo processado
  ordenado por Capitulo.ordem desc, EstadoElemento.id desc
  o primeiro
```

O `id` desc é o critério de desempate quando há mais de um estado no mesmo capítulo: os estados de um capítulo são gravados na ordem em que o usuário os confirma, então o maior `id` é o mais adiante na narrativa.

Esta consulta será implementada em `imagineer/servicos/` junto do item 4.4. Nesta parte (b) ela aparece apenas nos testes, provando que o modelo é capaz de respondê-la.

**Pendente da parte (c):** o campo `imagem_ancora_id` previsto no item 3.1 — a imagem já gerada que serve de âncora visual para gerações futuras — depende da tabela `imagens`. Será acrescentado por migration na parte (c).

#### (c) PerfilRenderizacao

O estilo visual a aplicar, separado dos dados narrativos.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `nome` | texto (100) | não | como você chama o perfil ("Aquarela sombria"); único |
| `estilo` | texto longo | sim | o estilo em si ("pintura a óleo", "quadrinho franco-belga") |
| `artista_referencia` | texto (200) | sim | artista cujo traço serve de referência |
| `iluminacao` | texto (200) | sim | ("contraluz de fim de tarde", "penumbra de vela") |
| `paleta` | texto (200) | sim | ("tons frios e dessaturados") |
| `formato` | texto (50) | sim | proporção ou enquadramento ("16:9", "retrato") |
| `modelo_alvo` | texto (100) | sim | ferramenta de imagem a que o perfil se adapta |

**Não pertence a um Livro.** É o que permite reaproveitar a mesma combinação de estilo entre obras diferentes — o motivo pelo qual o item 3.3 preferiu um perfil a um campo único de "estilo". O vínculo é o contrário: o Livro aponta para o seu perfil padrão.

Todos os campos de estilo aceitam nulo porque cada ferramenta de imagem entende um subconjunto diferente: um perfil voltado a uma delas pode não usar `artista_referencia`, outro pode não usar `formato`.

`modelo_alvo` existe porque cada ferramenta tem sintaxe própria — o mesmo estilo se escreve de um jeito numa e de outro jeito noutra.

#### (c) Frame

O recorte de um capítulo que vai virar uma imagem — um retrato solo ou uma cena.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `capitulo_id` | inteiro | não | referência ao Capítulo; indexado |
| `tipo` | enum (`PERSONAGEM`, `CENA`) | não | `PERSONAGEM` só aceita um estado ligado (item 4.4); padrão `CENA` |
| `titulo` | texto (300) | não | como identificar o frame na lista |
| `descricao` | texto longo | sim | o trecho ou o resumo do que acontece; vazio para `PERSONAGEM` |
| `horario` | texto (100) | sim | atributo situacional |
| `clima` | texto (100) | sim | atributo situacional |
| `humor` | texto (100) | sim | atributo situacional |
| `contexto_do_livro` | texto longo | sim | o que a leitura profunda do frame (item 4.4) confirmou no capítulo — só para `tipo=CENA` |
| `confirmado_pela_leitura_profunda` | booleano | não | se `contexto_do_livro` já foi lido; controla o modo `ECONOMIA` da `prioridade_ia` (item 4.3) |

Os três atributos situacionais ficam **no próprio Frame**, sem uma entidade "Contexto" separada: horário, clima e humor já são naturalmente parte dele, e uma tabela extra só acrescentaria uma junção (item 3.3).

**Sem campo `ordem`**, diferente do Capítulo. A ordem dos capítulos vem do índice do EPUB e precisa ser preservada explicitamente; os frames são criados pelo usuário enquanto lê um capítulo, então a ordem de criação já é a ordem narrativa. Acrescentar o campo depois é uma migration trivial, se a necessidade aparecer.

> **Divergência registrada, pós-validação com IA real.** Esta tabela chamava-se `Cena`, e não distinguia um retrato solo de um elemento de uma cena de verdade com vários elementos — a mesma entidade servia para as duas coisas. Um teste real expôs o problema: um prompt pedido para um personagem sozinho citou outro elemento por engano, porque a descrição do "recorte" (título + descrição livre) sempre entrava na montagem do prompt, mesmo quando a intenção era um retrato. A tabela foi renomeada para `Frame` — termo em inglês, escolhido deliberadamente pelo usuário como exceção à regra de idioma do `CLAUDE.md` por já ser um termo comumente entendido em português técnico, como "site" — e ganhou o campo `tipo` para tornar a intenção explícita, mais `contexto_do_livro` e `confirmado_pela_leitura_profunda` para a leitura profunda do frame (item 4.4). A migration renomeou tabela, colunas e restrições em vez de recriar, preservando os dados já existentes.

#### (c) Ligação entre Frame e EstadoElemento

Tabela de associação `frames_estados_elemento` (chamava-se `cenas_estados_elemento`), com as duas colunas formando a chave primária.

| Coluna | Observação |
|---|---|
| `frame_id` | referência ao Frame |
| `estado_elemento_id` | referência ao EstadoElemento |

A ligação é com o **Estado**, não com o Elemento. É isso que faz o frame guardar *como* cada elemento estava naquele ponto — que é o dado que entra no prompt. Ligar direto ao Elemento perderia essa informação, e o prompt não saberia qual das versões do personagem usar.

Não tem colunas próprias além das duas chaves, então é uma tabela simples de associação e não uma entidade do modelo.

#### (c) Prompt

O registro de cada prompt gerado, que permite regenerar e comparar modelos depois.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `frame_id` | inteiro | não | referência ao Frame; indexado |
| `perfil_renderizacao_id` | inteiro | sim | o perfil realmente usado |
| `modelo_ia` | texto (200) | sim | identificador do modelo no OpenRouter |
| `texto` | texto longo | não | o prompt em si, como foi copiado |
| `avaliacao` | texto longo | sim | sua anotação sobre como a imagem saiu |
| `data_criacao` | data/hora com fuso | não | preenchido pelo banco |

`perfil_renderizacao_id` guarda o perfil **usado naquela geração**, que pode ser o padrão do livro ou um override pontual. Aceita nulo, e apagar um perfil não apaga prompts (`ON DELETE SET NULL`): o histórico de prompts é mais valioso que a referência ao perfil, e perder um registro de prompt por causa de uma limpeza de perfis seria um prejuízo desproporcional.

`avaliacao` é a interpretação do campo "resultado" citado no item 3.1: um texto livre onde você anota como a imagem ficou ("acertou o rosto, errou a armadura"). É o que dá sentido a "comparar modelos depois" — sem a anotação, comparar exigiria reabrir as imagens e lembrar o que achou de cada uma.

`texto` guarda o prompt como foi copiado, e não os ingredientes para remontá-lo. Assim o registro continua fiel mesmo que o perfil de renderização ou a descrição de um estado mudem depois.

#### (c) Imagem

O arquivo importado de volta pelo usuário, compondo o catálogo.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `prompt_id` | inteiro | não | o prompt que originou a imagem; indexado |
| `caminho_arquivo` | texto (500) | não | caminho relativo dentro de `DIRETORIO_IMAGENS`; único |
| `data_importacao` | data/hora com fuso | não | preenchido pelo banco |

Só o **caminho** vai para o banco; o arquivo fica no volume dedicado (item 1.4). Guardar a imagem no banco engordaria o backup e as consultas sem nenhum ganho.

O caminho é **relativo**, não absoluto: mover a pasta de imagens ou trocar o Raspberry Pi não invalidaria todos os registros.

`prompt_id` é obrigatório: no fluxo do sistema, toda imagem do catálogo nasce de um prompt. Tornar a coluna opcional depois — para aceitar, por exemplo, uma imagem de referência externa — é uma migration trivial; o caminho inverso é que seria difícil.

> **Divergência do item 3.2:** ele diz que "um Prompt está associado a uma Imagem". Aqui a relação é de **um prompt para várias imagens**, sem restrição de unicidade em `prompt_id`. O motivo é prático: o mesmo prompt costuma ser gerado mais de uma vez, ou em duas ferramentas diferentes, e faz sentido guardar mais de um resultado no catálogo. Remover uma restrição de unicidade depois é fácil; acrescentá-la quando já existem dados duplicados é que dá trabalho.

#### (d) Configuracao

Uma linha única, com a configuração da integração com IA (item 4.3).

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária; sempre 1 |
| `chave_api_openrouter` | texto (200) | sim | cadastrada pelo app; sobrepõe a variável de ambiente |
| `modelo_extracao` | texto (200) | sim | modelo usado no passo 6 do fluxo |
| `modelo_prompt` | texto (200) | sim | modelo usado no passo 8 |

**Uma linha só, com `id` fixo em 1.** Não é a modelagem mais elegante, mas é a mais honesta para o que é: não existem "duas configurações" num sistema pessoal de um usuário. A alternativa — uma tabela de pares chave/valor — perderia a tipagem de cada campo e ganharia só flexibilidade que não vai ser usada. Uma restrição `CHECK (id = 1)` impede uma segunda linha aparecer por acidente.

Os três campos aceitam nulo porque o sistema precisa subir sem configuração nenhuma: a chave pode estar só na variável de ambiente, e os modelos podem ainda não ter sido escolhidos.

#### (c) As duas chaves estrangeiras pendentes

Com as tabelas acima criadas, os dois campos deixados de lado nas partes (a) e (b) passam a ser possíveis:

| Tabela | Coluna | Aponta para | Ao apagar o destino |
|---|---|---|---|
| `livros` | `perfil_renderizacao_padrao_id` | `perfis_renderizacao` | `SET NULL` |
| `estados_elemento` | `imagem_ancora_id` | `imagens` | `SET NULL` |

Ambas aceitam nulo, e ambas usam `SET NULL`: apagar um perfil de estilo não pode apagar o livro, e apagar uma imagem do catálogo não pode apagar o estado do personagem. A referência se desfaz, o dado narrativo permanece.

`imagem_ancora_id` é a "âncora visual" do item 3.1: uma imagem já aprovada daquele estado, que serve de referência nas gerações seguintes do mesmo personagem — o mecanismo que mantém a aparência consistente entre capítulos.

---

## Etapa 4 — Integração com IA

### 4.1 Provedor de IA

**OpenRouter** como ponto único de integração — agrega múltiplos modelos (incluindo opções gratuitas) atrás de uma API só, evitando escrever um adapter por fornecedor (Gemini, Groq etc.) na v1.

### 4.2 Interface abstrata

Camada de abstração `ProvedorIA` com quatro métodos:
- `extrair_elementos(texto_capitulo, estados_conhecidos, modelo) -> lista estruturada` — identifica **quem/o que aparece** no capítulo, e sugere frames do tipo `CENA` (passo 6, fase 1 — ver item 4.4).
- `sugerir_estado(texto_capitulo, elemento, estado_atual, modelo) -> descrição de aparência` — a **leitura profunda** de um elemento específico (fase 2 — ver item 4.4).
- `fundamentar_frame(texto_capitulo, titulo, descricao, horario, clima, humor, participantes, modelo) -> contexto` — confere "quem, onde, o quê" de um frame do tipo `CENA` contra o capítulo, sem sobrescrever o que o usuário escreveu (fase 3 — ver item 4.4).
- `montar_prompt(descricao_do_frame, elementos, perfil_renderizacao, modelo, contexto_do_livro, comentario_do_usuario) -> texto do prompt` — passo 8, combinando as fontes acima por ordem de prioridade (item 4.4).

Implementação concreta inicial: `ProvedorOpenRouter`, parametrizada por `id_modelo`. Os quatro métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que adivinhar o formato da resposta. Provedores nativos adicionais (Groq, Gemini) podem ser adicionados depois seguindo a mesma interface, se necessário.

> **Divergência registrada (item 1.5):** a primeira versão desta seção nomeava a interface como `AIProvider`, a implementação como `OpenRouterProvider` e o parâmetro como `render_profile`. Os nomes foram traduzidos para `ProvedorIA`, `ProvedorOpenRouter` e `perfil_renderizacao` por coerência com a regra de idioma: existe tradução natural, então o português prevalece. Definido antes de a pasta `ia/` ser preenchida, para não renomear código depois.

> **Divergência registrada, pós-validação com IA real (itens 4.4 e 6.6):** a versão original de `extrair_elementos` devolvia, numa passada só, tanto a identificação de cada elemento quanto uma descrição livre de aparência (`estado_sugerido`) e um veredito de continuidade (`manter_estado_atual`). Testado com `openai/gpt-4o-mini` num capítulo real de *A Vontade de Muitos*, esse desenho misturou atributos entre personagens (atribuiu o "joelho machucado" de um coadjuvante ao protagonista) — o modelo estava tentando descrever a aparência de nove elementos ao mesmo tempo na mesma resposta. Um teste com `google/gemini-2.5-flash` no mesmo capítulo, embora tenha corrigido esses erros, **inventou um elemento que não existe no texto** ("carroça de suprimentos"). O desenho passou a separar identificação (barata, ampla, sem descrição de aparência) de leitura profunda (focada, um elemento por vez, sempre lendo o capítulo de origem do estado) — ver item 4.4.

### 4.3 Configuração de modelos

Tela de configuração permitindo:
- Cadastro da API key do OpenRouter, nunca hardcoded.
- Seleção de modelo para extração de elementos (passo 6) e para montagem de prompt (passo 8), com opção "usar o mesmo modelo para os dois" marcada por padrão.
- Lista de modelos obtida dinamicamente do endpoint `/models` do OpenRouter (com filtro opcional para mostrar só os gratuitos).
- **Prioridade de IA** (`prioridade_ia`): `ECONOMIA` (padrão) ou `QUALIDADE` — controla se a leitura profunda do item 4.4 relê o capítulo toda vez que um prompt é montado, ou só da primeira vez por estado. Ver item 4.4 para o efeito exato. É um campo pensado para valer também em futuras decisões de custo-vs-qualidade no sistema, não só nesta.

#### De onde vem a chave

**Da variável de ambiente `CHAVE_API_OPENROUTER`, ou do banco — e o banco tem precedência.**

A variável de ambiente faz o sistema subir já configurado e nunca põe a chave num backup de banco. O cadastro pelo app existe porque o servidor roda num Raspberry Pi: trocar de chave ou de modelo não deveria exigir SSH, editar o `.env` e reiniciar o container.

Quem preferir só a variável de ambiente simplesmente nunca usa a tela, e nada muda.

**`GET /configuracao` nunca devolve a chave**, só informa se existe e de onde veio. Uma chave que sai do servidor é uma chave que vaza em log, em cache de app ou numa captura de tela.

#### Sobre o tamanho do capítulo caber no modelo

Medido nos dezoito livros de validação, em tokens estimados (a 4 caracteres por token):

| | Tokens |
|---|---|
| Mediana dos 747 capítulos úteis | 3.442 |
| Percentil 90 | 8.704 |
| Maior capítulo | 27.839 |

Quantos capítulos **não** caberiam, deixando 2.000 tokens de folga para instrução e resposta:

| Janela do modelo | Capítulos que não cabem |
|---|---|
| 8 mil | 203 de 747 — **27%** |
| 16 mil | 12 — 1,6% |
| 32 mil | **0** |

Conferido contra o endpoint `/models`: dos 21 modelos gratuitos disponíveis, **todos têm 32 mil de contexto ou mais**, vários com um milhão. Então **não há divisão de capítulo em partes** neste sistema: o texto vai inteiro, e a rota verifica o `context_length` do modelo escolhido antes de chamar — se não couber, a resposta diz qual é o problema em vez de deixar a API do modelo recusar com uma mensagem genérica.

Essa checagem prévia é o que evita o pior caso: descobrir que o capítulo não cabe **depois** de gastar a chamada.

#### O que foi implementado

A camada de IA inteira, com 33 testes e **nenhuma chamada de rede nos testes**:

| Arquivo | Papel |
|---|---|
| `ia/provedor.py` | O contrato `ProvedorIA` e os tipos que ele devolve |
| `ia/openrouter.py` | `ProvedorOpenRouter`: lista modelos e faz as duas chamadas |
| `ia/falso.py` | `ProvedorFalso`, para testes e para percorrer o sistema sem chave |
| `servicos/configuracao_ia.py` | Resolve de onde vem a chave e monta o provedor |
| `rotas/configuracao.py` | `GET`/`PUT /configuracao` e `GET /configuracao/modelos` |

O `ProvedorOpenRouter` é testado com um transporte falso do `httpx`, que responde o que o teste combinar. É o que permite testar o que uma chamada real raramente produziria na hora certa: resposta sem JSON, JSON embrulhado em cerca de markdown, frase de conversa antes do JSON, entrada com tipo inexistente, chave recusada, 429 de limite de uso e timeout.

**A leitura do JSON é tolerante de propósito.** Modelos põem cerca de markdown e escrevem "Claro! Aqui está:" mesmo quando a instrução pede o contrário — recusar por isso desperdiçaria uma chamada que na verdade deu certo. E uma entrada malformada é descartada em silêncio em vez de derrubar as outras vinte: é sugestão, e o usuário confirma tudo de qualquer forma.

**Um defeito achado numa chamada real.** O filtro de modelos de texto checava se `text` estava entre as saídas do modelo — e `google/lyria-3-pro-preview`, que é um modelo de **música**, declara `output_modalities: ["text", "audio"]`. Ele passava. O critério passou a ser "a saída é só texto", e a lista de gratuitos com 32 mil de contexto caiu de 21 para 19 modelos. A entrada pode incluir imagem ou vídeo sem problema: um modelo multimodal continua sabendo ler um capítulo.

Também descobri, na mesma chamada, que **os 458 modelos declaram modalidades** — então o caminho de reserva do filtro ("sem a informação, assume texto") não é exercitado hoje. Ficou como proteção contra o campo desaparecer da API: nesse caso é melhor a lista vir completa demais do que vazia, que deixaria o usuário sem como configurar.

### 4.4 Regra de decisão de novo Estado

A extração é **semi-automática**: a IA sugere, o usuário confirma. Isso evita depender de uma regra algorítmica perfeita para decidir sozinha se um capítulo representa mudança de estado. Depois de testar com IA real (ver a divergência registrada no item 4.2), o processo virou **duas fases**, para o texto do livro — e não um resumo apressado de vários elementos numa resposta só — ser sempre a fonte da descrição de aparência que chega ao prompt de imagem.

#### Fase 1 — Identificação (passo 6)

`POST /capitulos/{id}/sugestoes` continua chamando `extrair_elementos` com o texto do capítulo inteiro e o último estado conhecido de cada elemento já cadastrado. Devolve, para cada elemento encontrado: `tipo`, `nome`, `descricao` (identidade — quem ou o que é, não muda) e `manter_estado_atual` (um julgamento leve, comparando com o contexto de estados conhecidos). **Não devolve mais uma descrição de aparência** (`estado_sugerido` foi removido) — é exatamente essa parte que, tentando descrever vários elementos ao mesmo tempo, misturou atributos entre personagens num teste real.

O usuário revisa a lista (passo 7): confirma, ajusta ou descarta cada elemento, e cadastra o `Elemento` com um primeiro `EstadoElemento` — a descrição desse primeiro estado pode ser digitada à mão, ou ficar vaga/curta por enquanto, porque a fase 2 é quem vai efetivamente derivá-la do livro antes de qualquer prompt ser montado.

**A mesma chamada também sugere cenas.** Revisão feita a partir de um teste real seu: a extração original só listava elementos soltos ("quem existe no capítulo"), sem indicar quais combinações formam um momento que vale a pena ilustrar — e um jogo de tabuleiro saiu classificado como `AMBIENTE`, uma porta como `VEICULO`. Dois ajustes:

- `extrair_elementos` devolve, além de `elementos`, uma lista `frames`: recortes narrativos específicos do tipo `CENA` (título, descrição, horário/clima/humor quando o texto sustenta, e os participantes — por nome, casados contra os elementos já cadastrados do mesmo jeito que a lista de elementos já fazia). É rascunho, não grava nada — o usuário usa isso para pré-preencher `POST /capitulos/{id}/frames` em vez de montar cada cena do zero. Um frame sugerido sem nenhum participante é descartado (mesma tolerância a entrada malformada do item 4.2).
- A instrução ganhou definições explícitas de cada `tipo` (o que distingue `OBJETO` de `VEICULO`, `AMBIENTE` de `EDIFICACAO`) e um filtro de relevância para objetos — só inclui um objeto com peso visual memorável na cena, não papelada ou móvel genérico de fundo.

Testado com `gpt-4o-mini` no capítulo I de *A Vontade de Muitos*: da segunda vez, o tabuleiro saiu corretamente como `OBJETO`, e a extração sugeriu cinco cenas cobrindo os momentos certos do capítulo (o resgate na rocha, a partida de tabuleiro, a chegada de Hospius, o interrogatório de Nateo, o contato acidental com o Sapador) — nenhuma delas precisou ser inventada pelo usuário.

#### Fase 2 — Leitura profunda do elemento (passo 8, dentro de `POST /frames/{id}/prompts`)

Antes de montar o prompt, para **cada** estado ligado ao frame, o servidor relê o texto do **capítulo onde aquele estado foi originalmente registrado** (não necessariamente o capítulo do frame) e chama `sugerir_estado`, focando num elemento por vez — é essa concentração, um elemento por chamada, que evita a mistura de atributos da fase 1 antiga. O texto que volta:

- **Sobrescreve** `EstadoElemento.descricao` no banco — o livro é a fonte de verdade para a aparência de um elemento, mesmo que substitua o que foi digitado à mão no passo 7. Capítulos futuros que usam "o último estado conhecido" como contexto (fase 1) também passam a se beneficiar da versão mais fiel.
- É o que entra na montagem do prompt.

Vale tanto para um frame `PERSONAGEM` quanto para um `CENA` — os dois têm elementos com estado, e os dois se beneficiam de uma aparência bem descrita.

#### Fase 3 — Fundamentação do frame (só para `tipo=CENA`)

Um retrato (`tipo=PERSONAGEM`) não tem "quem, onde, o quê" para conferir — é sempre um elemento só. Uma cena (`tipo=CENA`) tem, e é aqui que o teste com IA real expôs um problema de origem: a entidade que hoje é `Frame` chamava-se `Cena` e servia para os dois casos, então a descrição livre de uma cena (que podia citar outros elementos por nome) sempre entrava no prompt de um retrato — mesmo quando a intenção era um retrato solo.

Por isso, para `tipo=CENA` com pelo menos um elemento ligado, o servidor também chama `fundamentar_frame`: relê o capítulo do frame, e confere o que o usuário escreveu (título, descrição, horário, clima, humor) contra o texto, com a aparência de cada participante já estabelecida como contexto. O resultado (`contexto`):

- **Não sobrescreve** `titulo`/`descricao` do frame — fica só em `Frame.contexto_do_livro`, como apoio.
- Entra em `montar_prompt` com prioridade **menor** que a descrição que o usuário escreveu (ver "Ordem de prioridade" abaixo) — feedback direto do usuário: uma releitura automática não deveria poder sobrepor o que uma pessoa que já leu o capítulo escreveu, sob risco de uma alucinação ou ambiguidade da IA divergir do que está confirmado.

Testado com IA real: a fundamentação de uma cena chegou a reler o trecho **errado** do capítulo (um momento bem posterior ao que a cena descrevia) — e o prompt final saiu correto mesmo assim, porque a prioridade protegeu a descrição do usuário. É a ordem de prioridade funcionando como rede de segurança contra a própria leitura automática errar.

#### Releitura tem custo: `prioridade_ia` controla as duas fases

Repetir a fase 2 e a fase 3 toda vez que um prompt é montado para o mesmo frame tem custo: cada chamada de `sugerir_estado`/`fundamentar_frame` é uma chamada de IA a mais, em cima da chamada que monta o prompt em si. Por isso existe `prioridade_ia` (item 4.3), valendo igualmente para as duas:

- **`QUALIDADE`**: relê o capítulo de origem de cada estado, e fundamenta o frame de novo, toda vez que `POST /frames/{id}/prompts` é chamado.
- **`ECONOMIA`** (padrão): relê só a primeira vez. `EstadoElemento.confirmado_pela_leitura_profunda` marca se aquele estado já passou pela fase 2; `Frame.confirmado_pela_leitura_profunda` marca o mesmo para a fase 3 do frame. Enquanto marcados, chamadas seguintes reaproveitam o que já foi lido, sem gastar outra chamada de IA.

#### Ordem de prioridade na montagem final do prompt

Quando há conflito entre as fontes que chegam a `montar_prompt`, a ordem é:

1. **Comentário do usuário** (campo `comentario` do pedido) — prioridade máxima. É uma correção de quem já viu o resultado anterior ou releu o capítulo com atenção.
2. **Descrição do frame escrita pelo usuário** (`titulo`/`descricao`/`horario`/`clima`/`humor`) — vazia para `tipo=PERSONAGEM` (não referencia nada além do elemento).
3. **Contexto do livro** (`fundamentar_frame`, só para `tipo=CENA`) — a leitura automática, usada só para preencher o que a descrição do usuário não cobriu, nunca para contradizê-la.

Não existe rota separada de "refinar": gerar de novo com um comentário é a mesma rota (`POST /frames/{id}/prompts`), chamada de novo — o histórico de tentativas já fica em `GET /frames/{id}/prompts`.

### 4.5 Engenharia das instruções de IA

Revisão feita a partir de material técnico externo (um documento de boas práticas de engenharia de prompt de imagem, preparado com apoio do Gemini) confrontado com o que já estava validado neste projeto. A regra ao incorporar algo foi: **adotar a técnica de escrita das instruções, sem reabrir a modelagem de dados já testada** — a alternativa (um JSON rico por elemento, com campos separados para material, iluminação, objetos etc.) foi considerada e descartada, ver Etapa 5.

#### O que foi incorporado

- **Descrição concreta, não adjetivo vazio.** `_INSTRUCAO_DE_ESTADO` (fase 2) e `_INSTRUCAO_DE_PROMPT` (passo 8) agora pedem material e textura (linho puído, couro rachado) em vez de qualificadores ("roupas simples"), e proíbem adjetivos subjetivos de qualidade ("lindo", "incrível", "épico") — um modelo de imagem não sabe o que fazer com "lindo", mas sabe o que fazer com "seda ao luar".
- **Emoção como física, não como palavra.** Em vez de "ele estava triste", a instrução pede a tradução em postura e expressão visíveis ("olhar baixo, ombros curvados") — a mesma lógica de "não confiar em metáfora literária" que já regia a leitura profunda, agora explícita para a IA.
- **Instantâneo congelado.** Modelos de imagem não representam ação contínua ("ele entra, pega o livro e sai"). As duas instruções agora pedem explicitamente uma pose ou gesto parado, específico do capítulo.
- **Template estruturado em `montar_prompt`.** O prompt final passa a seguir uma ordem fixa de blocos — enquadramento de câmera → sujeito num instante congelado → vestuário/textura/expressão → cenário imediato → fundo/arquitetura/época → iluminação/atmosfera → estética final — com vocabulário de fotografia/cinema (medium shot, golden hour, cool moonlight) para o resultado parecer uma adaptação cinematográfica, não uma ilustração genérica.
- **Identidade vs. situação.** `_INSTRUCAO_DE_ESTADO` passa a separar o que tende a não mudar entre capítulos (rosto, cor de cabelo, altura, compleição) do que muda com a cena (roupa, ferimento, sujeira) — preserva o primeiro a menos que o texto diga o contrário, atualiza o segundo com o que o capítulo mostra. É um reforço direto contra o problema de consistência de personagem entre capítulos distantes.
- **Referências visuais na resposta do prompt.** O campo `EstadoElemento.imagem_ancora_id` já existia desde o item 3.1, mas nunca tinha sido lido por nenhuma rota. `PromptDetalhe` (item 6.6) ganhou `referencias_visuais`: as imagens-âncora já aprovadas para os elementos da cena, para o app avisar "anexe esta imagem também" ao usuário — o fluxo de geração é manual (passo 9), então a API não anexa a imagem sozinha, só avisa que ela existe.

#### O que foi avaliado e descartado

- **Esquema JSON rico por elemento** (campos separados como `physical_description`, `clothing`, `architecture_and_materials`, `key_objects_in_scene`), em vez do texto livre único em `EstadoElemento.descricao`. Reabriria uma modelagem já testada de ponta a ponta (item 3.4b), exigiria migration e mexeria em toda a cadeia de rotas por um ganho que a mudança de instrução já entrega em boa parte: pedir para a IA *escrever* com esse nível de concretude no texto livre, em vez de *estruturar* isso em campos.
- **"Chunking" do capítulo** (dividir em blocos menores antes de mandar para a IA). O item 4.3 já mediu isso nos dezoito livros de validação: todos os modelos gratuitos com 32 mil de contexto ou mais comportam o maior capítulo medido inteiro. Dividir criaria um problema novo — cada pedaço perderia o contexto dos outros, piorando exatamente a mistura de atributos que a fase 2 já resolve ao ler o capítulo inteiro.
- **Fallback por gênero/tom do livro** quando um capítulo não descreve a aparência de um elemento (a sugestão era "deduzir a estética a partir do gênero"). Rejeitado: é a mesma classe de erro que produziu a "carroça de suprimentos" inventada no teste com `gemini-2.5-flash` (item 4.2). A regra do projeto continua sendo devolver a descrição já registrada e não inventar nada — o livro é a fonte de verdade, não o gênero.
- **Geração de imagem automatizada via OpenRouter** (modelos como FLUX.1/SDXL, com um padrão `Strategy`/`Adapter` para trocar de provedor). É uma mudança de arquitetura real — o passo 9 do fluxo (item 2.1) é deliberadamente manual, e automatizar geração envolve custo por imagem, escolha de provedor e um fluxo de UI diferente do que a Etapa 7 já esboçou. Fica como ideia registrada para uma decisão futura, não decidida nesta rodada.
- **Prefixo de texto para colar direto no Gemini** ("Crie uma imagem fotorrealista horizontal..."). É uma questão de UX do app (Etapa 7), e o app ainda não existe — fica anotado no item 7.7 (tela de Prompt) como algo a considerar quando a tela for implementada, não no backend.

---

## Etapa 5 — Decisões Técnicas e Justificativas

| Decisão | Motivo |
|---|---|
| Python + FastAPI em vez de Java + Spring Boot | `ebooklib` mais maduro que as opções Java para parsing de EPUB; footprint mais leve no Raspberry Pi; chamadas assíncronas naturais para IA; oportunidade de aprendizado (conhecimento básico prévio em Python) |
| OpenRouter como gateway único de IA | Evita multiplicar adapters por fornecedor; ainda permite ao usuário escolher modelo; tem opções gratuitas |
| Elemento genérico com enum `tipo` | Reduz duplicação de schema entre personagens/ambientes/objetos/criaturas |
| EstadoElemento separado do Elemento | Elementos mudam de aparência ao longo da narrativa; é essencial para consistência visual entre capítulos |
| Frame sem entidade "Contexto" separada | Informação situacional já é natural do próprio frame; evita tabela desnecessária |
| PerfilRenderizacao em vez de campo único de estilo | Permite reaproveitar/trocar estilo visual sem alterar dados narrativos; adapta-se a diferentes ferramentas de geração |
| Extração semi-automática (não totalmente automática) | Decisão de "novo estado ou não" fica sob controle do usuário, evitando erros de uma IA decidindo sozinha |
| Relações/Grupos adiados para v2 | Complexidade real (modelo tipo grafo + telas extras) não essencial para o MVP |
| Backend organizado por responsabilidade (modelos/esquemas/rotas/serviços/ia) | Mantém a regra de negócio independente de HTTP e de banco, o que a torna testável isoladamente; cada item novo tem um destino óbvio |
| Alembic desde o primeiro item, em vez de `create_all()` | O modelo de dados vai mudar muito nos próximos itens; `create_all()` exigiria apagar e recriar o banco a cada ajuste, e adotar Alembic depois daria retrabalho |
| `requirements.txt` + venv em vez de Poetry/uv | Transparência: o arquivo lista exatamente o que está instalado; funciona igual no PC de desenvolvimento e no Raspberry Pi, sem ferramenta extra para aprender agora |
| `psycopg` (v3) em vez de `psycopg2` | Tem wheels pré-compiladas para ARM64, evitando compilar driver no Raspberry Pi |
| Testes com prefixo `teste_` | Coerência com a regra de idioma; custa uma linha de configuração no pytest |
| Convenção de nomes para índices e restrições na `Base` | Sem ela o banco inventa os nomes, e cada ambiente fica com um nome diferente — impedindo que uma migration futura remova ou altere a restrição, porque precisa citá-la pelo nome. Definida antes da primeira migration de propósito |
| Chave primária inteira autoincremento | Legível na depuração, índices menores (conta num Raspberry Pi) e suficiente porque só o servidor cria registros; UUID só se o app precisasse criar dados offline |
| Porta do PostgreSQL publicada em `127.0.0.1:5432`, não em `0.0.0.0` | Permite rodar o Alembic e clientes de SQL na própria máquina, sem expor o banco para a rede que alcança o Raspberry Pi |
| Migrations com funções `aplicar`/`reverter` | Mantém a regra de idioma; os nomes `upgrade`/`downgrade` exigidos pelo Alembic ficam como apelidos no fim do arquivo |
| `tipo` do Elemento como VARCHAR + restrição CHECK, não ENUM nativo do PostgreSQL | Acrescentar um tipo novo é uma migration curta (trocar a restrição). Com ENUM nativo, o Alembic não detecta a mudança sozinho e **remover** um valor exige criar um tipo novo, converter a coluna e apagar o antigo |
| Unicidade do Elemento por (`livro_id`, `tipo`, `nome`) | Barra o cadastro duplicado que a extração automática produziria ao reencontrar o mesmo personagem em outro capítulo; o `tipo` entra na chave porque um nome pode designar coisas distintas (a região e o castelo Winterfell) |
| Ordem narrativa derivada de `Capitulo.ordem`, não de `data_criacao` nem do `id` do estado | O usuário pode processar capítulos fora de ordem ou revisitar um antigo — ordenar pela criação daria a resposta errada ao item 4.4 |
| Fora do Docker, conectar no banco por `127.0.0.1` e não por `localhost` | No Windows, `localhost` resolve para IPv6 (`::1`) antes de IPv4 e o Docker publica a porta só em IPv4: a conexão espera o timeout expirar antes de tentar o endereço certo, o que parece um travamento |
| Associação Frame ↔ **EstadoElemento**, não Frame ↔ Elemento | É o que faz o frame registrar *como* cada elemento estava naquele ponto. Ligado ao Elemento, o frame não saberia qual das versões do personagem usar no prompt |
| `PerfilRenderizacao` sem `livro_id`; é o Livro que aponta para o perfil | Se o perfil pertencesse a um livro não daria para reaproveitá-lo em outro — que é o motivo de ele existir como entidade (item 3.3) |
| `ON DELETE SET NULL` nas referências a perfil e a imagem-âncora | Apagar um perfil de estilo ou uma imagem do catálogo não pode apagar o dado narrativo. A referência se desfaz, o livro e o estado do personagem permanecem |
| Um Prompt para **várias** Imagens, divergindo do item 3.2 | Na prática o mesmo prompt é gerado mais de uma vez, ou em duas ferramentas diferentes, e faz sentido guardar mais de um resultado. Remover uma restrição de unicidade depois é fácil; acrescentá-la sobre dados já duplicados é que dá trabalho |
| Campo "resultado" do item 3.1 implementado como `avaliacao` (texto livre) | É o que dá sentido a "comparar modelos depois": uma nota numérica diria que um modelo foi melhor, mas não em quê — e é o "em quê" que ajuda a escrever o próximo prompt |
| Apenas o caminho da imagem no banco, e relativo | O arquivo fica no volume dedicado (item 1.4): guardá-lo no banco engordaria backup e consultas. Relativo para que mover a pasta ou trocar o Raspberry Pi não invalide todos os registros |
| Ordem e conteúdo dos capítulos vindos do **spine**, títulos vindos do **TOC** | Cada fonte resolve metade do problema: o spine é a ordem de leitura e está sempre presente, mas não traz títulos; o TOC traz títulos, mas é opcional, pode ser aninhado e pode apontar para âncoras |
| Extração (`extrair_epub`) separada da gravação (`importar_epub`) | O parsing é onde mora a complexidade e onde os testes precisam variar muito; testar isso não deveria exigir um banco no ar |
| EPUB lido de `BytesIO`, sem arquivo temporário | O `read_epub` do `ebooklib` aceita um objeto de arquivo, então os bytes do upload passam adiante como estão — menos uma coisa para limpar depois e menos uma falha possível em disco cheio |
| Descarte de documentos com menos de 100 caracteres | Capas, folhas de rosto e páginas de créditos existem em quantidade em todo EPUB e viriam como capítulos. O limite é baixo o bastante para não ameaçar um capítulo curto de verdade |
| `ordem` atribuída **depois** dos descartes | Vinda da posição no arquivo, a numeração pularia justamente as páginas descartadas, e a listagem no app teria buracos |
| Conversão de HTML para texto com `lxml`, sem BeautifulSoup | O `lxml` já vem como dependência do `ebooklib`; acrescentar `bs4` seria uma biblioteca a mais para o mesmo resultado |
| Exceção própria `ArquivoEpubInvalido` | Um arquivo corrompido viraria erro 500 sem explicação, com traço de pilha do `zipfile` no log, em vez de uma mensagem que o app possa mostrar |
| Identificador do livro vindo do `unique-identifier` declarado, não do primeiro `dc:identifier` | Um EPUB real listava cinco identificadores e o declarado era o último. Usar o primeiro faria a detecção de livro repetido depender da ordem em que o arquivo foi escrito |
| Página de navegação detectada pela proporção de texto dentro de links | Um "Sumário" em XHTML comum não é marcado como navegação pelo formato. Medido num livro real: 99,3% em 86 links na página de sumário, contra 20,5% no segundo colocado e nenhum link em 81 dos 85 documentos |
| Capítulos divididos pelas âncoras do índice quando ele é mais fino que os arquivos | Em *Flores para Algernon*, um arquivo continha 11 relatórios de progresso e a importação produzia um capítulo de 131 mil caracteres. As fronteiras que valem são as que o livro declara |
| Corte feito no ancestral comum das âncoras, não nos filhos do `<body>` | Em *O Processo* o documento estava inteiro dentro de um único `<div>`, e cortar entre os filhos do corpo dava uma fatia só |
| Posição no índice **descartada** como sinal | Em *O Processo* a única seção aninhada é o apêndice e os doze capítulos estão na raiz: o sinal se inverte e esconde o romance inteiro. Contribuía com exatamente um item nos dezoito livros |
| Anúncios de outros livros reconhecidos pelo ISBN no texto | Essas páginas não têm título nenhum, então nenhum critério de título as pega. Um número de 13 dígitos começando em 978 ou 979 não aparece em prosa narrativa |
| Texto antes da primeira âncora colado no capítulo anterior | O Calibre parte arquivos grandes no meio de um capítulo; sem isso, 42 mil caracteres do relatório anterior virariam um capítulo sem título e o relatório apareceria partido em dois |
| Material não-narrativo **sugerido** como ignorado, não descartado | Medição em dezoito livros: nenhum dos quatro sinais testados separa narrativa de apêndice com segurança. Esconder narrativa é muito pior que listar um glossário, então nada é descartado — a importação sugere e o usuário confirma |
| Limite de tamanho **relativo à mediana do livro**, não absoluto, e fixado em 10% | A mediana variou de **mil** caracteres numa coletânea de poemas a **89 mil** num livro que é um capítulo só, então um limite fixo serviria para um e falharia nos outros. Os 10% saíram de uma varredura: acima disso começa a esconder narrativa |
| Chave do OpenRouter aceita duas variáveis de ambiente: `CHAVE_API_OPENROUTER` e `IMAGINEER_KEY_OPEN_ROUTER` | Allan já mantém `IMAGINEER_KEY_OPEN_ROUTER` como variável de conta, fora deste projeto. Aceitar as duas (via `AliasChoices` do Pydantic) evita obrigá-lo a renomear algo que já existe no ambiente dele, sem abrir mão do nome em português como principal — é uma exceção pontual à regra de idioma do `CLAUDE.md`, feita conscientemente e só no nome da variável de ambiente, não no código |
| Extração de elementos dividida em identificação (fase 1) e leitura profunda (fase 2), em vez de uma chamada só | Testado com IA real (`gpt-4o-mini` e `gemini-2.5-flash`) num capítulo de *A Vontade de Muitos*: pedir a descrição de aparência de vários elementos na mesma resposta produziu mistura de atributos entre personagens e, num dos modelos, um elemento inventado. Descrever um elemento por vez, relendo o capítulo de origem, é o que reduz isso — ver item 4.4 |
| Leitura profunda sobrescreve `EstadoElemento.descricao`, em vez de só alimentar o prompt daquela vez | O livro é a fonte de verdade, e o usuário pode gerar uma cena antes de ter lido o capítulo pessoalmente — não dá para depender da revisão dele como garantia de qualidade. Sobrescrever também beneficia capítulos futuros, que usam "o último estado conhecido" como contexto da fase 1 |
| `prioridade_ia` (`ECONOMIA`/`QUALIDADE`) como campo de configuração, não parâmetro por chamada | Decisão de custo-vs-qualidade que o usuário quer controlar uma vez, na tela de configuração, e que deve valer para outras decisões parecidas no futuro — não é específica da leitura profunda |
| Comentário do usuário no corpo de `POST /frames/{id}/prompts`, sem rota separada de "refinar" | Gerar de novo com uma correção é a mesma operação de gerar um prompt, só com mais um dado de entrada; o histórico de tentativas já existe via `GET /frames/{id}/prompts`, então uma rota dedicada não acrescentaria nada que a existente não faça |
| `Cena` renomeada para `Frame`, com campo `tipo` (`PERSONAGEM`/`CENA`) | Um teste real mostrou a mesma entidade servindo, sem distinção, tanto para um retrato solo quanto para uma cena de verdade — a descrição livre de uma cena vazava para o prompt de um retrato. `Frame` é termo em inglês, escolhido deliberadamente pelo usuário (como exceção à regra de idioma, citando "site" como precedente de termo estrangeiro naturalizado) por já cobrir os dois sentidos sem ambiguidade |
| Fundamentação do frame (`fundamentar_frame`) não sobrescreve o que o usuário escreveu, ao contrário da leitura profunda do elemento | Pedido explícito do usuário: a escrita à mão de quem já leu o capítulo deve ter prioridade sobre a IA que monta o prompt, para uma alucinação ou ambiguidade da releitura automática não divergir do que foi confirmado. Validado com IA real: a fundamentação leu o trecho errado do capítulo, e o prompt final saiu correto porque a prioridade protegeu a descrição do usuário |
| Engenharia de prompt incorporada como reescrita de instrução, não como esquema JSON rico por elemento | Revisão de um material externo (item 4.5) sugeria campos estruturados por elemento (material, iluminação, objetos). Pedir para a IA *escrever* com esse nível de concretude no texto livre já existente entrega boa parte do ganho sem reabrir a modelagem do item 3.4b nem migrar dados |
| `referencias_visuais` em `PromptDetalhe`, lida a partir de `EstadoElemento.imagem_ancora_id` | O campo existia desde o item 3.1 mas nunca tinha sido lido por nenhuma rota — a consistência de personagem entre capítulos distantes dependia só da descrição em texto. Expor as imagens-âncora dos elementos da cena permite ao app avisar o usuário para anexá-las também, já que o fluxo de geração é manual (passo 9) |
| "Chunking" de capítulo e fallback por gênero/tom do livro, ambos descartados (item 4.5) | O primeiro fragmentaria o contexto que a leitura profunda depende de ter inteiro (item 4.3 já mediu que nenhum capítulo do corpus de validação excede a janela dos modelos gratuitos); o segundo é a mesma classe de erro que produziu o elemento inventado ("carroça de suprimentos") num teste real — o livro é a fonte de verdade, não o gênero |
| Geração de imagem automatizada (FLUX.1/SDXL via OpenRouter) não adotada nesta rodada | É mudança de arquitetura real, não afinação de prompt: custo por imagem, escolha de provedor e uma UI diferente da que a Etapa 7 já esboçou (fluxo manual de copiar/colar, passo 9). Registrada como ideia para decisão futura, não decidida sem o usuário |
| `extrair_elementos` também sugere `cenas` (recortes narrativos), na mesma chamada da fase 1 | Feedback do usuário revisando uma extração real: uma lista de elementos soltos não bastava, faltava sugerir quais combinações formam um momento que vale ilustrar. Juntar na mesma chamada evita reler o capítulo inteiro de novo só para esse fim |
| Filtro de relevância para objetos, e definições explícitas de cada `tipo` na instrução de extração | O mesmo teste real mostrou objetos irrelevantes (papelada genérica) e classificação errada (tabuleiro como `AMBIENTE`, porta como `VEICULO`). A instrução ganhou exemplos e um critério — "teria peso visual memorável?" — para reduzir os dois problemas |

---

## Etapa 6 — Rotas da API

Os endpoints que o app mobile consome. O desenho cobre o fluxo inteiro da Etapa 2; a implementação vem em fatias, e cada rota abaixo diz em que estado está.

### 6.1 Convenções

**Idioma e forma.** Caminhos, campos e mensagens em português. Recursos no plural (`/livros`, `/capitulos`), identificadores inteiros na URL.

**Sem prefixo de versão.** Nada de `/api/v1`: é um sistema pessoal com um cliente só, e acrescentar versionamento depois é trivial se algum dia houver um app antigo em uso que não dê para atualizar.

**Aninhamento só para criar e listar.** `POST /livros/{id}/elementos` cria um elemento no livro; `GET /elementos/{id}` acessa o elemento direto. Aninhar o acesso a um item (`/livros/2/elementos/7`) só acrescentaria uma chance de a URL ser inconsistente com os dados.

**`PATCH` para ajuste pontual**, e não `PUT`: o app quase sempre muda um campo só — marcar um capítulo como ignorado, anotar a avaliação de um prompt — e exigir o objeto inteiro convidaria a sobrescrever o que outra tela acabou de mudar.

**Códigos de resposta:**

| Situação | Código |
|---|---|
| Leitura bem-sucedida | 200 |
| Criação bem-sucedida | 201 |
| Exclusão bem-sucedida | 204 |
| Recurso não encontrado | 404 |
| Corpo da requisição malformado | 422, com o detalhe que o FastAPI já gera |
| EPUB inválido ou sem texto | 422, com a mensagem de `ArquivoEpubInvalido` |
| Conflito com uma restrição do banco, como cadastrar o mesmo elemento duas vezes | 409 |
| Arquivo acima do limite | 413 |

**Sem paginação.** Uma biblioteca pessoal tem dezenas de livros, e a listagem de capítulos mais longa dos dezoito de validação tem 105 itens. Paginar agora seria complexidade sem problema correspondente.

### 6.2 Livros e capítulos

| Método e caminho | O que faz | Estado |
|---|---|---|
| `POST /livros` | Recebe o arquivo EPUB e importa (passos 1 a 3 do fluxo) | **implementado** |
| `GET /livros` | Lista os livros da biblioteca | **implementado** |
| `GET /livros/{id}` | O livro com a lista de capítulos, sem o texto (passo 4) | **implementado** |
| `DELETE /livros/{id}` | Remove o livro e tudo que depende dele | **implementado** |
| `GET /capitulos/{id}` | Um capítulo **com** o texto (passo 5) | **implementado** |
| `PATCH /capitulos/{id}` | Ajusta `ignorado` e `titulo` | **implementado** |

**O texto não vai nas listagens.** É a decisão que mais afeta o desenho: devolver o texto de todos os capítulos em `GET /livros/{id}` daria respostas de megabytes. A listagem devolve o tamanho em caracteres, que é o que o app precisa para mostrar "capítulo curto" ou "capítulo longo", e o texto vem só quando o usuário abre um capítulo.

Medido contra o servidor rodando, com *Tress* (84 capítulos): `GET /livros/{id}` responde **7,5 KB**; o texto de todos os capítulos somados dá **674 KB**. São **90 vezes** menos dados numa tela que o app abre toda hora.

**O upload é síncrono.** Medido nos livros de validação: extrair e gravar leva de 0,03 a 0,33 segundo, mesmo no maior deles (12 MB, 67 capítulos). Pela rota, com o servidor no ar, um EPUB de 9 MB sobe e é importado em **0,28 segundo**. Uma fila de trabalho em segundo plano resolveria um problema que não existe, e acrescentaria estado para o app acompanhar.

**Importar o mesmo livro duas vezes é permitido**, conforme o item 3.4a. A resposta do `POST /livros` traz o campo `livros_semelhantes` com os livros que já tinham aquele `dc:identifier`, para o app poder avisar — sem impedir.

**Limite de tamanho do arquivo: 60 MB.** O maior dos dezoito livros de validação tem 46 MB (uma história em quadrinhos), então o limite acomoda o caso real com folga e continua protegendo o Raspberry Pi de um arquivo absurdo.

#### O que foi implementado

As seis rotas de livros e capítulos, com 19 testes que exercitam a API de verdade
pelo `TestClient` — cobrindo HTTP, esquema de resposta, serviço de importação e
banco de uma vez.

Verificado também contra o servidor rodando em Docker, importando livros reais:
`POST /livros` responde 201 em 0,28 s para um arquivo de 9 MB, `PATCH` num
capítulo muda a contagem de ignorados do livro, e `DELETE` no livro leva os
capítulos junto — um `GET` no capítulo apagado responde 404.

O upload precisou de uma dependência nova, `python-multipart`: o FastAPI a exige
para ler `multipart/form-data`, e sem ela a rota nem é registrada.

### 6.3 Elementos e estados

| Método e caminho | O que faz | Estado |
|---|---|---|
| `GET /livros/{id}/elementos` | Os elementos do livro, com o estado mais recente de cada | **implementado** |
| `POST /livros/{id}/elementos` | Cadastra um elemento confirmado pelo usuário (passo 7) | **implementado** |
| `GET /elementos/{id}` | O elemento com todos os seus estados | **implementado** |
| `PATCH /elementos/{id}` | Ajusta nome, tipo e descrição | **implementado** |
| `DELETE /elementos/{id}` | Remove o elemento e seus estados | **implementado** |
| `POST /elementos/{id}/estados` | Registra um novo estado a partir de um capítulo | **implementado** |
| `PATCH /estados/{id}` | Ajusta a descrição ou define a imagem-âncora | **implementado** |
| `DELETE /estados/{id}` | Remove um estado | **implementado** |
| `GET /capitulos/{id}/estados-vigentes` | O estado vigente de cada elemento naquele ponto da narrativa | **implementado** |

**`GET /livros/{id}/elementos` traz o estado mais recente de cada elemento**, e aceita `?tipo=PERSONAGEM` para a tela poder separar por tipo. "Mais recente" é pela ordem **narrativa**, não pela data de criação: o último estado em ordem de capítulo (item 3.4b).

**`GET /capitulos/{id}/estados-vigentes`** é a consulta do item 3.4b exposta como rota, porque é o que dá contexto à IA no passo 6 e ao usuário na tela de revisão. Devolve **todos** os elementos do livro, cada um com o estado que vigorava naquele ponto — ou `null`, quando o elemento ainda não tinha aparecido. O `null` é informação útil: significa "primeira aparição", e é o caso em que não há estado anterior para mandar à IA.

As duas rotas usam uma consulta só, com função de janela, em vez de uma consulta por elemento. A implementação fica em `imagineer/servicos/estados_de_elemento.py` — foi tirada dos testes do item 3.4b, onde vivia como protótipo.

**Criar elemento e primeiro estado no mesmo pedido.** O `POST /livros/{id}/elementos` aceita um `estado_inicial` opcional, porque é assim que o passo 7 funciona: o usuário confirma que o personagem existe *e* como ele está naquele capítulo. Em dois pedidos separados, uma falha no meio deixaria um elemento sem estado nenhum.

**Cadastrar o mesmo elemento duas vezes responde 409.** A restrição de unicidade (`livro_id`, `tipo`, `nome`) do item 3.4b existe justamente porque a extração automática reencontra o mesmo personagem em outro capítulo. A resposta traz o id do elemento que já existe, para o app poder oferecer "usar o existente" em vez de só reclamar.

**O capítulo de um estado precisa ser do mesmo livro do elemento.** Nada no banco impede associar um estado a um capítulo de outro livro — as duas chaves estrangeiras são independentes. A rota verifica e responde 422, porque o dado resultante seria silenciosamente incoerente: o estado apareceria na narrativa errada.

#### O que foi implementado

As nove rotas, com 26 testes. A consulta de estado vigente saiu dos testes do item
3.4b e virou `imagineer/servicos/estados_de_elemento.py`.

Ela usa **função de janela** (`ROW_NUMBER() OVER (PARTITION BY ...)`) para pegar
um estado por elemento numa ida só ao banco. A alternativa ingênua seria uma
consulta por elemento: com 50 elementos cadastrados, 50 consultas para montar uma
tela. Verificado antes de escrever que o SQLite dos testes também suporta função
de janela, então o mesmo código roda nos dois bancos.

Verificado contra o servidor rodando, com *O Alienista*: cadastrei "Simão
Bacamarte" com um estado no capítulo de ordem 3 e dois estados posteriores
(ordens 7 e 12), e a rota de estados vigentes devolveu, em cada ponto, a descrição
certa — "Homem de ciência, sóbrio" no capítulo 3, "Barba crescida, olhar
obsessivo" no 7, "Recolhido na Casa Verde" no 12. A "Casa Verde", cadastrada sem
estado, aparece nos três com `estado_vigente` nulo.

### 6.4 Frames

| Método e caminho | O que faz | Estado |
|---|---|---|
| `GET /capitulos/{id}/frames` | Os frames de um capítulo | **implementado** |
| `POST /capitulos/{id}/frames` | Cria um frame | **implementado** |
| `GET /frames/{id}` | O frame com os elementos e estados que ele referencia | **implementado** |
| `PATCH /frames/{id}` | Ajusta título, descrição e atributos situacionais | **implementado** |
| `DELETE /frames/{id}` | Remove o frame, sem apagar os estados que ele citava | **implementado** |
| `PUT /frames/{id}/estados` | Define a lista completa de estados do frame | **implementado** |

`PUT` e não `PATCH` em `/frames/{id}/estados`: aqui o app manda a lista inteira de quem está no frame, que é como a tela funciona — o usuário marca e desmarca elementos e salva o conjunto. Ids repetidos na lista são aceitos e contados uma vez: a chave primária da tabela de associação já impediria o repetido, e devolver um erro por isso só criaria trabalho para o app.

**`tipo=PERSONAGEM` exige exatamente um estado.** Tanto na criação quanto em `PUT /frames/{id}/estados` — um retrato solo é de um elemento só; duas ou mais pessoas já seria uma cena (item 4.4). A rota responde 422 se a contagem não bater.

**O frame devolve o estado *com* o elemento.** `GET /frames/{id}` traz, para cada estado, o nome e o tipo do elemento a que ele pertence — porque a tela mostra "Ned Stark: capa de pele, barba grisalha", e não o id de um estado solto. É a diferença entre a API servir a tela e a tela ter que remontar tudo.

**Os estados de um frame precisam ser do mesmo livro.** Mesmo problema do item 6.3: nada no banco impede associar a um frame o estado de um personagem de outro livro. A rota verifica e responde 422, listando os ids recusados.

### 6.5 Perfis de renderização

| Método e caminho | O que faz | Estado |
|---|---|---|
| `GET /perfis-renderizacao` | Lista os perfis, que são compartilhados entre livros | **implementado** |
| `POST /perfis-renderizacao` | Cria um perfil | **implementado** |
| `GET /perfis-renderizacao/{id}` | Abre um perfil | **implementado** |
| `PATCH /perfis-renderizacao/{id}` | Ajusta o perfil | **implementado** |
| `DELETE /perfis-renderizacao/{id}` | Remove o perfil, sem apagar livros nem prompts | **implementado** |
| `PATCH /livros/{id}` | Corrige metadados e define o perfil padrão do livro | **implementado** |

**Nome de perfil repetido responde 409.** A unicidade do item 3.4c existe porque dois perfis com o mesmo nome seriam indistinguíveis na tela de escolha.

**`PATCH /livros/{id}` também corrige metadados** — título, autor e idioma — e não só o perfil padrão. O motivo veio da validação: um dos dezoito livros declara os metadados de **outro livro** (*Treasure Island* se apresenta como *Death and the Afterlife in Ancient Egypt*). A importação é fiel ao que o arquivo diz, então quem corrige é o usuário.

#### O que foi implementado

As onze rotas das Etapas 6.4 e 6.5, com 30 testes.

Verificado contra o servidor rodando, com *O Alienista*: criei um perfil "Aquarela sombria", apontei o livro para ele, montei um frame com dois elementos em estados específicos, e confirmei que apagar o perfil deixa o livro de pé com `perfil_renderizacao_padrao_id` nulo — o `ON DELETE SET NULL` do item 3.4c valendo pela API. Apagar o frame também não levou os estados: eles pertencem ao elemento e à narrativa, não ao frame que os citou.

### 6.6 Prompts e catálogo de imagens

| Método e caminho | O que faz | Estado |
|---|---|---|
| `POST /frames/{id}/prompts` | Monta o prompt com a IA (passo 8) | **implementado** |
| `GET /frames/{id}/prompts` | O histórico de prompts do frame | **implementado** |
| `GET /prompts/{id}` | Um prompt com as imagens que saíram dele | **implementado** |
| `PATCH /prompts/{id}` | Anota a avaliação do resultado | **implementado** |
| `DELETE /prompts/{id}` | Remove o prompt e suas imagens | **implementado** |
| `POST /prompts/{id}/imagens` | Importa o arquivo de imagem gerado (passos 10 e 11) | **implementado** |
| `GET /imagens/{id}/arquivo` | Devolve o arquivo da imagem | **implementado** |
| `DELETE /imagens/{id}` | Remove a imagem do catálogo, e o arquivo do disco | **implementado** |

**`POST /frames/{id}/prompts` faz as leituras profundas (item 4.4) e depois chama `provedor.montar_prompt`:**

- **Antes de montar o prompt**, para cada estado ligado ao frame (`Frame.estados_elemento`), a rota decide se relê o capítulo de origem daquele estado: sempre, se `prioridade_ia == QUALIDADE`; só se `EstadoElemento.confirmado_pela_leitura_profunda` ainda for falso, se `== ECONOMIA`. Quando relê, chama `sugerir_estado`, grava o texto de volta em `EstadoElemento.descricao` e marca o campo como confirmado. Isso vale para os dois tipos de frame.
- **Só para `tipo=CENA`, e só se houver pelo menos um elemento ligado**, a rota também chama `fundamentar_frame`: relê o capítulo do frame para confirmar quem/onde/o quê contra o que o usuário escreveu, respeitando a mesma cache de `prioridade_ia` (`Frame.contexto_do_livro`/`confirmado_pela_leitura_profunda`). **Não sobrescreve** `titulo`/`descricao` do frame — o resultado é contexto de apoio, passado a `montar_prompt` com prioridade **menor** que o que o usuário escreveu.
- Para `tipo=PERSONAGEM`, a descrição do frame que vai para `montar_prompt` é sempre vazia — o prompt usa só a descrição do elemento (já atualizada pela leitura profunda acima), sem citar título, descrição ou atributos situacionais do frame.
- A lista de elementos que vai para `montar_prompt` vem dos estados do frame (já atualizados, se foi o caso), formatados como `"Nome: descrição do estado"`.
- O perfil de renderização é o informado no pedido (`perfil_renderizacao_id`) ou, na ausência dele, o padrão do livro (`Livro.perfil_renderizacao_padrao_id`). Sem nenhum dos dois, a rota responde 422 — não há estilo para aplicar.
- O modelo é o informado no pedido ou o `modelo_prompt` da configuração para `montar_prompt`; `sugerir_estado` e `fundamentar_frame` usam `modelo_extracao` (é leitura/verificação, não escrita criativa). Sem o modelo necessário, 422.
- O pedido aceita um campo opcional `comentario`: uma correção do usuário, com prioridade **máxima** — acima até da descrição do frame. Passa direto para `provedor.montar_prompt`.
- Ordem de prioridade final dentro de `montar_prompt`, em caso de conflito: **comentário do usuário > descrição do frame escrita pelo usuário > contexto do livro (fundamentação automática)**. É a resposta direta ao feedback do usuário: a IA não deveria poder sobrepor, com uma releitura automática, o que uma pessoa que já leu o capítulo escreveu.
- O prompt monta um texto único a partir dos campos do perfil (`estilo`, `artista_referencia`, `iluminacao`, `paleta`, `formato`) — os únicos preenchidos entram no texto, porque cada ferramenta de imagem usa um subconjunto diferente (item 3.4c).
- Erros do provedor seguem o mesmo mapeamento do item 6.7: `ChaveDeApiAusente`/`ModeloNaoEscolhido` → 422, qualquer outro `ErroDoProvedorIA` → 502. Vale para qualquer uma das três chamadas de IA envolvidas.

**A resposta traz `referencias_visuais`** (item 4.5): as imagens-âncora (`EstadoElemento.imagem_ancora_id`, item 3.1) já aprovadas para os elementos do frame, deduplicadas. `GET /prompts/{id}` recalcula isso na hora — não é uma foto congelada de quando o prompt foi criado, porque uma âncora pode ser definida depois. Serve para o app avisar "anexe esta imagem também" ao colar o prompt numa ferramenta que aceite referência visual, já que o passo 9 é manual e a API não tem como anexar a imagem sozinha.

**Validado com IA real, incluindo um caso em que a fundamentação errou.** Numa cena cujo primeiro momento do capítulo era "Vis lembra do pai, pendurado numa borda rochosa", `fundamentar_frame` releu o capítulo inteiro e voltou descrevendo um trecho bem posterior (a sala com o Sapador e o prisioneiro Nateo) — o capítulo tem vários momentos, e o modelo pegou o errado. Como o `contexto_do_livro` entra com prioridade **menor** que a descrição que o usuário escreveu, o prompt final ficou correto mesmo assim: continuou descrevendo a cena da borda rochosa, ignorando o contexto equivocado. É a ordem de prioridade funcionando exatamente como planejado — uma rede de segurança contra a própria leitura automática errar.

**O upload de imagem é multipart**, no mesmo padrão de `POST /livros` com o EPUB (item 6.2): o app manda os bytes da imagem no corpo do pedido, e o servidor grava o arquivo em `DIRETORIO_IMAGENS/prompts/{prompt_id}/{nome-gerado}` — um nome gerado (não o nome original) evita colisão entre duas imagens de nomes iguais vindas de ferramentas diferentes. Só o caminho relativo entra no banco (item 3.4c). Extensões aceitas: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` — o que cobre as ferramentas de geração de imagem em uso; outra extensão responde 422. O limite de tamanho é 25 MB por imagem, lido em blocos como no EPUB, para não estourar a memória do Raspberry Pi com um arquivo grande demais.

**Remover apaga o arquivo do disco, não só a linha do banco** — tanto em `DELETE /imagens/{id}` quanto em `DELETE /prompts/{id}` (que remove as imagens do prompt em cascata). Um arquivo ausente no disco não impede a remoção da linha: o objetivo é o catálogo ficar consistente, e um arquivo que já sumiu não deveria travar a limpeza do registro órfão.

**Limitação conhecida:** apagar um livro, capítulo, frame ou elemento remove as linhas de `prompts` e `imagens` em cascata no banco (item 3.4), mas **não** apaga os arquivos de imagem do disco — só as rotas específicas desta seção fazem essa limpeza. Adicionar isso exigiria um gatilho no banco ou uma varredura periódica, e nenhuma das duas coisas está no escopo do MVP; por ora o arquivo órfão é um custo aceitável, revisitável se o volume de imagens crescer.

#### O que foi implementado

As oito rotas, com 16 testes. O `ler_com_limite` que já protegia o upload do EPUB (item 6.2) virou função compartilhada em `servicos/upload.py`, reaproveitada aqui para o upload de imagem — é a mesma proteção contra um arquivo grande demais para a memória do Raspberry Pi, e duplicar essa lógica de leitura em blocos seria repetir um código sensível à segurança sem motivo.

O texto do perfil que vai para a IA é montado só com os campos preenchidos (`estilo`, `artista_referencia`, `iluminacao`, `paleta`, `formato`) — confirmado com um perfil só com `estilo` definido e outro com todos os campos, verificando que o texto muda de tamanho de acordo, sem campos vazios aparecendo como "None" ou string vazia no meio do prompt.

`DELETE /prompts/{id}` apaga os arquivos das imagens **depois** do commit que remove as linhas do banco, não antes: se a remoção de um arquivo falhasse no meio, o banco já estaria consistente (prompt e imagens removidos), e sobraria só um arquivo órfão no disco — o mesmo tipo de custo aceitável registrado na limitação conhecida acima, e não uma inconsistência de dados.

**Divergência registrada, pós-validação com IA real.** A versão inicial de `criar_prompt` só lia os estados já salvos no banco, sem tocar na IA antes de montar o prompt. Um teste de ponta a ponta com `openai/gpt-4o-mini` e `google/gemini-2.5-flash` no mesmo capítulo real mostrou erros de atribuição e um elemento inventado quando a descrição de aparência de vários elementos era gerada numa única chamada (item 4.2). A rota passou a fazer a leitura profunda elemento por elemento, imediatamente antes de montar o prompt, e a aceitar um `comentario` do usuário com prioridade sobre essa leitura. Na mesma rodada, ganhou `referencias_visuais` (item 4.5), conectando um campo que existia desde o item 3.1 mas nunca tinha sido lido por nenhuma rota.

**Segunda divergência, testando um retrato solo.** Um prompt pedido só para o Vis Solum citou o pai dele, porque a descrição livre da "cena" (que na época servia tanto para retrato quanto para cena de verdade) mencionava o pai por nome. A entidade `Cena` virou `Frame` com um campo `tipo` (item 3.4c), e a rota passou a: (1) zerar a descrição do frame quando `tipo=PERSONAGEM`, e (2) só para `tipo=CENA`, fazer uma segunda leitura profunda — `fundamentar_frame` — que confere o texto do usuário contra o capítulo sem sobrescrevê-lo. Testado com IA real: a fundamentação chegou a ler o trecho errado do capítulo (uma cena bem posterior), e o prompt final saiu correto mesmo assim, porque a descrição do usuário tem prioridade sobre o contexto do livro.

### 6.7 Extração e configuração

| Método e caminho | O que faz | Estado |
|---|---|---|
| `POST /capitulos/{id}/sugestoes` | Chama a IA para sugerir elementos e estados (passo 6) | **implementado** |
| `GET /configuracao/modelos` | Lista os modelos disponíveis no OpenRouter (item 4.3) | **implementado** |
| `GET /configuracao` | A configuração atual: modelos escolhidos, se há chave cadastrada | **implementado** |
| `PUT /configuracao` | Grava a configuração | **implementado** |

`GET /configuracao` **nunca devolve a chave de API**, só se ela está cadastrada. Uma chave que sai do servidor é uma chave que vaza em log, em cache de app ou em captura de tela.

**`POST /capitulos/{id}/sugestoes` não grava nada no banco.** É consulta pura, fiel ao item 4.4: a IA sugere, o usuário confirma depois pelas rotas já existentes da Etapa 6.3 (`POST /elementos`, `POST /elementos/{id}/estados`). A rota:

1. Busca o texto do capítulo e o estado vigente de cada elemento do livro **até aquele capítulo** (mesma consulta do item 6.3, `estado_vigente_por_elemento`, limitada por `Capitulo.ordem`) — é o contexto que permite à IA responder "manter estado atual" em vez de inventar um estado novo.
2. Confere se o texto cabe na janela do modelo escolhido (`modelo_extracao` da configuração) **antes** de chamar a IA — gastar a chamada para descobrir que não cabia seria o pior caso (item 4.3).
3. Chama `provedor.extrair_elementos` — só identificação (fase 1 do item 4.4): tipo, nome, descrição de identidade e `manter_estado_atual`. **Não** devolve mais uma descrição de aparência; essa parte é a leitura profunda (fase 2), que só acontece mais tarde, dentro de `POST /frames/{id}/prompts` (item 6.6).
4. Tenta casar cada sugestão com um elemento já cadastrado do livro, comparando tipo e nome **sem diferenciar maiúsculas/minúsculas nem acentuação** — a IA foi instruída a repetir o nome exato de um elemento conhecido, mas variações de caixa e acento apareceram como algo razoável de tolerar sem risco de casar elementos diferentes por engano. Quando casa, preenche `elemento_id` na resposta.
5. Faz o mesmo casamento para cada participante de cada `cena` sugerida (item 4.4) — mesma normalização, mesmo campo `elemento_id`.

Erros do provedor viram HTTP assim: `ChaveDeApiAusente` e `ModeloNaoEscolhido` e `TextoLongoDemais` → 422 (o problema é a configuração, o usuário resolve pela tela de configuração); qualquer outro `ErroDoProvedorIA` (rede, resposta fora do formato) → 502.

#### O que foi implementado

As três rotas de `/configuracao` foram implementadas junto com a camada de IA (Etapa 4.3), antes desta tabela ser atualizada — o código já existia, só faltava marcar. `POST /capitulos/{id}/sugestoes` é o item novo desta rodada, com 9 testes.

**Divergência registrada, pós-validação com IA real:** o campo `estado_sugerido` foi removido da resposta depois de um teste de ponta a ponta expor mistura de atributos entre elementos (ver a divergência do item 4.2 e a nova fase 2 do item 4.4). Numa rodada seguinte, a resposta ganhou `cenas` — feedback do usuário depois de revisar uma extração real: a lista de elementos sozinha não bastava, faltava sugerir quais combinações formam um momento que vale ilustrar, e alguns elementos identificados eram irrelevantes (papelada genérica) ou classificados no tipo errado (um tabuleiro de jogo como `AMBIENTE`, uma porta como `VEICULO`).

A checagem de "cabe no modelo" (`conferir_se_cabe`) saiu de método de `ProvedorOpenRouter` para função livre em `ia/openrouter.py`: a rota precisa da mesma checagem antes de chamar **qualquer** provedor, inclusive o `ProvedorFalso` dos testes, e a estimativa de tokens não depende de nenhum detalhe de um fornecedor específico. O método antigo continua existindo, agora só delegando para a função — o que evitou reescrever os testes que já cobriam esse comportamento.

O casamento por tipo e nome normalizado (sem caixa, sem acento) foi verificado com um elemento cadastrado como "João" e uma sugestão da IA vindo como "joão" — casa; com o mesmo nome mas tipo diferente — não casa, porque dois elementos diferentes podem legitimamente ter o mesmo nome (um personagem chamado "Winterfell" e um lugar chamado "Winterfell" não seriam a mesma coisa, hipoteticamente).

---

## Etapa 7 — Telas do App (Mobile)

Esboço do fluxo de UI, ainda sem código — o objetivo aqui é fechar **quais telas existem, o que cada uma mostra, quais rotas ela consome e para onde ela navega**, antes de tocar em Kotlin (item 7.10, Etapa 8). Cada tela é numerada e mapeada ao passo correspondente do fluxo da Etapa 2.

### 7.1 Mapa de navegação

```
Biblioteca ──(importar)──> [upload] ──> Livro
Livro ──(abrir capítulo)──> Capítulo ──(novo retrato | nova cena)──> Frame ──(gerar prompt)──> Prompt ──(importar imagem)── volta para Prompt (catálogo)
Livro ──(ver elementos)──> Elementos do Livro
Livro ──(perfil padrão)──> Perfis de Renderização
Qualquer tela ──(engrenagem)──> Configuração
```

Não há tela de "frame" ou "prompt" soltas fora de um capítulo/frame — a navegação é sempre hierárquica: **livro → capítulo → frame → prompt**, espelhando as rotas (`/livros/{id}/...`, `/capitulos/{id}/...`, `/frames/{id}/...`, `/prompts/{id}/...`).

### 7.2 Biblioteca

Tela inicial do app. Lista os livros já importados.

- **Rota**: `GET /livros`.
- **Mostra**: título, autor, total de capítulos e quantos estão ignorados, por livro (`LivroResumo`).
- **Ações**: tocar num livro abre a tela de Livro (7.3); botão flutuante "Importar" abre o seletor de arquivo do sistema operacional e dispara o upload.
- **Vazio**: lista vazia mostra um convite a importar o primeiro livro — não é um estado de erro.

### 7.3 Importar livro

Não é bem uma tela própria — é o estado de progresso do upload, sobreposto à Biblioteca (passos 1 a 4).

- **Rota**: `POST /livros` (multipart).
- **Durante**: barra de progresso do upload (arquivos grandes existem — o maior do corpus de validação tem 46 MB, item 4.3).
- **Ao terminar**: se `livros_semelhantes` vier não-vazio na resposta (item 6.2), mostra um aviso — "já existe um livro parecido" — com a opção de abrir o existente em vez do novo, ou seguir mesmo assim. Não impede a importação (é aviso, não bloqueio, coerente com o item 3.4a).
- **Erro**: EPUB inválido (422) mostra a mensagem que a API devolve; a importação é fiel ao que o arquivo diz, então um erro aqui costuma significar arquivo mesmo corrompido, não um bug.

### 7.4 Livro (detalhe)

Passos 3 a 5: a estrutura de capítulos do livro, e o ponto de entrada para tudo que pertence a ele.

- **Rota**: `GET /livros/{id}` (estrutura, sem texto — item 6.2).
- **Mostra**: metadados (título, autor, idioma), perfil de renderização padrão (ou "nenhum definido"), lista de capítulos em ordem, com indicação visual dos que estão marcados como ignorados.
- **Ações**: tocar num capítulo não-ignorado abre a tela de Capítulo (7.5); alternar o estado "ignorado" de um capítulo direto na lista (`PATCH /capitulos/{id}`, item 2.2); editar metadados e perfil padrão (`PATCH /livros/{id}`); atalho para "Elementos do livro" (7.6) e para "Perfis de renderização" (7.8); apagar o livro (`DELETE /livros/{id}`) com confirmação — é destrutivo e leva capítulos, elementos, frames, prompts e imagens junto (item 3.4).

### 7.5 Capítulo

O coração dos passos 5 a 7: ler o texto, pedir sugestões à IA, e confirmar o que de fato existe.

- **Rotas**: `GET /capitulos/{id}` (texto completo), `POST /capitulos/{id}/sugestoes` (passo 6, fase 1 do item 4.4), `GET /capitulos/{id}/estados-vigentes`, `POST /livros/{id}/elementos`, `POST /elementos/{id}/estados`.
- **Mostra**: o texto do capítulo (rolável); um botão "Analisar com IA" que dispara `POST /capitulos/{id}/sugestoes` e traz a lista de elementos identificados (tipo, nome, identidade, `manter_estado_atual`) — **sem** descrição de aparência, porque essa parte só existe na leitura profunda da fase 2 (item 4.4), que acontece mais adiante, na tela de Prompt.
- **Ações por sugestão**: confirmar (grava `Elemento` + `EstadoElemento` inicial), ajustar tipo/nome antes de confirmar, ou descartar (não faz nada — é só sugestão). Também dá para cadastrar um elemento à mão, sem passar pela IA. A lista de "estados vigentes" (item 3.4b) mostra o que já se sabe de cada elemento do livro até este ponto, útil para o usuário decidir se o que a IA sugeriu já é conhecido.
- **Navega para**: "Novo retrato" cria um frame `tipo=PERSONAGEM` para um elemento específico e abre a tela de Frame (7.6) já com ele; "Nova cena" cria um frame `tipo=CENA` vazio (ou pré-preenchido a partir de um `frames` sugerido pela IA, item 4.4) e abre a mesma tela pronta para escolher quem mais aparece; lista de frames já criados neste capítulo (retratos e cenas, diferenciados visualmente pelo `tipo`), cada um abrindo a tela de Frame existente.

### 7.6 Frame

O recorte de um capítulo que vai virar uma imagem — um retrato solo ou uma cena, passo 6.4.

- **Rotas**: `POST /capitulos/{id}/frames`, `GET /frames/{id}`, `PATCH /frames/{id}`, `PUT /frames/{id}/estados`.
- **Mostra**: `tipo` (retrato ou cena — não editável depois de criado, item 6.4); título; e, só para `tipo=CENA`, descrição e atributos situacionais (horário, clima, humor); a lista de elementos que aparecem no frame, cada um com o estado atual (item 6.4 — a API já devolve o estado com a identidade do elemento, para a tela não ter que remontar isso).
- **Ações**: editar título e, se `CENA`, os demais campos; marcar/desmarcar quais estados de elemento aparecem — num retrato, a tela permite só **um** marcado por vez (a API responde 422 se vier mais de um, item 6.4); os já marcados vêm de `GET /frames/{id}`, salvar manda a lista inteira via `PUT`; apagar o frame (não apaga os estados que ele citava).
- **Navega para**: "Gerar prompt" abre a tela de Prompt (7.7) e já dispara `POST /frames/{id}/prompts`; histórico de prompts já gerados para este frame, cada um abrindo a tela de Prompt no modo "ver resultado existente".

### 7.7 Prompt

Passos 8 a 11 — onde o texto vira, de fato, o insumo para a imagem, e onde a imagem volta para o catálogo.

- **Rotas**: `POST /frames/{id}/prompts`, `GET /prompts/{id}`, `PATCH /prompts/{id}`, `POST /prompts/{id}/imagens`, `GET /imagens/{id}/arquivo`, `DELETE /imagens/{id}`.
- **Ao gerar** (`POST /frames/{id}/prompts`): mostra um indicador de carregamento — as leituras profundas (item 4.4: uma por elemento, e mais uma de fundamentação da cena se `tipo=CENA`) podem levar alguns segundos, então isso não é instantâneo, e a tela precisa deixar isso claro (evita o usuário achar que travou). Um frame `PERSONAGEM` é mais rápido — não tem a fundamentação de cena.
- **Mostra**: o texto do prompt pronto, com um botão "copiar" (passo 9 é manual — colar numa ferramenta de imagem externa); campo de comentário opcional, com um botão "gerar de novo com este comentário" que refaz a chamada passando `comentario` (item 4.4 — é a mesma rota, não existe "refinar" separado, e o comentário tem prioridade sobre tudo o mais); histórico de tentativas anteriores do mesmo frame, para comparar.
- **Importar imagem** (passos 10-11): depois de gerar a imagem numa ferramenta externa, o usuário volta ao app e usa o seletor de arquivo do sistema para escolher a imagem, que sobe via `POST /prompts/{id}/imagens`. As imagens já importadas aparecem em miniatura (buscando o arquivo por `GET /imagens/{id}/arquivo`); tocar numa abre em tamanho cheio, com a opção de apagar (`DELETE /imagens/{id}`).
- **Avaliação**: campo de texto livre para anotar como a imagem ficou (`PATCH /prompts/{id}` — item 3.1/6.6), útil para comparar modelos depois.
- **Referências visuais** (item 4.5): se `referencias_visuais` vier não-vazio, a tela mostra essas imagens-âncora com um aviso — "anexe também, para manter a aparência consistente" — antes do botão de copiar. É uma sugestão para a ferramenta externa que aceitar imagem de referência (o Gemini aceita); a API não anexa nada sozinha.
- **Ideia para quando esta tela for implementada, não decidida agora**: como o texto vai para uma ferramenta externa por copiar/colar, um botão "copiar para o Gemini" poderia encapsular o prompt num prefixo mais natural para esse motor específico (ex: "Crie uma imagem fotorrealista horizontal com a seguinte descrição: ..."), em vez do texto cru — mas isso é decisão de UI do app, não do backend, e fica em aberto até a tela existir de verdade.

### 7.8 Elementos do livro

Fora do fluxo capítulo-a-capítulo — uma tela de consulta e correção geral, para quando o usuário quer ver ou ajustar um personagem sem estar processando um capítulo específico.

- **Rotas**: `GET /livros/{id}/elementos` (com filtro por tipo), `GET /elementos/{id}`, `PATCH /elementos/{id}`, `DELETE /elementos/{id}`.
- **Mostra**: lista de elementos do livro, separável por tipo (personagem, ambiente, objeto, criatura, grupo, veículo, edificação), cada um com o estado mais recente.
- **Ações**: abrir um elemento mostra todos os seus estados em ordem narrativa (histórico completo — a "ficha" do personagem ao longo do livro); editar identidade (nome, tipo, descrição); apagar (leva todos os estados junto).

### 7.9 Perfis de renderização

Lista compartilhada entre livros, acessível tanto pela tela de Livro quanto pela Biblioteca/Configuração.

- **Rotas**: `GET /perfis-renderizacao`, `POST`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`.
- **Mostra**: nome e campos de estilo de cada perfil.
- **Ações**: criar, editar, apagar (não leva livros nem prompts — só desfaz a referência, item 6.5); ao editar um livro, a escolha do perfil padrão usa esta mesma lista.

### 7.10 Configuração

Acessível de qualquer tela.

- **Rotas**: `GET/PUT /configuracao`, `GET /configuracao/modelos`.
- **Mostra**: se há chave cadastrada e de onde ela vem (nunca a chave em si — item 4.3); modelo de extração e de prompt escolhidos; `prioridade_ia` (`ECONOMIA`/`QUALIDADE` — item 4.4).
- **Ações**: cadastrar/apagar a chave; escolher os modelos a partir da lista dinâmica do OpenRouter (com filtro "só gratuitos"); trocar a prioridade de IA.

### 7.11 Fora do escopo desta rodada

- Login/múltiplos usuários: o sistema é pessoal, de um usuário só (item 1.1) — não há tela de autenticação.
- Notificações push, modo offline, sincronização em segundo plano: nada disso está no MVP.
- Tela de "grupos com membros explícitos": adiada para v2 junto com a modelagem (item 3.1).

---

## Etapa 8 — Pendências / Próximos Passos

- [ ] Confirmar formalmente o stack mobile (assumido Kotlin + Jetpack Compose nativo Android).
- [x] ~~Definir estrutura de pastas/módulos do projeto Python (FastAPI).~~ Concluído — ver item **1.5**.
- [x] ~~Desenhar as rotas da API (endpoints, contratos de request/response).~~ Concluído — **Etapa 6**, todas as seções (6.2 a 6.7): livros, capítulos, elementos e estados, frames, perfis de renderização, prompts e catálogo de imagens, configuração e sugestões de IA.
- [x] ~~Esboçar as telas do app (fluxo de UI, especialmente os passos 6-9 de confirmação/ajuste).~~ Concluído — **Etapa 7**: dez telas mapeadas às rotas da Etapa 6, mais o mapa de navegação. Ainda sem código — falta criar o projeto Android, próximo item desta lista.
- [x] ~~Permitir marcar um capítulo como ignorado.~~ Concluído — campo `Capitulo.ignorado`, pré-sugerido pela importação e confirmado pelo usuário (itens 2.2 e 3.4a). Exposto na API (item 6.2) e na tela de Livro (item 7.4).
- [ ] Criar o projeto Android (Kotlin + Jetpack Compose) e implementar as telas da Etapa 7.
- [ ] Refinar a engenharia do prompt de geração de imagens (instrução do item 4.2/`montar_prompt`) — próxima rodada, a pedido de Allan.
- [ ] Relações entre elementos e Grupos com membros explícitos (v2, fora do escopo do MVP).
