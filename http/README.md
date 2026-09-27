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
   reaproveitam essa variável (`{{livroId}}`, `{{frameId}}` etc.) — é assim que
   dá para abrir um elemento ou criar um frame sem copiar id na mão.
5. Variáveis globais persistem entre arquivos na mesma sessão do PyCharm. Se
   fechar a IDE ou quiser recomeçar do zero, rode de novo a requisição de
   importação do livro (`01-livros.http`) para gerar ids novos.

## Manutenção: confira as rotas a cada mudança

Toda vez que uma rota, schema ou nome de entidade mudar no código (renomeio,
campo novo obrigatório, path novo), esses arquivos ficam desatualizados
silenciosamente — não há teste automatizado que rode `.http`. Depois de
qualquer mudança desse tipo, releia os arquivos afetados e confira, contra o
código em `imagineer/rotas/` e `imagineer/esquemas/`, se o método, o path e os
campos do corpo ainda batem. Foi assim que o `POST /capitulos/{id}/frames`
com `tipo: PERSONAGEM` ficou sem `titulo` por um tempo depois do renomeio de
`Cena` para `Frame` — o campo continuou obrigatório no schema, mas o exemplo
não foi atualizado.

## Numeração dos arquivos

Segue a ordem do fluxo (Etapa 2 da especificação) e da Etapa 6:

| Arquivo | Cobre |
|---|---|
| `00-saude.http` | Item 6.1 — confere se a API está no ar |
| `01-livros.http` | Item 6.2 — importar, listar, abrir, ajustar, remover |
| `02-capitulos.http` | Item 6.2 — abrir um capítulo, marcar como ignorado |
| `03-elementos-e-estados.http` | Item 6.3 — cadastrar elementos, registrar estados, estados vigentes |
| `04-frames-e-perfis.http` | Itens 6.4 e 6.5 — frames (tipo PERSONAGEM ou CENA) e perfis de renderização |
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

Modelo escolhido: `openai/gpt-4o-mini`

## Sobre a leitura profunda e a fundamentação (item 4.4, fases 2 e 3)

`POST /frames/{id}/prompts` pode reler o capítulo em dois momentos diferentes,
com efeitos e prioridades diferentes:

- **Fase 2 — leitura profunda do elemento**: relê o capítulo de origem de
  cada estado do frame e **sobrescreve** a descrição salva no banco — para a
  aparência de um elemento, o livro é a fonte de verdade, mesmo que substitua
  o que foi digitado à mão.
- **Fase 3 — fundamentação do frame** (só para `tipo: CENA`): relê o capítulo
  para montar um `contexto_do_livro` que **apoia** o prompt, mas **não**
  sobrescreve título, descrição nem atributos do frame — o que o usuário
  escreveu sobre a cena tem prioridade, exatamente para evitar que uma
  alucinação ou ambiguidade da IA desvie o prompt. Frames do tipo PERSONAGEM
  pulam esta fase — é retrato solo, não há cena para fundamentar.

Por padrão (`prioridade_ia: ECONOMIA`) as duas fases só acontecem uma vez por
estado/frame; rodar a mesma requisição de novo é rápido e barato, porque
reaproveita a leitura anterior. Com `prioridade_ia: QUALIDADE`, relê toda vez
— mais fiel, mais lento, mais caro. Um comentário no corpo (`comentario`) tem
prioridade máxima sobre as duas fases.

## Sobre sugestões persistidas (item 3.4e)

Cada elemento/frame sugerido em `06-sugestoes.http` tem `id` próprio, salvo no
banco — não é mais um rascunho que some depois da resposta. Isso habilita:
`GET /livros/{id}/sugestoes-elemento?nome=...`, para achar todas as menções
de um nome no livro inteiro, mesmo em capítulos diferentes; `sugestoes_elemento_ids`
em `POST /livros/{id}/elementos` e a rota própria `POST
/elementos/{id}/estados-de-sugestoes`, para confirmar várias sugestões de
uma vez como o mesmo Elemento; e `sugestao_frame_id` em `POST
/capitulos/{id}/frames`, para criar o frame direto da cena sugerida. Exemplos
nos três arquivos (`03`, `04`, `06`).

## Limpar Banco de Dados
 `docker exec imagineer-api-1 alembic downgrade base`
 `docker exec imagineer-api-1 alembic upgrade head`  
