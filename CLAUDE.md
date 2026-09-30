# CLAUDE.md — Regras do Projeto Imagineer

Este projeto é ao mesmo tempo um sistema real e um projeto de aprendizado de programação. As regras abaixo existem para os dois objetivos ao mesmo tempo: gerar um sistema funcional e garantir que Allan entenda o que está sendo construído, passo a passo.

## Idioma

Todo o sistema é em português: nomes de entidades, classes, variáveis, campos, endpoints, mensagens de log, comentários, docstrings e qualquer texto de interface. Exceção apenas para termos técnicos já naturalizados no vocabulário de desenvolvimento em português (ex: *prompt*, *backend*, *endpoint*, *deploy*, *docker*) e para identificadores exigidos por bibliotecas/frameworks de terceiros (ex: métodos e classes do SQLAlchemy, FastAPI, palavras-chave do Python). Ao criar uma entidade, endpoint ou variável nova, usar nome em português — se não houver uma tradução natural, perguntar antes de adotar o termo em inglês.

## Fluxo de trabalho obrigatório

Para qualquer funcionalidade nova, seguir sempre esta ordem — nunca pular direto para código:

1. **Especificar**: descrever o que vai ser feito e por quê, antes de qualquer linha de código.
2. **Documentar**: atualizar `ESPECIFICACAO.md` (seção Etapa → Item correspondente) com a especificação acordada.
3. **Implementar**: só depois dos passos 1 e 2 estarem registrados.
4. **Testar**: nenhum item é considerado concluído sem teste, mesmo que simples.

Se um item não tiver etapa/seção correspondente ainda em `ESPECIFICACAO.md`, criar a seção primeiro.

## Explicações e aprendizado

Allan está aprendendo a programar através deste projeto e quer entender o sistema, não apenas receber código pronto.

- Ao implementar algo, explique o raciocínio por trás das escolhas — não só "o quê", mas "por quê".
- Prefira incrementos pequenos e revisáveis a grandes blocos de código de uma vez só.
- Ao concluir um item, atualize a seção correspondente da especificação com uma explicação em linguagem simples do que foi implementado de fato (pode divergir do plano original — nesse caso, registre a divergência e o motivo).
- Se uma decisão de arquitetura não estiver coberta pela especificação, pergunte antes de decidir sozinho.

## Estilo de código Python

- Seguir PEP8; usar type hints e docstrings em funções e classes públicas.
- Priorizar clareza sobre "esperteza" — o código deve ensinar, não apenas funcionar.
- Evitar abstrações prematuras: implementar o necessário para o MVP definido na especificação, não além.

## Testes

- Todo item novo precisa de teste (unitário, no mínimo) antes de ser considerado fechado.
- Não avançar para o próximo item com testes quebrados.
- A cada mudança que afete rotas, schemas ou nomes de entidade (renomeio, novo campo obrigatório, mudança de path), conferir se a coleção `.http` em `http/` ainda bate com o código — método, path, campos do corpo — e corrigir o que estiver desatualizado antes de considerar a mudança concluída.

## Git e versionamento

- Commits pequenos, idealmente um por item da especificação.
- Mensagens de commit explicando o motivo da mudança, não só o que mudou.
- Nunca commitar API keys ou segredos — usar `.env` (incluído no `.gitignore`).

## Escopo

- MVP primeiro: Elemento + EstadoElemento + Frame + Prompt + Imagem, conforme Etapa 3 da especificação.
- Relações entre elementos e Grupos com membros explícitos ficam para uma v2 — não implementar mesmo que pareça simples, sem antes atualizar a especificação para incluir esse escopo.

## O app Android e a especificação compartilhada

O app Android (repositório `Allandpn/Imagineer-App`) consome esta API e segue esta especificação.

- **`ESPECIFICACAO.md` é a única cópia editável.** O app não guarda cópia própria, então as duas versões não têm como divergir.
- **O Claude do app também escreve aqui**, quando o app precisa de uma mudança de rota, de campo ou de tela. Só **documentação**: o código da API não é alterado a partir de uma sessão do app.
- **Regras de convivência** (valem para quem escrever, aqui ou no app):
  - branch curta, criada a partir da `main` **atualizada**; nunca push direto na `main`;
  - um assunto por pull request, mexendo só na seção desse assunto — rotas na Etapa 6, telas na Etapa 7, pendências novas no fim da lista da Etapa 8;
  - marcar o que está "especificado" e o que está "implementado", como já é feito;
  - na descrição do PR, dizer o que muda para o outro lado (API ou app);
  - quem decide e mescla é o Allan.
- **Mudança de rota ou campo que o app já usa** precisa avisar isso no PR: o app lê esta especificação no começo de cada sessão e pode estar implementando em cima do texto antigo.

## Registro de decisões técnicas

Toda decisão de arquitetura relevante (troca de biblioteca, mudança no modelo de dados, escolha de modelo de IA, etc.) deve ser registrada na tabela "Decisões Técnicas e Justificativas" (Etapa 5) de `ESPECIFICACAO.md`, com o motivo da escolha e alternativas descartadas.
