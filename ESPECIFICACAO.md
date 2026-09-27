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
- **Mobile**: **assumido** Kotlin + Jetpack Compose (Android nativo), aproveitando a familiaridade com JVM. **Ainda não confirmado formalmente** — ver Etapa 7 (Pendências).

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
- **Cena**: recorte narrativo de um capítulo; referencia um ou mais Elementos (com seus Estados na ocasião); guarda atributos situacionais próprios (horário, clima, humor) diretamente nela — sem entidade "Contexto" separada.
- **PerfilRenderizacao**: perfil de estilo visual (estilo, artista de referência, iluminação, paleta, formato, modelo alvo). Configurado por padrão a nível de Livro, com possibilidade de override pontual ao gerar um prompt específico.
- **Prompt**: registro de cada prompt gerado (modelo de IA usado, texto, data, resultado, imagem associada), permitindo regenerar ou comparar modelos depois.
- **Imagem**: arquivo final importado pelo usuário, com referência ao Prompt/Cena/Elementos de origem, compondo o catálogo.

### 3.2 Relacionamentos

- Um Elemento pode aparecer em várias Cenas de vários Capítulos (muitos-para-muitos).
- Um Elemento tem vários EstadoElemento ao longo da história (um por "momento narrativo relevante").
- Uma Cena referencia vários Elementos (com o Estado vigente de cada um naquele ponto).
- Um Prompt está associado a uma Cena (e, por meio dela, aos Elementos/Estados usados como contexto) e a uma Imagem.

### 3.3 Decisões de modelagem (justificativas)

- **Elemento genérico em vez de tabelas por tipo**: personagens, ambientes, objetos, criaturas etc. compartilham a mesma necessidade — manter consistência visual ao longo da narrativa. Um enum `tipo` evita duplicação de schema e lógica.
- **EstadoElemento separado da identidade do Elemento**: personagens envelhecem, se ferem, trocam de roupa; objetos quebram; ambientes são destruídos/reconstruídos. Fixar uma única "descrição visual" no Elemento geraria inconsistência entre capítulos distantes da história.
- **Cena com atributos situacionais embutidos**: evita criar uma entidade "Contexto" isolada para informações (horário, clima) que já são naturalmente parte da própria cena.
- **PerfilRenderizacao em vez de campo único de "estilo"**: permite reutilizar combinações de estilo/iluminação/paleta entre livros, e adaptar à ferramenta de geração de imagem usada (cada uma tem sintaxe própria).
- **Relações entre elementos e Grupos com membros explícitos**: ideia boa, mas adiada para uma v2 — exige tabela de relacionamento tipo grafo e telas extras no app; não é essencial para o MVP (Elemento + Estado + Cena + Prompt + Imagem).

### 3.4 Campos das entidades

Esta seção detalha as colunas de cada tabela. Foi preenchida em três partes, todas **implementadas**:

- **(a)** `Livro` e `Capitulo` — a base da importação do EPUB.
- **(b)** `Elemento` e `EstadoElemento` — o coração da consistência visual.
- **(c)** `Cena`, `PerfilRenderizacao`, `Prompt` e `Imagem` — a geração e o catálogo.

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

#### (c) Cena

O recorte narrativo de um capítulo que vai virar uma imagem.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `capitulo_id` | inteiro | não | referência ao Capítulo; indexado |
| `titulo` | texto (300) | não | como identificar a cena na lista |
| `descricao` | texto longo | sim | o trecho ou o resumo do que acontece |
| `horario` | texto (100) | sim | atributo situacional |
| `clima` | texto (100) | sim | atributo situacional |
| `humor` | texto (100) | sim | atributo situacional |

Os três atributos situacionais ficam **na própria Cena**, sem uma entidade "Contexto" separada: horário, clima e humor já são naturalmente parte da cena, e uma tabela extra só acrescentaria uma junção (item 3.3).

**Sem campo `ordem`**, diferente do Capítulo. A ordem dos capítulos vem do índice do EPUB e precisa ser preservada explicitamente; as cenas são criadas pelo usuário enquanto lê um capítulo, então a ordem de criação já é a ordem narrativa. Acrescentar o campo depois é uma migration trivial, se a necessidade aparecer.

#### (c) Ligação entre Cena e EstadoElemento

Tabela de associação `cenas_estados_elemento`, com as duas colunas formando a chave primária.

| Coluna | Observação |
|---|---|
| `cena_id` | referência à Cena |
| `estado_elemento_id` | referência ao EstadoElemento |

A ligação é com o **Estado**, não com o Elemento. É isso que faz a cena guardar *como* cada elemento estava naquele ponto — que é o dado que entra no prompt. Ligar direto ao Elemento perderia essa informação, e o prompt não saberia qual das versões do personagem usar.

Não tem colunas próprias além das duas chaves, então é uma tabela simples de associação e não uma entidade do modelo.

#### (c) Prompt

O registro de cada prompt gerado, que permite regenerar e comparar modelos depois.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `cena_id` | inteiro | não | referência à Cena; indexado |
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

Camada de abstração `ProvedorIA` com dois métodos:
- `extrair_elementos(texto_capitulo, estados_conhecidos) -> lista estruturada`
- `montar_prompt(elementos_selecionados, estados, perfil_renderizacao) -> texto do prompt`

Implementação concreta inicial: `ProvedorOpenRouter`, parametrizada por `id_modelo`. Os dois métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que adivinhar o formato da resposta. Provedores nativos adicionais (Groq, Gemini) podem ser adicionados depois seguindo a mesma interface, se necessário.

> **Divergência registrada (item 1.5):** a primeira versão desta seção nomeava a interface como `AIProvider`, a implementação como `OpenRouterProvider` e o parâmetro como `render_profile`. Os nomes foram traduzidos para `ProvedorIA`, `ProvedorOpenRouter` e `perfil_renderizacao` por coerência com a regra de idioma: existe tradução natural, então o português prevalece. Definido antes de a pasta `ia/` ser preenchida, para não renomear código depois.

### 4.3 Configuração de modelos

Tela de configuração permitindo:
- Cadastro da API key do OpenRouter, nunca hardcoded.
- Seleção de modelo para extração de elementos (passo 6) e para montagem de prompt (passo 8), com opção "usar o mesmo modelo para os dois" marcada por padrão.
- Lista de modelos obtida dinamicamente do endpoint `/models` do OpenRouter (com filtro opcional para mostrar só os gratuitos).

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

A extração é **semi-automática**: a IA sugere, o usuário confirma. Isso evita depender de uma regra algorítmica perfeita para decidir sozinha se um capítulo representa mudança de estado:

1. Ao processar um capítulo, o backend busca o último `EstadoElemento` conhecido de cada elemento relevante.
2. Esse estado é enviado como contexto à IA junto do texto do capítulo.
3. A IA retorna uma sugestão: "manter estado atual" ou "possível novo estado: [detalhes]".
4. O app mostra a sugestão ao usuário, que confirma ou edita antes de qualquer gravação no banco.

---

## Etapa 5 — Decisões Técnicas e Justificativas

| Decisão | Motivo |
|---|---|
| Python + FastAPI em vez de Java + Spring Boot | `ebooklib` mais maduro que as opções Java para parsing de EPUB; footprint mais leve no Raspberry Pi; chamadas assíncronas naturais para IA; oportunidade de aprendizado (conhecimento básico prévio em Python) |
| OpenRouter como gateway único de IA | Evita multiplicar adapters por fornecedor; ainda permite ao usuário escolher modelo; tem opções gratuitas |
| Elemento genérico com enum `tipo` | Reduz duplicação de schema entre personagens/ambientes/objetos/criaturas |
| EstadoElemento separado do Elemento | Elementos mudam de aparência ao longo da narrativa; é essencial para consistência visual entre capítulos |
| Cena sem entidade "Contexto" separada | Informação situacional já é natural da própria cena; evita tabela desnecessária |
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
| Associação Cena ↔ **EstadoElemento**, não Cena ↔ Elemento | É o que faz a cena registrar *como* cada elemento estava naquele ponto. Ligada ao Elemento, a cena não saberia qual das versões do personagem usar no prompt |
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

### 6.4 Cenas

| Método e caminho | O que faz | Estado |
|---|---|---|
| `GET /capitulos/{id}/cenas` | As cenas de um capítulo | **implementado** |
| `POST /capitulos/{id}/cenas` | Cria uma cena | **implementado** |
| `GET /cenas/{id}` | A cena com os elementos e estados que ela referencia | **implementado** |
| `PATCH /cenas/{id}` | Ajusta título, descrição e atributos situacionais | **implementado** |
| `DELETE /cenas/{id}` | Remove a cena, sem apagar os estados que ela citava | **implementado** |
| `PUT /cenas/{id}/estados` | Define a lista completa de estados da cena | **implementado** |

`PUT` e não `PATCH` em `/cenas/{id}/estados`: aqui o app manda a lista inteira de quem está na cena, que é como a tela funciona — o usuário marca e desmarca elementos e salva o conjunto. Ids repetidos na lista são aceitos e contados uma vez: a chave primária da tabela de associação já impediria o repetido, e devolver um erro por isso só criaria trabalho para o app.

**A cena devolve o estado *com* o elemento.** `GET /cenas/{id}` traz, para cada estado, o nome e o tipo do elemento a que ele pertence — porque a tela mostra "Ned Stark: capa de pele, barba grisalha", e não o id de um estado solto. É a diferença entre a API servir a tela e a tela ter que remontar tudo.

**Os estados de uma cena precisam ser do mesmo livro.** Mesmo problema do item 6.3: nada no banco impede associar a uma cena o estado de um personagem de outro livro. A rota verifica e responde 422, listando os ids recusados.

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

Verificado contra o servidor rodando, com *O Alienista*: criei um perfil "Aquarela sombria", apontei o livro para ele, montei uma cena com dois elementos em estados específicos, e confirmei que apagar o perfil deixa o livro de pé com `perfil_renderizacao_padrao_id` nulo — o `ON DELETE SET NULL` do item 3.4c valendo pela API. Apagar a cena também não levou os estados: eles pertencem ao elemento e à narrativa, não à cena que os citou.

### 6.6 Prompts e catálogo de imagens

| Método e caminho | O que faz | Estado |
|---|---|---|
| `POST /cenas/{id}/prompts` | Monta o prompt com a IA (passo 8) | depende da Etapa 4 |
| `GET /cenas/{id}/prompts` | O histórico de prompts da cena | a implementar |
| `GET /prompts/{id}` | Um prompt com as imagens que saíram dele | a implementar |
| `PATCH /prompts/{id}` | Anota a avaliação do resultado | a implementar |
| `DELETE /prompts/{id}` | Remove o prompt e suas imagens | a implementar |
| `POST /prompts/{id}/imagens` | Importa o arquivo de imagem gerado (passos 10 e 11) | a implementar |
| `GET /imagens/{id}/arquivo` | Devolve o arquivo da imagem | a implementar |
| `DELETE /imagens/{id}` | Remove a imagem do catálogo, e o arquivo do disco | a implementar |

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
3. Chama `provedor.extrair_elementos`.
4. Tenta casar cada sugestão com um elemento já cadastrado do livro, comparando tipo e nome **sem diferenciar maiúsculas/minúsculas nem acentuação** — a IA foi instruída a repetir o nome exato de um elemento conhecido, mas variações de caixa e acento apareceram como algo razoável de tolerar sem risco de casar elementos diferentes por engano. Quando casa, preenche `elemento_id` na resposta.

Erros do provedor viram HTTP assim: `ChaveDeApiAusente` e `ModeloNaoEscolhido` e `TextoLongoDemais` → 422 (o problema é a configuração, o usuário resolve pela tela de configuração); qualquer outro `ErroDoProvedorIA` (rede, resposta fora do formato) → 502.

#### O que foi implementado

As três rotas de `/configuracao` foram implementadas junto com a camada de IA (Etapa 4.3), antes desta tabela ser atualizada — o código já existia, só faltava marcar. `POST /capitulos/{id}/sugestoes` é o item novo desta rodada, com 9 testes.

A checagem de "cabe no modelo" (`conferir_se_cabe`) saiu de método de `ProvedorOpenRouter` para função livre em `ia/openrouter.py`: a rota precisa da mesma checagem antes de chamar **qualquer** provedor, inclusive o `ProvedorFalso` dos testes, e a estimativa de tokens não depende de nenhum detalhe de um fornecedor específico. O método antigo continua existindo, agora só delegando para a função — o que evitou reescrever os testes que já cobriam esse comportamento.

O casamento por tipo e nome normalizado (sem caixa, sem acento) foi verificado com um elemento cadastrado como "João" e uma sugestão da IA vindo como "joão" — casa; com o mesmo nome mas tipo diferente — não casa, porque dois elementos diferentes podem legitimamente ter o mesmo nome (um personagem chamado "Winterfell" e um lugar chamado "Winterfell" não seriam a mesma coisa, hipoteticamente).

---

## Etapa 7 — Pendências / Próximos Passos

- [ ] Confirmar formalmente o stack mobile (assumido Kotlin + Jetpack Compose nativo Android).
- [x] ~~Definir estrutura de pastas/módulos do projeto Python (FastAPI).~~ Concluído — ver item **1.5**.
- [x] ~~Desenhar as rotas da API (endpoints, contratos de request/response).~~ Concluído — **Etapa 6**. Implementadas: livros, capítulos, elementos e estados, cenas, perfis de renderização, configuração e sugestões de IA (6.2 a 6.5 e 6.7). Falta só a Etapa 6.6.
- [ ] Rotas de prompts e catálogo de imagens (Etapa 6.6) — depende de gerar/importar imagens, que ainda não tem lugar de armazenamento definido no servidor.
- [ ] Esboçar as telas do app (fluxo de UI, especialmente os passos 6-9 de confirmação/ajuste).
- [x] ~~Permitir marcar um capítulo como ignorado.~~ Concluído — campo `Capitulo.ignorado`, pré-sugerido pela importação e confirmado pelo usuário (itens 2.2 e 3.4a). Falta expor o ajuste na API e no app.
- [ ] Relações entre elementos e Grupos com membros explícitos (v2, fora do escopo do MVP).
