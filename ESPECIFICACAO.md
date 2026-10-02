# Imagineer — Especificação do Sistema

## Sobre este documento

Este documento reúne as definições de arquitetura, modelagem de dados e fluxo do sistema Imagineer. Ele é um **documento vivo**: conforme cada item for implementado, a seção correspondente deve ser atualizada com uma explicação, em linguagem simples, do que foi feito e por quê — não apenas o plano original, mas o resultado real.

A estrutura segue o padrão **Etapa → Item**. Cada etapa representa uma fase lógica do sistema; cada item dentro dela é uma decisão ou funcionalidade específica que pode ser especificada, documentada, implementada e testada de forma independente.

**Idioma do sistema**: todo o sistema — nomes de entidades, campos, classes, endpoints, mensagens de log, textos de interface — é em português. Termos técnicos já naturalizados no vocabulário de desenvolvimento em português (ex: *prompt*, *backend*, *endpoint*, *deploy*, *docker*) são mantidos como estão, por não terem equivalente melhor e já serem de uso corrente. Assumindo essa interpretação (código e nomes de domínio em português, termos técnicos genéricos mantidos); ajuste se a intenção era outra.

---

## Etapa 1 — Visão Geral e Arquitetura

### 1.1 Objetivo do projeto

Sistema pessoal (não comercial) chamado **Imagineer**, que gera prompts de imagem a partir da leitura de e-books (EPUB), pensado para pessoas com afantasia (dificuldade de visualizar mentalmente cenas, personagens e ambientes durante a leitura).

**Mudança de visão (01/10/2026):** o projeto nasceu pensado só como gerador de prompts/imagens, assumindo que a leitura em si acontecia em outro app (Kindle, papel, etc.) e o EPUB era importado só como fonte de texto pra IA processar. A visão evoluiu: o Imagineer passa a mirar ser um **leitor de EPUB completo**, com a geração de imagens como uma camada em cima da leitura — tudo acontecendo dentro do próprio app, sem precisar de outro leitor em paralelo. Isso amplia o que "MVP completo" significa (a seção Escopo deste documento, no `CLAUDE.md`, ainda reflete o escopo original: Elemento + EstadoElemento + Frame + Prompt + Imagem). O levantamento comparativo contra leitores de EPUB de mercado (Kindle, Moon+ Reader, ReadEra, Apple Books, Libby, FBReader), com as lacunas identificadas e perguntas em aberto por funcionalidade, está em `EXPERIENCIA_DE_LEITURA.md` — documento de pesquisa, não especificação fechada; cada item dali só vira parte desta especificação quando for de fato discutido e decidido.

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
| `situacao_da_geracao` | texto (20) | não | `NAO_TENTADO` (padrão), `RECUSADO` ou `COM_SUCESSO`: o resultado da **última tentativa de gerar a imagem no app** (incremento 12). `NAO_TENTADO` também vale para o prompt que só foi copiado para outra ferramenta |
| `motivo_da_recusa` | texto longo | sim | a mensagem do provedor de imagem quando `RECUSADO`; nulo nos outros casos |
| `prompt_original_id` | inteiro | sim | no prompt **suavizado**, o prompt de onde ele saiu (S5); nulo no resto. `ON DELETE SET NULL`: apagar o original não apaga o suavizado |
| `data_criacao` | data/hora com fuso | não | preenchido pelo banco |

`perfil_renderizacao_id` guarda o perfil **usado naquela geração**, que pode ser o padrão do livro ou um override pontual. Aceita nulo, e apagar um perfil não apaga prompts (`ON DELETE SET NULL`): o histórico de prompts é mais valioso que a referência ao perfil, e perder um registro de prompt por causa de uma limpeza de perfis seria um prejuízo desproporcional.

`avaliacao` é a interpretação do campo "resultado" citado no item 3.1: um texto livre onde você anota como a imagem ficou ("acertou o rosto, errou a armadura"). É o que dá sentido a "comparar modelos depois" — sem a anotação, comparar exigiria reabrir as imagens e lembrar o que achou de cada uma.

**Situação da geração e suavização (S5, incremento 12).** `situacao_da_geracao` registra o que o provedor de imagem respondeu: `COM_SUCESSO` (gerou), `RECUSADO` (recusou o conteúdo) ou `NAO_TENTADO` (nunca foi enviado). Quando um prompt é recusado e o sistema o suaviza, o suavizado é um **prompt novo** (com o seu próprio texto e a sua própria situação) ligado ao original por `prompt_original_id`; **o original nunca é sobrescrito**. As três colunas aparecem em `GET /frames/{id}/prompts` e `GET /prompts/{id}`; são só de leitura por enquanto (quem as muda é a geração de imagem, próxima fatia).

**Implementado (02/10/2026): as três colunas** (migração `b8c0d2e4f6a8`, testada em Postgres: sobe, desce e sobe de novo; `alembic check` não vê diferença entre o modelo e o banco; os 11 prompts que já existiam ficaram `NAO_TENTADO`). `PromptResumo` e `PromptDetalhe` ganharam `situacao_da_geracao`, `motivo_da_recusa` e `prompt_original_id`. Nada ainda muda esses valores: quem os preenche é a geração de imagem (próxima fatia). 3 testes novos (551 no total): o prompt novo nasce `NAO_TENTADO`; a listagem e o detalhe trazem os três campos, com o suavizado ligado ao original; apagar o original não apaga o suavizado (`SET NULL`). **Para o app:** os três campos são **novos** na resposta; o app atual ignora campos desconhecidos, então nada quebra.

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
| `modelo_extracao` | texto (200) | sim | modelo usado no passo 6 do fluxo |
| `modelo_prompt` | texto (200) | sim | modelo usado no passo 8 |
| `modelo_perfil` | texto (200) | sim | modelo usado em `POST /livros/{id}/perfis-renderizacao/sugestao` (item 6.5) — campo próprio porque essa chamada é única por livro, não por capítulo, e compensa um modelo mais caro |
| `modelo_imagem` | texto (200) | não | **o modelo que gera a imagem** a partir do prompt (item 4.1, incremento 12). **Padrão `meta/muse-image`**, dado como valor inicial na migração, para a linha que já existe também nascer com ele. Só o OpenRouter, pelo `POST /api/v1/images` (não o `chat/completions`) |
| `modelo_suavizacao` | texto (200) | sim | modelo de **texto** que reescreve um prompt recusado pelo provedor de imagem (S6, incremento 12). **Vazio = usa o `modelo_prompt`**. Campo próprio porque é uma chamada curta e barata, que pode usar um modelo menor |

**Implementado (02/10/2026): `modelo_imagem` e `modelo_suavizacao`** (migração `a7b9c1d3e5f7`, testada em Postgres: sobe, desce e sobe de novo; a linha que já existia recebeu `meta/muse-image`). `GET /configuracao` devolve os dois campos; `PUT /configuracao` os aceita. **`modelo_imagem` vazio, em branco ou nulo responde 422** ("O modelo de imagem não pode ficar vazio.") e mantém o valor; `modelo_suavizacao` vazio volta a "usa o `modelo_prompt`". Nada chama esses modelos ainda: servem à geração de imagem (próxima fatia). 5 testes novos (548 no total). **Para o app:** os dois campos são **novos** na resposta; o app atual ignora campos desconhecidos, então nada quebra.

**Uma linha só, com `id` fixo em 1.** Não é a modelagem mais elegante, mas é a mais honesta para o que é: não existem "duas configurações" num sistema pessoal de um usuário. A alternativa — uma tabela de pares chave/valor — perderia a tipagem de cada campo e ganharia só flexibilidade que não vai ser usada. Uma restrição `CHECK (id = 1)` impede uma segunda linha aparecer por acidente.

Os campos de modelo aceitam nulo porque o sistema precisa subir sem configuração nenhuma: os modelos podem ainda não ter sido escolhidos.

> **Divergência registrada (item 4.3):** a primeira versão desta tabela tinha a coluna `chave_api_openrouter`, cadastrada pelo app. Foi **removida** (migration `c5d8e2f4a6b1`): chave de API não fica guardada no banco do servidor. A chave do servidor vem só da variável de ambiente; a de cada usuário vem por header, a cada chamada.

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

#### (g) Posição no texto das sugestões e dos frames — especificado, ainda não implementado

Para o app mostrar cada sugestão e cada ilustração **no ponto do capítulo a que pertence** (item 7.5b), a API precisa saber *onde* ela fica. Hoje nada guarda isso: o `Frame.descricao` é texto livre e as sugestões só têm nome e descrição.

**Colunas novas em `SugestaoDeElemento` e `SugestaoDeCena`:**

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `trecho_ancora` | texto (300) | sim | uma **citação literal e curta** do capítulo, devolvida pela IA junto com a sugestão (item 4.4, fase 1): para o elemento, a **primeira menção nesse capítulo**; para a cena, o **começo do momento** que ela descreve |
| `posicao_no_texto` | inteiro | sim | o deslocamento, em caracteres, desde o início de `Capitulo.texto`, onde a citação foi encontrada. **Calculado pelo servidor**, nunca pela IA. Nulo = não foi encontrada |

**Coluna nova em `Frame`:** `posicao_no_texto` (inteiro, nulo). **Revisado em 01/10/2026: só guarda o que o usuário escolheu** ("Ilustrar aqui"); o frame **não herda** a posição da sugestão, porque o artefato já cai para ela quando o frame não tem a sua (ver o incremento 11, terceira fatia). *Texto original do plano:* vem da sugestão quando o frame nasce de uma (`sugestao_cena_id`); num retrato, vem da sugestão do elemento **naquele capítulo**, se existir; e pode ser dada ou corrigida à mão pelo usuário ("Ilustrar aqui", item 7.5b). Sem valor, o frame continua funcionando e aparece na faixa "sem posição" do capítulo.

**Por que a IA devolve uma citação e não um número.** Modelos de linguagem contam caracteres mal: um deslocamento pedido direto viria errado com frequência. Citar um trecho do texto que eles acabaram de ler é bem mais confiável, e o servidor, que tem o texto inteiro, transforma a citação em número.

**Como o servidor localiza a posição — a ordem depende do tipo** (revisada em 30/09/2026, depois da medição com IA real abaixo):
- **Elemento: primeiro pelo nome, depois pela citação.** (1) busca **exata** do próprio nome no texto do capítulo — a primeira ocorrência é, por construção, a "primeira menção" que o artefato quer; (2) a mesma busca **normalizada**; (3) se o nome não aparece, a **citação** da IA: exata, normalizada e pelas primeiras palavras.
- **Cena: só pela citação** (não há nome a buscar): (1) exata; (2) normalizada; (3) pelas primeiras palavras.
- Se nada achar, `posicao_no_texto` fica nulo. A posição aponta para o **início do parágrafo** que contém o trecho, porque o app desenha ilustrações entre parágrafos.
- **Normalizar muda o tamanho do texto** (tirar acento, unificar aspas, juntar quebras de linha em espaço), então a busca normalizada **precisa guardar, para cada caractere normalizado, a posição do original de onde ele veio**. Sem esse mapa, uma citação achada no texto normalizado apontaria para o lugar errado do texto real. Isso vale para nome e para citação.

**Por que caractere e não número do parágrafo.** A regra que separa parágrafos mora no app (`dividirEmParagrafos`); se ela mudasse, as imagens andariam de lugar. O deslocamento não depende dessa regra, e o texto do capítulo não muda depois da importação (`PATCH /capitulos` só altera título e `ignorado`).

**Unidade do deslocamento: unidades UTF-16, não caracteres Unicode.** O servidor (Python) conta por caractere Unicode (*code point*), e o app (Kotlin) por unidade UTF-16; um emoji ou símbolo fora do plano básico conta 1 no primeiro e 2 no segundo, e tudo depois dele divergiria. O contrato é **UTF-16**, a contagem de quem consome o número, e o servidor converte ao gravar. Medido no corpus de validação (1124 capítulos): **nenhum** tem caractere fora do plano básico, então hoje a diferença não aparece — mas o contrato precisa dizer, porque o primeiro livro com um emoji a faria aparecer.

**Imagem mostrada no texto: a mais recente.** Um frame pode ter vários prompts e cada prompt várias imagens (item 3.4c). No texto aparece a imagem importada **mais recentemente** entre todas as do frame. Um campo "imagem principal" escolhida pelo usuário (`Frame.imagem_principal_id`) foi cogitado e **adiado**: só vale a pena se a escolha automática incomodar na prática.

**Validado com IA real em 30/09/2026 — o que a medição mostrou.** Experimento isolado (não grava nada no banco): 12 capítulos de 4 livros (*A Música do Silêncio*, *O Alienista*, *Perdido em Marte*, *Mistborn*), 2 modelos, 120 sugestões por modelo; o prompt foi um **de teste**, não o de produção. Custo: US$ 0,01 (`openai/gpt-4o-mini`) e US$ 0,11 (`anthropic/claude-haiku-4.5`).

| | gpt-4o-mini | claude-haiku-4.5 |
|---|---|---|
| Cena: posição achada pela citação | 100% | 100% |
| Elemento: posição achada pela citação | 99% | 89% |
| Citação literal exata (etapa 1) | 93–96% | 82–92% |
| Elemento: a citação é a **primeira menção** do nome (mesmo parágrafo) | **64%** | **76%** |
| Elemento: busca pelo **nome** acha a posição | ~97% | — |

- **A ideia central está validada:** a IA copia o trecho quase sempre de forma literal, e o servidor converte em posição; as etapas de tolerância (sem acento, aspas tipográficas) serviram de rede de segurança. O `claude-haiku-4.5` devolveu `null` em 8 de 72 elementos, obedecendo à instrução "na dúvida, null", e a busca pelo nome resgatou 7.
- **O que mudou no desenho:** para elementos, a citação **nem sempre é a primeira menção** (em 24 a 36% dos casos ela cai em outro parágrafo), enquanto a busca pelo nome acha o elemento em ~97% e é, por construção, a primeira ocorrência. Por isso a ordem acima: **nome primeiro para elementos, citação só como reserva**; para cenas, citação. Com isso a instrução de `trecho_ancora` para elementos deixa de ser o caminho principal.
- **Ressalvas:** amostra pequena (só português e inglês); prompt de teste; o critério "mesmo parágrafo" é uma aproximação (o nome completo pode aparecer mais tarde que uma menção por epíteto, como "o Sapador"); e mede se o **servidor acha** a posição, não se ela é a que o usuário esperaria ver. **Reavaliar** com o prompt de produção quando a fase 1 for alterada.
- **Plano B mantido:** posição nula continua válida, e a sugestão continua valendo sem artefato.

**Medido de novo em 01/10/2026, com o prompt de PRODUÇÃO (cenas).** Mesmos 12 capítulos dos 4 livros e os mesmos 2 modelos, agora pela rota real do provedor (`extrair_elementos`, com a instrução de `trecho_ancora` que vai para o servidor) e `posicao_da_citacao` (exata → normalizada → só o começo, de 6 a 3 palavras). Script: `scripts/medir_citacao_de_cena.py` (rodar de novo sempre que o prompt de extração mudar). Cada chamada foi gravada em `usos_ia`.

| | gpt-4o-mini | claude-haiku-4.5 |
|---|---|---|
| Cenas sugeridas (12 capítulos) | 50 | 107 |
| A IA citou (`trecho_ancora` não nulo) | 100% | 100% |
| Citação literal no texto (etapa 1) | 86% | 90% |
| **Posição achada pelo servidor** | **98%** | **100%** |
| Participante da cena perto da posição achada (verificação de bom senso) | 88% | 94% |
| Tamanho médio da citação | 65 caracteres | 102 caracteres |
| Custo da rodada | **US$ 0,017** | **US$ 0,298** |

- **A posição de cena está validada com o prompt de produção:** 98% a 100% das citações viram posição, igual ou melhor que a medição de 30/09 (que usou um prompt de teste). O desenho (citação da IA + conversão no servidor, com as tolerâncias) se sustenta.
- **"Achada" não é "certa".** O teste de participante perto mede se a posição cai onde alguém da cena aparece (nas 2.500 letras seguintes): 88% e 94%. Os 6% a 12% restantes não são necessariamente erro (a cena pode começar antes de citar o nome pelo apelido), mas é a medida mais próxima de "o ícone está no lugar certo" que dá para ter sem olhar uma a uma. A conferência visual no tablet continua sendo o teste final.
- **Custo:** o haiku custou **cerca de 18 vezes mais** que o gpt-4o-mini na mesma tarefa (US$ 0,0248 contra US$ 0,0014 por capítulo, em média) e sugeriu o **dobro de cenas** (107 contra 50) — mais caro e mais prolixo, sem ganho que justifique na posição (98% contra 100%). Para analisar capítulos, o `gpt-4o-mini` segue sendo a escolha econômica.
- **Uma chamada do haiku falhou** (`Server disconnected without sending a response`, 1 de 12), o tipo de erro de rede que a rota já traduz em 502 e que se resolve tentando de novo.
- **Ressalva:** a mesma amostra pequena (4 livros, português e inglês); capítulos escolhidos por tamanho (6 mil a 45 mil caracteres), não aleatórios.

#### (h) Marcador e Pin — onde o leitor parou (implementado no servidor em 01/10/2026; defeito D4)

Duas entidades novas, **por livro**. O vocabulário é decisão do Allan: **marcador** = a posição de leitura **automática** (retomar de onde parou); **pin** = a posição marcada **à mão**, com nota opcional. Ambos ficam **no servidor**, para valer em qualquer aparelho, e viajam no "baixar livro" (item 6.9).

**`Marcador`** (tabela `marcadores`) — **um por livro**:

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | |
| `livro_id` | inteiro, FK → `livros` (apagar em cascata) | não | **único**: só existe um marcador por livro |
| `capitulo_id` | inteiro, FK → `capitulos` (apagar em cascata) | não | o capítulo onde a pessoa parou |
| `posicao_no_texto` | inteiro | não | deslocamento em **UTF-16** desde o início de `Capitulo.texto` — o **mesmo contrato do item 3.4g**, para não depender de como o app divide parágrafos. O app grava o início do parágrafo que está no topo da tela |
| `lido_em` | data/hora com fuso | não | **quando a pessoa chegou ali**, segundo o aparelho (e não quando o servidor recebeu). É o que resolve o conflito entre aparelhos (abaixo) |

**`Pin`** (tabela `pins`) — **vários por livro**:

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | |
| `livro_id` | inteiro, FK → `livros` (apagar em cascata) | não | |
| `capitulo_id` | inteiro, FK → `capitulos` (apagar em cascata) | não | |
| `posicao_no_texto` | inteiro | não | UTF-16, como acima |
| `nota` | texto (1000) | sim | uma anotação curta do usuário; nulo = pin sem nota |
| `criado_em` | data/hora com fuso | não | preenchido pelo banco (`NOW()`) |

**Conflito entre dois aparelhos (decisão tomada com recomendação; fácil de rever).** O **marcador mais recente vence**, medido por `lido_em`, **não** pela hora em que a gravação chegou: um aparelho que ficou offline e só sincroniza horas depois **não** passa por cima de uma leitura mais nova feita em outro. O `PUT` aceita o valor se o `lido_em` dele for **igual ou mais novo** que o guardado, e **sempre devolve o marcador que ficou valendo** com `aceito: true/false` — assim o app que perdeu sabe que "outro aparelho leu mais recentemente" e pode oferecer continuar de lá. `lido_em` no futuro (relógio adiantado) é **limitado ao horário do servidor**, para um aparelho com relógio errado não travar o marcador. Não há identificação de aparelho (contas de usuário estão adiadas, item 7.0a). **Pins** não têm conflito: são linhas independentes; editar a nota do mesmo pin em dois aparelhos é "o último a gravar vence".

**Marcador e pin NÃO sobem a `revisao` do livro (item 6.9) — de propósito.** A `revisao` diz "o que o leitor mostra da lista do livro mudou, releia". O marcador é gravado **a cada pouco de leitura**; se subisse a revisão, o app reler a lista do livro o tempo todo e o cache (A8) não serviria para nada. É a mesma lógica das duas exceções já documentadas em `banco/revisao.py`. O app lê o marcador e os pins **por rotas próprias** (item 6.10).

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

- `suavizar_prompt(texto, modelo) -> texto do prompt` — **implementado (02/10/2026, S6)**: reescreve um prompt que o provedor de imagem recusou, trocando o explícito pelo sugerido (item 6.6, "Gerar a imagem").
- `gerar_imagem(prompt, modelo) -> imagem` — **implementado (02/10/2026)**: gera a imagem pelo `POST /api/v1/images` do OpenRouter e devolve os bytes. Levanta `ConteudoRecusado` (filha de `ErroDoProvedorIA`) quando o provedor recusa o conteúdo (S4).

Implementação concreta inicial: `ProvedorOpenRouter`, parametrizada por `id_modelo`. Os quatro métodos devolvem objetos tipados, não texto cru, para que a rota não tenha que adivinhar o formato da resposta. Provedores nativos adicionais (Groq, Gemini) podem ser adicionados depois seguindo a mesma interface, se necessário.

> **Divergência registrada (item 1.5):** a primeira versão desta seção nomeava a interface como `AIProvider`, a implementação como `OpenRouterProvider` e o parâmetro como `render_profile`. Os nomes foram traduzidos para `ProvedorIA`, `ProvedorOpenRouter` e `perfil_renderizacao` por coerência com a regra de idioma: existe tradução natural, então o português prevalece. Definido antes de a pasta `ia/` ser preenchida, para não renomear código depois.

> **Divergência registrada, pós-validação com IA real (itens 4.4 e 6.6):** a versão original de `extrair_elementos` devolvia, numa passada só, tanto a identificação de cada elemento quanto uma descrição livre de aparência (`estado_sugerido`) e um veredito de continuidade (`manter_estado_atual`). Testado com `openai/gpt-4o-mini` num capítulo real de *A Vontade de Muitos*, esse desenho misturou atributos entre personagens (atribuiu o "joelho machucado" de um coadjuvante ao protagonista) — o modelo estava tentando descrever a aparência de nove elementos ao mesmo tempo na mesma resposta. Um teste com `google/gemini-2.5-flash` no mesmo capítulo, embora tenha corrigido esses erros, **inventou um elemento que não existe no texto** ("carroça de suprimentos"). O desenho passou a separar identificação (barata, ampla, sem descrição de aparência) de leitura profunda (focada, um elemento por vez, sempre lendo o capítulo de origem do estado) — ver item 4.4.

### 4.3 Configuração de modelos

Tela de configuração permitindo:
- Chave da API do OpenRouter, nunca hardcoded e **nunca guardada no banco** (ver "De onde vem a chave" abaixo).
- Seleção de modelo para extração de elementos (passo 6) e para montagem de prompt (passo 8), com opção "usar o mesmo modelo para os dois" marcada por padrão.
- Lista de modelos obtida dinamicamente do endpoint `/models` do OpenRouter (com filtro opcional para mostrar só os gratuitos, e mais três sinais — item 4.3, "Mais filtros" abaixo, implementado).
- **Prioridade de IA** (`prioridade_ia`): `ECONOMIA` (padrão) ou `QUALIDADE` — controla se a leitura profunda do item 4.4 relê o capítulo toda vez que um prompt é montado, ou só da primeira vez por estado. Ver item 4.4 para o efeito exato. É um campo pensado para valer também em futuras decisões de custo-vs-qualidade no sistema, não só nesta.

#### De onde vem a chave

**De um header por chamada, ou da variável de ambiente do servidor — e o header tem precedência.** O banco **nunca** guarda a chave.

1. **Header `X-Chave-API-OpenRouter`** — a chave pessoal de quem está usando o app, guardada só no celular (item 7.0). Vale só para aquela chamada: o servidor a repassa ao OpenRouter e a esquece. Não é gravada em banco, em cache nem em log.
2. **Variável de ambiente `CHAVE_API_OPENROUTER`** (ou `IMAGINEER_KEY_OPEN_ROUTER`, ver Etapa 5) — a chave do próprio servidor, definida no `.env` (via SSH no Raspberry Pi). É o que o uso pessoal do Allan continua usando, sem mudar nada.
3. Nenhuma das duas: as rotas que chamam IA respondem o erro "não há chave configurada".

**Regras do header:**
- Vale em toda rota que passa pela dependência `obter_provedor` (sugestões, prompts, sugestão de perfil, lista de modelos). Rotas que não usam IA o ignoram.
- Header ausente, vazio ou só com espaços = ausente: cai para a variável de ambiente. (Um app que manda o header sempre, mesmo sem chave própria, não quebra.)
- Nunca aparece em resposta nem em mensagem de erro.

**`PUT /configuracao` deixa de aceitar `chave_api_openrouter`.** O campo saiu do schema e o corpo passa a recusar campos desconhecidos: mandar `chave_api_openrouter` devolve **422**, em vez de responder 200 sem gravar e deixar o usuário achar que a chave foi salva.

**`GET /configuracao` nunca devolve a chave**, só informa o que o **servidor** tem: `tem_chave_api` e `origem_da_chave`, que agora é `"ambiente"` ou `"ausente"` (o valor `"banco"` deixou de existir). Não considera o header — quem tem chave própria já sabe, ela está no celular dele. Uma chave que sai do servidor é uma chave que vaza em log, em cache de app ou numa captura de tela.

**Por que mudou** (reverte a decisão original, "o banco tem precedência"): o cadastro pelo app fazia sentido para o Allan sozinho — trocar de chave sem SSH no Raspberry Pi —, mas guardar a chave de qualquer usuário no banco do servidor não escala para mais de uma pessoa usando o mesmo backend. Cada um controla a própria chave, só no próprio celular. O custo: quem quiser trocar a chave **do servidor** volta a precisar de SSH e reinício do container — aceitável, porque é uma troca rara.

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

#### Custo das chamadas de IA (especificado e implementado em 01/10/2026; item M3 da Etapa 8)

**Pedido do Allan:** guardar o custo de cada solicitação à IA, para usar como métrica no futuro. O OpenRouter devolve, em cada resposta, o bloco `usage` com os tokens e o **custo em dólares** (`cost`); o servidor passa a gravar isso.

**Tabela nova `usos_ia` (`UsoDeIA`, migration `b2d4f6a8c0e1`), uma linha por chamada bem-sucedida:**

| Coluna | Tipo | Nulo? | Observação |
|---|---|---|---|
| `id` | inteiro | não | |
| `criado_em` | data/hora | não | preenchido pelo banco (`NOW()`), como `Imagem.data_importacao` |
| `operacao` | texto (40) | não | qual passo do fluxo chamou: `extracao`, `estado`, `identidade`, `fundamentacao`, `prompt` ou `perfil` |
| `modelo` | texto (200) | não | o modelo usado, como escolhido na configuração |
| `tokens_entrada` / `tokens_saida` | inteiro | sim | `usage.prompt_tokens` / `usage.completion_tokens` |
| `custo` | decimal (12, 8) | sim | `usage.cost`, em dólares. **Nulo = o OpenRouter não informou** (acontece com modelos gratuitos ou chave própria do provedor) — nunca zero inventado |
| `id_da_geracao` | texto (100) | sim | o `id` da resposta; permite conferir a cobrança no painel do OpenRouter |

**Como funciona.** `ProvedorOpenRouter` aceita um `ao_usar` opcional (uma função); depois de cada chamada de conversa bem-sucedida, lê o `usage` da resposta e a chama com um `UsoDeIA` (`ia/provedor.py`). Quem monta o provedor (`construir_provedor`, via a dependência `obter_provedor`) passa uma função que **grava a linha numa sessão própria, com commit imediato** (`servicos/uso_de_ia.py`). Duas decisões, e o porquê:
- **Sessão própria, e não a da rota.** A rota pode falhar depois da chamada (um 422, um erro ao gravar as sugestões) e desfazer a transação dela; mas a chamada **já foi cobrada**. Gravar à parte mantém o registro fiel ao que foi gasto.
- **Gravar nunca derruba a chamada.** Se o banco falhar ao registrar o uso, o erro vai para o log e a resposta da IA segue normalmente: perder uma linha de métrica é melhor do que perder um capítulo analisado que já custou dinheiro.
- A camada `ia/` continua sem conhecer o banco: ela só avisa quem a chamou.

**O que fica de fora por ora (YAGNI):** nenhuma rota de leitura (as métricas são "para o futuro"; consulta-se o banco direto); nenhum vínculo com livro ou capítulo (o provedor não sabe em que livro está; se a métrica por livro fizer falta, acrescenta-se uma coluna depois, com o contexto da rota); só chamadas de **conversa** (a listagem de modelos é gratuita e pública); chamadas que **falham** não gravam (não há cobrança confirmada).

### 4.4 Regra de decisão de novo Estado

A extração é **semi-automática**: a IA sugere, o usuário confirma. Isso evita depender de uma regra algorítmica perfeita para decidir sozinha se um capítulo representa mudança de estado. Depois de testar com IA real (ver a divergência registrada no item 4.2), o processo virou **duas fases**, para o texto do livro — e não um resumo apressado de vários elementos numa resposta só — ser sempre a fonte da descrição de aparência que chega ao prompt de imagem.

#### Fase 1 — Identificação (passo 6)

`POST /capitulos/{id}/sugestoes` continua chamando `extrair_elementos` com o texto do capítulo inteiro e o último estado conhecido de cada elemento já cadastrado. Devolve, para cada elemento encontrado: `tipo`, `nome`, `descricao` (identidade — quem ou o que é, não muda) e `manter_estado_atual` (um julgamento leve, comparando com o contexto de estados conhecidos). **Não devolve mais uma descrição de aparência** (`estado_sugerido` foi removido) — é exatamente essa parte que, tentando descrever vários elementos ao mesmo tempo, misturou atributos entre personagens num teste real.

O usuário revisa a lista (passo 7): confirma, ajusta ou descarta cada elemento, e cadastra o `Elemento` com um primeiro `EstadoElemento` — a descrição desse primeiro estado pode ser digitada à mão, ou ficar vaga/curta por enquanto, porque a fase 2 é quem vai efetivamente derivá-la do livro antes de qualquer prompt ser montado.

**A mesma chamada também sugere cenas.** Revisão feita a partir de um teste real seu: a extração original só listava elementos soltos ("quem existe no capítulo"), sem indicar quais combinações formam um momento que vale a pena ilustrar — e um jogo de tabuleiro saiu classificado como `AMBIENTE`, uma porta como `VEICULO`. Dois ajustes:

- `extrair_elementos` devolve, além de `elementos`, uma lista `cenas`: recortes narrativos específicos do tipo `CENA` (título, descrição, horário/clima/humor quando o texto sustenta, e os participantes — por nome, casados contra os elementos já cadastrados do mesmo jeito que a lista de elementos já fazia). É rascunho, não grava nada — o usuário usa isso para pré-preencher `POST /capitulos/{id}/frames` em vez de montar cada cena do zero. Uma cena sugerida sem nenhum participante é descartada (mesma tolerância a entrada malformada do item 4.2).
- A instrução ganhou definições explícitas de cada `tipo` (o que distingue `OBJETO` de `VEICULO`, `AMBIENTE` de `EDIFICACAO`) e um filtro de relevância para objetos — só inclui um objeto com peso visual memorável na cena, não papelada ou móvel genérico de fundo.

Testado com `gpt-4o-mini` no capítulo I de *A Vontade de Muitos*: da segunda vez, o tabuleiro saiu corretamente como `OBJETO`, e a extração sugeriu cinco cenas cobrindo os momentos certos do capítulo (o resgate na rocha, a partida de tabuleiro, a chegada de Hospius, o interrogatório de Nateo, o contato acidental com o Sapador) — nenhuma delas precisou ser inventada pelo usuário.

**Citação de âncora na fase 1 — especificado, ainda não implementado (item 3.4g).** `extrair_elementos` passa a pedir, para cada elemento e cada cena sugerida, o campo `trecho_ancora`: uma citação **literal**, de poucas palavras (em torno de 80 caracteres), copiada do capítulo — a primeira menção do elemento nesse capítulo, ou o começo do momento da cena. A instrução proíbe parafrasear, resumir ou traduzir a citação, e diz que, na dúvida, é melhor devolver nulo do que inventar. O servidor converte a citação em `posicao_no_texto`. Sem citação, ou com citação não encontrada, a sugestão continua valendo — só não ganha artefato no texto.

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
| Chave do OpenRouter sai do banco: só variável de ambiente no servidor, ou header `X-Chave-API-OpenRouter` por chamada (item 4.3) | Revertida a decisão original ("banco tem precedência"). Guardar a chave de cada usuário no banco do servidor não escala para mais de uma pessoa no mesmo backend, e a chave num backup de banco é um vazamento esperando acontecer. O header vale por chamada e nunca é persistido; a coluna foi removida por migration, sem deixar dado morto. `PUT /configuracao` recusa o campo antigo com 422 em vez de ignorá-lo em silêncio, para ninguém achar que salvou. Descartado: manter a coluna sem uso (chave esquecida em backup); aceitar header vazio como erro 400 (quebraria app que manda o header sempre). Custo aceito: trocar a chave **do servidor** volta a exigir SSH |
| Ícones do Material: dependência `material-icons-extended`, e não só o `core` (app Android, incremento 6) | O conjunto básico não tem "arquivar" nem "restaurar", que o Allan pediu como botões de um toque (pasta com seta). Antes o `extended` tinha sido evitado "por um só desenho"; agora são dois já, e os blocos C, D e E (imagens, copiar prompt, catálogo) vão precisar de mais. Descartado: desenhar `ImageVector` à mão — risco de um caminho errado e trabalho a refazer para cada ícone novo. Custo aceito: o APK de debug fica maior (~33 MB, e o app é de uso pessoal); a versão de release, com o R8, descarta os ícones não usados |
| O app passa a **guardar livros no aparelho**: Room para o índice, arquivos para o texto e as imagens, em dois níveis (Leve automático, Baixado pedido) — **reverte** a regra "sem cache local" do item 7.0 (30/09/2026) | O app deixou de ser só um gerador de prompts e está virando um leitor de livros: abrir instantâneo e ler sem conexão são o produto. O conteúdo que se guarda (texto do capítulo, arquivo de imagem) **não muda** depois de importado, então não há conflito; o que muda (arquivar, elementos, frames) continua mandando o servidor. A cópia local é **descartável**, o que dispensa migrações delicadas. Descartado: só o cache de imagens do carregador (Coil), que o sistema pode limpar e portanto não garante leitura offline; e guardar o índice em arquivo JSON (perde consultas e integridade). Custo aceito: o app ganha uma dependência (Room) e uma camada nova atrás dos repositórios que já existem (item 7.0a) |
| **Offline só de leitura**; escrever offline fica de fora (item 7.0a) | Escrever offline exige fila e resolução de conflito entre aparelhos, que é o que encarece uma sincronização; e as ações de IA precisam do servidor de qualquer jeito. Decisão do Allan, 30/09/2026 |
| **Contas de usuário adiadas**, com quatro preparações agora (chave do cache com servidor e conta; imagens pelo cliente HTTP do app; telas sem assumir usuário único; perfis compartilhados anotados) | Com um usuário só, contas seriam custo sem retorno (mudar cada rota para filtrar por dono); as preparações são quase de graça e evitam refazer o cache e o carregamento de imagens depois. Decisão do Allan, 30/09/2026 |
| **`revisao` por livro** (contador) para o app saber se algo mudou sem baixar tudo de novo (item 6.9) | Hoje não há coluna de alteração em quase nada. Alternativa descartada: data de alteração em cada tabela (mais colunas e sem a vantagem de um número único por livro) |
| Imagens em **tamanhos nomeados** (`miniatura`, `leitura`, `original`), e não uma largura livre (item 6.9) | Uma largura livre deixaria qualquer cliente gerar versões sem limite e encher o disco do Raspberry Pi |
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
| Posição das sugestões e dos frames guardada **em caracteres** (`posicao_no_texto`), obtida de uma **citação** devolvida pela IA | A IA erra contagem de caracteres, mas cita bem um trecho que acabou de ler; o servidor, com o texto inteiro, converte. Caractere, e não parágrafo, para não depender da regra de divisão de parágrafos do app. Alternativas descartadas: pedir o número à IA (impreciso) e só buscar o nome no texto (não serve para cenas) |
| Imagem mostrada no texto = a **mais recente** do frame; sem campo "imagem principal" por enquanto | Evita uma escolha a mais para o usuário e um campo novo no banco. Reavaliar se a escolha automática incomodar |
| App com **biblioteca de imagens (Coil)** e cache de imagens — **exceção** à regra "sem cache" do item 7.0 | A regra valia para *dados* (livros, capítulos). Imagens são grandes: sem cache, cada rolagem baixaria a figura de novo pela rede. Coil carrega só o que está na tela |
| **Geração de imagem pelo app fica apenas reservada** (item 7.5b): lugar na interface, sem campo no banco nem rota | Continua só o OpenRouter (item 4.1). O contrato se define quando se verificar o que o OpenRouter oferece para imagem; criar campos antes seria abstração prematura |
| **Custo de cada chamada de IA gravado em tabela própria** (`usos_ia`), em sessão separada e sem nunca derrubar a chamada (01/10/2026) | Pedido do Allan, para métricas futuras. O OpenRouter já devolve tokens e custo em dólares em cada resposta. Sessão própria porque a rota pode desfazer a transação dela depois de a chamada já ter sido cobrada; falha ao gravar só vai para o log. `custo` nulo (e não zero) quando o provedor não informa. *Alternativas descartadas:* gravar na sessão da rota (perderia o registro em chamadas cobradas cuja rota falhou) e acumular em memória (some ao reiniciar) |
| **Marcador (posição automática) e pin (posição manual) guardados no servidor, por livro; o marcador mais recente vence pelo `lido_em` do aparelho, e nenhum dos dois sobe a `revisao`** (01/10/2026) | Decisão do Allan: servidor, para valer em qualquer aparelho e viajar no "baixar livro". O `lido_em` vem do aparelho (e não da hora em que a gravação chega) para um aparelho offline não sobrescrever uma leitura mais nova; o servidor limita um `lido_em` no futuro ao seu relógio. Não sobem a `revisao` porque o marcador é gravado o tempo todo e faria o app reler a lista do livro sem parar. Posição no mesmo contrato UTF-16 do item 3.4g. *Alternativas descartadas:* guardar só no aparelho (não sincroniza), hora do servidor para decidir o conflito (um aparelho que sincroniza tarde venceria), e um marcador por aparelho (exige identificar aparelhos, que as contas de usuário adiadas resolveriam melhor) |
| **A orientação do usuário na reanálise fica guardada no capítulo e roda a IA sozinha** (01/10/2026) | Pedido do Allan: poder dizer o que a análise não pegou. Guardada porque só as sugestões **não confirmadas** são refeitas: sem guardar, o que o usuário pediu e ainda não confirmou sumiria na reanálise seguinte, e ele teria de redigitar. Roda a IA sem `forcar=true` porque mandar o texto já é o pedido de reanalisar. A IA a trata como palpite, não como fato, para não inventar o que o capítulo não mostra. *Alternativas descartadas:* valer só para a rodada em que foi enviada (perde o pedido na reanálise seguinte) e uma lista de orientações acumuladas (mais coisas para gerenciar na tela, sem pedido) |
| **Sugestão que não aparece no texto é sinalizada (`achado_no_texto`), nunca apagada; e a segunda análise simultânea do mesmo capítulo recebe 409** (01/10/2026) | Sinalizar: apagar perderia elementos legítimos que o texto chama por outro nome, e a busca por nome erra 1% a 3%; o app decide como mostrar. 409: esperar prenderia o pedido por minutos e esconderia a análise em andamento; é imediato e não gasta IA. A trava é em memória, válida com um só processo da API. *Alternativas descartadas:* apagar na geração; a segunda análise esperar a primeira; trava no banco (desnecessária com um processo) |
| **Imagens reduzidas com Pillow (`miniatura` 256 px, `leitura` 1280 px, JPEG 85) e dimensões guardadas; o layout no texto decidido pela imagem real, não pelo tipo do frame** (01/10/2026) | A imagem aparece em vários lugares (texto, painel de IA, ficha do elemento, catálogo de artefatos) e pesa até ~2 MB: carregar o original para um ícone desperdiça a rede do tablet. Pillow é o padrão para isso e tem pacote para ARM64. As dimensões vão para o banco porque a ferramenta de imagem externa nem sempre obedece o formato pedido no prompt (2:3 ou 16:9): o app decide o layout (retrato em duas colunas, paisagem na largura da tela) pelo que a imagem realmente é. *Alternativas descartadas:* decidir o layout por `Frame.tipo` (erraria quando a ferramenta ignora a proporção) e ler só o cabeçalho do arquivo à mão (resolveria as dimensões, mas não a redução) |
| **Geração de imagem no app: modelo padrão `meta/muse-image`, com `black-forest-labs/flux.2-klein-4b` como alternativa; o usuário poderá configurar o modelo (decidido depois)** (01/10/2026) | Decisão do Allan, com **os dados dele**: o `meta/muse-image` **permite imagens sensíveis** e custa **cerca de US$ 0,01 por imagem**, o menor entre os dois que ele já tinha na lista. **Não verifiquei** preço, política de conteúdo nem formato de saída: isso fica para quando a geração for implementada (item 4.1 e o botão reservado, 7.5b). Vale a ressalva já registrada na Etapa 8: qualquer mecanismo de conteúdo sensível só pode operar **dentro da política do modelo escolhido**; o sistema não contorna moderação de provedor. A escolha do modelo pelo usuário (e onde ela mora: `Configuracao`, item 3.4d, ou no perfil de renderização) **fica para depois**. A **importação** da imagem (incremento 12) vem **antes** e é independente disso |
| **Prompt recusado pelo provedor de imagem: uma suavização automática e uma segunda tentativa; nova recusa volta ao usuário para editar** (02/10/2026) | Testado em 01/10/2026 pelo `POST /api/v1/images` do OpenRouter com o prompt da Auri (*A Música do Silêncio*), que descreve a personagem nua: o `meta/muse-image` **recusou** (400, "content management policy", sem dizer o motivo) e o `black-forest-labs/flux.2-klein-4b` também (400, "flagged for sexual or adult content"); a web do OpenRouter, mesmo com o rótulo +18 e a confirmação de idade, bloqueou igual. **A premissa de que o modelo da Meta "permite imagens sensíveis" não se confirmou**; o preço (US$ 0,01 por imagem) sim. Quatro variações com **cobertura parcial** (cabelo e pano de linho sobre o corpo; ombros e braços nus; só o pano; vestida) **foram aceitas**, e a de cobertura parcial foi aprovada pelo Allan como fiel à ideia do autor sem ser chocante. O mesmo prompt no Gemini (web) saiu **muito divergente do texto**. **Decisão do Allan:** manter o `meta/muse-image` e tratar a recusa com um fluxo de três passos (S1 a S3, abaixo). **Alternativas descartadas:** (a) pôr a regra de suavização na instrução de prompt, que mudaria **todos** os prompts, inclusive os colados em outras ferramentas, e erraria o filtro de cada provedor; (b) verificação local do conteúdo antes de enviar, e regra de menores na instrução do prompt original — o Allan considera a moderação dos provedores **mais eficiente do que qualquer verificação nossa**, e o conteúdo do livro já está à mão do usuário; (c) pedir confirmação antes da segunda tentativa, que custaria um toque sem ganho (a recusa não cobra). **Ressalva mantida:** o sistema nunca contorna moderação de provedor; a suavização só deixa o prompt dentro da política do modelo |
| **`Configuracao.modelo_imagem` e `Configuracao.modelo_suavizacao` como campos próprios; os três modelos de texto continuam com os nomes de hoje** (02/10/2026) | O Allan pediu campos novos na configuração para a geração de imagem. **Alternativa descartada: renomear** `modelo_prompt`/`modelo_perfil` (ele sugeriu padrões como `modelo_prompt_perfil` e `modelo_prompt_imagem`): o nome `modelo_prompt` já é usado pelo app, pelos arquivos `.http` e por dezenas de testes, e renomear é uma mudança de contrato com o app sem ganho funcional; além disso dois campos com "perfil" no nome confundiriam. Os campos novos seguem o padrão `modelo_<tarefa>`. `modelo_imagem` não aceita nulo (sem ele a geração não tem o que chamar) e nasce `meta/muse-image`; `modelo_suavizacao` é opcional e cai no `modelo_prompt`. **Os ids entram à mão por enquanto** (`PUT /configuracao`): a busca e a escolha dos modelos dentro do app, sem ir ao site do OpenRouter, é a pendência registrada na Etapa 8. A lista de `GET /configuracao/modelos` hoje só traz modelos de **texto**; a de imagem fica para essa pendência |
| **Suavização trecho a trecho, com a mesma quantidade de itens** (02/10/2026) | A suavização por texto livre **suprimia pontos** da descrição do autor, mesmo com a instrução pedindo para mantê-los: nada obrigava o modelo a isso. Agora o servidor divide o prompt em trechos (separados por vírgula), manda a lista numerada e exige **o mesmo número de itens** de volta, juntando-os na ordem; número diferente = uma nova tentativa, e se errar de novo, erro (502). **Alternativas descartadas:** só reforçar a instrução em texto livre (continua sem garantia); comparar palavras no servidor (frágil: sinônimos e a própria troca do explícito mudam as palavras). Fidelidade garantida por **estrutura**, não por confiança no modelo |
| **`Imagem.origem` (`IMPORTADA`/`GERADA`)** (02/10/2026) | O Allan quer as imagens importadas numa seção própria, no fim, e as geradas em destaque (T2). O banco só sabia que uma imagem pertence a um prompt. **Alternativa descartada:** deduzir a origem pela situação do prompt (`COM_SUCESSO`): um prompt gerado pode também receber uma imagem importada, então a dedução erra |
| O container da API **aplica as migrations sozinho ao subir** (`alembic upgrade head` antes do `uvicorn`), e a imagem passa a ter um `.dockerignore` (30/09/2026) | O servidor roda 24/7 num Raspberry Pi: depois de um reinício ou de uma atualização do código, ele precisa subir com o banco no formato que o código espera, sem ninguém lembrar de um comando à mão. Num banco já atualizado o comando não faz nada; num banco vazio cria tudo (verificado: 15 tabelas, versão `f9a4c6e8b0d3`). Risco aceito: uma migration com defeito impede a API de subir — o motivo aparece em `docker compose logs api`. O `.dockerignore` tira da imagem o `venv`, o `.git`, o `.env`, os testes e a documentação (build mais rápido no Pi e nenhum segredo dentro da imagem). *Alternativa descartada:* rodar `alembic upgrade head` à mão a cada atualização (fácil de esquecer; foi assim até aqui). |

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
| `POST /elementos/{id}/historico-identidade` | Acrescenta à mão o que um capítulo revela sobre quem o elemento é (item 3.4f) | **implementado** |
| `PATCH /historico-identidade/{id}`, `DELETE /historico-identidade/{id}` | Corrige ou apaga um acréscimo de identidade | **implementado** |
| `POST /elementos/{id}/mesclar` | Junta o elemento (origem) a `destino_id`, que fica: estados, identidade e sugestões passam para o destino, a origem deixa de existir | **implementado** |
| `POST /elementos/{id}/estados` | Registra um novo estado a partir de um capítulo | **implementado** |
| `POST /elementos/{id}/estados-de-sugestoes` | Registra um Estado por sugestão escolhida, numa chamada só (item 3.4e) | **implementado** |
| `GET /estados/{id}` | Um estado isolado, com o elemento a que pertence | **implementado** |
| `PATCH /estados/{id}` | Ajusta a descrição ou define a imagem-âncora | **implementado** |
| `DELETE /estados/{id}` | Remove um estado | **implementado** |
| `GET /capitulos/{id}/estados-vigentes` | O estado vigente de cada elemento naquele ponto da narrativa | **implementado** |
| `GET /livros/{id}/sugestoes-elemento?nome=...` | Busca sugestões de elemento por nome, em todos os capítulos do livro — acha menções antigas do mesmo personagem para associar (item 3.4e); resposta traz `estado_id` por sugestão (item 3.4e) | **implementado** |
| `PATCH /sugestoes-elemento/{id}` | Corrige só o `elemento_id` de uma sugestão (`null` **desfaz de verdade**), sem gravar Estado (item 4.6), **ou** a descarta/restaura (`descartada`, item 6.8) — uma coisa por pedido | **implementado** |
| `PATCH /sugestoes-cena/{id}` | Descarta (ou restaura) uma sugestão de cena (item 6.8) | **implementado** |

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
| `POST /prompts/{id}/gerar-imagem` | **Gera a imagem pelo servidor**, com suavização se o provedor recusar (S1 a S12) | **implementado** |
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

#### Gerar a imagem (especificado em 02/10/2026; incremento 12, S1 a S12 do item 7.5b)

`POST /prompts/{id}/gerar-imagem`: o servidor envia o prompt ao modelo de imagem (`Configuracao.modelo_imagem`, item 3.4d), grava a imagem **pelo mesmo caminho da importação** (disco, `Imagem`, dimensões, versões reduzidas) e atualiza a situação do prompt (item 3.4c). **Gasta IA** (cerca de US$ 0,01 por imagem gerada); a recusa não cobra.

**Corpo (opcional):** `{"texto": "..."}`: o prompt **editado à mão** pelo usuário (S3). Sem corpo, vale o texto do prompt.

**O fluxo:**

1. **Sem `texto` (ou igual ao do prompt):** S1, envia o prompt tal como está. Se **gerou**, o prompt fica `COM_SUCESSO` e a imagem entra nele.
2. **Se o provedor recusou o conteúdo** (S4), o prompt fica `RECUSADO` com o `motivo_da_recusa` (gravado **antes** de seguir, para a recusa não se perder se o resto falhar). O servidor **suaviza** (`suavizar_prompt`, com `modelo_suavizacao`, ou o `modelo_prompt` se aquele estiver vazio; sem nenhum dos dois, 422) e cria um **prompt novo** com o texto suavizado e `prompt_original_id` apontando para o original. Faz a **segunda tentativa** com ele (S2). Gerou: o suavizado fica `COM_SUCESSO` e recebe a imagem. Recusou de novo: o suavizado fica `RECUSADO`, e o servidor **devolve ao usuário** (S3).
3. **Com `texto` diferente do prompt (edição manual, S3):** o texto editado vira um **prompt novo** (com `prompt_original_id` apontando para o prompt de onde o usuário partiu) e é enviado **direto**, sem suavização. O original nunca é sobrescrito.

**Resposta (200, nos dois desfechos):**

| Campo | O que é |
|---|---|
| `resultado` | `GERADA` ou `RECUSADA` |
| `suavizado` | `true` se o prompt enviado por último é uma versão suavizada pelo sistema |
| `prompt` | o prompt que foi enviado **por último** (o original, o suavizado ou o editado), com a situação e o `motivo_da_recusa`: é o que o app mostra e deixa editar |
| `imagem` | a imagem gerada (`ImagemResumo`), ou nulo se `RECUSADA` |

Recusa não é erro de servidor: responde **200** com `RECUSADA`, e o app lê o `prompt` devolvido para abrir a edição.

**Erros:** `404` prompt inexistente; `422` sem chave ou sem modelo (`ChaveDeApiAusente`, `ModeloNaoEscolhido`); `502` qualquer outro erro do provedor (rede, 503 "temporariamente indisponível", resposta fora do formato), **sem suavizar**.

**Custo (item 4.3):** cada imagem gerada grava uma linha em `usos_ia` com `operacao="imagem"` (o provedor informa o custo em dólares); a suavização grava `operacao="suavizacao"`. A recusa não cobra e não grava linha.

**Como o provedor reconhece a recusa (S4):** erro **400** do OpenRouter cuja mensagem fala de política de conteúdo (hoje: *content management policy*, na Meta; *flagged for sexual or adult content*, na Black Forest Labs). A detecção fica numa função só, fácil de ajustar quando um provedor mudar o texto; mensagem desconhecida cai no erro comum.

**Resposta do OpenRouter lida:** `data[0].b64_json` (base64) com `media_type` (`image/webp` no `meta/muse-image`); a extensão do arquivo sai do `media_type`. Resposta só com URL, em vez de base64, não é tratada por enquanto (erro do provedor).

**Implementado (02/10/2026), em linguagem simples.** A rota `POST /prompts/{id}/gerar-imagem` roda o fluxo inteiro **no servidor**, para o app só chamar e mostrar o resultado. A lógica mora num serviço novo (`servicos/geracao_de_imagem.py`) e não na rota, que é fina; assim a regra "original, suavizar, segunda tentativa, devolver" fica num lugar só e testável sem HTTP. O provedor (`ProvedorOpenRouter`) ganhou `gerar_imagem` (chama `/images`, lê o base64) e `suavizar_prompt` (chama o modelo de texto com a instrução própria, `_INSTRUCAO_DE_SUAVIZACAO`, que traz as regras S7 a S9). Para distinguir uma **recusa de conteúdo** de qualquer outra falha, o erro HTTP do OpenRouter agora guarda o código e o corpo (`ErroHttpDoProvedor`, que continua sendo um `ErroDoProvedorIA`), e uma função isolada (`_motivo_de_recusa`) reconhece o 400 com texto de política; quem muda a redação de uma recusa só mexe ali. O prompt suavizado e o editado são **prompts novos** ligados ao de origem; a situação de cada tentativa (`RECUSADO`/`COM_SUCESSO`) é gravada **na hora**, então uma recusa não se perde mesmo se a etapa seguinte falhar (por exemplo, sem modelo de suavização, o que responde 422 depois de já ter marcado o original `RECUSADO`). A imagem gerada entra no catálogo pelo mesmo caminho da importada (arquivo em disco, linha em `imagens`, largura e altura), então miniaturas, tela cheia e o ícone `ILUSTRADO` funcionam sem mudança. `ProvedorFalso` ganhou `recusas_de_imagem` (quantas das primeiras gerações recusar), `prompt_suavizado` e os registros das chamadas, e gera um PNG de verdade; **nenhum teste chama o OpenRouter nem gasta dinheiro**. 31 testes novos (17 do provedor com transporte HTTP falso, 14 da rota; 582 no total). **Ainda não foi chamado o `meta/muse-image` por esta rota**: o formato da resposta e a recusa foram vistos nos testes manuais de 01/10 e reproduzidos nos testes, mas a primeira chamada real pela rota fica para quando o Allan pedir. **Para o app:** rota **nova**; o app atual não a usa. O tempo de resposta de uma geração real não foi medido; o app vai precisar do tempo de espera longo (como em `gerar prompt`).

**O que não entra:** parâmetros de tamanho/proporção no pedido (o formato vai no próprio texto do prompt, item 4.5; não testei esses parâmetros no `meta/muse-image`), mais de uma imagem por pedido, *streaming*, a tela do app (próxima fatia) e a escolha do modelo pelo usuário dentro do app (Etapa 8).

#### O que foi implementado

As oito rotas, com 16 testes. O `ler_com_limite` que já protegia o upload do EPUB (item 6.2) virou função compartilhada em `servicos/upload.py`, reaproveitada aqui para o upload de imagem — é a mesma proteção contra um arquivo grande demais para a memória do Raspberry Pi, e duplicar essa lógica de leitura em blocos seria repetir um código sensível à segurança sem motivo.

O texto do perfil que vai para a IA é montado só com os campos preenchidos (`estilo`, `artista_referencia`, `iluminacao`, `paleta`, `formato`) — confirmado com um perfil só com `estilo` definido e outro com todos os campos, verificando que o texto muda de tamanho de acordo, sem campos vazios aparecendo como "None" ou string vazia no meio do prompt.

`DELETE /prompts/{id}` apaga os arquivos das imagens **depois** do commit que remove as linhas do banco, não antes: se a remoção de um arquivo falhasse no meio, o banco já estaria consistente (prompt e imagens removidos), e sobraria só um arquivo órfão no disco — o mesmo tipo de custo aceitável registrado na limitação conhecida acima, e não uma inconsistência de dados.

**Divergência registrada, pós-validação com IA real.** A versão inicial de `criar_prompt` só lia os estados já salvos no banco, sem tocar na IA antes de montar o prompt. Um teste de ponta a ponta com `openai/gpt-4o-mini` e `google/gemini-2.5-flash` no mesmo capítulo real mostrou erros de atribuição e um elemento inventado quando a descrição de aparência de vários elementos era gerada numa única chamada (item 4.2). A rota passou a fazer a leitura profunda elemento por elemento, imediatamente antes de montar o prompt, e a aceitar um `comentario` do usuário com prioridade sobre essa leitura. Na mesma rodada, ganhou `referencias_visuais` (item 4.5), conectando um campo que existia desde o item 3.1 mas nunca tinha sido lido por nenhuma rota.

**Segunda divergência, testando um retrato solo.** Um prompt pedido só para o Vis Solum citou o pai dele, porque a descrição livre da "cena" (que na época servia tanto para retrato quanto para cena de verdade) mencionava o pai por nome. A entidade `Cena` virou `Frame` com um campo `tipo` (item 3.4c), e a rota passou a: (1) zerar a descrição do frame quando `tipo=PERSONAGEM`, e (2) só para `tipo=CENA`, fazer uma segunda leitura profunda — `fundamentar_frame` — que confere o texto do usuário contra o capítulo sem sobrescrevê-lo. Testado com IA real: a fundamentação chegou a ler o trecho errado do capítulo (uma cena bem posterior), e o prompt final saiu correto mesmo assim, porque a descrição do usuário tem prioridade sobre o contexto do livro.

### 6.7 Extração e configuração

| Método e caminho | O que faz | Estado |
|---|---|---|
| `POST /capitulos/{id}/sugestoes` | Sugere elementos e cenas (passo 6); `?forcar=true` ignora o cache e chama a IA de novo. **Gera (e cobra) se o capítulo nunca foi analisado** — para só ler, use o `GET` da mesma rota (item 6.8) | **implementado** |
| `GET /configuracao/modelos` | Lista os modelos disponíveis no OpenRouter (item 4.3); filtros `somente_com_json`/`somente_nao_moderados`/`ordenar_por_custo` | **implementado** |
| `GET /configuracao` | A configuração atual: modelos escolhidos, se o **servidor** tem chave (`"ambiente"`/`"ausente"`) | **implementado** |
| `PUT /configuracao` | Grava modelos (extração, prompt, perfil, **imagem** e **suavização**) e `prioridade_ia`. **Não aceita mais `chave_api_openrouter`** (422) — item 4.3 | **implementado** |

**Header `X-Chave-API-OpenRouter`** (opcional) vale em toda rota que chama IA — sugestões, prompts, sugestão de perfil e lista de modelos — e tem precedência sobre a variável de ambiente do servidor (item 4.3).

`GET /configuracao` **nunca devolve a chave de API**, só se o servidor tem uma. Uma chave que sai do servidor é uma chave que vaza em log, em cache de app ou em captura de tela.

**`POST /capitulos/{id}/sugestoes` não grava Elemento nem Frame no banco.** É a IA sugerindo; o usuário confirma depois pelas rotas já existentes da Etapa 6.3 (`POST /elementos`, `POST /elementos/{id}/estados`) e da Etapa 6.4 (`POST /frames`). A sugestão em si, porém, é persistida como linhas (item 3.4e). A rota:

1. Busca o texto do capítulo e o estado vigente de cada elemento do livro **até aquele capítulo** (mesma consulta do item 6.3, `estado_vigente_por_elemento`, limitada por `Capitulo.ordem`) — é o contexto que permite à IA responder "manter estado atual" em vez de inventar um estado novo.
2. **Se `Capitulo.sugestoes_geradas_em` já está preenchido e o pedido não veio com `?forcar=true`, não chama a IA** — serve o que já está salvo em `SugestaoDeElemento`/`SugestaoDeCena`.
3. Sem sugestão salva, ou com `forcar=true`: confere se o texto cabe na janela do modelo escolhido (`modelo_extracao` da configuração) **antes** de chamar a IA — gastar a chamada para descobrir que não cabia seria o pior caso (item 4.3).
4. Chama `provedor.extrair_elementos` — só identificação (fase 1 do item 4.4): tipo, nome, descrição de identidade e `manter_estado_atual`. **Não** devolve mais uma descrição de aparência; essa parte é a leitura profunda (fase 2), que só acontece mais tarde, dentro de `POST /frames/{id}/prompts` (item 6.6). O resultado vira linhas em `SugestaoDeElemento`/`SugestaoDeCena`, substituindo só as sugestões ainda não confirmadas do capítulo (item 3.4e).
5. Tenta casar cada sugestão (recém-gerada ou já salva) com um elemento já cadastrado do livro, comparando tipo e nome **sem diferenciar maiúsculas/minúsculas nem acentuação** — a IA foi instruída a repetir o nome exato de um elemento conhecido, mas variações de caixa e acento apareceram como algo razoável de tolerar sem risco de casar elementos diferentes por engano. Quando casa, preenche `elemento_id` **e marca `casamento_automatico=true`** (item 3.4e/4.6, implementado) — ninguém revisou esse casamento específico ainda.
6. Faz o mesmo casamento para cada participante de cada cena sugerida (item 4.4) — mesma normalização, mesmo campo `elemento_id`, mesma marcação de `casamento_automatico`.

**Resposta ganha `sugestoes_pendentes_anteriores` (implementado, item 4.6).** Contagem de `SugestaoDeElemento`/`SugestaoDeCena` com `elemento_id`/`frame_id` nulo em capítulos anteriores (`Capitulo.ordem` menor) do mesmo livro — não bloqueia a chamada, só avisa que o contexto (`estados_conhecidos`) usado nesta análise está mais pobre do que poderia estar.

**Cada `SugestaoDeElemento` da resposta também ganha `estado_id` (item 3.4e, implementado).** Mesmo cálculo de `GET /livros/{id}/sugestoes-elemento`: se `elemento_id` já foi casado (passo 5/6 acima) mas não existe `EstadoElemento` daquele elemento **neste** capítulo, `estado_id` vem `null` — sinal de que confirmar a sugestão ainda falta virar um Estado de verdade, mesmo já estando "casada".

**Cada `CenaSugerida` da resposta ganha `frame_id` (implementado em 01/10/2026, defeito D2; 1 teste novo).** O Frame criado a partir da cena: **nulo = ainda pendente (ou descartada), preenchido = confirmada**. Campo novo e opcional, vale também para `GET /capitulos/{id}/sugestoes` e para a resposta de `PATCH /sugestoes-cena/{id}`. Antes dele o app **não tinha como** separar cenas confirmadas das pendentes. **Mudança de contrato do servidor (só acréscimo): o app pode usá-lo a qualquer momento.**

**Reanálise com orientação do usuário (M1; implementada em 01/10/2026).** `POST /capitulos/{id}/sugestoes` aceita um **corpo opcional** `{"orientacao": "..."}`: o usuário diz **o que a análise não pegou** ("falta a cena em que X chega ao porto", "o objeto Y também aparece") e a IA recebe isso junto do capítulo. Quem não manda corpo continua funcionando como sempre. As regras:
- **Orientação não vazia roda a IA**, mesmo que o capítulo já tenha sido analisado e sem precisar de `forcar=true`: mandá-la **é** o pedido de reanalisar. (Sem isso, o texto digitado seria ignorado em silêncio e o usuário ficaria sem entender por quê.)
- **A IA só inclui o que o texto realmente mostra.** A instrução diz que a orientação é um **palpite do usuário**, não um fato: se o que ele descreve não está no capítulo, a IA não inventa (mesma postura do item 4.4 sobre o usuário ter lido o capítulo, mas poder estar enganado).
- **Fica guardada no capítulo** (`Capitulo.orientacao_da_analise`, até 1000 caracteres; migration `e5a7c9d1f3b4`) e é **reaproveitada** nas reanálises seguintes. Sem isso, o que o usuário pediu e ainda não confirmou sumiria na reanálise seguinte, porque só as sugestões **não confirmadas** são refeitas (item 3.4e). **Uma orientação nova substitui a anterior; `""` (texto vazio ou em branco) a apaga** — e, por ser um pedido explícito de reanalisar, roda a IA sem ela.
- `GET` e `POST` devolvem a orientação vigente no campo `orientacao` (nulo = nenhuma), para o app mostrar o que está valendo e deixar editar.
- **Tamanho:** até **1000 caracteres** (422 acima). Não é o lugar de colar trechos do livro.
- **Não muda o que sobrevive à reanálise:** sugestões confirmadas ou descartadas continuam intactas, e o que a IA repetir delas não é recriado (item 3.4e).

**Verificado com IA real (01/10/2026, `gpt-4o-mini`, *O Alienista* cap. 3; `scripts/verificar_orientacao.py`).** Com uma orientação **falsa** ("um dragão ataca a cidade e Napoleão foge a cavalo"), a IA **não inventou nada**: nem dragão, nem Napoleão, e as cenas foram as mesmas. Com uma **verdadeira** ("falta a esposa do médico", que já estava no capítulo), a análise reagiu e acrescentou a cena "D. Evarista se preocupa". Uma amostra só, e a IA não é determinística: a conferência real é o uso. **Migration `e5a7c9d1f3b4`; 11 testes novos (511 no total); falta o app.** *Em linguagem simples:* o usuário escreve o que sentiu falta, o servidor guarda isso no capítulo e pede à IA para procurar com atenção, sem aceitar o que o texto não mostra.

**Sugestão que não aparece no texto é sinalizada, nunca apagada (implementado em 01/10/2026).** Cada `ElementoSugerido` da resposta ganha `achado_no_texto` (booleano): `true` quando o nome (ou um pedaço que seja nome próprio, item 3.4g) aparece no capítulo; `false` quando não. **Contexto:** a medição de 30/09/2026 mostrou que a IA às vezes lista um elemento que o capítulo não traz (3 de 4 sem posição, num capítulo medido). **Alternativas:** (A) apagar essas sugestões ao gerar; (B) **mantê-las e sinalizar**; (C) não fazer nada. **Escolhida a B**: apagar (A) perderia elementos legítimos que o texto chama por outro nome (um epíteto, uma tradução diferente) e a busca por nome tem um erro conhecido de 1% a 3%; a sinalização custa uma linha e deixa o app **ordenar essas por último e marcá-las "confira"**, sem decidir pela pessoa. É calculado na leitura, como a posição dos artefatos, então vale também nos capítulos já analisados. Cenas não têm o campo (a posição delas só existe depois de reanalisar, item 3.4g: um `false` seria enganoso nas antigas).

**Uma análise por capítulo de cada vez (implementado em 01/10/2026).** Se já há uma análise **em andamento** do mesmo capítulo, um `POST /capitulos/{id}/sugestoes` que precise rodar a IA responde **409** ("já há uma análise deste capítulo em andamento"), **sem gastar IA**. **Contexto:** duas análises simultâneas eram duas cobranças e duas levas de sugestões repetidas (pendência registrada no item 6.8). **Alternativas:** (A) a segunda **espera** a primeira e devolve o resultado dela; (B) **recusar** a segunda com 409; (C) nada. **Escolhida a B**: esperar prende um pedido por até minutos (o tempo limite da IA é generoso) e esconde do app que há uma análise rolando; o 409 é imediato e claro, e o app já desabilita o botão. **Limite conhecido, registrado:** a trava mora **na memória do processo**, então vale com **um só processo** da API (como é hoje, o `uvicorn` do container). Com vários processos, teria de virar uma marca no banco. A trava só vale para quem **roda a IA**: leituras (`GET`) e `POST` servido do que já está salvo não são barrados.

*Testes (9 novos; 520 no total):* a trava recusa a segunda reserva e libera ao sair, **inclusive se a análise falha**; o 409 não gasta IA; leitura e `POST` servido do salvo passam; e um teste com **duas requisições de verdade ao mesmo tempo** mostra uma só chamada à IA. **Falta o app:** mostrar o `achado_no_texto` ("confira") e tratar o 409 (a análise de outro aparelho em andamento).

Erros do provedor viram HTTP assim: `ChaveDeApiAusente` e `ModeloNaoEscolhido` e `TextoLongoDemais` → 422 (o problema é a configuração, o usuário resolve pela tela de configuração); qualquer outro `ErroDoProvedorIA` (rede, resposta fora do formato) → 502.

#### O que foi implementado

As três rotas de `/configuracao` foram implementadas junto com a camada de IA (Etapa 4.3), antes desta tabela ser atualizada — o código já existia, só faltava marcar. `POST /capitulos/{id}/sugestoes` é o item novo desta rodada, com 14 testes.

**Divergência registrada, pós-validação com IA real:** o campo `estado_sugerido` foi removido da resposta depois de um teste de ponta a ponta expor mistura de atributos entre elementos (ver a divergência do item 4.2 e a nova fase 2 do item 4.4). Numa rodada seguinte, a resposta ganhou `frames` (então chamado `cenas`) — feedback do usuário depois de revisar uma extração real: a lista de elementos sozinha não bastava, faltava sugerir quais combinações formam um momento que vale ilustrar, e alguns elementos identificados eram irrelevantes (papelada genérica) ou classificados no tipo errado (um tabuleiro de jogo como `AMBIENTE`, uma porta como `VEICULO`).

**Segunda divergência registrada, pós-uso real.** A rota nasceu como consulta pura, sem gravar nada — inclusive a sugestão em si. Testando o fluxo completo na mão, ficou claro o problema: a IA não é determinística, então cada chamada podia devolver um resultado diferente do anterior para o mesmo capítulo, e não havia como saber qual das respostas usar para criar o frame de verdade. A rota passou a salvar a resposta da IA em `Capitulo.sugestoes_ia` (sem `elemento_id`, recalculado a cada leitura) e a servir esse cache por padrão, só chamando a IA de novo com `?forcar=true` — o mesmo princípio de cache-a-não-ser-que-peça-de-novo já usado na leitura profunda e na fundamentação de frame (item 4.4, fases 2 e 3), agora estendido à fase 1.

A checagem de "cabe no modelo" (`conferir_se_cabe`) saiu de método de `ProvedorOpenRouter` para função livre em `ia/openrouter.py`: a rota precisa da mesma checagem antes de chamar **qualquer** provedor, inclusive o `ProvedorFalso` dos testes, e a estimativa de tokens não depende de nenhum detalhe de um fornecedor específico. O método antigo continua existindo, agora só delegando para a função — o que evitou reescrever os testes que já cobriam esse comportamento.

O casamento por tipo e nome normalizado (sem caixa, sem acento) foi verificado com um elemento cadastrado como "João" e uma sugestão da IA vindo como "joão" — casa; com o mesmo nome mas tipo diferente — não casa, porque dois elementos diferentes podem legitimamente ter o mesmo nome (um personagem chamado "Winterfell" e um lugar chamado "Winterfell" não seriam a mesma coisa, hipoteticamente).

> **Terceira divergência, registrada e implementada (item 3.4e).** O casamento automático por nome (parágrafo acima) tem um limite real: só pega variações de caixa/acento, não nomes genuinamente diferentes para a mesma pessoa (`"Sextus Hospius"` num capítulo, `"Hospius"` só, capítulos depois). A causa raiz tem uma parte evitável pelo fluxo de uso — `estados_conhecidos` (o que alimenta o reconhecimento da IA) só inclui elementos **já confirmados com um estado registrado**, então gerar sugestões de vários capítulos em lote, sem confirmar nada entre uma chamada e outra, priva a IA da própria informação que ajudaria a reconhecer o personagem — mas mesmo confirmando capítulo a capítulo, o casamento automático continua limitado a nomes parecidos. `Capitulo.sugestoes_ia` foi substituído por tabelas de sugestão persistidas e buscáveis, com confirmação em lote (`sugestoes_elemento_ids`) para os casos em que o casamento automático falha.

### 6.8 Artefatos do capítulo (os ícones no texto) — implementado

| Método e caminho | O que faz | Estado |
|---|---|---|
| `GET /capitulos/{id}/sugestoes` | **Só leitura** das sugestões já salvas do capítulo — a mesma resposta do `POST`, **sem nunca chamar a IA** | **implementado** (30/09/2026, 8 testes; a função nem declara a dependência do provedor de IA, então a garantia é estrutural) |
| `GET /capitulos/{id}/artefatos` | Tudo que o leitor do capítulo precisa desenhar sobre o texto, numa chamada só — **sem chamar a IA** | **implementado** — elementos (30/09/2026) e cenas (01/10/2026, a posição da cena só existe depois de analisar/reanalisar o capítulo) |
| `GET /capitulos/{id}/marcadores` | **Obsoleta.** O nome antigo de `/artefatos`: mesmos dados, no campo `marcadores` em vez de `artefatos`. Mantida só até o app migrar; depois, removida | **implementado** como alias (01/10/2026) |
| `PATCH /frames/{id}` | Passa a aceitar `posicao_no_texto` (item 3.4g); `null` tira o frame da posição | **implementado** (01/10/2026) |
| `POST /capitulos/{id}/frames` | Passa a aceitar `posicao_no_texto` (o "Ilustrar aqui"). **Divergência do plano:** com `sugestao_cena_id` o frame **não** copia a posição da sugestão (ver abaixo) | **implementado** (01/10/2026) |

**Renomeado em 01/10/2026: "marcador" virou "artefato" (decisão do Allan, defeito D4).** "Marcador" passa a ser outra coisa — a posição de leitura (Etapa 8, D4). **Mudança de rota que o app já usa:** `GET /capitulos/{id}/marcadores` → `GET /capitulos/{id}/artefatos`, e o campo `marcadores` da resposta → `artefatos`. Os campos de cada item **não mudaram** (`tipo`, `tipo_do_elemento`, `sugestao_id`, `frame_id`, `rotulo`, `posicao_no_texto`, `situacao`, `imagem_id`), nem os valores de `tipo` (`ELEMENTO`, `CENA`). **A rota e o campo antigos continuam funcionando, como alias, até o app migrar** — o app em uso não quebra. Nos textos desta especificação, "artefato" é o ícone no texto do capítulo; onde se lê "marcador" referente a ele, é o nome antigo.

**Por que uma rota só.** Para saber quais imagens mostrar, o app teria de listar os frames do capítulo, depois os prompts de cada frame, depois as imagens de cada prompt — uma chamada por frame e outra por prompt. Uma tela de leitura não pode esperar isso.

**Ler não é gerar: `GET /capitulos/{id}/sugestoes`.** Hoje só existe o `POST /capitulos/{id}/sugestoes` (item 6.7), e ele **chama a IA — e cobra — quando o capítulo nunca foi analisado**. Um leitor que carrega artefatos ao abrir o capítulo, ou que reabre o painel depois de sair no meio de uma análise, não pode usá-lo: gastaria IA sem ninguém pedir, e duas chamadas simultâneas seriam duas cobranças. O `GET` devolve o que está salvo no formato de `SugestoesDeCapitulo` (`gerado_em` **nulo = nunca analisado**, listas vazias), recalcula o casamento com `elemento_id` como o `POST` já faz (idempotente), e **nunca** chama o provedor. O `POST` passa a ser **só** o botão "Analisar" / "Reanalisar" do painel. *(Achado ao especificar o incremento 9 do app, 30/09/2026.)* ~~Pendência: duas análises **simultâneas** do mesmo capítulo continuam possíveis no servidor.~~ **Resolvida em 01/10/2026:** a segunda recebe 409 (item 6.7).

**Cada artefato traz:** `tipo` (`ELEMENTO` ou `CENA`), **`tipo_do_elemento`** (`PERSONAGEM`, `AMBIENTE`, `OBJETO`, `CRIATURA`, `GRUPO`, `VEICULO` ou `EDIFICACAO` — só nos artefatos de `ELEMENTO`; nulo nos de `CENA`; é o que escolhe o ícone, ver 7.5b), `sugestao_id` (nulo se o artefato nasceu à mão), `frame_id` (nulo até existir um frame), `rotulo` (nome do elemento ou título da cena), `posicao_no_texto` (nulo = sem posição), `situacao` e `imagem_id` (a mais recente do frame, ou nulo).

**`situacao`**, a mesma para os dois tipos: `SUGERIDO` (a sugestão existe e ainda não foi confirmada) → `CONFIRMADO` (virou elemento ou frame) → `PROMPT_PRONTO` (há prompt, falta imagem) → `ILUSTRADO` (há imagem). É o que faz o ícone mostrar onde o usuário parou quando volta de outro app.

**Ordem:** por `posicao_no_texto`; artefatos sem posição vêm depois, na ordem de criação.

**Um artefato de elemento leva ao retrato**: o `frame_id` dele é o frame `PERSONAGEM` daquele elemento *neste* capítulo, quando existe. Sugestões descartadas não aparecem.

**Imagens reduzidas (pendência).** `GET /imagens/{id}/arquivo` devolve o original, que pode ter vários MB. Para a leitura seria melhor uma versão reduzida (por exemplo, um parâmetro `largura`). Fica como pendência na Etapa 8; não bloqueia a primeira entrega.

### 6.9 Contrato para cache e leitura offline — especificado, ainda não implementado

Suporte do servidor ao item 7.0a. Nada aqui muda o que já existe: são acréscimos.

| Método e caminho | O que faz | Estado |
|---|---|---|
| (todas as respostas) | **Compressão gzip** (só acima de ~1 KB; imagens ficam de fora) | **implementado** |
| `GET /livros`, `GET /livros/{id}` | Trazem `revisao`; o segundo envia `ETag` e responde `304` a `If-None-Match` | **implementado** |
| `GET /livros/{id}/midias` | Manifesto das imagens do livro, com o tamanho de cada uma | **implementado** |
| `GET /livros/{id}/textos` | O texto de **todos** os capítulos numa chamada só | **implementado** |
| `GET /imagens/{id}/arquivo` | Cache imutável (`Cache-Control: immutable`) e `ETag`; `Imagem.tamanho_em_bytes` | **implementado** |
| `GET /imagens/{id}/arquivo?tamanho=` | Tamanhos nomeados (`miniatura`, `leitura`, `original`) | **implementado** (01/10/2026) |
| `largura`, `altura`, `orientacao` na imagem | `ImagemResumo`, no manifesto de mídias e no artefato; o app decide o layout sem baixar a imagem (item 7.5b, I1) | **implementado** (01/10/2026) |
| `GET /livros/{id}/marcador`, `GET /livros/{id}/pins` | Entram no pacote do "baixar livro" (item 6.10). **Não** sobem a `revisao` | **rotas implementadas** (item 6.10); a inclusão no pacote é do app |

**Implementado em 30/09/2026 (primeira metade do contrato, 16 testes; 348 no backend):** compressão, cache imutável e tamanho das imagens, o manifesto de mídias e os textos do livro. Migration `d6e1a3b5c7f2` (`Imagem.tamanho_em_bytes`, nula nas imagens antigas; o manifesto a calcula do disco e a grava na primeira vez). **Ficam para depois:** os tamanhos nomeados de imagem (`?tamanho=`, que exige gerar e guardar versões reduzidas).

**`revisao` e `ETag` implementados (30/09/2026; 377 testes no backend, 29 deles desta peça).** Migration `e7f2b4c6d8a1` (`Livro.revisao`, zerada nos livros existentes). **Decisão de implementação, resolvendo a pendência do item 6.9: um ouvinte do banco** (`imagineer/banco/revisao.py`, evento `before_flush`), e não uma chamada em cada rota — uma rota nova que altere dados não precisa lembrar de nada. O ouvinte mapeia cada objeto ao seu livro (capítulo, elemento, estado, histórico de identidade, frame, prompt, imagem, sugestões) e sobe o contador por **expressão SQL** (o banco soma, então duas gravações ao mesmo tempo não escrevem o mesmo número). **Duas exceções de propósito:** mudar só o tamanho de uma imagem (o manifesto o grava numa *leitura*, e uma leitura que sobe a revisão faria o app reler para sempre) e gravar um valor igual ao que já estava lá (sem mudança real, não há o que revisar).

**Pontos cegos conhecidos, documentados no próprio módulo:** (1) **apagar um perfil de renderização** faz o *banco* zerar (`ON DELETE SET NULL`) o perfil padrão dos livros que o usavam, sem nenhum evento do ORM — tratado à parte, subindo a revisão de cada livro atingido (e coberto por teste); (2) **operações em massa** (`delete(...)` direto) também não disparam eventos — hoje só há duas, em `_gerar_sugestoes`, sempre seguidas de mudanças pelo ORM no mesmo fluxo; uma operação em massa nova que altere dado visível **sem** isso precisaria subir a revisão à mão. **Tabela de ações nos testes:** 17 caminhos que alteram dado, cada um com um teste que prova que a revisão sobe — uma rota nova sem linha ali salta aos olhos.

**Já é assim, e fica registrado para não se perder:** `GET /livros/{id}` devolve só os capítulos e seus metadados (id, ordem, título, arquivado, tamanho do texto, sugestões pendentes), **nunca o texto** — 90 vezes menor que as listagens com texto (item 6.2). O texto só vem em `GET /capitulos/{id}`.

**Compressão.** O servidor hoje não comprime nada. Texto em português comprime muito bem, e um capítulo chega a ~110 KB sem compressão. É uma linha de configuração (`GZipMiddleware`, só acima de ~1 KB); o cliente HTTP do app descomprime sozinho. Imagens já são comprimidas e não ganham com isso.

**`revisao` (inteiro, por livro).** Um contador que **sobe a cada mudança no que o leitor mostra** daquele livro: importação, `PATCH` de livro, `PATCH` de capítulo (título, arquivado), elemento, estado, frame, prompt, imagem e sugestões. O app guarda a última revisão vista e, ao abrir o livro, só relê a lista se ela mudou (item 7.0a, A8). `GET /livros/{id}` devolve também `ETag` com a revisão e responde `304` a `If-None-Match`, economizando até a lista. **Como subir o contador** é decisão de implementação, com um risco a conhecer: chamar uma função em cada rota que muda algo é fácil de esquecer numa rota nova; ouvir o momento em que o banco grava (*hook* do SQLAlchemy) é mais robusto. Seja qual for, **um teste por rota que altera dado** deve provar que a revisão subiu. Hoje **não existe** coluna de alteração nas tabelas (só `data_importacao` e `sugestoes_geradas_em`), então a revisão é uma coluna nova em `Livro`.

**`GET /livros/{id}/midias`** devolve, para cada imagem do livro: `imagem_id`, `frame_id`, `tamanho_em_bytes` (o original) e o tipo do arquivo. É o que permite ao app mostrar **"Baixar — 240 MB" antes de começar** (item 7.0a, A4) e saber o que falta baixar. Exige que a `Imagem` passe a guardar `tamanho_em_bytes` — coluna nova, preenchida na importação e, para as imagens existentes, a partir do tamanho do arquivo em disco.

**`GET /livros/{id}/textos`** devolve `[{capitulo_id, texto}]` de **todos** os capítulos. Existe para "Baixar para ler offline": o texto de um livro tem ~0,7 MB em mediana (~0,3 MB comprimido), então uma chamada é melhor que 50. É uma **otimização**: sem ela, o app poderia baixar capítulo por capítulo.

**Tamanhos de imagem e dimensões — implementado em 01/10/2026 (decisão do Allan; biblioteca Pillow).**
- **`?tamanho=miniatura`** = **256 px** no lado maior; **`leitura`** = **1280 px** no lado maior; **`original`** (padrão) = o arquivo como veio. Qualquer outro valor é 422. As versões reduzidas são **JPEG qualidade 85**, geradas **uma vez, na primeira vez que alguém as pede**, e guardadas em `derivadas/<tamanho>/<id>.jpg` dentro de `DIRETORIO_IMAGENS` (mesmo volume do catálogo). Transparência vira fundo branco.
- **Nunca amplia:** se a imagem já cabe no tamanho pedido, devolve o **original** (ampliar só engordaria o arquivo e piorava a imagem). Arquivo que o Pillow não consegue ler também volta como original.
- Mesmo cabeçalho de cache imutável do original: o arquivo de uma imagem nunca muda. Apagar a imagem apaga as versões reduzidas.
- **`Imagem.largura` e `Imagem.altura`** (migration `f6a8d0e2b4c5`): lidas pelo Pillow **na importação**; nas imagens antigas, **calculadas na primeira leitura** e gravadas (como o `tamanho_em_bytes`, e sem subir a `revisao`: o app não precisa reler a lista por isso). `orientacao` é calculada: `RETRATO` se altura > largura, `PAISAGEM` se não, nulo sem dimensões. Um arquivo que o Pillow não lê **continua sendo aceito** na importação (as dimensões ficam nulas), como era antes.
- **O artefato** ganha `imagem_largura`, `imagem_altura` e `imagem_orientacao` (nulos sem imagem).
- **Testes: 17 novos (543 no total).** Cobrem: dimensões e orientação na importação (retrato, paisagem, quadrada), arquivo que não é imagem (aceito, sem dimensões), `miniatura` e `leitura` (tamanho e proporção), nunca ampliar, geração uma vez só, transparência, tamanho inválido (422), apagar imagem e prompt (versões reduzidas somem), dimensões calculadas na leitura sem subir a `revisao`, e os campos novos no artefato. **Falta o app** (incremento 12: o layout do item 7.5b).
- *Por que Pillow:* é a biblioteca padrão para isso em Python, tem pacote pronto para o Raspberry Pi (ARM64) e dispensa compilar. *Alternativa descartada:* ler só o cabeçalho do arquivo à mão (serviria para as dimensões, mas não para reduzir).

**Imagem: tamanhos nomeados e cache imutável.** `GET /imagens/{id}/arquivo` hoje devolve sempre o original (até 25 MB). Passa a aceitar `?tamanho=`: **`miniatura`** (margem do texto e listas), **`leitura`** (imagem entre os parágrafos) ou **`original`** (o padrão, como hoje e para ampliar). Tamanhos **nomeados e em número fixo**, e não uma largura livre: uma largura livre deixaria qualquer cliente gerar versões sem limite e encher o disco. A versão reduzida é gerada uma vez e guardada em disco (nome derivado do arquivo original). As três respostas levam `Cache-Control: public, max-age=31536000, immutable` — seguro porque o arquivo de uma imagem **nunca** muda — e `ETag`. *(O `FileResponse` do Starlette envia `ETag` e `Last-Modified`, mas **não** responde `304` a `If-None-Match`: isso só o `StaticFiles` faz. Não é necessário: com `immutable` de um ano, um cliente correto nem chega a revalidar, e os ids de imagem nunca mudam.)* *(Os valores exatos em pixels, como 400 e 1200, ficam para o momento de implementar, depois de ver imagens reais.)* Isto realiza a pendência "imagens reduzidas" já registrada no item 6.8.

### 6.10 Marcador e pins do livro — implementado no servidor em 01/10/2026 (18 testes; falta o app)

Rotas do item 3.4h. Todas respondem **404** se o livro (ou o pin) não existe.

| Método e caminho | O que faz | Estado |
|---|---|---|
| `GET /livros/{id}/marcador` | O marcador do livro, ou `{"marcador": null}` se a pessoa ainda não leu nada (como `gerado_em` nulo no item 6.7: "nunca" é um estado normal, não um erro) | **implementado** |
| `PUT /livros/{id}/marcador` | Grava o marcador. Corpo: `capitulo_id`, `posicao_no_texto`, `lido_em`. Regra de conflito acima. Devolve `{marcador, aceito}` | **implementado** |
| `GET /livros/{id}/pins` | Os pins do livro, **na ordem do livro** (ordem do capítulo, depois posição) | **implementado** |
| `POST /livros/{id}/pins` | Cria um pin: `capitulo_id`, `posicao_no_texto`, `nota` opcional. **201** | **implementado** |
| `PATCH /pins/{id}` | Ajusta a `nota` (`null` apaga a nota). Devolve o pin | **implementado** |
| `DELETE /pins/{id}` | Remove o pin. **204** | **implementado** |

**Validações (422):** o `capitulo_id` precisa ser **deste livro**; `posicao_no_texto` não pode ser negativa nem passar do tamanho do texto do capítulo (em UTF-16); `nota` até 1000 caracteres. **O `PUT` não valida `lido_em` contra o relógio além do limite acima** (futuro é limitado, não recusado).

**O que o app faz** (para o Claude do app; telas ficam a especificar na Etapa 7): grava o marcador **quando a pessoa para de rolar** (alguns segundos depois do último movimento) e **ao sair do capítulo/livro**, nunca a cada pixel; ao abrir o livro, lê o marcador e oferece "Continuar de onde parou"; se o `PUT` voltar com `aceito: false`, avisa que outro aparelho leu mais recentemente. Pin é criado por uma ação explícita na leitura (toque longo ou botão) e listado numa tela do livro.

**Entra no "baixar livro" (item 6.9 e 7.0a):** o pacote offline passa a incluir `GET /livros/{id}/marcador` e `GET /livros/{id}/pins`, junto de `textos` e `midias`. Offline continua **só de leitura** (item 7.0a): o marcador lido offline fica guardado no aparelho e é enviado ao voltar a rede, e o `lido_em` é o que mantém a ordem certa. Criar ou apagar **pins** sem rede **não** é suportado por ora.

**Em linguagem simples, o que foi feito (01/10/2026).** O servidor ganhou duas tabelas (`marcadores` e `pins`, migration `c3e5a7b9d1f2`) e as seis rotas acima. Quando o app avisa "parei aqui" (`PUT /livros/{id}/marcador`), o servidor compara a hora do aparelho com a do marcador já guardado: se a nova for mais recente (ou igual), substitui; se for mais antiga, não mexe e devolve `aceito: false` com o marcador que continua valendo. O servidor recusa capítulo de outro livro e posição além do fim do texto (contada em UTF-16, como o app conta). Os pins são independentes e voltam na ordem do livro. Nada disso sobe a `revisao` do livro (um teste prova). **Divergências do plano: nenhuma.** Testado também ao vivo no PostgreSQL (hora com fuso, limite de hora no futuro). **Falta, no app:** gravar o marcador ao parar de rolar e ao sair, "Continuar de onde parou", a tela de pins, e levar os dois no "baixar livro".

**Fica para depois:** destaques de trecho; um `trecho` (amostra do texto) devolvido junto de cada pin para a lista (o app, com o texto baixado, consegue montá-lo); estatísticas de leitura; "continuar lendo" na Biblioteca (a rota `GET /livros` poderia trazer o marcador de cada livro — decidir quando a tela for especificada).

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
@Serializable data class CapitulosArquivados(val livroId: Int)      // 7.4 (revisão do incremento 6)
```

"Importar livro" (7.3) não é destino próprio — é estado sobreposto à Biblioteca (barra de progresso/diálogo), não uma tela que empilha na navegação. `Prompt.promptId` é opcional: `null` ao gerar um prompt novo a partir do frame, preenchido ao abrir um prompt já existente do histórico. A pilha é hierárquica e simples — Biblioteca → Livro → Capítulo → Frame → Prompt, cada tela empilha a próxima, sem `popUpTo` especial (exceto Importar → Livro, que substitui o estado de importação em vez de empilhar). Elementos do Livro, Perfis de Renderização e Configuração são acessíveis de vários pontos (ícones na barra superior), fora da pilha hierárquica principal.

**(Parcialmente superado pelo item 7.0a: a decisão de não cachear livros mudou em 30/09/2026, quando o app passou a ser também um leitor. O DataStore continua guardando as preferências.) Armazenamento local: Jetpack DataStore (Preferences), só pro que precisa persistir hoje.** O app não cacheia livros/elementos/prompts — tudo vem do servidor a cada chamada, já que ele está sempre a uma chamada de distância via Tailscale (item acima). Dois dados salvos localmente, com sensibilidade diferente:

- **Endereço do servidor** (item acima): dado comum, `DataStore` normal (texto plano) basta.
- **Chave de API do OpenRouter — nunca armazenada remotamente, de propósito.** Reabriu o item 4.3 do backend, **já implementado**: `PUT /configuracao` não aceita mais `chave_api_openrouter` (422), a coluna foi removida do banco e o header `X-Chave-API-OpenRouter` passou a valer em toda rota de IA. A única forma persistente de configurar a chave no servidor passa a ser a variável de ambiente do `.env` no próprio Raspberry Pi (via SSH — hoje já existe como opção, item 4.3), pro uso pessoal do Allan. Para um uso futuro com mais de um usuário, cada um guardaria a própria chave só no celular, nunca no servidor. No app, a chave é um **segredo**, não um dado comum — guardada em `EncryptedSharedPreferences` (ou a variante criptografada do DataStore, biblioteca `androidx.security.crypto`, baseada em Tink), não em texto plano. Toda chamada que envolve IA manda a chave no header `X-Chave-API-OpenRouter`, quando o usuário tiver configurado uma no app; o servidor nunca persiste esse valor — nem em banco, nem em log.

**(Superado pelo item 7.0a para **leitura**: sem conexão, o que já foi lido ou baixado abre. Vale ainda para as **ações que exigem o servidor**.) Erro/offline: sem cache local, tela de erro com "tentar de novo".** Coerente com a decisão de não cachear dado nenhum localmente (item acima) — o app sempre depende do servidor, então sem servidor não há o que mostrar mesmo. Qualquer chamada que falhar (timeout, sem conexão, Pi desligado, Tailscale desconectado) mostra uma mensagem clara ("não consegui falar com o servidor") com um botão pra tentar de novo, em vez de simular um modo offline com dado desatualizado — que introduziria sincronização e conflito sem necessidade real pro uso de hoje.

**Design visual: Material 3 puro, sem tema customizado.** Usa os componentes e cores padrão do próprio design system do Android/Compose (`MaterialTheme` sem paleta customizada), incluindo cor dinâmica (Material You — segue o papel de parede do sistema, Android 12+) e tema claro/escuro automático, seguindo a preferência do sistema. Menos decisão de design pra tomar agora, foco no funcional — trocar por um tema customizado depois é direto, o Material 3 foi feito pra isso.

**Build/assinatura: keystore própria, versionamento semântico simples.** Instalação manual (sideload, item 1.3) ainda exige o APK assinado — o Android recusa instalar um `.apk` sem assinatura. Uma keystore local, gerada uma vez e guardada com cuidado fora do repositório (nunca commitada — mesmo princípio do `.env`/segredos já usado no backend, item 5), assina as releases. `versionCode` incrementa a cada build; `versionName` segue semântico simples (`0.1.0`, `0.2.0`...). Importante: reinstalar uma versão nova por cima de uma antiga só funciona se as duas forem assinadas pela **mesma** keystore — perder a keystore significa ter que desinstalar o app inteiro (perdendo o que estiver salvo localmente, item acima) pra instalar de novo.

**Wireframes (baixa fidelidade, fora do repositório — link vivo abaixo).** Antes de codar, as telas da Etapa 7 foram esboçadas como protótipo clicável, pra validar fluxo e estrutura antes do visual final (Material 3, item acima). Publicado como Artifact (não é um arquivo deste repositório — Kotlin não lê isso, é só material de referência de design): **https://claude.ai/artifact/SYG2RH5qocHEiWuWXZEFEx**. Organizado nos mesmos 5 blocos de jornada que a implementação deveria seguir, cada um cobrindo as telas já numeradas na Etapa 7:

- **Bloco A — Biblioteca e Importação**: 7.2 (Biblioteca) + 7.3 (confirmar metadados pendentes, item 6.2).
- **Bloco B — Leitura e Catalogação**: 7.4 (Livro) + 7.5 (Capítulo — texto, sugestões, cenas).
- **Bloco C — Criação do Frame**: 7.6 (retrato ou cena, elementos ligados).
- **Bloco D — Prompt e Catálogo**: 7.7 (texto do prompt, referências visuais, importar imagem).
- **Bloco E — Gestão Transversal**: 7.8 (Elementos), 7.9 (Perfis de Renderização), 7.10 (Configuração — já reflete a chave de API como segredo local, item acima).

Os wireframes são clicáveis (Biblioteca → Livro → Capítulo → Frame → Prompt, mais os ícones de Elementos/Perfis/Configuração na barra) — dá pra navegar a jornada inteira dentro do Artifact antes de aprofundar tela por tela. **Próximo passo, ainda não feito**: revisar os wireframes e aprofundar bloco a bloco (detalhes de cada tela, estados de erro/vazio, antes de escrever qualquer Kotlin).

### 7.0a Armazenamento local e sincronização — especificado, ainda não implementado

**Como nasceu (30/09/2026).** O Allan percebeu que o app deixou de ser só um gerador de prompts de imagem: está virando um **leitor de livros completo**, no estilo do Kindle, em que se lê sem conexão e os livros e as imagens acompanham o usuário entre aparelhos. Testando no tablet e no celular ao mesmo tempo, viu que o que se arquiva em um aparece no outro — e pediu que o uso offline e a sincronização fossem alinhados **agora**, antes de as imagens entrarem no texto, para não complicar depois. Esta seção é esse alinhamento. **Nenhum código foi escrito.**

**O que já é verdade hoje** (verificado no código):
- **O servidor é a única fonte da verdade**, e é por isso que dois aparelhos já enxergam o mesmo estado. Para uso **online** com vários aparelhos, **não há nada a construir**.
- **As imagens ficam só no servidor**: arquivos em disco (volume do Docker), só o caminho no banco, nome gerado (UUID, nunca sobrescrito), limite de 25 MB por imagem (item 6.6). A tabela `Imagem` **não guarda tamanho** nem dimensões.
- **O app não guarda nada** além do endereço do servidor (DataStore).
- **O servidor não tem data de alteração** em quase nada (só `data_importacao` e `sugestoes_geradas_em`) e **não comprime** as respostas.
- **Medido no corpus de validação (22 livros):** o texto de um livro tem, em mediana, **677 KB** (máximo 2,2 MB), com 50 capítulos em mediana; a biblioteca inteira soma **17,5 MB de texto**. O peso está nas **imagens** (tamanho real ainda não medido; suposição de 1 a 4 MB cada).
- **`GET /livros/{id}` já devolve só os metadados dos capítulos**, sem o texto (item 6.2, medido: 7,5 KB contra 674 KB de texto num livro de 84 capítulos). O texto só vem em `GET /capitulos/{id}`, ao abrir o capítulo.

**A ideia que organiza tudo: separar o que muda do que não muda.**

| Tipo | Exemplos | Regra |
|---|---|---|
| **Imutável e volumoso** | texto do capítulo; arquivo de imagem | Pode ser guardado no aparelho **sem risco de conflito**: o conteúdo não muda depois de importado (`PATCH /capitulos` só altera título e `ignorado`; o arquivo de imagem tem nome único e nunca é sobrescrito) |
| **Mutável e pequeno** | arquivar, metadados, elementos, frames, prompts, sugestões | **Continua mandando o servidor**; o aparelho só guarda a última cópia vista |

**Decisões do Allan (30/09/2026):**
1. **Offline é só de leitura.** Não se escreve offline: nada de fila de alterações nem resolução de conflito entre aparelhos — é isso que torna a sincronização cara. As ações de IA (analisar, gerar prompt, importar imagem) precisam do servidor de qualquer jeito.
2. **O índice local é um banco simples (Room)**, e o texto e as imagens ficam em **arquivos** privados do app. Isto **reverte** a regra "sem Room" do item 7.0 e do `CLAUDE.md` do app.
3. **Dois níveis**, como o YouTube ou o Spotify (ver abaixo).
4. **Contas de usuário ficam para depois**, com as quatro preparações abaixo.
5. **A rota do livro devolve só os capítulos e seus metadados**, sem o conteúdo — o que, como visto, **já é o caso**; o conteúdo vem só ao abrir o capítulo.

**Os dois níveis** (proposta do Allan, refinada):

| | **Leve — automático** | **Baixado — pedido pelo usuário** |
|---|---|---|
| Quando | Ao entrar no livro e ao ler | Botão **"Baixar para ler offline"**, por livro |
| O que guarda | Lista de capítulos e metadados; o **texto** do que se lê (e o do próximo capítulo, antes de o usuário chegar lá); as **miniaturas** das imagens vistas | **Tudo**: o texto de todos os capítulos e **todas as imagens em tamanho real** |
| Garantia | **Melhor esforço**: pode ser limpo para liberar espaço | **Garantido**: só sai quando o usuário remove |
| Custo em disco | Pequeno (texto de um livro: ~0,7 MB) | Grande (as imagens; pode passar de 100 MB por livro) |

**Regras (A1 a A15).**
- **A1 — Abrir um livro é instantâneo.** Mostra na hora o que já está no aparelho e **revalida em segundo plano** pela revisão do livro (item 6.9). Sem conexão, usa o que tem; sem nada local e sem conexão, diz que precisa de conexão. *(Isto atende à sugestão do Allan de baixar o mínimo ao entrar no livro: só a lista de capítulos e metadados, nunca o conteúdo.)*
- **A2 — Abrir um capítulo: primeiro o aparelho.** Se o texto está no aparelho, abre **sem rede**; senão baixa, guarda e abre. Ao abrir o capítulo N, o app **baixa o N+1 em segundo plano** — o leitor nunca espera na virada de página.
- **A3 — Imagens: sempre pelo repositório local.** As telas pedem a imagem a um repositório que devolve um **arquivo local**, baixando só se faltar: **miniatura primeiro; o tamanho real só ao ampliar** (ou se o livro estiver "Baixado"). Esta regra precisa valer **desde o primeiro pixel** da exibição de imagens (incremento 12): se a imagem nascer buscando direto da rede, ela teria de ser refeita quando o offline chegar.
- **A4 — "Baixar para ler offline"** baixa o texto de **todos** os capítulos e **todas as imagens em tamanho real**. **Antes de começar, mostra o tamanho total** ("Baixar — 240 MB"), calculado pelo manifesto de mídias (item 6.9), e por padrão **só em Wi-Fi**. Tem progresso, pode ser **pausado e cancelado**, e **retoma** de onde parou. O livro fica marcado como **"Baixado"**, com a data.
- **A5 — Cada arquivo é gravado inteiro ou não é gravado.** Um download interrompido nunca deixa um arquivo pela metade que pareça pronto.
- **A6 — Livro "Baixado" continua baixado.** Se o servidor ganhar imagens novas, elas entram na fila e são baixadas quando houver conexão (em Wi-Fi).
- **A7 — Sem conexão, só se lê.** Ficam **indisponíveis**, com um aviso claro de "sem conexão": arquivar/restaurar, editar o livro, o perfil padrão, apagar, importar, e todo o painel de IA (analisar, gerar prompt, importar imagem). O app mostra um **indicador de que está offline**, e o que depende do servidor não finge que funcionou.
- **A8 — Revisão.** Se a revisão do livro mudou, relê **só** a lista de capítulos e os metadados. O texto e as imagens **não precisam de revalidação**: os ids deles são imutáveis.
- **A9 — Livro apagado no servidor.** Ao revalidar, se o livro não existe mais (404), o app **oferece** apagar a cópia local — **nunca apaga sozinho**.
- **A10 — A cópia local é descartável.** O servidor guarda tudo; o que está no aparelho pode ser apagado e baixado de novo sem perda. Por isso, se o índice local corromper ou mudar de formato entre versões do app, a resposta é **apagar e reconstruir**, e não escrever migrações delicadas.
- **A11 — Espaço sob controle.** Uma tela mostra, **por livro**, quanto está no nível Leve e quanto está Baixado, com "Limpar cache" (só o Leve) e "Remover download" (só o Baixado). O nível Leve tem uma **cota** e é limpo do mais antigo para o mais novo; o Baixado nunca é limpo sozinho.
- **A12 — Fora do backup automático do Android.** Hoje o app permite backup (`allowBackup`); centenas de MB de imagens não podem ir para a nuvem do Google. Os arquivos de texto e imagem entram na regra de exclusão.
- **A13 — Arquivos privados do app**, inacessíveis a outros aplicativos.
- **A14 — Importar uma imagem já deixa uma cópia local.** O arquivo que o usuário escolheu na galeria já está no aparelho: depois do envio, o app o guarda como cópia local em vez de baixá-lo de volta.
- **A15 — Nada aqui altera o que o servidor guarda.**

**Preparação para contas de usuário** (decisão: contas ficam para depois; estas quatro são baratas agora e evitam refazer depois):
- **a) A chave do cache inclui o servidor e a conta.** Hoje a conta é sempre a mesma; o espaço para ela já existe, então um segundo usuário nunca enxerga os livros do primeiro.
- **b) As imagens são carregadas pelo cliente HTTP do app**, e não por um endereço solto: uma imagem atrás de login só abre se a requisição levar a credencial. O carregador de imagens usa o mesmo `OkHttpClient` do app.
- **c) As telas novas não assumem que o usuário é único.**
- **d) Os perfis de renderização hoje são compartilhados entre livros**; com contas, será preciso decidir de quem eles são. Fica registrado para essa época.

**Riscos e como ficam mitigados.**

| Risco | Mitigação |
|---|---|
| Cache desatualizado | Revisão por livro (A8); texto e imagem têm id imutável |
| Disco cheio | Tamanho por livro e cota do nível Leve (A11) |
| Download interrompido | Arquivo inteiro ou nada, e retomada (A4, A5) |
| Livro apagado no servidor | Conferir ao abrir e oferecer apagar a cópia (A9) |
| Índice local corrompido ou de formato antigo | A cópia é descartável (A10) |
| Backup automático inchado | Exclusão dos arquivos (A12) |
| Dois aparelhos importando imagem ao mesmo tempo | Sem conflito: cada importação cria uma imagem nova |

**Ordem de entrega e tamanho relativo** (não são estimativas de tempo; "incremento" é o tamanho dos que já fizemos). Os incrementos 10 e 11 do capítulo ilustrado **não dependem** desta seção e podem seguir em paralelo.
1. **Servidor (contrato do item 6.9)**: compressão; imagens com cache imutável, tamanhos nomeados e `tamanho_em_bytes`; manifesto de mídias; textos do livro numa chamada; revisão do livro. *Pequeno a médio.*
2. **App — índice Room e texto no aparelho**, atrás do repositório de capítulos que já existe, **sem mexer nas telas** (A1, A2, A8, A10). *Médio.* Já entrega a abertura **instantânea** do capítulo.
3. **App — imagens pelo repositório local** (A3), **junto do incremento 12**. *Médio.*
4. **App — "Baixar para ler offline"**, tamanho em disco e indicador de "sem conexão" (A4 a A7, A9, A11, A12). *Médio a grande.*
5. **Contas de usuário.** *Grande, no backend; pequeno no app.* Depois.

**Fora do escopo:** escrever offline (fila e conflito); contas (só a preparação); **posição de leitura sincronizada entre aparelhos** (como o Kindle faz — é um campo pequeno e aditivo, que cabe depois); geração de imagem pelo app.

#### Passo 1 do app em detalhe — índice Room e texto no aparelho (especificado em 30/09/2026)

**O que este passo entrega:** ler um capítulo já visto **sem rede**, abrir o capítulo seguinte **sem espera** e abrir um livro já visto **sem conexão**. **Nenhuma tela muda**: tudo acontece dentro dos repositórios que já existem (`RepositorioDeLivros.abrirLivro` e `RepositorioDeCapitulos.abrirCapitulo`), que passam a consultar o aparelho antes da rede. Os ViewModels e as telas continuam chamando as mesmas funções.

**Divergência consciente do plano (A1).** A regra A1 diz "mostra na hora e revalida em segundo plano". Isso exige que a tela receba **duas respostas** (a local, depois a do servidor), ou seja, **mexer no `LivroViewModel`** — e este passo prometeu não mexer nas telas. Então, aqui, `abrirLivro` faz uma **revalidação condicional**: manda ao servidor a revisão que tem (`If-None-Match`); se nada mudou, o servidor responde `304` **sem corpo** (poucos bytes) e o app entrega a cópia local; sem conexão, entrega a cópia local também. **Sem conexão e sem cópia**, dá a falha de sempre. A abertura *instantânea* de verdade (mostrar a cópia e atualizar por cima) fica para o passo que tocar o `LivroViewModel`, junto do indicador "sem conexão" (A7).

**Onde cada coisa mora:**

| O quê | Onde | Por quê |
|---|---|---|
| Livro visto: revisão, a lista de capítulos e os metadados | **Room**, tabela `livro_local` (chave, id do livro, revisão, o `LivroDetalhe` em JSON, quando foi guardado) | É o índice: pequeno, consultável, e saber a revisão é o que permite o `304` |
| Quais capítulos têm texto no aparelho | **Room**, tabela `texto_local` (chave, id do capítulo, id do livro, tamanho em bytes, quando foi guardado) | Base para A11 (tamanho por livro) e para a cota do nível Leve, sem varrer pastas |
| O texto do capítulo | **Arquivo** `…/imagineer/<pasta-da-chave>/livro-<id>/capitulo-<id>.txt`, no armazenamento privado do app, UTF-8 | Texto de ~100 KB não pertence a um banco; arquivo é simples de medir e apagar |

O JSON do livro em `livro_local` é **de propósito**: a lista de capítulos é sempre lida e gravada **inteira**, nunca consultada por campo; colunas para cada campo só dariam trabalho quando a API ganhar campos novos (`ignoreUnknownKeys` e valores padrão já toleram o formato crescer).

**A chave do cache (preparação "a" para contas).** `servidor + conta`, hoje `conta = "unica"`. A chave vira o prefixo de todas as linhas e o nome da pasta (um *hash* curto dela, porque a URL tem caracteres que não servem em nome de pasta). Trocar o endereço do servidor no app **não mistura** livros de dois servidores: o livro 3 de um não é o livro 3 do outro.

**Regras deste passo (L1 a L9).**
- **L1 — Abrir capítulo: aparelho primeiro.** Se a linha de `texto_local` **e** o arquivo existem, e o livro do capítulo está em `livro_local`, o capítulo sai **do aparelho, sem rede**: o `CapituloDetalhe` é montado com os metadados do livro guardado (título, arquivado, tamanho, sugestões pendentes, ordem) e o texto do arquivo. Se faltar qualquer uma das três peças, **vai à rede** como hoje.
- **L2 — Baixou, guardou.** Capítulo vindo da rede é gravado (texto no arquivo + linha no índice) **antes de ser entregue**. Falhou ao gravar (disco cheio, por exemplo)? O capítulo **é entregue mesmo assim**: guardar é cortesia, nunca pode impedir a leitura.
- **L3 — Gravação inteira ou nenhuma (A5).** O texto é escrito num arquivo temporário e **renomeado** ao final; a linha do índice só é criada depois. Um arquivo sem linha, ou uma linha sem arquivo, vale como "não tenho".
- **L4 — Adiantar o seguinte.** Ao entregar o capítulo N, o app **baixa em segundo plano** o próximo capítulo **não arquivado** do mesmo livro (pela ordem do livro guardado), se ainda não o tem. **Melhor esforço**: sem rede ou com erro, ignora em silêncio; não bloqueia nem avisa a tela; só um adiantamento por vez.
- **L5 — Abrir livro: revalidação condicional (A1, A8).** Com cópia local: pede ao servidor com `If-None-Match: "<revisão>"`. `304` → cópia local. `200` → **substitui** a cópia (novo JSON, nova revisão) e entrega a nova. Falha de **conexão** → cópia local. Falha **com resposta do servidor** (404, 500…) → a falha, e um `404` **não apaga** nada sozinho (A9 fica para o passo 4). Sem cópia: pede sem o cabeçalho e guarda o resultado.
- **L6 — O que muda o livro invalida a cópia por construção.** Como a revisão sobe no servidor a cada mudança visível, a próxima abertura recebe `200`. Por isso `ajustarLivro`, `ajustarCapitulo` e a importação **não precisam** tocar na cópia. Única exceção: **`removerLivro`** (sucesso ou `404`) **apaga a cópia local** do livro — índice e arquivos —, porque o livro deixou de existir.
- **L7 — Só o texto é imutável.** O texto do capítulo **nunca é revalidado** (A8): o id é o mesmo, o conteúdo também. Metadados (título, arquivado, sugestões pendentes) vêm da lista do livro, revalidada em L5.
- **L8 — A cópia é descartável (A10).** Índice ilegível, JSON que não desserializa ou arquivo que sumiu: **trata como ausente** e refaz da rede. Mudança de formato do banco entre versões do app: o Room **apaga e recria** (`fallbackToDestructiveMigration`), sem migração escrita à mão.
- **L9 — Fora do backup do Android (A12).** O texto pode ser baixado de novo; não deve ir para a nuvem do Google. Nada aparece na tela; é configuração.

**Implementado em 30/09/2026 (app: 338 testes, 32 deles novos; ainda a validar no tablet).** Em linguagem simples: o app agora tem uma "gaveta" no próprio aparelho. Ao abrir um livro, guarda a lista de capítulos; ao ler um capítulo, guarda o texto; ao abrir o capítulo N, baixa o N+1 por conta própria. Da segunda vez, o capítulo abre sem nenhum pedido ao servidor, e o livro se confirma com uma pergunta de poucos bytes ("mudou desde a revisão 7?" — "não").

**Divergências do plano, e o motivo:**
- **L9 ficou mais simples do que o escrito.** Em vez de editar `backup_rules.xml` e `data_extraction_rules.xml`, o banco e os textos moram em `noBackupFilesDir`, a pasta que o Android **nunca** inclui no backup. Não há regra para esquecer de atualizar, e vale também para o que for criado ali no futuro (as imagens do passo 3).
- **A lista de capítulos de um capítulo aberto do aparelho vem do livro guardado**, como previsto em L1; por isso `sugestoes_pendentes` e `ignorado` mostram o valor da última vez que o livro foi aberto. Como a tela do livro sempre vem antes e revalida (L5), na prática o valor está atual.
- **Consultas ao índice são `suspend` e rodam no executor do Room**; os arquivos rodam em `Dispatchers.IO`. Nenhum ViewModel mudou.

**Onde está o código (app, pacote `local/`):** `ChaveDoCache` (servidor+conta), `IndiceLocal` (interface) e `IndiceLocalPeloRoom`/`BancoLocal` (tabelas `livro_local` e `texto_local`), `ArmazemDeTextos` (interface) e `ArmazemDeTextosEmArquivos`, `melhorEsforco` (a regra "falha local = não tenho"). As regras L1 a L7 vivem em `RepositorioDeCapitulosPeloRetrofit` e `RepositorioDeLivrosPeloRetrofit`. `ProvedorDeApi.emUso()` entrega a API e a chave juntas. `LivroDetalhe` ganhou `revisao`; `ApiImagineer.livroSeMudou` manda o `If-None-Match`.

**Fora deste passo (e onde entra):** lista de livros da Biblioteca offline e abertura instantânea com atualização por cima (passo que tocar os ViewModels, junto do indicador "sem conexão", A7); cota e limpeza do nível Leve e tela de espaço (A11, passo 4); imagens (A3, passo 3); "Baixar para ler offline" (A4, passo 4). **O texto guardado pelo nível Leve não tem cota neste passo**: ~0,7 MB por livro não justifica a complexidade agora; a cota chega com a tela de espaço.

**Como se testa.** A parte que conversa com o banco e com o disco fica atrás de **interfaces** (`IndiceLocal`, `ArmazemDeTextos`), com **versões em memória** para os testes de unidade: a regra de quando ir à rede, quando usar o aparelho e quando adiantar o seguinte é testada sem aparelho. O `304` é testado com o MockWebServer, que já existe no projeto. A versão Room e a de arquivos são exercitadas no **tablet** (roteiro manual).

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
- **Mostra**: título, autor, quantos capítulos ativos e quantos estão arquivados, por livro (`LivroResumo`; "arquivado" é o nome que a tela dá ao `ignorado` da API — ver 7.5a, revisão do incremento 6).
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

### 7.3a Bloco A em detalhe — Biblioteca, Importação e Configuração mínima

Aprofundamento do item 7.0 antes do primeiro código Kotlin. É o **primeiro bloco a ser implementado**, e de propósito inclui uma versão mínima da Configuração (7.10): sem o endereço do servidor, nenhuma outra tela consegue chamar a API.

#### Ordem de implementação (incrementos pequenos, cada um roda no celular)

1. **Esqueleto:** projeto Compose vazio, `MaterialTheme`, navegação com os destinos tipados de 7.0 (telas ainda em branco). Critério: abre no tablet. **Implementado:** `navegacao/Destinos.kt` (os oito destinos), `navegacao/GrafoDeNavegacao.kt` e `telas/TelaProvisoria.kt` (uma tela de mentira reutilizável, com botões que provam a navegação, limitada a 600 dp de largura). Compila e o teste de unidade padrão passa; o critério (abrir e navegar no tablet) é verificação manual.
2. **Configuração mínima:** tela para digitar e salvar a URL do servidor (DataStore). Critério: fechar e reabrir o app mantém a URL. **Implementado** (decisões no bloco "Incremento 2 em detalhe", abaixo): `dados/NormalizarUrl.kt`, `dados/ArmazenamentoDeConfiguracao.kt` (interface + DataStore), `rede/ApiImagineer.kt` (Retrofit, só `GET /configuracao`), `rede/ServidorImagineer.kt` (o teste de conexão, com as três falhas), `telas/configuracao/` (ViewModel + tela) e `ImagineerApp` (injeção manual). 21 testes de unidade na JVM: normalização (9), desserialização com JSON real do backend (2) e ViewModel com armazenamento/servidor falsos (10, incluindo a corrida "resultado de teste antigo não sobrescreve o texto novo"). Falta a verificação manual no tablet, contra o servidor de verdade.
3. **Camada de rede:** Retrofit + `kotlinx.serialization`, com `GET /livros`. Critério: a Biblioteca mostra os livros reais do Raspberry Pi/PC. (Retrofit já entrou no incremento 2; aqui entram a rota de livros, o repositório e a tela — decisões em "Incremento 3 em detalhe".) **Implementado:** `rede/ResultadoDaChamada.kt` (`chamarApi`, a tradução de falhas), `rede/LivroResumo.kt`, `rede/RepositorioDeLivros.kt`, `telas/biblioteca/` (ViewModel com os quatro estados + tela com pull-to-refresh e recarga em `ON_RESUME`). 39 testes de unidade no total no app (18 novos: JSON real de `/livros`, as três falhas, os estados da Biblioteca, a corrida entre duas recargas e o texto dos cartões). Falta a verificação manual no tablet.
4. **Biblioteca completa:** estados de vazio, carregando e erro (abaixo). **Divisão real entre 3 e 4:** como os quatro estados e o pull-to-refresh nascem juntos com a lista (não faz sentido chamar a API sem tratar o erro), o incremento 3 já os entrega; o incremento 4 fica com o que sobrou — **Remover livro** (`DELETE /livros/{id}`, com confirmação) e o acesso aos Perfis de renderização. **Incremento 4 implementado** (decisões em "Incremento 4 em detalhe"): `DELETE /livros/{id}` na `ApiImagineer`, `removerLivro` + `interpretarRemocao` (o 404 conta como sucesso) no repositório, `EstadoDaRemocao` (4 estados do diálogo) no ViewModel, menu ⋮ e diálogo na tela, botão "Perfis" na barra. 11 testes novos (50 no total no app). Falta a verificação manual no tablet.
5. **Importar:** seletor de arquivo, upload com progresso, aviso de `livros_semelhantes`, formulário de `metadados_pendentes`. Decisões e o que se descobriu no backend em "Incremento 5 em detalhe". **Implementado:** `rede/LivroDetalhe.kt` (`LivroDetalhe`, `CapituloResumo`, `RespostaImportacao`, `LivroAjuste`), `rede/DetalheDoErro.kt` (a mensagem da API vira a do app), `rede/CorpoComProgresso.kt` (upload em fluxo, uso único), `dados/LeitorDeArquivos.kt`, `RepositorioDeLivros` com `importarLivro`/`ajustarLivro`/`abrirLivro`, `telas/importacao/` (`ImportacaoViewModel` com 5 estados + diálogos) e o botão Importar na Biblioteca. **113 testes de unidade no app** (63 novos neste incremento), inclusive um `MockWebServer` que atravessa a pilha de rede inteira e confere o formato do multipart (campo `arquivo`, nome do arquivo, bytes íntegros), o corpo do `PATCH` e os códigos HTTP. Falta a verificação manual no tablet.

#### Contratos da API que o Bloco A usa

| Chamada | Usada em | Classe Kotlin (`@Serializable`) |
|---|---|---|
| `GET /livros` | Biblioteca | `LivroResumo` — `id`, `titulo`, `autor?`, `idioma?`, `nome_arquivo`, `data_importacao`, `total_de_capitulos`, `capitulos_ignorados` |
| `POST /livros` (multipart, campo `arquivo`) | Importar | `RespostaImportacao` — `livro: LivroDetalhe`, `livros_semelhantes: List<LivroResumo>` |
| `PATCH /livros/{id}` | Formulário de metadados | corpo `LivroAjuste` (só `titulo`/`autor` aqui), resposta `LivroDetalhe` |
| `DELETE /livros/{id}` | Remover livro (menu do item da lista) | 204, sem corpo |

Os nomes dos campos no JSON são os do backend, em português — as classes Kotlin usam **os mesmos nomes**, sem `@SerialName` de tradução, para o espelhamento ser óbvio. Campos opcionais do backend (`str | None`) viram `String? = null` no Kotlin.

#### Biblioteca (7.2) — estados

A tela é uma função do estado do `ViewModel`, um de quatro:

| Estado | O que a tela mostra |
|---|---|
| **Carregando** | Indicador de progresso centralizado |
| **Lista** | Um cartão por livro: título, autor (ou "Autor desconhecido"), "N capítulos" e, só se `capitulos_ignorados > 0`, "M ignorados". Ordem: a do servidor, **alfabética por título** (item 6.2) — o app não reordena; a versão anterior desta especificação dizia "mais recente primeiro", divergência corrigida por ser lógica duplicada sem ganho claro. Tocar abre o Livro. O menu de três pontos do cartão oferece **Remover**, com confirmação — apaga o livro e tudo que depende dele |
| **Vazio** | Convite a importar o primeiro livro. Não é erro |
| **Erro** | "Não consegui falar com o servidor", o motivo curto e o botão **Tentar de novo**. Vale para timeout, sem conexão, Pi desligado, Tailscale desconectado (item 7.0) |

Puxar para atualizar (`pull-to-refresh`) refaz o `GET /livros`. Como o app não cacheia nada (item 7.0), a lista é sempre recarregada ao voltar para a tela.

**Sem URL configurada** (primeira abertura): a Biblioteca nem chama a API; abre direto a Configuração mínima, com uma frase explicando o que colocar ali.

#### Importar (7.3) — sequência

1. Botão flutuante → seletor de arquivo do sistema (`ActivityResultContracts.OpenDocument`, filtro `application/epub+zip`).
2. Upload multipart, com barra de progresso. O app **lê o arquivo em fluxo** (não carrega os até 46 MB inteiros na memória) e não tem cancelamento na v1.
3. Resposta 201:
   - `livros_semelhantes` não vazio → diálogo "Já existe um livro parecido": **Abrir o existente** ou **Seguir mesmo assim**. Aviso, nunca bloqueio (item 3.4a). Nota: o livro novo **já foi gravado** no servidor; "abrir o existente" não o desfaz — oferecer **Remover o novo** nesse diálogo, para não deixar duplicata sem querer.
   - `metadados_pendentes` não vazio → formulário obrigatório de título/autor, pré-preenchido; **Salvar** chama `PATCH /livros/{id}`; só com a lista vazia a importação termina e o app navega para o Livro (substituindo o estado de importação, sem empilhar — item 7.0).
4. Erros: 422 mostra a mensagem que a API devolve; 413 diz que o arquivo passa de 60 MB; falha de rede cai no mesmo estado de erro da Biblioteca. **Se a rede cair no meio do upload**, o app não sabe se o servidor chegou a gravar: ao "tentar de novo" ele **recarrega a lista antes** e só reenvia se o livro não apareceu, para não duplicar em silêncio.

#### Configuração mínima (7.10, parte 1)

- **Um campo:** URL base do servidor (ex.: `http://100.x.y.z:8000`, endereço Tailscale). Botão **Testar** faz `GET /configuracao` e mostra "conectado" ou o erro. Só salva se o teste passar, ou se o usuário confirmar salvar mesmo assim.
- **Normalização:** aceita com ou sem `http://` e com ou sem barra final; sem esquema, assume `http://`.
- A chave de API pessoal e a escolha de modelos entram no Bloco E (7.10 completa) — a rota existe, mas nada no Bloco A precisa de IA.

#### Incremento 2 em detalhe — decisões

- **Retrofit entra já aqui, e não no incremento 3.** O botão "Testar" precisa chamar `GET /configuracao`, e escrever essa chamada com outra biblioteca para depois jogá-la fora seria trabalho perdido. O incremento 2 cria a interface `ApiImagineer` com **uma** rota (`GET /configuracao`); o incremento 3 só acrescenta as rotas de livros a ela.
- **A URL base é dinâmica**, então o cliente Retrofit não é um objeto único criado na inicialização: uma função `criarApi(urlBase)` monta o cliente a partir da URL salva (ou digitada, no caso do "Testar", que precisa testar **antes** de salvar). O Retrofit exige que a URL base termine em `/`; o app guarda **sem** a barra final e acrescenta na hora de montar o cliente.
- **`Json { ignoreUnknownKeys = true }`.** O backend pode ganhar campos novos sem que o app precise ser reinstalado na mesma hora; ignorar o que o app não conhece evita quebrar por isso. O contrário (campo que o app espera e o servidor não manda) continua sendo erro.
- **Normalização da URL** (função pura, testável na JVM): apara espaços; sem esquema (`://`), assume `http://`; só aceita `http` e `https`; remove barras finais; recusa texto vazio, esquema diferente ou endereço sem host. Devolve `null` quando inválida.
- **Resultado do teste** distingue três falhas, porque o conserto de cada uma é diferente: (1) **não chegou ao servidor** (`IOException`: timeout, sem conexão, Tailscale desligado) → "não consegui falar com o servidor"; (2) **chegou, mas respondeu erro HTTP** → "o servidor respondeu N"; (3) **chegou, mas a resposta não é a do Imagineer** (JSON que não bate, ou página HTML de outro serviço) → "esse endereço responde, mas não parece o servidor do Imagineer". Sucesso mostra "Conectado" e se o servidor tem chave de API própria (`tem_chave_api`).
- **Salvar:** com o teste bem-sucedido para o **texto atual**, "Salvar" fica disponível. Mudar o texto invalida o teste. Se o teste falhou, aparece **"Salvar mesmo assim"** — útil quando o Pi está desligado agora, mas o endereço está certo.
- **Depois de salvar, o app volta para a Biblioteca limpando a pilha.** Trocar o servidor invalida tudo o que estava aberto (ids de livros de outro servidor não significam nada no novo), então não faz sentido voltar para a tela anterior.
- **Primeira abertura:** se não há URL salva, o app abre direto na Configuração (em vez de na Biblioteca), sem botão de voltar. A leitura do DataStore é assíncrona; até ela terminar, a tela fica vazia — em vez de piscar a Biblioteca e pular para a Configuração.
- **`network_security_config`:** HTTP em texto puro liberado para todos os endereços, e não só para um domínio. O motivo é que o endereço Tailscale é um IP (`100.x.y.z`) e o mecanismo do Android só sabe liberar por nome de domínio ou IP exato — como o IP muda de instalação para instalação, não dá para fixá-lo no APK. Aceitável porque o tráfego vai dentro do túnel criptografado do Tailscale (item 7.0) e o APK é de uso pessoal. Se o app um dia for distribuído a outras pessoas, isto precisa ser reavaliado.

#### Incremento 3 em detalhe — decisões

- **Um repositório por assunto, como interface.** `RepositorioDeLivros` (a Biblioteca, e mais tarde o Livro) fica entre o ViewModel e o Retrofit, com uma implementação de verdade e uma falsa para teste — mesma ideia de `ServidorImagineer` (incremento 2). O ViewModel nunca vê `HttpException` nem `IOException`: recebe um `ResultadoDaChamada` (`Sucesso(dado)` ou `Falha(motivo)`), com o motivo **já escrito para o usuário**.
- **A tradução de falha é uma função só**, compartilhada com o teste de conexão do incremento 2 (o mesmo `IOException`/`HttpException`/`SerializationException`, as mesmas três mensagens). Duplicar isso em cada repositório faria as telas divergirem na hora de dizer "não consegui falar com o servidor".
- **O cliente Retrofit é reaproveitado enquanto a URL não muda.** Montar um `OkHttpClient` a cada chamada joga fora o pool de conexões; o repositório guarda o último par (URL, API) e só remonta se a URL salva mudou.
- **Erro é tratado tela a tela, não por um mecanismo global.** Cada tela tem o seu estado de erro com "Tentar de novo". Coerente com "sem cache, sem modo offline" (item 7.0): não há um estado "offline" do app para anunciar — cada chamada simplesmente dá certo ou falha, e a tela que a fez sabe o que mostrar.
- **A Biblioteca recarrega toda vez que volta a ficar visível** (`ON_RESUME`), e não só na primeira abertura: é o que garante ver o livro que acabou de ser importado, ou removido, sem ação do usuário. Se já há lista na tela, a recarga é silenciosa (a lista antiga fica visível com o indicador de atualização); se falhar, cai no estado de erro.
- **`data_importacao` fica como texto ISO no app por enquanto** (`"2026-09-30T01:11:16"`): nenhuma tela do Bloco A a exibe, e converter para data sem uso seria trabalho especulativo.
- **Acesso à Configuração:** ícone de engrenagem na barra superior da Biblioteca (item 7.1, "qualquer tela → engrenagem"). Os botões provisórios de navegação da Biblioteca deixam de existir; o acesso a Livro passa a vir de tocar num livro real.

#### Incremento 4 em detalhe — Remover livro e acesso aos Perfis

- **Ativação: menu de três pontos (⋮) em cada cartão**, com a opção "Remover". Escolhido em vez de toque longo porque é visível — quem não conhece o gesto não o descobre — e difícil de acionar sem querer com o dedo num tablet. (A versão anterior do item 7.3a dizia "segurar ou menu"; fica só o menu.)
- **Confirmação por diálogo simples**, com o título do livro: *"Remover "A Guerra dos Tronos"? Isto apaga também os capítulos, elementos, frames, prompts e imagens deste livro. Não dá para desfazer."* com **Cancelar** e **Remover**. Descartado: exigir digitar o título — protege mais, mas cansa numa ação que se repete ao testar, e o uso é pessoal.
- **O que a rota apaga** (`DELETE /livros/{id}`, 204): o livro e tudo que depende dele (item 6.2). O aviso do diálogo lista isso de propósito: "remover um livro" soa menos grave do que apagar todo o catálogo visual que ele acumulou.
- **Estados do diálogo**, um de quatro: sem diálogo · **confirmando** · **removendo** (botões desabilitados, indicador de progresso — impede o duplo toque de disparar dois `DELETE`) · **falhou** (mostra o motivo, com "Tentar de novo" e "Fechar"). O diálogo **não fecha sozinho** quando a remoção falha, para o usuário ver por quê.
- **Depois de remover, a lista é recarregada** (o mesmo `carregar()` da Biblioteca): se era o último livro, cai no estado Vazia.
- **`404` na remoção conta como sucesso.** O objetivo do usuário é "este livro não existir mais"; se o servidor diz que ele já não existe (removido de outro lugar, por exemplo pelo `/docs`), o objetivo está cumprido, e mostrar erro seria só ruído. Para isso, `ResultadoDaChamada.Falha` ganha o campo opcional `codigoHttp` (nulo para falhas de conexão) — decisão de tratar o 404 fica numa função pura, testável, e não espalhada na tela.
- **Acesso aos Perfis de renderização:** um botão de texto "Perfis" na barra superior da Biblioteca, ao lado da engrenagem. Texto em vez de ícone porque o conjunto básico de ícones do Material (`material-icons-core`, item 7.3a) não tem um ícone apropriado, e o conjunto completo (`extended`) pesa dezenas de megabytes de dependência por um só desenho. A tela de destino continua provisória até o Bloco E.

#### Incremento 5 em detalhe — Importar livro

O maior incremento do Bloco A. Refina a sequência de "Importar (7.3)" acima com o que se descobriu lendo o backend.

**Estrutura.** A importação tem um ViewModel próprio (`ImportacaoViewModel`), separado do da Biblioteca, que já cuida de lista e remoção. É uma camada por cima da tela, como o diálogo de remoção: a lista continua visível atrás. O estado é um de cinco: **Nenhuma** · **Enviando** (nome, bytes enviados, total) · **Semelhantes** (livro novo + os já existentes) · **MetadadosPendentes** (livro novo, erro inline opcional) · **Falhou** (motivo; com o arquivo, se dá para tentar de novo). Ao terminar, o ViewModel emite "ir para o Livro N" como evento de uso único, e a Biblioteca navega.

**Ordem das verificações depois do `201`:** (1) `livros_semelhantes` não vazio → diálogo de semelhantes; (2) `metadados_pendentes` não vazio → formulário; (3) senão, concluído. Semelhantes vem primeiro porque é a decisão mais barata de tomar — e se o usuário resolver remover o livro novo ali, não precisa nem preencher o formulário.

**Ler o arquivo em fluxo, com progresso.**
- O corpo do upload lê o `InputStream` do arquivo escolhido aos poucos, e **reporta o progresso** em bytes. O total vem de `OpenableColumns.SIZE` do provedor de arquivos; se o provedor não informa, o progresso fica indeterminado (sem porcentagem).
- **O corpo é de uso único** (`isOneShot`): o fluxo do arquivo só pode ser lido uma vez, então o OkHttp **não pode** reenviar sozinho depois de uma falha de conexão — sem isso ele tentaria reenviar um fluxo já consumido e mandaria um arquivo truncado sem avisar.
- O relatório de progresso é **limitado** (só quando avança ao menos 1% ou 256 KB), para 46 MB não virarem milhares de atualizações de tela.
- Quando os bytes enviados chegam ao total, a tela troca a barra por "Processando no servidor…": o servidor ainda extrai e grava os capítulos (0,03–0,33 s, mas visível).
- O arquivo é aberto **antes** do pedido, e uma falha ao abri-lo (permissão perdida, arquivo movido) vira a mensagem "Não consegui abrir o arquivo escolhido" — e não a falha de rede genérica, que seria enganosa.
- `writeTimeout` de 60 s no cliente HTTP (o padrão de 10 s por escrita é curto para uma conexão lenta).

**Validações locais, antes de subir qualquer byte:** a extensão precisa ser `.epub` (o filtro do seletor é só uma sugestão), e o tamanho, quando conhecido, não pode passar de **60 MB** — a mensagem é a mesma do servidor ("O arquivo passa do limite de 60 MB."), mas sem gastar 60 MB de upload para descobrir. O seletor aceita `application/epub+zip` **e** `application/octet-stream`: alguns gerenciadores de arquivos classificam EPUB como genérico, e com o filtro estrito o arquivo apareceria acinzentado.

**A mensagem de erro vem da API.** O backend devolve `{"detail": "..."}` em 404/413/422 (verificado). O app passa a mostrar esse texto em vez de "O servidor respondeu com erro 422." — para toda tela, não só a importação (`chamarApi`). Se o corpo não tem `detail` em texto (o `detail` de um erro de validação do FastAPI é uma lista; um `500` pode vir como texto puro), volta à mensagem genérica com o código.

**Diálogo de semelhantes** ("Já existe um livro parecido"): lista o(s) título(s) existente(s) e oferece **Seguir mesmo assim**, **Abrir o existente** (o primeiro da lista) e **Remover o novo**. O livro novo já foi gravado; sem o "Remover o novo" a duplicata ficaria no servidor mesmo para quem só quis olhar o antigo. Falha ao remover mostra o erro no próprio diálogo.

**Formulário de metadados, só com os campos pendentes.** Se só falta o autor, só o autor aparece. Regras que vêm do backend (`PATCH /livros/{id}`, verificado):
- Mandar `titulo` **confirma** o título — mesmo com o valor igual ao que já estava lá. Por isso o campo vem pré-preenchido com o que a extração achou (o nome do arquivo, no fallback) e basta tocar em Salvar para confirmar.
- Um `autor` vazio (`""`) **não é** nulo para o backend: seria gravado e o autor deixaria de contar como pendente **sem existir**. O app **bloqueia campo vazio** e nunca manda texto em branco.
- O corpo do `PATCH` leva **só** os campos pendentes (campos nulos por padrão são omitidos do JSON).
- Se, depois do `PATCH`, `metadados_pendentes` ainda não está vazio, o formulário continua aberto com um aviso do que falta.
- O formulário **não tem "Cancelar"**: título e autor são mandatórios (item 7.3). Mas para não prender o usuário num livro que ele não quer, há um botão **Remover livro** (mesma rota do diálogo de semelhantes).

**Rede cai no meio do upload.** O app não sabe se o servidor chegou a gravar. Antes do **primeiro** envio, o ViewModel guarda os ids dos livros que existiam (`GET /livros`; se essa chamada falha, o servidor está fora e não há o que verificar). Em "Tentar de novo", ele **relista antes de reenviar**: se apareceu um livro **novo** (id que não estava no retrato) com o mesmo `nome_arquivo`, o upload tinha funcionado — o app busca o detalhe (`GET /livros/{id}`) e segue a partir dali, sem reenviar. Só se não apareceu é que reenvia. Sem isso, um Wi-Fi que oscila duplicaria o livro em silêncio. (Um livro novo sem `livros_semelhantes` nesse caminho: o app não tem como reconstruir esse aviso, e aceita a perda.)

**Sem cancelamento na v1**, como já dito acima: a barra não tem botão de cancelar, e o diálogo de envio não fecha por toque fora ou botão voltar. O pior caso é um upload lento até o `writeTimeout`.

**Botão "Importar"** (`ExtendedFloatingActionButton`) na Biblioteca, visível em todos os estados — inclusive no vazio e no de erro. Escolher o arquivo é o primeiro passo do fluxo, e sem ele o estado vazio ("Importe um EPUB") não teria como cumprir o que diz.

**Depois de qualquer mudança no servidor** (livro criado, removido ou ajustado), a Biblioteca recarrega a lista — mesmo quando o fluxo termina sem navegar (por exemplo, "Remover o novo"). Um contador de "versão da biblioteca" no `ImportacaoViewModel` sinaliza isso.

**Novas rotas na `ApiImagineer`:** `POST /livros` (multipart), `PATCH /livros/{id}` (`LivroAjuste`) e `GET /livros/{id}` (`LivroDetalhe`, com `CapituloResumo`) — os dois últimos servem também à tela de Livro (7.4), mais adiante.

**Limitação conhecida (achada por um teste): tamanho informado errado.** Se o provedor de arquivos declara um tamanho diferente do real, o OkHttp aborta o envio (o `Content-Length` não bate com os bytes) e o app mostra a mensagem genérica de "não consegui falar com o servidor" — enganosa, porque o problema não é a rede. Não foi tratado: é raro (provedores de arquivo padrão do Android informam certo), e distinguir esse caso exigiria inspecionar a mensagem da exceção. Se aparecer no uso real, o conserto é mandar o envio "em pedaços" (`contentLength = -1`) sempre que o tamanho não puder ser confiado.

**Testes:** desserialização com JSON **real** do backend (importação com semelhantes e pendentes, e a resposta do `PATCH`); extração do `detail` (texto, lista de validação, corpo que não é JSON); validação local (extensão, tamanho); o corpo do upload (conteúdo idêntico, progresso monotônico terminando no total, `isOneShot`); e o `ImportacaoViewModel` com repositório e leitor de arquivos falsos, cobrindo cada ramo acima, inclusive a verificação antes de reenviar e o formulário que recusa campo vazio.

#### Detalhes de plataforma que não são óbvios

- **Tráfego HTTP em texto puro é bloqueado por padrão no Android 9+.** O servidor fala HTTP simples (não HTTPS) e o endereço Tailscale é um IP, então o app precisa de um `network_security_config` liberando *cleartext* — de forma restrita ao possível: o tráfego já vai dentro do túnel criptografado do Tailscale, que é o que justifica aceitar HTTP aqui (item 7.0, "Acesso fora de casa"). Sem isso, toda chamada falha com um erro genérico de rede que engana.
- **Timeouts:** leitura de 30 s no cliente HTTP em geral; o upload usa um tempo maior, por causa dos arquivos grandes.
- **Permissão de internet** (`INTERNET`) no manifesto. O seletor de arquivo do sistema dispensa qualquer permissão de armazenamento.
- **Versão mínima do Android: API 31 (Android 12).** Decidido em 29/09/2026. O dispositivo de teste é um **Galaxy Tab S8 com Android 16**, então a cor dinâmica do Material You (Android 12+) está garantida e não há paleta de reserva para manter. O celular do Allan não foi usado como referência: o alvo real de teste é o tablet.
- **O dispositivo de teste é um tablet (tela ~11"), e os wireframes foram desenhados para celular.** Consequência para o código: nada de largura fixa; as listas usam a largura disponível, e cartões/formulários têm largura máxima (~600 dp, centralizados) para não ficarem esticados. Layout em duas colunas (lista + detalhe) fica fora do MVP, mas a estrutura das telas não deve impedi-lo depois. Testar também em modo retrato e paisagem (o tablet gira). O app deve funcionar em celular igualmente, por ser o uso final previsto (item 1.3).
- **Nome do pacote: `com.allan.imagineer`.** Como o pacote é o identificador do app e **não pode mudar depois sem reinstalar**, foi escolhido antes de qualquer código.
- **Onde mora o código do app: `G:\Git\Apps\Imagineer`**, fora deste repositório (o backend continua em `G:\Git\Imagineer`, e a especificação de **ambos** fica aqui, em `ESPECIFICACAO.md`). Stack criada pelo assistente do Android Studio: AGP 9.4.1, Kotlin 2.2.10, Compose BOM 2026.02.01, Kotlin DSL; dependências acrescentadas no incremento 1: `navigation-compose` 2.9.0, `kotlinx-serialization-json` 1.9.0 e `material-icons-core`.

#### Fora do escopo do Bloco A

Busca/filtro na Biblioteca, ordenação escolhida pelo usuário, capa do livro (o backend não extrai capa), edição de metadados fora do fluxo de importação (isso é da tela de Livro, 7.4) e qualquer chamada de IA.

#### Testes

- **ViewModels:** teste unitário de cada estado da Biblioteca (carregando/lista/vazio/erro) com um repositório falso — a mesma ideia do `ProvedorFalso` do backend: o ViewModel recebe a interface no construtor (item 7.0, DI manual), então o teste troca a rede por uma lista fixa.
- **Normalização da URL:** teste unitário puro (casos: com/sem `http://`, barra final, espaços).
- **Desserialização:** teste com um JSON real de `GET /livros` e `POST /livros` colado como fixture, para garantir que as classes Kotlin espelham mesmo o backend (o erro típico é um campo renomeado de um lado só).
- **Ponta a ponta manual:** no celular, contra o servidor real, checklist do critério de cada incremento acima.

### 7.4 Livro (detalhe)

Passos 3 a 5: a estrutura de capítulos do livro, e o ponto de entrada para tudo que pertence a ele.

- **Rota**: `GET /livros/{id}` (estrutura, sem texto — item 6.2).
- **Mostra**: metadados (título, autor, idioma), perfil de renderização padrão (ou "nenhum definido"), lista de capítulos em ordem, com indicação visual dos que estão marcados como ignorados, e (implementado, item 4.6) um indicador por capítulo de quantas sugestões ainda faltam confirmar (`sugestoes_pendentes`, item 6.2) — não bloqueia nada, só ajuda o usuário a ver de relance onde falta revisar. **Capítulo com `titulo` nulo** (item 2.2 — os ~11% que nem o título de reserva tirado do texto recupera) **exibe "Capítulo `<ordem>`" como reserva de exibição**, só na tela — não é dado novo da API, mesma lógica do item 7.9 (formatação fica no cliente). Ajustar se necessário quando esta tela for de fato implementada.
- **Ações**: tocar num capítulo não-ignorado abre a tela de Capítulo (7.5); arquivar um capítulo direto na lista e restaurá-lo da área de arquivados (`PATCH /capitulos/{id}` com `ignorado`, item 2.2; ver 7.5a, revisão do incremento 6); editar metadados e perfil padrão (`PATCH /livros/{id}`); atalho para "Elementos do livro" (7.8) e para "Perfis de renderização" (7.9); apagar o livro (`DELETE /livros/{id}`) com confirmação — é destrutivo e leva capítulos, elementos, frames, prompts e imagens junto (item 3.4).

**Wireframe revisado (29/09/2026, Bloco B):** editar metadados e apagar o livro saíram de botões soltos na tela e viraram um menu de três pontos na barra superior (junto com um item "Editar metadados e perfil padrão" e outro "Apagar livro", este em vermelho) — decisão do Allan revisando o protótipo: uma ação tão relevante quanto apagar o livro não deveria disputar espaço visual com o dia a dia da tela. O toggle de "ignorado" por capítulo ganhou um ícone próprio em cada linha (arquivar/restaurar), em vez de só mostrar um selo sem ação.

**Pendência registrada, não implementada agora**: o estado "perfil padrão: nenhum definido" (quando o livro ainda não tem perfil escolhido) não tem tela própria no protótipo — fica pra quando a tela for de fato codada, seguindo o mesmo texto reserva já usado noutros lugares desta especificação.

### 7.5 Capítulo

O coração dos passos 5 a 7: ler o texto, pedir sugestões à IA, e confirmar o que de fato existe.

- **Rotas**: `GET /capitulos/{id}` (texto completo), `POST /capitulos/{id}/sugestoes` (passo 6, fase 1 do item 4.4), `GET /capitulos/{id}/estados-vigentes`, `POST /livros/{id}/elementos`, `POST /elementos/{id}/estados`.
- **Mostra**: o texto do capítulo (rolável); um botão "Analisar com IA" que dispara `POST /capitulos/{id}/sugestoes` e traz a lista de elementos identificados (tipo, nome, identidade, `manter_estado_atual`) — **sem** descrição de aparência, porque essa parte só existe na leitura profunda da fase 2 (item 4.4), que acontece mais adiante, na tela de Prompt. Se `sugestoes_pendentes_anteriores` vier maior que zero (implementado, item 4.6), um aviso não-bloqueante: "Você tem N sugestões não confirmadas em capítulos anteriores — confirmar primeiro deixa esta análise mais precisa". Cada participante de cena sugerida com `casamento_automatico=true` (item 4.6) aparece destacado, antes de o usuário confirmar a cena. Uma sugestão já casada (`elemento_id` preenchido) mas com `estado_id` nulo (item 3.4e/6.7) também aparece destacada — "casada, mas ainda não virou Estado neste capítulo".
- **Ações por sugestão**: confirmar (grava `Elemento` + `EstadoElemento` inicial), ajustar tipo/nome antes de confirmar, ou descartar (não faz nada — é só sugestão). Também dá para cadastrar um elemento à mão, sem passar pela IA. A lista de "estados vigentes" (item 3.4b) mostra o que já se sabe de cada elemento do livro até este ponto, útil para o usuário decidir se o que a IA sugeriu já é conhecido. Para um participante com casamento automático destacado, corrigir o vínculo sem confirmar um Estado usa `PATCH /sugestoes-elemento/{id}` (item 6.3/4.6).
- **Navega para**: "Novo retrato" cria um frame `tipo=PERSONAGEM` para um elemento específico e abre a tela de Frame (7.6) já com ele; "Nova cena" cria um frame `tipo=CENA` vazio (ou pré-preenchido a partir de um `frames` sugerido pela IA, item 4.4) e abre a mesma tela pronta para escolher quem mais aparece; lista de frames já criados neste capítulo (retratos e cenas, diferenciados visualmente pelo `tipo`), cada um abrindo a tela de Frame existente.

**Wireframe revisado (29/09/2026, Bloco B):** três coisas que só existiam em prosa aqui ganharam tela no protótipo. (1) "Novo retrato" agora passa por uma tela de escolher o elemento antes de abrir o Frame — no texto original isso já estava implícito ("para um elemento específico"), mas não havia como mostrar essa escolha. (2) A lista de "estados vigentes" citada nas Ações ganhou tela própria, com um botão "Ver estados vigentes do livro" no Capítulo — antes só existia como conceito de rota (`GET /capitulos/{id}/estados-vigentes`), sem lugar nenhum pra aparecer. (3) O ajuste de tipo/nome/vínculo de uma sugestão (`PATCH /sugestoes-elemento/{id}`) ganhou uma tela de formulário simples, acessada por um ícone de lápis em cada sugestão — inclusive pro caso "casada, mas ainda não virou Estado", que agora tem uma linha própria na lista (sem os botões de confirmar/descartar, só o de corrigir vínculo, porque não é uma sugestão nova).

### 7.5a Bloco B em detalhe — Leitura e Catalogação

Aprofundamento das telas 7.4 (Livro) e 7.5 (Capítulo), no mesmo formato do 7.3a. O Bloco B é grande — sobretudo a análise por IA — e por isso é dividido em incrementos que continuam a numeração do Bloco A. Cada um roda no tablet:

6. **Livro, só leitura + ignorar capítulo:** a tela de Livro com metadados, lista de capítulos, alternar "ignorado" e navegar para Capítulo, Elementos e Perfis. **Implementado:** `rede/ProvedorDeApi.kt` (o cliente Retrofit compartilhado, extraído do repositório de livros), `rede/RepositorioDeCapitulos.kt`, `telas/livro/` (`LivroViewModel`, `TelaLivro`, `FormatacaoDoLivro`) e `PATCH /capitulos/{id}` na `ApiImagineer`. 138 testes de unidade no app (25 novos), inclusive JSON real de `GET /livros/{id}` e do `PATCH /capitulos` e a corrida entre uma recarga e um alternar em andamento. Falta a verificação manual no tablet.
7. **Livro, ajustes:** editar título/autor/idioma, definir o perfil de renderização padrão (precisa da lista de perfis) e apagar o livro pela própria tela. Decisões em "Incremento 7 em detalhe". **Implementado:** `LivroAjuste.paraJson()` (campo ausente, valor ou `null` explícito), `rede/PerfilRenderizacao.kt` e `RepositorioDePerfis` (só leitura), `telas/comum/` (`ControleDeRemocao` e `DialogoDeRemocao`, extraídos da Biblioteca e agora compartilhados), e no `LivroViewModel` a edição, a escolha de perfil e a remoção, com o menu ⋮ e os diálogos em `DialogosDoLivro.kt`. **181 testes de unidade no app** (43 novos neste incremento). Falta a verificação manual no tablet.
8. **Capítulo, só leitura:** o texto rolável do capítulo. Decisões em "Incremento 8 em detalhe". **Implementado:** `CapituloDetalhe` e `GET /capitulos/{id}`, `abrirCapitulo` no `RepositorioDeCapitulos`, e `telas/capitulo/` (`CapituloViewModel` com `dividirEmParagrafos`, e `TelaCapitulo` com `LazyColumn` de parágrafos e texto selecionável). **199 testes de unidade no app** (18 novos). Falta a verificação manual no tablet, sobretudo com um capítulo longo de verdade — a fluidez da rolagem é o que os testes de unidade não medem.
9. **(Redefinido pela entrega em etapas do item 7.5b, abaixo: o painel de IA e a lista de sugestões, sem posição no texto. Os incrementos 10 e 11 abaixo também passam a seguir aquela ordem.) Capítulo, análise por IA (leitura):** "Analisar com IA" e a lista de sugestões de elementos e cenas, com os destaques do item 7.5. Primeiro incremento que gasta chamada de IA de verdade.
10. **Capítulo, confirmar sugestões:** confirmar, ajustar ou descartar; cadastrar elemento à mão; estados vigentes.
11. **Capítulo, frames:** lista de frames do capítulo e "Novo retrato" / "Nova cena" — a ponte para o Bloco C.

#### Incremento 6 em detalhe — Livro (leitura) e ignorar capítulo

- **Estrutura:** `LivroViewModel` recebe o `livroId` e dois repositórios: o de livros (`GET /livros/{id}`, já existe desde o incremento 5) e um **novo `RepositorioDeCapitulos`** (`PATCH /capitulos/{id}`). Capítulos ganham repositório próprio, e não mais um método em `RepositorioDeLivros`, porque o de livros já tem cinco funções e a Capítulo (incrementos 8 a 11) vai crescer a partir desse novo. Para os dois não duplicarem a montagem do cliente Retrofit, ela sai para uma classe `ProvedorDeApi`.
- **Estados:** **Carregando** · **Pronto** (o livro, e o conjunto de capítulos com uma alteração em andamento) · **Erro** (motivo + "Tentar de novo"). Recarrega toda vez que a tela volta a ficar visível (`ON_RESUME`), como a Biblioteca: ao voltar de um capítulo, o `sugestoes_pendentes` pode ter mudado. Com o livro já na tela a recarga é silenciosa. **(Atualizado após o incremento 8 — recarga que falha.)** Se essa recarga silenciosa **falhar**, o livro **continua na tela** e um aviso (`Snackbar`, sem ação: "Não consegui atualizar o livro.") diz que não deu para atualizar; a tela só cai em **Erro** quando **não havia livro para mostrar** (primeira abertura). O motivo da diferença em relação à Biblioteca (item 7.3a, onde a falha da recarga cai no erro de propósito): aqui a recarga existe só para atualizar detalhes como `sugestoes_pendentes` ao voltar de um capítulo, e a tela guarda estado que não deve ser perdido por causa disso — seleção em lote, capítulos com chamada em andamento e diálogos abertos. Achado na revisão de código de 30/09/2026: até então o código trocava o livro por **Erro** em qualquer falha, e a especificação não dizia o que fazer nesse caso. Teste novo: livro `Pronto` + recarga que falha → livro mantido, aviso emitido, estado continua `Pronto`. **Exceção: `404`.** Se a recarga responde que o livro **não existe mais** (apagado por outro caminho — outro aparelho, o `/docs`), não há livro válido a preservar: a tela cai em **Erro**, mostrando o motivo da API ("Não existe livro com id N."), em vez de ficar exibindo dados de um livro que já não existe com só um aviso genérico. Qualquer outra falha (sem conexão, `5xx`, resposta estranha) continua preservando o livro. Achado na análise do PR #1 (30/09/2026).
- **Cabeçalho:** título, autor ("Autor desconhecido" se nulo), idioma se houver, "N capítulos · M ignorados" e o perfil padrão. **O perfil aparece só como "definido" ou "nenhum definido"**: a API devolve apenas o id (`perfil_renderizacao_padrao_id`), e mostrar o nome exigiria outra chamada e o `GET` de perfis, que só entra no incremento 7. Se `metadados_pendentes` vier não-vazio (o usuário pulou o formulário da importação por outro caminho), mostra uma linha "Faltam dados: autor" — a edição em si é do incremento 7.
- **Lista de capítulos**, em ordem. Cada linha: título (**"Capítulo `<ordem>`" quando `titulo` é nulo** — item 7.4), tamanho legível ("850 caracteres", "3,4 mil caracteres", "112 mil caracteres" — o servidor só devolve o número e a formatação é do cliente, como no 7.9) e, se `sugestoes_pendentes > 0`, um selo com a contagem.
- **(Substituído — ver "Revisão do incremento 6" abaixo.) Ignorar/reativar:** um interruptor por linha, com **ligado = capítulo catalogado** e desligado = ignorado. Escolhido em vez de um botão de "ignorar" porque o estado atual fica visível sem tocar em nada, e o item 2.2 trata o ignorado como o estado **sugerido pela importação** — o usuário revisa uma lista, não executa uma ação. Um capítulo ignorado aparece esmaecido e **não abre** ao tocar (item 7.4). **Só o bloco do título e do tamanho é clicável**, e não a linha inteira: com a linha toda clicável, um toque impreciso no interruptor (ou no espaço em volta) abria o capítulo em vez de ignorá-lo — achado testando no tablet. O lado do interruptor não responde a toque nenhum além do próprio interruptor.
- **`PATCH /capitulos/{id}` devolve o capítulo com o texto** (`CapituloDetalhe`, verificado). O app não precisa do texto ali: lê só o `CapituloResumo` (os campos extras são ignorados pelo `ignoreUnknownKeys`) e descarta o resto. Custa o texto trafegar sem uso — até ~110 KB no maior capítulo dos livros de validação —, aceitável para um toque ocasional, e evita mudar o backend por isso.
- **Alterar não é otimista.** O interruptor só muda quando o servidor confirma; enquanto a chamada está no ar, o interruptor daquela linha é **trocado por um indicador de progresso** (impede o duplo toque e o "pisca-pisca" de um estado que depois volta atrás). Um interruptor apenas apagado não diz que o app está esperando — achado testando no tablet, onde o servidor parado fazia a espera ir até o *timeout* de conexão (10 s) com pouca indicação visual. Se falhar, o interruptor fica onde estava e um aviso (`Snackbar`) mostra o motivo. **O aviso é um evento, e não um estado** (`Channel`, não `StateFlow`): com o servidor fora do ar toda falha tem a mesma mensagem, e um estado não emite quando o valor novo é igual ao atual — os toques seguintes ao primeiro ficavam sem nenhum retorno, e como o interruptor nunca muda de posição sozinho, o aviso é o único sinal de que o toque foi processado. Achado testando no tablet; cada falha dispensa o aviso anterior e mostra um novo. Depois do sucesso, `capitulos_ignorados` do cabeçalho é recalculado a partir da própria lista.
- **Barra superior:** seta de voltar e os atalhos "Elementos" e "Perfis" (botões de texto, pelo mesmo motivo do incremento 4). "Editar" e "Apagar livro" chegam no incremento 7.
- **Erro 404** (o livro foi removido por outro caminho): o motivo vem da API ("Não existe livro com id N.") e a seta de voltar continua na barra — "Tentar de novo" ali não resolveria.
- **Testes:** ViewModel com repositórios falsos (estados, alternar com sucesso e com falha, duplo toque, recarga silenciosa e a corrida entre uma recarga e um alternar em andamento); funções puras (`tituloDoCapitulo`, `descreverTamanho`); desserialização com JSON **real** de `GET /livros/{id}` e de `PATCH /capitulos/{id}`; e o `MockWebServer` para o `PATCH` (caminho, corpo `{"ignorado":true}` e 404).

#### Incremento 7 em detalhe — Livro: editar, perfil padrão e apagar

Três ações sobre o livro aberto, todas num menu ⋮ na barra superior (ao lado dos atalhos "Elementos" e "Perfis"): **Editar**, **Perfil padrão…** e **Apagar livro**.

**O problema que atravessa tudo: mandar `null` de propósito.** Até aqui o app **omite** campos nulos do JSON (campo ausente = "não mexa", item 6.2). Mas limpar o idioma ou remover o perfil padrão exige mandar `null` de verdade, e o backend trata os dois casos de forma diferente (verificado: `{"idioma": null}` limpa; ausente não mexe). O `LivroAjuste` deixa de ser serializado direto: ganha os campos `idioma` e `perfil_renderizacao_padrao_id` e duas marcas explícitas, `limparIdioma` e `limparPerfilPadrao`, e um `paraJson()` monta o corpo — campo ausente fica de fora, marca acionada vira `null`. A API recebe o `JsonObject` já montado. Uma alternativa descartada foi ligar `encodeDefaults` no `Json` do app: mandaria **todos** os nulos, inclusive `titulo` e `autor`, e no backend `autor: null` faz o autor voltar a ficar pendente.

**Editar (título, autor, idioma).** Um diálogo com três campos preenchidos com os valores atuais. Regras:
- **Título e autor são mandatórios** (item 7.3): campo em branco bloqueia o "Salvar" com mensagem. No autor isso protege de um detalhe do backend — `autor: ""` não é nulo para ele, então gravaria uma string vazia e o autor deixaria de contar como pendente sem existir. O título vazio o backend já recusa (422), mas o app avisa antes.
- **Idioma é opcional.** Em branco significa "sem idioma": se o livro tinha um, o app manda `null` explícito para limpar; se já não tinha, não manda nada.
- **Só os campos que mudaram são enviados**, comparando o texto aparado com o valor atual. Não é só economia: mandar `titulo` **confirma** o título no backend (item 6.2), e um título que o usuário nem tocou não deve ser confirmado por tabela. Nada mudou → o diálogo só fecha, sem chamada.
- Falha mostra o motivo dentro do diálogo, que continua aberto com os dados digitados.

**Perfil padrão.** O cabeçalho passa a mostrar o **nome** do perfil, e não só "definido": depois de carregar o livro, se `perfil_renderizacao_padrao_id` não é nulo, o app busca `GET /perfis-renderizacao/{id}`. É *best-effort* — se falhar, cai no "definido" do incremento 6, em vez de derrubar a tela por um detalhe de cabeçalho. "Perfil padrão…" abre um diálogo com a lista (`GET /perfis-renderizacao`): botões de escolha, um por perfil, mais **"Nenhum"**, com o atual marcado. Escolher chama `PATCH /livros/{id}` na hora (sem botão "Salvar" extra — a escolha é o gesto); "Nenhum" manda `null` explícito. Sem perfis criados, o diálogo diz "Nenhum perfil criado ainda" e aponta para a tela de Perfis. **Criar** perfis continua sendo da tela de Perfis (Bloco E): aqui só se escolhe entre os existentes.

**Apagar livro.** O mesmo diálogo de confirmação da Biblioteca (item 7.3a, incremento 4), que aqui **sai do arquivo da Biblioteca e vira compartilhado**, junto com a máquina de estados por trás dele (`ControleDeRemocao`: confirmando → removendo → falhou, com o `404` contando como sucesso). Duas telas com a mesma lógica escrita duas vezes divergiriam. Removido com sucesso, a tela **volta para a Biblioteca** (o livro que ela mostrava já não existe) e a Biblioteca recarrega ao reaparecer.

**Testes:** `LivroAjuste.paraJson()` em todas as combinações (campo ausente, valor, `null` explícito); um `MockWebServer` confirmando que `{"idioma":null}` chega ao servidor; JSON **real** de perfil (`GET /perfis-renderizacao` e `/{id}`); o `ViewModel` para cada ramo (nada mudou, só o que mudou, campos em branco, idioma limpo, falha, nome do perfil, escolha e "Nenhum", lista vazia, apagar com sucesso e com falha); e o `ControleDeRemocao` **só indiretamente**, pelos dois ViewModels que o usam (Biblioteca e Livro) — um teste isolado repetiria os mesmos cenários.

#### Incremento 8 em detalhe — Capítulo (só leitura)

A tela de Capítulo (7.5) nasce como **leitor de texto**. A análise por IA, as sugestões e os frames entram nos incrementos 9 a 11, sobre a mesma tela.

- **Rota:** `GET /capitulos/{id}` (`CapituloDetalhe`: os campos do resumo, mais `livro_id` e `texto`). O texto do maior capítulo dos livros de validação tem ~110 KB; trafega uma vez por abertura.
- **Estados:** **Carregando** · **Pronto** · **Erro** (motivo + "Tentar de novo"). Diferente da Biblioteca e do Livro, **não recarrega ao voltar a ficar visível**: o texto de um capítulo não muda. Carrega uma vez, e o ViewModel guarda o resultado ao girar o tablet. (`sugestoes_pendentes` e `ignorado`, que podem mudar, ganharão tela própria de atualização nos incrementos 9 e 10.)
- **O texto é dividido em parágrafos antes de chegar à tela.** O backend separa parágrafos com uma linha em branco (`\n\n`) e mantém `\n` sozinho para quebras dentro de um parágrafo (`<br>`); já normaliza `\r\n` e junta 3 ou mais quebras em 2 (verificado no código da importação). O app divide em `\n{2,}`, descarta pedaços vazios e mantém o `\n` interno como quebra de linha real. Cada parágrafo é **um item de uma lista com rolagem preguiçosa** (`LazyColumn`): um único `Text` com 110 KB seria medido e desenhado inteiro de uma vez, mesmo com 99% fora da tela. A função de divisão é pura (fora do Compose) para ser testada na JVM.
- **Leitura confortável, num tablet:** corpo em `bodyLarge` com espaçamento de linha ampliado, 12 dp entre parágrafos, e largura máxima de ~600 dp centralizada — linhas de 100 caracteres cansam. O título vem da barra superior ("Capítulo `<ordem>`" quando `titulo` é nulo, como em 7.4) e, abaixo, uma linha com a ordem e o tamanho legível.
- **Texto selecionável** (`SelectionContainer`): o usuário vai querer copiar um trecho — por exemplo, para descrever uma cena. **Limitação conhecida:** a seleção não atravessa parágrafos (cada um é um item da lista); dentro de um parágrafo funciona normalmente.
- **Capítulo ignorado:** a tela de Livro não abre capítulos ignorados (item 7.4), mas o estado pode ter mudado por outro caminho. Se vier `ignorado = true`, o texto é mostrado normalmente com um aviso discreto "Este capítulo está marcado como ignorado" — não bloqueia a leitura.
- **Capítulo sem texto** (`texto` vazio ou só espaços): mostra "Este capítulo não tem texto." em vez de uma tela em branco.
- **Sem navegação "próximo/anterior" por enquanto:** exigiria a lista de capítulos do livro nesta tela; volta-se ao Livro para escolher outro. Pode entrar depois, se fizer falta na leitura.
- **Barra superior:** só a seta de voltar. O botão "Analisar com IA" chega no incremento 9.
- **Testes:** divisão em parágrafos (quebra dupla, tripla, `\n` interno preservado, bordas, texto vazio); ViewModel (estados, erro, tentar de novo, não recarrega se já está pronto); JSON **real** de `GET /capitulos/{id}`; e o `MockWebServer` para o caminho e o `404`.

#### Revisão do incremento 6 — arquivar em vez de ignorar

**O que motivou.** Testando o interruptor no tablet, dois problemas apareceram. O técnico: a linha inteira era clicável, e um toque impreciso no interruptor abria o capítulo (corrigido restringindo a área clicável ao título, mas o problema de fundo ficou). O de desenho: descobriu-se que, **no backend, `ignorado` não faz nada além de contar** (verificado no código: nenhuma rota recusa um capítulo ignorado; só `capitulos_ignorados` o usa). Então a marca existia na tela sem uma função clara — servia só para esmaecer uma linha. A decisão do Allan, com a analogia das *conversas arquivadas do WhatsApp*: **um capítulo desativado deve sair da lista e ir para uma área separada, de onde pode ser restaurado; a lista do livro mostra só os ativos.**

**O modelo novo.**
- **Arquivar** é a ação; **Arquivados** é a área; **Restaurar** desfaz. Na API continua sendo `ignorado` (`PATCH /capitulos/{id}`); "arquivado" é só o **vocabulário da tela**. Renomear o campo do backend (com migration) foi considerado e **adiado**: mexe em banco e em API por uma questão de rótulo, e a tradução mora num só lugar (a tela). Se o vocabulário incomodar no futuro, é uma migration simples.
- **A lista do livro mostra só os capítulos ativos.** **(Superado pela "Segunda revisão" abaixo: o botão por linha deu lugar à seleção em lote.)** Cada linha tinha, à direita, um **botão de arquivar (ícone de pasta com seta para baixo)**, num toque só — no lugar do interruptor. Começou como um menu ⋮ com "Arquivar" (dois toques); o Allan pediu um toque só, e o botão dispensa confirmação porque **é reversível** (área de arquivados → restaurar). Fica numa área própria, separada do título, então um toque impreciso no título não arquiva, e um no botão não abre o capítulo.
- **"Arquivados (N)":** uma linha logo abaixo do cabeçalho, **só quando N > 0**, como no WhatsApp. Toca-se nela para abrir a área de arquivados.
- **A área de arquivados é uma tela própria** (`CapitulosArquivados(livroId)`), com a lista dos capítulos arquivados. Cada linha tem o título (que abre o capítulo para **leitura** — o aviso "Este capítulo está arquivado" já aparece lá) e um **botão de restaurar (ícone de pasta com seta para cima)**, separado da área do título. Restaurado, o capítulo some da área de arquivados e volta à lista principal. Sem nenhum arquivado, a tela diz "Nenhum capítulo arquivado."
- **As duas telas compartilham o mesmo `LivroViewModel`** (escopado à tela de Livro na pilha de navegação): arquivar numa e restaurar na outra sempre enxergam o mesmo livro, sem recarregar nem ficar defasado.
- **Continua não sendo otimista**: a linha só sai da lista quando o servidor confirma, e enquanto isso o botão vira um indicador de progresso.
- **"Desfazer" depois de arquivar** *(vale também para o lote — ver a segunda revisão)*. Como nas conversas arquivadas do WhatsApp, arquivar mostra um aviso temporário no rodapé — **"Arquivado: `<título do capítulo>`"**, com a ação **Desfazer**. Pedido do Allan: sem isso, quem arquiva o capítulo errado precisa abrir a área de arquivados e *adivinhar qual foi* para restaurá-lo. Regras:
  - O aviso **nomeia o capítulo** ("Capítulo N" se não tem título): é o que responde "qual foi?".
  - **Desfazer chama a mesma rota de restaurar** (`PATCH` com `ignorado = false`), sem caminho especial. Se falhar, mostra o erro como qualquer outra falha.
  - **Dura 10 segundos** (`Long`). O padrão do Material 3 para um aviso com ação seria **indefinido** — ficaria na tela até alguém tocar —, o que é errado para algo que só deve tirar o usuário de um engano imediato.
  - **Arquivar de novo troca o aviso.** Só o último arquivamento fica desfazível pelo aviso; os anteriores continuam na área de arquivados. Empilhar um aviso por toque seria ruído.
  - Só o **arquivar** ganha "Desfazer". **Restaurar** não: o capítulo some da área de arquivados e reaparece na lista, e desfazer um restaurar seria arquivar de novo, que é um toque.
  - O aviso é um **evento** com dados (`Aviso`: texto e, opcionalmente, os capítulos a restaurar — a lista de ids do lote), e não só uma frase: quem o exibe (as telas de Livro e de Arquivados, que compartilham o mesmo ViewModel) sabe qual capítulo restaurar sem consultar a lista.
- **As sugestões pendentes viram texto, não balão.** A linha do capítulo mostra "3,4 mil caracteres · 13 sugestões a confirmar" (singular: "1 sugestão a confirmar"; sem pendentes, nada). O número são as sugestões de **elemento e de cena** que a IA encontrou naquele capítulo e o usuário ainda não confirmou nem descartou (item 4.6 — o backend soma `SugestaoDeElemento` sem elemento e `SugestaoDeCena` sem frame). Antes era um balão numérico sem rótulo, e quem o via no tablet não tinha como saber o que era.
- **As contagens passam a ser de ativos:** o cartão da Biblioteca e o cabeçalho do Livro dizem, por exemplo, "9 capítulos · 3 arquivados", onde 9 são os ativos — e não "12 capítulos · 3 ignorados", que misturava total com ignorados e deixava a soma ambígua. O `total_de_capitulos` da API continua sendo o total; o cliente subtrai.
- **Implementado:** `arquivar`/`restaurar` no `LivroViewModel` (no-op se o capítulo já está no estado pedido), a linha "Arquivados" e o menu ⋮ por capítulo em `TelaLivro`, a `TelaCapitulosArquivados`, o destino `CapitulosArquivados` e o `livroViewModel(livroId, dono)` que faz as duas telas compartilharem o mesmo ViewModel. `descreverCapitulos` conta os ativos. **204 testes de unidade no app.** Falta a verificação manual no tablet.
- **Capítulo arquivado abre para leitura** (pela área de arquivados): o aviso da tela de Capítulo passa de "marcado como ignorado" para "arquivado". O que a importação **sugeriu** como ignorado já nasce arquivado; o usuário revisa a área de arquivados para restaurar o que era narrativa de verdade.

#### Segunda revisão do incremento 6 — arquivar e restaurar em lote, por seleção

**O que motivou.** Testando o botão de um toque por linha, o Allan propôs algo melhor para o caso comum: a importação costuma sugerir **vários** capítulos não narrativos de uma vez, e arquivá-los um a um é repetitivo. A ideia: um único botão no topo, caixas de seleção nas linhas, e o usuário marca quais capítulos e confirma. **Esta rodada trata só das regras de negócio; o desenho visual (posição dos botões, ícones, aparência da barra de seleção) é refinado depois.**

As regras abaixo valem para as **duas** telas — a lista principal (que **arquiva**) e a área de arquivados (que **restaura**) — de forma simétrica.

**Entrar e sair do modo de seleção**
1. **Duas entradas:** tocar no botão do topo (**Arquivar** na lista; **Restaurar** nos arquivados) ou **tocar e segurar** numa linha, que já entra com ela marcada. O botão só faz sentido se há capítulos nessa tela.
2. **O modo persiste até confirmar ou cancelar.** Desmarcar o último capítulo **não** sai do modo (quem entrou pelo botão do topo começa com zero marcados, então sair sozinho seria incoerente). Sai-se por **Cancelar**, por **confirmar**, ou pelo **botão voltar** do aparelho (que cancela o modo em vez de sair da tela).
3. **Fora do modo, tocar no título abre o capítulo** (como antes). **Dentro do modo, tocar na linha marca ou desmarca** — não abre nada.
4. **Enquanto seleciona, as outras ações ficam indisponíveis** (Elementos, Perfis, o menu do livro, a linha "Arquivados"): sair da tela com uma seleção pela metade seria ambíguo.
5. **Só se marca o que o modo permite:** na lista, capítulos ativos; nos arquivados, capítulos arquivados. Um capítulo cuja chamada ainda está em andamento **não pode** ser marcado.

**Confirmar**
6. **O próprio botão "Arquivar (N)" é a confirmação** — sem diálogo extra, porque a ação é reversível (Desfazer e a área de arquivados). Fica **desabilitado com zero marcados**. O mesmo vale para "Restaurar (N)".
7. **Uma chamada `PATCH /capitulos/{id}` por capítulo, em sequência.** Não existe rota em lote, e criar uma foi **adiado**: é uma mudança de API para ganhar tempo de ida e volta, e com dezenas de capítulos em sequência a espera ainda é de poucos segundos. Fica registrado como possível otimização.
8. **Continua não otimista:** cada capítulo só sai da lista quando o servidor confirma o dele, e os marcados mostram progresso enquanto esperam a vez.

**Quando algo falha**
9. **Para no primeiro erro.** Se o servidor está fora do ar, continuar tentaria os N capítulos restantes e cada um levaria o *timeout* de conexão (10 s): um lote de 20 esperaria mais de 3 minutos para dar o mesmo erro 20 vezes. Os capítulos **já concluídos ficam** arquivados; os **restantes continuam marcados**, para o usuário tentar de novo com o mesmo botão.
10. O aviso diz o que aconteceu: **"K de N arquivados. `<motivo>`"**. Se nenhum foi concluído, só o motivo.

**Quando tudo dá certo**
11. **Sai do modo**, e um aviso temporário nomeia o que foi feito: **"Arquivado: `<nome>`"** para um capítulo, **"N capítulos arquivados"** para vários — com **Desfazer**.
12. **Desfazer restaura exatamente os capítulos daquele lote**, e mais nenhum (o aviso carrega a lista de ids). Segue o mesmo caminho de restaurar em lote e **não gera outro aviso de sucesso** (senão restaurar geraria um aviso, que ofereceria desfazer, e assim por diante).
13. **Só arquivar ganha aviso de sucesso.** Restaurar não: os capítulos somem da área de arquivados, que é retorno suficiente; só as **falhas** de restaurar geram aviso.
14. O aviso dura 10 s, e **um lote novo troca o aviso anterior**: só o último lote fica desfazível pelo aviso; os anteriores continuam na área de arquivados.

**Implementado:** `Selecao`/`ModoDeSelecao`, `iniciarSelecao`/`alternarSelecao`/`cancelarSelecao`/`confirmarSelecao`, o lote sequencial com parada no primeiro erro (`executarLote`), o aviso do lote (`avisoDoLote`), a poda da seleção e o `desfazerArquivamento`, no `LivroViewModel`; na interface, uma linha e uma barra de seleção compartilhadas (`SelecaoDeCapitulos.kt`) pelas duas telas. **238 testes de unidade no app** (28 novos, cada um citando a regra R# que cobre). A interface é provisória, de propósito. Falta a verificação manual no tablet.

**Consistência**
15. **Quando a lista recarrega, a seleção é podada:** um capítulo marcado que deixou de existir ou de estar elegível (foi arquivado por outro caminho, ou removido) é desmarcado sozinho, em vez de gerar uma chamada que falharia.
16. **Os botões de arquivar/restaurar por linha deixam de existir.**
17. **O nome no aviso vem da lista, e não da resposta do servidor:** uma frase da tela não deve depender do formato de uma resposta de rede (achado quando um teste com resposta falsa mostrou o nome errado).
18. **Selecionar todos** (acrescentado em 30/09/2026, depois de a rodada original deixá-lo de fora): um botão na barra do modo de seleção que **alterna**:
    - **Marca todos os capítulos elegíveis** do modo (ativos ao arquivar, arquivados ao restaurar) — **menos os que têm chamada em andamento**, pela mesma regra R5: nada em andamento pode ser marcado.
    - Se **todos já estão marcados**, o mesmo botão **desmarca todos**. Continua no modo (R2); só sai por confirmar, cancelar ou voltar. Se só alguns estão marcados, completa a seleção.
    - O rótulo diz o que vai acontecer: **"Selecionar todos"** ou **"Desmarcar todos"**.
    - **Só existe dentro do modo de seleção**: não faz sentido fora dele, e entrar pelo botão do topo já começa com zero marcados, deixando o "todos" a um toque. Com o lote no ar, é ignorado (R8).
    - Marcar todos **não confirma nada**: o usuário ainda precisa tocar em "Arquivar (N)" / "Restaurar (N)" (R6). É o que torna seguro oferecer um gesto tão amplo.
19. **Fora do escopo desta rodada:** o desenho visual da barra de seleção e da linha marcada.

### 7.5b Capítulo ilustrado — leitura com artefatos e painel de IA (especificado, ainda não implementado)

Nascida de uma conversa com o Allan em 30/09/2026. Hoje as imagens só aparecem na tela de Prompt (7.7); esta seção define onde elas vivem na leitura e como os comandos de IA do capítulo ficam reunidos.

**Ideia central.** O capítulo vira o lugar de tudo: lê-se o texto, vê-se onde há uma cena ou um personagem, toca-se no artefato, gera-se o prompt, importa-se a imagem — e ela passa a fazer parte do texto, naquele ponto.

**O leitor.**
- **Artefatos numa faixa na margem** do parágrafo (não no meio do texto), com **um ícone diferente para cada tipo** (decisão do Allan, 30/09/2026): **oito** ao todo — um para cada tipo de elemento (`PERSONAGEM`, `AMBIENTE`, `OBJETO`, `CRIATURA`, `GRUPO`, `VEICULO`, `EDIFICACAO`, item 3.4) e um para **cena**. O artefato de elemento marca a primeira menção dele no capítulo e leva ao retrato. Vários artefatos no mesmo parágrafo se agrupam em um, com o número. Cada ícone mostra a `situacao` (sugerido, confirmado, prompt pronto, ilustrado). Um interruptor no painel liga e desliga os artefatos.
- **Depois de importada, a imagem é desenhada entre os parágrafos**, na posição do artefato, e **ampliável ao toque** (tela cheia, como no 7.7). Aparece a mais recente do frame (item 3.4g). Carregamento por biblioteca de imagens com cache (decisão na Etapa 5).
- **Sem posição**: artefatos e frames sem `posicao_no_texto` ficam numa faixa "Sem posição" no topo do capítulo; não se perdem.
- **Ilustrar à mão**: tocar e segurar um parágrafo → "Ilustrar aqui" cria (ou posiciona) um frame ali, para trechos que a IA não sugeriu.
- **Ícone, cor e rótulo de acessibilidade:** oito ícones parecidos se confundem, então cada tipo leva **ícone e cor próprios**, e cada artefato tem descrição falada ("personagem: Hospius, prompt pronto"). **Ainda a decidir:** o desenho e a cor de cada um, e o que mostrar quando vários artefatos de tipos diferentes caem no mesmo parágrafo (um ícone "vários" com a contagem é a proposta). **Possível filtro por tipo** no painel (o interruptor único de ligar/desligar pode ficar curto com oito tipos) — só se a poluição aparecer na prática.
- Quantidade de artefatos não é tratada como problema: nos testes do Allan, os capítulos voltaram com poucos personagens. Reavaliar se isso mudar.

**A imagem no texto — o layout (decidido pelo Allan em 01/10/2026).** Regras numeradas; o desenho fino é refinado no tablet.

- **I1 — Dois quadros padrão; a imagem é encaixada neles (decisão do Allan, 01/10/2026, revista).** O texto tem **dois quadros de tamanho fixo**: **retrato 2:3** e **paisagem 16:9** (os mesmos formatos que o prompt já pede à ferramenta de imagem: frame `PERSONAGEM` e `CENA`, item 4.5). A imagem que chega **nem sempre obedece** o formato pedido, então **o quadro é escolhido pela imagem real** (`orientacao` do servidor, item 6.9: altura > largura = retrato; o resto, inclusive a quadrada, = paisagem) e, **se a proporção da imagem for diferente da do quadro, o espaço que sobra é preenchido de preto e a imagem fica centralizada** (*letterbox*). O layout do texto, portanto, **nunca depende** de a ferramenta ter acertado a proporção. *Alternativa descartada:* decidir o quadro pelo `Frame.tipo` (erraria quando a ferramenta ignora a proporção).
- **I2 — Retrato: duas colunas.** A partir do **começo do parágrafo** do artefato (item 3.4g), a região vira **duas colunas**: o **texto continua à esquerda** e o **quadro retrato 2:3 fica à direita**. Quando o quadro termina, o texto **volta a uma coluna só**.
- **I3 — Paisagem: o texto é interrompido e a imagem ocupa a largura.** O quadro 16:9 ocupa a **largura da área de leitura**, **antes do parágrafo** da posição do artefato, e o texto **continua embaixo**. *Revisto em 01/10/2026:* a primeira ideia era cortar o texto no fim de uma frase (pontuação final) dentro do parágrafo; o Allan simplificou: **a imagem entra no começo do parágrafo** (a posição já guarda o início do parágrafo, item 3.4g). O corte no meio do parágrafo fica como ajuste possível **depois de testar no tablet**.
- **I4 — Tocar na imagem a abre no tamanho normal** (tela cheia, o arquivo `original`; zoom com pinça; voltar fecha). Vale para o **capítulo**; nos demais lugares (painel de IA, ficha do elemento, catálogo de artefatos) o desenho é **decidido depois** (Allan, 01/10/2026).
- **I5 — Cada lugar carrega o tamanho certo** (item 6.9): `leitura` entre os parágrafos; `miniatura` na margem, nas listas e no painel; `original` só na tela cheia (e no nível "Baixado" do item 7.0a).
- **I6 — A imagem mostrada é a mais recente do frame** (item 3.4g), e só artefatos `ILUSTRADO` ganham imagem no texto.
- **I7 — Imagem sem dimensões** (importada antes de o servidor guardá-las): o servidor as calcula na primeira leitura; enquanto vierem nulas, o app trata como paisagem.
- **I8 — Onde a imagem aparece** além do capítulo: o **painel de IA do capítulo** (aba "Gerados"), a **ficha do elemento** e o **catálogo dos artefatos do capítulo** — todos com a `miniatura`.

**O botão de IA.** Um botão **fixo no canto inferior direito**. **Some ao rolar para baixo e reaparece ao rolar para cima**; também fica visível ao chegar ao topo ou ao fim do capítulo, para não haver um ponto da tela sem acesso a ele. (Um botão arrastável foi cogitado e descartado: obriga a arrastar, e a posição fixa é mais simples e acessível.)

**O painel de IA**, no padrão do app *JW Library*, segundo o Allan:
- **Tablet (tela larga): aside lateral direito**, que divide a tela com o texto.
- **Celular: uma tela própria de IA.** No lugar do botão de IA aparece um botão para **voltar ao texto**, no mesmo canto.
- **Três abas** (o desenho detalhado vem depois): **Sugestões** (elementos e cenas: confirmar, ajustar, descartar), **Gerados** (frames, prompts e imagens, com o que está esperando imagem; aqui fica o **importar imagem**, no item do prompt) e **Capítulo** (analisar, reanalisar, configurações da IA).
- **Tocar num artefato abre o painel naquele item; tocar num item do painel leva o texto até a posição dele.**

**O fluxo de um artefato**
1. "Analisar com IA" (aba Capítulo) gera as sugestões, agora com posição (item 3.4g).
2. O usuário toca num artefato. No de **cena**, abre uma folha de revisão com o resumo e os participantes, destacando os de `casamento_automatico=true` (item 4.6). No de **elemento**, pode confirmar, ajustar ou descartar; confirmado, oferece "Novo retrato".
3. As ações são **Gerar prompt** e **Gerar imagem**. *(Proposta, a confirmar com o Allan: "Gerar prompt" confirma a sugestão junto — cria o frame a partir de `sugestao_cena_id` — desde que o usuário tenha passado pela folha de revisão. O item 4.6 pede sinalizar o casamento automático, nunca pular a revisão.)*
4. Com o prompt pronto: copiar, colar na ferramenta externa, salvar a imagem na galeria, voltar ao app e **importar** (seletor do sistema, `POST /prompts/{id}/imagens`). O artefato passa a `ILUSTRADO` e a imagem entra no texto.

**Gerar imagem: lugar reservado.** O botão existe na interface, **desabilitado**, com uma explicação curta ao tocar ("ainda não disponível"). Não há campo no banco nem rota no servidor. Continua só o OpenRouter (item 4.1); o contrato será definido quando se verificar o que ele oferece para geração de imagem — o que ainda **não foi verificado**.

**Arquitetura no app.** O estado da tela de Capítulo vai crescer, e o `LivroViewModel` já tem mais de 600 linhas. Por isso a tela nasce com **dois ViewModels**: um da **leitura** (texto, parágrafos, artefatos) e outro do **painel de IA** (sugestões, geração, importação), que se falam por um **"item selecionado" compartilhado**, no escopo da tela de Capítulo. Os detalhes ficam para o primeiro incremento.

**Entrega em etapas** (substitui a lista antiga; cada uma testável no tablet). As posições no texto dependem de trabalho no servidor, então o app **não espera por elas**: as colunas são opcionais, e a lista de sugestões funciona sem posição.

- **Incremento 9 do app — o painel de IA e a lista de sugestões, sem posição no texto.** *Servidor:* `GET /capitulos/{id}/sugestoes` (item 6.8, pequeno e com teste). *App:* o **botão de IA** (canto inferior direito; some ao rolar para baixo, reaparece ao rolar para cima e nas pontas); o **painel** (aside no tablet, tela própria no celular, com o botão de voltar ao texto no mesmo canto); ao abrir o painel, o app **lê** as sugestões salvas (`GET`, sem custo); **"Analisar com IA"** (só quando `gerado_em` é nulo) e **"Reanalisar"** (com aviso de que refaz as sugestões ainda não confirmadas e gasta IA) chamam o `POST`; a **lista** de elementos e cenas com os destaques do item 7.5 (`casamento_automatico`, "casada mas ainda não virou Estado", `sugestoes_pendentes_anteriores`). Erros do provedor (422 de configuração, 502) aparecem com a mensagem da API. **A leitura do texto continua instantânea e não depende de nada disto.**
- **Incremento 10 do app — revisar e confirmar, dividido em dois (30/09/2026):** **10a — confirmar elementos** (criar, vincular a um existente, confirmar o casamento automático, registrar estado, esconder) e **10b — a cena** (o modal de revisão com resumo e participantes, confirmar, "Gerar prompt", copiar e "Novo retrato"). Nesta ordem porque o servidor só cria o frame de uma cena quando todos os participantes já são elementos confirmados com estado.
- **Servidor, em paralelo ou antes do 11:** `trecho_ancora`, `posicao_no_texto` (com nome primeiro para elementos, item 3.4g), `tipo_do_elemento` nos artefatos e `GET /capitulos/{id}/artefatos`.
- **Incremento 11 do app — os ícones no texto.** Artefatos na margem (um ícone por tipo), "Ilustrar aqui", tocar num artefato abre o painel naquele item.
- **Incremento 12 do app — imagens no texto.** Importar a imagem e desenhá-la entre os parágrafos (biblioteca de imagens, cache, tela cheia); imagens reduzidas no servidor.
- **Mais adiante, quando o Allan decidir:** "Gerar imagem" de verdade.

**A análise vale também em capítulo arquivado** (decisão do Allan, 30/09/2026): o backend não bloqueia, "arquivado" é só organização (item 7.5a, revisão do incremento 6), e a importação erra ao sugerir arquivamento — o usuário não precisa restaurar um capítulo só para analisá-lo.

#### Incremento 9 do app em detalhe — o painel de IA e a lista de sugestões

Regras de negócio, numeradas como **P1 a P15**. O desenho visual (posição exata, animação, ícones) é refinado depois; aqui valem as regras. **Só leitura e análise**: confirmar, ajustar e descartar são do incremento 10.

**O painel e quando ele carrega**
- **P1 — O texto nunca espera pelo painel.** O capítulo abre e é lido exatamente como no incremento 8; o painel só carrega o que precisa **na primeira vez que é aberto**, e guarda o resultado enquanto a tela de Capítulo existe (não relê a cada abrir e fechar).
- **P2 — Abrir o painel é sempre uma leitura**: `GET /capitulos/{id}/sugestoes` (item 6.8), que **nunca gera nem cobra**. Quatro estados: **Lendo**, **Nunca analisado** (`gerado_em` nulo), **Pronto** (há sugestões, ou a análise rodou e não achou nada) e **Erro** (motivo + "Tentar de novo").
- **P3 — O botão de IA.** Canto inferior direito. **Some ao rolar para baixo e reaparece ao rolar para cima**, e fica visível no topo e no fim do texto (item 7.5b). Só a **direção da rolagem** decide, acima de um pequeno limiar, para um tremor do dedo não esconder o botão.
- **P4 — Celular × tablet.** *(Decisão do Allan, 30/09/2026: o aside só aparece em **paisagem** no tablet, porque um tablet de ~11" em retrato fica em torno de 800 dp, abaixo do limiar. Mantido assim por enquanto; **revisitar quando as imagens entrarem no texto**, para ver se o aside cabe em retrato.)* Em **tela larga** (a partir de ~840 dp), o painel é um **aside à direita**, dividindo a tela com o texto, que continua rolável. Em tela **estreita**, o painel ocupa a **tela inteira**, e **o botão de IA vira "voltar ao texto"**, no mesmo canto. Se o painel está aberto, isso **sobrevive a girar o aparelho**.
- **P5 — Capítulo arquivado abre o painel** e pode ser analisado (item 7.5b).

**Analisar e Reanalisar — o único ponto que gasta IA**
- **P6 — "Analisar com IA" só existe quando o capítulo nunca foi analisado.** Chama `POST` **sem** `forcar`. Enquanto roda: estado **Analisando**, o botão fica desabilitado, e a tela diz que pode levar até um minuto. **Nada mais chama o `POST`.**
- **P7 — "Reanalisar" só existe depois de analisado**, e pede **confirmação**: *"Isso refaz as sugestões ainda não confirmadas e gasta IA. As já confirmadas ficam."* Só então chama `POST` com `forcar=true`.
- **P8 — Falha na análise não perde nada.** O erro mostra a **mensagem da API** (422: falta chave ou modelo, ou o texto não cabe no modelo; 502: o provedor falhou) e a tela **volta ao estado de antes** — a lista antiga continua ali, ou "Nunca analisado" continua oferecendo o botão. Nunca há **repetição automática**: repetir sozinho seria cobrar duas vezes sem ninguém pedir.
- **P9 — Sair da tela no meio de uma análise.** O app cancela a espera, mas **o servidor pode terminar e salvar** (a análise não depende de o app continuar ouvindo). Ao reabrir o painel, o `GET` mostra o resultado, ou "Nunca analisado" se não terminou. *(Limite conhecido, registrado no item 6.8: tocar em "Analisar" de novo enquanto o servidor ainda roda a primeira vez pode disparar duas análises.)*
- **P10 — Tempo de espera próprio.** Uma análise por IA leva de alguns segundos a mais de um minuto, bem além do tempo de espera comum do app (30 s), que a daria como falha enganosamente. **Só esta chamada** tem um tempo de espera maior (180 s); todas as outras seguem com 30 s, para uma falha de conexão continuar aparecendo depressa.

**O que a lista mostra**
- **P11 — Aviso de pendências anteriores.** Se `sugestoes_pendentes_anteriores > 0`: *"Você tem N sugestões não confirmadas em capítulos anteriores — confirmar primeiro deixa esta análise mais precisa."* **Não bloqueia nada.** Aparece onde ajuda a decidir: antes de analisar e no diálogo de reanalisar.
- **P12 — Cada elemento** mostra tipo, nome e a identidade (`descricao`), com os **destaques** do item 7.5, na ordem de importância: (a) **"Casado automaticamente — confira"** quando `casamento_automatico` (ninguém revisou esse casamento, item 4.6); (b) **"Casado, mas ainda sem estado neste capítulo"** quando `elemento_id` existe e `estado_id` é nulo (item 3.4e); (c) **"Já cadastrado"** quando `elemento_id` existe e o casamento foi revisado; e, à parte, (d) "mantém o estado conhecido" quando `manter_estado_atual`.
- **P13 — Cada cena** mostra título, descrição e, **só quando existem**, horário, clima e humor; e os participantes (tipo e nome), com o mesmo destaque de casamento automático.
- **P14 — Análise que não achou nada** é um resultado, e não um erro: *"A análise não encontrou elementos nem cenas neste capítulo."*, com Reanalisar disponível.
- **P15 — Nada aqui altera dado.** A lista é **somente leitura** neste incremento; as ações por sugestão chegam no 10.

**Implementado (30/09/2026):** no servidor, `GET /capitulos/{id}/sugestoes` (8 testes, 332 no total); no app, `rede/Sugestoes.kt` (DTOs), `RepositorioDeSugestoes` (ler × analisar, separados de propósito), o interceptador do tempo de espera (`X-Timeout-Leitura`, removido antes de sair), `telas/capitulo/painel/` (`PainelDeIaViewModel`, `RegrasDoPainel` com os destaques, a visibilidade do botão e a decisão aside × tela cheia, e `PainelDeIa`) e a integração em `TelaCapitulo` (botão de IA, aside no tablet, tela cheia no celular, `BackHandler`). **306 testes de unidade no app** (54 novos). **Falta a verificação manual no tablet, com o servidor reconstruído.**

**Testes:** o `ViewModel` do painel (cada estado e transição, P6 a P10, P14), o texto dos destaques (P12), a lógica de mostrar/esconder o botão ao rolar (P3), a decisão aside × tela cheia (P4), desserialização com JSON **real** do backend, e o `MockWebServer` para o `GET`, o `POST`, o `POST ?forcar=true` e o tempo de espera maior.

#### Incremento 10a do app em detalhe — confirmar elementos (especificado em 30/09/2026)

**Por que elementos antes de cenas (decisão do Allan, 30/09/2026).** O plano original fazia o 10 em bloco. Ao dividi-lo, a ordem natural era "cenas primeiro, que é o que gera a imagem" — mas o servidor **recusa** criar o frame de uma cena (`POST /capitulos/{id}/frames` com `sugestao_cena_id`, item 6.4) enquanto qualquer participante não for um elemento confirmado **e** tiver algum estado até aquele capítulo (422: "Confirme primeiro os elementos desta cena"). Então o 10 se divide assim: **10a — confirmar elementos** (este) e **10b — a cena: revisar, confirmar, gerar prompt, copiar e "Novo retrato"**. Só depois do 10a o 10b funciona de ponta a ponta.

**O que o 10a entrega:** a lista de elementos do painel de IA deixa de ser só leitura e ganha **ações por elemento**. Só usa rotas que **já existem** no servidor (itens 6.3 e 6.8); nenhuma mudança de backend.

Regras de negócio, **E1 a E10**:

- **E1 — Quatro situações, derivadas dos campos que a API já devolve** (P12). Cada uma oferece as suas ações:

| Situação (campos) | Rótulo | Ações |
|---|---|---|
| `elemento_id` nulo | **Nova** | **Criar elemento**, **Vincular a um existente**, **Esconder** |
| `elemento_id` preenchido e `casamento_automatico` | **Casada automaticamente — confira** | **Confirmar** (está certo), **Trocar** (vincular a outro) e **Desfazer** (volta a "Nova") |
| `elemento_id` preenchido, revisada, `estado_id` nulo | **Casada, mas sem estado neste capítulo** | **Registrar estado** |
| `elemento_id` e `estado_id` preenchidos | **Confirmada** | nenhuma (já pode ser usada numa cena, 10b) |

- **E2 — Criar elemento.** Abre um diálogo **já preenchido** com o que a IA identificou — tipo, nome e identidade (`descricao`) —, **editáveis**: é aqui que o usuário "ajusta" (corrige o nome, troca o tipo). Confirmar chama `POST /livros/{livro_id}/elementos` com `tipo`, `nome`, `descricao` e `sugestoes_elemento_ids: [id da sugestão]`; o servidor cria o elemento **e** o estado deste capítulo numa chamada só, e liga a sugestão. `409` (já existe um elemento com esse nome e tipo): mostra a mensagem da API no diálogo e oferece **"Vincular a um existente"** em vez de criar outro.
- **E3 — Vincular a um existente.** Abre uma lista dos elementos do livro (`GET /livros/{id}/elementos`), **com busca por nome** e os do **mesmo tipo primeiro**. Escolher um chama `POST /elementos/{id}/estados-de-sugestoes` com `[id da sugestão]`, que **liga a sugestão e cria o estado** deste capítulo, tudo numa chamada. Serve quando a IA chamou de "Hospius" quem o livro já cadastrou como "Sextus Hospius" (item 3.4e).
- **E4 — Confirmar o casamento automático.** `PATCH /sugestoes-elemento/{id}` com o **mesmo** `elemento_id`: o servidor passa `casamento_automatico` a falso (item 4.6). **Não cria estado**; a situação passa a "casada, mas sem estado" (ou "confirmada", se já havia estado).
- **E5 — Trocar e Desfazer.** **Trocar** abre a lista de E3 e, ao escolher, faz **só** o `PATCH` com o novo `elemento_id` (sem criar estado: se faltar, a sugestão passa a "casada, mas sem estado" e o usuário toca em **Registrar estado**; se já houver, passa a "confirmada" — assim o app nunca tenta criar um estado duplicado). **Desfazer** faz `PATCH` com `elemento_id: null` (sem estado nenhum). Se um estado já havia sido criado no elemento errado, ele **continua lá**: o app **avisa** ("o estado criado no elemento anterior não foi apagado") em vez de apagar sem perguntar.
- **E6 — Registrar estado.** `POST /elementos/{elemento_id}/estados-de-sugestoes` com `[id da sugestão]`. A descrição do estado é **um rascunho, vinda da identidade** (item 3.4e): a leitura profunda a refaz sozinha na primeira vez que um prompt for gerado. O app **diz isso** ao registrar.
- **E7 — Esconder (o "descartar" de hoje).** *(Superada pela regra E16, da rodada 2, abaixo: o descartar agora é no servidor e o "esconder" local foi retirado.)* *(Decisão do Allan, 30/09/2026: não existe rota de descartar no servidor; por ora a sugestão só é **escondida no aparelho**. Pendência registrada na Etapa 8.)* Só para a situação **Nova**. Some da lista e de **"Esconder" volta por "Mostrar escondidas (N)"**, no fim da lista. Fica guardado **no aparelho** (tabela local), por capítulo e por servidor; **não sincroniza entre aparelhos** e **não muda nada no servidor**. Uma **reanálise** gera sugestões novas (ids novos), então as escondidas voltam a aparecer — é o comportamento esperado enquanto não houver descartar de verdade.
- **E8 — Depois de cada ação que dá certo, o painel relê** as sugestões (`GET`, que nunca gasta IA), **sem** voltar ao estado "Lendo": a lista se atualiza no lugar, sem perder a posição de rolagem. Assim a tela mostra o que o servidor de fato tem, e não uma suposição.
- **E9 — Uma ação por vez em cada elemento.** Enquanto roda, os botões daquele elemento ficam desabilitados e mostram um indicador. Se falhar, a **mensagem da API** aparece no próprio elemento e **nada muda** (nenhuma repetição automática). **Sem conexão**, as ações falham com o aviso de sempre: nada fica em fila (regra A7).
- **E10 — Nenhuma ação do 10a gasta IA.** São todas rotas de cadastro. A IA só roda em **Analisar/Reanalisar** (P6, P7) e ao **gerar o prompt** (10b).

**Implementado em 30/09/2026 (app: 370 testes, 32 deles novos; ainda a validar no tablet).** Em linguagem simples: cada elemento sugerido no painel de IA ganhou botões conforme a situação dele (criar, vincular, confirmar, trocar, desfazer, registrar estado, esconder). Depois de cada ação, o painel pergunta de novo ao servidor e mostra o que ele de fato tem. Nenhuma ação usa IA.

**Onde está o código (app):** `RepositorioDeElementos` (`rede/`: listar, criar, registrar estado, ajustar casamento), `PainelDeIaViewModel` (as ações E1 a E10 e os diálogos), `RegrasDoPainel` (`situacaoDoElemento`, `acoesDoElemento`, `filtrarParaVincular`), `PainelDeIa` (botões e diálogos), e, para o "esconder", a tabela local `sugestao_escondida` (`local/EscondidasLocais`).

**Divergências do plano:** (1) o banco do aparelho passou à **versão 2** (tabela nova); como a cópia local é descartável (A10), a migração é "apagar e refazer", o que **esvazia o cache de textos uma vez** — o app baixa de novo o que for lido. (2) **Trocar** não cria estado (texto da regra E5 ajustado acima). (3) O diálogo de criar tem o botão **"Vincular a um existente"** só depois de um 409.

**O que não entra no 10a:** qualquer coisa de **cena** (revisão, confirmar, gerar prompt, copiar) e **"Novo retrato"** — são do 10b; **"Confirmar todos"** em lote (pode vir depois, se a lista longa incomodar); descartar de verdade (pendência).

**Testes.** O `ViewModel` do painel (cada ação, sucesso e falha, o relê depois da ação, E9 em uma por vez, E7), a regra que decide a situação e as ações de cada elemento (E1), o `MockWebServer` para cada rota nova (método, caminho, corpo) e a desserialização com JSON **real** do backend.

#### Incremento 10a, rodada 2 — correções do teste no tablet (30/09/2026)

**O que o Allan encontrou testando o 10a**, e o que se descobriu ao investigar:

1. **As sugestões de personagens já cadastrados mostravam o estado do capítulo 1 no capítulo 4.** *Verificado no banco real:* em cerca de metade das sugestões de elementos já conhecidos, a descrição era **idêntica** ao estado do capítulo anterior. **Causa:** ao analisar, o servidor entregava à IA o "último estado de aparência" de cada elemento, e a IA o copiava para a sugestão. Isso também fazia "Registrar estado" criar, no capítulo 4, um estado que era cópia do do capítulo 1. **Decisão do Allan:** mandar o estado anterior só confunde a IA; o que vale é o **compilado que define quem é o personagem** (a identidade vigente, item 3.4f) — e o usuário precisa **ver esse histórico** para decidir a qual personagem associar uma sugestão.
2. **Vincular e Trocar não permitem editar; "esconder" não resolve.** O certo é **descartar** de verdade, para a sugestão sair das pendentes em todos os aparelhos.
3. **Depois de confirmada, a sugestão não pode ser editada.** Ações permanentes são ruins para a experiência: toda confirmação precisa ter caminho de volta.
4. *(achado ao investigar)* **"Desfazer" não desfazia.** O casamento automático roda a cada leitura e religava a sugestão ao mesmo elemento logo em seguida.

**Servidor — implementado em 30/09/2026 (394 testes; 17 novos).** Migration `f9a4c6e8b0d3`.
- **A IA passa a receber a identidade, nunca a aparência.** O contexto da extração é, para **cada elemento do livro**, `Nome (TIPO): identidade vigente até o capítulo anterior` (`Elemento.descricao` mais o histórico de identidade, item 3.4f) — sem a descrição de aparência de nenhum capítulo. O parâmetro do provedor passou de `estados_conhecidos` para `elementos_conhecidos`. A instrução manda usar **exatamente o nome da lista** e dizer em `descricao` só quem ou o que é, sem copiar. **`manter_estado_atual` deixou de ser pedido à IA** (sem o estado, ela não tem como julgar): o campo continua na resposta, sempre `false` em sugestões novas, e **o app deve ignorá-lo**. Vale a partir da próxima análise de cada capítulo; o que já está salvo não é reescrito.
- **Cada sugestão casada traz, na resposta:** `elemento_casado` (`id`, `tipo`, `nome` e a **`identidade`** vigente até aquele capítulo) e `estado_vigente` (`id`, `capitulo_id`, `ordem_do_capitulo`, `descricao` — o estado que **vale** neste capítulo, possivelmente vindo de um capítulo anterior; nulo se o elemento ainda não tem estado). `estado_id` continua sendo o estado **deste** capítulo.
- **Descartar.** Coluna `descartada` em `SugestaoDeElemento` e em `SugestaoDeCena`; `PATCH /sugestoes-elemento/{id}` e `PATCH /sugestoes-cena/{id}` com `{"descartada": true|false}`. A descartada **sai das pendentes** (`sugestoes_pendentes` do capítulo e `sugestoes_pendentes_anteriores`), **não é casada automaticamente** e **sobrevive a uma reanálise**: a IA repetir a mesma (mesmo tipo e nome; ou mesmo título de cena) **não a recria**. Continua na lista, marcada `descartada: true`, para o app oferecer "Restaurar". **Só se descarta o que não está ligado:** uma sugestão com `elemento_id` responde `409` (desfaça o casamento antes); uma cena que já virou Frame também.
- **Desfazer de verdade.** Coluna `casamento_desfeito`: `PATCH` com `elemento_id: null` a liga, e o casamento automático passa a **pular** essas sugestões. Ligar a um elemento de novo a desliga. O corpo do `PATCH` passou a levar **uma coisa por pedido** (`elemento_id` ou `descartada`; vazio ou os dois juntos = `422`) — antes `elemento_id` era obrigatório.

**App — implementado em 30/09/2026 (405 testes; ainda a validar no tablet).** Regras **E11 a E18**, que **revisam** as E1 a E10 acima (onde divergirem, valem estas):
- **E11 — O cartão separa três coisas:** **"Sugestão da IA"** (nome e `descricao`, a identidade sugerida); **"Casada com"** (`elemento_casado`: nome e identidade vigente — o que o usuário confere); e **"Estado neste capítulo"** (`estado_id`) **ou** **"Usa o estado do capítulo N"** (`estado_vigente`, com a descrição dele). O destaque "Mantém o estado conhecido" **some** (campo abandonado).
- **E12 — Situações revisadas.** "Casada, mas sem estado" só existe quando **não há estado nenhum** (`estado_vigente` nulo). Casada **com estado vigente** conta como **Confirmada**: uma cena usa o estado vigente (item 6.4), não exige um criado neste capítulo.
- **E13 — Vincular e Trocar mostram o histórico.** Cada elemento da lista é **expansível** e mostra a **identidade** (`GET /elementos/{id}`: `descricao` e `historico_identidade`) e os **estados por capítulo**, para o usuário saber de qual personagem se trata. O botão é **"Usar este"**. A lista continua com busca e os do mesmo tipo primeiro.
- **E14 — "Editar" em todo cartão** (inclusive Confirmada e depois de Vincular/Trocar): abre um diálogo com **(a)** *Quem é* — nome, tipo e identidade do **elemento** casado (`PATCH /elementos/{id}`); **(b)** *Estado neste capítulo* — a descrição do estado deste capítulo (`PATCH /estados/{id}`), ou **criar** um estado novo neste capítulo quando só há o vigente de outro (`POST /elementos/{id}/estados`); **(c)** *Desfazer confirmação*. No cartão **Nova**, "Criar elemento" continua sendo o editor (E2).
- **E15 — Desfazer confirmação.** `PATCH elemento_id: null` (vale de verdade). Se existe um estado **criado neste capítulo**, pergunta se também o **apaga** (`DELETE /estados/{id}`), **avisando** que frames que usam esse estado perdem esse participante (o servidor não impede). Nunca apaga sem perguntar; o elemento em si **nunca** é apagado por aqui.
- **E16 — Descartar substitui Esconder** (E7): só na situação **Nova**, com `PATCH descartada: true`. As descartadas saem da lista e vão para **"Descartadas (N)"**, no fim, com **"Restaurar"**. **Acaba a tabela local `sugestao_escondida`** (banco à versão 3; cópia descartável). Descartar é **imediato e reversível**, sem diálogo de confirmação.
- **E17 — "Trocar" e "Desfazer"** passam a existir também em **Confirmada** (via Editar), não só no casamento automático.
- **E18 — Cenas** (10b) herdam: descartar e restaurar cena, e o participante mostra com quem foi casado.

**Como ficou no app, em linguagem simples.** O cartão de cada elemento agora mostra três blocos com rótulo: **"Sugestão da IA"** (o que a IA escreveu), **"Casada com Fulano (tipo)"** e a identidade dele, e o **estado** dizendo de qual capítulo é ("Estado neste capítulo" ou "Usa o estado do capítulo 1"). Todo cartão confirmado tem **Editar**; dentro dele, além dos campos, ficam **Trocar elemento** e **Desfazer confirmação**. Ao escolher um elemento para vincular ou trocar, cada um da lista tem **Ver histórico** (quem é e como estava, capítulo a capítulo) e **Usar este**. **Descartar** sai do cartão na hora e vai para **Descartadas (N)**, com **Restaurar**.

**Divergências do plano, e o motivo:**
- **`GET /elementos/{id}` ganhou `ordem_do_capitulo`** em cada estado e em cada registro de identidade (campo novo e opcional, só preenchido nessa rota; 397 testes no servidor). O app precisava dele para escrever "Capítulo 3"; a alternativa era cruzar com a lista do livro, o que trazia mais uma dependência para o painel.
- **Desfazer direto** (sem diálogo) quando **não há estado neste capítulo**; só pergunta se há estado a apagar. Não havia o que perguntar no outro caso.
- **Descartar não pede confirmação** (E16): é imediato e reversível.
- **A tabela local `sugestao_escondida` foi retirada** e o banco do aparelho foi à **versão 3**; como a cópia é descartável (A10), o app apaga e refaz o cache de textos uma vez.
- **Em "Trocar"**, o estado do elemento anterior não é apagado (E5): o app avisa. O diálogo de desfazer é o único caminho que oferece apagar.
- **O editor só salva o que mudou** e, se falhar no meio (ex.: nome repetido), para na primeira falha: o que já foi salvo antes dela fica salvo.

**Decisões registradas (30/09/2026).** *Descartar no servidor, e não só no aparelho:* sincroniza entre aparelhos e tira a sugestão da contagem de pendentes; alternativa descartada: esconder localmente (não sincroniza, e a pendência continuava contando). *Descartadas ficam na reanálise:* coerente com as confirmadas, que também ficam; alternativa descartada: a reanálise limpar tudo que não foi confirmado (o descartado voltaria). *A IA recebe identidade, não aparência:* mandar a aparência a fazia copiá-la; a alternativa de só ajustar a tela deixaria o texto copiado nas sugestões.

**Risco conhecido:** apagar um estado que um frame usa tira esse participante do frame sem aviso do servidor (`ON DELETE CASCADE` na associação). O app avisa (E15); impedir no servidor fica como pendência se incomodar.

#### Incremento 10a, rodada 3 — a tela de Elementos e um painel que aguenta um livro grande (30/09/2026)

**O que o Allan encontrou no capítulo 8 de *A Vontade de Muitos*, e o que se apurou.**

1. **Nome quebrado em várias linhas na lista de vincular.** Nome, "Ver histórico" e "Usar este" dividiam a mesma linha; o nome ficava na coluna que sobrava.
2. **Personagens que aparecem nas cenas sugeridas precisam de marca:** descartar a sugestão de um deles pode comprometer a imagem da cena depois.
3. **O histórico de um personagem cresce sem parar.** Mostrá-lo dentro de um diálogo não escala; o lugar dele é uma **tela própria de elementos**, com a informação estruturada (identidade, descrição, estado de cada capítulo) e a opção de editar.
4. **Não estava claro de onde vêm "Sugestão da IA", "Casada com" e "Usa o estado do capítulo 8".** *Apurado:* (a) "Sugestão da IA" de um elemento já conhecido é só **a identidade que o servidor mandou à IA, devolvida por ela** — o elemento nasceu da sugestão do capítulo 1, então o texto do capítulo 1 voltava. Não informa nada. (b) "Casada com" mostrava a **identidade vigente inteira** (descrição inicial mais todos os acréscimos colados) **sem limite**, e o servidor também mandava à IA a identidade de **todos** os elementos do livro a cada análise: não escala. (c) O **"8" era a `ordem` do capítulo** (a posição no livro), e não o título: em *A Vontade de Muitos*, a posição 8 é o "Capítulo VI", porque "Créditos" e "Classificações" ocupam as posições 1 e 2. Nas telas de Livro o usuário vê **títulos**, então o número confundia.
5. **"Editar" deve levar à tela do elemento, e não a um modal** — a informação é muita.
6. **Elementos que não são personagens também evoluem** (veículo, navio, lugar, cidade). O servidor **já** guarda estados para qualquer tipo; faltava a tela e o vincular respeitarem o tipo: ao vincular, o usuário liga a algo **do mesmo tipo**.
7. **O mais importante: que informação a tela de sugestões mostra**, para não ficar sobrecarregada conforme o livro avança.

**Decisões do Allan (30/09/2026):** criar já a **tela de Elementos do livro** (item 7.8) em tela cheia, com lista e ficha; organizar o painel **compacto e por situação**; **limitar** o tamanho no servidor; e, ao descartar quem aparece numa cena sugerida, **marcar e pedir confirmação**.

**Servidor** *(implementado em 30/09/2026; 403 testes)*
- **S1 — Identidade resumida nas sugestões.** `elemento_casado.identidade` vem **resumida em até ~300 caracteres** (corte na última palavra inteira, terminando em `…`). A identidade completa só vem em `GET /elementos/{id}`.
- **S2 — Limite no contexto da IA.** Cada elemento entra como `Nome (TIPO): identidade` com a identidade cortada em **~200 caracteres**, e a lista inteira tem **teto de ~8.000 caracteres**, priorizando os elementos que apareceram **mais recentemente** (o capítulo do estado vigente mais novo, do mais recente para o mais antigo; quem não tem estado vai por último). O que não cabe fica fora: o casamento automático é **por nome, no servidor**, e não depende disso.
- **S3 — Título do capítulo.** `estado_vigente` (nas sugestões), cada estado e cada registro de identidade (em `GET /elementos/{id}`) trazem também `titulo_do_capitulo` (pode ser nulo: o app usa "Capítulo N", como na tela de Livro).

**App — regras E19 a E32** *(implementado em 30/09/2026; 423 testes; ainda a validar no tablet)* (revisam E11 a E18; onde divergirem, valem estas)
- **E19 — Capítulo sempre pelo título.** Onde o app dizia "capítulo 8", diz o **título** ("Capítulo VI"); sem título, "Capítulo N" com a `ordem`, como a tela de Livro.
- **E20 — A tela de Elementos do livro** (item 7.8), em tela cheia, aberta pelo botão **Elementos** da tela de Livro. **Lista** com busca por nome e filtro por tipo; cada linha mostra nome, tipo, quantos estados tem e um trecho do estado mais recente. Tocar abre a **ficha**.
- **E21 — A ficha do elemento:** cabeçalho com nome e tipo; **Quem é** (a identidade vigente, completa, com o que cada capítulo acrescentou em ordem); **Aparência por capítulo** (um cartão por estado, em ordem narrativa, com o título do capítulo). **Editar** nome, tipo e identidade; **editar** e **apagar** um estado; **apagar o elemento** (com aviso: leva os estados junto). Quando a ficha foi aberta a partir de uma sugestão e o capítulo dela **ainda não tem estado**, oferece **"Adicionar estado neste capítulo"**. *(Adicionar estado em qualquer outro capítulo fica como pendência.)*
- **E22 — "Editar" e "Ver histórico" do painel levam à ficha** (no lugar do modal "Editar" e da expansão dentro da lista). O diálogo de editar sai; **Trocar** e **Desfazer confirmação** continuam no painel, porque dizem respeito à **sugestão**, e não ao elemento.
- **E23 — Vincular e Trocar continuam sendo um diálogo**, agora **limpo**: o nome **em linha própria** (sem competir com botões) e os botões **embaixo**; lista **só do mesmo tipo** da sugestão, com a chave **"Mostrar outros tipos"**; cada item tem **"Ver ficha"**, que abre a ficha por cima — ao voltar, o diálogo reaparece como estava — e **"Usar este"**.
- **E24 — O painel é compacto e por situação.** No topo, três filtros com contadores: **Pendentes** (padrão: nova, casada automaticamente, casada sem estado), **Confirmados** e **Descartados**. O cartão **fechado** tem 1 ou 2 linhas: tipo e nome, **uma** etiqueta de situação e, se for o caso, **"Aparece em N cenas"**. **Tocar abre** os detalhes e as ações; o recado de uma ação (erro ou aviso) e o indicador de "em andamento" aparecem **também fechado**.
- **E25 — O que cada situação mostra ao abrir.** **Nova:** "Sugestão da IA" (a descrição). **Casada (qualquer):** "Casada com Fulano (tipo)" e um **trecho** da identidade (já resumida pelo servidor), com **"Ver ficha"**; **a "Sugestão da IA" deixa de aparecer**, porque só repete a identidade. **Estado:** "Estado neste capítulo" ou "Usa o estado de «título»", cortado em poucas linhas. As etiquetas do cartão fechado: **Nova**, **Casada — confira**, **Casada, sem estado**, **Confirmada**.
- **E26 — Elementos das cenas ficam marcados.** O cartão mostra **"Aparece em N cenas"**, e, aberto, os **títulos** delas (calculado no app, cruzando `participantes` das cenas com as sugestões; nenhuma mudança no servidor). Conta só cenas **não descartadas**.
- **E27 — Descartar quem aparece numa cena pede confirmação.** O aviso lista as cenas e diz que descartar pode atrapalhar a imagem delas; só descarta se o usuário confirmar. Sem cenas, continua **imediato** (E16).
- **E28 — As cenas também são compactas:** título e nº de participantes fechados; ao abrir, descrição, horário/clima/humor e participantes.
- **E29 — Ordem da lista:** o que precisa de ação primeiro (nova, casada automaticamente, casada sem estado), depois o resto, na ordem em que a IA listou.
- **E30 — Outros tipos.** Nada de específico para personagem: "Aparência" é o rótulo de qualquer tipo, e a ficha serve a veículo, lugar, objeto etc.
- **E31 — Um capítulo aberto pela ficha não perde o painel:** ao voltar da ficha, o painel **relê** as sugestões (E8), porque o que foi editado lá pode mudar o cartão.
- **E32 — Sem modo offline neste incremento.** A lista e a ficha dependem do servidor; sem conexão mostram o aviso de sempre (regra A7). Guardá-las no aparelho para leitura fica para depois.

**Como ficou, em linguagem simples.** O botão **Elementos** da tela de Livro agora abre uma **lista** (busca por nome e filtro por tipo); tocar num elemento abre a **ficha** (quem é, com o que cada capítulo acrescentou, e a aparência em cada capítulo, pelo título), de onde se edita, se apaga um estado ou o elemento inteiro. No painel de IA, cada sugestão é um cartão de **uma linha** com uma etiqueta (Nova, Casada — confira, Casada, sem estado, Confirmada), marcado com **"Aparece em N cenas"** quando é o caso; **tocar abre** os detalhes e os botões. No topo, três filtros com contadores — **Pendentes**, **Confirmados**, **Descartados** — e o painel abre nos pendentes.

**Divergências do plano, e o motivo:**
- **O botão "Editar" virou "Ver ficha"** (a edição vive na ficha, como pedido); **Trocar** e **Desfazer** ficaram no cartão de toda sugestão casada, inclusive a confirmada — dizem respeito à sugestão, não ao elemento.
- **Vincular/Trocar continua um diálogo** (limpo, só do mesmo tipo, com "Incluir outros tipos"), e não uma tela em "modo escolher": "Ver ficha" abre a ficha por cima e o diálogo volta como estava, porque o ViewModel do painel vive enquanto o capítulo estiver aberto. Uma tela de escolha inteira custaria mais e não traria nada a mais.
- **Na ficha, só se edita a identidade inicial.** *(Superado pela rodada 5: os acréscimos de cada capítulo passam a ser editáveis, e adicionar estado em qualquer capítulo existe.)*
- **`manter_estado_atual` some da tela** (o servidor ainda o devolve, sempre `false` em sugestões novas).
- **Sem limite de quantos cartões o painel desenha:** os filtros e o "abrir ao toque" bastam por ora; se um capítulo trouxer centenas de sugestões, a paginação entra como pendência.

**O que não entra:** adicionar estado em **qualquer** capítulo a partir da ficha; a aba de **Cenas** (confirmadas) da tela de Elementos — chega com o 10b, junto dos frames; visão offline da ficha.

#### Incremento 10a, rodada 4 — ajustes do teste da rodada 3 e mesclar elementos (30/09/2026)

**O que o Allan encontrou**, e o que se decidiu:

1. **"Adicionar estado neste capítulo" parecia um balão estranho.** Estava espremido ao lado do título da seção. *Ajuste:* passa a ser um **botão de largura total, abaixo do título**. Continua **só aparecendo quando a ficha é aberta a partir de um capítulo** (E21); a consulta geral de personagens e cenas pela tela inicial do livro será discutida adiante.
2. **Cartões confirmados apareciam abertos ao trocar de filtro, poluindo a tela.** Causa: quais cartões estavam abertos era lembrado por id, atravessando os filtros. **Regra E33:** os cartões **sempre** aparecem **compactos** ao entrar num filtro (Pendentes, Confirmados ou Descartados); um cartão que **muda de filtro** (por exemplo, ao ser confirmado) também volta compacto. Abrir continua sendo só um toque.
3. **"Quem é" é dinâmico?** *Resposta (sem mudança de comportamento):* sim, em parte. A identidade de um elemento é a **descrição inicial** (o que a IA descreveu quando ele foi criado, editável pela ficha) **mais os acréscimos que cada capítulo revela**. Os acréscimos são gravados pelo **servidor sozinho**, mas **só quando um prompt é gerado** para um frame que usa o elemento naquele capítulo (leitura profunda de identidade, item 4.4, fase 2b): a IA relê o capítulo e, se ele revelar algo **novo** sobre quem o elemento é, grava um acréscimo — no máximo **um por elemento e capítulo**. Então a ficha **cresce conforme se geram imagens ao longo do livro**; confirmar sugestões, sozinho, não a alimenta. *Possível melhoria, não decidida:* permitir ao usuário acrescentar e corrigir acréscimos à mão na ficha.
4. **Um elemento duplicado com outro tipo não dá para juntar.** Um elemento foi cadastrado como veículo e outro, com o mesmo nome, como ambiente; eram o mesmo. Mudar o tipo de um para o do outro dá **409** (o servidor não aceita dois elementos com o mesmo tipo e nome no livro, item 6.3), e a ficha não tinha como **associar** um ao outro.

**Decisão de desenho para o ponto 4: mesclar elementos.** *Mesclar* junta um elemento ("origem") **dentro de outro** ("destino"): tudo que era da origem passa a ser do destino, e a origem deixa de existir. O servidor ganha uma rota; a ficha ganha o botão.

**Servidor** *(`POST /elementos/{id}/mesclar`, item 6.3)*
- **Corpo:** `{"destino_id": N}`. **Resposta:** a ficha (`ElementoDetalhe`) do **destino**, já com tudo junto.
- **O que passa da origem para o destino:** **todos os estados** de aparência (e, portanto, os frames que os usam continuam funcionando, porque a ligação é com o estado); **todos os acréscimos de identidade**; e **as sugestões de elemento** casadas com a origem (passam a estar casadas com o destino).
- **O que fica do destino:** nome, tipo e identidade inicial. **Se o destino não tem identidade inicial, ganha a da origem.** A referência visual padrão (`imagem_ancora_padrao_id`) é a do destino; se ele não tem, ganha a da origem.
- **Erros:** `404` se um dos dois não existe; `422` se forem o mesmo elemento ou de livros diferentes. Nada é alterado em caso de erro (tudo numa transação).
- Sobe a revisão do livro (item 6.9), como qualquer mudança.

**Implementado em 30/09/2026** *(servidor: 414 testes, 11 deles da mesclagem; app: 434 testes; ainda a validar no tablet).* A rota nasceu exatamente como especificada. **Um detalhe de implementação:** os estados, o histórico e as sugestões são movidos por atualização em massa **antes** de apagar a origem, porque a relação `Elemento.estados` apaga o que sobrar nela; sem isso, apagar a origem levaria junto os estados que acabaram de passar para o destino.

**App — regras E33 a E37**
- **E33 — Cartões sempre compactos ao trocar de filtro** (ponto 2), inclusive o que muda de filtro.
- **E34 — "Adicionar estado neste capítulo"** em botão próprio, largura total, abaixo do título da seção (ponto 1).
- **E35 — "Mesclar com outro elemento"** na ficha (menu da barra superior). Abre a **lista dos outros elementos do livro**, com busca **já preenchida com o nome do elemento** (quase sempre o duplicado tem o mesmo nome) e com o tipo de cada um. Escolher um pede **confirmação**: *"«Jon» (Ambiente) será juntado a «Jon» (Veículo): estados, identidade e sugestões passam para o escolhido, e «Jon» (Ambiente) deixa de existir. Isso não pode ser desfeito."* Confirmado, a ficha volta para a lista. **Para manter o outro como o principal, abra a ficha dele e mescle no sentido contrário.**
- **E36 — O 409 ao editar explica e aponta a saída.** Quando editar nome ou tipo dá conflito, o diálogo mostra a mensagem do servidor e a dica **"Se são o mesmo elemento, use Mesclar com outro elemento."**
- **E37 — Mesclar tem de refletir no painel:** ao voltar para o capítulo, as sugestões se releem (E31) e mostram o elemento já mesclado.

#### Incremento 10a, rodada 5 — acrescentar e corrigir a identidade à mão (30/09/2026)

**Pedido do Allan:** poder **acrescentar e corrigir à mão** os acréscimos de identidade de um elemento (o que cada capítulo revela sobre **quem** ele é, item 3.4f), que até aqui só o servidor gravava, ao gerar prompts. E uma dúvida: **a mesclagem leva todos os estados do elemento?** *Sim* — estados, histórico de identidade e sugestões passam para o destino. **Nuance:** se os dois elementos tinham estado **no mesmo capítulo**, **os dois ficam** (o banco não impede dois estados do mesmo elemento no mesmo capítulo, item 3.1); o usuário apaga um deles na ficha, se quiser.

**Servidor** *(item 6.3)*
- **`POST /elementos/{id}/historico-identidade`** `{capitulo_id, descricao}` → `201` com o acréscimo. O capítulo tem de ser **do mesmo livro** do elemento (`422` senão). Um acréscimo manual **vale como o do servidor**: o servidor só tenta gerar um acréscimo automático para um par (elemento, capítulo) que **ainda não tem** nenhum (item 4.4, fase 2b), então escrever um à mão **impede** o automático naquele capítulo.
- **`PATCH /historico-identidade/{id}`** `{descricao}` — corrige o texto. **`DELETE /historico-identidade/{id}`** — apaga (`204`). `404` se não existe. A descrição não pode ser vazia (`422`).
- Cada resposta de `GET /elementos/{id}` já traz `ordem_do_capitulo` e `titulo_do_capitulo` nos acréscimos; os de uma criação trazem também.
- Sobe a revisão do livro (item 6.9), como qualquer mudança.

**Implementado em 30/09/2026** *(servidor: 424 testes, 10 dos acréscimos e 1 da mesclagem no mesmo capítulo; app: 450 testes; ainda a validar no tablet).* Em linguagem simples: na ficha, cada acréscimo de identidade tem **Editar** e **Apagar**, e há **Adicionar acréscimo**; para acrescentar, o app pede **o capítulo** (lista pelo título, com busca) — ou já usa o capítulo de onde você veio. A mesma escolha de capítulo serve ao novo botão **Adicionar estado em outro capítulo**, que fecha a pendência da rodada 3. O aviso do editor de elemento ("os acréscimos não são editados aqui") saiu, porque agora são. **Divergências:** nenhuma de regra; a lista de capítulos vem do repositório de livros (que responde do aparelho quando pode), e capítulos **arquivados** aparecem marcados, sem bloqueio.

**App — regras E38 a E41**
- **E38 — Cada acréscimo da ficha** (seção "Quem é") mostra o capítulo (pelo título) e o texto, com **Editar** e **Apagar**; apagar pede confirmação.
- **E39 — "Adicionar acréscimo"** na seção "Quem é". Pede **primeiro o capítulo** (lista dos capítulos do livro, **pelo título**, com busca) e depois o texto. **Se a ficha foi aberta a partir de um capítulo, esse capítulo já vem escolhido**, sem a lista.
- **E40 — "Adicionar estado" em qualquer capítulo.** O mesmo seletor de capítulo (E39) passa a servir à seção "Aparência por capítulo": o botão "Adicionar estado neste capítulo" (E34) continua só quando a ficha veio de um capítulo sem estado, e agora há também **"Adicionar estado em outro capítulo"**, que fecha a pendência anterior.
- **E41 — Texto vazio é recusado** nos dois (acréscimo e estado), com a mensagem no próprio diálogo, sem chamar o servidor; falha do servidor mostra a mensagem da API no diálogo.

#### Incremento 10b, primeira fatia — a cena: revisar, confirmar, descartar e restaurar (especificado e implementado em 01/10/2026; 538 testes; falta validar no tablet)

O 10b (a cena) foi dividido em três fatias, cada uma testável no tablet: **(1) esta** — revisar, confirmar, descartar e restaurar a cena; **(2)** "Gerar prompt" e copiar; **(3)** "Novo retrato". Nenhuma delas importa imagem (isso é o incremento 12). O servidor já tem tudo (itens 6.4, 6.7 e 6.8); a única mudança lá foi o `frame_id` na cena (D2).

**Regras (C1 a C10):**

- **C1 — Duas portas, um só modal.** Tocar no **cartão da cena** (painel) ou no **artefato de cena** no texto abre o **modal da cena**: a mesma folha do modal do elemento (E42). *Corrige um defeito:* até aqui o toque no ícone de cena chamava o modal de **elemento** com o id da cena; os ids são de tabelas diferentes, então abriria o elemento errado (ou "não existe mais").
- **C2 — ~~Um modal por vez.~~ *Substituída pelo C12 (pilha de modais), a pedido do Allan em 01/10/2026.*** Antes: abrir o modal da cena fechava o do elemento, e vice-versa. O estado mora no ViewModel, como o do elemento, e vale a regra do D3: o modal só é desenhado com o capítulo `RESUMED`.
- **C3 — O que o modal mostra.** Título, descrição, horário/clima/humor e **cada participante** (tipo e nome) com a sua situação: **"Sem elemento — revise"** (ainda não é um elemento cadastrado), **"Casamento automático — confira"** (P13) ou "Casado com *Nome*". O participante **sem elemento** ganha o botão **"Revisar"**, que **fecha o modal da cena e abre o modal daquele elemento** (para confirmar, vincular ou criar); é o caminho mais curto para destravar a cena.
- **C4 — Ações por situação.** **Pendente:** *Confirmar cena* (a principal) e *Descartar*. **Confirmada** (já virou frame): nenhuma ação de decisão (o *Gerar prompt* chega na fatia 2). **Descartada:** *Restaurar*.
- **C5 — Confirmar a cena.** `POST /capitulos/{id}/frames` com `sugestao_cena_id` (o servidor usa o estado vigente de cada participante). **Sucesso:** relê as sugestões e os artefatos; a cena passa para **Confirmadas**, o modal fecha (como o E44) e o cartão mostra "Cena confirmada". **422** (falta confirmar um elemento ou registrar um estado): a **mensagem do servidor** aparece no modal, **sem fechar**. **409** (a cena já foi confirmada, por exemplo em outro aparelho): relê, fecha e avisa "Esta cena já estava confirmada".
- **C6 — Descartar e restaurar** são imediatos, reversíveis e **sem confirmação** (como o E16): `PATCH /sugestoes-cena/{id}`. Cena descartada vai para **Descartadas**, de onde se restaura.
- **C7 — Uma ação por cena de cada vez** (como o E9): enquanto uma roda, os botões ficam desabilitados e há uma barra de progresso. **Sem repetição automática.**
- **C8 — Nenhuma ação desta fatia gasta IA.** São rotas de cadastro.
- **C9 — O cartão da cena** mostra **uma etiqueta de situação** (Pendente, Confirmada, Descartada). **Revisto em 01/10/2026 (pedido do Allan):** tocar o cartão **expande no lugar**, com **o mesmo corpo do modal** (participantes, decisões e, na cena confirmada, os prompts). Antes (primeira versão), o toque abria o modal e o cartão não se expandia; isso deixava os prompts acessíveis só pelo ícone no texto.
- **C11 — Ações rápidas nos participantes (pedido do Allan, 01/10/2026).** Cada participante da cena mostra a situação **do elemento dele** (o elemento vem na mesma resposta) e a **ação principal ali mesmo**, sem sair do modal da cena: **"Confirmar"** o casamento automático, **"Registrar estado"** quando o elemento casado ainda não tem estado até este capítulo. Um elemento **novo** só oferece **"Revisar"**, porque criar ou vincular exige escolher. **"Revisar"** aparece sempre que há pendência. Confirmar o casamento ou registrar o estado **não fecha a cena**: ela continua aberta, com o participante em dia, e o servidor passa a aceitar "Confirmar cena". Antes, a pessoa tinha de procurar o elemento, decidir e voltar à cena.
- **C12 — Modais empilhados (pedido do Allan, 01/10/2026; substitui o C2).** Tocar num ícone do texto começa uma **pilha nova** com aquele modal. **"Revisar" empilha** o modal do elemento **por cima** do da cena; **fechar o de cima revela o de baixo**, já atualizado com o que se decidiu (E44 fecha só o modal de cima). Cada modal é uma janela e a última composta fica por cima; todas seguem a regra do D3 (só desenhadas com o capítulo `RESUMED`). "Ver ficha" fecha **a pilha inteira**. *Problema que isto resolve:* com um modal por vez, "Revisar" fechava a cena, e depois de decidir o elemento era preciso reabri-la.
- **C10 — O que não entra:** gerar prompt, copiar e "Novo retrato" (fatias 2 e 3); editar título ou descrição da cena; confirmar várias cenas de uma vez.

**Atualização de 01/10/2026 (547 testes):** C11 e C12 implementados depois do primeiro teste do Allan no tablet. **Divergência do C3:** o participante já confirmado continua aparecendo como "Elemento confirmado" (sem o nome do elemento casado).

**Como ficou (em linguagem simples).** Tocar numa cena, no painel ou no ícone dela no texto, abre uma folha com o título, a descrição e cada participante, dizendo se já é um elemento confirmado. Se algum ainda não for, há um botão **Revisar** que leva direto ao modal daquele elemento. Confirmar a cena chama o servidor (que usa o estado de cada participante); se faltar algo, a mensagem do servidor aparece na própria folha, sem fechá-la. **Divergências do plano:** no C3, o participante confirmado aparece como "Elemento confirmado" (o servidor não devolve o *nome* do elemento casado nas cenas, só o do participante; mostrar "Casado com *Nome*" exigiria um campo novo). **Defeito corrigido de passagem:** o ícone de cena no texto abria o modal do elemento de mesmo id. O rastro temporário do D3 foi removido.

#### "Confirmar todos" no painel de IA (pedido do Allan, 01/10/2026; implementado, 561 testes; falta validar no tablet)

Um botão no painel de IA do capítulo que decide de uma vez o que já tem par. **Decisão de desenho minha, a rever com o uso:** o lote confirma **só o que não exige escolha**, e **sempre mostra a conta antes** — porque o casamento automático é justamente o que o sistema pede para conferir (item 4.6), e confirmá-lo em massa sem avisar anularia esse cuidado.

- **L1 — O botão.** "Confirmar todos", ao lado de "Reanalisar", na lista de sugestões. Só fica habilitado quando há **algo que o lote consiga confirmar** (elementos novos sozinhos não bastam) e nenhuma análise ou lote está rodando.
- **L2 — Confirmação com a conta.** O diálogo diz **o que vai acontecer** (quantos casamentos serão confirmados, quantos estados registrados, quantas cenas tentadas) **e o que não vai** ("não gasta IA e não descarta nada"; quantos elementos novos ficam para a pessoa).
- **L3 — Ordem e ritmo.** (1) confirma os **casamentos automáticos**; (2) relê; registra o **estado** de quem ainda não tem (inclusive quem acabou de ter o casamento confirmado); (3) relê; tenta confirmar as **cenas pendentes**; (4) relê. **Uma chamada por vez**, sem repetição automática.
- **L4 — Falhas.** Uma chamada que o **servidor recusa** (422: falta confirmar algo) deixa **aquele item pendente** e o lote **continua**; já uma falha de **conexão** (sem código HTTP) **interrompe** o lote, para não esperar vários tempos limites seguidos. Um **409** (cena já confirmada, por exemplo em outro aparelho) conta como feito.
- **L5 — O resumo.** Ao terminar, o painel mostra uma ou duas frases ("Confirmado: 1 casamento, 1 estado, 1 cena. 1 elemento novo espera sua decisão."), com o primeiro motivo de recusa e, se parou, onde parou. Dispensa-se com o X; some ao começar outro lote.
- **L6 — O que o lote NUNCA faz.** Criar elemento novo (criar ou vincular exige escolha), descartar qualquer coisa, ou gastar IA. O estado registrado é um **rascunho** (item 4.4), como sempre.
- **L7 — Descartados ficam de fora**, e cenas já confirmadas também.

*Em linguagem simples:* o botão resolve, de uma vez, o que já tem um par óbvio, e deixa para você só o que realmente precisa de uma decisão sua.

#### Incremento 10b, segunda fatia — gerar o prompt e copiar (especificado e implementado em 01/10/2026; 586 testes; ajustado após o primeiro teste: G11 a G13; falta validar no tablet)

Depois de a cena virar frame (primeira fatia), o modal dela passa a oferecer o que vem a seguir no fluxo do sistema (item 2.1, passos 8 e 9): **montar o prompt com a IA** e **copiar** para colar na ferramenta de imagem. Importar a imagem de volta é o incremento 12. Servidor: `GET` e `POST /frames/{id}/prompts` (item 6.6), sem mudança.

**Regras (G1 a G10):**

- **G1 — Só para cena confirmada.** O bloco "Prompts" aparece no modal de uma cena **que já virou frame** (`frame_id` preenchido). Cena pendente ou descartada não tem prompt.
- **G2 — Ler não custa.** Ao abrir o modal de uma cena confirmada, o app lista os prompts já gerados (`GET /frames/{id}/prompts`, **sem IA**), do mais novo para o mais antigo. Cada um mostra o **texto** e o botão **Copiar**.
- **G3 — Gerar custa, então pede confirmação.** O botão **"Gerar prompt"** (ou **"Gerar outro prompt"**, se já há algum) abre um diálogo que diz que **gasta IA** (a leitura do capítulo e a montagem do prompt) e traz um campo **opcional** "Ajuste" (até 2000 caracteres): uma correção pontual do usuário, com prioridade sobre a leitura automática (item 4.4). É assim que se pede um refinamento: **gerar de novo com um comentário**. Mesmo padrão do Reanalisar (P7).
- **G4 — Gerar.** `POST /frames/{id}/prompts` com o comentário, se houver (o perfil é o **padrão do livro**, e o modelo, o da configuração). Pode levar mais de um minuto, então usa o tempo de espera longo da análise (P10). **Sem repetição automática**; **uma geração por frame de cada vez**.
- **G5 — Resultado.** O prompt novo aparece no topo da lista, com **Copiar**. Se o servidor devolver **referências visuais** (imagens-âncora dos elementos), o app avisa "Anexe também as N imagens de referência" (o fluxo é manual: a API não anexa nada).
- **G6 — Copiar.** Copia o texto do prompt para a área de transferência do aparelho e confirma na hora ("Copiado."). Não passa pelo servidor.
- **G7 — Erros mostram a mensagem do servidor** no modal, sem fechá-lo: sem perfil padrão no livro (422), sem modelo de prompt escolhido (422), chave de IA ausente (422), serviço de IA fora do ar (502). O que o app **ainda não consegue resolver sozinho**: criar o perfil de renderização (a tela de Perfis, item 7.9, ainda é provisória), então a mensagem de "sem perfil padrão" é um beco sem saída no app por enquanto (**limite conhecido**).
- **G8 — Sair no meio. *(Revisto em 01/10/2026, a pedido do Allan: ver G13.)*** A geração roda no **serviço do app**, como a análise (D1): sair do capítulo **não a cancela**, e ao voltar ao modal a pessoa reencontra o "gerando" e recebe o resultado, **sem cobrar de novo**. *Texto original:* o app não esperava o servidor; o prompt só aparecia ao reabrir o modal.
- **G9 — Nenhuma outra ação gasta IA.** Só o "Gerar" desta fatia.
- **G11 — Compartilhar o prompt (pedido do Allan, 01/10/2026).** Além de **Copiar**, cada prompt tem **Compartilhar**: abre o seletor do Android (`ACTION_SEND`, texto simples) para mandar o texto a outro app, como uma IA de imagem. É o mecanismo já decidido no item 7.7 (o app não recebe nada de volta).
- **G12 — "Gerar imagem" reservado (pedido do Allan, 01/10/2026).** Cada prompt tem também o botão **Gerar imagem**, que ainda **não gera nada**: ao tocar, explica "Em breve: gerar a imagem aqui no app. Por enquanto, copie ou compartilhe o prompt e importe a imagem depois." Existe para **reservar o lugar** na interface (já previsto no item 7.5b); não há campo no banco nem rota. Quando o app gerar a imagem, este é o botão que passa a funcionar.
- **G13 — Aviso translúcido de prompt gerado (pedido do Allan, 01/10/2026).** Ao terminar a geração, o app avisa, como na análise (D1): **no próprio modal**, uma faixa translúcida "Prompt gerado." por 2,5 s (o modal é uma janela por cima de tudo e esconderia o aviso do app); e, **se a pessoa não está olhando o modal daquela cena**, o aviso global no centro inferior: dentro do livro, "Prompt gerado: «Cena»."; fora dele, "Prompt gerado em «Livro», capítulo 3: «Cena»."; se falhou, o motivo. O aviso global **se cala** quando o modal daquela cena está na tela. *(Diferente da análise: o painel de IA aberto não cala o aviso de prompt, porque o prompt aparece no modal, não no painel.)*
- **Correção do modal (01/10/2026):** o conteúdo dos modais (cena e elemento) **passa a rolar**. Um prompt longo (ou muitos participantes) passava da altura da folha e ficava **cortado**, com os botões fora de alcance.
- **G10 — O que não entra:** "Novo retrato" (fatia 3), importar a imagem (incremento 12), avaliar o resultado, escolher outro perfil ou modelo, editar o texto do prompt.

**Como ficou (em linguagem simples).** Numa cena que já virou frame, o modal ganha uma seção "Prompts". Ela lista o que já foi gerado, do mais novo para o mais antigo, cada um com um botão **Copiar** (o texto também pode ser selecionado). O botão **Gerar prompt** abre um aviso de que gasta IA e um campo opcional "Ajuste"; ao confirmar, o servidor monta o prompt, que aparece no topo da lista. Se algo der errado (por exemplo, o livro sem perfil padrão), a mensagem do servidor aparece ali mesmo. **Divergências do plano:** nenhuma. **Limites conhecidos:** a mensagem de "sem perfil padrão" não tem conserto dentro do app enquanto a tela de Perfis for provisória (G7); e sair do capítulo durante a geração não cancela nada no servidor, o prompt fica gravado e aparece ao reabrir o modal (G8).

#### Incremento 10b, terceira fatia — "Novo retrato" (especificado e implementado em 01/10/2026; 595 testes; ajustado após o teste: N9; falta validar no tablet)

Fecha o 10b: além da **cena** (fatias 1 e 2), o elemento confirmado também pode ter o seu **retrato**, um frame `tipo=PERSONAGEM` que usa só a aparência daquele elemento (item 4.4), e a partir dele a pessoa gera o prompt como numa cena. Servidor: `POST /capitulos/{id}/frames` com `tipo=PERSONAGEM` e **um** estado em `estados_ids` (item 6.4), sem mudança.

**Regras (N1 a N8):**

- **N1 — Onde.** No **modal do elemento** já **confirmado** (casado, revisado e com estado que vale neste capítulo; não descartado), uma seção **"Retrato"**. Elemento ainda pendente não tem retrato.
- **N2 — Sem retrato ainda: "Novo retrato".** O botão cria o frame com **o estado que vale neste capítulo** (`estado_vigente`, o deste capítulo ou o vigente de um anterior). **Não gasta IA.** Vale para **qualquer tipo** de elemento (personagem, ambiente, objeto...); "retrato" é o nome do frame solo, `PERSONAGEM`.
- **N3 — Com retrato: os prompts.** Se o elemento já tem retrato neste capítulo, a seção mostra **a mesma seção de prompts da cena** (G1 a G13): listar, **Gerar prompt**, **Copiar**, **Compartilhar**, **Gerar imagem** (reservado) e o aviso translúcido. **Não oferece um segundo retrato.**
- **N4 — Como o app sabe se há retrato.** O **artefato** daquele elemento já traz o `frame_id` do retrato mais novo dele neste capítulo (item 6.8). Logo depois de criar, o app usa o id devolvido e **relê os artefatos** (o ícone no texto passa a `CONFIRMADO`).
- **N5 — Erros e ritmo.** A mensagem do servidor aparece no modal, sem fechá-lo. **Uma criação por elemento de cada vez; sem repetição automática.**
- **N6 — O aviso do prompt** diz o nome do retrato: "Prompt gerado: «Retrato de Jon»." (G13).
- **N7 — Nenhuma ação desta fatia gasta IA**, exceto o **Gerar prompt** já existente (G3, com confirmação).
- **N9 — Lista e ícone fazem a mesma coisa (pedido do Allan, 01/10/2026).** Tudo o que se faz pelo **ícone no texto** (confirmar a cena, gerar prompt, **Novo retrato**, copiar, compartilhar) também se faz pelo **cartão expandido na lista do painel de IA do capítulo**, e vice-versa. O **elemento** confirmado mostra a seção "Retrato" dentro do próprio cartão (expandido); a **cena** mostra o corpo completo no cartão expandido. O modal e o cartão usam **o mesmo código**, então nunca divergem. Um "Revisar" na lista empilha o modal do elemento por cima do painel.
- **N8 — O que não entra:** retrato com **posição** escolhida ("Ilustrar aqui"), **mais de um** retrato por elemento por capítulo, escolher **outro estado** que não o vigente, e a tela de Frame (7.6), que continua provisória.

**Como ficou (em linguagem simples).** No modal de um elemento já confirmado aparece a seção "Retrato". Se ainda não há retrato, um botão **Novo retrato** cria o frame solo daquele elemento (não gasta IA) e a seção passa a mostrar, no lugar do botão, a mesma área de prompts da cena (gerar, copiar, compartilhar). O ícone do elemento no texto se atualiza sozinho. **Com isto o 10b está completo:** da sugestão da IA até o prompt copiado, tanto para cenas quanto para retratos; o que falta para fechar o ciclo é **importar a imagem de volta** (incremento 12). **Divergências do plano:** nenhuma.

#### Incremento 12, primeira fatia — importar a imagem (especificado em 01/10/2026)

O ciclo do fluxo (item 2.1, passos 9 a 11): o prompt foi copiado ou compartilhado, a imagem foi gerada **fora** do app (ou será, pelo botão reservado), e agora ela **volta** para o catálogo. **Ordem decidida pelo Allan (01/10/2026):** primeiro **importar a imagem** e **posicioná-la no texto**; **gerar a imagem no app** vem depois e reaproveita tudo isto, porque só muda de onde vêm os bytes. Esta fatia **importa e mostra**; **desenhar no texto** (os quadros retrato e paisagem do item 7.5b, I1 a I8) é a **segunda fatia**.

**Regras (J1 a J10):**

- **J1 — Onde.** Em **cada prompt** (no modal e no cartão expandido da lista, cena ou retrato), um botão **"Importar imagem"**, ao lado de Copiar, Compartilhar e Gerar imagem.
- **J2 — Escolher.** Abre o **seletor de arquivos do Android**, só imagens. O app confere **antes de enviar**: a extensão é uma das que o servidor aceita (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) e o tamanho cabe no limite do servidor (**25 MB**); senão, diz o motivo e **não envia**.
- **J3 — Enviar.** `POST /prompts/{id}/imagens` (multipart, campo `arquivo`), com **barra de progresso** (a imagem pode ter vários MB). **Um envio por prompt de cada vez; sem repetição automática** (repetir sozinho mandaria um arquivo já consumido). Falhas mostram a mensagem do servidor no cartão.
- **J4 — Mostrar.** A imagem importada aparece **no cartão do prompt** como **miniatura** (`?tamanho=miniatura`, item 6.9), da mais nova para a mais antiga. **Tocar abre em tela cheia**, no **tamanho normal** (`original`), com **zoom por pinça**; voltar fecha.
- **J5 — Ao abrir.** Ao listar os prompts de um frame, os que já têm imagem (`total_de_imagens`) **trazem as suas** (`GET /prompts/{id}`): a imagem importada ontem aparece hoje.
- **J6 — O ícone acompanha.** Depois de importar, o artefato do elemento ou da cena passa a **`ILUSTRADO`** (item 6.8): o app relê os artefatos.
- **J7 — A biblioteca de imagens.** O app usa o **Coil** (decisão já registrada na Etapa 5), com o **cache dele**: miniaturas se baixam uma vez. É a exceção, já prevista, à regra "sem cache de dados" do item 7.0. O endereço vem do servidor configurado; não há login.
- **J8 — Várias imagens por prompt** são normais (a pessoa gera o mesmo prompt mais de uma vez, ou em ferramentas diferentes); no texto aparece a **mais recente** (item 3.4g).
- **J9 — Nada disto gasta IA.**
- **J10 — O que não entra:** **desenhar a imagem no texto** (segunda fatia), **remover** uma imagem, **trocar** a imagem principal, gerar a imagem no app, e a cópia **offline** das imagens (passo 3 do armazenamento local, item 7.0a).

**Implementado (01/10/2026), em linguagem simples.** Cada prompt, no modal e na lista, ganhou o botão **Importar imagem**: ele abre o seletor de arquivos do Android só com imagens. Antes de enviar, o app confere a extensão e os 25 MB (J2), para não subir um arquivo grande só para ouvir "não". O envio mostra uma barra de progresso, um por prompt de cada vez, e o erro do servidor aparece como veio (J3). Depois de importar, a miniatura aparece no cartão do prompt, a mais nova primeiro, e o app relê os artefatos para o ícone no texto virar `ILUSTRADO` (J6). Ao abrir um frame, a listagem só diz **quantas** imagens cada prompt tem; o app pede `GET /prompts/{id}` **só dos que têm** e, se esse pedido falhar, o prompt aparece sem as miniaturas (J5). Tocar na miniatura abre a imagem em tela cheia, com zoom por pinça. O **Coil 3.3.0** (com o cliente OkHttp) baixa e guarda em cache as imagens. Nenhuma mudança no servidor. 16 testes novos (611 no app, todos passando).

**Correção da importação (02/10/2026, J2) — o botão não funcionava no tablet.** Causa: o seletor de arquivos do Android estava registrado **dentro do botão**, e o botão fica no modal; o modal só é desenhado com a tela ativa (correção do D3), então ao abrir o seletor a tela deixa de estar ativa, o modal sai da composição e **o resultado da escolha se perde, sem nenhuma mensagem**. Agora o seletor mora na **tela do capítulo** (que não sai da composição) e o alvo (frame e prompt) fica no ViewModel do painel (`escolherImagemPara` / `imagemEscolhida`). **Segunda proteção:** o app também usa o **tipo MIME** que o seletor informa quando o *nome* não tem extensão (nomes como `image-3f2a`), e envia o arquivo com a extensão certa. 6 testes novos (638 no app). **Não reproduzi o defeito no tablet**: a causa é a que o código e o comportamento do Android indicam; o Allan confirma.

#### Incremento 12, fatias seguintes — prompt recusado pelo provedor: suavizar e tentar de novo (especificado em 02/10/2026)

Vale **quando o app gerar a imagem** (o botão reservado, item 7.5b); hoje o fluxo é manual e nada disto roda. Fica registrado agora porque muda o que o prompt guarda (item 3.1) e a instrução de IA (item 4.2).

**O fluxo (S1 a S3), decidido pelo Allan:**

- **S1 — Primeira tentativa** com o **prompt original**, sem alteração.
- **S2 — Se o provedor recusar** o conteúdo, o prompt vai **automaticamente** para a **suavização** (uma chamada de IA de texto) e o app faz a **segunda tentativa** com o prompt suavizado, sem pedir confirmação. **A recusa não cobra** (dado do Allan).
- **S3 — Se recusar de novo**, o app **devolve ao usuário** com o prompt suavizado num campo **editável**; ele pode ajustar à mão e tentar mais uma vez, se quiser. A tentativa depois da edição é uma **chamada direta** ao provedor: não dispara outra suavização.

**Regras (S4 a S12):**

- **S4 — Só a recusa de conteúdo dispara a suavização.** O erro 400 do provedor com a mensagem de política (hoje: "content management policy" na Meta; "flagged for sexual or adult content" na Black Forest Labs). **Outros erros** (503, tempo esgotado, chave inválida, saldo) aparecem como erro comum, sem suavizar. As mensagens variam por provedor, então a **detecção fica isolada numa função** fácil de ajustar, e uma mensagem desconhecida cai no erro comum.
- **S5 — Os prompts ficam salvos com a situação.** Cada prompt guarda: a **situação** (`NAO_TENTADO`, `RECUSADO`, `COM_SUCESSO`), o **motivo da recusa** (a mensagem do provedor) e, no suavizado, o **vínculo com o prompt original** (`prompt_original_id`). O original **nunca é sobrescrito**; o suavizado é um prompt novo. Exige migração no banco.
- **S6 — Instrução separada.** A suavização tem **a sua própria instrução** (`_INSTRUCAO_DE_SUAVIZACAO`), usada **só neste caminho**; a instrução do prompt normal **não muda**. O modelo de texto é o de prompt (item 4.3). **Suavizar é decisão do sistema, não do usuário:** não há botão para pedir a suavização; o usuário só **edita o prompt à mão** (S3).
- **S7 — O que a suavização faz.** Mantém a **cena, os personagens, o enquadramento e a estética**; troca o explícito pelo **sugerido** (cobertura parcial por cabelo, pano, sombra ou enquadramento; ombros e braços à mostra) e **nunca** usa palavras como `nude` ou `naked`. O prompt de cobertura parcial aprovado em 01/10/2026 é o modelo.
- **S8 — Violência:** sempre **sem sangue** e **nunca explícita**.
- **S9 — Menores:** sempre **vestidos** e **nunca em cena sensual**. Só isso: a checagem de quem é menor, e o que fazer quando a cena pede o contrário, **ficam com a moderação do provedor**, que o Allan considera mais eficiente do que qualquer regra nossa (decisão de 02/10/2026).
- **S10 — Regra fixa:** S8 e S9 **não são configuráveis**.
- **S11 — Transparência.** O app diz que o provedor recusou e que tentou uma versão mais suave; o **prompt original continua visível** e os dois podem ser copiados.
- **S12 — Uma suavização automática por pedido, sem laço.**

**O que não entra:** verificação local do conteúdo antes de enviar e regra de menores na instrução do prompt original (decisão do Allan: a moderação dos provedores é melhor do que a nossa); botão "Suavizar prompt" (descartado: a suavização é do sistema, S6); a escolha do modelo de imagem pelo usuário; a própria geração de imagem no app, que é o próximo incremento e depende deste desenho.

#### Incremento 12, terceira fatia — gerar a imagem no app (especificado em 02/10/2026)

O botão **Gerar imagem**, que até aqui só explicava que viria depois (G12), passa a gerar de verdade, chamando `POST /prompts/{id}/gerar-imagem` (item 6.6, "Gerar a imagem"). Quem decide suavizar, tentar de novo e gravar é o **servidor** (S1 a S12); o app só chama e mostra o desfecho. Esta fatia **só mostra** a imagem como na importação (miniaturas e tela cheia, J4); **desenhar no texto** é a fatia seguinte.

**Regras (K1 a K10):**

- **K1 — O botão.** O **Gerar imagem** de cada prompt (no modal e no cartão expandido da lista) chama a rota **direto, sem diálogo de confirmação**: a imagem custa cerca de **US$ 0,01** e a pessoa acabou de tocar no botão. (O *Gerar prompt* pede confirmação porque lê o capítulo inteiro e custa mais; se o custo da imagem crescer, volta a confirmar.)
- **K2 — Enquanto gera.** Barra de progresso com *"Gerando a imagem… pode levar mais de um minuto."* O botão e o **Importar imagem** do prompt ficam desabilitados; **um pedido por prompt de cada vez, sem repetição automática**. Usa o tempo de espera longo (180 s), como o *Gerar prompt*.
- **K3 — Gerou.** A miniatura aparece no cartão (as mesmas de J4), com o aviso *"Imagem gerada."* Se o servidor precisou **suavizar**, o aviso diz isso: *"O provedor recusou o prompt original; a imagem saiu de uma versão mais suave, que ficou salva como outro prompt."* O ícone no texto passa a `ILUSTRADO` (J6).
- **K4 — Recusou de novo (S3).** O app abre o diálogo **"O provedor recusou este prompt"**, com o **motivo** que o provedor deu, o **prompt devolvido num campo editável** e dois botões: **Tentar de novo** (manda o texto editado; é uma chamada direta, **sem nova suavização**) e **Fechar** (o prompt continua na lista, marcado). O diálogo é desenhado **uma vez**, na raiz do painel, como o do *Gerar prompt*.
- **K5 — Etiquetas na lista.** Cada prompt mostra a sua situação (item 3.4c): **"Recusado pelo provedor"** (`RECUSADO`, com o motivo à mostra) e, quando veio de outro, **"Versão suavizada"** (o sistema reescreveu: tem modelo) ou **"Versão editada"** (a pessoa reescreveu: sem modelo). `NAO_TENTADO` não leva etiqueta. A distinção suavizada/editada usa o `modelo_ia` do prompt, que o servidor preenche só na suavização.
- **K6 — A lista se atualiza sozinha.** Depois de qualquer desfecho, o app **relê a lista de prompts** do frame **sem piscar o "Lendo…"**: o original mudou de situação e pode haver um prompt novo (suavizado ou editado).
- **K7 — Erros.** Falha de rede, 422 (sem chave ou sem modelo) ou 502: a mensagem do servidor aparece no cartão do prompt, nada mais muda e dá para tocar de novo. Sem repetição automática.
- **K8 — Sair da tela.** O pedido pertence à tela do capítulo: sair dela durante a geração **interrompe a espera do app**, mas **o servidor termina e grava a imagem**; ela aparece na próxima vez que o prompt for aberto (J5). Cobrar sem entregar na tela é o custo aceito desta primeira versão.
- **K9 — Nada de modelo no app ainda.** Qual modelo gera (e qual suaviza) é o da configuração do servidor (item 3.4d); a escolha dentro do app é pendência da Etapa 8.
- **K10 — O que não entra:** confirmação de custo, cancelar a geração, progresso de verdade (a barra é indeterminada), aviso global quando a pessoa sai do modal, **desenhar a imagem no texto** (fatia seguinte).

**Implementado (02/10/2026), em linguagem simples.** O botão **Gerar imagem** de cada prompt agora chama a rota nova direto (K1), com barra de progresso indeterminada e um pedido por prompt (K2), no tempo de espera longo de 180 s. Se gerou, aparece o aviso e a miniatura (as mesmas da importação), o ícone no texto vira `ILUSTRADO` e a lista de prompts é **relida sem piscar** (K3, K6): ela precisa ser relida porque o servidor pode ter criado um prompt novo (o suavizado ou o editado) e mudado a situação do original. Se o provedor recusou de novo, abre o diálogo **"O provedor recusou este prompt"**, com o motivo e o prompt devolvido para editar; **Tentar de novo** manda o texto editado em chamada direta (K4). A lista ganhou as etiquetas **Versão suavizada**, **Versão editada** e **Recusado pelo provedor** (K5). O diálogo mora em `DialogosDoPainel`, junto do *Gerar prompt*, para nunca aparecer duplicado quando o mesmo frame está no modal e na lista. Enquanto um prompt gera, o **Importar imagem** dele fica desligado (e vice-versa). **Divergência da regra G12:** o botão deixou de ser o aviso "em breve"; a constante antiga saiu. O pedido pertence à `viewModelScope` da tela do capítulo, como a importação: sair da tela durante a geração interrompe a espera do app, não o servidor (K8). 21 testes novos (632 no app, todos passando): regras puras (avisos e etiquetas), o ViewModel com o repositório falso (gerar, suavizado, recusa, tentar de novo, um por prompt, erro, lista relida sem passar por "Lendo") e o repositório pela rede com `MockWebServer` (corpo `{}` ou `{"texto": ...}`, desfecho `GERADA`, `RECUSADA` e a mensagem de erro). **Ainda não foi testado no tablet nem com o modelo real**: o Allan valida a chamada de verdade, com o backend atualizado.

#### Incremento 12, quarta fatia — o fluxo de imagem em um toque e os ajustes de 02/10/2026 (especificado em 02/10/2026)

Vieram do teste real no tablet (01 e 02/10). Seis pontos, na ordem em que serão feitos: **suavização mais fiel** (S7 revisada), **editar o prompt** (R), **imagens importadas e importar único** (T), **ações da imagem** (U), **o fluxo em um toque** (Q) e, por último, a **pendência do perfil do elemento** (registrada na Etapa 8, sem implementar).

##### S7 revisada — suavizar sem perder o que o autor descreveu

**Problema:** a suavização estava **suprimindo pontos** da descrição do autor (a instrução pedia para manter tudo, mas nada obrigava o modelo a isso). **Decisão:** a suavização passa a ser **trecho a trecho**. O servidor divide o prompt recusado em **trechos** (o prompt é uma lista separada por vírgulas, item 4.4), manda a lista **numerada** e exige de volta **uma lista com o mesmo número de itens**, cada um com a nova redação **do mesmo trecho**: igual ao original se não tem nada explícito, ou trocado só no que é explícito. O servidor junta os itens na mesma ordem. Se o modelo devolver um número diferente de itens, o servidor pede **uma vez** de novo; se errar de novo, é erro do provedor (502), **sem inventar um prompt com trechos faltando**. A instrução também pede: **mudar o mínimo** (só a palavra ou expressão explícita; nada de trocar por sinônimos o que não era problema; pele, cabelo, expressão, luz e estilo ficam como estão) e **temperatura baixa** (0,2). As regras S8 (violência) e S9 (menores) continuam.

**Implementado (02/10/2026): S7 revisada.** `suavizar_prompt` divide o prompt em trechos (`dividir_em_trechos`), manda a lista numerada, exige o JSON `{"trechos": [...]}` com **o mesmo número de itens** e junta na ordem com ", ". Número diferente, item vazio, item que não é texto ou resposta sem JSON = nova tentativa (no máximo uma); errando de novo, `ErroDoProvedorIA` e nenhum prompt é criado com trechos faltando. A temperatura da chamada é 0,2 (`_conversar` ganhou o parâmetro). A instrução pede trecho sem nada explícito **idêntico, palavra por palavra**, e mudança **mínima** no explícito. 13 testes novos, 3 antigos reescritos (592 → 594 no total com os de T3). **Ainda não validado com o modelo real**: o Allan repete o prompt da Auri e confere se nenhum ponto da descrição some.

##### R — Editar o prompt antes de gerar

- **R1.** Cada prompt da lista tem **Editar**: abre o **mesmo campo** do diálogo da recusa (K4), com o texto do prompt.
- **R2.** **Gerar imagem com este texto** envia o texto editado em chamada direta (S3): vira um **prompt novo**, ligado ao de onde saiu, sem suavizar. **Cancelar** não muda nada. Se o texto não mudou, vale o fluxo normal.
- **R3.** Serve a qualquer prompt, inclusive um que já gerou imagem (o caso: gerar de novo com um ajuste, ou com outro modelo quando a escolha de modelo existir).

##### T — Imagens importadas e importar único

- **T1.** **Um só botão "Importar imagem" por frame**, em vez de um por prompt (J1 revisada). Importa para o **prompt mais recente** do frame. Frame sem prompt não mostra o botão (a imagem precisa de um prompt: item 3.4c).
- **T2.** As imagens **importadas** ficam numa seção própria, **"Imagens importadas"**, no **fim** da área do frame. As **geradas** aparecem em destaque, como a imagem do frame (Q).
- **T3. Servidor:** `Imagem.origem` (`IMPORTADA` ou `GERADA`; item 3.4c), preenchida por quem grava (importar = `IMPORTADA`, gerar = `GERADA`) e devolvida em `ImagemResumo`. As imagens que **já existiam** ficam `IMPORTADA` (o banco não distingue as geradas nos testes de 01/10; são poucas). Migração com `server_default`.
- **T4.** Os prompts continuam **sem** botão de importar; cada um mantém o **Gerar imagem** (K1) e o **Editar** (R1).

**Implementado (02/10/2026): T3, o servidor.** `Imagem.origem` (`IMPORTADA` por padrão, `GERADA` quando o servidor gera), migração `c9d1e3f5a7b9` (testada em Postgres: sobe, desce, sobe; `alembic check` limpo), devolvida em `ImagemResumo`. 2 testes novos. **Para o app:** campo **novo** na resposta das imagens; o app atual ignora campos desconhecidos. As telas (T1, T2) vêm na fatia do app.

##### U — Excluir, compartilhar e salvar a imagem

Na **tela cheia** da imagem (J4), três ações:

- **U1. Compartilhar** (a imagem em tamanho original, pelo seletor de apps do Android, via `FileProvider` e um arquivo temporário no cache).
- **U2. Salvar na galeria** (pasta `Pictures/Imagineer`, pelo `MediaStore`: no Android 10+ não pede permissão). Confirma com o aviso *"Salva na galeria."*
- **U3. Excluir** (`DELETE /imagens/{id}`, item 6.6): **pede confirmação** (apaga para sempre, inclusive o arquivo no servidor). Depois, a imagem some da lista e o app **relê os artefatos** (o ícone pode deixar de ser `ILUSTRADO`).
- **U4.** O app baixa o arquivo original por `GET /imagens/{id}/arquivo` (item 6.9) para as duas primeiras; erros aparecem como mensagem.

##### Q — Gerar a imagem em um toque

**Objetivo:** criar elemento, gerar retrato, gerar prompt, gerar imagem eram quatro toques e dois diálogos. O fluxo vira **um botão** que faz o que falta.

- **Q1. O botão principal do frame** é **"Gerar retrato"** (elemento) ou **"Gerar imagem"** (cena): **um só por frame**, no lugar de *Novo retrato* + *Gerar prompt* + *Gerar imagem*.
- **Q2. O toque faz, em sequência, só o que falta:** (a) **criar o frame** do retrato, se o elemento ainda não tem (a cena já tem frame desde que é confirmada); (b) **gerar o prompt** (`POST /frames/{id}/prompts`, gasta IA), **se o frame ainda não tem nenhum**; (c) **gerar a imagem** do prompt **mais recente** (`POST /prompts/{id}/gerar-imagem`, K1 a K8, incluindo suavizar e o diálogo da recusa).
- **Q3. Sem diálogo de confirmação.** Sob o botão, uma linha fixa: *"Gera o prompt e a imagem (gasta IA)."* O diálogo do *Gerar prompt* (G3) **só aparece em "Novo prompt"** (Q6).
- **Q4. Andamento por etapa**, com barra indeterminada: *"Criando o retrato…"*, *"Montando o prompt…"*, *"Gerando a imagem…"*. Um toque por frame de cada vez, sem repetição automática.
- **Q5. Falhou no meio?** O que já foi feito **fica** (frame, prompt) e a mensagem do servidor aparece. Tocar de novo **continua de onde parou**: não recria o frame, não refaz o prompt que existe.
- **Q6. Frame que já tem prompt:** o botão só **gera a imagem** do prompt mais recente. **Novo prompt** (G3: com diálogo de custo e ajuste opcional) fica na seção recolhida.
- **Q7. Os prompts ficam recolhidos** em **"Ver prompts"** (lista, copiar, compartilhar, **Editar**, Gerar imagem de um prompt antigo, Novo prompt, etiquetas K5). O que aparece em destaque é a **imagem**.
- **Q8. Sem rota nova:** o app orquestra as três chamadas que já existem. **Revisa:** N2 (o *Novo retrato* deixa de ser um botão solto), N3, G3 e K1 (o *Gerar imagem* por prompt passa para dentro de *Ver prompts*).
- **Q9. O que não entra:** escolher o modelo no app (Etapa 8), cancelar no meio, confirmar custo, e as imagens no texto do capítulo (fatia 12b).

#### Incremento 11 do app, primeira fatia — os ícones dos elementos no texto (implementado em 30/09/2026)

**Pedido do Allan:** ao analisar o capítulo, as sugestões aparecem no painel de IA **e também como ícones no texto**. Fatia combinada com ele, dada a pouca cota do dia: **só os elementos, de ponta a ponta**; as cenas entram depois.

**Servidor (446 testes, 22 deles novos).** `GET /capitulos/{id}/artefatos` devolve um artefato por sugestão de elemento **não descartada**: `tipo` (`ELEMENTO`), `tipo_do_elemento` (escolhe o ícone), `rotulo` (o nome do cadastro, se casada), `posicao_no_texto`, `situacao` (`SUGERIDO` → `CONFIRMADO` → `PROMPT_PRONTO` → `ILUSTRADO`, pelo **retrato** do elemento neste capítulo: o frame `PERSONAGEM` cujo único estado é dele), `frame_id` e `imagem_id` (a mais recente). **Só leitura: nunca chama a IA.** Ordem por posição; os sem posição vão depois.

**Divergências do plano (item 3.4g), e o motivo:**
- **A posição é calculada na hora da leitura, pelo nome, sem colunas novas nem migration.** O item 3.4g previa gravar `posicao_no_texto` ao gerar a sugestão. Para elementos a busca pelo nome é barata e determinística, e assim **funciona nos capítulos já analisados, sem reanalisar nem gastar IA** — era o que permitia ver o resultado hoje. As colunas (`trecho_ancora`, `posicao_no_texto`) continuam necessárias **para as cenas**, que só se localizam pela citação da IA.
- **A busca é por palavra inteira** ("Vis" não casa com "visto" nem com "Vision"). O 3.4g não dizia; sem isso, um nome curto "aparecia" em qualquer palavra que o contenha.
- **Reserva por nome parcial.** Se o nome completo não aparece, vale a primeira menção de **qualquer pedaço que seja nome próprio** (palavra com maiúscula e 3 letras ou mais): a IA sugeriu "Septimus Ellanher" e o texto diz "Ellanher". Palavras minúsculas ("de", "prata") não servem de reserva: genéricas demais.
- **Um ícone por elemento.** Duas sugestões do mesmo elemento (ou do mesmo tipo e nome, se ainda não casadas) viram **um** artefato, o da sugestão mais antiga; o painel continua listando todas.
- **Achado com dados reais (30/09/2026, capítulo de 21 sugestões): a reanálise duplicava as sugestões já confirmadas** — a confirmada sobrevivia, a IA a listava de novo e criava outra. **Corrigido:** o que a IA repetir de uma sugestão confirmada (ou descartada) **não é recriado**. Duplicatas que já estavam no banco continuam aparecendo no painel (os ícones já as unem); a limpeza dos dados antigos ficou como pendência.
- **Nome que não aparece no texto fica "sem posição":** na prática, também **denuncia uma sugestão que a IA listou sem o elemento estar no capítulo** (3 dos 4 sem posição do capítulo medido). Decidir depois se essas devem ser filtradas do painel.
- Valem as demais regras do 3.4g: início do **parágrafo** da primeira menção; busca exata e depois **normalizada** (sem acento, sem diferença de caixa, aspas tipográficas viradas retas, quebras viradas espaço) **com mapa de índices** para o texto original; unidade **UTF-16**.

**App (466 testes, 17 novos):**
- **E42 — Os ícones no texto.** Depois que o texto carrega (ele **nunca espera** pelos ícones; se a chamada falhar, o capítulo continua legível, só sem ícones), o app lê os artefatos e desenha, numa **calha de largura fixa à esquerda de cada parágrafo**, o ícone de cada elemento que aparece pela primeira vez ali. Um desenho por tipo: personagem, ambiente, objeto, criatura, grupo, veículo, edificação (e um genérico para um tipo novo). **A situação enche o ícone:** sugestão ainda não confirmada = **contorno**; confirmada = **cheio**; prompt pronto = cor de destaque secundária; ilustrado = cor primária. Artefatos **sem posição** (o nome não foi achado) ficam numa faixa "Sem posição no texto", no começo.
- **Tocar num ícone abre um MODAL com a sugestão, sem trocar de tela (E42, revisada após o teste do Allan).** A primeira versão abria o painel de IA e rolava até o cartão; a troca de contexto atrapalhava a leitura. Agora o toque abre uma **folha por cima do texto** com o **mesmo cartão do painel, já aberto e com as mesmas ações**: confirmar, criar elemento, vincular, trocar, desfazer, descartar e **ver a ficha** (investigar mais). Fechar volta ao texto exatamente onde estava; **a folha também fecha sozinha quando o usuário conclui a decisão (E44)**. Se as sugestões ainda não tinham sido lidas (o painel nunca fora aberto), o modal as lê — só o `GET`, que não gasta IA. Os **diálogos do painel** (criar, vincular, desfazer...) passaram a ser desenhados **uma vez só, pela tela de Capítulo**, e não dentro do painel, para valerem também com o painel fechado.
- **E44 — O modal fecha quando a decisão está concluída.** *(Pedido do Allan após o teste.)* **Fecham o modal, quando dão certo:** **criar o elemento**, **vincular ou trocar** (escolher o elemento), **confirmar**, **registrar estado** e **descartar** (inclusive depois do aviso de que aparece em cenas). **Não fecham:** **desfazer** e **restaurar** (devolvem a sugestão a "nova" e pedem a próxima decisão) e qualquer ação que **falhe** (o modal e o diálogo ficam, com a mensagem da API). Só fecha o modal **da própria sugestão**: agir em outra não o toca. O ícone no texto já mostra o resultado atrás da folha. *(Efeito: o aviso "o estado é um rascunho" de registrar estado aparece só no cartão do painel, não mais no modal.)*
- **E43 — A jornada de leitura não se perde.** *(a)* **O modal e os diálogos abertos moram no ViewModel**, que sobrevive à navegação: quem vai à ficha de um personagem (inclusive a de **outro** personagem, pelo "Ver ficha" do diálogo de vincular) e volta **reencontra o modal e o diálogo como estavam**, já com as sugestões relidas (E31). *(b)* **A posição de rolagem do texto** subiu para a tela de Capítulo: no celular o texto sai da tela enquanto o painel está aberto em tela cheia, e a rolagem antes se perdia (o texto voltava ao topo); agora sobrevive a isso e a ir a outra tela e voltar. O painel (aside no tablet, tela cheia no celular) continua existindo para a visão geral do capítulo. *(c)* **O modal só é desenhado com o capítulo na frente.** Ele é uma **janela própria**, acima de tudo, e captura o botão voltar: desenhado enquanto a ficha estava por cima, fazia o primeiro "voltar" da ficha cair nele e a tela parecia voltar para a ficha (achado do Allan). O estado dele continua no ViewModel, e ele reaparece sozinho ao voltar ao capítulo. A navegação para a ficha também não empilha uma segunda igual (`launchSingleTop`). **Vale o mesmo para os diálogos do painel (vincular, criar, desfazer...)**, que também são janelas próprias: só são desenhados com o capítulo na frente — **sem esperar o fim da animação**: somem no instante em que o capítulo começa a sair (`ON_PAUSE`) e voltam no instante em que ele começa a voltar (`ON_START`). *(A primeira versão esperava o estado `RESUMED`, que só chega depois da animação de volta: o capítulo aparecia e o diálogo de vincular "brotava" instantes depois — achado do Allan.)* *(Achado em 30/09/2026: o relato de "a ficha do objeto ficava voltando" veio de vincular → Ver ficha, caminho que a primeira correção, só do modal, não cobria.)* **A navegação à ficha, e o "voltar" dela, só agem com a tela da entrada na frente** (`RESUMED`): um segundo toque durante a transição não empilha outra ficha nem desempilha também o capítulo. *Esta correção parte de uma hipótese: o bug não foi reproduzido fora do tablet. Se persistir, o próximo passo é ler o `logcat` do tablet.*
- A posição do servidor é achada no app pelo **último parágrafo que começa nela ou antes** — tolera uma pequena diferença de aparo.

**Fica para a próxima fatia:** os ícones de **cena** (precisam do `trecho_ancora` no prompt da IA, das colunas e de **reanalisar** cada capítulo), "Ilustrar aqui" e a imagem desenhada entre os parágrafos (incremento 12).

#### Incremento 11, segunda fatia — os artefatos de cena (servidor; implementado em 01/10/2026, 459 testes, 13 novos; falta o app)

**O quê.** `GET /capitulos/{id}/artefatos` passa a devolver, além dos de elemento, um artefato `CENA` por sugestão de cena **não descartada**. É a parte que o 3.4g já previa; esta fatia só fixa o recorte e as decisões abaixo.

**Por quê é diferente dos elementos.** Elemento tem nome, então o servidor o acha no texto na hora da leitura. Cena não tem nome a buscar: só a **IA** sabe onde o momento começa. Por isso a posição da cena precisa ser **pedida à IA (uma citação) e gravada** quando a sugestão nasce.

**Decisões:**
- **D1 — Só `SugestaoDeCena` ganha colunas** (`trecho_ancora`, texto 300; `posicao_no_texto`, inteiro; ambas nulas; uma migration). `SugestaoDeElemento` **não** ganha: a posição dela continua sendo calculada pelo nome (divergência já registrada acima).
- **D2 — O prompt da IA pede `trecho_ancora` em cada cena:** uma citação **literal e curta** (até ~200 caracteres) do começo do momento, copiada do texto; **`null` na dúvida**. `CenaSugerida` (provedor e falso) ganha o campo; um valor que não seja texto vira nulo.
- **D3 — O servidor converte a citação em posição ao gravar a sugestão** (em `_gerar_sugestoes`), nunca a IA. Ordem do 3.4g: **exata → normalizada (com mapa de índices) → só o começo, com 6 palavras e, se não achar, 5, 4 e 3** (menos que 3 é genérico demais); resultado = início do **parágrafo**, em **UTF-16**. Não achou = `posicao_no_texto` nula. A busca da citação **não** é por palavra inteira (é um trecho, não um nome); as de elemento continuam sendo.
- **D4 — Mesmo formato de artefato:** `tipo=CENA`, `tipo_do_elemento` nulo, `rotulo` = título da cena, `sugestao_id`, `frame_id` (o `Frame` confirmado, se houver), `imagem_id` (a mais recente do frame). `situacao`: `SUGERIDO` (sem frame) → `CONFIRMADO` (frame sem prompt) → `PROMPT_PRONTO` → `ILUSTRADO`, como nos elementos. Entram na **mesma ordenação** (por posição; sem posição depois).
- **D5 — Capítulos já analisados ficam sem posição nas cenas** até serem **reanalisados** (não há como saber onde a cena começa sem a IA). Seguem valendo, só sem ícone no texto. **Nenhuma reanálise automática**: custa IA e só o usuário decide. Cena **confirmada** (com `frame_id`) sobrevive à reanálise e, portanto, **não ganha posição retroativa** nesta fatia; só o "Ilustrar aqui" / `PATCH /frames` (próxima fatia) dá posição a um frame.
- **D6 — Fora desta fatia:** `Frame.posicao_no_texto`, `PATCH /frames` e `POST /capitulos/{id}/frames` com posição (**feitos na terceira fatia, logo abaixo**), "Ilustrar aqui", a imagem entre os parágrafos e o lado do app (ícone de cena, E42 estendido).

**Em linguagem simples, o que foi feito.** Quando o usuário clica em "Analisar", a IA agora devolve, para cada cena, uma frase copiada do texto onde o momento começa. O servidor procura essa frase no capítulo (primeiro igual, depois ignorando acento e aspas, depois só o começo dela, caso a IA tenha inventado o fim) e guarda o número da posição. Quando o app pede os artefatos, as cenas vêm junto dos elementos, cada uma já com a posição. Se a IA não citou, ou a citação não existe no texto, a cena vem sem posição e continua valendo.

**Divergência do plano:** o 3.4g previa as "primeiras palavras" sem dizer quantas. Um primeiro teste mostrou que fixar 6 falhava quando a IA acertava só as 4 primeiras; ficou **de 6 a 3, o mais longo primeiro**. O prompt de cena foi alterado (instrução de `trecho_ancora`), então **a taxa de acerto precisa ser reavaliada com IA real** (a medição de 30/09/2026 usou um prompt de teste) — ainda não foi feito. Migration `a1c3e5f7b9d2`.

**Testes (feitos):** o serviço de citação (exata, normalizada com acento/aspas, primeiras palavras, não achada, UTF-16 depois de um emoji, início do parágrafo); o parser da IA (`trecho_ancora` presente, ausente, não-texto); `_gerar_sugestoes` gravando a posição; o artefato de cena em cada `situacao`, o descartado fora, a ordenação misturada com elementos e o `GET` sem chamar a IA.

#### Incremento 11, terceira fatia — "Ilustrar aqui": a posição do frame (servidor; implementado em 01/10/2026, 12 testes; 500 no total; falta o app)

**O quê.** `Frame` ganha `posicao_no_texto` (inteiro, nulo; migration `d4f6b8c0e2a3`). `POST /capitulos/{id}/frames` e `PATCH /frames/{id}` aceitam o campo, e `FrameResumo`/`FrameDetalhe` o devolvem. É o que o item 7.5b chama de "Ilustrar aqui": a pessoa toca e segura um parágrafo e cria (ou posiciona) um frame ali, para trechos que a IA não sugeriu.

**Regra central: o frame manda na posição (decisão de desenho, 01/10/2026).** Uma imagem só existe num lugar, então o que o usuário põe no frame vale mais que o que a IA sugeriu:
- Um artefato que tem **frame com `posicao_no_texto`** é desenhado **na posição do frame**, não na da sugestão (nem na do nome do elemento). É assim que o usuário **corrige** um lugar que a IA errou.
- Sem posição no frame, vale o que já valia (a citação da cena, o nome do elemento).
- **Um frame que nenhuma sugestão representa** (uma cena inventada à mão, ou o retrato de um elemento que não tem sugestão neste capítulo) **vira um artefato próprio**, com `sugestao_id` nulo. **Com ou sem posição:** sem posição, cai na faixa "Sem posição" do capítulo (item 7.5b), que é o lugar de "o que não se perde".
- Um artefato de frame de **retrato** (`PERSONAGEM`) leva `tipo=ELEMENTO` e o `tipo_do_elemento` do elemento; um de **cena**, `tipo=CENA`.

**Divergência do plano (item 3.4g):** o plano dizia que o frame **herda** a posição da sugestão ao nascer dela. Não herda: o artefato já **cai para a posição da sugestão** quando o frame não tem a sua, então copiar seria duplicar um dado que pode mudar (reanálise) e que o usuário não pediu. `Frame.posicao_no_texto` só guarda o que a pessoa **escolheu**.

**Validações:** `posicao_no_texto` não pode ser negativa nem passar do fim do texto do capítulo, contada em **UTF-16** (422), como no marcador (item 3.4h).

**Em linguagem simples.** Agora um frame pode ter um lugar no texto, escolhido pela pessoa. Quando o app pede os artefatos, esse lugar vale mais que o da IA, e um frame que a IA nunca sugeriu (uma cena inventada à mão) também aparece, com ou sem lugar. Nada muda para quem não usa a posição. **Falta, no app:** o gesto de tocar e segurar um parágrafo e o "Ilustrar aqui".

**Testes:** o frame guarda e devolve a posição; recusa posição inválida; `PATCH` muda e `null` limpa; a posição do frame vence a da sugestão no artefato (cena e retrato); o frame sem sugestão vira artefato, com e sem posição; um frame que a sugestão representa **não** vira artefato repetido; confirmar uma cena não copia a posição.

#### Navegação entre capítulos por gesto (item 7.5c, implementado em 30/09/2026; 489 testes no app; ainda a validar no tablet)

**Pedido do Allan:** no leitor, **deslizar o dedo para a esquerda ou para a direita** muda de capítulo, "como é o fluxo normal dos livros". **Refinamento pedido após o primeiro teste:** a transição deve ser **suave, com a página vizinha acompanhando o dedo**: se o capítulo seguinte **ainda não foi carregado**, a página que vem junto mostra um **carregando**; se **já foi**, o **texto** dele vem acompanhando o movimento.

**A primeira versão** detectava o gesto e *substituía* a tela por uma animação depois do arrasto. Foi **substituída** por um **pager de verdade** (abaixo), e o detector de gesto saiu.

**Decisões:**
- **N1 — Sentido, como num livro:** deslizar **para a esquerda** vai ao **seguinte**; **para a direita**, ao **anterior**.
- **N2 — Por onde se passa a página:** os capítulos **não arquivados**, na ordem do livro, **mais o capítulo aberto, mesmo que arquivado** (abre-se um arquivado pela área de arquivados, e o leitor precisa começar nele).
- **N3 — O leitor é um pager sobre esses capítulos.** A **página vizinha acompanha o dedo**; cada página é um capítulo, com o **seu** ViewModel (texto e ícones). A página entra na composição quando o dedo a aproxima: **carregando** se o texto ainda não veio, **o texto** se já estava lá (já visto, ou adiantado pelo item 7.0a, L4). O pager mantém **uma página de cada lado já pronta** (`beyondViewportPageCount = 1`), então na prática o texto costuma estar pronto antes de o dedo chegar.
- **N4 — O texto nunca espera pela lista de capítulos.** O capítulo aberto aparece **sozinho, como sempre**; assim que a lista do livro chega (do aparelho, em geral na hora), o leitor passa a ser um pager com os vizinhos, **no mesmo ponto**. Se a leitura da lista falhar, o leitor segue **sem vizinhos** (nenhum gesto de virar).
- **N5 — A pilha não cresce:** passar a página **não navega**; fica na mesma tela. O "voltar" depois de ler vários capítulos leva ao **livro**. A rota continua sendo a do capítulo em que se **começou**.
- **N6 — O que é "do capítulo da tela":** o **painel de IA, o modal, os ícones e a ficha** são do capítulo em que a página **parou** (`settledPage`); o **título** acompanha a página mais à vista (`currentPage`). Trocar de página com o painel aberto no aside mostra as sugestões do novo capítulo (cada capítulo tem o seu ViewModel de painel; o `GET` é só leitura).
- **N7 — O gesto não atrapalha o resto:** é o comportamento padrão do pager de Compose — a rolagem vertical, a seleção de texto (toque longo) e o toque nos ícones continuam funcionando; só um arrasto horizontal passa a página.
- **N8 — O painel em tela cheia (celular)** fica **por cima** do pager, que **continua composto por baixo** (assim a posição de leitura de cada capítulo não se perde, E43); enquanto está aberto, o pager **não reage ao dedo**. No tablet, o painel é o aside ao lado do pager.
- **N9 — Nas pontas** não há vizinho: o pager simplesmente **não passa** além do primeiro ou do último capítulo (o aviso "Este é o primeiro/último" da primeira versão saiu: o arrasto elástico basta).

**O que não entra:** botões de "capítulo anterior/seguinte" para quem não usa gesto; vibração ou som.

**Testes:** a escolha dos capítulos do leitor (arquivados, o atual arquivado, ordem, atual ausente) e o `ViewModel` da lista (começa só com o aberto, completa com o índice certo, falha silenciosa, lê uma vez). O desenho e o gesto em si (Compose) são validados no tablet.

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
- **Mostra**: se o *servidor* tem chave (`"ambiente"`/`"ausente"`, nunca a chave em si — item 4.3) e, separado, se o app tem uma chave própria guardada no celular; modelo de extração e de prompt escolhidos; `prioridade_ia` (`ECONOMIA`/`QUALIDADE` — item 4.4).
- **Ações**: cadastrar/apagar a chave **própria, só no celular** (mandada no header `X-Chave-API-OpenRouter`); escolher os modelos a partir da lista dinâmica do OpenRouter (com filtro "só gratuitos"); trocar a prioridade de IA.

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
- [ ] Criar o projeto Android (Kotlin + Jetpack Compose) e implementar as telas da Etapa 7. **Arquitetura já especificada** (item 7.0: MVVM sem Hilt, Retrofit + kotlinx.serialization, Navigation Compose type-safe, DataStore, Tailscale, sem autenticação de app, Material 3, keystore própria) — falta só o código. **Wireframes de baixa fidelidade já publicados** (link no item 7.0), organizados nos mesmos 5 blocos de jornada — **Bloco A concluído** (item 7.3a, incrementos 1 a 5: esqueleto, Configuração, Biblioteca, remover livro e importar livro — validados no tablet). **Bloco B aprofundado** (item 7.5a, incrementos 6 a 11) e em implementação; os blocos C a E seguem aprofundados um de cada vez, antes de cada um ser codado.
- [x] ~~**Reabrir o item 4.3: `PUT /configuracao` deixa de aceitar `chave_api_openrouter`.**~~ **Implementado** (item 4.3) — header `X-Chave-API-OpenRouter` com precedência sobre a variável de ambiente, coluna removida (migration `c5d8e2f4a6b1`), `PUT` recusa o campo antigo com 422, header vazio conta como ausente. `origem_da_chave` agora é `"ambiente"` ou `"ausente"`. Testado (unitário da resolução + ligação real do header na rota); ainda não exercitado contra o OpenRouter de verdade. Decisões na Etapa 5. Achado no caminho: a listagem alfabética de `migracoes/versions` não mostra qual é a última migration — usar `alembic heads`.
- [x] ~~Refinar a engenharia do prompt de geração de imagens.~~ **Uma rodada implementada** (item 4.5/4.7): bloco de estética do prompt final separado e estruturado em vez de tecido em prosa; reforço contra linguagem temática residual na sugestão de perfil; `Elemento.imagem_ancora_padrao_id` para mitigar variação de consistência visual entre capítulos distantes e entre ferramentas de geração diferentes. Nenhuma das três mudanças de instrução foi validada com IA real ainda — vale rodar contra o corpus de validação antes de considerar madura. Novas rodadas de refinamento continuam abertas, a pedido de Allan.
- [ ] Relações entre elementos e Grupos com membros explícitos (v2, fora do escopo do MVP).
- [ ] **Armazenamento local e sincronização** (item 7.0a; contrato do servidor no item 6.9). **Especificado em 30/09/2026. Servidor implementado; app: passo 1 (Room + texto no aparelho) implementado, falta validar no tablet; passos 3 e 4 por fazer.** Offline só de leitura; Room para o índice; dois níveis (Leve e Baixado); revisão por livro; imagens em tamanhos nomeados; contas de usuário adiadas com quatro preparações. Ordem: contrato do servidor → índice e texto no aparelho → imagens pelo repositório local (junto do incremento 12) → "Baixar para ler offline". **Servidor: gzip, cache imutável e tamanho das imagens, manifesto de mídias, textos do livro e `revisao`/`ETag` já implementados** (falta só `?tamanho=`). Pendências: tamanho real das imagens geradas (o Allan relatou, em 30/09/2026, até ~2 MB e muitas de poucas centenas de KB); valores em pixels dos tamanhos nomeados; cota padrão do nível Leve.
- [x] ~~Descartar sugestão de verdade.~~ **Servidor implementado em 30/09/2026** (item 7.5b, rodada 2 do 10a: `descartada`, `PATCH /sugestoes-elemento/{id}` e `PATCH /sugestoes-cena/{id}`). **Falta o app** (regras E14 a E16; hoje o app ainda usa o "esconder" local).
- [ ] **Redesenho do layout da área do livro (ideia do Allan, 30/09/2026; a detalhar antes de qualquer código).** **Rodapé** com **ícones, sem texto**, para a navegação dentro do livro: **Elementos, Cenas, Pendências e Arquivados**; **topo** só com o **nome da tela** e o **menu de três pontos**. A **lista de Capítulos permanece como é hoje**: na tela principal, o nome do livro com alguns dados e, embaixo, a seção com a lista de capítulos. Telas de dentro (Capítulo, Ficha) ficam em tela cheia, sem a barra. **Na lista de capítulos**, ícones minimalistas e fáceis de entender para o **tamanho do capítulo** e a **quantidade de sugestões**. **Decisões do Allan (30/09/2026):** cada ícone da barra abre **uma tela**. **Pendências** é uma tela que **reúne todas as pendências de confirmação do livro, estruturadas por capítulo** (as próprias sugestões, não só a contagem — o que provavelmente exige uma rota nova no servidor que devolva as sugestões pendentes do livro inteiro; especificar antes). **Menu de três pontos:** por enquanto, as ações de hoje (editar o livro, perfil padrão, apagar). **Cabeçalho do livro:** o **nome e o autor**, com um **ícone** que abre um **modal** com os demais metadados. **Cenas:** só depois do **10b** (reforça fazer o 10b antes do layout). **As telas de Capítulo e de IA serão revistas e discutidas depois**, fora deste redesenho.
- [ ] **Capítulo ilustrado** (item 7.5b; itens 3.4g, 4.4 e 6.8): artefatos de elemento e de cena no texto, botão e painel de IA, imagem importada embutida na posição. **Especificado em 30/09/2026, nada implementado.** Pendências de validação: (a) ~~a taxa de acerto da citação de âncora com IA real (maior risco)~~ — **medida em 30/09/2026** (item 3.4g): a posição é achada em ~99% dos casos, e para elementos o nome é melhor que a citação; **reavaliado com o prompt de produção em 01/10/2026: 98% a 100% das cenas** (item 3.4g); (b) o desenho detalhado das abas do painel; (c) o comportamento do aside no tablet e da tela de IA no celular; (d) imagens reduzidas no servidor; (e) o que o OpenRouter oferece para gerar imagem, antes de tirar o botão "Gerar imagem" do estado reservado.
- [x] ~~Implementar sugestões persistidas (`SugestaoDeElemento`/`SugestaoDeCena`/`SugestaoDeParticipante`), busca por nome cross-capítulo e confirmação em lote.~~ Concluído — item 3.4e, validado com o caso real do "Sextus Hospius"/"Hospius".
- [ ] **Discutir: virar um leitor de EPUB completo, não só gerador de prompts/imagens (01/10/2026).** Mudança de visão registrada no item 1.1. Levantamento comparativo contra leitores de mercado (Kindle, Moon+ Reader, ReadEra, Apple Books, Libby, FBReader), lacunas priorizadas e perguntas em aberto por funcionalidade (retomar leitura, tipografia/tema, sumário navegável, busca no texto, marcadores/destaques, entre outras) estão em `EXPERIENCIA_DE_LEITURA.md` — documento de pesquisa separado, grande demais pra viver dentro desta especificação. Nenhum item de lá tem decisão tomada; cada um só entra de fato nesta especificação quando for discutido e fechado, seguindo o fluxo normal do `CLAUDE.md`.
- [ ] **Discutir: chat dentro do livro para conversar com a IA sobre o que está sendo lido (01/10/2026).** Ideia levantada por Allan, ainda sem especificação — registrada só como tópico a discutir, nada decidido. Perguntas em aberto que precisam de resposta antes de virar item de Etapa: que contexto a IA recebe (só o capítulo atual? todos os capítulos já lidos/ignorados? os elementos/estados já confirmados?); a conversa é persistida (nova entidade, tipo `MensagemDeChat` ligada a `Livro` e/ou `Capitulo`) ou é descartável, só de sessão; isso é por livro ou por capítulo; tem risco de o chat divergir do canon que as entidades `Elemento`/`EstadoElemento` já capturam (a IA "inventando" resposta fora do que foi confirmado); e qual o custo de IA por mensagem, já que hoje o modelo de custo do projeto é só por capítulo analisado (item 4.3/4.4), não por interação livre. Não é escopo do MVP (item Escopo do CLAUDE.md) até ser especificado.
- [ ] **Discutir: opção de gerar a imagem diretamente no app, além de só gerar o prompt (01/10/2026).** Reabre a decisão do item 7.7 (hoje: só gera prompt, usuário abre no Gemini via `Intent.ACTION_SEND`) — não substitui, oferece como alternativa. Depende de resolver primeiro a pendência em aberto sobre a chave de API do Gemini (ver discussão de 29/09/2026 acima, ainda sem resposta do Allan). Perguntas em aberto: (1) **precisa de configuração de modelo de geração de imagem**, análoga à de modelo de texto (item 4.3) — qual provedor/modelo, custo por imagem, e se isso fica em `Configuracao` (item 3.4d) ou num novo campo por `PerfilRenderizacao`; (2) a opção de abrir no Gemini continua existindo lado a lado, ou vira só um modo entre outros; (3) geração de imagem é assíncrona de verdade (precisa do indicador de carregamento já citado como pendência no item 7.7) — como o app avisa quando terminar; (4) onde a imagem gerada é salva (mesmo fluxo de `Imagem`/catálogo do item 6.6, ou caminho novo).
- [ ] **Discutir: guardrails obrigatórios para imagens envolvendo crianças e adolescentes (01/10/2026).** Levantado por Allan junto com o item de conteúdo sensível abaixo — tratar como requisito de segurança não-negociável, não como configuração opcional a ser ligada/desligada. Perguntas em aberto: como o sistema identifica que um `Elemento` é uma criança/adolescente (campo de faixa etária em `Elemento`, inferido pela IA na fase de identificação do item 4.4, ou os dois); o que acontece quando identificado — forçar um modelo moderado (`somente_nao_moderados`, já existe como filtro em `GET /configuracao/modelos`, item 4.3) para qualquer prompt que referencie esse elemento, reforço de instrução no prompt final (item 4.5), ou bloqueio de certas combinações de palavras-chave antes mesmo de chamar a IA; e se a checagem vale só pra elementos identificados como criança/adolescente ou também pra cenas/frames sem elemento nomeado (ex.: "multidão de crianças brincando"). Esse guardrail vale **mesmo que o item de conteúdo sensível abaixo seja implementado** — não é algo que se desliga junto.
- [ ] **Discutir: obter a imagem de capa do livro para exibir na Biblioteca (01/10/2026).** Hoje `Livro` (item 3.4a) não tem nenhum campo de capa, e a importação do EPUB (item 2.2) descarta a página de capa como "documento sem texto útil" — mas isso é a página XHTML da capa, não a imagem em si; o arquivo de imagem da capa (`.jpg`/`.png`, referenciado no manifesto do EPUB via `properties="cover-image"`) nunca chegou a ser extraído. A tela de Biblioteca (item 7.2) hoje não mostra nenhuma imagem por livro. Perguntas em aberto: extrair a capa do próprio EPUB no momento da importação (igual o catálogo de imagens do item 6.6 já guarda arquivo com nome via `uuid4`) versus deixar como campo opcional pra quando não tiver capa no arquivo; o que mostrar quando o EPUB não define `cover-image` (hoje nenhum fallback existe — precisa de um texto reserva como os já usados noutros lugares, ex. iniciais do título); se a capa é servida como arquivo estático (mesmo padrão do catálogo de imagens) ou embutida em base64 na resposta de `GET /livros`; e se isso é MVP (afeta a tela mais usada do app) ou fica pra depois.
- [ ] **Discutir: mecanismo para geração de imagens com conteúdo sensível, como violência ou nudez artística (01/10/2026).** Levantado por Allan para cenas de livros que descrevem esse tipo de conteúdo (comum em ficção adulta). Importante deixar registrado desde já: qualquer "mecanismo" aqui só pode operar **dentro do que a política de conteúdo do provedor/modelo de IA escolhido já permite** — não é viável, e não faz parte do escopo deste projeto, construir algo que contorne a moderação de um provedor. Na prática isso provavelmente significa: (1) permitir escolher, por `Configuracao` ou por `PerfilRenderizacao`, um modelo cuja política já cobre conteúdo artístico maduro (o filtro `moderado`/`somente_nao_moderados` do item 4.3 já distingue isso); (2) o prompt final (item 4.5) refletir fielmente o que o capítulo descreve, inclusive violência/nudez, em vez de suavizar automaticamente; (3) o guardrail de crianças/adolescentes acima continua valendo integralmente, sem exceção, mesmo com esse modo ativado. Ainda sem decisão nenhuma — fica para quando o Allan quiser aprofundar.

### Defeitos e pedidos achados no teste do tablet (01/10/2026)

Teste do Allan com o app, depois do incremento 11 (ícones de elemento) e da navegação por gesto. Os itens 1, 2, 3 e 5 são do **app**; o 2 também pede um campo novo no **servidor**; o 4 é uma funcionalidade nova que precisa de especificação antes de qualquer código.

- [x] **D1 — Aviso de análise concluída, mesmo fora da tela.** Ao clicar em "Analisar" no painel de IA do capítulo e **sair da tela antes de terminar**, o usuário não fica sabendo. **Decidido pelo Allan (01/10/2026):** um aviso curto (*snackbar*/toast), **no canto inferior direito**, dizendo que a análise **foi concluída** (e, se falhar, que falhou), com o **alcance dependendo de onde a pessoa está**: **dentro do livro**, só o capítulo ("Análise do capítulo X concluída"); **fora do livro** (Biblioteca ou outra tela), o livro e o capítulo ("Análise concluída: *livro*, capítulo X"). Consequência técnica: **a análise precisa sobreviver à saída da tela de capítulo** (hoje ela vive no ViewModel dele) e o aviso precisa morar num lugar **acima da navegação**, que saiba em que livro o usuário está. Tocar no aviso poderia levar ao capítulo — a decidir no app. **Autorizado pelo Allan a implementar (01/10/2026).** **App implementado em 01/10/2026 (521 testes; falta validar no tablet):** `ServicoDeAnalises` no escopo do app roda o `POST` (uma análise por capítulo de cada vez) e emite um evento ao terminar; um avisador global (`AvisadorDeAnalises`) mostra o *snackbar* **centralizado, bem embaixo e translúcido** (ajuste do Allan após o teste de 01/10/2026: a primeira versão, no canto inferior direito, ficou mal posicionada), para não esconder o texto. **Dentro do livro:** "Análise do capítulo 3 concluída." **Fora:** "Análise concluída em «Livro», capítulo 3." **Falha:** o mesmo, com o motivo (o 409 de outro aparelho aparece assim). **Sem aviso** para quem está olhando o painel daquele capítulo (o resultado já aparece nele). Quem volta ao capítulo com a análise rodando reencontra o "analisando" e recebe o resultado, sem cobrar de novo. *Ainda não feito:* tocar no aviso para ir ao capítulo.
- [x] **D2 — A lista de cenas aparece em todas as abas do painel (pendentes, confirmadas, descartadas).** **Servidor implementado (01/10/2026):** `CenaSugerida` ganhou `frame_id` (nulo = pendente, preenchido = confirmada; item 6.7) — antes o app **não tinha como** saber se a cena estava confirmada. **Falta o app:** a seção "Cenas" é uma lista única no fim do painel e só exclui as descartadas (`PainelDeIa.kt`), sem obedecer à aba; distribuir como já se faz com os elementos (descartada → Descartadas; com `frame_id` → Confirmadas; senão → Pendentes). **Autorizado pelo Allan a implementar no app (01/10/2026).** **App implementado em 01/10/2026:** as cenas obedecem ao filtro (pendentes, confirmadas, descartadas) pelo `frame_id`, e os contadores somam elementos e cenas. **Teste do Allan (01/10/2026):** como ainda **não há botão para confirmar cenas** (é o 10b), todas aparecem em Pendentes; as abas Confirmadas e Descartadas só se enchem depois do 10b. A cena descartada ainda não tem "Restaurar" (também do 10b).
- [ ] **D3 — A ficha do personagem ainda "pisca" e volta ao perfil quando se usa a seta nativa de voltar do Android** (o botão/gesto do sistema). Pela seta de cima do app funciona. É a **terceira** rodada deste defeito (E43): a correção anterior partiu de uma hipótese e **nunca foi reproduzida fora do tablet**. O passo registrado era ler o `logcat` do tablet; falta fazê-lo. Pista: só o caminho do **sistema** falha, e é o que passa pelo `BackHandler`/`OnBackPressedDispatcher`, não pelo botão da barra — vale comparar os dois caminhos. **Allan: "temos que corrigir" (01/10/2026).** **Em 01/10/2026:** o Allan enviou o logcat; ele mostra o modal da sugestão abrindo e sendo removido em ~0,4 s, mas **não registra a navegação**, então a causa continua desconhecida. Entrou um **rastro temporário** (tag `ImagineerNav`, `Rastro.kt` no app): cada mudança de tela com o tamanho da pilha, os pedidos de abrir e voltar da ficha com quem chamou, e o abrir/fechar do modal. **Próximo passo:** o Allan reproduz o erro e envia o Logcat filtrado por `ImagineerNav`; o rastro sai quando o D3 for resolvido. **Causa achada em 01/10/2026 (rastro do Logcat) e corrigida, a validar no aparelho:** o modal e os diálogos do painel são **janelas próprias** e eram desenhados assim que o capítulo chegava a `STARTED`. Mas o "voltar" do Android **anima a volta enquanto o gesto acontece**, e nessa fase o capítulo já está `STARTED` (visível por baixo da ficha) sem ser `RESUMED`. A janela do modal nascia por cima no meio do gesto, virava o destino do "voltar" e **cancelava a animação da navegação**: a ficha reaparecia ("pisca e volta") **sem registrar nenhuma mudança de tela**, e vários toques seguidos só funcionavam quando um deles pegava a navegação antes de o modal compor — exatamente o que o Logcat mostrou. A seta de cima do app funcionava porque não usa o gesto animado. **Correção:** modal e diálogos só são desenhados com o capítulo **`RESUMED`** (na frente e com a animação terminada). **Efeito colateral aceito:** ao voltar da ficha, o modal reaparece **depois** da animação (~0,3 s), e não junto dela. O rastro `ImagineerNav` foi removido em 01/10/2026, depois de o Allan confirmar no aparelho. **Ajuste de 01/10/2026 (feedback do Allan):** com o D3 corrigido, o modal reaparecia sozinho "instantes depois" de voltar da ficha, o que parecia um defeito. **Regra nova: "Ver ficha" a partir do modal FECHA o modal**; ao voltar, a pessoa cai no texto onde estava. Os **diálogos** (vincular, criar...) continuam reaparecendo como estavam: estão no meio de uma tarefa (E43). Isto **revoga** a parte do E43(a) que dizia que o modal deve ser reencontrado ao voltar da ficha.
- [ ] **D4 — Saber onde o leitor parou: "marcador" e "pin" (funcionalidade nova; vocabulário e onde guardar decididos em 01/10/2026; rotas e telas a especificar).** O livro deve guardar **onde a pessoa parou de ler**, como os leitores de EPUB conhecidos. **Vocabulário decidido pelo Allan** (e que **muda um nome já existente**):
  - **"Artefato"** passa a ser o nome dos **ícones no texto do capítulo** (antes "marcador": a rota `/marcadores` e as classes `Marcador`, `TipoDeMarcador`, `MarcadoresDoCapitulo`, `SituacaoDoMarcador`, hoje `Artefato`, `TipoDeArtefato`, `ArtefatosDoCapitulo`, `SituacaoDoArtefato`). **Renomeado no servidor em 01/10/2026** (item 6.8), com a rota e o campo antigos mantidos como **alias** até o app migrar — era a primeira etapa do D4, porque o código não pode ter dois "marcadores". **App migrado em 01/10/2026** (rota `/artefatos`, classes `Artefato*`); o alias `/marcadores` do servidor já pode ser removido assim que o app novo estiver instalado no tablet.
  - **"Marcador"** passa a ser a **posição de leitura automática**: o capítulo e o deslocamento no texto do último ponto visto, gravados sozinhos enquanto se lê; o livro **reabre ali** ("Continuar lendo" na Biblioteca e na tela do Livro). Um por livro.
  - **"Pin"** é a posição **marcada à mão**, com nota opcional; vários por livro, numa lista. Destaques de trecho ficam para depois.
  - **Onde guardar: no servidor** (vale em qualquer aparelho). **E a informação viaja junto quando o livro for baixado** para ler offline (itens 6.9 e 7.0a): marcador e pins entram no que o "Baixar para ler offline" leva, e na `revisao` do livro.
  - **A posição usa o mesmo contrato do `posicao_no_texto` (item 3.4g):** deslocamento em **UTF-16** desde o início de `Capitulo.texto`, para não depender de como o app divide parágrafos.
  - **Especificado em 01/10/2026** (itens 3.4h e 6.10): entidades `Marcador` e `Pin`, rotas, regra de conflito entre aparelhos (o mais recente pelo `lido_em` do aparelho vence) e o "baixar livro". **Servidor: implementado em 01/10/2026 (18 testes). App: a fazer — tela de pins, "continuar de onde parou" e a gravação automática.** Ainda em aberto, só para o app: como o marcador e os pins aparecem nas telas.
- [x] **D5 — Sem rede, sair do livro para a Biblioteca mostra "não consegui conectar com o servidor". ~~Defeito~~ Esperado hoje (decisão do Allan, 01/10/2026).** Com o Wi-Fi desligado, a Biblioteca mostra só essa mensagem. O Allan considera **esse o comportamento esperado por ora**: a Biblioteca ainda depende do servidor, e a leitura offline vale para os **capítulos já guardados** (item 7.0a), não para a lista de livros. Fica como **melhoria possível, não pedida**: a Biblioteca mostrar os livros guardados no aparelho quando não há rede (o dado já existe no Room, `livro_local`).

- [x] **M1 — Reanálise com orientação do usuário.** **Servidor implementado em 01/10/2026** (item 6.7, "Reanálise com orientação do usuário"): corpo opcional `{"orientacao"}` no `POST /capitulos/{id}/sugestoes`, guardada no capítulo e devolvida em `orientacao`. **Falta o app:** um campo de texto no "Reanalisar" ("o que a análise não pegou?"), mostrando a orientação vigente e deixando apagar. **App implementado em 01/10/2026:** o diálogo de Reanalisar ganhou o campo "O que a análise não pegou?" (até 1000 caracteres), já preenchido com a orientação que vale; só vai ao servidor o que mudou (igual = nada de novo; apagado = vazio, que apaga).
- [ ] **M2 — Botão de pesquisar no capítulo (melhoria pedida em 01/10/2026; do app).** Busca dentro do texto do capítulo aberto, com avanço entre as ocorrências. É a "busca no texto" da lista do `EXPERIENCIA_DE_LEITURA.md` (prioridade 4). A busca no capítulo já carregado pode ser **só do app** (o texto está lá); busca no livro todo é outra conversa (item 6.2 teria de ganhar uma rota).
- [ ] **M3 — Guardar o custo de cada chamada de IA, para métricas (pedido em 01/10/2026; ver "Custo das chamadas de IA" no item 4.3).** O OpenRouter devolve o custo e os tokens de cada chamada; o servidor passa a **gravar** isso.

- [ ] **Decisão do Allan (01/10/2026): o Raspberry Pi só recebe a migração no fim do projeto.** Até lá, desenvolve-se e testa-se **localmente**; o roteiro do `SERVIDOR.md` fica pronto para quando chegar a hora. As migrations novas continuam sendo criadas normalmente.

### Pendências técnicas (achadas revisando a API, ainda sem decisão de implementar)

- [x] **`PATCH /capitulos/{id}` devolve o texto do capítulo — decidido em 01/10/2026: deixar como está (opção a).** O Allan arquiva **no máximo uns 5 capítulos de uma vez** no uso normal (os demais, um a um): o custo do texto trafegando é pequeno e o app já trata a falha no meio do lote ("K de N arquivados"). Uma rota em lote só se o arquivamento em massa ficar lento na prática. *Texto original:* **devolve o texto do capítulo, e o arquivamento em lote multiplica esse custo.** Achado na revisão de código do app (30/09/2026). O item 7.5a (incremento 6) já decidiu **aceitar** o texto trafegando sem uso, porque era "um toque ocasional" (até ~110 KB no maior capítulo dos livros de validação) e evitava mexer no backend. Essa conta mudou com a seleção em lote (segunda revisão do incremento 6, **uma chamada por capítulo**): arquivar N capítulos baixa N textos completos só para o app descartá-los (30 capítulos de ~100 KB ≈ 3 MB). Opções, sem decisão ainda: (a) manter como está (custo baixo sobre Tailscale); (b) uma rota em lote, tipo `PATCH /livros/{id}/capitulos` recebendo os ids e o `ignorado`, que devolveria só `CapituloResumo`; (c) o `PATCH /capitulos/{id}` passar a devolver `CapituloResumo` — contraria a convenção do item 6.1 (todo `PATCH` devolve a versão completa) e por isso é a menos indicada. **Não bloqueia o app**: ele já lê só o `CapituloResumo` e ignora o resto. Reavaliar se o lote ficar lento na prática ou se surgir uso em dados móveis.
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

- [x] **Camada `servicos/` subutilizada em rotas complexas — resolvido para `rotas/elementos.py` (01/10/2026); `rotas/frame.py` e `rotas/prompts.py` ficam.** `rotas/elementos.py` caiu de **1.697 para 773 linhas**. A lógica saiu para dois serviços novos: `servicos/sugestoes.py` (gerar as sugestões, casar com os elementos cadastrados, contar as pendentes, montar o contexto da IA) e `servicos/artefatos.py` (montar os artefatos do capítulo), **sem conhecer HTTP** (os erros sobem como exceções do domínio e o tratador global os traduz). As rotas de sugestões e de artefatos foram para um módulo próprio, `rotas/sugestoes.py` (437 linhas). **Verificado:** as **61 rotas** da aplicação (método, caminho, corpo e respostas, comparadas com o `openapi()` antes e depois) são **idênticas**; 526 testes verdes. Único efeito visível: no `/docs`, as rotas movidas passam da etiqueta "Elementos" para "Sugestões". *Ficou de fora, por ser outro assunto:* `_sugestoes_de_elemento_do_livro` (valida o pedido HTTP, 404/422) segue em `rotas/elementos.py`, porque um serviço que levanta `HTTPException` deixaria de ser independente de HTTP. *Texto original:* `rotas/elementos.py` (cerca de 1100 linhas — 1103 conferidas em 30/09/2026) e `rotas/frame.py` carregam lógica de negócio inteira em funções privadas (`_gerar_sugestoes`, `_casar_sugestoes_pendentes`, `_resolver_titulo`, `_resolver_estados_da_sugestao`, `_estados_do_livro`) em vez de em serviço puro — diferente do padrão já bem seguido por `estados_de_elemento.py`, `identidade_de_elemento.py`, `importacao_epub.py`, `upload.py` e `catalogo_imagens.py`. Consequência prática: essa lógica só é testada indiretamente via `TestClient` (rota), nunca isolada; e mistura orquestração HTTP com regra de negócio. Quando for mexer nessas rotas de novo, vale extrair pra serviço em vez de crescer mais a função privada.
- [x] **Helpers de busca duplicados entre módulos de rota.** **Resolvido em 01/10/2026:** uma só implementação em `rotas/_comum.py` (`obter_ou_404`) e uma função fina por entidade; 14 cópias removidas de 7 módulos (159 linhas a menos), as mensagens de 404 idênticas, 520 testes verdes. *Texto original:* `_buscar_livro`, `_buscar_elemento`, `_buscar_frame`, `_buscar_capitulo` são reimplementados quase identicamente em `rotas/livros.py`, `rotas/elementos.py` e `rotas/frame.py` (mesmo padrão: busca por id, 404 se não achar). Um helper genérico (`get_or_404`) num módulo compartilhado eliminaria a repetição.
- [x] **Sem exception handler global.** **Resolvido em 01/10/2026:** `imagineer/erros.py` traduz os erros do domínio em respostas HTTP num lugar só (`ChaveDeApiAusente`, `ModeloNaoEscolhido`, `TextoLongoDemais` → 422; qualquer outro `ErroDoProvedorIA` → 502; `AnaliseEmAndamento` → 409). Removeu **quatro cópias idênticas** do mesmo `try/except` (sugestões, perfil, prompt, lista de modelos) e as três verificações "nenhum modelo escolhido" passaram a levantar `ModeloNaoEscolhido`, a mesma exceção que o provedor já usava. Corpo e mensagens iguais (`{"detail": ...}`), 526 testes verdes. O Starlette escolhe o tratador **mais específico** pela hierarquia (testado: `ChaveDeApiAusente` é filha de `ErroDoProvedorIA` e dá 422, não 502). *Texto original:* Todo erro é `HTTPException` lançada ad-hoc dentro da rota/função auxiliar — consistente entre rotas (404/422/409/502 usados do jeito certo), mas sem um `@app.exception_handler` centralizando o padrão. Não é um problema hoje, só fica mais visível se o número de rotas crescer.
- [ ] **`rotas/elementos.py` ainda tem 5 `APIRouter` (prefixos `/livros`, `/elementos`, `/estados`, `/capitulos` e `/historico-identidade`), mas o arquivo caiu de 1.697 para 773 linhas** (01/10/2026, ver o item acima). Deixa de ser urgente; reavaliar se voltar a crescer. *Texto original:* **acumula 5 `APIRouter` diferentes no mesmo arquivo** , organizado por "recurso lógico" em vez de por rota REST — documentado no docstring do próprio arquivo, mas vale reconsiderar se o arquivo continuar crescendo.
- [ ] **Escolher os modelos dentro do app** (pedido do Allan, 02/10/2026): buscar e escolher o modelo de **imagem** (e os de texto) sem sair do app para consultar o site do OpenRouter. Hoje os ids entram à mão em `PUT /configuracao`. Exige: filtrar `output_modalities=image` na listagem do OpenRouter (hoje `GET /configuracao/modelos` só traz texto), e mostrar preço por imagem e se o modelo é moderado. Especificar antes de implementar.
- [ ] **Perfil (ficha) do elemento sem as imagens dele nem as cenas em que aparece** (achado do Allan no tablet, 02/10/2026): na tela do catálogo, tocar num elemento abre a ficha, e ali **não aparecem as imagens do elemento** (retrato, gerado ou importado) **nem as cenas em que ele participa**. Falta, no mínimo: uma rota que junte as imagens dos frames do elemento e as cenas em que ele é participante (provavelmente `GET /elementos/{id}/imagens` e `GET /elementos/{id}/cenas`, a confirmar lendo o item 6.3 e as tabelas de ligação), e a seção correspondente na ficha (item 7.4). **Decidido (Allan, 02/10/2026): registrar agora e fazer em momento oportuno.** Especificar antes de implementar.

**Pontos fortes confirmados na mesma revisão** (não é pendência, registrado pra não reabrir a dúvida): sessão de banco via `Depends`/`yield` correta, sem N+1 óbvio (usa agregação no banco); schemas Pydantic com `Field` de constraints reais, enums e separação `*Novo`/`*Ajuste`/`*Resumo`/`*Detalhe` consistente; migrações Alembic bem geridas (14, nomes descritivos, convenção de nomes de constraint definida desde o início); sem SQL injection, sem path traversal no upload (nomes de arquivo via `uuid4`), sem segredo vazando em log; ~7100 linhas de teste com boa cobertura de rota e um provedor de IA falso (`ia/falso.py`) pra testar sem custo real.
