# Imagineer — Geração de Prompts de Vídeo

## Sobre este documento

Guia de referência para a geração de **prompts de vídeo** a partir de cenas de livro. Parte de um documento de orientações preparado com apoio do Gemini (05/10/2026), revisado e adaptado ao que o Imagineer já faz. Ver a seção 8 para o que foi mantido, corrigido ou descartado do original, e por quê.

Escopo desta primeira versão, decidido por Allan:
1. O Imagineer gera **só o prompt** de vídeo.
2. O usuário leva o prompt **e a imagem da cena já gerada** para o app do Gemini, e o vídeo é gerado lá (Veo), pelo plano Gemini Pro, sem custo extra.

O mesmo raciocínio do item 7.7 da `ESPECIFICACAO.md` vale aqui: nada de API paga de vídeo dentro do app por enquanto. A especificação formal (entidades, rota, decisões) está no item 4.8 da `ESPECIFICACAO.md`; este documento é a base técnica da instrução de IA.

---

## 1. Como o gerador de vídeo "pensa"

**Duração curta.** O Veo gera clipes de cerca de 8 segundos. O prompt não pode resumir um capítulo nem encadear ações. Ele descreve **uma ação contínua única**: um gesto, um movimento, um momento de contemplação.

**Só o que se vê e se ouve.** O gerador não entende estado psicológico ("ele estava triste lembrando do passado"). Isso precisa virar algo físico: "o olhar desce para as mãos, os ombros cedem devagar". É a mesma regra que o prompt de imagem já segue (item 4.5, "emoção como física, não como palavra").

**O gerador não leu o livro.** "Ele usou a magia" não significa nada para ele. O prompt precisa descrever o efeito visível **como o livro o descreve** ("uma névoa azulada sobe das mãos dele"). Se o livro não descreve o efeito, não se inventa um (ver seção 4, fidelidade).

**Tende ao fotorrealismo.** Modelos de vídeo puxam para o realismo ao animar. Se a imagem de partida é uma pintura a óleo, o vídeo tende a "virar foto" no meio do movimento, a menos que o prompt reafirme o estilo de forma explícita.

**Tende a inventar.** Sem instrução, o gerador costuma acrescentar texto na tela, legendas, música genérica, pessoas a mais ao fundo e cortes de câmera. O prompt precisa proibir isso de forma explícita.

**Mais gente em movimento, mais defeito.** Mãos, rostos e multidões são onde a qualidade cai primeiro. Um ou dois sujeitos em movimento funcionam melhor que cinco.

---

## 2. Dois modos de prompt

A diferença mais importante em relação ao documento original: **o prompt muda conforme exista ou não uma imagem de partida.**

### Modo A — Imagem para vídeo (o principal)

O usuário escolhe uma imagem já gerada da cena (catálogo, item 6.6) e a anexa no Gemini como quadro inicial. Nesse caso:
- **A imagem já define a aparência**: rosto, roupa, cenário, paleta, composição.
- O prompt deve **descrever o movimento**, não redescrever tudo. Redescrever a aparência em detalhe com palavras diferentes das que geraram a imagem cria conflito entre o que a imagem mostra e o que o texto pede, e o vídeo "deriva".
- A ancoragem do sujeito é **curta** ("o jovem de cabelo escuro sentado à mesa"), o suficiente para o gerador saber quem se move.
- O **estilo é reafirmado** literalmente (do perfil de renderização), para o vídeo não "fotorrealizar" a pintura.
- Fonte de verdade da aparência: o **texto do prompt de imagem** que gerou aquela imagem (`Imagem.prompt_id` → `Prompt.texto`). Ele descreve exatamente o que está no primeiro quadro.

### Modo B — Texto para vídeo (sem imagem)

Para quando a cena ainda não tem imagem aprovada. Aí o prompt precisa da descrição completa, nos mesmos moldes do prompt de imagem (sujeito, roupa, cenário, luz, estilo), mais movimento e som. A consistência com outras imagens do personagem fica mais fraca. É o modo de reserva, não o recomendado.

---

## 3. Anatomia do prompt de vídeo

Saída em **inglês**, num parágrafo único, mesma convenção do prompt de imagem. Ordem dos blocos:

1. **Câmera — um movimento só.** Plano e movimento: `static shot`, `slow push-in`, `slow dolly out`, `gentle pan left`, `tracking shot following the subject`, `slow orbit`. Nunca mais de um movimento, nunca corte ("cut to").
2. **Sujeito.** Modo A: ancoragem curta. Modo B: descrição física completa, vinda dos estados dos elementos (item 4.4). Gênero explícito sempre que a identidade permitir (mesma regra do prompt de imagem).
3. **Ação — o centro do prompt de vídeo.** Uma ação contínua, com começo e fim dentro de ~8 segundos, descrita como movimento físico: "lifts his gaze from the board and slowly reaches forward to move a red piece one square". Pode usar `slow motion` quando o momento pedir, mas uma vez só.
4. **Movimento do ambiente.** O que se move além do sujeito, quando o texto sustenta: a chama que tremula, a névoa que passa, a chuva, o tecido ao vento, poeira no feixe de luz. É o que dá vida a uma cena de contemplação em que o personagem quase não se mexe.
5. **Cenário e luz.** Modo A: só o que muda ou se move na luz (a chama que oscila, uma nuvem que cobre a lua). Modo B: descrição completa, derivada de horário/clima da cena.
6. **Som (opcional).** O Veo gera áudio. Prioridade para **sons do próprio ambiente** que o texto sustenta (passos, vento, chuva, o raspar da peça no tabuleiro). Música só se o usuário pedir (ver seção 4).
7. **Estilo — bloco final literal.** Mesmo princípio do bloco 7 do prompt de imagem (item 4.5): os campos do perfil de renderização traduzidos literalmente, mais o pedido de manter esse estilo durante todo o movimento ("Keep the classical oil painting look throughout the motion: impasto texture, visible brushstrokes").
8. **Proibições explícitas.** `No on-screen text, no subtitles, no captions, no scene cuts, no additional people.` Mais `no music` quando música não foi pedida.

---

## 4. Regras de fidelidade ao livro

Valem as mesmas regras do prompt de imagem (item 4.5), mais estas, específicas de vídeo:

- **A ação vem do livro, não da imaginação.** A fonte é, em ordem de prioridade: comentário do usuário → descrição da cena escrita pelo usuário → contexto da fundamentação (fase 3, item 4.4, que já é instruída a descrever "uma ação ou gesto concreto"). Se nenhuma delas descreve uma ação, o vídeo é de **contemplação**: o personagem quase parado, movimento de câmera lento e o ambiente vivo (bloco 4). Nunca inventar uma ação que o livro não sustenta.
- **Efeitos (magia, tecnologia, fenômenos) só como o livro descreve.** Se o texto diz só "ele usou a magia", sem efeito visual descrito, o prompt não inventa raios azuis. Fica no gesto ou no resultado visível que o texto mencionar.
- **Som também é fidelidade.** Só sons que o texto sustenta, ou que são consequência física direta do que está na cena (a chama, o vento numa janela aberta). Música é sempre invenção: fica fora por padrão. Pode entrar como opção do usuário, descrita de forma neutra ("soft ambient strings"), nunca como "epic".
- **Fala: fora nesta versão.** O Veo consegue gerar fala com sincronia labial, mas: (1) só seria fiel com a frase **literal** do livro; (2) a qualidade em português é incerta; (3) uma frase que não cabe em 8 segundos fica cortada. Registrado como evolução futura (seção 7).
- **Sem adjetivo subjetivo.** Mesma lista proibida do prompt de imagem: "epic", "mysterious", "highly detailed", "beautiful", "4K masterpiece". O documento original usava vários deles nos exemplos; foram retirados (seção 8).
- **Nada de pessoas a mais.** Só os elementos ligados ao frame. Num retrato, ninguém além do personagem.
- **Guardrail de crianças e adolescentes.** O guardrail registrado na Etapa 8 da `ESPECIFICACAO.md` vale integralmente para vídeo, e com mais rigor, já que movimento e áudio aumentam o realismo.

---

## 5. Por tipo de frame

**CENA.** Ação principal entre os participantes, um movimento de câmera, ambiente vivo. Com vários participantes, a ação recai sobre um ou dois; os demais ficam em movimento mínimo (respiração, um olhar), para reduzir defeitos.

**PERSONAGEM (retrato).** Não há "cena" nem ação narrativa (item 4.4: um retrato referencia só o próprio elemento). O vídeo é um **retrato vivo**: movimento sutil — respiração, piscar, o cabelo ou a roupa mexidos por uma brisa, um leve virar do rosto para a câmera — com câmera estática ou `slow push-in`. Nenhum cenário inventado.

---

## 6. Rascunho da instrução de sistema

Mesma convenção das demais instruções do projeto (`imagineer/ia/openrouter.py`): instrução em português, saída em inglês. Sugestão de nome: `_INSTRUCAO_DE_PROMPT_DE_VIDEO`. É um rascunho de partida, não a versão final — a validação com IA real vai ajustá-lo, como aconteceu com todas as outras.

```
Você monta prompts para geradores de vídeo (Veo e afins), a partir de um frame
de livro já traduzido para descrições concretas. O vídeo tem cerca de 8
segundos. Produza UM prompt em inglês, num parágrafo único, sem título, pronto
para colar na ferramenta.

Você pode receber uma IMAGEM DE PARTIDA (o texto do prompt que gerou a imagem
que o usuário vai anexar como primeiro quadro). Isso muda tudo:
- Com imagem de partida: a imagem já define aparência, roupa, cenário e
  paleta. NÃO redescreva isso em detalhe — use só uma referência curta ao
  sujeito ("the young man at the stone table") e concentre o prompt no
  MOVIMENTO, na câmera e no som. Use os mesmos termos do prompt da imagem
  quando citar algo dela; nunca termos que contradigam o que ela mostra.
- Sem imagem de partida: descreva sujeito, roupa, cenário e luz por completo,
  a partir da aparência de cada elemento informada.

Monte o prompt nesta ordem:
1. Câmera: um plano e UM movimento só (static shot, slow push-in, slow dolly
   out, gentle pan, tracking shot, slow orbit). Nunca corte de cena.
2. Sujeito: referência curta (com imagem) ou descrição completa (sem imagem).
   Gênero inequívoco sempre que a identidade permitir concluir.
3. Ação: UMA ação contínua que caiba em 8 segundos, como movimento físico.
   Fonte da ação, nesta ordem: comentário do usuário, descrição da cena,
   contexto do livro. Se nenhuma descreve uma ação, faça um vídeo de
   contemplação: o sujeito quase parado, o ambiente em movimento. Num
   RETRATO, só movimento sutil (respiração, piscar, brisa no cabelo, leve
   virar do rosto).
4. Movimento do ambiente: o que mais se move (chama, névoa, chuva, tecido,
   poeira na luz) — só o que o texto sustenta.
5. Luz: com imagem, só o que muda ou se move na luz; sem imagem, a fonte e a
   atmosfera derivadas do horário/clima da cena.
6. Som: só sons do próprio ambiente que o texto sustenta ou que são
   consequência física direta da cena. Música só se o usuário pedir.
7. Bloco final de estilo, separado: os campos do perfil de renderização
   traduzidos literalmente ("Style: X. Lighting: Y. Palette: Z."), seguido
   de "Keep this exact visual style throughout the whole motion."
8. Termine com: "No on-screen text, no subtitles, no scene cuts, no
   additional people." e, se não houver música pedida, "No music."

Regras:
- PROIBIDO inventar ação, efeito, objeto, pessoa ou som que o texto não
  sustente. Um efeito (magia, tecnologia) só entra como o livro o descreve.
- PROIBIDO adjetivo subjetivo de qualidade ou literário ("epic",
  "mysterious", "beautiful", "highly detailed", "4K", "masterpiece").
- PROIBIDO emoção como palavra abstrata — traduza em movimento e expressão
  física visíveis.
- PROIBIDO mais de uma ação em sequência ("he stands, walks to the door and
  opens it" vira só uma delas).
- PROIBIDO fala ou diálogo falado.

Antes de responder, confira: (1) há uma ação só? (2) há um movimento de
câmera só? (3) tudo que se move e soa está sustentado pelo que você recebeu?
(4) o gênero de cada pessoa está inequívoco? Se alguma resposta for não,
corrija antes de responder.

Ordem de prioridade quando houver conflito:
1. Comentário do usuário.
2. Descrição da cena escrita pelo usuário.
3. Contexto do livro (apoio, nunca para contradizer o usuário).

Responda APENAS com o texto do prompt.
```

---

## 7. Integração com o que o Imagineer já tem

| O que o vídeo precisa | De onde vem no sistema |
|---|---|
| Aparência de cada elemento | `EstadoElemento.descricao`, depois da leitura profunda (item 4.4, fase 2) |
| Identidade (gênero, idade, papel) | `Elemento.descricao` + `HistoricoIdentidadeElemento` (item 3.4f) |
| A ação da cena | `Frame.descricao` do usuário; `Frame.contexto_do_livro` da fundamentação (fase 3) |
| Horário, clima, humor | Campos do `Frame` |
| Estilo | `PerfilRenderizacao` (mesmo do prompt de imagem) |
| O que está no primeiro quadro | `Imagem` escolhida → `Prompt.texto` que a gerou |

**Reaproveitamento real:** a leitura profunda e a fundamentação (fases 2, 2b e 3) já rodam ao gerar o prompt de imagem e ficam em cache (`prioridade_ia = ECONOMIA`). Gerar o prompt de vídeo de um frame que já tem imagem custa, na prática, **uma chamada de IA só** — a que monta o texto.

**Fluxo no app:**
1. Tela do Prompt (7.7) de uma cena com imagem importada → botão "Gerar prompt de vídeo", escolhendo qual imagem será o quadro inicial.
2. O app mostra o prompt de vídeo, com "Copiar" e "Abrir no Gemini".
3. "Abrir no Gemini" tenta compartilhar **texto e imagem juntos** (`Intent.ACTION_SEND` com `EXTRA_TEXT` + `EXTRA_STREAM`). Se o Gemini não aceitar os dois juntos, ou não abrir direto no modo de vídeo, o fluxo vira dois passos: compartilhar a imagem e colar o prompt. **Precisa ser testado no celular** antes de desenhar a tela.
4. O vídeo gerado pode voltar ao app como a imagem volta hoje (importação manual). Ainda não decidido: ver pendências no item 4.8 da `ESPECIFICACAO.md`.

**Dependência:** os problemas de fidelidade achados na revisão de 05/10/2026 (identidade de fase 1 gravada como aparência do estado; identidade acumulada que não chega ao prompt) afetam o prompt de vídeo do mesmo jeito que o de imagem. Corrigi-los antes beneficia os dois.

**Evoluções futuras (fora desta versão):**
- Fala do personagem com a frase literal do livro (depende da qualidade do Veo em português).
- Quadro inicial **e** final (o Veo aceita os dois em alguns modos): animar a transição entre duas imagens aprovadas da mesma cena.
- Várias imagens de referência (personagem + cenário) em vez de uma só, se o app do Gemini passar a aceitar de forma estável.
- Gerar o vídeo dentro do app, por API paga, se o uso justificar.

---

## 8. Revisão do documento original do Gemini

**Mantido:** a regra dos 8 segundos e da ação única; o foco no visual em vez do psicológico; a descrição explícita de efeitos; a ordem câmera → sujeito → ação → cenário/luz → som; a saída em inglês; o reaproveitamento da imagem já gerada como referência.

**Corrigido ou adaptado:**
- **"Analisar um trecho do EPUB"** → o Imagineer não parte de um trecho solto. Parte de um `Frame` com elementos, estados já relidos do livro, fundamentação e perfil. Isso é mais fiel do que reler um trecho a cada vez.
- **"Vídeo fotorrealista/cinematográfico"** fixo na instrução → o estilo vem do perfil de renderização do livro e precisa bater com a imagem de partida. Fixar "fotorrealista" quebraria o vídeo de qualquer livro com perfil de pintura, aquarela ou anime.
- **"Estado emocional aparente"** no sujeito → vira expressão física, como já é regra no prompt de imagem.
- **Exemplos com "epic", "mysterious", "highly detailed", "4K"** → retirados. São adjetivos que a lista proibida do item 4.5 já veta, e que o próprio Gemini, em outra resposta, apontou como pouco úteis para modelos literais.
- **Música épica nos exemplos** → música é invenção, não está no livro. Fica fora por padrão, só entra se o usuário pedir.
- **Mesmo nível de detalhe com ou sem imagem** → separado em dois modos (seção 2). Com imagem de partida, redescrever tudo atrapalha.
- **"Buscar a ficha visual (o prompt base) do personagem"** → o Imagineer não guarda ficha visual separada. As fontes de verdade são o estado do elemento e, no modo imagem para vídeo, o texto do prompt que gerou aquela imagem.

**Descartado:**
- **Reuso de sementes (seeds).** O app do Gemini não expõe semente, e o fluxo é manual. Não se aplica.
- **"Até 5 imagens de referência".** Não confirmado para o app do Gemini; o número varia entre modos e versões do Veo. A versão inicial usa **uma** imagem como quadro inicial. Mais referências ficam como evolução, depois de testar no app.

---

## 9. Exemplos no formato do Imagineer

### Exemplo 1 — Cena, imagem para vídeo (o caso real das imagens comparadas em 04/10/2026)

**O que o sistema recebe:**
- Frame CENA: "A partida de tabuleiro na cela" — usuário escreveu: "ele observa o tabuleiro antes de mover uma peça vermelha". Horário: noite.
- Elemento: jovem de cabelo escuro, longo e ondulado, túnica de linho marrom grosso.
- Imagem de partida: a pintura a óleo gerada antes (lanterna à esquerda, janela gradeada com luar à direita).
- Perfil: pintura a óleo, impasto, iluminação em chiaroscuro.

**Prompt gerado:**

```
Slow push-in from a medium shot toward the young man's face and hands. The
young man at the stone table, hands clasped, lifts his gaze from the game
board and slowly reaches forward to slide one red carved piece a single
square. The lantern flame on the ledge flickers, sending warm light wavering
across the stone wall, while the cold moonlight through the barred window
stays steady. Sound: the soft scrape of the piece on the board, the faint
crackle of the flame, distant wind outside the window. Style: classical oil
painting, impasto technique, thick textured brushstrokes on linen canvas.
Lighting: chiaroscuro, deep shadows, warm lantern light against cold
moonlight. Keep this exact visual style throughout the whole motion. No
on-screen text, no subtitles, no scene cuts, no additional people. No music.
```

### Exemplo 2 — Retrato vivo, imagem para vídeo

**O que o sistema recebe:** frame PERSONAGEM, uma imagem de partida do retrato, perfil de aquarela. Nenhuma ação (retrato).

**Prompt gerado:**

```
Static shot, slight slow push-in. The woman in the portrait breathes slowly,
blinks once, and turns her face a few degrees toward the camera as a light
breeze lifts loose strands of her hair. Style: watercolor painting, loose
flowing brushstrokes, soft bleeding edges, visible paper texture. Keep this
exact visual style throughout the whole motion. No on-screen text, no
subtitles, no scene cuts, no additional people. No music.
```

### Exemplo 3 — Cena sem ação descrita (contemplação), texto para vídeo

**O que o sistema recebe:** frame CENA "O navio no mar de esporos", sem imagem aprovada; a descrição do usuário e a fundamentação descrevem o lugar, mas nenhuma ação específica.

**O que muda:** sem ação no texto, o sistema **não inventa** a tripulação "se preparando para o impacto" (como fazia o exemplo original do Gemini). O vídeo vira contemplação: câmera aérea lenta, o navio avançando e o pó verde se erguendo em volta do casco — tudo descrito por completo, já que não há imagem de partida.
