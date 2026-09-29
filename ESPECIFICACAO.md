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
- **Mobile**: **Kotlin + Jetpack Compose (Android nativo)** — confirmado (Etapa 5, decisão registrada). Telas esboçadas na Etapa 7.
- **Distribuição do app**: instalação manual do APK (sideload), sem passar pela Play Store — uso pessoal, só no próprio celular do Allan, ao menos por enquanto. Ver Etapa 5.

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

> **Bug real, achado testando manualmente com um EPUB de conversão de terceiros (não um dos dezoito livros de validação), e corrigido.** A importação respondia 500 — `TypeError: 'Link' object is not iterable` — ao percorrer o TOC. Causa: o `ebooklib` normalmente devolve cada entrada aninhada do TOC como uma lista (mesmo com um filho só, uma seção vem como `(Secao, [Link])`), mas na leitura de alguns EPUBs (aparentemente o formato varia conforme a ferramenta que gerou o arquivo) uma entrada solta vem como objeto direto — `(Secao, Link)`, sem a lista — ou até o TOC inteiro como um único `Link` solto, sem lista nenhuma ao redor. A função que achata o índice (`_entradas_do_indice`) assumia sempre a forma "com lista" e quebrava ao tentar iterar sobre um objeto que não é iterável. Corrigido normalizando qualquer entrada que não seja lista/tupla para uma lista de um item só, antes de iterar — cobre os dois casos (TOC inteiro solto, e filho de seção solto) com a mesma checagem, porque a função já era recursiva. Não reproduzível escrevendo um EPUB com o próprio `ebooklib` (a escrita sempre normaliza para lista) — o teste de regressão chama a função interna diretamente, com um objeto que imita a forma encontrada na leitura real.

> **Efeito colateral observado, não necessariamente um bug do sistema.** O mesmo EPUB rendeu só 3 capítulos para um romance inteiro, e um dos títulos recuperados saiu com caracteres de substituição (`�`) — indício de um problema de codificação no próprio arquivo (uma conversão de terceiros, pelo nome do arquivo). Não investigado a fundo ainda; se aparecer de novo noutro livro, vale medir contra o corpus de validação como os outros achados de parsing.

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
- **SugestaoDeElemento**: um elemento que a IA identificou num capítulo (fase 1 do item 4.4), persistido — não um resultado descartável. Aponta para um `Elemento` real quando resolvida (automaticamente, por nome, ou manualmente, pelo usuário). Ver item 3.4e.
- **SugestaoDeCena** / **SugestaoDeParticipante**: o equivalente, do lado da cena sugerida (`tipo=CENA`) — um frame candidato e os elementos sugeridos que participam dele. Ver item 3.4e.
- **HistoricoIdentidadeElemento**: o que um capítulo específico revela/acrescenta sobre a *identidade* de um Elemento (quem ele é, não sua aparência) — ver item 3.4f. Ao contrário de `EstadoElemento`, é cumulativo: um registro não substitui o anterior, soma-se a ele.

### 3.2 Relacionamentos

- Um Elemento pode aparecer em vários Frames de vários Capítulos (muitos-para-muitos).
- Um Elemento tem vários EstadoElemento ao longo da história (um por "momento narrativo relevante").
- Um Frame referencia um ou mais Elementos (com o Estado vigente de cada um naquele ponto) — exatamente um, se `tipo=PERSONAGEM`.
- Um Prompt está associado a um Frame (e, por meio dele, aos Elementos/Estados usados como contexto) e a uma Imagem.
- Um Capítulo tem várias SugestaoDeElemento e várias SugestaoDeCena (uma rodada de `POST /capitulos/{id}/sugestoes`). Uma SugestaoDeCena referencia várias SugestaoDeElemento (via SugestaoDeParticipante) do **mesmo** capítulo (item 3.4e).
- Um Elemento tem vários HistoricoIdentidadeElemento ao longo da história (um por capítulo em que algo novo foi revelado sobre quem ele é — nem todo capítulo gera um registro, ver item 3.4f).

### 3.3 Decisões de modelagem (justificativas)

- **Elemento genérico em vez de tabelas por tipo**: personagens, ambientes, objetos, criaturas etc. compartilham a mesma necessidade — manter consistência visual ao longo da narrativa. Um enum `tipo` evita duplicação de schema e lógica.
- **EstadoElemento separado da identidade do Elemento**: personagens envelhecem, se ferem, trocam de roupa; objetos quebram; ambientes são destruídos/reconstruídos. Fixar uma única "descrição visual" no Elemento geraria inconsistência entre capítulos distantes da história.
- **Frame com atributos situacionais embutidos**: evita criar uma entidade "Contexto" isolada para informações (horário, clima) que já são naturalmente parte do próprio frame.
- **PerfilRenderizacao em vez de campo único de "estilo"**: permite reutilizar combinações de estilo/iluminação/paleta entre livros, e adaptar à ferramenta de geração de imagem usada (cada uma tem sintaxe própria).
- **Relações entre elementos e Grupos com membros explícitos**: ideia boa, mas adiada para uma v2 — exige tabela de relacionamento tipo grafo e telas extras no app; não é essencial para o MVP (Elemento + Estado + Frame + Prompt + Imagem).
- **HistoricoIdentidadeElemento como tabela própria, em vez de sobrescrever `Elemento.descricao`**: identidade e aparência têm semânticas de tempo opostas. Aparência é um retrato num ponto da narrativa — sobrescrever é correto, porque o personagem realmente está diferente agora (`EstadoElemento`, item 3.3 acima). Identidade é cumulativa — o que o capítulo 8 revela (um segredo, uma origem) continua verdade no capítulo 20; sobrescrever perderia o que já foi revelado antes. Por isso identidade precisa de histórico somado, não de um campo único reescrito a cada leitura. Ver item 3.4f e 4.4 (fase 2b).

### 3.4 Campos das entidades

Esta seção detalha as colunas de cada tabela. Foi preenchida em partes:

- **(a)** `Livro` e `Capitulo` — a base da importação do EPUB. **Implementada.**
- **(b)** `Elemento` e `EstadoElemento` — o coração da consistência visual. **Implementada.**
- **(c)** `Frame`, `PerfilRenderizacao`, `Prompt` e `Imagem` — a geração e o catálogo. **Implementada.**
- **(d)** `Configuracao` — a integração com IA. **Implementada.**
- **(e)** `SugestaoDeElemento`, `SugestaoDeCena`, `SugestaoDeParticipante` — sugestões da IA persistidas. **Implementada.**
- **(f)** `HistoricoIdentidadeElemento` — identidade evolutiva do Elemento, capítulo a capítulo. **Implementada** — resolve a pendência de prioridade alta da Etapa 8.

O modelo do MVP tem 15 tabelas, criadas por migrations que encadeiam a partir de um banco vazio.

Decisões que valem para todas as tabelas:

- **Chave primária**: inteiro autoincremento. Legível na depuração ("capítulo 5 do livro 2"), índices menores — o que conta num Raspberry Pi — e suficiente porque só o servidor cria registros. UUID só faria sentido se o app precisasse criar registros offline, o que não está no escopo.
- **Nomes de tabela no plural** (`livros`, `capitulos`): a tabela guarda muitos; a classe, que representa um, fica no singular.

#### (a) Livro

Metadados do EPUB importado.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `titulo` | texto (500) | não | do metadado `dc:title` do EPUB, ou o nome do arquivo como reserva — nunca nulo |
| `titulo_confirmado` | booleano | não | se `titulo` veio de verdade do `dc:title` (`true`) ou é só o fallback do nome do arquivo (`false`) — item 6.2 |
| `autor` | texto (300) | **sim** | muitos EPUBs não preenchem |
| `idioma` | texto (20) | sim | código do metadado `dc:language` (ex: `pt-BR`) |
| `identificador_epub` | texto (200) | sim | o `dc:identifier` do arquivo (ISBN ou UUID) |
| `nome_arquivo` | texto (500) | não | nome original do arquivo enviado |
| `data_importacao` | data/hora com fuso | não | preenchido pelo banco na inserção |

`identificador_epub` é **indexado, mas não único**: serve para avisar que um livro já foi importado antes, e não para impedir. Muitos EPUBs pirateados ou convertidos repetem identificadores genéricos, e uma restrição de unicidade bloquearia importações legítimas.

`data_importacao` é preenchido pelo próprio banco (`NOW()`), não pelo Python. Assim o horário é o do servidor, consistente entre registros, independente do relógio de quem chamou a API.

**Título e autor são mandatórios do ponto de vista do usuário — item 6.2, implementado, achado testando manualmente com um livro real.** `titulo` nunca fica nulo no banco (cai pro nome do arquivo), e `autor` continua aceitando nulo de propósito (item 3.4a original). Mas os dois são, na prática, informação que o app precisa ter — a tela de importação (Etapa 7) só deveria se dar por concluída com os dois preenchidos, pedindo ao usuário quando a extração não conseguir. Como o import é síncrono (não pode esperar por uma resposta do usuário no meio da chamada), o servidor não bloqueia nada — só sinaliza: `LivroDetalhe.metadados_pendentes` (lista de strings, ex.: `["titulo", "autor"]`) é quem a tela usa pra decidir se ainda falta alguma coisa. Uma lista (não um booleano por campo) porque outros campos podem virar mandatórios no futuro, sem precisar de coluna nova a cada vez — só somar uma checagem. `PATCH /livros/{id}` com `titulo` marca `titulo_confirmado=true`, mesmo que o valor mandado seja igual ao que já estava — digitar é, em si, a confirmação.

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
| `sugestoes_ia` | JSON | sim | **superseded, ver nota abaixo** — a última resposta de `POST /capitulos/{id}/sugestoes` (elementos e frames, sem `elemento_id`) |
| `sugestoes_modelo` | texto (200) | sim | **superseded** — o modelo que gerou `sugestoes_ia` |
| `sugestoes_geradas_em` | data/hora | sim | quando a última rodada de sugestões deste capítulo foi gerada (sobrevive à mudança abaixo) |

> **Divergência registrada.** `sugestoes_ia`/`sugestoes_modelo` nasceram como um blob JSON único por capítulo (cache simples, para a IA não ser rechamada a cada consulta — item 6.7). Discutindo casos reais de teste (um personagem citado com nomes diferentes em capítulos distintos, sem casamento automático), ficou claro que um blob opaco não dava para referenciar nem para buscar: não tinha como o usuário dizer "esta sugestão do capítulo 7 é a mesma pessoa desta do capítulo 3" sem reprocessar tudo. Os dois campos foram substituídos por três tabelas de verdade (`SugestaoDeElemento`, `SugestaoDeCena`, `SugestaoDeParticipante` — item 3.4e), com `id` próprio por sugestão, buscáveis e referenciáveis. `sugestoes_geradas_em` sobreviveu, agora como "quando foi a última rodada de sugestão deste capítulo", sem o texto junto.
>
> A migration que fez essa troca (`694c20b4e5d2`) precisou de um passo extra além do que o Alembic gerou sozinho: `sugestoes_geradas_em` continuou preenchido, com a data da última chamada sob o sistema antigo, mesmo sem nenhuma linha nas tabelas novas — a rota lia esse campo como "já tem sugestão salva" e nunca mais chamava a IA para aquele capítulo, devolvendo uma lista vazia para sempre. Achado testando contra o banco real (capítulos que já tinham sugestão do sistema antigo). A migration zera `sugestoes_geradas_em` de todos os capítulos como parte da própria mudança de schema.

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
| `imagem_ancora_padrao_id` | inteiro | sim | a referência visual de como este elemento normalmente parece (item 4.5) — `SET NULL` ao apagar a imagem |

Valores de `tipo`: `PERSONAGEM`, `AMBIENTE`, `OBJETO`, `CRIATURA`, `GRUPO`, `VEICULO`, `EDIFICACAO`.

`GRUPO` existe como rótulo desde já (serve para agrupar "os Stark", "a Patrulha da Noite"), mas **sem membros explícitos** — a tabela de relacionamento que ligaria um grupo aos seus integrantes continua adiada para a v2, conforme o item 3.3.

Restrição de unicidade em (`livro_id`, `tipo`, `nome`): impede que a extração automática cadastre duas vezes o mesmo personagem no mesmo livro. Inclui o `tipo` porque um nome pode legitimamente designar coisas diferentes — a cidade *Winterfell* e a edificação *Winterfell* são registros distintos.

`descricao` aceita nulo: no momento em que o usuário confirma uma sugestão da IA, pode ainda não haver descrição de identidade definida.

**`imagem_ancora_padrao_id`, separado da âncora por Estado (item 3.1).** Motivado por um cenário real: o usuário gera o retrato de um personagem no capítulo 1, uma cena no capítulo 3, e outra no capítulo 10 — dias depois, possivelmente numa ferramenta de geração de imagem diferente a cada vez. `EstadoElemento.imagem_ancora_id` sozinho não resolve isso: cada novo Estado nasce sem âncora própria, e nada herda automaticamente a do Estado anterior (herdar automaticamente foi cogitado e descartado — arriscado quando a aparência realmente mudou, ex.: personagem ferido, envelhecido). `imagem_ancora_padrao_id` é a "foto-base" do elemento — escolhida à mão pelo usuário, nunca a mais recente automaticamente — e serve de reserva quando o Estado usado num Frame não tem âncora própria (`referencias_visuais`, item 4.5). Mesma separação identidade/aparência que já existe para texto (`Elemento.descricao` vs. `EstadoElemento.descricao`), agora também para imagem.

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
| `formato` | texto (50) | sim | override opcional da proporção — **implementado**, ver nota abaixo |
| `modelo_alvo` | texto (100) | sim | ferramenta de imagem a que o perfil se adapta |

**Não pertence a um Livro.** É o que permite reaproveitar a mesma combinação de estilo entre obras diferentes — o motivo pelo qual o item 3.3 preferiu um perfil a um campo único de "estilo". O vínculo é o contrário: o Livro aponta para o seu perfil padrão.

Todos os campos de estilo aceitam nulo porque cada ferramenta de imagem entende um subconjunto diferente: um perfil voltado a uma delas pode não usar `artista_referencia`, outro pode não usar `formato`.

`modelo_alvo` existe porque cada ferramenta tem sintaxe própria — o mesmo estilo se escreve de um jeito numa e de outro jeito noutra.

**`formato` vira override opcional, não a única fonte da proporção — implementado (item 4.5/6.6).** Achado testando manualmente: como o campo é único por perfil, mas um perfil é compartilhado entre retratos (`Frame.tipo=PERSONAGEM`) e cenas (`Frame.tipo=CENA`), não havia como expressar "retrato vertical, cena horizontal" sem digitar um texto artificial cobrindo os dois casos no mesmo campo (ex.: `"16:9 (para cenários) ou 2:3 (para retratos)"`) — que aí ia parar, literalmente, no bloco de estética do prompt final, sem servir de instrução real pra IA nem pra ferramenta de imagem.

Proporção não é uma escolha de **estilo** (isso já é `estilo`/`artista_referencia`/`iluminacao`/`paleta`) — é uma escolha ligada a **o que está sendo retratado**, informação que o sistema já tem via `Frame.tipo`. A correção: `montar_prompt` passa a decidir a proporção sozinho a partir do tipo do frame — `PERSONAGEM` → `"2:3, portrait orientation"`, `CENA` → `"16:9, landscape orientation"` — e `PerfilRenderizacao.formato` vira um **override opcional**: preenchido, vale pros dois tipos de frame igualmente (mesmo princípio de "explícito sempre vence" que já rege a prioridade do restante do prompt, item 4.4); vazio, usa o padrão automático por tipo.

#### (c) Frame

O recorte de um capítulo que vai virar uma imagem — um retrato solo ou uma cena.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `capitulo_id` | inteiro | não | referência ao Capítulo; indexado |
| `tipo` | enum (`PERSONAGEM`, `CENA`) | não | `PERSONAGEM` só aceita um estado ligado (item 4.4); padrão `CENA` |
| `titulo` | texto (300) | não | como identificar o frame na lista; opcional no pedido de criação para `tipo=PERSONAGEM` — a rota gera a partir do nome do elemento (item 6.4) |
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
| `modelo_perfil` | texto (200) | sim | modelo usado em `POST /livros/{id}/perfis-renderizacao/sugestao` (item 6.5) — campo próprio porque essa chamada é única por livro, não por capítulo, e compensa um modelo mais caro |

**Uma linha só, com `id` fixo em 1.** Não é a modelagem mais elegante, mas é a mais honesta para o que é: não existem "duas configurações" num sistema pessoal de um usuário. A alternativa — uma tabela de pares chave/valor — perderia a tipagem de cada campo e ganharia só flexibilidade que não vai ser usada. Uma restrição `CHECK (id = 1)` impede uma segunda linha aparecer por acidente.

Os quatro campos de texto aceitam nulo porque o sistema precisa subir sem configuração nenhuma: a chave pode estar só na variável de ambiente, e os modelos podem ainda não ter sido escolhidos.

#### (e) SugestaoDeElemento, SugestaoDeCena, SugestaoDeParticipante

Substitui `Capitulo.sugestoes_ia`/`sugestoes_modelo` (nota no item 3.4a). Cada sugestão da IA (fase 1 do item 4.4) vira uma linha própria, com `id` estável — buscável e referenciável, ao contrário do blob JSON que substituiu.

**SugestaoDeElemento**

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `capitulo_id` | inteiro | não | referência ao Capítulo que originou a sugestão; indexado |
| `tipo` | enum (`TipoElemento`) | não | como a IA classificou |
| `nome` | texto (200) | não | como a IA nomeou |
| `descricao` | texto longo | sim | identidade sugerida (fase 1 — não é aparência) |
| `manter_estado_atual` | booleano | não | julgamento da IA: o estado conhecido continua valendo |
| `modelo` | texto (200) | não | o modelo que gerou esta sugestão especificamente |
| `elemento_id` | inteiro | sim | o Elemento real a que esta sugestão corresponde — preenchido automaticamente (nome normalizado casando, como já acontece hoje) ou manualmente pelo usuário |
| `casamento_automatico` | booleano | não | **implementado** — `true` quando `elemento_id` veio só do casamento automático por nome (passo 5 do item 6.7), nunca revisado por uma pessoa; vira `false` quando o usuário confirma ou corrige esta sugestão especificamente (item 6.3, pendência de correção de casamento). Ver "Casamento automático de participante" no item 4.4 |

**`estado_id`, na resposta (não é coluna no banco) — implementado.** `elemento_id` preenchido só diz que a sugestão está ligada a um Elemento; não diz se aquele **capítulo específico** já virou um `EstadoElemento`. Achado com um caso real: a sugestão do capítulo 5 de "Sextus Hospius" já estava casada com o elemento, mas só o Estado do capítulo 3 existia — o elemento ficava "congelado" na primeira aparição até alguém notar e chamar `POST /elementos/{id}/estados-de-sugestoes` manualmente, sem nada na resposta indicando isso. `GET /livros/{id}/sugestoes-elemento` e `POST /capitulos/{id}/sugestoes` (item 6.7) passam a calcular, para cada sugestão com `elemento_id` preenchido, se já existe um `EstadoElemento` com aquele `elemento_id` e `capitulo_id` — devolvendo o id do estado (o mais recente, se houver mais de um; item 3.4b já admite dois estados no mesmo capítulo) ou `null`. É a mesma lógica de campo calculado que `estado_vigente` já usa (item 6.3) — nada de novo no banco.

**SugestaoDeCena**

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `capitulo_id` | inteiro | não | referência ao Capítulo; indexado |
| `titulo` | texto (300) | não | |
| `descricao` | texto longo | sim | |
| `horario` | texto (100) | sim | |
| `clima` | texto (100) | sim | |
| `humor` | texto (100) | sim | |
| `modelo` | texto (200) | não | o modelo que gerou esta sugestão |
| `frame_id` | inteiro | sim | o Frame real criado a partir desta sugestão, quando confirmada |

`modelo` vive em cada linha, não numa coluna só do Capítulo: como `forcar=true` só substitui sugestões ainda não confirmadas, um mesmo capítulo pode acabar com sugestões de rodadas (e modelos) diferentes ao mesmo tempo.

Sempre `tipo=CENA` implícito: a IA só sugere cenas (item 4.4); um retrato (`tipo=PERSONAGEM`) nasce direto de um Elemento, por iniciativa do usuário, nunca de uma sugestão.

> **Divergência registrada, pós-uso real.** A tabela chamava-se `SugestaoDeFrame`, e o campo da resposta de `POST /capitulos/{id}/sugestoes` chamava-se `frames`. Revisando a API, ficou claro que isso reintroduzia, na camada de sugestão, a mesma confusão Cena/Personagem que motivou renomear `Cena` para `Frame` (item 3.4c): a IA sugere uma **cena**, não um Frame — o Frame só passa a existir quando o usuário confirma que aquilo vira de fato um recorte pra gerar imagem. Renomeado para `SugestaoDeCena`/`CenaSugerida`, com o campo da resposta virando `cenas`. `frame_id` continua com esse nome — está correto, é o Frame de verdade que a confirmação cria, não a sugestão.

**SugestaoDeParticipante** (associação, sem `id` próprio — as duas colunas formam a chave primária)

| Coluna | Observação |
|---|---|
| `sugestao_cena_id` | referência à SugestaoDeCena |
| `sugestao_elemento_id` | referência à SugestaoDeElemento — sempre do **mesmo** capítulo da SugestaoDeCena |

**`elemento_id`/`frame_id` nulos não bloqueiam nada — só marcam "ainda não confirmada".** É a mesma filosofia do `elemento_id` que a resposta de `POST /capitulos/{id}/sugestoes` já devolve hoje, só que persistido: a sugestão em si nunca vira Elemento/Frame sozinha, o usuário confirma pelas rotas de cadastro (item 6.3/6.4). A diferença é que agora a confirmação pode ser **em lote** e **cross-capítulo**: `GET /livros/{id}/sugestoes-elemento?nome=...` busca todas as menções de um nome no livro inteiro, e `POST /elementos`/`POST /elementos/{id}/estados` aceitam uma lista de `sugestoes_elemento_ids` para criar um Elemento com um Estado por capítulo, numa chamada só (item 6.3).

**`forcar=true` preserva sugestões já confirmadas.** Regenerar a sugestão de um capítulo (`POST /capitulos/{id}/sugestoes?forcar=true`) só substitui as linhas com `elemento_id`/`frame_id` nulos — uma sugestão já virada Elemento ou Frame de verdade não desaparece numa rodada nova, mesmo que a IA não repita a mesma sugestão da vez anterior.

**Por que não um vínculo direto entre duas sugestões ainda não confirmadas** (ex.: `SugestaoDeElemento.associada_a_id`, auto-referência): foi considerado e descartado. Resolveria o caso de duas sugestões nenhuma confirmada, mas introduziria um conceito novo — cadeia de sugestões pendentes, com as perguntas de o que acontece num ciclo, numa cadeia longa, ou quando `forcar=true` regenera uma sugestão que já está associada. A busca por nome (`GET /livros/{id}/sugestoes-elemento?nome=...`) resolve a mesma necessidade — achar todas as menções de "Hospius" no livro — sem esse conceito extra: o "vínculo" nunca existe como dado solto, só aparece no momento em que o usuário confirma, como a lista de sugestões escolhidas naquela chamada.

#### O que foi implementado

As três tabelas, mais `GET /livros/{id}/sugestoes-elemento`, `sugestoes_elemento_ids` em `POST /livros/{id}/elementos` e no novo `POST /elementos/{id}/estados-de-sugestoes`, e `sugestao_cena_id` em `POST /capitulos/{id}/frames` — 13 testes novos (Etapa 6.3/6.4/6.7).

**`POST /elementos/{id}/estados-de-sugestoes` nasceu como rota própria, não como campo a mais em `POST /elementos/{id}/estados`.** O plano original (item 6.3, antes desta rodada) era só acrescentar `sugestoes_elemento_ids` à rota que já existe. Na hora de implementar, ficou claro o problema: aquela rota cria **um** estado e devolve **um** `EstadoResumo`; confirmar várias sugestões de uma vez cria vários estados. Misturar os dois faria o formato da resposta depender do corpo do pedido — mais simples abrir uma rota nova com resposta sempre em lista.

**Validado com o caso real que motivou tudo isto.** No livro de teste, a IA sugeriu "Sextus Hospius" no capítulo I e só "Hospius" no capítulo V — os dois nomes não casaram pelo nome normalizado, exatamente o problema original. `GET /livros/1/sugestoes-elemento?nome=hospius` achou as duas sugestões, capítulos diferentes; `POST /livros/1/elementos` com as duas em `sugestoes_elemento_ids` criou um Elemento com dois Estados, um por capítulo, numa chamada só; as leituras seguintes de `POST /capitulos/{id}/sugestoes` (para os dois capítulos, sem `forcar`) já mostraram `elemento_id` casado nos dois, sem rechamar a IA. Depois, `POST /capitulos/3/frames` com `sugestao_cena_id` da cena "A chegada de Hospius" resolveu os dois participantes (Hospius e um segundo personagem, Hrolf, confirmado à parte) sozinho, sem `estados_ids` no pedido.

> **Divergência esclarecida, achada testando o caso acima.** Os dois Estados criados por `sugestoes_elemento_ids`/`estados-de-sugestoes` saíram com a **mesma descrição**, mesmo sendo capítulos diferentes — pareceu que o personagem tinha "congelado" na primeira aparição. A causa: o texto vem da sugestão de **identidade** (fase 1, item 4.4 — "quem é", documentada desde o início como algo que não muda entre capítulos), copiada como rascunho pro `EstadoElemento.descricao` — o mesmo padrão que `estado_inicial` já usava. Não é a aparência do capítulo; é só um placeholder até a leitura profunda (fase 2) rodar de verdade. Confirmado ao vivo: gerar um prompt pro Frame de retrato do capítulo V rodou a leitura profunda (`confirmado_pela_leitura_profunda` virou `true`) e reescreveu a descrição com o que o capítulo V realmente diz — bem diferente do capítulo I, que continuou com o rascunho porque nenhum prompt tinha sido gerado a partir dele ainda. Os docstrings de `estados-de-sugestoes` e o `.http` (item 3.4e) ganharam esse aviso explícito, que só existia perto de `estado_inicial` antes.

**Divergência registrada, achada validando contra o banco real.** A migration que cria as tabelas novas e apaga `sugestoes_ia`/`sugestoes_modelo` (`694c20b4e5d2`) inicialmente não tratava `Capitulo.sugestoes_geradas_em` — a coluna sobrevive à troca, com o mesmo nome. Capítulos que já tinham sugestão gerada pelo sistema antigo ficaram com essa data preenchida e nenhuma linha nas tabelas novas: a rota lia "já tem sugestão salva" e nunca mais chamava a IA para aqueles capítulos, devolvendo lista vazia para sempre. A migration ganhou um `UPDATE capitulos SET sugestoes_geradas_em = NULL` como parte da própria mudança de schema — sem isso, qualquer ambiente que já tivesse usado a versão anterior ficaria com capítulos "mudos" depois do deploy.

#### (f) HistoricoIdentidadeElemento — implementado

Resolve a pendência de prioridade alta da Etapa 8: `Elemento.descricao` (identidade) é escrito uma vez, na confirmação, e nunca mais revisitado — diferente de `EstadoElemento.descricao` (aparência), que a leitura profunda (fase 2, item 4.4) atualiza a cada capítulo relevante.

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | chave primária |
| `elemento_id` | inteiro | não | referência ao Elemento; indexado |
| `capitulo_id` | inteiro | não | capítulo que revelou este incremento; indexado |
| `descricao` | texto longo | não | só o que **este** capítulo especificamente acrescenta sobre a identidade — não um resumo acumulado |
| `confirmado_pela_leitura_profunda` | booleano | não | mesmo espírito do campo homônimo em `EstadoElemento`: se este registro já passou pela leitura profunda de identidade (fase 2b, item 4.4), ou é ainda rascunho |
| `data_criacao` | data/hora com fuso | não | preenchido pelo banco |

**Cumulativo, não "última vale".** Diferente da consulta de "estado vigente" (item 3.4b, que pega só o registro mais recente), a "identidade vigente até um capítulo" é a **união** de `Elemento.descricao` (identidade inicial, registrada na confirmação — item 4.4) com todos os `HistoricoIdentidadeElemento` cujo `Capitulo.ordem` seja menor ou igual ao do capítulo em questão, em ordem narrativa crescente:

```
identidade vigente do elemento X até o capítulo N
  Elemento.descricao (identidade inicial)
  + registros de HistoricoIdentidadeElemento do elemento X
      onde Capitulo.ordem <= ordem do capítulo N
      ordenados por Capitulo.ordem asc
```

Isso reaproveita o mesmo princípio já validado para `EstadoElemento` (item 3.4b: ordem narrativa via `Capitulo.ordem`, não ordem de processamento) — o que resolve, de graça, o processamento fora de ordem: se o usuário processa o capítulo 10 antes do 4, a identidade vigente usada ao gerar algo no capítulo 4 nunca inclui o que só o capítulo 10 revelou (evita um "spoiler" retroativo contaminar um ponto anterior da narrativa).

**Não cria registro quando não há nada de novo.** A leitura profunda de identidade (fase 2b, item 4.4) só grava uma linha quando o capítulo realmente acrescenta algo — evita um histórico poluído de "nada mudou" a cada leitura.

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
- `sugerir_identidade(texto_capitulo, elemento, identidade_vigente_ate_aqui, modelo) -> incremento de identidade ou nulo` — **implementado**: a leitura profunda de *identidade* de um elemento específico (fase 2b — ver item 4.4). Instruída a só acrescentar fatos novos, nunca contradizer ou remover o que já é conhecido; devolve nulo quando o capítulo não revela nada novo sobre aquele elemento.
- `fundamentar_frame(texto_capitulo, titulo, descricao, horario, clima, humor, participantes, modelo) -> contexto` — confere "quem, onde, o quê" de um frame do tipo `CENA` contra o capítulo, sem sobrescrever o que o usuário escreveu (fase 3 — ver item 4.4).
- `montar_prompt(descricao_do_frame, elementos, perfil_renderizacao, modelo, contexto_do_livro, comentario_do_usuario) -> texto do prompt` — passo 8, combinando as fontes acima por ordem de prioridade (item 4.4).

Implementação concreta inicial: `ProvedorOpenRouter`, parametrizada por `id_modelo`. Os quatro métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que adivinhar o formato da resposta. Provedores nativos adicionais (Groq, Gemini) podem ser adicionados depois seguindo a mesma interface, se necessário.

> **Divergência registrada (item 1.5):** a primeira versão desta seção nomeava a interface como `AIProvider`, a implementação como `OpenRouterProvider` e o parâmetro como `render_profile`. Os nomes foram traduzidos para `ProvedorIA`, `ProvedorOpenRouter` e `perfil_renderizacao` por coerência com a regra de idioma: existe tradução natural, então o português prevalece. Definido antes de a pasta `ia/` ser preenchida, para não renomear código depois.

> **Divergência registrada, pós-validação com IA real (itens 4.4 e 6.6):** a versão original de `extrair_elementos` devolvia, numa passada só, tanto a identificação de cada elemento quanto uma descrição livre de aparência (`estado_sugerido`) e um veredito de continuidade (`manter_estado_atual`). Testado com `openai/gpt-4o-mini` num capítulo real de *A Vontade de Muitos*, esse desenho misturou atributos entre personagens (atribuiu o "joelho machucado" de um coadjuvante ao protagonista) — o modelo estava tentando descrever a aparência de nove elementos ao mesmo tempo na mesma resposta. Um teste com `google/gemini-2.5-flash` no mesmo capítulo, embora tenha corrigido esses erros, **inventou um elemento que não existe no texto** ("carroça de suprimentos"). O desenho passou a separar identificação (barata, ampla, sem descrição de aparência) de leitura profunda (focada, um elemento por vez, sempre lendo o capítulo de origem do estado) — ver item 4.4.

### 4.3 Configuração de modelos

Tela de configuração permitindo:
- Cadastro da API key do OpenRouter, nunca hardcoded.
- Seleção de modelo para extração de elementos (passo 6) e para montagem de prompt (passo 8), com opção "usar o mesmo modelo para os dois" marcada por padrão.
- Lista de modelos obtida dinamicamente do endpoint `/models` do OpenRouter (com filtro opcional para mostrar só os gratuitos, e mais três sinais — item 4.3, "Mais filtros" abaixo, implementado).
- **Prioridade de IA** (`prioridade_ia`): `ECONOMIA` (padrão) ou `QUALIDADE` — controla se a leitura profunda do item 4.4 relê o capítulo toda vez que um prompt é montado, ou só da primeira vez por estado. Ver item 4.4 para o efeito exato. É um campo pensado para valer também em futuras decisões de custo-vs-qualidade no sistema, não só nesta.

#### De onde vem a chave

**Da variável de ambiente `CHAVE_API_OPENROUTER`, ou do banco — e o banco tem precedência.**

A variável de ambiente faz o sistema subir já configurado e nunca põe a chave num backup de banco. O cadastro pelo app existe porque o servidor roda num Raspberry Pi: trocar de chave ou de modelo não deveria exigir SSH, editar o `.env` e reiniciar o container.

Quem preferir só a variável de ambiente simplesmente nunca usa a tela, e nada muda.

**`GET /configuracao` nunca devolve a chave**, só informa se existe e de onde veio. Uma chave que sai do servidor é uma chave que vaza em log, em cache de app ou numa captura de tela.

> **Divergência registrada, ainda não implementada (Etapa 8).** Especificando o armazenamento local do app mobile (item 7.0), a decisão acima ("o banco tem precedência") foi revertida: chave de API não deve ficar guardada remotamente, nem no banco do servidor. `PUT /configuracao` vai deixar de aceitar `chave_api_openrouter`; a variável de ambiente vira a única forma persistente no servidor, e o app passa a mandar a chave por chamada (header `X-Chave-API-OpenRouter`) quando o usuário configurar uma própria — nunca persistida no servidor. Motivo: o cadastro pelo app fazia sentido pro Allan sozinho, mas guardar a chave de qualquer usuário no banco do servidor não escala pra um cenário com mais de uma pessoa usando o mesmo backend — cada um deveria controlar a própria chave, só no próprio celular.

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

#### Mais filtros em `GET /configuracao/modelos` (implementado)

Hoje só existem `somente_gratuitos` e `contexto_minimo`. Confirmado ao vivo contra o `/models` do OpenRouter (endpoint público, sem chave — 460 modelos na resposta) que os três candidatos identificados na pendência da Etapa 8 existem exatamente como suspeitado:

- **`supported_parameters`** (lista de strings) — contém `"response_format"` e/ou `"structured_outputs"` quando o modelo aceita resposta estruturada/JSON. Ataca direto o erro `"O modelo não devolveu JSON"`, visto com modelos pequenos/gratuitos: testado um modelo gratuito real (`inclusionai/ling-3.0-flash-sante:free`) sem nenhum dos dois na lista — exatamente o tipo de modelo que esse filtro evitaria escolher para extração/prompt.
- **`pricing.completion`** (string, preço por token de saída) — presente em **todos** os 460 modelos, inclusive gratuitos (`"0"`).
- **`top_provider.is_moderated`** (booleano) — presente em todos; 134 dos 460 modelos vieram `true`.

`ModeloDisponivel` (item 4.3, `ia/provedor.py`) ganha três campos: `suporta_json: bool` (derivado de `supported_parameters`), `custo_saida: float` (de `pricing.completion`) e `moderado: bool` (de `top_provider.is_moderated`) — sempre presentes na resposta de cada modelo, não só quando filtrado, porque o custo é informação útil mesmo sem filtrar por ele.

`GET /configuracao/modelos` ganha dois filtros novos, mesmo padrão booleano de `somente_gratuitos`: `somente_com_json` e `somente_nao_moderados` — e um `ordenar_por_custo` (booleano) para ordenar a lista por `custo_saida` crescente, já que "mais barato primeiro" é o caso de uso mais comum ao comparar modelos.

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

- `extrair_elementos` devolve, além de `elementos`, uma lista `cenas`: recortes narrativos específicos do tipo `CENA` (título, descrição, horário/clima/humor quando o texto sustenta, e os participantes — por nome, casados contra os elementos já cadastrados do mesmo jeito que a lista de elementos já fazia). É rascunho, não grava nada — o usuário usa isso para pré-preencher `POST /capitulos/{id}/frames` em vez de montar cada cena do zero. Uma cena sugerida sem nenhum participante é descartada (mesma tolerância a entrada malformada do item 4.2).
- A instrução ganhou definições explícitas de cada `tipo` (o que distingue `OBJETO` de `VEICULO`, `AMBIENTE` de `EDIFICACAO`) e um filtro de relevância para objetos — só inclui um objeto com peso visual memorável na cena, não papelada ou móvel genérico de fundo.

Testado com `gpt-4o-mini` no capítulo I de *A Vontade de Muitos*: da segunda vez, o tabuleiro saiu corretamente como `OBJETO`, e a extração sugeriu cinco cenas cobrindo os momentos certos do capítulo (o resgate na rocha, a partida de tabuleiro, a chegada de Hospius, o interrogatório de Nateo, o contato acidental com o Sapador) — nenhuma delas precisou ser inventada pelo usuário.

#### Fase 2 — Leitura profunda do elemento (passo 8, dentro de `POST /frames/{id}/prompts`)

Antes de montar o prompt, para **cada** estado ligado ao frame, o servidor relê o texto do **capítulo onde aquele estado foi originalmente registrado** (não necessariamente o capítulo do frame) e chama `sugerir_estado`, focando num elemento por vez — é essa concentração, um elemento por chamada, que evita a mistura de atributos da fase 1 antiga. O texto que volta:

- **Sobrescreve** `EstadoElemento.descricao` no banco — o livro é a fonte de verdade para a aparência de um elemento, mesmo que substitua o que foi digitado à mão no passo 7. Capítulos futuros que usam "o último estado conhecido" como contexto (fase 1) também passam a se beneficiar da versão mais fiel.
- É o que entra na montagem do prompt.

Vale tanto para um frame `PERSONAGEM` quanto para um `CENA` — os dois têm elementos com estado, e os dois se beneficiam de uma aparência bem descrita.

#### Fase 2b — Leitura profunda de identidade (implementado)

Resolve a pendência de prioridade alta da Etapa 8. No mesmo ponto em que a fase 2 relê o capítulo de origem de cada estado, o servidor chama também `sugerir_identidade`, passando a **identidade vigente até aquele capítulo** (item 3.4f — `Elemento.descricao` mais a união de `HistoricoIdentidadeElemento` em ordem narrativa) como contexto.

- **Não sobrescreve nada** — ao contrário da fase 2 (aparência), o resultado, quando existe, vira uma **linha nova** em `HistoricoIdentidadeElemento`, presa ao capítulo relido. É a diferença de semântica registrada no item 3.3: identidade acumula, não substitui.
- Quando o capítulo não revela nada de novo sobre aquele elemento (o caso comum — a maioria dos capítulos não acrescenta identidade a todo personagem que aparece), `sugerir_identidade` devolve nulo e nenhuma linha é criada.
- Reaproveita a mesma chamada de IA que já lê o capítulo para a fase 2, com a mesma instrução de "não inventar" — sem chamada de IA extra por elemento, só um retorno a mais na mesma resposta.
- Respeita `prioridade_ia` do mesmo jeito que as fases 2 e 3 (`confirmado_pela_leitura_profunda` de cada `HistoricoIdentidadeElemento`, ver item 4.4 abaixo).

**Por que junto da fase 2, e não da fase 1 (identificação).** Na fase 1, o elemento pode nem existir no banco ainda — não há "identidade vigente" para comparar. A fase 2 já roda depois da confirmação, um elemento por vez, relendo o capítulo de origem: é o ponto natural para também perguntar "isso revela algo novo sobre quem ele é", sem introduzir um terceiro momento de releitura.

#### Fase 3 — Fundamentação do frame (só para `tipo=CENA`)

Um retrato (`tipo=PERSONAGEM`) não tem "quem, onde, o quê" para conferir — é sempre um elemento só. Uma cena (`tipo=CENA`) tem, e é aqui que o teste com IA real expôs um problema de origem: a entidade que hoje é `Frame` chamava-se `Cena` e servia para os dois casos, então a descrição livre de uma cena (que podia citar outros elementos por nome) sempre entrava no prompt de um retrato — mesmo quando a intenção era um retrato solo.

Por isso, para `tipo=CENA` com pelo menos um elemento ligado, o servidor também chama `fundamentar_frame`: relê o capítulo do frame, e confere o que o usuário escreveu (título, descrição, horário, clima, humor) contra o texto, com a aparência de cada participante já estabelecida como contexto. O resultado (`contexto`):

- **Não sobrescreve** `titulo`/`descricao` do frame — fica só em `Frame.contexto_do_livro`, como apoio.
- Entra em `montar_prompt` com prioridade **menor** que a descrição que o usuário escreveu (ver "Ordem de prioridade" abaixo) — feedback direto do usuário: uma releitura automática não deveria poder sobrepor o que uma pessoa que já leu o capítulo escreveu, sob risco de uma alucinação ou ambiguidade da IA divergir do que está confirmado.

Testado com IA real: a fundamentação de uma cena chegou a reler o trecho **errado** do capítulo (um momento bem posterior ao que a cena descrevia) — e o prompt final saiu correto mesmo assim, porque a prioridade protegeu a descrição do usuário. É a ordem de prioridade funcionando como rede de segurança contra a própria leitura automática errar.

#### Releitura tem custo: `prioridade_ia` controla as fases

Repetir a fase 2, a fase 2b e a fase 3 toda vez que um prompt é montado para o mesmo frame tem custo: cada chamada de `sugerir_estado`/`sugerir_identidade`/`fundamentar_frame` é uma chamada de IA a mais, em cima da chamada que monta o prompt em si. Por isso existe `prioridade_ia` (item 4.3), valendo igualmente para todas:

- **`QUALIDADE`**: relê o capítulo de origem de cada estado (fases 2 e 2b), e fundamenta o frame de novo (fase 3), toda vez que `POST /frames/{id}/prompts` é chamado.
- **`ECONOMIA`** (padrão): relê só a primeira vez. `EstadoElemento.confirmado_pela_leitura_profunda` marca se aquele estado já passou pela fase 2; `HistoricoIdentidadeElemento.confirmado_pela_leitura_profunda` marca o mesmo para a fase 2b (item 3.4f); `Frame.confirmado_pela_leitura_profunda` marca o mesmo para a fase 3 do frame. Enquanto marcados, chamadas seguintes reaproveitam o que já foi lido, sem gastar outra chamada de IA.

#### Ordem de prioridade na montagem final do prompt

Quando há conflito entre as fontes que chegam a `montar_prompt`, a ordem é:

1. **Comentário do usuário** (campo `comentario` do pedido) — prioridade máxima. É uma correção de quem já viu o resultado anterior ou releu o capítulo com atenção.
2. **Descrição do frame escrita pelo usuário** (`titulo`/`descricao`/`horario`/`clima`/`humor`) — vazia para `tipo=PERSONAGEM` (não referencia nada além do elemento).
3. **Contexto do livro** (`fundamentar_frame`, só para `tipo=CENA`) — a leitura automática, usada só para preencher o que a descrição do usuário não cobriu, nunca para contradizê-la.

Não existe rota separada de "refinar": gerar de novo com um comentário é a mesma rota (`POST /frames/{id}/prompts`), chamada de novo — o histórico de tentativas já fica em `GET /frames/{id}/prompts`.

#### Identidade do elemento como contexto, e gênero explícito no prompt

Melhoria a pedido do Allan, revisando um retrato gerado sem indicação de gênero. A leitura profunda de um estado (fase 2, `sugerir_estado`) já recebia `descricao_do_elemento` (a identidade — `Elemento.descricao`) como contexto desde o início; mas essa identidade **não chegava** nem em `fundamentar_frame` (fase 3, cena) nem em `montar_prompt` (montagem final) — os dois recebiam só `"Nome: aparência"` de cada elemento (`_elementos_do_frame`), nunca quem o elemento é.

`_elementos_do_frame` passa a montar `"Nome (identidade): aparência"` quando `Elemento.descricao` existe, e `"Nome: aparência"` quando não — alimentando `fundamentar_frame` e `montar_prompt` de uma vez, sem precisar de uma terceira leitura. A instrução de `montar_prompt` (item 4.5) ganhou uma regra: se o gênero estiver claro pela identidade ou aparência fornecida, deixar isso inequívoco no prompt (ex.: "man"/"woman") — sem inventar quando a informação não permitir concluir.

> **Divergência achada testando com IA real, e reforçada.** A regra existia, mas ficou sem efeito na prática: um retrato de "Auri" (identidade em português dizia "uma jovem" — feminino, pelo artigo) saiu sem nenhuma palavra de gênero no prompt final em inglês. Causa provável: a regra vivia embutida no meio da descrição do bloco 2 ("sujeito num instante congelado"), disputando atenção com a instrução de pose — pouco destaque pra uma regra que devia ser seguida sempre. Reforço: a regra virou um item próprio da seção "Regras" (mesmo nível dos `PROIBIDO`), e ganhou uma autoconferência explícita antes do formato de resposta — "isso aparece marcado sem ambiguidade em algum lugar do texto? Se não, corrija antes de responder" — mesmo padrão já usado no reforço de linguagem temática da sugestão de perfil (item 6.5). Ainda não validado com IA real de novo.

### 4.5 Engenharia das instruções de IA

Revisão feita a partir de material técnico externo (um documento de boas práticas de engenharia de prompt de imagem, preparado com apoio do Gemini) confrontado com o que já estava validado neste projeto. A regra ao incorporar algo foi: **adotar a técnica de escrita das instruções, sem reabrir a modelagem de dados já testada** — a alternativa (um JSON rico por elemento, com campos separados para material, iluminação, objetos etc.) foi considerada e descartada, ver Etapa 5.

#### O que foi incorporado

- **Descrição concreta, não adjetivo vazio.** `_INSTRUCAO_DE_ESTADO` (fase 2) e `_INSTRUCAO_DE_PROMPT` (passo 8) agora pedem material e textura (linho puído, couro rachado) em vez de qualificadores ("roupas simples"), e proíbem adjetivos subjetivos de qualidade ("lindo", "incrível", "épico") — um modelo de imagem não sabe o que fazer com "lindo", mas sabe o que fazer com "seda ao luar".
- **Emoção como física, não como palavra.** Em vez de "ele estava triste", a instrução pede a tradução em postura e expressão visíveis ("olhar baixo, ombros curvados") — a mesma lógica de "não confiar em metáfora literária" que já regia a leitura profunda, agora explícita para a IA.
- **Instantâneo congelado.** Modelos de imagem não representam ação contínua ("ele entra, pega o livro e sai"). As duas instruções agora pedem explicitamente uma pose ou gesto parado, específico do capítulo.
- **Template estruturado em `montar_prompt`.** O prompt final passa a seguir uma ordem fixa de blocos — enquadramento de câmera → sujeito num instante congelado → vestuário/textura/expressão → cenário imediato → fundo/arquitetura/época → iluminação/atmosfera → estética final — com vocabulário de fotografia/cinema (medium shot, golden hour, cool moonlight) para o resultado parecer uma adaptação cinematográfica, não uma ilustração genérica.
- **Bloco de estética separado da prosa, não tecido nela — implementado e validado com IA real.** Achado revisando a API a pedido do Allan: o bloco 7 ("Estética final") pedia pra IA *tecer* os campos do perfil de renderização na mesma prosa corrida da cena/sujeito — o que os campos do perfil já são estruturados no banco (`estilo`/`artista_referencia`/`iluminacao`/`paleta`/`formato`) não sobrevivia até o prompt final, porque a IA reescrevia tudo numa frase só, com liberdade de parafrasear. A instrução agora pede um bloco final **separado** e **estruturado** (`"Style: X. Lighting: Y. Palette: Z. Format: W. Reference: V."`), com a regra explícita: aqui a IA só traduz PT→EN literalmente, sem interpretar — diferente dos blocos 1-6 (cena/sujeito), onde ela tem liberdade criativa de verdade. Testado com IA real (retrato de "Will"): o bloco final saiu exatamente no formato pedido, com os campos do perfil traduzidos literalmente. Duas imprecisões pequenas, aceitas por ora sem novo ajuste: (1) a prosa também descreve pincelada/paleta com as próprias palavras, redundante com o bloco final — parcialmente esperado, já que o bloco 6 (iluminação) já pede pra derivar do estilo; (2) a IA separou os dois blocos com uma quebra de linha (`\n\n`), o que diverge um pouco de "texto corrido só" — a instrução pedia as duas coisas ao mesmo tempo ("corrido" e "separado"), e a IA resolveu essa ambiguidade à própria maneira.
- **Identidade vs. situação.** `_INSTRUCAO_DE_ESTADO` passa a separar o que tende a não mudar entre capítulos (rosto, cor de cabelo, altura, compleição) do que muda com a cena (roupa, ferimento, sujeira) — preserva o primeiro a menos que o texto diga o contrário, atualiza o segundo com o que o capítulo mostra. É um reforço direto contra o problema de consistência de personagem entre capítulos distantes.
- **Referências visuais na resposta do prompt.** O campo `EstadoElemento.imagem_ancora_id` já existia desde o item 3.1, mas nunca tinha sido lido por nenhuma rota. `PromptDetalhe` (item 6.6) ganhou `referencias_visuais`: as imagens-âncora já aprovadas para os elementos da cena, para o app avisar "anexe esta imagem também" ao usuário — o fluxo de geração é manual (passo 9), então a API não anexa a imagem sozinha, só avisa que ela existe. Estendido no item 4.7 com uma âncora padrão por Elemento, além da âncora por Estado.
- **Linguagem temática residual reforçada em `_INSTRUCAO_DE_PERFIL` — implementado.** Pendência adiada do item 6.5: o bug de mistura de movimentos artísticos já tinha sido corrigido, mas sobrava um resíduo mais fraco (ex.: `"paleta que sugere perigo e duplicidade"`) — a palavra temática aparecendo *dentro* de uma frase visual, não isolada. A instrução ganhou um exemplo negativo concreto desse padrão e um "teste" explícito: "um ilustrador consegue desenhar literalmente o que você escreveu, sem interpretar sentimento ou intenção narrativa?". Ainda não validado com IA real.

#### O que foi avaliado e descartado

- **Esquema JSON rico por elemento** (campos separados como `physical_description`, `clothing`, `architecture_and_materials`, `key_objects_in_scene`), em vez do texto livre único em `EstadoElemento.descricao`. Reabriria uma modelagem já testada de ponta a ponta (item 3.4b), exigiria migration e mexeria em toda a cadeia de rotas por um ganho que a mudança de instrução já entrega em boa parte: pedir para a IA *escrever* com esse nível de concretude no texto livre, em vez de *estruturar* isso em campos.
- **"Chunking" do capítulo** (dividir em blocos menores antes de mandar para a IA). O item 4.3 já mediu isso nos dezoito livros de validação: todos os modelos gratuitos com 32 mil de contexto ou mais comportam o maior capítulo medido inteiro. Dividir criaria um problema novo — cada pedaço perderia o contexto dos outros, piorando exatamente a mistura de atributos que a fase 2 já resolve ao ler o capítulo inteiro.
- **Fallback por gênero/tom do livro** quando um capítulo não descreve a aparência de um elemento (a sugestão era "deduzir a estética a partir do gênero"). Rejeitado: é a mesma classe de erro que produziu a "carroça de suprimentos" inventada no teste com `gemini-2.5-flash` (item 4.2). A regra do projeto continua sendo devolver a descrição já registrada e não inventar nada — o livro é a fonte de verdade, não o gênero.
- **Título/autor do livro como contexto de `montar_prompt`** (a pedido do Allan, pensando em ajudar a IA com mais contexto). Rejeitado pelo mesmo motivo do item acima: dar à IA "conhecimento geral" sobre a obra (gênero, época, estilo do autor) convida a preencher lacunas com suposição em vez de usar só o que foi de fato apurado do capítulo — reabriria o mesmo canal que produziu a "carroça de suprimentos". Diferente da sugestão de perfil (item 6.5), que recebe título/autor de propósito porque **não tem** texto de capítulo nenhum pra divergir — aqui `montar_prompt` já recebe a fonte real (aparência apurada, contexto fundamentado), e título/autor não preencheria lacuna nenhuma, só abriria risco.
- **Geração de imagem automatizada via OpenRouter** (modelos como FLUX.1/SDXL, com um padrão `Strategy`/`Adapter` para trocar de provedor). É uma mudança de arquitetura real — o passo 9 do fluxo (item 2.1) é deliberadamente manual, e automatizar geração envolve custo por imagem, escolha de provedor e um fluxo de UI diferente do que a Etapa 7 já esboçou. Fica como ideia registrada para uma decisão futura, não decidida nesta rodada.
- **Prefixo de texto para colar direto no Gemini** ("Crie uma imagem fotorrealista horizontal..."). É uma questão de UX do app (Etapa 7), e o app ainda não existe — fica anotado no item 7.7 (tela de Prompt) como algo a considerar quando a tela for implementada, não no backend.

### 4.6 Confirmação incentivada, nunca forçada (implementado)

O público-alvo do app é o leitor lendo o livro **pela primeira vez**, gerando sugestões capítulo a capítulo — mas nada garante que ele confirme todas antes de seguir em frente. Discussão registrada aqui porque mudou o desenho de duas pendências da Etapa 8 ao mesmo tempo.

**Por que não forçar processamento sequencial (não pular capítulo).** Foi cogitado e descartado. `Capitulo.ordem` (item 3.4b) já garante consistência de dado mesmo fora de ordem — pular capítulo não corrompe nada tecnicamente. O que pular prejudica é só a **qualidade do casamento automático**, porque `estados_conhecidos` (o contexto que a IA usa para reconhecer um elemento já visto) depende de **quanto já foi confirmado**, não de quantos capítulos já foram lidos ou processados. Forçar sequência também quebraria de propósito um uso legítimo: alguém que já leu o livro e quer gerar imagens de cenas favoritas fora de ordem.

**Por que não exigir "ler antes de analisar".** Inverificável — o servidor não tem como saber se o usuário leu o capítulo antes de tocar em "Analisar com IA". Forçar isso na tela (ex.: exigir rolar até o fim do texto) é fácil de contornar e não ataca o problema real: mesmo tendo lido, o usuário pode confiar demais numa sugestão específica e não conferir — foi o que aconteceu no caso real que motivou esta discussão (ver abaixo).

**O problema real encontrado**, testando o fluxo de confirmar uma cena sugerida: o casamento automático de **participante** (item 6.7, passo 6 — mesma normalização de nome usada para elementos) associou um personagem a um `Elemento` errado, e confirmar a cena (`sugestao_cena_id`, item 6.4) levou esse erro direto para um Frame de verdade, sem nenhum ponto em que o usuário fosse obrigado a revisar aquele casamento específico — a confirmação em lote da cena (deliberadamente rápida, para não repetir título/descrição) não distingue "elemento_id veio de confirmação explícita" de "elemento_id veio só do casamento por nome, nunca revisado".

**Decisões:**

1. **`SugestaoDeElemento.casamento_automatico`** (item 3.4e) sinaliza, por participante, quando o `elemento_id` veio só do casamento automático por nome — sem bloquear nada, só tornando visível o que hoje é silencioso. A tela de Capítulo (7.5) destaca participantes com `casamento_automatico=true` antes do usuário confirmar a cena.
2. **`POST /capitulos/{id}/sugestoes` sinaliza sugestões pendentes em capítulos anteriores** do mesmo livro (contagem de `SugestaoDeElemento`/`SugestaoDeCena` com `elemento_id`/`frame_id` nulo, capítulos com `Capitulo.ordem` menor que o capítulo analisado). Não bloqueia a análise do capítulo atual — só avisa, porque é exatamente esse cenário (analisar um capítulo novo com pendências acumuladas) que deixa `estados_conhecidos` mais pobre e o casamento automático mais arriscado. A tela de Livro (7.4) também mostra, por capítulo, um indicador de quantas sugestões ainda faltam confirmar.
3. **Corrigir só o casamento, sem criar Estado junto** (pendência já registrada na Etapa 8, puxada para este mesmo escopo): hoje, toda forma de mudar `elemento_id` de uma sugestão cria um `EstadoElemento` como efeito colateral (item 3.4e) — o que serve bem ao caso comum (reconhecer o personagem de novo), mas não ao caso de o casamento automático ter errado e o usuário só querer desfazer. Nova rota `PATCH /sugestoes-elemento/{id}` (item 6.3) ajusta só `elemento_id` (inclusive para `null`, desfazendo o casamento), marca `casamento_automatico=false` (é uma correção explícita) e não grava Estado nenhum.

Juntas, essas três decisões substituem "impedir o erro" (impossível de garantir 100%, com uma IA não determinística) por "tornar o erro visível e barato de corrigir" — a auditoria continua sendo do usuário, mas com sinal de onde olhar e um jeito de um clique só para desfazer quando algo passar batido.

#### O que foi implementado

Toda a rodada desta seção, junto da identidade evolutiva (item 3.4f/4.4 fase 2b) e das duas pendências técnicas menores (`GET /estados/{id}`, filtros de `GET /configuracao/modelos`) — **31 testes novos, 304 no total, todos passando**. Migration `f3a7c9d1b2e4` (nova tabela `historico_identidade_elemento`, coluna `casamento_automatico`).

**O que foi verificado nesta rodada:** o comportamento de cada rota/campo novo contra o `ProvedorFalso` e o SQLite de teste (casamento automático marcando `casamento_automatico=true`, `PATCH /sugestoes-elemento/{id}` corrigindo sem criar Estado, confirmar a mesma cena duas vezes respondendo 409 com o `frame_id` existente, `estado_id` nulo quando casado mas sem Estado no capítulo, `sugestoes_pendentes_anteriores` contando elementos e cenas de capítulos anteriores, a fase 2b criando `HistoricoIdentidadeElemento` só quando há algo novo e só uma vez por par elemento/capítulo mesmo em `QUALIDADE`), e os três nomes de campo do OpenRouter (`supported_parameters`, `pricing.completion`, `top_provider.is_moderated`) confirmados ao vivo contra o `/models` real antes de implementar.

**Ainda não verificado:** nenhuma chamada de IA real ainda testou `sugerir_identidade` — a instrução (`_INSTRUCAO_DE_IDENTIDADE`) segue o mesmo padrão já validado de `_INSTRUCAO_DE_ESTADO`, mas o comportamento de "não inventar quando não há nada de novo" e "não contradizer o que já é conhecido" só foi exercitado com o `ProvedorFalso`. Vale rodar contra o corpus de validação (*A Vontade de Muitos*, capítulos de "Vis") antes de considerar a fase 2b madura — é o mesmo tipo de validação que revelou a mistura de atributos na fase 1 original (item 4.2).

### 4.7 Consistência visual entre capítulos distantes e entre ferramentas diferentes (implementado)

Discussão levantada por um cenário real do Allan: ele gera o retrato de um personagem no capítulo 1, uma cena com ele no capítulo 3, e outra no capítulo 10 — possivelmente dias depois, e cada geração pode acontecer numa ferramenta de imagem diferente (a geração é manual, passo 9 — o sistema não controla qual ferramenta o usuário escolhe naquele dia). Cada ferramenta interpreta a mesma descrição de texto de um jeito visualmente distinto, então texto sozinho não seria suficiente para segurar consistência entre ferramentas.

**O mecanismo existente (item 3.1, `EstadoElemento.imagem_ancora_id`) já ataca parte do problema, mas tem um buraco.** A âncora vive no **Estado**, não no Elemento. Cada novo capítulo relevante pode virar um `EstadoElemento` novo (item 3.4b), e um estado novo nasce **sem** âncora — nada herda automaticamente a âncora do estado anterior. Se o usuário esquecer de reatribuir manualmente (o caso mais provável, "vários dias depois"), `referencias_visuais` do capítulo 10 vem vazia, e a ferramenta de imagem gera um rosto do zero, sem nenhuma referência.

**Solução: `Elemento.imagem_ancora_padrao_id` (item 3.4b), separado da âncora por Estado.** "Como este elemento normalmente parece" — uma referência visual de nível de **identidade**, ao lado da âncora de nível de **aparência** que já existia. `referencias_visuais` (`rotas/prompts.py::_referencias_visuais`) passa a cair nela quando o Estado ligado ao frame não tem âncora própria:

1. Âncora do **Estado** ligado ao frame, se existir — mais específica, "como ele está *nesta* cena".
2. Senão, a âncora **padrão** do Elemento — "como ele normalmente parece".
3. Sem nenhuma das duas, o elemento não entra na lista (mesmo comportamento de antes).

**Herança automática (copiar a âncora do estado anterior pro novo) foi cogitada e descartada.** Perigosa quando a aparência realmente mudou — um personagem ferido ou envelhecido herdaria uma referência visual desatualizada, e o sistema não tem como distinguir esse caso de "nada mudou" sozinho. `imagem_ancora_padrao_id` é sempre uma escolha explícita do usuário (via `PATCH /elementos/{id}`), nunca inferida automaticamente — mesmo princípio de "a IA nunca decide identidade/aparência sozinha" que já rege o resto do sistema.

**Gatilho na tela (Etapa 7, ainda sem código):** ao importar de volta uma imagem gerada (`POST /prompts/{id}/imagens`, passos 10/11), o app oferece duas marcações possíveis, nenhuma automática — "âncora deste Estado" (já existia) e "referência principal do Elemento" (nova). O usuário decide as duas, ou nenhuma.

Migration `a92e5f1c8d3b`. 4 testes novos (311 no total). Verificado contra `ProvedorFalso`/SQLite de teste: a âncora padrão preenche `referencias_visuais` quando o Estado não tem âncora própria, a âncora do Estado vence quando as duas existem, `PATCH /elementos/{id}` responde 422 pra uma imagem inexistente, e apagar a imagem-âncora padrão não apaga o elemento (`SET NULL`).

---

## Etapa 5 — Decisões Técnicas e Justificativas

| Decisão | Motivo |
|---|---|
| Python + FastAPI em vez de Java + Spring Boot | `ebooklib` mais maduro que as opções Java para parsing de EPUB; footprint mais leve no Raspberry Pi; chamadas assíncronas naturais para IA; oportunidade de aprendizado (conhecimento básico prévio em Python) |
| Kotlin + Jetpack Compose (Android nativo) confirmado como stack mobile, em vez de Flutter/React Native | O app é distribuído por instalação manual do APK (sideload), sem Play Store, só para o próprio celular do Allan — sem alcance multiplataforma como objetivo, o custo extra de um framework cross-platform não compra nada. Nativo aproveita a familiaridade já existente com JVM (mesmo motivo do backend em Python/FastAPI: oportunidade de aprendizado sobre uma base que já existe) |
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
| Identidade do elemento incluída no contexto de `fundamentar_frame` e `montar_prompt` (`"Nome (identidade): aparência"`), e regra de gênero explícito na instrução de prompt | A pedido do Allan, revisando um retrato sem gênero indicado no texto final. A identidade já ia para a leitura profunda de um estado (`sugerir_estado`) desde o início, mas nunca chegava nas duas chamadas seguintes — a IA que monta o prompt final nunca via quem o elemento é, só a aparência |
| `referencias_visuais` em `PromptDetalhe`, lida a partir de `EstadoElemento.imagem_ancora_id` | O campo existia desde o item 3.1 mas nunca tinha sido lido por nenhuma rota — a consistência de personagem entre capítulos distantes dependia só da descrição em texto. Expor as imagens-âncora dos elementos da cena permite ao app avisar o usuário para anexá-las também, já que o fluxo de geração é manual (passo 9) |
| "Chunking" de capítulo e fallback por gênero/tom do livro, ambos descartados (item 4.5) | O primeiro fragmentaria o contexto que a leitura profunda depende de ter inteiro (item 4.3 já mediu que nenhum capítulo do corpus de validação excede a janela dos modelos gratuitos); o segundo é a mesma classe de erro que produziu o elemento inventado ("carroça de suprimentos") num teste real — o livro é a fonte de verdade, não o gênero |
| Geração de imagem automatizada (FLUX.1/SDXL via OpenRouter) não adotada nesta rodada | É mudança de arquitetura real, não afinação de prompt: custo por imagem, escolha de provedor e uma UI diferente da que a Etapa 7 já esboçou (fluxo manual de copiar/colar, passo 9). Registrada como ideia para decisão futura, não decidida sem o usuário |
| `extrair_elementos` também sugere `cenas` (recortes narrativos), na mesma chamada da fase 1 | Feedback do usuário revisando uma extração real: uma lista de elementos soltos não bastava, faltava sugerir quais combinações formam um momento que vale ilustrar. Juntar na mesma chamada evita reler o capítulo inteiro de novo só para esse fim |
| Filtro de relevância para objetos, e definições explícitas de cada `tipo` na instrução de extração | O mesmo teste real mostrou objetos irrelevantes (papelada genérica) e classificação errada (tabuleiro como `AMBIENTE`, porta como `VEICULO`). A instrução ganhou exemplos e um critério — "teria peso visual memorável?" — para reduzir os dois problemas |
| Sugestões persistidas em tabelas próprias (`SugestaoDeElemento`/`SugestaoDeCena`/`SugestaoDeParticipante`), não num blob JSON por capítulo (item 3.4e) | Um blob não é buscável nem referenciável: não dava para achar "todas as menções de Hospius no livro" nem confirmar várias de uma vez. Testado o caso real: "Sextus Hospius" (capítulo 3) e "Hospius" (capítulo 7) não casaram pelo nome normalizado, e a causa raiz (gerar sugestões em lote, sem confirmar nada entre chamadas, priva `estados_conhecidos` da informação que ajudaria a IA a reconhecer) não elimina a necessidade de uma confirmação manual para os casos em que o casamento automático ainda assim falhar |
| Confirmação em lote via Elemento/EstadoElemento, sem vínculo direto entre duas sugestões não confirmadas (`associada_a_id` descartado) | Um vínculo sugestão-para-sugestão resolveria o mesmo caso, mas introduziria conceito novo (cadeia pendente: ciclo, cadeia longa, o que fazer se `forcar=true` regenerar uma sugestão associada). A busca por nome cross-capítulo (`GET /livros/{id}/sugestoes-elemento?nome=...`) resolve a mesma necessidade de descoberta sem esse conceito extra |
| `SugestaoDeFrame` renomeada para `SugestaoDeCena` (campo da resposta `frames` → `cenas`), pouco depois de criada | Revisão da API expôs que a tabela reintroduzia, na camada de sugestão, a mesma confusão Cena/Personagem que motivou renomear `Cena` para `Frame` na geração (item 3.4c) — a IA sugere uma cena, não um Frame; o Frame só existe quando o usuário confirma |
| `tipo`/`nome` de `ElementoNovo` viram opcionais (com padrão vindo da primeira sugestão referenciada), revertendo a decisão original do item 3.4e | Exigir os dois sempre, mesmo confirmando uma sugestão só (sem ambiguidade nenhuma), era atrito sem necessidade — a ambiguidade só existe combinando sugestões com nomes diferentes entre si, caso em que digitar continua obrigatório |
| Sugestão de perfil de renderização por IA (`POST /livros/{id}/perfis-renderizacao/sugestao`, item 6.5) manda só título/autor/idioma, nunca o texto de um capítulo | Diferente de toda outra operação de IA do sistema, que lê o texto real do livro: aqui não há como saber em que capítulo a narrativa de fato começa (prólogos, epígrafes e sumários residuais antecedem o "Capítulo I" em vários livros do corpus de validação), então ler "o primeiro capítulo" arriscava basear o estilo em conteúdo que não representa o livro. A alternativa aceita foi deixar a IA reconhecer a obra pelos metadados |
| Plugin de busca do OpenRouter (`plugins: [{"id": "web"}]`) ligado só em `sugerir_perfil_renderizacao`, nenhuma outra operação | É a única chamada desta camada que não manda nenhum texto do livro para a IA se basear — sem isso, a IA dependeria só do próprio conhecimento prévio, com mais chance de errar a obra ou inventar um estilo genérico para o gênero. Testado com IA real: `perplexity/sonar-pro` (busca nativa) e `anthropic/claude-sonnet-4.5`/`claude-haiku-4.5` deram sugestões visivelmente mais específicas que `openai/gpt-4o-mini` sem busca |
| `HistoricoIdentidadeElemento` cumulativo (soma registros), em vez de sobrescrever `Elemento.descricao` como a fase 2 já faz com `EstadoElemento` | Identidade e aparência têm semânticas de tempo opostas: aparência é um retrato num ponto da narrativa (sobrescrever é correto), identidade é cumulativa (o que o capítulo 8 revela continua verdade no capítulo 20; sobrescrever perderia isso). Ver item 3.3 e 4.4 (fase 2b) |
| "Identidade vigente" calculada por união de registros com `Capitulo.ordem <=` o capítulo em questão, reaproveitando o mesmo princípio de ordem narrativa já validado em `EstadoElemento` (item 3.4b) | Resolve o processamento fora de ordem de graça: identidade revelada só num capítulo posterior nunca vaza para um ponto anterior da narrativa, mesmo que esse capítulo posterior tenha sido processado primeiro |
| Não forçar processamento sequencial de capítulos, nem exigir "leitura antes de análise" | O primeiro reverteria uma decisão já validada (item 3.4b) sem resolver o problema real (qualidade do casamento depende de confirmação, não de ordem) e quebraria o uso legítimo de gerar cenas fora de ordem num livro já lido. O segundo é inverificável pelo servidor e não ataca o caso real encontrado (confiar demais numa sugestão específica, mesmo tendo lido) — ver item 4.6 |
| `SugestaoDeElemento.casamento_automatico` e aviso de sugestões pendentes em capítulos anteriores, em vez de bloquear a confirmação em lote de uma cena | Um teste real mostrou o casamento automático de participante errando silenciosamente e chegando a um Frame de verdade sem revisão. Sinalizar (em vez de bloquear) preserva a confirmação em lote já validada como boa UX, só tornando visível o que hoje é silencioso — ver item 4.6 |
| `PATCH /sugestoes-elemento/{id}` para corrigir só `elemento_id`, sem criar Estado junto | Hoje toda forma de mudar `elemento_id` cria um `EstadoElemento` como efeito colateral (item 3.4e), o que não serve ao caso de só desfazer um casamento automático errado. É o complemento natural da sinalização acima: sem um jeito barato de corrigir, sinalizar o erro sozinho não ajuda muito — ver item 4.6 |
| Confirmar a mesma cena sugerida duas vezes responde 409 (com o `frame_id` já existente), em vez de criar um Frame duplicado | Mesmo padrão já usado para elemento duplicado (item 6.3) — consistência de resposta a erro em todo o projeto. Vale só para `sugestao_cena_id`; um frame manual com `estados_ids` continua sem restrição, porque duplicar participantes pode ser intencional ali |
| `estado_id` calculado na resposta de sugestão (não coluna no banco), em vez de um booleano `tem_estado_neste_capitulo` | Dá pro app navegar direto pro Estado já existente, sem uma segunda chamada — mesmo padrão de campo calculado já usado em `estado_vigente` (item 6.3). Exposto em `GET /livros/{id}/sugestoes-elemento` e em `POST /capitulos/{id}/sugestoes`, não só na busca cross-capítulo, porque a tela de Capítulo (7.5) se beneficia do mesmo sinal na hora da análise |
| `GET /estados/{id}` devolve o estado com o elemento embutido, mesmo padrão de `GET /frames/{id}` | Consistência: a tela não deveria ter que cruzar duas chamadas pra saber de quem é o estado que está mostrando, e o projeto já resolve isso assim em outro lugar |
| `custo_saida`/`suporta_json`/`moderado` sempre presentes na resposta de cada modelo, com filtros booleanos (`somente_com_json`/`somente_nao_moderados`) e ordenação (`ordenar_por_custo`) em vez de um único parâmetro combinado | Mesmo padrão já usado por `somente_gratuitos`/`contexto_minimo` — filtros simples e compostos pelo app, sem inventar uma linguagem de consulta nova. Nomes de campo (`supported_parameters`, `pricing.completion`, `top_provider.is_moderated`) confirmados ao vivo contra o `/models` do OpenRouter antes de especificar, conforme a pendência exigia |
| `Configuracao.modelo_perfil` como campo próprio, em vez de reaproveitar `modelo_extracao` | A pedido do Allan, comparando custo real (`claude-haiku-4.5`: US$ 0,0114 vs. `gpt-4o-mini`: US$ 0,00736 na mesma chamada). A sugestão de perfil acontece uma vez por livro; `modelo_extracao` é chamado a cada capítulo — amarrar os dois obrigaria a mesma escolha de custo para frequências de uso muito diferentes |
| `CategoriaEstilo`, vocabulário fechado de seis famílias de estilo, em vez de deixar a IA escolher livremente | Um prompt gerado a partir de uma sugestão de perfil sem restrição saiu visualmente confuso numa ferramenta de imagem real — a IA tinha misturado "oil on canvas" com "expressionist shadows", dois movimentos artísticos incompatíveis, e usado linguagem temática ("conspiração e revelação") em vez de visual. Restringir a um vocabulário fechado, escolhido pelo usuário ou pela IA dentro do mesmo conjunto, elimina a mistura sem tirar a IA da jogada |
| `POST /perfis-renderizacao` sem atalho de `livro_id` para criar direto de uma sugestão, mantendo duas chamadas separadas (item 6.5) | A sugestão de perfil é deliberadamente de mão única, sem persistir nada — diferente de `sugestao_cena_id` (item 3.4e), que funciona porque aquela sugestão *é* persistida e tem `id` estável. Imitar o atalho exigiria persistir também, sem ganho real (uma chamada por livro, sem o problema de "mesma menção em capítulos diferentes" que justificou persistir sugestão de elemento) |
| `reconheceu_a_obra` como campo explícito, em vez de o app inferir pelo padrão "tudo nulo" | Ambíguo: "tudo nulo" também acontece quando a IA reconhece o livro mas não sabe, por exemplo, um artista de referência específico — um caso parcial legítimo, diferente de não reconhecer a obra. Mesmo princípio já usado em `manter_estado_atual`/`confirmado_pela_leitura_profunda`: tornar visível a confiança do próprio modelo |
| `Elemento.imagem_ancora_padrao_id` (âncora de identidade), separado de `EstadoElemento.imagem_ancora_id` (âncora de aparência) | Sem isso, cada novo Estado nasce sem âncora e nada herda a do anterior — se o usuário processar capítulos distantes no tempo (dias depois, possivelmente noutra ferramenta de imagem), `referencias_visuais` vem vazia e a consistência visual do personagem se perde (item 4.7) |
| Herança automática da âncora do estado anterior pro novo, descartada | Perigosa quando a aparência realmente mudou (personagem ferido, envelhecido) — herdaria uma referência desatualizada sem o sistema ter como perceber a diferença sozinho. A âncora padrão continua sendo escolha explícita do usuário, nunca inferida |
| Bloco de estética do prompt final separado e estruturado, em vez de tecido na mesma prosa da cena | Os campos do perfil de renderização já são estruturados no banco, mas a instrução original pedia pra IA tecê-los na prosa corrida — o que virava paráfrase livre, perdendo precisão nos parâmetros técnicos (item 4.5) |
| Reforço contra linguagem temática residual em `_INSTRUCAO_DE_PERFIL`, com exemplo negativo concreto e um "teste" explícito | O resíduo achado (`"paleta que sugere perigo e duplicidade"`) mostrou que a palavra temática pode aparecer *dentro* de uma frase visual, não só isolada — a regra original não cobria esse caso (item 6.5) |
| `metadados_pendentes` como lista de strings, em vez de um booleano por campo (`titulo_pendente`/`autor_pendente`) | Extensível sem coluna nova: se outro campo virar mandatório no futuro, é só somar uma checagem na função que monta a lista — o esquema de resposta não muda |
| `titulo_confirmado` como coluna própria em vez de inferir "é fallback" comparando `titulo` com o nome do arquivo | O fallback sobrescreve a coluna com um valor indistinguível de um título real depois de gravado — comparar string com o nome do arquivo quebraria assim que o usuário editasse o título pra algo que coincidentemente combina com o nome do arquivo. `autor` não precisa disso: `is None` já é um sinal confiável, porque autor nunca tem fallback |
| Import não bloqueia a gravação por falta de título/autor — só sinaliza via `metadados_pendentes` | O upload é síncrono (item 6.2) e não pode esperar resposta do usuário no meio da chamada. Quem impõe "não avança sem preencher" é a tela de importação (Etapa 7), lendo o sinal que a API expõe |
| Nome sugerido do perfil ("Livro — Categoria") montado na tela, sem campo novo na API | É formatação de exibição (traduzir o enum `categoria_estilo` pra um rótulo legível já é trabalho da tela), e só existe um cliente hoje — centralizar no backend não teria ganho real (item 7.9) |
| Proporção do prompt decidida por `Frame.tipo` (padrão automático), com `PerfilRenderizacao.formato` virando override opcional | Proporção não é escolha de estilo, é escolha ligada ao que está sendo retratado (retrato vertical, cena horizontal) — informação que `Frame.tipo` já tem. Um campo único por perfil, compartilhado entre os dois tipos de frame, forçava o usuário a digitar um texto artificial tentando cobrir os dois casos, que ia parar literal no prompt final sem funcionar como instrução (item 4.5) |
| `referencias_visuais` vazio vira aviso na tela, não bloqueio de `POST /frames/{id}/prompts` — sem mudança de backend, só da tela (Etapa 7) quando existir | Consistente com o padrão já fechado no item 4.6 (sinalizar, nunca travar). Bloquear forçaria sempre gerar retrato solo antes de qualquer cena, impondo uma ordem de trabalho que nem todo usuário quer — a âncora nem precisa vir de um retrato, pode vir de qualquer imagem aprovada (item 4.7). A lista vazia já é o sinal suficiente, sem precisar de campo novo |

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

**`GET /livros/{id}` ganha `sugestoes_pendentes` por capítulo (implementado, item 4.6).** Contagem de `SugestaoDeElemento`/`SugestaoDeCena` daquele capítulo ainda com `elemento_id`/`frame_id` nulo — o que alimenta o indicador de pendência da tela de Livro (7.4), sem exigir uma chamada extra por capítulo.

**`metadados_pendentes` (implementado, item 3.4a) em `POST /livros`, `GET /livros/{id}` e `PATCH /livros/{id}`.** Lista com `"titulo"`/`"autor"` quando a extração não conseguiu obter — título e autor são mandatórios do ponto de vista do usuário, e é essa lista que a tela de importação usa pra saber se ainda falta pedir algo antes de se dar por concluída. Migration `c4d8e29f0a17`.

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
| `POST /livros/{id}/elementos` | Cadastra um elemento confirmado pelo usuário (passo 7); aceita `sugestoes_elemento_ids` para criar um Estado por capítulo sugerido, numa chamada só (item 3.4e) | **implementado** |
| `GET /elementos/{id}` | O elemento com todos os seus estados e todo o histórico de identidade (item 3.4f) | **implementado** |
| `PATCH /elementos/{id}` | Ajusta nome, tipo, descrição e a referência visual principal (`imagem_ancora_padrao_id`, item 4.5/4.7) | **implementado** |
| `DELETE /elementos/{id}` | Remove o elemento e seus estados | **implementado** |
| `POST /elementos/{id}/estados` | Registra um novo estado a partir de um capítulo | **implementado** |
| `POST /elementos/{id}/estados-de-sugestoes` | Registra um Estado por sugestão escolhida, numa chamada só (item 3.4e) | **implementado** |
| `GET /estados/{id}` | Um estado isolado, com o elemento a que pertence | **implementado** |
| `PATCH /estados/{id}` | Ajusta a descrição ou define a imagem-âncora | **implementado** |
| `DELETE /estados/{id}` | Remove um estado | **implementado** |
| `GET /capitulos/{id}/estados-vigentes` | O estado vigente de cada elemento naquele ponto da narrativa | **implementado** |
| `GET /livros/{id}/sugestoes-elemento?nome=...` | Busca sugestões de elemento por nome, em todos os capítulos do livro — acha menções antigas do mesmo personagem para associar (item 3.4e); resposta traz `estado_id` por sugestão (item 3.4e) | **implementado** |
| `PATCH /sugestoes-elemento/{id}` | Corrige só o `elemento_id` de uma sugestão (inclusive para `null`), sem gravar Estado (item 4.6) | **implementado** |

**`GET /estados/{id}` — implementado.** Achado revisando a coleção `.http`: só existiam `PATCH` e `DELETE` para um estado; não tinha como testar (ou o app mostrar) um estado isolado por id, só abrindo o elemento inteiro (`GET /elementos/{id}`, que traz todos os estados) ou pelo estado vigente (`GET /capitulos/{id}/estados-vigentes`). A resposta traz o estado com nome/tipo do elemento a que pertence, mesmo padrão já usado em `GET /frames/{id}` (item 6.4) — a tela não precisa cruzar duas chamadas pra saber de quem é o estado que está mostrando.

**`GET /livros/{id}/elementos` traz o estado mais recente de cada elemento**, e aceita `?tipo=PERSONAGEM` para a tela poder separar por tipo. "Mais recente" é pela ordem **narrativa**, não pela data de criação: o último estado em ordem de capítulo (item 3.4b).

**`GET /capitulos/{id}/estados-vigentes`** é a consulta do item 3.4b exposta como rota, porque é o que dá contexto à IA no passo 6 e ao usuário na tela de revisão. Devolve **todos** os elementos do livro, cada um com o estado que vigorava naquele ponto — ou `null`, quando o elemento ainda não tinha aparecido. O `null` é informação útil: significa "primeira aparição", e é o caso em que não há estado anterior para mandar à IA.

As duas rotas usam uma consulta só, com função de janela, em vez de uma consulta por elemento. A implementação fica em `imagineer/servicos/estados_de_elemento.py` — foi tirada dos testes do item 3.4b, onde vivia como protótipo.

**Criar elemento e primeiro estado no mesmo pedido.** O `POST /livros/{id}/elementos` aceita um `estado_inicial` opcional, porque é assim que o passo 7 funciona: o usuário confirma que o personagem existe *e* como ele está naquele capítulo. Em dois pedidos separados, uma falha no meio deixaria um elemento sem estado nenhum.

**Cadastrar o mesmo elemento duas vezes responde 409.** A restrição de unicidade (`livro_id`, `tipo`, `nome`) do item 3.4b existe justamente porque a extração automática reencontra o mesmo personagem em outro capítulo. A resposta traz o id do elemento que já existe, para o app poder oferecer "usar o existente" em vez de só reclamar.

**O capítulo de um estado precisa ser do mesmo livro do elemento.** Nada no banco impede associar um estado a um capítulo de outro livro — as duas chaves estrangeiras são independentes. A rota verifica e responde 422, porque o dado resultante seria silenciosamente incoerente: o estado apareceria na narrativa errada.

> **Item 3.4e.** `sugestoes_elemento_ids` em `POST /livros/{id}/elementos` resolve o caso em que a IA sugeriu o mesmo personagem em capítulos diferentes, com nomes diferentes demais para o casamento automático reconhecer (ex.: "Sextus Hospius" no capítulo 3, "Hospius" no capítulo 7) — sem isso, o usuário teria que confirmar cada capítulo numa chamada separada, copiando a descrição à mão. Para um elemento **já existente**, o mesmo em lote é `POST /elementos/{id}/estados-de-sugestoes` — rota própria, não o mesmo campo em `POST /elementos/{id}/estados`, porque aquela cria um estado só e devolve um objeto, não uma lista. `GET /livros/{id}/sugestoes-elemento?nome=...` é o que permite achar essas sugestões antes de confirmar, sem vasculhar capítulo por capítulo.
>
> **`tipo`/`nome` são opcionais quando vêm sugestões — segunda divergência sobre a decisão original do item 3.4e.** A primeira versão exigia os dois sempre explícitos, mesmo confirmando uma sugestão só, pelo receio de ambiguidade entre nomes divergentes (o caso Hospius). Revisando na prática, ficou claro que isso é atrito sem necessidade no caso comum (uma sugestão só, sem ambiguidade nenhuma): a rota agora usa `tipo`/`nome` da **primeira** sugestão da lista quando eles não vêm no pedido. Continuam obrigatórios sem nenhuma sugestão referenciada — aí não há de onde tirar um padrão — e digitar continua sendo a única forma de escolher o nome canônico ao combinar sugestões com nomes diferentes entre si.

> **`PATCH /sugestoes-elemento/{id}` — implementado (item 4.6).** Diferente de `POST /elementos/{id}/estados-de-sugestoes`, não grava `EstadoElemento` nenhum — só corrige o vínculo `elemento_id` da sugestão (para um elemento diferente, ou para `null`, desfazendo o casamento). Marca `casamento_automatico=false`, porque é uma correção explícita do usuário. Resolve o caso em que o casamento automático por nome (item 6.7, passo 5/6) associou a sugestão a um elemento errado, sem que o usuário precise apagar um Estado à parte para desfazer o engano.

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
| `POST /capitulos/{id}/frames` | Cria um frame; aceita `sugestao_cena_id` para pré-preencher a partir de uma cena sugerida (item 3.4e) | **implementado** |
| `GET /frames/{id}` | O frame com os elementos e estados que ele referencia | **implementado** |
| `PATCH /frames/{id}` | Ajusta título, descrição e atributos situacionais | **implementado** |
| `DELETE /frames/{id}` | Remove o frame, sem apagar os estados que ele citava | **implementado** |
| `PUT /frames/{id}/estados` | Define a lista completa de estados do frame | **implementado** |

`PUT` e não `PATCH` em `/frames/{id}/estados`: aqui o app manda a lista inteira de quem está no frame, que é como a tela funciona — o usuário marca e desmarca elementos e salva o conjunto. Ids repetidos na lista são aceitos e contados uma vez: a chave primária da tabela de associação já impediria o repetido, e devolver um erro por isso só criaria trabalho para o app.

**`tipo=PERSONAGEM` exige exatamente um estado.** Tanto na criação quanto em `PUT /frames/{id}/estados` — um retrato solo é de um elemento só; duas ou mais pessoas já seria uma cena (item 4.4). A rota responde 422 se a contagem não bater.

**O frame devolve o estado *com* o elemento.** `GET /frames/{id}` traz, para cada estado, o nome e o tipo do elemento a que ele pertence — porque a tela mostra "Ned Stark: capa de pele, barba grisalha", e não o id de um estado solto. É a diferença entre a API servir a tela e a tela ter que remontar tudo.

**Os estados de um frame precisam ser do mesmo livro.** Mesmo problema do item 6.3: nada no banco impede associar a um frame o estado de um personagem de outro livro. A rota verifica e responde 422, listando os ids recusados.

**`titulo` é opcional no pedido de criação quando `tipo=PERSONAGEM`.** A coluna continua obrigatória no banco (item 3.4c), mas exigir que o app digite um título para um retrato solo era pedir de novo uma informação que o próprio pedido já contém: o nome do elemento já está implícito em `estados_ids`. Se `titulo` não vier, a rota gera `"Retrato de <nome do elemento>"` sozinha. Para `tipo=CENA` continua obrigatório — ali o título é a conta do usuário sobre quem, onde e o quê (item 4.4), e o sistema não tem como inventar isso.

> **Divergência registrada, pós-uso real.** O campo nasceu obrigatório para os dois tipos, herdado do antigo `Cena` (item 3.4c). Um teste manual expôs que, para `PERSONAGEM`, `titulo` não é usado em lugar nenhum — `_descricao_do_frame` o descarta — e digitá-lo manualmente é retrabalho sem função, já que o único uso real (identificar o frame na listagem, que não traz nomes de elemento) o sistema já sabe preencher sozinho a partir do estado ligado.

> **Item 3.4e.** Com `sugestao_cena_id`, `titulo`/`descricao`/`horario`/`clima`/`humor` vêm da `SugestaoDeCena` referenciada, a não ser que o pedido também traga um valor explícito para aquele campo — o explícito sempre vence, mesmo princípio do `titulo` do retrato acima. Se `estados_ids` não vier, a rota resolve sozinha, participante por participante: precisa que a `SugestaoDeElemento` de cada um já tenha `elemento_id` preenchido (senão 422, listando quem falta confirmar — **confirmar elemento sempre vem antes de confirmar frame**), e usa o **estado vigente** daquele elemento até este capítulo (mesma função já usada no item 6.3), não exige um estado criado *neste* capítulo especificamente. Ao criar com sucesso, marca `SugestaoDeCena.frame_id`.

> **Confirmar a mesma cena sugerida duas vezes responde 409 (implementado).** Achado revisando a API: nada impedia chamar `POST /capitulos/{id}/frames` com o mesmo `sugestao_cena_id` mais de uma vez — cada chamada criava um Frame novo, sobrescrevendo `SugestaoDeCena.frame_id` sem aviso, e o Frame anterior ficava órfão no banco (confirmado testando: três chamadas seguidas, três Frames, só o último referenciado). Mesmo princípio já usado para elemento duplicado (item 6.3): se `sugestao_cena_id` referencia uma `SugestaoDeCena` cujo `frame_id` já está preenchido, a rota responde 409 com o `frame_id` existente, para o app oferecer abrir o Frame já criado em vez de duplicar. Vale **só** quando o pedido usa `sugestao_cena_id` — criar um frame manualmente com `estados_ids` (sem sugestão) continua livre, porque aí duas cenas com os mesmos participantes podem ser legítimas (dois momentos diferentes do capítulo com o mesmo elenco).

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

#### Sugestão de perfil por IA (item 6.5)

| Método e caminho | O que faz | Estado |
|---|---|---|
| `POST /livros/{id}/perfis-renderizacao/sugestao` | Sugere um perfil de estilo, só com os metadados do livro | **implementado** |

O usuário normalmente cria o perfil de renderização à mão, mas ainda não leu o livro nesse momento — não tem como saber que estilo combina com a obra. A ideia surgiu como pendência técnica (Etapa 8), virou rascunho de validação e, com as três decisões abaixo fechadas, sai do estado de rascunho.

**Por que só metadados, e não o texto de um capítulo.** A primeira ideia era ler o primeiro capítulo, como as outras operações de IA fazem. Foi descartada: não há como saber de antemão em qual capítulo a narrativa de fato começa (prólogos, sumários residuais e epígrafes aparecem antes do "Capítulo I" em vários dos livros de validação) — ler o capítulo errado daria um estilo baseado em conteúdo que não representa o livro. Em vez disso, a rota manda só `titulo`/`autor`/`idioma` (`Livro`) e pede para a IA reconhecer a obra — inclusive **buscando na internet**, usando o plugin de busca do OpenRouter (`plugins: [{"id": "web"}]`, ligado só nesta chamada). Isso troca o risco de ler o trecho errado do livro pelo risco de a IA confundir com outra obra homônima ou, sem autor, ter menos certeza — por isso a instrução pede para devolver os campos como `null` (não como texto genérico) quando não reconhecer a obra com confiança.

**Não persiste nada.** Ao contrário de `SugestaoDeElemento`/`SugestaoDeCena` (item 3.4e), não existe casamento por nome nem necessidade de reconsultar entre capítulos — é uma sugestão de mão única. O usuário decide se usa a resposta para preencher `POST /perfis-renderizacao` ou ignora.

**Testado com IA real, comparando modelos.** Com `openai/gpt-4o-mini` (o mais barato configurado), a sugestão para "A Vontade de Muitos" (James Islington) saiu genérica ("fantasia épica, detalhes suaves"). Com modelos intermediários (`anthropic/claude-haiku-4.5`) e mais caros (`anthropic/claude-sonnet-4.5`, `perplexity/sonar-pro`), o resultado ficou muito mais rico e específico — citou "Marc Simonetti"/"Caravaggio" (referências de verdade) e detalhes de paleta/iluminação coerentes com a obra. Comparando `claude-haiku-4.5` (US$ 0,0114, 767ms) com `gpt-4o-mini` (US$ 0,00736, 590ms) na mesma chamada, a diferença de custo (~55%) compensou a diferença de qualidade — mas só porque é **uma chamada por livro**, não por capítulo.

**Campo de modelo próprio: `modelo_perfil`, separado de `modelo_extracao`.** Amarrar a sugestão de perfil ao mesmo modelo usado para extrair elementos (chamado a cada capítulo, dezenas de vezes por livro) obrigaria escolher entre "barato o bastante para não pesar no capítulo 40" ou "bom o bastante para a única chamada que vale a pena caprichar" — as duas coisas têm frequência de uso muito diferente para compartilhar a mesma configuração de custo. `Configuracao.modelo_perfil` (migration `eea9a38d1007`) resolve isso: `PUT /configuracao` aceita o campo separado, e a rota responde 422 se ele não estiver escolhido (mesmo padrão de `modelo_extracao`/`modelo_prompt`, item 4.3).

**Bug encontrado testando com `perplexity/sonar-pro`, e corrigido:** o modelo devolveu `"artista_referencia": "nulo"` como texto, em vez de usar `null` de verdade no JSON. `_texto_ou_nulo` (função compartilhada por toda a camada `ia/openrouter.py`) passou a tratar um conjunto de palavras (`nulo`, `null`, `none`, `n/a`, "não informado") como ausência de valor, e a instrução do modelo foi reforçada para pedir explicitamente o valor JSON `null`.

**Testado sem autor** (zerando temporariamente `Livro.autor` de um livro real e restaurando em seguida): com um livro de título reconhecível, a IA ainda identificou a obra e devolveu uma sugestão rica, sem repetir o bug do "nulo" — não foi possível validar ainda o comportamento com um livro realmente desconhecido (título genérico e sem autor), que é o caso em que a instrução de devolver `null` sem inventar importa mais.

**Bug real encontrado usando o prompt de verdade numa ferramenta de imagem, e corrigido: mistura de movimentos artísticos incompatíveis.** Uma sugestão livre (sem restrição nenhuma de vocabulário) devolveu `"oil on canvas style, dramatic realism with expressionist shadows"` — pintura a óleo realista **e** expressionista ao mesmo tempo, dois movimentos que se contradizem — e usou linguagem temática/narrativa em vez de visual (`"evoking atmosphere of conspiracy and revelation"`, algo que um modelo de imagem não sabe desenhar). O prompt final, gerado a partir desse perfil, saiu visualmente confuso na ferramenta de geração.

**Correção: `CategoriaEstilo`, um vocabulário fechado de seis famílias de estilo** (`FOTORREALISTA_CINEMATOGRAFICO`, `PINTURA_A_OLEO`, `AQUARELA`, `ARTE_DIGITAL_CONCEITUAL`, `QUADRINHOS`, `CARTOON_ANIMACAO` — enum puro em `imagineer/modelos/configuracao.py`, sem coluna no banco). `SugestaoDePerfilPedido.categoria_estilo` (opcional, no corpo de `POST /livros/{id}/perfis-renderizacao/sugestao`) deixa o usuário escolher a categoria de antemão — pensando numa futura tela de criação de perfil com opções pré-definidas — e a IA detalha os atributos **dentro** dela, em vez de escolher livremente. Sem categoria informada, a IA ainda escolhe uma sozinha, mas restrita ao mesmo vocabulário fechado — nunca mais uma combinação livre. A resposta (`PerfilRenderizacaoSugestao.categoria_estilo`) sempre informa qual categoria foi usada, mesmo quando a IA que escolheu.

Testado com IA real (`claude-haiku-4.5`) nas três categorias: sem restrição a IA escolheu `ARTE_DIGITAL_CONCEITUAL` sozinha; forçando `PINTURA_A_OLEO`, citou Caravaggio/Rembrandt (coerente); forçando `CARTOON_ANIMACAO`, citou referências de anime — nenhuma mistura de movimentos nas três. Ainda sobra um resquício de linguagem temática misturada aos termos visuais (ex.: "sugere perigo e duplicidade") — mais fraco que o bug original, registrado como refinamento futuro, não bloqueia o uso.

#### Três decisões que fecham o rascunho

**1. `POST /perfis-renderizacao` não aceita `livro_id` — continuam duas chamadas separadas (sugerir, depois criar).** Foi cogitado um atalho de uma chamada só, no mesmo espírito de `sugestao_cena_id` em `POST /capitulos/{id}/frames` (item 3.4e). A diferença que descarta a ideia: `sugestao_cena_id` funciona porque aquela sugestão é **persistida** — tem um `id` estável que o usuário já viu antes de confirmar. A sugestão de perfil é deliberadamente de mão única, sem persistir nada (parágrafo acima); imitar o mesmo atalho exigiria persistir também, reabrindo uma decisão já tomada sem ganho real (é uma chamada por livro, não tem o problema de "mesma menção em capítulos diferentes" que justificou persistir sugestão de elemento). Manter duas chamadas também segue o mesmo princípio usado no resto do sistema: toda sugestão de IA passa por um ponto de revisão explícito antes de virar dado real — aqui, o próprio campo `nome` (que a sugestão não tem) já obriga o usuário a passar por `POST /perfis-renderizacao` conscientemente.

**2. `PerfilRenderizacaoSugestao.reconheceu_a_obra` (booleano) — implementado.** Antes, a IA sem reconhecer o livro devolvia todos os campos `null`, e nada na resposta dizia *por que* — o app não tinha como distinguir isso de "reconheceu o livro, mas não sabe um artista de referência específico" (caso parcial legítimo). A instrução (`_INSTRUCAO_DE_PERFIL`) agora pede o campo explicitamente, com a regra clara: `true` sempre que a obra foi identificada com confiança razoável, mesmo que campos específicos fiquem nulos por falta de informação; só `false` quando a IA genuinamente não sabe de que livro se trata. Ausente na resposta (modelo antigo, ou que ignorou parte da instrução) conta como `true` por padrão — um falso "não reconheci" seria pior que simplesmente não ter o aviso. Mesmo princípio já usado em `manter_estado_atual`/`confirmado_pela_leitura_profunda`: tornar visível a confiança do próprio modelo, em vez do app adivinhar.

**3. Reforçar mais a instrução contra linguagem temática residual — implementado (item 4.5).** O resíduo achado (`"sugere perigo e duplicidade"` misturado a termos visuais) era mais fraco que o bug original de mistura de movimentos artísticos (já corrigido), mas expôs que a regra original não cobria a palavra temática aparecendo *dentro* de uma frase visual, só isolada. `_INSTRUCAO_DE_PERFIL` ganhou um exemplo negativo concreto e um "teste" explícito ("um ilustrador consegue desenhar literalmente isto?"). Resolvido na mesma rodada que reestruturou o bloco de estética do prompt final — ver item 4.5 e 4.7.

#### O que foi implementado nesta rodada

`reconheceu_a_obra` em `PerfilRenderizacaoSugerido` (`ia/provedor.py`), na interpretação do JSON em `ProvedorOpenRouter.sugerir_perfil_renderizacao` e no esquema `PerfilRenderizacaoSugestao` — 3 testes novos (307 no total). **Ainda não verificado com IA real**: os testes cobrem o parsing (`reconheceu_a_obra=False` explícito, campo ausente contando como `True`) contra o `ProvedorFalso` e um transporte HTTP falso, mas nenhuma chamada real ainda confirmou se o modelo de fato usa o campo do jeito instruído (ex.: se marca `false` de verdade para um título genérico e desconhecido, em vez de inventar uma sugestão genérica mesmo sem reconhecer a obra). Vale testar isso especificamente antes de confiar no aviso na tela.

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
- **`formato` como override opcional, com padrão automático por `Frame.tipo` — implementado (item 3.4c/4.5).** `PERSONAGEM` usa `"2:3, portrait orientation"`, `CENA` usa `"16:9, landscape orientation"`, a não ser que `PerfilRenderizacao.formato` venha preenchido — aí o valor explícito vale pros dois tipos. 3 testes novos (320 no total). Ainda não validado com IA real.
- Erros do provedor seguem o mesmo mapeamento do item 6.7: `ChaveDeApiAusente`/`ModeloNaoEscolhido` → 422, qualquer outro `ErroDoProvedorIA` → 502. Vale para qualquer uma das três chamadas de IA envolvidas.

**A resposta traz `referencias_visuais`** (item 4.5/4.7): a âncora do `EstadoElemento` ligado ao frame quando existe, senão a âncora padrão do `Elemento` (`imagem_ancora_padrao_id`), já aprovadas, deduplicadas. `GET /prompts/{id}` recalcula isso na hora — não é uma foto congelada de quando o prompt foi criado, porque uma âncora pode ser definida depois. Serve para o app avisar "anexe esta imagem também" ao colar o prompt numa ferramenta que aceite referência visual, já que o passo 9 é manual e a API não tem como anexar a imagem sozinha.

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
| `POST /capitulos/{id}/sugestoes` | Sugere elementos e cenas (passo 6); `?forcar=true` ignora o cache e chama a IA de novo | **implementado** |
| `GET /configuracao/modelos` | Lista os modelos disponíveis no OpenRouter (item 4.3); filtros `somente_com_json`/`somente_nao_moderados`/`ordenar_por_custo` | **implementado** |
| `GET /configuracao` | A configuração atual: modelos escolhidos, se há chave cadastrada | **implementado** |
| `PUT /configuracao` | Grava a configuração | **implementado** |

`GET /configuracao` **nunca devolve a chave de API**, só se ela está cadastrada. Uma chave que sai do servidor é uma chave que vaza em log, em cache de app ou em captura de tela.

**`POST /capitulos/{id}/sugestoes` não grava Elemento nem Frame no banco.** É a IA sugerindo; o usuário confirma depois pelas rotas já existentes da Etapa 6.3 (`POST /elementos`, `POST /elementos/{id}/estados`) e da Etapa 6.4 (`POST /frames`). A sugestão em si, porém, é persistida como linhas (item 3.4e). A rota:

1. Busca o texto do capítulo e o estado vigente de cada elemento do livro **até aquele capítulo** (mesma consulta do item 6.3, `estado_vigente_por_elemento`, limitada por `Capitulo.ordem`) — é o contexto que permite à IA responder "manter estado atual" em vez de inventar um estado novo.
2. **Se `Capitulo.sugestoes_geradas_em` já está preenchido e o pedido não veio com `?forcar=true`, não chama a IA** — serve o que já está salvo em `SugestaoDeElemento`/`SugestaoDeCena`.
3. Sem sugestão salva, ou com `forcar=true`: confere se o texto cabe na janela do modelo escolhido (`modelo_extracao` da configuração) **antes** de chamar a IA — gastar a chamada para descobrir que não cabia seria o pior caso (item 4.3).
4. Chama `provedor.extrair_elementos` — só identificação (fase 1 do item 4.4): tipo, nome, descrição de identidade e `manter_estado_atual`. **Não** devolve mais uma descrição de aparência; essa parte é a leitura profunda (fase 2), que só acontece mais tarde, dentro de `POST /frames/{id}/prompts` (item 6.6). O resultado vira linhas em `SugestaoDeElemento`/`SugestaoDeCena`, substituindo só as sugestões ainda não confirmadas do capítulo (item 3.4e).
5. Tenta casar cada sugestão (recém-gerada ou já salva) com um elemento já cadastrado do livro, comparando tipo e nome **sem diferenciar maiúsculas/minúsculas nem acentuação** — a IA foi instruída a repetir o nome exato de um elemento conhecido, mas variações de caixa e acento apareceram como algo razoável de tolerar sem risco de casar elementos diferentes por engano. Quando casa, preenche `elemento_id` **e marca `casamento_automatico=true`** (item 3.4e/4.6, implementado) — ninguém revisou esse casamento específico ainda.
6. Faz o mesmo casamento para cada participante de cada cena sugerida (item 4.4) — mesma normalização, mesmo campo `elemento_id`, mesma marcação de `casamento_automatico`.

**Resposta ganha `sugestoes_pendentes_anteriores` (implementado, item 4.6).** Contagem de `SugestaoDeElemento`/`SugestaoDeCena` com `elemento_id`/`frame_id` nulo em capítulos anteriores (`Capitulo.ordem` menor) do mesmo livro — não bloqueia a chamada, só avisa que o contexto (`estados_conhecidos`) usado nesta análise está mais pobre do que poderia estar.

**Cada `SugestaoDeElemento` da resposta também ganha `estado_id` (item 3.4e, implementado).** Mesmo cálculo de `GET /livros/{id}/sugestoes-elemento`: se `elemento_id` já foi casado (passo 5/6 acima) mas não existe `EstadoElemento` daquele elemento **neste** capítulo, `estado_id` vem `null` — sinal de que confirmar a sugestão ainda falta virar um Estado de verdade, mesmo já estando "casada".

Erros do provedor viram HTTP assim: `ChaveDeApiAusente` e `ModeloNaoEscolhido` e `TextoLongoDemais` → 422 (o problema é a configuração, o usuário resolve pela tela de configuração); qualquer outro `ErroDoProvedorIA` (rede, resposta fora do formato) → 502.

#### O que foi implementado

As três rotas de `/configuracao` foram implementadas junto com a camada de IA (Etapa 4.3), antes desta tabela ser atualizada — o código já existia, só faltava marcar. `POST /capitulos/{id}/sugestoes` é o item novo desta rodada, com 14 testes.

**Divergência registrada, pós-validação com IA real:** o campo `estado_sugerido` foi removido da resposta depois de um teste de ponta a ponta expor mistura de atributos entre elementos (ver a divergência do item 4.2 e a nova fase 2 do item 4.4). Numa rodada seguinte, a resposta ganhou `frames` (então chamado `cenas`) — feedback do usuário depois de revisar uma extração real: a lista de elementos sozinha não bastava, faltava sugerir quais combinações formam um momento que vale ilustrar, e alguns elementos identificados eram irrelevantes (papelada genérica) ou classificados no tipo errado (um tabuleiro de jogo como `AMBIENTE`, uma porta como `VEICULO`).

**Segunda divergência registrada, pós-uso real.** A rota nasceu como consulta pura, sem gravar nada — inclusive a sugestão em si. Testando o fluxo completo na mão, ficou claro o problema: a IA não é determinística, então cada chamada podia devolver um resultado diferente do anterior para o mesmo capítulo, e não havia como saber qual das respostas usar para criar o frame de verdade. A rota passou a salvar a resposta da IA em `Capitulo.sugestoes_ia` (sem `elemento_id`, recalculado a cada leitura) e a servir esse cache por padrão, só chamando a IA de novo com `?forcar=true` — o mesmo princípio de cache-a-não-ser-que-peça-de-novo já usado na leitura profunda e na fundamentação de frame (item 4.4, fases 2 e 3), agora estendido à fase 1.

A checagem de "cabe no modelo" (`conferir_se_cabe`) saiu de método de `ProvedorOpenRouter` para função livre em `ia/openrouter.py`: a rota precisa da mesma checagem antes de chamar **qualquer** provedor, inclusive o `ProvedorFalso` dos testes, e a estimativa de tokens não depende de nenhum detalhe de um fornecedor específico. O método antigo continua existindo, agora só delegando para a função — o que evitou reescrever os testes que já cobriam esse comportamento.

O casamento por tipo e nome normalizado (sem caixa, sem acento) foi verificado com um elemento cadastrado como "João" e uma sugestão da IA vindo como "joão" — casa; com o mesmo nome mas tipo diferente — não casa, porque dois elementos diferentes podem legitimamente ter o mesmo nome (um personagem chamado "Winterfell" e um lugar chamado "Winterfell" não seriam a mesma coisa, hipoteticamente).

> **Terceira divergência, registrada e implementada (item 3.4e).** O casamento automático por nome (parágrafo acima) tem um limite real: só pega variações de caixa/acento, não nomes genuinamente diferentes para a mesma pessoa (`"Sextus Hospius"` num capítulo, `"Hospius"` só, capítulos depois). A causa raiz tem uma parte evitável pelo fluxo de uso — `estados_conhecidos` (o que alimenta o reconhecimento da IA) só inclui elementos **já confirmados com um estado registrado**, então gerar sugestões de vários capítulos em lote, sem confirmar nada entre uma chamada e outra, priva a IA da própria informação que ajudaria a reconhecer o personagem — mas mesmo confirmando capítulo a capítulo, o casamento automático continua limitado a nomes parecidos. `Capitulo.sugestoes_ia` foi substituído por tabelas de sugestão persistidas e buscáveis, com confirmação em lote (`sugestoes_elemento_ids`) para os casos em que o casamento automático falha.

---

## Etapa 7 — Telas do App (Mobile)

Esboço do fluxo de UI, ainda sem código — o objetivo aqui é fechar **quais telas existem, o que cada uma mostra, quais rotas ela consome e para onde ela navega**, antes de tocar em Kotlin (item 7.10, Etapa 8). Cada tela é numerada e mapeada ao passo correspondente do fluxo da Etapa 2.

### 7.0 Arquitetura do app

Decisões de arquitetura, tomadas antes de escrever qualquer código Kotlin — pendência de prioridade alta da Etapa 8 ("criar o projeto Android"), especificada em rodada própria antes da implementação.

**Padrão de tela: MVVM (Model-View-ViewModel).** É o padrão recomendado pelo próprio Google pra Compose, e o mais bem documentado — cada tela tem um `ViewModel` que guarda o estado (o que a tela mostra) e expõe funções pra UI chamar (ex.: "carregar livro", "confirmar sugestão"). A `View` (a função `@Composable`) só lê esse estado e desenha; nunca fala direto com a rede.

**Injeção de dependência: manual, sem Hilt.** Hilt resolve um problema real em apps grandes com muitas dependências cruzadas — não é o caso aqui: o app inteiro fala com um repositório de API só. Um `ViewModel` recebe o cliente HTTP no construtor, sem framework de DI. Menos uma biblioteca pra aprender antes de precisar dela; adotar Hilt depois é viável se o projeto crescer.

**Camada de rede: Retrofit + OkHttp, com `kotlinx.serialization` para JSON.** Retrofit é o padrão de fato do Android há anos — a API do Imagineer vira uma interface Kotlin com anotações (`@GET`, `@POST`) e funções `suspend`, integrando naturalmente com corrotinas. `kotlinx.serialization` (mantida pelo próprio time do Kotlin, não uma biblioteca de terceiros como Moshi/Gson) faz a conversão JSON ↔ classes Kotlin sem depender de reflexão em tempo de execução — mais rápida, e erros de mapeamento aparecem em tempo de compilação, não em produção. Classes de resposta marcadas com `@Serializable`, espelhando os esquemas Pydantic do backend (item 6, cada rota).

**Endereço do servidor: tela de configuração, salvo localmente.** O app pergunta a URL base (ex.: o endereço Tailscale do Raspberry Pi) numa tela simples — a primeira vez que abre, ou em "Configuração" (mesma tela do item 7.10) — e guarda via DataStore (ver "Armazenamento local", abaixo). Evita recompilar/reinstalar o APK só porque o endereço do servidor mudou; funciona bem com o cenário já decidido (sideload, uso pessoal, item 1.3).

**Acesso fora de casa: Tailscale, não porta aberta no roteador.** O servidor fica só na rede interna (item 1.4) — abrir porta esbarraria no NAT da operadora residencial (CGNAT), que a maioria não permite contornar sem IP público dedicado. O Tailscale resolve isso sem precisar de nada no roteador: cada dispositivo (Raspberry Pi e celular) entra numa VPN mesh privada, com endereço próprio estável dentro dela, e o Tailscale fura o NAT automaticamente (ou cai num relay dele mesmo, quando o NAT é restritivo demais). O endereço salvo no app (parágrafo acima) é esse endereço Tailscale — funciona igual dentro e fora de casa. Configuração do celular é única (instalar o app, logar, autorizar o dispositivo); depois disso a VPN roda em segundo plano e reconecta sozinha ao trocar de rede — só é preciso lembrar de isentar o app do Tailscale da otimização de bateria do Android, pra ele não ser derrubado em segundo plano.

**Autenticação da API: nenhuma, de propósito.** A proteção real é de rede, não de aplicação: só quem está na tailnet consegue sequer alcançar o servidor — quem não está nem chega a tentar uma chamada HTTP. Adicionar login pra um app de uso individual seria complexidade (validar token em toda rota, telas de login) sem ganho real de segurança nesse modelo de ameaça. Reconsiderar se um dia o acesso deixar de ser só o Allan (item 1.3 já registrou essa mesma condição pra decisão do stack mobile).

**Grafo de navegação: Jetpack Navigation Compose, com destinos tipados via `kotlinx.serialization`** (mesma biblioteca já escolhida pra rede, item acima — sem strings de rota soltas):

```kotlin
@Serializable object Biblioteca                                    // 7.2 — tela inicial
@Serializable data class Livro(val livroId: Int)                   // 7.4
@Serializable data class Capitulo(val capituloId: Int)              // 7.5
@Serializable data class Frame(val frameId: Int)                    // 7.6
@Serializable data class Prompt(val frameId: Int, val promptId: Int? = null)  // 7.7
@Serializable data class ElementosDoLivro(val livroId: Int)         // 7.8
@Serializable object PerfisDeRenderizacao                           // 7.9
@Serializable object Configuracao                                   // 7.10
```

"Importar livro" (7.3) não é destino próprio — é estado sobreposto à Biblioteca (barra de progresso/diálogo), não uma tela que empilha na navegação. `Prompt.promptId` é opcional: `null` ao gerar um prompt novo a partir do frame, preenchido ao abrir um prompt já existente do histórico. A pilha é hierárquica e simples — Biblioteca → Livro → Capítulo → Frame → Prompt, cada tela empilha a próxima, sem `popUpTo` especial (exceto Importar → Livro, que substitui o estado de importação em vez de empilhar). Elementos do Livro, Perfis de Renderização e Configuração são acessíveis de vários pontos (ícones na barra superior), fora da pilha hierárquica principal.

**Armazenamento local: Jetpack DataStore (Preferences), só pro que precisa persistir hoje.** O app não cacheia livros/elementos/prompts — tudo vem do servidor a cada chamada, já que ele está sempre a uma chamada de distância via Tailscale (item acima). Dois dados salvos localmente, com sensibilidade diferente:

- **Endereço do servidor** (item acima): dado comum, `DataStore` normal (texto plano) basta.
- **Chave de API do OpenRouter — nunca armazenada remotamente, de propósito.** Reabre o item 4.3 do backend: hoje `PUT /configuracao` salva a chave no banco do servidor, com precedência sobre a variável de ambiente — isso muda. `PUT /configuracao` deixa de aceitar `chave_api_openrouter` (implementação pendente, fora do escopo desta especificação do app, mas bloqueia o app funcionar de ponta a ponta até ser feita). A única forma persistente de configurar a chave no servidor passa a ser a variável de ambiente do `.env` no próprio Raspberry Pi (via SSH — hoje já existe como opção, item 4.3), pro uso pessoal do Allan. Para um uso futuro com mais de um usuário, cada um guardaria a própria chave só no celular, nunca no servidor. No app, a chave é um **segredo**, não um dado comum — guardada em `EncryptedSharedPreferences` (ou a variante criptografada do DataStore, biblioteca `androidx.security.crypto`, baseada em Tink), não em texto plano. Toda chamada que envolve IA manda a chave no header `X-Chave-API-OpenRouter`, quando o usuário tiver configurado uma no app; o servidor nunca persiste esse valor — nem em banco, nem em log.

**Erro/offline: sem cache local, tela de erro com "tentar de novo".** Coerente com a decisão de não cachear dado nenhum localmente (item acima) — o app sempre depende do servidor, então sem servidor não há o que mostrar mesmo. Qualquer chamada que falhar (timeout, sem conexão, Pi desligado, Tailscale desconectado) mostra uma mensagem clara ("não consegui falar com o servidor") com um botão pra tentar de novo, em vez de simular um modo offline com dado desatualizado — que introduziria sincronização e conflito sem necessidade real pro uso de hoje.

**Design visual: Material 3 puro, sem tema customizado.** Usa os componentes e cores padrão do próprio design system do Android/Compose (`MaterialTheme` sem paleta customizada), incluindo cor dinâmica (Material You — segue o papel de parede do sistema, Android 12+) e tema claro/escuro automático, seguindo a preferência do sistema. Menos decisão de design pra tomar agora, foco no funcional — trocar por um tema customizado depois é direto, o Material 3 foi feito pra isso.

**Build/assinatura: keystore própria, versionamento semântico simples.** Instalação manual (sideload, item 1.3) ainda exige o APK assinado — o Android recusa instalar um `.apk` sem assinatura. Uma keystore local, gerada uma vez e guardada com cuidado fora do repositório (nunca commitada — mesmo princípio do `.env`/segredos já usado no backend, item 5), assina as releases. `versionCode` incrementa a cada build; `versionName` segue semântico simples (`0.1.0`, `0.2.0`...). Importante: reinstalar uma versão nova por cima de uma antiga só funciona se as duas forem assinadas pela **mesma** keystore — perder a keystore significa ter que desinstalar o app inteiro (perdendo o que estiver salvo localmente, item acima) pra instalar de novo.

**Wireframes (baixa fidelidade, fora do repositório — link vivo abaixo).** Antes de codar, as telas da Etapa 7 foram esboçadas como protótipo clicável, pra validar fluxo e estrutura antes do visual final (Material 3, item acima). Publicado como Artifact (não é um arquivo deste repositório — Kotlin não lê isso, é só material de referência de design): **https://claude.ai/artifact/SYG2RH5qocHEiWuWXZEFEx**. Organizado nos mesmos 5 blocos de jornada que a implementação deveria seguir, cada um cobrindo as telas já numeradas na Etapa 7:

- **Bloco A — Biblioteca e Importação**: 7.2 (Biblioteca) + 7.3 (confirmar metadados pendentes, item 6.2).
- **Bloco B — Leitura e Catalogação**: 7.4 (Livro) + 7.5 (Capítulo — texto, sugestões, cenas).
- **Bloco C — Criação do Frame**: 7.6 (retrato ou cena, elementos ligados).
- **Bloco D — Prompt e Catálogo**: 7.7 (texto do prompt, referências visuais, importar imagem).
- **Bloco E — Gestão Transversal**: 7.8 (Elementos), 7.9 (Perfis de Renderização), 7.10 (Configuração — já reflete a chave de API como segredo local, item acima).

Os wireframes são clicáveis (Biblioteca → Livro → Capítulo → Frame → Prompt, mais os ícones de Elementos/Perfis/Configuração na barra) — dá pra navegar a jornada inteira dentro do Artifact antes de aprofundar tela por tela. **Próximo passo, ainda não feito**: revisar os wireframes e aprofundar bloco a bloco (detalhes de cada tela, estados de erro/vazio, antes de escrever qualquer Kotlin).

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

**Wireframe revisado (29/09/2026, Bloco A):** o estado vazio (que antes só existia em prosa aqui) ganhou tela própria no protótipo — texto convidativo + botão que leva direto pro fluxo de importação, sem passar pela Biblioteca com cards. O botão flutuante "Importar" foi corrigido pra abrir o estado de **progresso** do upload (7.3), não o formulário de metadados — esse só aparece se a extração realmente falhar em achar título/autor.

### 7.3 Importar livro

Não é bem uma tela própria — é o estado de progresso do upload, sobreposto à Biblioteca (passos 1 a 4).

- **Rota**: `POST /livros` (multipart).
- **Durante**: barra de progresso do upload (arquivos grandes existem — o maior do corpus de validação tem 46 MB, item 4.3).
- **Ao terminar**: se `livros_semelhantes` vier não-vazio na resposta (item 6.2), mostra um aviso — "já existe um livro parecido" — com a opção de abrir o existente em vez do novo, ou seguir mesmo assim. Não impede a importação (é aviso, não bloqueio, coerente com o item 3.4a).
- **Se `metadados_pendentes` vier não-vazio (item 6.2), a tela não se dá por concluída.** Título e/ou autor são mandatórios do ponto de vista do usuário — mostra um formulário obrigatório (pré-preenchido com o que a extração conseguiu, ex.: título = nome do arquivo) pedindo pra confirmar/completar antes de navegar pra tela de Livro. `PATCH /livros/{id}` grava a correção; só depois de `metadados_pendentes` vir vazio a importação é considerada concluída. É o único campo obrigatório desta forma por enquanto — mais podem entrar se necessário, sem mudar o mecanismo (a lista já é extensível).
- **Erro**: EPUB inválido (422) mostra a mensagem que a API devolve; a importação é fiel ao que o arquivo diz, então um erro aqui costuma significar arquivo mesmo corrompido, não um bug.

**Wireframe revisado (29/09/2026, Bloco A):** esta era a única tela do bloco com protótipo antes da revisão (só o formulário de metadados pendentes) — os outros três estados descritos acima (progresso, livro semelhante, erro) não tinham tela nenhuma. Agora os quatro existem e são navegáveis em sequência: progresso → (se aplicável) livro semelhante → (se aplicável) metadados pendentes → Livro. A tela de erro traz o texto "a importação é fiel ao que o arquivo diz" explicitamente, pra não parecer bug do app quando o EPUB é que está corrompido.

### 7.4 Livro (detalhe)

Passos 3 a 5: a estrutura de capítulos do livro, e o ponto de entrada para tudo que pertence a ele.

- **Rota**: `GET /livros/{id}` (estrutura, sem texto — item 6.2).
- **Mostra**: metadados (título, autor, idioma), perfil de renderização padrão (ou "nenhum definido"), lista de capítulos em ordem, com indicação visual dos que estão marcados como ignorados, e (implementado, item 4.6) um indicador por capítulo de quantas sugestões ainda faltam confirmar (`sugestoes_pendentes`, item 6.2) — não bloqueia nada, só ajuda o usuário a ver de relance onde falta revisar. **Capítulo com `titulo` nulo** (item 2.2 — os ~11% que nem o título de reserva tirado do texto recupera) **exibe "Capítulo `<ordem>`" como reserva de exibição**, só na tela — não é dado novo da API, mesma lógica do item 7.9 (formatação fica no cliente). Ajustar se necessário quando esta tela for de fato implementada.
- **Ações**: tocar num capítulo não-ignorado abre a tela de Capítulo (7.5); alternar o estado "ignorado" de um capítulo direto na lista (`PATCH /capitulos/{id}`, item 2.2); editar metadados e perfil padrão (`PATCH /livros/{id}`); atalho para "Elementos do livro" (7.6) e para "Perfis de renderização" (7.8); apagar o livro (`DELETE /livros/{id}`) com confirmação — é destrutivo e leva capítulos, elementos, frames, prompts e imagens junto (item 3.4).

**Wireframe revisado (29/09/2026, Bloco B):** editar metadados e apagar o livro saíram de botões soltos na tela e viraram um menu de três pontos na barra superior (junto com um item "Editar metadados e perfil padrão" e outro "Apagar livro", este em vermelho) — decisão do Allan revisando o protótipo: uma ação tão relevante quanto apagar o livro não deveria disputar espaço visual com o dia a dia da tela. O toggle de "ignorado" por capítulo ganhou um ícone próprio em cada linha (arquivar/restaurar), em vez de só mostrar um selo sem ação.

**Pendência registrada, não implementada agora**: o estado "perfil padrão: nenhum definido" (quando o livro ainda não tem perfil escolhido) não tem tela própria no protótipo — fica pra quando a tela for de fato codada, seguindo o mesmo texto reserva já usado noutros lugares desta especificação.

### 7.5 Capítulo

O coração dos passos 5 a 7: ler o texto, pedir sugestões à IA, e confirmar o que de fato existe.

- **Rotas**: `GET /capitulos/{id}` (texto completo), `POST /capitulos/{id}/sugestoes` (passo 6, fase 1 do item 4.4), `GET /capitulos/{id}/estados-vigentes`, `POST /livros/{id}/elementos`, `POST /elementos/{id}/estados`.
- **Mostra**: o texto do capítulo (rolável); um botão "Analisar com IA" que dispara `POST /capitulos/{id}/sugestoes` e traz a lista de elementos identificados (tipo, nome, identidade, `manter_estado_atual`) — **sem** descrição de aparência, porque essa parte só existe na leitura profunda da fase 2 (item 4.4), que acontece mais adiante, na tela de Prompt. Se `sugestoes_pendentes_anteriores` vier maior que zero (implementado, item 4.6), um aviso não-bloqueante: "Você tem N sugestões não confirmadas em capítulos anteriores — confirmar primeiro deixa esta análise mais precisa". Cada participante de cena sugerida com `casamento_automatico=true` (item 4.6) aparece destacado, antes de o usuário confirmar a cena. Uma sugestão já casada (`elemento_id` preenchido) mas com `estado_id` nulo (item 3.4e/6.7) também aparece destacada — "casada, mas ainda não virou Estado neste capítulo".
- **Ações por sugestão**: confirmar (grava `Elemento` + `EstadoElemento` inicial), ajustar tipo/nome antes de confirmar, ou descartar (não faz nada — é só sugestão). Também dá para cadastrar um elemento à mão, sem passar pela IA. A lista de "estados vigentes" (item 3.4b) mostra o que já se sabe de cada elemento do livro até este ponto, útil para o usuário decidir se o que a IA sugeriu já é conhecido. Para um participante com casamento automático destacado, corrigir o vínculo sem confirmar um Estado usa `PATCH /sugestoes-elemento/{id}` (item 6.3/4.6).
- **Navega para**: "Novo retrato" cria um frame `tipo=PERSONAGEM` para um elemento específico e abre a tela de Frame (7.6) já com ele; "Nova cena" cria um frame `tipo=CENA` vazio (ou pré-preenchido a partir de um `frames` sugerido pela IA, item 4.4) e abre a mesma tela pronta para escolher quem mais aparece; lista de frames já criados neste capítulo (retratos e cenas, diferenciados visualmente pelo `tipo`), cada um abrindo a tela de Frame existente.

**Wireframe revisado (29/09/2026, Bloco B):** três coisas que só existiam em prosa aqui ganharam tela no protótipo. (1) "Novo retrato" agora passa por uma tela de escolher o elemento antes de abrir o Frame — no texto original isso já estava implícito ("para um elemento específico"), mas não havia como mostrar essa escolha. (2) A lista de "estados vigentes" citada nas Ações ganhou tela própria, com um botão "Ver estados vigentes do livro" no Capítulo — antes só existia como conceito de rota (`GET /capitulos/{id}/estados-vigentes`), sem lugar nenhum pra aparecer. (3) O ajuste de tipo/nome/vínculo de uma sugestão (`PATCH /sugestoes-elemento/{id}`) ganhou uma tela de formulário simples, acessada por um ícone de lápis em cada sugestão — inclusive pro caso "casada, mas ainda não virou Estado", que agora tem uma linha própria na lista (sem os botões de confirmar/descartar, só o de corrigir vínculo, porque não é uma sugestão nova).

### 7.6 Frame

O recorte de um capítulo que vai virar uma imagem — um retrato solo ou uma cena, passo 6.4.

- **Rotas**: `POST /capitulos/{id}/frames`, `GET /frames/{id}`, `PATCH /frames/{id}`, `PUT /frames/{id}/estados`.
- **Mostra**: `tipo` (retrato ou cena — não editável depois de criado, item 6.4); título; e, só para `tipo=CENA`, descrição e atributos situacionais (horário, clima, humor); a lista de elementos que aparecem no frame, cada um com o estado atual (item 6.4 — a API já devolve o estado com a identidade do elemento, para a tela não ter que remontar isso).
- **Ações**: editar título e, se `CENA`, os demais campos; marcar/desmarcar quais estados de elemento aparecem — num retrato, a tela permite só **um** marcado por vez (a API responde 422 se vier mais de um, item 6.4); os já marcados vêm de `GET /frames/{id}`, salvar manda a lista inteira via `PUT`; apagar o frame (não apaga os estados que ele citava).
- **Navega para**: "Gerar prompt" abre a tela de Prompt (7.7) e já dispara `POST /frames/{id}/prompts`; histórico de prompts já gerados para este frame, cada um abrindo a tela de Prompt no modo "ver resultado existente".

**Wireframe revisado (29/09/2026, Bloco C):** a distinção `PERSONAGEM`/`CENA` — que no texto acima é só "só para `tipo=CENA`" — virou duas telas de protótipo diferentes, porque a diferença não é cosmética: um retrato mostra um único elemento com botão "Trocar elemento" (nunca "adicionar"), enquanto a cena mostra vários com "+ Adicionar elemento". Também ficou mais claro no protótipo que o vínculo de um elemento ao frame não é genérico — é um **Estado específico** daquele elemento (`estados_ids` marcados via `PUT /frames/{id}/estados`), por isso cada elemento na lista agora mostra um chip "Estado: Capítulo N" com link pra trocar qual estado vale ali. Editar e apagar o frame também viraram menu de três pontos, mesmo padrão do item 7.4.

### 7.7 Prompt

Passos 8 a 11 — onde o texto vira, de fato, o insumo para a imagem, e onde a imagem volta para o catálogo.

- **Rotas**: `POST /frames/{id}/prompts`, `GET /prompts/{id}`, `PATCH /prompts/{id}`, `POST /prompts/{id}/imagens`, `GET /imagens/{id}/arquivo`, `DELETE /imagens/{id}`.
- **Ao gerar** (`POST /frames/{id}/prompts`): mostra um indicador de carregamento — as leituras profundas (item 4.4: uma por elemento, e mais uma de fundamentação da cena se `tipo=CENA`) podem levar alguns segundos, então isso não é instantâneo, e a tela precisa deixar isso claro (evita o usuário achar que travou). Um frame `PERSONAGEM` é mais rápido — não tem a fundamentação de cena.
- **Mostra**: o texto do prompt pronto, com um botão "copiar" (passo 9 é manual — colar numa ferramenta de imagem externa) e um botão "Abrir no Gemini" (ver decisão abaixo); campo de comentário opcional, com um botão "gerar de novo com este comentário" que refaz a chamada passando `comentario` (item 4.4 — é a mesma rota, não existe "refinar" separado, e o comentário tem prioridade sobre tudo o mais); histórico de tentativas anteriores do mesmo frame, para comparar.
- **Importar imagem** (passos 10-11): depois de gerar a imagem numa ferramenta externa, o usuário volta ao app e usa o seletor de arquivo do sistema para escolher a imagem, que sobe via `POST /prompts/{id}/imagens`. As imagens já importadas aparecem em miniatura (buscando o arquivo por `GET /imagens/{id}/arquivo`); tocar numa abre em tamanho cheio, com a opção de apagar (`DELETE /imagens/{id}`).
- **Avaliação**: campo de texto livre para anotar como a imagem ficou (`PATCH /prompts/{id}` — item 3.1/6.6), útil para comparar modelos depois.
- **Referências visuais** (item 4.5): se `referencias_visuais` vier não-vazio, a tela mostra essas imagens-âncora com um aviso — "anexe também, para manter a aparência consistente" — antes do botão de copiar. É uma sugestão para a ferramenta externa que aceitar imagem de referência (o Gemini aceita); a API não anexa nada sozinha.
- **`referencias_visuais` vazio também é um sinal — sem mudança de backend, achado testando manualmente (item 4.5/4.7).** Não bloqueia gerar o prompt (mesmo princípio do item 4.6: sinalizar, nunca travar) — mas a tela mostra um aviso não-bloqueante ("nenhum dos elementos desta cena tem referência visual ainda — a consistência entre gerações pode variar mais") quando a lista vem vazia. Sem campo novo na API: a lista vazia já é o sinal, o cliente só precisa checar o tamanho — mesmo raciocínio do item 7.9 (dado que o cliente já tem não vira campo novo).
- **Decisão registrada (29/09/2026): "Abrir no Gemini" via compartilhamento do Android, não geração dentro do app.** Cogitamos gerar a imagem direto no app via API do Gemini — descartado porque a chave do Allan (plano da faculdade) só vale pro app/site do Gemini, sem acesso à API paga, e não faz sentido pagar por uma API quando o mesmo modelo já está disponível de graça pelo app. Também cogitamos o caminho inverso — o Imagineer receber a imagem de volta por compartilhamento, direto do app do Gemini, sem passar pela galeria — descartado: a geração no Gemini não é instantânea, e o usuário provavelmente já vai ter navegado pra outras telas do Imagineer nesse meio-tempo, então não há como garantir que o app "lembra" pra qual prompt aquela imagem pertence quando ela chega. Ficou só a metade que funciona: um botão "Abrir no Gemini" usa `Intent.ACTION_SEND` (o mecanismo de compartilhamento do próprio Android) pra mandar o texto do prompt direto pro app do Gemini, sem precisar copiar manualmente e trocar de app na mão — o botão "Copiar" continua existindo, pra quando o usuário preferir colar em outro lugar. A importação da imagem de volta (passos 10-11) continua manual, pelo seletor de arquivo do sistema, como já estava especificado. **Ainda em aberto, não decidido agora**: encapsular o prompt num prefixo mais natural pro Gemini (ex.: "Crie uma imagem fotorrealista horizontal com a seguinte descrição: ...") em vez do texto cru — fica pra quando a tela for implementada de fato.

**Wireframe revisado (29/09/2026, Bloco D):** o indicador de carregamento citado acima ("mostra um indicador... a tela precisa deixar isso claro") não tinha tela — agora tem, com o texto explicando por que demora (leitura por elemento + fundamentação de cena) e que um retrato é mais rápido. As duas variações de referências visuais (`referencias_visuais` vazio vs. preenchido) também viraram duas telas de protótipo separadas, já que o texto pede coisas visualmente diferentes em cada caso — a com referência mostra as imagens-âncora e o aviso "anexe também" **antes do botão Copiar**, como pedido acima. O "histórico de tentativas anteriores do mesmo frame" ganhou uma lista dentro da própria tela de Prompt (antes só existia no Frame). Tocar numa imagem importada agora abre a tela de tamanho cheio com a opção de apagar, que faltava no protótipo original.

### 7.8 Elementos do livro

Fora do fluxo capítulo-a-capítulo — uma tela de consulta e correção geral, para quando o usuário quer ver ou ajustar um personagem sem estar processando um capítulo específico.

- **Rotas**: `GET /livros/{id}/elementos` (com filtro por tipo), `GET /elementos/{id}`, `PATCH /elementos/{id}`, `DELETE /elementos/{id}`.
- **Mostra**: lista de elementos do livro, separável por tipo (personagem, ambiente, objeto, criatura, grupo, veículo, edificação), cada um com o estado mais recente.
- **Ações**: abrir um elemento mostra todos os seus estados em ordem narrativa (histórico completo — a "ficha" do personagem ao longo do livro); editar identidade (nome, tipo, descrição); apagar (leva todos os estados junto).

**Wireframe revisado (29/09/2026, Bloco B/E):** essa era a lacuna mais séria encontrada na revisão — os cards da lista de elementos não eram clicáveis no protótipo original, e a "ficha" com histórico completo (a ação mais citada nesta seção) não existia como tela. Agora existe: identidade, aparência atual e histórico de estados por capítulo, com editar/apagar acessíveis por um menu de três pontos (mesmo padrão do item 7.4/7.6). Um botão "+" na barra da lista permite cadastrar elemento manualmente, sem depender de sugestão da IA num capítulo.

### 7.9 Perfis de renderização

Lista compartilhada entre livros, acessível tanto pela tela de Livro quanto pela Biblioteca/Configuração.

- **Rotas**: `GET /perfis-renderizacao`, `POST`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`.
- **Mostra**: nome e campos de estilo de cada perfil.
- **Ações**: criar, editar, apagar (não leva livros nem prompts — só desfaz a referência, item 6.5); ao editar um livro, a escolha do perfil padrão usa esta mesma lista.

**Criar a partir de uma sugestão da IA** (`POST /livros/{id}/perfis-renderizacao/sugestao`, item 6.5): abre o formulário de criação pré-preenchido com os campos que a IA sugeriu. **O campo "nome" não vem da API** (a sugestão não devolve nome, de propósito — quem nomeia é o usuário) — a tela pré-preenche sozinha com `"<título do livro> — <categoria_estilo traduzida para exibição>"` (ex.: "A Música do Silêncio — Pintura a Óleo"), editável antes de confirmar. Decisão registrada: isso não precisa virar dado da API porque é formatação de exibição (traduzir o enum `categoria_estilo` pra um rótulo legível já é trabalho da tela), e hoje só existe um cliente — centralizar no backend não teria ganho.

**Wireframe revisado (29/09/2026, Bloco E):** os cards da lista eram só vitrine no protótipo original — "+ Novo perfil" e "Sugerir perfil com IA" não levavam a lugar nenhum, e os cards não abriam nada. Agora cada card abre a edição do perfil (com "Apagar perfil" e a nota de que isso não afeta livros/prompts já usando ele), "+ Novo perfil" abre um formulário em branco, e "Sugerir perfil com IA" abre o formulário pré-preenchido com o nome no formato `"<título> — <categoria_estilo>"` descrito acima.

### 7.10 Configuração

Acessível de qualquer tela.

- **Rotas**: `GET/PUT /configuracao`, `GET /configuracao/modelos`.
- **Mostra**: se há chave cadastrada e de onde ela vem (nunca a chave em si — item 4.3); modelo de extração e de prompt escolhidos; `prioridade_ia` (`ECONOMIA`/`QUALIDADE` — item 4.4).
- **Ações**: cadastrar/apagar a chave; escolher os modelos a partir da lista dinâmica do OpenRouter (com filtro "só gratuitos"); trocar a prioridade de IA.

**Wireframe revisado (29/09/2026, Bloco E):** "de onde ela vem" (mostrar acima) tinha ficado ambíguo no protótipo original — só existia a chave local do app (item 7.0), sem indicar a chave do **servidor** (variável de ambiente), que é a que vale quando o app não manda nenhuma pelo header. Agora são dois cards separados: um pra chave local (com "Apagar chave deste aparelho", que faltava) e um informativo sobre a chave do servidor. Os três modelos (Extração/Prompt/Perfil) eram só texto estático no protótipo original — agora são clicáveis e abrem um seletor com o filtro "só gratuitos" citado acima, que ainda não tinha tela.

### 7.11 Fora do escopo desta rodada

- Login/múltiplos usuários: o sistema é pessoal, de um usuário só (item 1.1) — não há tela de autenticação.
- Notificações push, modo offline, sincronização em segundo plano: nada disso está no MVP.
- Tela de "grupos com membros explícitos": adiada para v2 junto com a modelagem (item 3.1).

---

## Etapa 8 — Pendências / Próximos Passos

- [x] ~~Confirmar formalmente o stack mobile.~~ **Confirmado**: Kotlin + Jetpack Compose (Android nativo). Distribuição por instalação manual do APK, sem Play Store — uso pessoal, só no celular do Allan por enquanto. Ver item 1.3 e a decisão registrada na Etapa 5.
- [x] ~~Definir estrutura de pastas/módulos do projeto Python (FastAPI).~~ Concluído — ver item **1.5**.
- [x] ~~Desenhar as rotas da API (endpoints, contratos de request/response).~~ Concluído — **Etapa 6**, todas as seções (6.2 a 6.7): livros, capítulos, elementos e estados, frames, perfis de renderização, prompts e catálogo de imagens, configuração e sugestões de IA.
- [x] ~~Esboçar as telas do app (fluxo de UI, especialmente os passos 6-9 de confirmação/ajuste).~~ Concluído — **Etapa 7**: dez telas mapeadas às rotas da Etapa 6, mais o mapa de navegação. Ainda sem código — falta criar o projeto Android, próximo item desta lista.
- [x] ~~Permitir marcar um capítulo como ignorado.~~ Concluído — campo `Capitulo.ignorado`, pré-sugerido pela importação e confirmado pelo usuário (itens 2.2 e 3.4a). Exposto na API (item 6.2) e na tela de Livro (item 7.4).
- [ ] **Projeto Android criado (29/09/2026), primeira fatia vertical implementada — falta o resto das telas.** Estrutura Gradle Kotlin DSL em `android/` (módulo `app`, Kotlin 2.0.21, AGP 8.7.2, compileSdk/targetSdk 35, minSdk 26), seguindo a arquitetura do item 7.0 à risca: MVVM sem Hilt (fábricas manuais de ViewModel), Retrofit + `kotlinx.serialization` (sem Gson/Moshi), Navigation Compose com destinos tipados exatamente como o snippet Kotlin do item 7.1 (todos os 8 destinos já declarados em `navegacao/Destinos.kt` e ligados no `NavHost`), DataStore para o endereço do servidor, Material 3 puro com cor dinâmica (sem tema customizado). Implementado de ponta a ponta: **Biblioteca** (item 7.2 — estados de carregando/vazia/com livros/sem servidor configurado/erro, contra `GET /livros` de verdade), **Livro** (item 7.4 — metadados, lista de capítulos com o texto reserva "Capítulo `<ordem>`" pra título nulo, chips de ignorado/sugestões pendentes, atalhos pra Elementos e Perfis, alternar "ignorado" por capítulo direto na lista, e apagar o livro atrás do menu de três pontos com confirmação — **editar metadados e perfil padrão ainda não**, fica pra quando a tela de edição existir de verdade) **Capítulo** (item 7.5 — só o texto completo, rolável, por enquanto: "Analisar com IA", sugestões de elemento/cena, estados vigentes e criar frame ficam pra próximos incrementos, é a tela mais complexa da Etapa 7) **Elementos do livro** (item 7.8 — lista com filtro por tipo, chips "Todos/Personagem/Ambiente/.../Edificação"; cada linha mostra a aparência do estado vigente, não a identidade — `Elemento.descricao` é uma coisa, `EstadoElemento.descricao` é outra, ver item 3.4f; abrir um elemento é a próxima fatia, entrou um destino de navegação novo pra isso, `ElementoDetalhe`, que o item 7.1 não previa por listar só os destinos de topo) **Perfis de renderização** (item 7.9 — lista só leitura, cada card com nome e um resumo de estilo/paleta; criar, editar, apagar e sugerir com IA ficam pra próxima fatia) **Frame** (item 7.6 — retrato ou cena, distinção tratada de verdade na tela, não só cosmética: um retrato mostra só o elemento, sem descrição/horário/clima/humor, porque não há "cenário" a descrever; editar, marcar/desmarcar estados, apagar e gerar prompt ficam pra próxima fatia) e uma versão mínima de **Configuração** (só o endereço do servidor, o suficiente pra Biblioteca funcionar — chave de API, modelos e prioridade de IA ainda faltam, item 7.10). Só a tela de Prompt e a de Elemento (detalhe) existem ainda só como destino de navegação com um texto "ainda não implementada" — a navegação inteira já existe, uma tela de cada vez entra depois, igual foi feito aqui.
  - **Testado**: `BibliotecaViewModelTest` (4 casos), `LivroViewModelTest` (5 casos), `CapituloViewModelTest` (3 casos), `ElementosViewModelTest` (6 casos), `PerfisViewModelTest` (3 casos) e `FrameViewModelTest` (2 casos — sucesso com elementos, erro de rede) cobrem os estados e ações de cada tela sem tocar em Android de verdade — o repositório é trocado por uma API falsa no teste, e o endereço do servidor vem de uma interface (`ProvedorDeEnderecoDoServidor`) em vez do `PreferenciasApp`/DataStore concreto. `./gradlew :app:testDebugUnitTest` roda em JVM puro (23/23 passando). `./gradlew :app:assembleDebug` gera o APK completo sem erro — build compilado e validado neste ambiente (Android SDK mínimo instalado à parte, fora do repositório).
  - **Divergência do plano original**: nenhuma — a arquitetura já estava bem especificada no item 7.0, só faltava mesmo escrever o código. Na tela de Livro, o campo "Perfil padrão" mostra só "definido"/"nenhum definido" por enquanto, sem o nome do perfil (ex.: "Aquarela sombria") — `GET /livros/{id}` só devolve o id (`perfil_renderizacao_padrao_id`), e buscar o nome exigiria chamar `GET /perfis-renderizacao` também; isso fica pra quando a tela de Perfis (7.9) for implementada e o app já tiver um jeito de resolver perfil por id sem duplicar a chamada.
  - **Achado implementando "apagar livro"**: a Biblioteca (7.2), depois de já ter sido aberta uma vez, não recarregava sozinha ao voltar de outra tela — um livro apagado continuaria aparecendo na lista até o app reiniciar. Resolvido de forma geral (não só pro caso de apagar): a Biblioteca agora escuta o ciclo de vida do próprio destino de navegação (`NavBackStackEntry.lifecycle`, não o da Activity) e recarrega toda vez que volta a ficar visível — mesmo mecanismo serve pra quando a importação de livro (item 7.3) for implementada.
  - **O que este ambiente não consegue validar**: não há emulador nem dispositivo físico aqui — o app nunca rodou de verdade, só compilou e passou nos testes de unidade. Cor dinâmica, layout na tela, e o fluxo de navegação tocando na tela real precisam ser conferidos no Android Studio do Allan antes de considerar a fatia "pronta" de fato.
- [ ] **Prioridade: busca nas listas (Biblioteca, Elementos do livro, Capítulos).** Achado na revisão comparativa de UX (29/09/2026, ver "Análise de mercado e diferenciação" abaixo) — nenhuma tela de listagem tem campo de busca, só o filtro por tipo em Elementos (item 7.8). Um livro de fantasia típico passa de 50 elementos e 40 capítulos; toda ferramenta de mercado comparável (Notion, Todoist, a própria Kindle Library) tem busca assim que a lista cresce além de uma tela. Sem isso, o diferencial de acompanhar muitos elementos ao longo de muitos capítulos (ver análise abaixo) vira o próprio motivo do app ficar difícil de usar. Ainda sem desenho de tela — entra na revisão bloco a bloco antes do código Kotlin.
- [ ] **Reabrir o item 4.3: `PUT /configuracao` deixa de aceitar `chave_api_openrouter`.** Achado especificando o armazenamento local do app (item 7.0): chave de API não deve ficar guardada remotamente, nem no banco do servidor — reverte a decisão original de item 4.3 ("banco tem precedência sobre variável de ambiente"). Depois da mudança, a única forma persistente de configurar a chave no servidor é a variável de ambiente do `.env` (via SSH no Raspberry Pi); toda chamada que envolve IA passa a aceitar um header opcional (`X-Chave-API-OpenRouter`) com prioridade sobre a variável de ambiente, nunca persistido em lugar nenhum do servidor. Bloqueia o app funcionar de ponta a ponta com chave própria até ser implementado — mas não bloqueia o uso pessoal do Allan, que continua usando a variável de ambiente.
- [x] ~~Refinar a engenharia do prompt de geração de imagens.~~ **Uma rodada implementada** (item 4.5/4.7): bloco de estética do prompt final separado e estruturado em vez de tecido em prosa; reforço contra linguagem temática residual na sugestão de perfil; `Elemento.imagem_ancora_padrao_id` para mitigar variação de consistência visual entre capítulos distantes e entre ferramentas de geração diferentes. Nenhuma das três mudanças de instrução foi validada com IA real ainda — vale rodar contra o corpus de validação antes de considerar madura. Novas rodadas de refinamento continuam abertas, a pedido de Allan.
- [ ] Relações entre elementos e Grupos com membros explícitos (v2, fora do escopo do MVP).
- [x] ~~Implementar sugestões persistidas (`SugestaoDeElemento`/`SugestaoDeCena`/`SugestaoDeParticipante`), busca por nome cross-capítulo e confirmação em lote.~~ Concluído — item 3.4e, validado com o caso real do "Sextus Hospius"/"Hospius".

### Pendências técnicas (achadas revisando a API, ainda sem decisão de implementar)

- [x] ~~Não existe `GET /estados/{id}`.~~ **Implementado** (item 6.3) — devolve o estado com o elemento a que pertence, mesmo padrão de `GET /frames/{id}`.
- [x] **Sugerir o perfil de renderização por IA.** ~~Hoje o usuário cria o perfil (estilo, iluminação, paleta) à mão~~ — implementado e validado com IA real: `POST /livros/{id}/perfis-renderizacao/sugestao` (item 6.5). Diverge do plano original: em vez de ler o texto do livro, manda só título/autor/idioma e deixa a IA reconhecer a obra (buscando na internet, se precisar) — decisão registrada na Etapa 5, com o motivo (não dá pra saber onde a narrativa realmente começa). As três decisões que faltavam para fechar o rascunho, todas fechadas: `POST /perfis-renderizacao` não ganha atalho de uma chamada só (mantidas as duas chamadas, sugerir e criar); `reconheceu_a_obra` sinaliza quando a IA não identifica o livro (implementado, ainda não testado com IA real); reforço contra linguagem temática residual implementado — ver item 6.5 para os detalhes.
- [x] ~~Mais filtros em `GET /configuracao/modelos`.~~ **Implementado** (item 4.3) — `supported_parameters`/`pricing.completion`/`top_provider.is_moderated` confirmados ao vivo contra o `/models` do OpenRouter (460 modelos, endpoint público sem chave). Novos campos `suporta_json`/`custo_saida`/`moderado` em cada modelo da resposta, e filtros `somente_com_json`/`somente_nao_moderados`/`ordenar_por_custo`.
- [x] ~~Não existe forma de corrigir só o casamento `elemento_id` de uma `SugestaoDeElemento`, sem criar um Estado junto.~~ **Implementado** (item 4.6/6.3) — nova rota `PATCH /sugestoes-elemento/{id}`, junto da rodada de identidade evolutiva e sinalização de casamento automático não revisado.
- [x] ~~`POST /capitulos/{id}/frames` com `sugestao_cena_id` não impede confirmar a mesma sugestão duas vezes.~~ **Implementado** (item 6.4) — responde 409 com o `frame_id` já existente, mesmo padrão usado para elemento duplicado (item 6.3). Cada chamada criava um Frame novo, mesmo com `SugestaoDeCena.frame_id` já preenchido; achado testando: três confirmações seguidas da mesma cena criaram três Frames, só o último referenciado, os outros dois órfãos. Vale só para `sugestao_cena_id` — `estados_ids` sem sugestão continua livre.
- [x] ~~`GET /livros/{id}/sugestoes-elemento` não diz se a sugestão já virou Estado.~~ **Implementado** (item 3.4e/6.3/6.7) — campo calculado `estado_id` (o Estado daquele elemento **neste** capítulo, ou `null`), exposto na busca cross-capítulo **e** na resposta de análise por capítulo (`POST /capitulos/{id}/sugestoes`), para a tela de Capítulo (7.5) sinalizar na hora. Achado com um caso real: sugestão do capítulo 5 de "Sextus Hospius" já estava casada com o elemento, mas só o Estado do capítulo 3 existia — congelado na primeira aparição até alguém notar manualmente.

### Pendência técnica — prioridade alta

- [x] ~~A identidade do Elemento (`Elemento.descricao`) não acompanha o que o livro revela sobre quem o personagem é, capítulo a capítulo — só a aparência (`EstadoElemento`) tem esse mecanismo.~~ **Implementado.** Achado com um caso real: nas sugestões de "Vis" nos capítulos 3, 4 e 5, o campo `descricao` (identidade, fase 1 do item 4.4) saiu **idêntico** nos três — a IA, corretamente instruída a não inventar identidade nova a cada chamada, só repetia o que já sabia, mas `Elemento.descricao` nunca era revisitado depois da confirmação inicial. Resolvido na especificação com a nova entidade `HistoricoIdentidadeElemento` (item 3.4f) e a fase 2b da leitura profunda (item 4.4): identidade passa a acumular por capítulo, do mesmo jeito que a aparência já evolui — mas somando registros em vez de sobrescrever, porque identidade (diferente de aparência) não deixa de valer entre capítulos. A mesma rodada de discussão também resolveu duas pendências vizinhas, registradas no item 4.6: confirmação de sugestão não é forçada nem por ordem de capítulo nem por "leitura antes de analisar", mas o casamento automático de participante ganha sinalização (`casamento_automatico`) e um jeito barato de corrigir (`PATCH /sugestoes-elemento/{id}`, pendência que estava na lista acima). **Implementado e testado** (migration `f3a7c9d1b2e4`, `sugerir_identidade`, as rotas e campos novos — 31 testes novos, ver item 4.6). Ainda falta validar contra o corpus de dezoito livros e contra IA real, como as demais operações desta camada.

**Revisado e confirmado correto** (perguntas do Allan sobre a API, 27/09/2026 — registrado para não reabrir a discussão sem motivo novo):

- `PATCH /livros/{id}` devolver `LivroDetalhe`, e não `LivroResumo`: é o padrão do projeto — toda rota de ajuste devolve a versão completa (`PATCH /capitulos`, `/elementos`, `/frames` fazem o mesmo). Mudar só a de livros quebraria a consistência sem ganho claro.
- `descricao` em `POST /livros/{id}/elementos` já é opcional (`str | None = None`) — confirmado com uma chamada real, sem o campo, sem erro.
- Livro duplicado já tem tratamento deliberado (item 3.4a): `identificador_epub` indexado mas não único, de propósito — muitos EPUBs convertidos/piratas repetem identificador genérico, e bloquear impediria importações legítimas. A rota avisa (`livros_semelhantes`), não impede.
- `estados_ids` "bastar" para criar uma cena, sem repetir título/descrição: já resolvido para cena **sugerida** (`sugestao_cena_id`, item 3.4e, preenche tudo sozinho). Para cena **inventada pelo usuário**, título/descrição continuam obrigatórios de propósito — é a conta do próprio usuário sobre quem/onde/o quê (Etapa 5), o sistema não pode inventar isso sem risco de divergir do livro.

### Pendência técnica — arquitetura do backend (achada em revisão de código, 29/09/2026)

Revisão de arquitetura (não é busca por bug específico) comparando o backend contra práticas usuais de projetos FastAPI/SQLAlchemy maduros. Nada aqui bloqueia o MVP — registrado como dívida técnica para uma rodada de refatoração futura, não pra corrigir agora.

- [ ] **Camada `servicos/` subutilizada em rotas complexas.** `rotas/elementos.py` (1104 linhas) e `rotas/frame.py` carregam lógica de negócio inteira em funções privadas (`_gerar_sugestoes`, `_casar_sugestoes_pendentes`, `_resolver_titulo`, `_resolver_estados_da_sugestao`, `_estados_do_livro`) em vez de em serviço puro — diferente do padrão já bem seguido por `estados_de_elemento.py`, `identidade_de_elemento.py`, `importacao_epub.py`, `upload.py` e `catalogo_imagens.py`. Consequência prática: essa lógica só é testada indiretamente via `TestClient` (rota), nunca isolada; e mistura orquestração HTTP com regra de negócio. Quando for mexer nessas rotas de novo, vale extrair pra serviço em vez de crescer mais a função privada.
- [ ] **Helpers de busca duplicados entre módulos de rota.** `_buscar_livro`, `_buscar_elemento`, `_buscar_frame`, `_buscar_capitulo` são reimplementados quase identicamente em `rotas/livros.py`, `rotas/elementos.py` e `rotas/frame.py` (mesmo padrão: busca por id, 404 se não achar). Um helper genérico (`get_or_404`) num módulo compartilhado eliminaria a repetição.
- [ ] **Sem exception handler global.** Todo erro é `HTTPException` lançada ad-hoc dentro da rota/função auxiliar — consistente entre rotas (404/422/409/502 usados do jeito certo), mas sem um `@app.exception_handler` centralizando o padrão. Não é um problema hoje, só fica mais visível se o número de rotas crescer.
- [ ] **`rotas/elementos.py` acumula 5 `APIRouter` diferentes no mesmo arquivo**, organizado por "recurso lógico" em vez de por rota REST — documentado no docstring do próprio arquivo, mas vale reconsiderar se o arquivo continuar crescendo.

**Pontos fortes confirmados na mesma revisão** (não é pendência, registrado pra não reabrir a dúvida): sessão de banco via `Depends`/`yield` correta, sem N+1 óbvio (usa agregação no banco); schemas Pydantic com `Field` de constraints reais, enums e separação `*Novo`/`*Ajuste`/`*Resumo`/`*Detalhe` consistente; migrações Alembic bem geridas (14, nomes descritivos, convenção de nomes de constraint definida desde o início); sem SQL injection, sem path traversal no upload (nomes de arquivo via `uuid4`), sem segredo vazando em log; ~7100 linhas de teste com boa cobertura de rota e um provedor de IA falso (`ia/falso.py`) pra testar sem custo real.

### Análise de mercado e diferenciação (29/09/2026)

Avaliação em quatro partes, não só contra esta especificação: arquitetura de código (seção acima), modelagem de domínio vs. ferramentas de mercado, UX do app mobile vs. padrões de mercado, e síntese de onde o Imagineer pode se diferenciar. Comparado contra World Anvil, Campfire, Plottr (worldbuilding/planejamento), Sudowrite Story Bible e NovelAI Lorebook (assistentes de escrita com memória de personagem), e getimg.ai/Midjourney `--cref` (consistência visual de personagem em geração de imagem).

**Diferenciais reais identificados** (nenhum concorrente pesquisado cobre isso):

1. **Personagem como algo que evolui no tempo, não uma ficha fixa.** Sudowrite, NovelAI, World Anvil e Campfire tratam personagem como card estático, atualizado manualmente quando o autor lembra. O par `EstadoElemento`/`HistoricoIdentidadeElemento` (itens 3.4b/3.4f) é a única modelagem encontrada que acompanha "como ele estava *neste* capítulo" de forma estrutural — não é um recurso a mais, é uma categoria de dado que o mercado pesquisado não tem.
2. **Ponto de partida invertido: livro pronto, não mundo em construção.** Toda ferramenta pesquisada assume que o autor constrói o mundo enquanto escreve. O Imagineer assume um texto já terminado (do usuário ou de terceiro) e extrai o canon dele, capítulo a capítulo, via IA — categoria de produto ("ferramenta de leitura/adaptação" em vez de "ferramenta de planejamento") que não apareceu em nenhuma busca.
3. **Referência visual amarrada a um momento da história, não ao personagem inteiro.** `--cref` (Midjourney) e "Elements" (getimg.ai) fixam uma imagem de referência pra sempre. `Elemento.imagem_ancora_padrao_id` (item 4.5) já é o embrião de algo que nenhum concorrente oferece: âncora por Estado em vez de por Elemento — gerar "no estilo de como ele estava no capítulo 12" automaticamente. Ainda não implementado dessa forma, só registrado como direção possível.
4. **Mobile-nativo de ponta a ponta.** Campfire e Sudowrite têm app de celular, mas como companion — a criação pesada continua no desktop/web. O Imagineer não tem essa muleta (item 7.0): toda a criação/edição é pensada pro celular desde o início.

**Riscos que podem anular esses diferenciais se não forem tratados:**
- Falta de busca nas listas (ver pendência de prioridade acima) — sem isso, "acompanhar muitos elementos ao longo de muitos capítulos" vira o próprio motivo do app ser difícil de usar, antes de qualquer diferencial importar.
- A dívida de arquitetura do backend (seção acima) trava a velocidade de evoluir justamente o diferencial nº 3 (âncora por Estado exige mexer bastante no código de frame/prompt).
- O loop de copiar/colar pra ferramenta externa na tela de Prompt (item 7.7) é o único ponto do fluxo principal onde o usuário sai do app — nenhuma ferramenta de consistência visual do mercado pesquisado exige isso. Decisão de escopo já conhecida e aceita, não uma lacuna a corrigir agora, mas é o maior ponto de fricção do fluxo core caso o escopo mude no futuro.

**Posicionamento sugerido** (orientação estratégica, não requisito): o Imagineer não compete direto com World Anvil/Campfire (planejamento) nem com Sudowrite/NovelAI (assistente de escrita). O ângulo que nenhuma ferramenta pesquisada ocupa é "peguei um livro pronto e quero visualizar as cenas dele sem perder a linha do tempo de como tudo mudou" — hoje resolvido manualmente com planilha ou board de referências, sem ferramenta dedicada.
