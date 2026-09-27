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
- **Mobile**: **assumido** Kotlin + Jetpack Compose (Android nativo), aproveitando a familiaridade com JVM. **Ainda não confirmado formalmente** — ver Etapa 6 (Pendências).

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

**3. Quinze livros publicados de verdade.** Alguns são EPUB 3, outros EPUB 2,
vários passaram por conversão no Calibre. Esta etapa foi a que mais valeu, e a
variedade de formato é que fez o trabalho:

| Tipo | Livros |
|---|---|
| Romance | *A Vontade de Muitos*, *Mistborn: O Império Final*, *O Poço da Ascensão*, *Tress, a garota do Mar Esmeralda*, *Devoradores de Estrelas*, *Perdido em Marte*, *O apanhador no campo de centeio*, *O estrangeiro*, *O Processo* |
| Romance epistolar | *Flores para Algernon* |
| Novela com aparato crítico | *O Alienista* |
| Poema épico com notas do tradutor | *Odisseia* |
| Coletânea de contos | *Os 100 Melhores Contos de Humor*, *Os 100 Melhores Contos de Crime e Mistério* |
| Livro técnico, em inglês | *The Sherlock Holmes Handbook* |

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

#### Sugestão de capítulo ignorado

Um capítulo é **sugerido** como ignorado quando qualquer um destes vale:

1. O título começa com um rótulo conhecido de material não-narrativo (`Créditos`, `Glossário`, `Notas`, `Sobre o autor`, `Apêndice`, `Índice`, `Cronologia`…), comparado sem acento e em minúsculas.
2. O texto contém um **ISBN** — um número de 13 dígitos começando em 978 ou 979. É o que reconhece as páginas de "compre agora e leia" que os e-books comerciais trazem no fim: elas não têm título nenhum, então nenhum outro critério as pega, e um ISBN não aparece em prosa narrativa.
3. O texto tem menos de **10%** da mediana do próprio livro. O critério é relativo porque a mediana variou de 4 mil a 29 mil caracteres entre os quinze livros — um limite fixo serviria para um e falharia nos outros.

E um critério **protege**, vencendo o de tamanho: um título claramente narrativo. Vale para:

- as palavras de estrutura, em português e em inglês: `Capítulo`, `Canto`, `Prólogo`, `Epílogo`, `Interlúdio`, `Parte`, `Livro`, `Relatório de Progresso`, `Chapter`, `Prologue`, `Epilogue`, `Part`, `Book`;
- um número ou numeral romano isolado (`15`, `XIV`);
- um título que **começa** com número e separador (`3 - AS MÃOS, OS PÉS E O VENTRE`, `36. O NÚMERO TRÊS`), que é como as coletâneas numeram os contos.

É o que salva o capítulo 26 de *O apanhador no campo de centeio*, com 11% da mediana do livro, e as fábulas de Esopo nas coletâneas, com 7%.

A ordem dos critérios é rótulo, ISBN, proteção, tamanho — do mais confiável ao mais frouxo. Na prática rótulo e proteção não colidem, porque a comparação de rótulo é por prefixo: um título que começa com número não casa com nenhum rótulo, então um hipotético "1. Prefácio" acaba mantido. É o erro seguro.

#### Resultado nos quinze livros

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
| Os 100 Melhores Contos de Humor | 105 | 4 |
| Os 100 Melhores Contos de Crime e Mistério | 104 | 4 |
| **Total** | **785** | **118** |

**Nenhum capítulo narrativo é escondido em nenhum dos quinze livros.** Alguns acertos que valem registro:

- *Flores para Algernon*: os 17 relatórios de progresso, remontados a partir de 13 arquivos em que as fronteiras eram âncoras.
- *Odisseia*: os 24 cantos limpos, com os 24 documentos de "Notas ao Canto" sugeridos.
- *O Processo*: os 12 capítulos do romance e os 11 fragmentos.
- *O apanhador no campo de centeio*: os 26 capítulos, inclusive o de número 26, com 1.523 caracteres — 11% da mediana — salvo pela proteção de título.
- *As duas coletâneas*: os 100 contos de cada uma, inclusive fábulas de Esopo de 600 caracteres.
- *The Sherlock Holmes Handbook*: os 47 verbetes, com `Introduction`, `Acknowledgments`, `About the Author` e a página de copyright sugeridos.
- *Tress*: os 75 capítulos, que **não têm título** no índice, com as notas de tradução e os cinco anúncios da editora sugeridos.

Sobra menos de um item não-narrativo mantido por livro — cada um a um toque de ser desmarcado.

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

`ignorado` existe porque todo EPUB traz, misturado aos capítulos, material que não é narrativa: créditos, glossário, agradecimentos, notas do tradutor, anúncios da editora. A importação **sugere** marcando este campo (ver item 2.2) e o usuário confirma — nada é descartado no parsing. Acrescentado depois da validação contra quinze livros reais, que mostrou que nenhum critério automático separa os dois com segurança.

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

Implementação concreta inicial: `ProvedorOpenRouter`, parametrizada por `id_modelo`. Provedores nativos adicionais (Groq, Gemini) podem ser adicionados depois seguindo a mesma interface, se necessário.

> **Divergência registrada (item 1.5):** a primeira versão desta seção nomeava a interface como `AIProvider`, a implementação como `OpenRouterProvider` e o parâmetro como `render_profile`. Os nomes foram traduzidos para `ProvedorIA`, `ProvedorOpenRouter` e `perfil_renderizacao` por coerência com a regra de idioma: existe tradução natural, então o português prevalece. Definido antes de a pasta `ia/` ser preenchida, para não renomear código depois.

### 4.3 Configuração de modelos

Tela de configuração permitindo:
- Cadastro da API key do OpenRouter (armazenada em variável de ambiente/config segura, nunca hardcoded).
- Seleção de modelo para extração de elementos (passo 6) e para montagem de prompt (passo 8), com opção "usar o mesmo modelo para os dois" marcada por padrão.
- Lista de modelos obtida dinamicamente do endpoint `/models` do OpenRouter (com filtro opcional para mostrar só os gratuitos).

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
| Posição no índice **descartada** como sinal | Em *O Processo* a única seção aninhada é o apêndice e os doze capítulos estão na raiz: o sinal se inverte e esconde o romance inteiro. Contribuía com exatamente um item nos quinze livros |
| Anúncios de outros livros reconhecidos pelo ISBN no texto | Essas páginas não têm título nenhum, então nenhum critério de título as pega. Um número de 13 dígitos começando em 978 ou 979 não aparece em prosa narrativa |
| Texto antes da primeira âncora colado no capítulo anterior | O Calibre parte arquivos grandes no meio de um capítulo; sem isso, 42 mil caracteres do relatório anterior virariam um capítulo sem título e o relatório apareceria partido em dois |
| Material não-narrativo **sugerido** como ignorado, não descartado | Medição em quinze livros: nenhum dos quatro sinais testados separa narrativa de apêndice com segurança. Esconder narrativa é muito pior que listar um glossário, então nada é descartado — a importação sugere e o usuário confirma |
| Limite de tamanho **relativo à mediana do livro**, não absoluto, e fixado em 10% | A mediana variou de 7 mil a 44 mil caracteres entre os quinze livros, então um limite fixo serviria para um e falharia nos outros. Os 10% saíram de uma varredura: acima disso começa a esconder narrativa |

---

## Etapa 6 — Pendências / Próximos Passos

- [ ] Confirmar formalmente o stack mobile (assumido Kotlin + Jetpack Compose nativo Android).
- [x] ~~Definir estrutura de pastas/módulos do projeto Python (FastAPI).~~ Concluído — ver item **1.5**.
- [ ] Desenhar as rotas da API (endpoints, contratos de request/response).
- [ ] Esboçar as telas do app (fluxo de UI, especialmente os passos 6-9 de confirmação/ajuste).
- [x] ~~Permitir marcar um capítulo como ignorado.~~ Concluído — campo `Capitulo.ignorado`, pré-sugerido pela importação e confirmado pelo usuário (itens 2.2 e 3.4a). Falta expor o ajuste na API e no app.
- [ ] Relações entre elementos e Grupos com membros explícitos (v2, fora do escopo do MVP).
