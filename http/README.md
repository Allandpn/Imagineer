# Testando a API pelo HTTP Client do PyCharm

Estes arquivos `.http` cobrem as rotas da Etapa 6 da especificação, na ordem em
que o fluxo do sistema as usa. Servem para testar manualmente, sem precisar
importar nada no Postman.

## Como usar

1. Abra qualquer arquivo `.http` no PyCharm.
2. No canto superior direito de cada requisição, escolha o ambiente **dev**
   (vem de `http-client.env.json` — só define `baseUrl`, nenhum segredo).
3. Suba a API antes de rodar (`docker compose up -d`, ou `uvicorn
   imagineer.principal:aplicacao --reload` a partir do venv).
4. Rode as requisições **na ordem do arquivo**: as de criação guardam o id
   criado numa variável global (`client.global.set(...)`), e as de baixo
   reaproveitam essa variável (`{{livroId}}`, `{{cenaId}}` etc.) — é assim que
   dá para abrir um elemento ou criar uma cena sem copiar id na mão.
5. Variáveis globais persistem entre arquivos na mesma sessão do PyCharm. Se
   fechar a IDE ou quiser recomeçar do zero, rode de novo a requisição de
   importação do livro (`01-livros.http`) para gerar ids novos.

## Numeração dos arquivos

Segue a ordem do fluxo (Etapa 2 da especificação) e da Etapa 6:

| Arquivo | Cobre |
|---|---|
| `00-saude.http` | Item 6.1 — confere se a API está no ar |
| `01-livros.http` | Item 6.2 — importar, listar, abrir, ajustar, remover |
| `02-capitulos.http` | Item 6.2 — abrir um capítulo, marcar como ignorado |
| `03-elementos-e-estados.http` | Item 6.3 — cadastrar elementos, registrar estados, estados vigentes |
| `04-cenas-e-perfis.http` | Itens 6.4 e 6.5 — cenas e perfis de renderização |
| `05-configuracao-ia.http` | Item 6.7 — chave, modelos, escolha de modelo |
| `06-sugestoes.http` | Item 6.7 — `POST /capitulos/{id}/sugestoes` (passo 6, precisa de chave configurada) |
| `07-prompts-e-imagens.http` | Item 6.6 — montar prompt, catálogo de imagens |

## Sobre o arquivo EPUB de `01-livros.http`

Nenhum EPUB fica dentro do repositório (são arquivos grandes e, em geral,
protegidos por direito autoral). Ajuste o caminho no `< caminho...` da primeira
requisição para um EPUB real na sua máquina antes de rodar.

## Sobre `06-sugestoes.http` e a parte de IA de `07-prompts-e-imagens.http`

Fazem chamada de verdade ao OpenRouter — precisam de `CHAVE_API_OPENROUTER` (ou
`IMAGINEER_KEY_OPEN_ROUTER`) configurada no ambiente, e de `modelo_extracao` e
`modelo_prompt` escolhidos em `05-configuracao-ia.http` primeiro (os dois: o
`modelo_extracao` também é usado na leitura profunda, ver abaixo). Modelos
gratuitos às vezes respondem 429 (limite de uso) por estarem sobrecarregados —
não é erro do sistema; troque de modelo na requisição de configuração e tente
de novo.

## Sobre a leitura profunda (item 4.4, fase 2)

`POST /cenas/{id}/prompts` relê o capítulo de origem de cada estado da cena
antes de montar o prompt, e **sobrescreve** a descrição salva no banco — o
livro é a fonte de verdade, mesmo que substitua o que foi digitado à mão. Por
padrão (`prioridade_ia: ECONOMIA`) isso só acontece uma vez por estado; rodar
a mesma requisição de novo é rápido e barato, porque reaproveita a leitura
anterior. Com `prioridade_ia: QUALIDADE`, relê toda vez — mais fiel, mais
lento, mais caro. Um comentário no corpo (`comentario`) tem prioridade sobre
os dois.
