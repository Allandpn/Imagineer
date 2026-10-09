"""Implementação de ``ProvedorIA`` sobre o OpenRouter (item 4.1).

O OpenRouter é um gateway único para muitos modelos, inclusive gratuitos, com uma
API compatível com a da OpenAI. Foi escolhido para não precisar de um adaptador
por fornecedor na v1 (Etapa 5).
"""

import base64
import binascii
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

import httpx

from imagineer.ia import esquemas_json
from imagineer.ia.catalogo_de_texto import (
    Capacidades,
    capacidades_de,
    decimal_ou_nulo as _decimal_ou_nulo,
    e_rapido,
    ler_catalogo,
    obter_capacidades,
)
from imagineer.ia.fornecedores_de_imagem import (
    NOMES_DOS_FORNECEDORES,
    VARIAVEIS_DA_CHAVE,
    GeradorDeImagemExterno,
    separar_fornecedor,
)
from imagineer.ia.provedor import (
    AudioNarrado,
    ModeloDeImagemDisponivel,
    ModeloDeVoz,
    ReferenciasParaGerar,
    CenaSugerida,
    ChaveDeApiAusente,
    ConteudoRecusado,
    ElementoSugerido,
    ErroDoProvedorIA,
    EstadoSugerido,
    ExtracaoDeElementos,
    FrameFundamentado,
    IdentidadeSugerida,
    ImagemGerada,
    ModeloDisponivel,
    ModeloNaoEscolhido,
    ParticipanteSugerido,
    PerfilRenderizacaoSugerido,
    PromptMontado,
    ProvedorIA,
    TextoLongoDemais,
    UsoDaChamada,
)
from imagineer.ia.tarefas import (  # noqa: F401 - as temperaturas são usadas aqui e importadas daqui por quem já as importava
    ORDEM_DOS_ESFORCOS,
    TEMPERATURA_DA_CORRECAO,
    TEMPERATURA_DA_SUAVIZACAO,
    TEMPERATURA_DA_TRADUCAO,
    TEMPERATURA_DE_FIDELIDADE,
    TEMPERATURA_DO_PROMPT,
    NivelDeRaciocinio,
    PerfilDaTarefa,
    perfil_da,
)
from imagineer.modelos import CategoriaEstilo, TipoElemento

ENDERECO_BASE = "https://openrouter.ai/api/v1"

CARACTERES_POR_TOKEN = 4
"""Estimativa grosseira de quantos caracteres cabem num token, em português.

Serve para dimensionar antes de chamar, não para cobrar. Errar por 20% aqui não
muda a decisão de "cabe" ou "não cabe", porque a folga é bem maior que isso.
"""

FOLGA_DE_TOKENS = 2000
"""Tokens reservados para a instrução e para a resposta do modelo.

O texto do capítulo não é a única coisa que ocupa contexto: a instrução, os
estados conhecidos e a resposta também. Reservar essa folga é o que evita passar
do limite por pouco.
"""

TEMPO_LIMITE = 180.0
"""Segundos de espera por uma resposta.

Generoso de propósito: modelos gratuitos ficam em fila, e um capítulo de 25 mil
tokens leva tempo. Um limite curto transformaria lentidão em erro.
"""

ROTULO_DA_APARENCIA_FIXA = "Aparência fixa:"
ROTULO_DO_INSTANTE = "Neste instante:"
ROTULO_DO_AMBIENTE = "Onde está:"
"""Os rótulos das três partes do estado de um elemento (A1).

O estado continua sendo **um texto só** (o app mostra e o usuário edita como sempre); os rótulos em português
é que deixam o gerador de prompt saber qual parte é qual, sem coluna nova no banco.
"""

_INSTRUCAO_DE_EXTRACAO = """\
Você analisa um capítulo de livro e identifica os elementos visuais que aparecem \
nele, para que alguém possa depois gerar imagens das cenas. Nesta etapa você só \
IDENTIFICA — não descreva a aparência de ninguém ainda. Além dos elementos, você \
também sugere CENAS: recortes narrativos específicos, combinando elementos que \
interagem num mesmo momento — é isso que alguém efetivamente ilustraria, não uma \
lista solta de "quem existe no capítulo".

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "elementos": [
    {
      "tipo": "PERSONAGEM",
      "nome": "como o elemento é chamado no texto",
      "descricao": "quem ou o que é: papel na história, natureza, função"
    }
  ],
  "cenas": [
    {
      "titulo": "título curto do momento, como 'A chegada de Hospius'",
      "descricao": "o que acontece nesse momento específico, em 1-2 frases",
      "horario": "período do dia, se o texto sugerir, senão nulo",
      "clima": "condição do ambiente, se o texto sugerir, senão nulo",
      "humor": "tom emocional da cena, se ficar claro, senão nulo",
      "trecho_ancora": "citação literal do começo desse momento, copiada do texto",
      "trecho": "citação literal de 1 a 3 frases que narram esse momento, copiada do texto",
      "participantes": [
        {"tipo": "PERSONAGEM", "nome": "nome exatamente como em elementos"}
      ]
    }
  ]
}

## Os tipos de elemento, e como não confundi-los

- **PERSONAGEM**: um ser humano ou humanoide com identidade própria (nome, \
papel na história) — inclui pessoas comuns, nobres, funcionários, qualquer \
gente do enredo.
- **CRIATURA**: um ser vivo não-humanoide com presença própria na cena (animal, \
monstro, criatura fantástica). Para os fins de sugerir cenas, PERSONAGEM e \
CRIATURA contam igualmente como "alguém" que pode protagonizar um momento.
- **AMBIENTE**: um espaço ou lugar amplo (uma floresta, uma rua, um cômodo) — \
o "onde" da cena, não um item dentro dele.
- **EDIFICACAO**: uma construção específica e nomeável, quando o foco é a \
estrutura em si (um castelo, uma torre, uma prisão inteira) — diferente de \
AMBIENTE, que é o espaço genérico onde a ação acontece.
- **OBJETO**: um item físico específico, portátil ou fixo — arma, livro, \
móvel, tabuleiro de jogo, porta, moeda, dispositivo. Portas, tabuleiros e \
lanternas são OBJETO, nunca AMBIENTE nem VEICULO.
- **VEICULO**: algo cuja função é **transportar** pessoas ou carga de um lugar \
a outro (carruagem, navio, montaria usada para viajar). Nunca uma porta, um \
móvel ou qualquer objeto fixo no lugar — isso é OBJETO.
- **GRUPO**: um coletivo mencionado sem que seus integrantes sejam \
individualizados ("os guardas", "a multidão").

## Regras

- Inclua apenas o que tem presença visual no capítulo. Ignore conceitos abstratos.
- "descricao" é a identidade do elemento (quem ou o que é), não a aparência dele \
neste capítulo — a aparência é analisada depois, um elemento por vez.
- Se um elemento da lista de elementos já cadastrados aparece no capítulo, use \
exatamente o nome que está na lista, e não um apelido ou variação. Em "descricao", \
diga só quem ou o que ele é (a identidade), sem copiar a descrição da lista nem \
descrever a aparência neste capítulo.
- **Objetos: seja seletivo.** Só inclua um objeto se ele tem peso visual \
memorável na cena — algo que o leitor lembraria de ver, um símbolo, algo \
central para uma ação marcante (a moeda entregue como pagamento, o tabuleiro \
em que a partida acontece). NÃO inclua cenário genérico de fundo (papelada, \
móveis comuns, ferramentas do dia a dia) a menos que a cena realmente gire em \
torno do objeto.
- **Cenas: pense em composição, não em lista.** Cada cena deve ter pelo menos \
um PERSONAGEM ou CRIATURA envolvido interagindo com outro elemento (outro \
personagem, um objeto, ou estar situado num ambiente/edificação) — não sugira \
uma "cena" que é só um ambiente vazio ou um objeto sozinho. Prefira poucas \
cenas bem compostas (os momentos que um leitor lembraria) a listar cada \
parágrafo do capítulo como uma cena.
- "trecho_ancora" de cada cena: copie, **palavra por palavra e sem alterar nada**, \
uma frase curta (até 200 caracteres) do texto do capítulo, no ponto em que o momento \
da cena COMEÇA. Não resuma, não traduza, não corrija pontuação. Se não tiver certeza \
de achar um trecho exato, use null.
- "trecho" de cada cena: copie, **palavra por palavra e sem alterar nada**, de 1 a 3 frases \
seguidas do capítulo (até 500 caracteres) que NARRAM o momento da cena — a ação, o lugar e o que \
se vê, nas palavras do autor. Pode começar onde "trecho_ancora" começa. Não resuma, não traduza, \
não una frases de lugares diferentes do texto. Se não tiver certeza de achar um trecho exato, use \
null: um trecho que não esteja no capítulo é descartado.
- Se o pedido trouxer uma "ORIENTAÇÃO DO USUÁRIO", procure com atenção o que ela \
descreve (um elemento, uma cena) e inclua se estiver no texto. A orientação é um \
PALPITE do usuário, não um fato: se o que ele descreve NÃO aparece neste capítulo, \
não invente — ignore. Todo o resto das regras vale igual.
- Todo nome em "participantes" deve corresponder exatamente a um nome que \
também está em "elementos".
- Escreva em português.
"""

_INSTRUCAO_DE_ESTADO = """\
Você lê um capítulo de livro inteiro, mas quer descrever a aparência de UM SÓ \
elemento — ignore todos os outros, mesmo que apareçam no texto.

O texto que você escrever vira, mais tarde, a matéria-prima de um prompt de \
imagem. Modelos de imagem não entendem metáfora literária ("olhar frio como o \
gelo", "silêncio ensurdecedor") — eles precisam de dado físico e sensorial \
concreto. Por isso, ao traduzir o que o texto sugere, prefira sempre o que se vê:

- Materialidade e textura: do que é feita a roupa, o objeto, a superfície \
(linho puído, couro rachado, seda ao luar) — não só "roupas simples" ou \
"roupas ricas".
- Estado físico e expressão como algo visível: idade aparente, porte, \
ferimentos, e a expressão como músculo e postura (sobrancelhas franzidas, \
ombros caídos), não como sentimento abstrato ("ele estava triste" vira "olhar \
baixo, ombros curvados").
- Um instante congelado, não uma ação contínua: descreva UMA pose ou gesto \
específico do capítulo, como se fosse um fotograma parado — não "ele entra, \
pega o livro e sai", mas o momento em que a mão toca a página.

Você devolve TRÊS partes, porque cada uma tem um papel diferente na imagem:

1. "aparencia_fixa": os traços que NÃO mudam ao longo do livro — idade aparente, porte, \
pele, rosto, cor, comprimento e tipo do cabelo, marcas permanentes. Pode vir de QUALQUER \
ponto do capítulo (e do estado já registrado), não só do primeiro instante. Nunca roupa, \
pose, humor, nem como o cabelo está (NÃO escreva "preso", "solto", "rabo de cavalo", \
"trança": isso muda e vai no instante; aqui só cor, comprimento e tipo). Sem isso a imagem \
perde a identidade da pessoa, então inclua tudo que o texto disser, e não comente o que o \
texto NÃO diz (nada de "altura não informada"). Para um lugar ou um objeto: forma, tamanho \
e materiais.

2. "instante": UM SÓ INSTANTE, o PRIMEIRO em que o elemento aparece no capítulo. Se o \
elemento muda de roupa, de pose ou de estado ao longo do capítulo (por exemplo, aparece de \
camisola e depois sem roupa), descreva a roupa, a pose, a expressão e o humor do PRIMEIRO \
instante, sem misturar com os seguintes. É um fotograma parado, não uma linha do tempo: \
nada de "depois", "mais tarde", "em seguida", "finalmente".

Expressão e postura NUNCA ficam de fora do instante: toda descrição de pessoa ou criatura \
inclui a expressão do rosto (sorriso, olhar, tensão) e a postura ou o gesto, sempre que o \
texto os sustenta, e também o humor que se vê (animada, nervosa, cansada), traduzido em \
músculo e postura. Uma descrição só com cabelo, pele e roupa é pobre demais para virar \
imagem: ela perde a emoção da cena.

3. "ambiente": ONDE o elemento está nesse mesmo instante, para a imagem ter imersão — um \
sujeito em primeiro plano com um fundo qualquer quebra a imagem. Descreva o lugar e o que \
se vê ao redor e atrás dele: materiais, tamanho, objetos próximos, e a luz e o que há no ar \
(uma vela, o sol por uma fresta, poeira) quando o texto sustenta. Escreva só o que APARECERIA \
NO QUADRO: o lugar e uns 4 a 6 detalhes visuais marcantes, não um inventário (nada de contar \
saídas, portas ou o que está fora de vista). Nomes inventados pelo livro (de lugares, criaturas, \
objetos) não dizem nada a quem vai desenhar: escreva sempre o que SE VÊ ("um filhote de luz azul \
num prato"), e o nome só junto disso. Só o que o texto diz ou \
implica com segurança: se ele não diz onde o elemento está, devolva null em vez de inventar \
um cenário. Para um elemento que é o próprio lugar (AMBIENTE, EDIFICACAO), devolva null.

Regras de fidelidade ao texto (mais importantes que o estilo de escrita acima):
- Descreva só o que o texto diz ou implica com segurança. Não invente detalhes \
que o texto não sustenta, mesmo que pareçam plausíveis para o gênero da obra.
- Não confunda com outro elemento — releia com cuidado a quem cada detalhe \
pertence antes de escrever. Um detalhe de outro personagem nunca deve aparecer \
na descrição deste.
- Separe o que é identidade (rosto, cor e tipo de cabelo, altura, compleição — \
tende a não mudar de capítulo para capítulo) do que é situacional (roupas, \
ferimentos, sujeira, humor — muda com a cena). Preserve a identidade já \
registrada a menos que o texto diga explicitamente que ela mudou (idade que \
avança, um ferimento permanente); atualize a parte situacional com o que este \
capítulo mostra.
- O pedido pode trazer "APARÊNCIA ESTABELECIDA ATÉ AQUI": os traços fixos que este \
elemento já tinha em capítulos anteriores. Use-os para completar na "aparencia_fixa" o \
que ESTE capítulo não repete (a cor do cabelo dita no primeiro capítulo continua valendo), \
mas o texto deste capítulo vence se disser que algo mudou. Dela, nunca copie roupa, pose \
ou humor.
- Se o elemento pedido não aparecer de forma clara neste capítulo, ou se o \
texto não descrever sua aparência, devolva o estado já registrado (nas três \
partes acima), sem inventar nada novo e sem deduzir a partir do gênero ou tom do \
livro.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "aparencia_fixa": "os traços que não mudam, seguindo as regras acima",
  "instante": "o primeiro instante: roupa, pose, expressão e humor",
  "ambiente": "onde está nesse instante, ou null se o texto não diz"
}

Escreva em português.
"""

_INSTRUCAO_DE_IDENTIDADE = """\
Você lê um capítulo de livro inteiro, mas quer descobrir se ele revela algo \
NOVO sobre a IDENTIDADE de UM SÓ elemento — quem ele é: papel na história, \
origem, relações, segredos, traços de caráter. Isto NÃO é aparência física \
(cor de cabelo, roupas, ferimentos) — isso é outra etapa. É sobre quem ou o \
que o elemento É.

Você recebe a identidade já conhecida dele, se houver. Sua tarefa é achar só \
o que é GENUINAMENTE NOVO neste capítulo:
- Nunca repita o que já está na identidade conhecida.
- Nunca contradiga nem substitua o que já é conhecido — identidade só \
acumula, não se apaga.
- Se o capítulo não revela nada novo sobre quem este elemento é, isso é o \
caso mais comum, não uma falha: responda com "descricao": null em vez de \
forçar uma novidade que não existe.
- Descreva só o que o texto diz ou implica com segurança. Não invente.
- Escreva só o INCREMENTO em si — uma ou duas frases do que é novo, não um \
resumo de tudo que já se sabe sobre o elemento.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "descricao": "o que este capítulo especificamente revela de novo sobre a identidade, ou null se nada"
}

Escreva em português.
"""

_INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME = """\
Você lê um capítulo de livro para conferir uma cena que o usuário já descreveu \
com as próprias palavras — você é uma segunda opinião, não a palavra final.

Você recebe como o usuário descreveu a cena (título, descrição, horário, clima, \
humor) e quem participa dela, cada um já com a aparência estabelecida. Pode vir também \
o "TRECHO DO LIVRO EM QUE A CENA ACONTECE": as palavras do autor nesse momento. Se vier, \
é ali que a cena está: foque nele (e no que o cerca, para o contexto) e ignore outras \
passagens do capítulo com os mesmos personagens. Releia o capítulo e escreva um parágrafo curto (até 3 frases) confirmando, com base só \
no texto:
- Onde a cena acontece: o ambiente ou construção, com detalhes físicos que o \
texto sustente.
- O que fisicamente acontece nesse momento específico: uma ação ou gesto \
concreto, não uma sequência de eventos.
- Qualquer detalhe visual do ambiente (iluminação, clima, objetos presentes) \
que o texto mostre e a descrição do usuário não tenha coberto.

Regras:
- Você NÃO substitui a descrição do usuário. Se o que você lê parecer \
contradizer o que ele escreveu, não corrija — apenas registre o que o texto \
mostra; quem monta o prompt final decide, e a palavra do usuário vale mais que \
a sua (ele já leu o capítulo; você pode estar enganado ou lendo o trecho errado).
- Não invente. Se o capítulo não deixar algo claro, diga que não é claro em vez \
de supor.
- Não repita a aparência física dos participantes — isso já foi estabelecido \
em outra etapa. Foque em local, ação e ambiente.
- Escreva em português.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{
  "contexto": "o parágrafo de confirmação, seguindo as regras acima"
}
"""

_INSTRUCAO_DE_PROMPT = """\
Você monta prompts para ferramentas de geração de imagem (Midjourney, DALL-E, \
Imagen e afins), a partir de um frame de livro já traduzido para descrições \
concretas de aparência. Um frame pode ser um RETRATO (um elemento só, sem \
nenhum outro) ou uma CENA (vários elementos interagindo) — a diferença fica \
clara pelo que foi preenchido abaixo. Produza UM prompt em inglês, num texto \
corrido só (sem título, sem numerar os blocos), pronto para colar na \
ferramenta — o bloco final de estética (ver abaixo) é estruturado, mas ainda \
faz parte do mesmo texto único, não uma resposta separada.

Se não vier nenhuma descrição de cena (só um elemento na lista), monte um \
RETRATO: use exclusivamente a descrição desse elemento e o estilo pedido — não \
mencione, sugira ou implique a presença de mais ninguém. Um retrato NÃO é um sujeito \
solto num fundo qualquer: ele acontece no lugar onde o elemento está (veja abaixo).

**Num retrato a pose é SEMPRE neutra.** O retrato é a imagem de referência do personagem para \
todas as cenas, e uma pose ou expressão marcante contaminaria as cenas. Por isso o sujeito fica de pé, \
com o corpo relaxado, os braços soltos ao lado do corpo, olhando para a câmera, com expressão \
neutra ("standing in a neutral relaxed pose, arms at sides, facing the camera, neutral expression"). \
SEM gesto, ação, emoção marcada nem objeto na mão, mesmo que o "Neste instante:" descreva um \
(dele use só a roupa e o penteado). Só o comentário do usuário pode pedir outra pose.

Se vierem **ELEMENTOS VINCULADOS AO SUJEITO**, o retrato continua sendo do **sujeito \
principal** (o primeiro da lista de elementos), mas os vinculados **aparecem junto dele, como \
parte do que se vê** (o objeto que ele carrega, o lugar onde está, a criatura ao lado), com a \
aparência informada para cada um e **sem acrescentar mais ninguém**. O enquadramento pode \
abrir para caber o conjunto; o sujeito segue em primeiro plano.

A descrição de cada elemento pode vir em até três partes rotuladas: "Aparência fixa:" \
(traços que não mudam: sempre entram no prompt, mesmo que o instante não os cite), \
"Neste instante:" (roupa, pose, expressão e humor do momento) e "Onde está:" (o lugar \
e o que o cerca naquele momento).

Monte o prompt seguindo esta ordem de blocos, separados por vírgula (pule um \
bloco se não houver informação para ele — nunca invente para preencher):

1. Enquadramento e câmera: um tipo de plano (medium shot, close-up, wide shot, \
low-angle, over-the-shoulder) coerente com a cena ou o retrato.
2. Sujeito principal, num instante congelado: quem/o que é o foco, numa pose \
ou gesto específico e parado — nunca uma ação contínua ("ele caminha e olha \
para trás" vira "mid-stride, glancing back"). Num retrato a pose é a neutra (ver acima).
3. Vestuário, texturas e expressão física de cada elemento presente.
4. Cenário imediato e objetos ao redor: numa cena, os da cena; num retrato, os do "Onde \
está:" do elemento (se não houver esse campo, pule — não invente).
5. Ambiente de fundo, arquitetura e época: numa cena, os da cena; num retrato, o lugar \
do "Onde está:", com os detalhes concretos que ele traz (materiais, objetos, o que se vê \
atrás do sujeito), para que a imagem tenha imersão e o fundo seja o do livro, nunca um \
fundo genérico ou neutro.
6. Iluminação e atmosfera: a fonte de luz (candlelight, golden hour, cool \
moonlight, harsh neon) — a **fonte de luz vem sempre da cena** (horário, clima, o lugar e o \
que ela descreve); o perfil de estilo não escolhe a fonte. Não invente uma fonte que \
contradiga o que foi dito. **O que há no ar (poeira, névoa, fumaça, partículas) só entra se \
os insumos disserem**: não acrescente "dust motes", "mist" ou "suspended particles" só para \
dar clima. Se a descrição não fala em luz, escreva só a que o horário, o clima ou o lugar \
sustentam.

Depois dos blocos acima (a prosa da cena/sujeito), acrescente um bloco \
FINAL e SEPARADO — não misture com a prosa, nem reescreva os campos numa \
frase corrida — com os atributos do perfil de renderização informado, \
traduzidos para o inglês **literalmente**, campo por campo, no formato \
"Style: X. Lighting: Y. Palette: Z. Format: W. Reference: V." (pule um \
campo se ele não vier no perfil informado). Isso é diferente dos blocos 1-6: \
ali você tem liberdade criativa para traduzir o texto do capítulo em \
imagem; aqui não — o perfil já é uma escolha técnica e deliberada do \
usuário, e sua única função é traduzir para o inglês sem interpretar, \
embelezar ou parafrasear. Se o "Lighting" do perfil citar uma fonte de luz que contradiz o \
horário ou o lugar da cena, mantenha a tradução literal, mas escreva no bloco 6 só a fonte \
da cena: o "Lighting" do perfil vale como convenção de renderização (contraste, \
qualidade da sombra), não como fonte.

Regras:
- PROIBIDO usar adjetivos subjetivos de qualidade ou literários ("lindo", \
"incrível", "poderoso", "misterioso", "super detalhado", "épico"). Troque por \
material, textura, luz e enquadramento.
- PROIBIDO descrever emoção como palavra abstrata — traduza em expressão física \
e postura visíveis.
- Mantenha fielmente a aparência de cada elemento como foi descrita; não invente \
elementos que não estão na lista.
- **Lista fechada de quem aparece.** Aparece na imagem **só** quem está na lista de elementos e o que a \
descrição da cena escrita pelo usuário cita. O trecho do livro e o contexto do livro servem para \
confirmar a ação, os objetos que ela usa e a luz, e **nunca** para trazer mais pessoas, criaturas ou \
objetos de destaque: se o trecho cita alguém que não está na lista nem na descrição, esse alguém NÃO \
entra no prompt. Quando a descrição da cena não fala de mais ninguém, diga de forma positiva quem está \
no quadro, ao fim da prosa e antes do bloco de estilo ("only these figures in the frame: a woman and a \
small glowing creature"), sem multidões, figuras ao fundo ou animais que ninguém pediu.
- **Fidelidade ao autor, inclusive no que é delicado.** Descreva o corpo, a roupa (ou \
a falta dela) e a ação exatamente como a descrição informada diz. Se a pessoa está \
nua, escreva que está nua ("nude"); se a descrição não cita roupa, não invente \
nenhuma; e nunca omita, atenue ou troque por conta própria nudez, violência ou \
qualquer outro conteúdo sensível, nem para "proteger" a imagem. Outra etapa do sistema \
cuida disso depois, só se o provedor de imagem recusar o prompt; aqui o seu trabalho é \
ser fiel. Também não acrescente nada que a descrição não diga.
- **O clima emocional vem da cena, não do perfil de estilo.** O humor da imagem é o da \
expressão e da postura descritas para a pessoa e para a cena: se a descrição mostra \
animação, sorriso ou energia, o prompt NÃO pode soar contemplativo, triste ou \
melancólico. Do perfil use só a técnica (pincelada, luz, paleta, formato, referência). \
As palavras de clima do perfil (como "contemplativa", "introspectiva", "onírica") entram \
só no bloco final de estética, traduzidas literalmente, e nunca na prosa da cena.
- **Um só instante.** A descrição de um elemento pode trazer mais de um momento do \
livro (por exemplo, vestido e depois sem roupa). Escolha UM instante e descreva só o \
que vale nele: numa cena, o que a descrição da cena indica; num retrato (sem cena), a roupa e o \
penteado do "Neste instante:" (ou, sem rótulos, do PRIMEIRO momento descrito), com a pose neutra. Dos outros momentos use apenas traços permanentes (cabelo, \
pele, porte, humor), e NUNCA roupa ou pose que contradigam o instante escolhido: o \
prompt não pode juntar, por exemplo, "nude" com roupa, nem duas poses incompatíveis. O \
comentário do usuário, se houver, pode indicar outro momento e vale mais que esta regra.
- **Penteado e roupa vêm só do instante.** Se a "Aparência fixa:" fala de cabelo preso ou solto, \
ignore isso e use o que o "Neste instante:" diz; se o instante não diz, escreva só cor, \
comprimento e tipo do cabelo, sem dizer preso nem solto.
- **Só o que se vê.** Os nomes inventados pelo livro (lugares, criaturas, objetos) não dizem \
nada ao modelo de imagem: no prompt, troque-os pelo que se vê ("a small glowing blue creature \
on a plate", não "Foxen"; "a small stone room", não "the Manto"). Só a pessoa do retrato pode \
aparecer pelo nome. Não conte saídas, portas ou coisas fora do quadro, e não repita o mesmo \
elemento duas vezes.
- **Numa cena, a ação vem da cena.** O que acontece (quem faz o quê, com quem ou com o quê) vem **só** da descrição da \
cena (e do contexto do livro, no que ela não cobre). O "Neste instante:" de cada elemento descreve o estado dele no \
capítulo, que pode ser **outro momento**: dele use só roupa, penteado e estado físico, **nunca a pose, o gesto, a \
expressão ou a ação** quando a cena diz o que a pessoa ou o objeto está fazendo. A **ação principal da cena tem de \
estar clara no prompt** (no bloco do sujeito, num instante congelado) e não pode ser trocada por uma pose parada de um \
elemento: se a cena diz que Auri pinga gotas em Foxen, o prompt mostra isso, e não "Auri parada ao lado". Um elemento \
acrescentado à cena contribui com a **aparência** dele, e não muda o que a cena conta.
- **O lugar vem da cena; num retrato, do "Onde está:".** Numa cena, o cenário é o da \
descrição da cena; o "Onde está:" dos elementos só preenche o que a cena não diz, e nunca \
a contradiz. Num retrato, o "Onde está:" é o cenário: descreva o sujeito dentro dele, em \
primeiro plano e com o ambiente reconhecível ao redor.
- Incorpore o estilo, a paleta e a **convenção de iluminação** do perfil indicado (contraste, \
dureza da sombra, volume); a **fonte** da luz é a da cena.
- **Gênero de cada pessoa presente, sempre que a identidade ou a aparência \
informada permitir concluir com segurança**: deixe isso inequívoco no prompt \
("man", "woman", ou o termo que a informação sustentar — "young man", "elderly \
woman" quando a idade também estiver clara). Ferramentas de imagem produzem \
resultados inconsistentes sem essa indicação explícita. Não invente gênero \
quando a informação não permitir concluir.

Antes de responder, confira: se o sujeito principal (ou qualquer pessoa \
presente na cena) tem gênero claro pela identidade/aparência informada, isso \
aparece marcado sem ambiguidade em algum lugar do texto? Se a resposta for \
não, corrija antes de responder — não devolva o prompt sem essa checagem.

Ordem de prioridade quando houver conflito entre as fontes abaixo:
1. Comentário do usuário (se houver) — é uma correção de quem já viu o \
resultado anterior ou releu o capítulo com atenção. Vale mais que tudo.
2. A descrição da cena escrita pelo usuário — ele já leu o capítulo; é a conta \
oficial do que acontece.
2b. O trecho do livro (se houver) — são as palavras do autor nesse momento: use-o para \
confirmar e completar a ação, os objetos e a luz da cena, e **não acrescente nada que ele \
não sustente**, nem pessoas, criaturas ou objetos de destaque que não estejam na lista de elementos \
nem na descrição da cena. Se a descrição do usuário disser algo diferente do trecho, vale a do usuário.
3. O contexto do livro (se houver) — uma releitura automática, só para \
preencher o que a descrição do usuário não cobriu. Nunca use isso para \
contradizer o que o usuário escreveu.

Responda APENAS com o texto do prompt, sem aspas, sem explicação, sem título, \
sem numerar os blocos.
"""

_INSTRUCAO_DE_PROMPT_DE_VIDEO = """\
Você monta prompts para geradores de vídeo (Veo e afins), a partir de um frame de livro já traduzido para descrições concretas. O \
vídeo tem cerca de 8 segundos. Produza UM prompt em inglês, num parágrafo único, sem título, pronto para colar na ferramenta.

Você pode receber uma IMAGEM DE PARTIDA: o texto do prompt que gerou a imagem que o usuário vai anexar como primeiro quadro do \
vídeo. Isso muda tudo:
- COM imagem de partida: a imagem já define aparência, roupa, cenário e paleta. NÃO redescreva isso em detalhe: use só uma \
referência curta ao sujeito ("the young man at the stone table") e concentre o prompt no MOVIMENTO, na câmera e no som. Quando \
citar algo da imagem, use os mesmos termos do prompt dela; nunca termos que contradigam o que ela mostra.
- SEM imagem de partida: descreva sujeito, roupa, cenário e luz por completo, a partir da aparência de cada elemento informada.

Monte o prompt nesta ordem:
1. Câmera: um plano e UM movimento só (static shot, slow push-in, slow dolly out, gentle pan, tracking shot, slow orbit). Nunca \
corte de cena.
2. Sujeito: referência curta (com imagem) ou descrição completa (sem imagem). Gênero inequívoco sempre que a identidade ou a \
aparência permitir concluir.
3. Ação: UMA ação contínua que caiba em 8 segundos, descrita como movimento físico. Fonte da ação, nesta ordem: comentário do \
usuário, descrição da cena, trecho do livro, contexto do livro. Se nenhuma descreve uma ação, faça um vídeo de CONTEMPLAÇÃO: o \
sujeito quase parado, o ambiente em movimento; nunca invente uma ação. Num RETRATO (um elemento só, sem cena), só movimento \
sutil: respiração, piscar, brisa no cabelo ou na roupa, um leve virar do rosto.
4. Movimento do ambiente: o que mais se move (chama, chuva, tecido, água), SÓ o que os insumos sustentam. Poeira, névoa, fumaça \
e partículas no ar NÃO se acrescentam para dar clima: só entram se os insumos disserem.
5. Luz: com imagem, só o que muda ou se move na luz; sem imagem, a fonte e a atmosfera derivadas do horário e do clima da cena. A \
fonte da luz vem da cena, nunca do perfil de estilo.
6. Som: só sons do próprio ambiente que o texto sustenta ou que são consequência física direta do que se vê (a chama, o vento numa \
janela aberta, os passos). Música NÃO, a menos que o comentário do usuário peça.
7. Bloco final de estilo, separado da prosa: os campos do ESTILO VISUAL informado (o perfil de renderização) traduzidos para o inglês \
LITERALMENTE ("Style: X. Lighting: Y. Palette: Z."), seguido de "Keep this exact visual style throughout the whole motion." Esses \
campos vêm do ESTILO VISUAL, NUNCA do texto da imagem de partida (que pode ter sido escrito com outro perfil): se os dois divergirem, \
vale o ESTILO VISUAL.
8. Termine com: "No on-screen text, no subtitles, no scene cuts, no additional people." e, se não houver música pedida, \
"No music."

Regras:
- PROIBIDO inventar ação, efeito, objeto, pessoa ou som que os insumos não sustentem. Um efeito (magia, tecnologia) só entra como o \
livro o descreve; se ele diz só "usou a magia", fique no gesto.
- PROIBIDO adjetivo subjetivo de qualidade ou literário ("epic", "mysterious", "beautiful", "highly detailed", "4K", "masterpiece").
- PROIBIDO emoção como palavra abstrata: traduza em movimento e expressão física visíveis.
- PROIBIDO mais de uma ação em sequência ("he stands, walks to the door and opens it" vira só uma delas).
- PROIBIDO fala ou diálogo falado.
- Só os elementos informados aparecem; nenhuma pessoa a mais.
- Fidelidade ao autor, inclusive no que é delicado: não omita nem atenue nudez, violência ou qualquer conteúdo sensível, e não acrescente \
nada que os insumos não digam. Outra etapa do sistema cuida de recusas do provedor.

Antes de responder, confira: (1) há uma ação só? (2) há um movimento de câmera só? (3) tudo que se move e soa está sustentado pelo que \
você recebeu? (4) o gênero de cada pessoa está inequívoco? (5) NÃO entrou poeira, névoa ou música sem que os insumos peçam? Se alguma \
resposta for não, corrija antes de responder.

Ordem de prioridade quando houver conflito:
1. Comentário do usuário (se houver).
2. A descrição da cena escrita pelo usuário.
3. O trecho do livro (as palavras do autor), para confirmar e completar a ação.
4. O contexto do livro (apoio, nunca para contradizer o usuário).

Responda APENAS com o texto do prompt, sem aspas, sem explicação, sem título.
"""

_INSTRUCAO_DE_SUAVIZACAO = """\
Você revisa um prompt de geração de imagem que o provedor de imagem RECUSOU por \
conteúdo (moderação). O prompt vem de uma descrição escrita por um autor, e a ideia \
dele tem de continuar legível. Sua tarefa é ACHAR os trechos que têm algo explícito e \
reescrever SÓ esses. Todo o resto do prompt o sistema mantém EXATAMENTE como está: \
você não o devolve e não pode mudá-lo.

Responda APENAS com um JSON neste formato:
{"trocas": [{"trecho": "texto EXATO tirado do prompt", "novo": "a nova redação desse trecho"}]}

Regras das trocas:
- "trecho" tem de ser copiado LETRA POR LETRA do prompt (o sistema o procura no texto). \
Pegue só o pedaço mínimo que precisa mudar, com poucas palavras, mas COMPLETO: inclua \
os adjetivos ligados ao trecho explícito, sem partir a expressão no meio (por exemplo \
"nude with pale, smooth skin" inteiro, e não só "nude with pale"). Nunca uma frase \
inteira nem o prompt todo.
- Só entram trechos que precisam mudar. O que não é explícito NÃO entra na lista: pele, \
cabelo, expressão, postura, objetos, luz, cenário, estilo e o bloco final de estética \
ficam como estão.
- O "novo" ocupa o lugar exato do "trecho" e o resto do prompt continua colado logo \
depois, então a frase tem de continuar correta (releia como ela fica). Se o trecho vem \
ligado a palavras de ligação ("a young woman nude with long golden hair"), inclua o \
pedaço inteiro no "trecho" e escreva o "novo" já com a ligação ("a young woman with bare \
shoulders and arms, her torso softly lost in shadow, and long golden hair"), para não \
sobrar uma frase quebrada.
- Se mais de um trecho for explícito, uma troca para cada um. Nunca devolva "novo" vazio.
- Mude o MÍNIMO: troque só a palavra ou a expressão explícita e mantenha, no "novo", o \
que era do trecho e não era problema (como "pale, smooth skin"). Não troque por \
sinônimos o que não era problema.

O que é "explícito" e como reescrever:
- Nudez: o objetivo é SUGERIR, e não vestir. NÃO acrescente roupa, tecido, manto, \
vestido, pano, túnica nem qualquer peça de vestuário que o prompt não citava: a pessoa \
continua como o autor a descreveu, só sem as palavras explícitas. Não use nude, naked, \
topless nem bare body. O "novo" de um trecho de nudez tem de dizer DUAS coisas: o que \
APARECE (por exemplo, ombros e braços) E o que COBRE o resto, escrito por extenso (por \
exemplo "her torso softly lost in shadow", "half in shadow", "the lower body outside the \
frame"). Apagar só a palavra "nude", ou escrever só "bare shoulders and arms", NÃO \
basta: sem a cobertura escrita, a ideia do autor se perde. A cobertura vem da \
COMPOSIÇÃO: a sombra, o enquadramento, um braço ou uma mão, a pose, o cabelo caindo \
sobre o corpo (só se o prompt não o descreve preso) ou objetos do cenário na frente. \
A cobertura NÃO pode contradizer o resto \
do prompt: se o cabelo está preso, não o faça cair sobre o corpo; se os braços estão \
levantados, não os cruze nem os abaixe. Quando a pose e o cabelo já estão descritos no \
prompt, cubra com SOMBRA ou ENQUADRAMENTO, que não conflitam com nada ("her torso softly \
lost in shadow", "the lower body outside the frame", "soft shadows across her chest").
  Exemplo CERTO: "nude with pale, smooth skin" -> "bare shoulders and arms, pale, smooth \
skin, her torso softly lost in shadow".
  Exemplo ERRADO 1: "nude with pale, smooth skin" -> "pale, smooth skin" (só apagou a \
palavra: a ideia do autor se perdeu).
  Exemplo ERRADO 2: "nude with pale, smooth skin" -> "wearing a loose linen dress" (isso \
muda o que o autor descreveu).
- Violência: sempre sem sangue e sem nada explícito: troque também a ferida aberta, o \
corte e o corpo mutilado, não só a palavra "blood". Sugira pelo instante antes ou \
depois, por sombras, pela expressão e pela postura.
  Exemplo CERTO: "a deep gaping wound across his chest with blood pouring out" -> "a \
dark shadow across his chest, his torn armor stained".
  Exemplo ERRADO: "a deep gaping wound across his chest with blood pouring out" -> "a \
deep gaping wound across his chest" (só tirou a palavra "blood": a ferida aberta, que é o \
explícito, ficou).
- Menores de idade: SÓ quando o prompt disser ou deixar claro que a pessoa é criança, \
adolescente ou tem menos de 18 anos ("child", "girl", "boy", "teenager", uma idade \
abaixo de 18), ela fica sempre vestida e nunca em cena sensual. "Young woman" e "young \
man" são adultos: não aplique esta regra a eles, e nunca vista alguém só por precaução.
- Não torne a cena mais sensual nem mais violenta do que era.
"""

_INSTRUCAO_DE_TRADUCAO_PARA_PORTUGUES = """\
Você traduz prompts de geração de imagem do inglês para o português do Brasil, para uma pessoa ler.

REGRAS:
- Traduza TUDO, sem resumir, sem acrescentar nem tirar nenhum detalhe (personagens, roupas, cenário, luz, câmera, estilo).
- Mantenha nomes próprios como estão.
- Termos técnicos de fotografia, arte ou estilo sem tradução natural podem ficar em inglês.
- Responda SÓ com a tradução, sem comentários nem aspas.
"""

_INSTRUCAO_DE_TRADUCAO_PARA_INGLES = """\
You translate image-generation prompts from Brazilian Portuguese into English, to be sent to an image model.

RULES:
- Translate EVERYTHING, without summarizing and without adding or removing any detail (characters, clothing, setting, light, camera, style).
- Keep proper names as they are.
- Write natural, descriptive English, as a good image prompt reads; keep photographic/art style terms in their usual English form.
- Reply ONLY with the translation, no comments and no quotation marks.
"""

_INSTRUCAO_DE_CORRECAO = """\
Você corrige prompts de geração de imagem (em inglês) a pedido de uma pessoa que já viu o resultado ou releu o texto.

Você recebe o PROMPT ATUAL e o PEDIDO DE CORREÇÃO (em português ou inglês). Devolva o prompt corrigido.

REGRAS:
- O pedido da pessoa vale mais que qualquer parte do prompt atual: se ele contradiz o prompt, o pedido vence.
- Mude SÓ o que o pedido manda mudar. Todo o resto fica IDÊNTICO ao prompt atual, palavra por palavra: personagens, roupas, cenário, luz, câmera, ordem dos blocos.
- Se o pedido manda tirar algo, tire-o por inteiro (e qualquer frase que dependa dele); se manda trocar, troque só isso.
- Mantenha o prompt em inglês, num texto corrido só, e mantenha o bloco final de estilo ("Style: ... Lighting: ... Palette: ...") como está, a menos que o pedido seja sobre ele.
- Não acrescente elementos, pessoas, objetos nem adjetivos subjetivos de qualidade ("beautiful", "epic", "stunning") que o pedido não mencione.
- Se o pedido é impossível de aplicar ao prompt (por exemplo, manda tirar algo que não está nele), devolva o prompt atual sem mudanças.
- Responda SÓ com o prompt corrigido, sem comentários, sem aspas, sem título.
"""

_DESCRICAO_DE_CATEGORIA = {
    CategoriaEstilo.FOTORREALISTA_CINEMATOGRAFICO: (
        "still de cinema: lente e enquadramento fotográficos, profundidade de "
        "campo, grão de filme — não pareça uma pintura"
    ),
    CategoriaEstilo.PINTURA_A_OLEO: (
        "pincelada visível, textura de tela, tradição da pintura clássica a óleo"
    ),
    CategoriaEstilo.AQUARELA: (
        "traços soltos, transparência, bordas que sangram — nunca bordas duras "
        "nem textura de tela"
    ),
    CategoriaEstilo.ARTE_DIGITAL_CONCEITUAL: (
        "pintura digital de \"concept art\" (jogos/cinema): luz dramática, "
        "pincelada digital limpa — sem grão de filme nem textura de tela"
    ),
    CategoriaEstilo.QUADRINHOS: (
        "contorno de tinta bem definido, cores chapadas ou tramadas, estética "
        "de graphic novel — nunca fotorrealista"
    ),
    CategoriaEstilo.CARTOON_ANIMACAO: (
        "formas simplificadas, cores vivas e saturadas, estética de animação — "
        "nunca fotorrealista nem pintura tradicional"
    ),
    CategoriaEstilo.ANIME: (
        "ilustração de anime: contorno de tinta fino, cel-shading com sombras "
        "chapadas de borda dura, olhos grandes e traços estilizados — nunca "
        "textura de pele realista nem fotografia"
    ),
    CategoriaEstilo.PIXEL_ART: (
        "pixel art de jogo retrô: grade de pixels visível, paleta limitada, "
        "dithering no lugar de degradê — nunca suave nem em alta resolução"
    ),
    CategoriaEstilo.GRAVURA_CLASSICA: (
        "gravura clássica de livro do século XIX: linhas de tinta com hachura "
        "cruzada, monocromática ou sépia sobre papel envelhecido — nunca "
        "colorida nem com sombreado suave"
    ),
    CategoriaEstilo.ANIMACAO_3D: (
        "longa-metragem de animação 3D: formas esculpidas, proporções levemente "
        "exageradas, olhos grandes, luz global e cor rica — nunca fotográfica "
        "nem 2D chapada. Não cite nome de estúdio"
    ),
}

_INSTRUCAO_DE_PERFIL = """\
Você sugere um estilo visual (perfil de renderização) para adaptar um livro em \
imagens de referência geradas por IA. Você recebe só título, autor e idioma do \
livro — não o texto dele. Se reconhecer a obra, use o que sabe sobre gênero, \
tom, época e ambientação; se precisar, pesquise na internet para identificar a \
obra antes de responder. Se não conseguir identificar o livro com confiança a \
partir do que foi informado, responda com todos os campos usando o valor JSON \
`null` (nunca a palavra "nulo" como texto) em vez de inventar um estilo genérico \
— e "reconheceu_a_obra": false.

`reconheceu_a_obra` é `true` sempre que você identificou a obra com confiança \
razoável, mesmo que algum campo específico (ex.: um artista de referência) \
ainda fique `null` por falta de informação — isso é diferente de não \
reconhecer o livro. Só use `false` quando você genuinamente não sabe de que \
livro se trata.

## Categorias de estilo (escolha UMA, nunca misture)

{categorias}

Se o pedido trouxer uma "CATEGORIA ESCOLHIDA", use exatamente essa — não troque \
por outra, mesmo que ache outra mais adequada ao livro. Sem categoria indicada, \
escolha você mesma a mais coerente com o gênero/tom da obra, mas ainda assim \
**uma só** da lista acima — nunca combine técnicas de categorias diferentes \
(ex.: nunca "pintura a óleo" com "grão de filme", que é de outra categoria).

## Regras

- Todo campo é linguagem **técnica e visual** (técnica de arte, tipo de luz, \
cor), nunca linguagem **temática ou narrativa** ("conspiração", "traição", \
"revelação", "nostalgia", "perigo", "dualidade", "mistério", "tensão") — um \
modelo de imagem não sabe desenhar um tema, só técnica, luz e cor concretas. \
Isso vale mesmo como qualificador dentro de uma frase maior: "paleta que \
sugere perigo e duplicidade" é tão temática quanto "perigo e duplicidade" \
sozinho — o problema não é a palavra estar isolada, é ela aparecer em \
qualquer lugar do campo.
- Teste cada campo antes de responder: um ilustrador consegue desenhar \
literalmente o que você escreveu, sem precisar interpretar um sentimento ou \
uma intenção narrativa? Se a resposta for não, reescreva só com o que é \
fisicamente visível (cor, luz, textura, traço) — nunca a emoção ou o tema por \
trás disso.
- "artista_referencia" deve combinar com a categoria escolhida (não cite um \
pintor a óleo clássico para a categoria QUADRINHOS, por exemplo).
- "iluminacao" descreve só a **convenção de renderização** da luz (contraste, \
dureza e profundidade das sombras, como a luz modela o volume), **nunca a fonte** \
("luz de vela", "pôr do sol", "luar"): o perfil vale para o livro inteiro, e a fonte \
de luz de cada cena vem do horário e do lugar dela. Uma fonte no perfil contradiria \
as cenas que não combinam com ela.

Responda APENAS com um objeto JSON, sem texto antes ou depois, neste formato:

{{
  "reconheceu_a_obra": true,
  "estilo": "técnica e tom visual dentro da categoria escolhida, ex.: 'aquarela, traços soltos, sombras marcadas'",
  "artista_referencia": "um artista ou estilo artístico coerente com a categoria, ou nulo",
  "iluminacao": "só a CONVENÇÃO de renderização da luz, ex.: 'alto contraste, sombras profundas e suaves, volume modelado pela luz'",
  "paleta": "cores predominantes, ex.: 'tons terrosos e cinza'",
  "formato": "uma palavra: retrato, paisagem ou quadrado",
  "categoria_estilo": "o identificador exato da categoria escolhida, ex.: 'PINTURA_A_OLEO'"
}}

Escreva em português, exceto o nome de artistas/obras.
"""

_INSTRUCAO_DE_PERFIL = _INSTRUCAO_DE_PERFIL.format(
    categorias="\n".join(
        f"- {categoria.value}: {descricao}"
        for categoria, descricao in _DESCRICAO_DE_CATEGORIA.items()
    )
)


class ErroHttpDoProvedor(ErroDoProvedorIA):
    """O OpenRouter respondeu com um código de erro HTTP.

    Filha de ``ErroDoProvedorIA`` (para o resto do sistema nada muda), mas guarda o ``codigo`` e o
    corpo da resposta: é com eles que ``gerar_imagem`` distingue uma **recusa de conteúdo** de
    qualquer outra falha (S4).
    """

    def __init__(self, codigo: int, corpo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.corpo = corpo


_MARCAS_DE_RECUSA_DE_CONTEUDO = (
    "content management policy",  # Meta (meta/muse-image)
    "sexual or adult content",  # Black Forest Labs (flux.2-klein-4b)
    "content policy",
    "moderation",
)
"""Trechos (em minúsculas) que, num erro 400, indicam recusa de conteúdo (S4).

**É o único lugar** que sabe como cada provedor escreve a recusa: se um deles mudar o texto, é aqui
que se ajusta. Mensagem desconhecida cai no erro comum (sem suavizar)."""


def _motivo_de_recusa(erro: ErroHttpDoProvedor) -> str | None:
    """A mensagem do provedor se o erro é uma recusa de conteúdo (S4); ``None`` se é outro erro."""
    if erro.codigo != 400:
        return None
    mensagem = erro.corpo
    try:
        dado = json.loads(erro.corpo)
        texto = dado["error"]["message"]
        if isinstance(texto, str) and texto.strip():
            mensagem = texto
    except (ValueError, KeyError, TypeError):
        pass
    if any(marca in mensagem.lower() for marca in _MARCAS_DE_RECUSA_DE_CONTEUDO):
        return mensagem.strip()
    return None


@dataclass(frozen=True)
class PedidoComCapitulo:
    """Um pedido de **leitura** de um capítulo (4.10, LM9): o capítulo, que é igual em todas as leituras dele, e o que varia.

    Existe para o capítulo ir **primeiro** no pedido. Os provedores guardam em cache o **começo** do pedido, então, com o capítulo antes
    do que muda (o elemento, a cena), cada leitura depois da primeira paga o capítulo a preço de cache, e não de novo por inteiro.
    """

    capitulo: str
    """``Capitulo.texto`` **sem nenhuma normalização**: o prefixo tem de ser idêntico, byte a byte, entre as leituras do mesmo capítulo."""

    variavel: str
    """O que muda de uma leitura para outra. **Nada disto** pode vir antes do capítulo (nome do elemento, id, hora...)."""


RODAPE_DO_CAPITULO = "\n\n---\n"
"""O que separa o capítulo do que varia, no pedido (LM9)."""


class ProvedorOpenRouter(ProvedorIA):
    """Conversa com o OpenRouter.

    O cliente HTTP é recebido de fora para os testes poderem injetar um
    transporte falso, em vez de a classe criar a conexão por conta própria.
    """

    def __init__(
        self,
        chave_api: str | None = None,
        cliente: httpx.Client | None = None,
        ao_usar: Callable[[UsoDaChamada], None] | None = None,
        geradores_de_imagem: dict[str, GeradorDeImagemExterno] | None = None,
        dormir: Callable[[float], None] = time.sleep,
        modelo_reserva: str | None = None,
    ):
        self._modelo_reserva = modelo_reserva
        """O modelo a que o OpenRouter recorre se o principal de uma chamada de texto falhar (4.10, LM13). Nulo = sem reserva."""
        self._dormir = dormir
        """Como esperar entre uma tentativa e outra (LM5). Os testes injetam um falso, para não esperar de verdade."""
        self._geradores_de_imagem = geradores_de_imagem or {}
        """Os geradores de imagem dos outros fornecedores (fal.ai, Replicate), só dos que têm chave (F2)."""
        self._chave_api = chave_api
        self._cliente = cliente or httpx.Client(base_url=ENDERECO_BASE, timeout=TEMPO_LIMITE)
        self._precos_de_voz: dict[str, Decimal | None] | None = None
        """O preço por caractere de cada modelo de voz, lido do catálogo **uma vez** por provedor (NA3)."""
        self._ao_usar = ao_usar
        """Chamada depois de cada conversa bem-sucedida, com o que ela consumiu (item 4.3).
        O provedor não sabe o que fazer com isso (gravar, somar...): só avisa."""

    # ----------------------------------------------------------------------- #
    # Modelos
    # ----------------------------------------------------------------------- #

    def listar_modelos(self) -> list[ModeloDisponivel]:
        """Os modelos de texto do OpenRouter.

        Este endpoint é **público**: não precisa de chave. É o que permite a tela
        de configuração mostrar a lista antes de a chave estar cadastrada — o que
        é justamente a ordem em que o usuário faz as coisas.

        Modelos que não recebem e devolvem texto são descartados: a lista tem
        modelos de imagem, áudio e música, e nenhum deles serve aqui.
        """
        # A mesma leitura que a montagem de cada chamada usa (LM17): no máximo uma ida ao OpenRouter a cada 10 minutos.
        brutos = ler_catalogo(lambda: self._pedir("GET", "/models"))

        modelos = []
        for bruto in brutos:
            if not _e_modelo_de_texto(bruto):
                continue
            capacidades = capacidades_de(bruto)  # LM16: o que decide a escolha de um modelo para ler um livro
            modelos.append(
                ModeloDisponivel(
                    id=bruto.get("id", ""),
                    nome=bruto.get("name") or bruto.get("id", ""),
                    contexto=int(bruto.get("context_length") or 0),
                    gratuito=_e_gratuito(bruto),
                    suporta_json=_suporta_json(bruto),
                    custo_saida=_custo_de_saida(bruto),
                    moderado=_e_moderado(bruto),
                    preco_entrada=float(capacidades.preco_entrada or 0),
                    preco_cache_leitura=None if capacidades.preco_cache_leitura is None else float(capacidades.preco_cache_leitura),
                    raciocinio_obrigatorio=capacidades.raciocinio_obrigatorio,
                    esforcos=list(capacidades.esforcos),
                    rapido=e_rapido(capacidades),
                    saida_maxima=capacidades.saida_maxima,
                )
            )

        return sorted(modelos, key=lambda m: (not m.gratuito, m.nome.lower()))

    def listar_modelos_de_imagem(self) -> list[ModeloDeImagemDisponivel]:
        """Os modelos de **imagem** do OpenRouter (endpoint público, sem chave), com o preço **por token de imagem** (MI1)."""
        dados = self._pedir("GET", "/models?output_modalities=image")
        modelos = []
        for bruto in dados.get("data", []):
            if not bruto.get("id") or bruto["id"].startswith("openrouter/"):  # "openrouter/auto" é um roteador, não um modelo
                continue
            preco = bruto.get("pricing") or {}
            modelos.append(
                ModeloDeImagemDisponivel(
                    id=bruto["id"],
                    nome=bruto.get("name") or bruto["id"],
                    preco_por_token=_numero_ou_nulo(preco.get("image_output") or preco.get("image_token")),
                    moderado=_e_moderado(bruto),
                )
            )
        return sorted(modelos, key=lambda m: m.nome.lower())

    # ----------------------------------------------------------------------- #
    # Voz (NA1 a NA3)
    # ----------------------------------------------------------------------- #

    def listar_modelos_de_voz(self) -> list[ModeloDeVoz]:
        """Os modelos de **voz** do OpenRouter (endpoint público, sem chave), com as vozes e o preço **por caractere** (NA1).

        O preço só vale como "por caractere" quando o modelo cobra **só** a entrada (``pricing.prompt``): quem cobra também por token de
        saída (Gemini TTS) ou só por segundo (Seed Audio) fica sem preço, porque dar um número daria um falso. Gratuito = preço zero."""
        dados = self._pedir("GET", "/models?output_modalities=speech")
        modelos = []
        for bruto in dados.get("data", []):
            if not bruto.get("id"):
                continue
            preco = bruto.get("pricing") or {}
            entrada, saida = _decimal_ou_nulo(preco.get("prompt")), _decimal_ou_nulo(preco.get("completion"))
            # Gratuito = **todo** preço zero (Seed Audio tem o prompt em zero e cobra por segundo: não é gratuito); sem preço nenhum = não se sabe.
            gratuito = bool(preco) and all((_decimal_ou_nulo(v) or 0) == 0 for v in preco.values())
            por_caractere = Decimal(0) if gratuito else (entrada if entrada and not saida else None)
            modelos.append(
                ModeloDeVoz(
                    id=bruto["id"],
                    nome=bruto.get("name") or bruto["id"],
                    vozes=[str(v) for v in (bruto.get("supported_voices") or [])],
                    preco_por_caractere=por_caractere,
                    gratuito=gratuito,
                )
            )
        return sorted(modelos, key=lambda m: (not m.gratuito, m.nome.lower()))

    @property
    def pode_narrar(self) -> bool:
        return bool(self._chave_api)

    def narrar(self, texto: str, modelo: str, voz: str | None) -> AudioNarrado:
        """Fala o texto pelo endpoint de voz do OpenRouter (``/audio/speech``, compatível com o da OpenAI) e devolve o MP3 (NA1)."""
        if not modelo:
            raise ModeloNaoEscolhido("Nenhum modelo de narração foi escolhido. Escolha um em Configurações → Narração.")
        if not self._chave_api:
            raise ChaveDeApiAusente(
                "Não há chave de API do OpenRouter configurada. Defina a variável de ambiente CHAVE_API_OPENROUTER ou mande a sua chave pelo app."
            )
        corpo = {"model": modelo, "input": texto, "response_format": "mp3"}
        if voz:
            corpo["voice"] = voz

        conteudo, cabecalhos = self._pedir_audio(corpo)
        custo = self._custo_da_narracao(modelo, len(texto))
        id_da_geracao = cabecalhos.get("x-generation-id")
        self._avisar_narracao(modelo, custo, id_da_geracao)
        return AudioNarrado(conteudo=conteudo, custo=custo, id_da_geracao=id_da_geracao)

    def _custo_da_narracao(self, modelo: str, caracteres: int) -> Decimal | None:
        """Caracteres × o preço por caractere que o catálogo informa (NA3); ``None`` se o modelo não cobra por caractere ou o catálogo falhou."""
        if self._precos_de_voz is None:
            try:
                self._precos_de_voz = {m.id: m.preco_por_caractere for m in self.listar_modelos_de_voz()}
            except ErroDoProvedorIA:
                logging.getLogger(__name__).warning("Não foi possível ler os preços das vozes do OpenRouter agora.")
                return None  # tenta de novo no próximo trecho
        preco = self._precos_de_voz.get(modelo)
        return None if preco is None else (Decimal(caracteres) * preco).quantize(Decimal("0.00000001"))

    def _avisar_narracao(self, modelo: str, custo: Decimal | None, id_da_geracao: str | None) -> None:
        """Avisa o ``ao_usar`` do trecho falado. **Nunca derruba a chamada** (como ``_avisar_uso``). O custo vai como estimado (CU2)."""
        if self._ao_usar is None:
            return
        try:
            self._ao_usar(
                UsoDaChamada(operacao="narracao", modelo=modelo, custo=custo, id_da_geracao=id_da_geracao, estimado=custo is not None)
            )
        except Exception:  # noqa: BLE001 - de propósito: métrica nunca derruba a chamada
            logging.getLogger(__name__).exception("Não foi possível anotar o consumo da narração.")

    # ----------------------------------------------------------------------- #
    # As três operações do item 4.2
    # ----------------------------------------------------------------------- #

    def extrair_elementos(
        self,
        texto_capitulo: str,
        elementos_conhecidos: list[str],
        modelo: str,
        orientacao: str | None = None,
    ) -> ExtracaoDeElementos:
        """Pede ao modelo os elementos visuais do capítulo — fase 1 (passo 6)."""
        conhecidos = (
            "\n".join(f"- {elemento}" for elemento in elementos_conhecidos)
            if elementos_conhecidos
            else "(nenhum elemento cadastrado ainda)"
        )
        variavel = f"ELEMENTOS JÁ CADASTRADOS NESTE LIVRO (nome, tipo e quem são):\n{conhecidos}"
        if orientacao:
            variavel += (
                "\n\nORIENTAÇÃO DO USUÁRIO (algo que ele acha que a análise anterior deixou passar; "
                f"é um palpite dele, não um fato):\n{orientacao}"
            )
        pedido = PedidoComCapitulo(capitulo=texto_capitulo, variavel=variavel)

        resposta = self._conversar(modelo, _INSTRUCAO_DE_EXTRACAO, pedido, operacao="extracao", temperatura=TEMPERATURA_DE_FIDELIDADE)
        bruto = _extrair_json(resposta)
        if bruto is None:
            raise ErroDoProvedorIA(
                "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
                "pequenos não seguem bem instruções de formato."
            )
        return ExtracaoDeElementos(
            elementos=_interpretar_elementos(bruto),
            cenas=_interpretar_cenas_sugeridas(bruto),
            modelo=modelo,
        )

    def sugerir_estado(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        descricao_do_elemento: str | None,
        estado_atual: str | None,
        modelo: str,
        aparencia_anterior: str | None = None,
        id_do_capitulo: int | None = None,
    ) -> EstadoSugerido:
        """Pede ao modelo a aparência de UM elemento — fase 2 (item 4.4)."""
        pedido = PedidoComCapitulo(
            capitulo=texto_capitulo,
            variavel=(
                f"ELEMENTO A DESCREVER: {nome} ({tipo.name})\n"
                f"IDENTIDADE JÁ CONHECIDA: {descricao_do_elemento or '(nenhuma)'}\n"
                f"APARÊNCIA ESTABELECIDA ATÉ AQUI (traços fixos de capítulos anteriores): "
                f"{aparencia_anterior or '(nenhuma ainda)'}\n"
                f"ESTADO JÁ REGISTRADO (pode estar desatualizado): "
                f"{estado_atual or '(nenhum ainda)'}"
            ),
        )

        resposta = self._conversar(
            modelo, _INSTRUCAO_DE_ESTADO, pedido, operacao="estado", temperatura=TEMPERATURA_DE_FIDELIDADE,
            sessao_de_cache=_sessao_de_cache(id_do_capitulo, texto_capitulo),
        )
        return EstadoSugerido(descricao=_interpretar_estado(resposta), modelo=modelo)

    def sugerir_identidade(
        self,
        texto_capitulo: str,
        tipo: TipoElemento,
        nome: str,
        identidade_vigente: str | None,
        modelo: str,
        id_do_capitulo: int | None = None,
    ) -> IdentidadeSugerida:
        """Pede ao modelo o que há de novo na identidade de UM elemento — fase 2b."""
        pedido = PedidoComCapitulo(
            capitulo=texto_capitulo,
            variavel=(
                f"ELEMENTO: {nome} ({tipo.name})\n"
                f"IDENTIDADE JÁ CONHECIDA: {identidade_vigente or '(nenhuma ainda)'}"
            ),
        )

        resposta = self._conversar(
            modelo, _INSTRUCAO_DE_IDENTIDADE, pedido, operacao="identidade", temperatura=TEMPERATURA_DE_FIDELIDADE,
            sessao_de_cache=_sessao_de_cache(id_do_capitulo, texto_capitulo),
        )
        return IdentidadeSugerida(descricao=_interpretar_identidade(resposta), modelo=modelo)

    def fundamentar_frame(
        self,
        texto_capitulo: str,
        titulo: str,
        descricao: str | None,
        horario: str | None,
        clima: str | None,
        humor: str | None,
        participantes: list[str],
        modelo: str,
        trecho: str | None = None,
        id_do_capitulo: int | None = None,
    ) -> FrameFundamentado:
        """Pede ao modelo para conferir a cena contra o capítulo (item 4.4)."""
        lista = "\n".join(f"- {p}" for p in participantes) or "(nenhum)"
        variavel = (
            f"O QUE O USUÁRIO ESCREVEU SOBRE A CENA:\n"
            f"Título: {titulo}\n"
            f"Descrição: {descricao or '(nenhuma)'}\n"
            f"Horário: {horario or '(não informado)'}\n"
            f"Clima: {clima or '(não informado)'}\n"
            f"Humor: {humor or '(não informado)'}\n\n"
            f"PARTICIPANTES, COM A APARÊNCIA JÁ ESTABELECIDA:\n{lista}"
        )
        if trecho:
            variavel += f"\n\nTRECHO DO LIVRO EM QUE A CENA ACONTECE (literal, as palavras do autor):\n{trecho}"
        pedido = PedidoComCapitulo(capitulo=texto_capitulo, variavel=variavel)

        resposta = self._conversar(
            modelo, _INSTRUCAO_DE_FUNDAMENTACAO_DE_FRAME, pedido, operacao="fundamentacao", temperatura=TEMPERATURA_DE_FIDELIDADE,
            sessao_de_cache=_sessao_de_cache(id_do_capitulo, texto_capitulo),
        )
        return FrameFundamentado(
            contexto=_interpretar_contexto(resposta), modelo=modelo
        )

    def montar_prompt(
        self,
        descricao_do_frame: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
        contexto_do_livro: str | None = None,
        comentario_do_usuario: str | None = None,
        elementos_vinculados: list[str] | None = None,
        trecho_do_livro: str | None = None,
    ) -> PromptMontado:
        """Pede ao modelo o prompt de imagem (passo 8)."""
        lista = "\n".join(f"- {elemento}" for elemento in elementos) or "(nenhum)"
        pedido = (
            f"CENA (escrita pelo usuário; vazio significa retrato solo):\n"
            f"{descricao_do_frame or '(nenhuma — monte um retrato)'}\n\n"
            f"ELEMENTOS QUE APARECEM, COM A APARÊNCIA DE CADA UM:\n{lista}\n\n"
            f"ESTILO VISUAL:\n{perfil_renderizacao}"
        )
        if elementos_vinculados:
            vinculados = "\n".join(f"- {elemento}" for elemento in elementos_vinculados)
            pedido += f"\n\nELEMENTOS VINCULADOS AO SUJEITO (aparecem junto dele neste retrato):\n{vinculados}"
        if trecho_do_livro:
            pedido += f"\n\nTRECHO DO LIVRO (o que o autor escreveu neste momento; confira com ele a ação, os objetos e a luz):\n{trecho_do_livro}"
        if contexto_do_livro:
            pedido += f"\n\nCONTEXTO DO LIVRO (apoio, não substitui a cena acima):\n{contexto_do_livro}"
        if comentario_do_usuario:
            pedido += f"\n\nCOMENTÁRIO DO USUÁRIO (prioridade máxima):\n{comentario_do_usuario}"

        resposta = self._conversar(modelo, _INSTRUCAO_DE_PROMPT, pedido, operacao="prompt", temperatura=TEMPERATURA_DO_PROMPT)
        return PromptMontado(texto=resposta.strip(), modelo=modelo)

    def montar_prompt_de_video(
        self,
        descricao_do_frame: str,
        elementos: list[str],
        perfil_renderizacao: str,
        modelo: str,
        contexto_do_livro: str | None = None,
        comentario_do_usuario: str | None = None,
        elementos_vinculados: list[str] | None = None,
        trecho_do_livro: str | None = None,
        prompt_da_imagem: str | None = None,
        eh_retrato: bool = False,
    ) -> PromptMontado:
        """Pede ao modelo o prompt de vídeo (item 4.8)."""
        lista = "\n".join(f"- {elemento}" for elemento in elementos) or "(nenhum)"
        pedido = (
            f"TIPO DO FRAME: {'RETRATO (retrato vivo, sem ação narrativa)' if eh_retrato else 'CENA'}\n\n"
            f"CENA (escrita pelo usuário; vazio significa retrato solo):\n"
            f"{descricao_do_frame or '(nenhuma — monte um retrato vivo)'}\n\n"
            f"ELEMENTOS QUE APARECEM, COM A APARÊNCIA DE CADA UM:\n{lista}\n\n"
            f"ESTILO VISUAL:\n{perfil_renderizacao}"
        )
        if elementos_vinculados:
            vinculados = "\n".join(f"- {elemento}" for elemento in elementos_vinculados)
            pedido += f"\n\nELEMENTOS VINCULADOS AO SUJEITO (aparecem junto dele):\n{vinculados}"
        if trecho_do_livro:
            pedido += f"\n\nTRECHO DO LIVRO (o que o autor escreveu neste momento):\n{trecho_do_livro}"
        if contexto_do_livro:
            pedido += f"\n\nCONTEXTO DO LIVRO (apoio, não substitui a cena acima):\n{contexto_do_livro}"
        if prompt_da_imagem:
            pedido += (
                "\n\nIMAGEM DE PARTIDA (o texto do prompt que gerou a imagem usada como primeiro quadro; "
                f"ela já define a aparência):\n{prompt_da_imagem}"
            )
        else:
            pedido += "\n\nIMAGEM DE PARTIDA: (nenhuma — descreva sujeito, roupa, cenário e luz por completo)"
        if comentario_do_usuario:
            pedido += f"\n\nCOMENTÁRIO DO USUÁRIO (prioridade máxima):\n{comentario_do_usuario}"

        resposta = self._conversar(modelo, _INSTRUCAO_DE_PROMPT_DE_VIDEO, pedido, operacao="prompt_de_video", temperatura=TEMPERATURA_DO_PROMPT)
        return PromptMontado(texto=resposta.strip(), modelo=modelo)

    def traduzir_prompt(self, texto: str, para: str, modelo: str) -> PromptMontado:
        """Traduz um prompt entre inglês e português com um modelo barato (PT2, PT3). Uma chamada, temperatura baixa."""
        if not texto.strip():
            raise ErroDoProvedorIA("O texto a traduzir está vazio.")
        if para not in ("pt", "en"):
            raise ErroDoProvedorIA("A tradução é só entre inglês (en) e português (pt).")
        instrucao = _INSTRUCAO_DE_TRADUCAO_PARA_PORTUGUES if para == "pt" else _INSTRUCAO_DE_TRADUCAO_PARA_INGLES
        resposta = self._conversar(modelo, instrucao, texto, operacao="traducao", temperatura=TEMPERATURA_DA_TRADUCAO)
        traduzido = resposta.strip()
        if not traduzido:
            raise ErroDoProvedorIA(f"O modelo {modelo} devolveu uma tradução vazia.")
        return PromptMontado(texto=traduzido, modelo=modelo)

    def corrigir_prompt(self, texto: str, instrucao: str, modelo: str) -> PromptMontado:
        """Corrige o prompt como a pessoa pediu, mudando só o que o pedido manda (P6). Uma chamada, temperatura baixa."""
        if not texto.strip():
            raise ErroDoProvedorIA("O prompt a corrigir está vazio.")
        if not instrucao.strip():
            raise ErroDoProvedorIA("Diga o que você quer mudar no prompt.")
        pedido = f"PROMPT ATUAL:\n{texto.strip()}\n\nPEDIDO DE CORREÇÃO:\n{instrucao.strip()}"
        resposta = self._conversar(modelo, _INSTRUCAO_DE_CORRECAO, pedido, operacao="correcao", temperatura=TEMPERATURA_DA_CORRECAO)
        corrigido = resposta.strip()
        if not corrigido:
            raise ErroDoProvedorIA(f"O modelo {modelo} devolveu um prompt vazio.")
        return PromptMontado(texto=corrigido, modelo=modelo)

    def suavizar_prompt(self, texto: str, modelo: str) -> PromptMontado:
        """Suaviza um prompt recusado trocando **só os trechos explícitos**, e deixa o resto idêntico (S7 revisada).

        O modelo recebe o prompt inteiro e devolve **pares** ``trecho exato -> nova redação``. O servidor confere que
        cada trecho existe **literalmente** no prompt e faz a troca; todo o resto do texto fica como o autor o escreveu
        **por construção**: o modelo não consegue suprimir um ponto da descrição, porque não devolve o texto, só as
        trocas. Troca inválida (trecho que não existe, vazio, igual, que se sobrepõe a outra ou grande demais) ou
        nenhuma troca = uma nova tentativa; errando de novo, ``ErroDoProvedorIA``.
        """
        if not texto.strip():
            raise ErroDoProvedorIA("O prompt a suavizar está vazio.")
        pedido = f"PROMPT RECUSADO PELO PROVEDOR DE IMAGEM:\n{texto}"

        motivo_anterior: str | None = None
        for _ in range(TENTATIVAS_DA_SUAVIZACAO):
            # Na segunda tentativa, diz por que a primeira foi recusada: sem isso o modelo repetiria a mesma resposta.
            pedido_atual = pedido
            if motivo_anterior:
                pedido_atual += f"\n\nATENÇÃO: a sua resposta anterior foi recusada porque {motivo_anterior}. Corrija."
            resposta = self._conversar(
                modelo, _INSTRUCAO_DE_SUAVIZACAO, pedido_atual, operacao="suavizacao", temperatura=TEMPERATURA_DA_SUAVIZACAO
            )
            suave, motivo_anterior = _aplicar_trocas(texto, resposta)
            if suave is not None:
                return PromptMontado(texto=suave, modelo=modelo)
        raise ErroDoProvedorIA(
            f"O modelo {modelo} não apontou trocas válidas para suavizar o prompt. Edite o prompt à mão e tente de novo."
        )

    def gerar_imagem(
        self,
        prompt: str,
        modelo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        """Gera a imagem por ``POST /images`` (não o ``/chat/completions``, que recusa modelos de imagem).

        Só ``model`` e ``prompt`` no pedido: foi o que se testou com o ``meta/muse-image``. A resposta
        traz a imagem em base64 (``data[0].b64_json``) e o ``media_type``. A recusa de conteúdo (S4)
        vira ``ConteudoRecusado``; **não grava consumo**, porque a recusa não cobra.
        """
        if not modelo:
            raise ModeloNaoEscolhido(
                "Nenhum modelo de imagem foi escolhido. Configure 'modelo_imagem' em /configuracao."
            )
        fornecedor, id_do_modelo = separar_fornecedor(modelo)
        if fornecedor != "openrouter":
            return self._gerar_em_outro_fornecedor(
                fornecedor, id_do_modelo, prompt, modelo, sem_filtro_de_seguranca, referencias
            )
        if sem_filtro_de_seguranca:
            raise ErroDoProvedorIA("Desligar o filtro de segurança só é permitido no Replicate.")  # F14
        modelo = id_do_modelo  # `openrouter:x` e `x` são o mesmo modelo
        if not self._chave_api:
            raise ChaveDeApiAusente(
                "Não há chave de API do OpenRouter configurada. Envie a sua no "
                "header X-Chave-API-OpenRouter ou defina a variável de ambiente "
                "CHAVE_API_OPENROUTER no servidor."
            )

        try:
            corpo: dict[str, object] = {"model": modelo, "prompt": prompt}
            if referencias is not None:
                # W4: `input_references` é uma lista de `{"type": "image_url", "image_url": {"url": <data URL>}}`.
                corpo[referencias.parametro] = [
                    {"type": "image_url", "image_url": {"url": imagem.como_data_url()}} for imagem in referencias.imagens
                ]
            dados = self._pedir("POST", "/images", json=corpo, autenticado=True)
        except ErroHttpDoProvedor as erro:
            motivo = _motivo_de_recusa(erro)
            if motivo is not None:
                raise ConteudoRecusado(motivo) from erro
            raise

        try:
            item = dados["data"][0]
            conteudo = base64.b64decode(item["b64_json"], validate=True)
            tipo = item.get("media_type") or "image/png"
        except (KeyError, IndexError, TypeError, ValueError, binascii.Error, AttributeError) as erro:
            raise ErroDoProvedorIA(f"O modelo {modelo} respondeu num formato inesperado.") from erro
        if not conteudo:
            raise ErroDoProvedorIA(f"O modelo {modelo} devolveu uma imagem vazia.")

        self._avisar_uso("imagem", modelo, dados)
        return ImagemGerada(conteudo=conteudo, tipo_de_midia=tipo, modelo=modelo)

    def _gerar_em_outro_fornecedor(
        self,
        fornecedor: str,
        id_do_modelo: str,
        prompt: str,
        modelo_completo: str,
        sem_filtro_de_seguranca: bool = False,
        referencias: ReferenciasParaGerar | None = None,
    ) -> ImagemGerada:
        """Gera a imagem no fal.ai ou no Replicate (F1 a F10). O fornecedor sem chave dá 422, dizendo qual variável falta."""
        if not id_do_modelo:
            raise ModeloNaoEscolhido(f"O modelo \"{modelo_completo}\" não diz qual modelo do {NOMES_DOS_FORNECEDORES[fornecedor]} usar.")
        gerador = self._geradores_de_imagem.get(fornecedor)
        if gerador is None:
            raise ChaveDeApiAusente(
                f"Não há chave do {NOMES_DOS_FORNECEDORES[fornecedor]}. Cadastre a sua em Configurações (o app a envia a cada chamada) "
                f"ou, no servidor do dono, defina {VARIAVEIS_DA_CHAVE[fornecedor]} no .env."
            )
        imagem = gerador.gerar(prompt, id_do_modelo, sem_filtro_de_seguranca, referencias)
        imagem.modelo = modelo_completo
        # F7: nenhum dos dois devolve o custo em dólares; o consumo é anotado com custo nulo, nunca um zero inventado.
        if self._ao_usar is not None:
            try:
                self._ao_usar(UsoDaChamada(operacao="imagem", modelo=modelo_completo, provedor=fornecedor))
            except Exception:  # noqa: BLE001 - métrica nunca derruba a chamada
                logging.getLogger(__name__).exception("Não foi possível anotar o consumo da chamada à IA.")
        return imagem

    def sugerir_perfil_renderizacao(
        self,
        titulo: str,
        autor: str | None,
        idioma: str | None,
        categoria_estilo: CategoriaEstilo | None,
        modelo: str,
    ) -> PerfilRenderizacaoSugerido:
        """Pede ao modelo um estilo visual, só com os metadados do livro.

        Única chamada desta classe que habilita o plugin de busca do
        OpenRouter (``usar_busca_web``) — é a única que não manda nenhum
        trecho do livro, então depender só do conhecimento do modelo teria
        mais chance de errar a obra.
        """
        pedido = (
            f"Título: {titulo}\n"
            f"Autor: {autor or '(não informado)'}\n"
            f"Idioma: {idioma or '(não informado)'}\n"
            f"CATEGORIA ESCOLHIDA: "
            f"{categoria_estilo.value if categoria_estilo else '(nenhuma — escolha você mesma)'}"
        )

        resposta = self._conversar(
            modelo, _INSTRUCAO_DE_PERFIL, pedido, operacao="perfil", usar_busca_web=True, esperar_json=True
        )
        bruto = _extrair_json(resposta)
        if bruto is None:
            raise ErroDoProvedorIA(
                "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
                "pequenos não seguem bem instruções de formato."
            )
        return PerfilRenderizacaoSugerido(
            estilo=_texto_ou_nulo(bruto.get("estilo")),
            artista_referencia=_texto_ou_nulo(bruto.get("artista_referencia")),
            iluminacao=_texto_ou_nulo(bruto.get("iluminacao")),
            paleta=_texto_ou_nulo(bruto.get("paleta")),
            formato=_texto_ou_nulo(bruto.get("formato")),
            categoria_estilo=_interpretar_categoria(
                bruto.get("categoria_estilo"), padrao=categoria_estilo
            ),
            # Ausente na resposta (modelo antigo, ou instrução ignorada) conta
            # como reconhecida — só vira False com o campo explícito, nunca
            # por omissão, para não gerar um falso aviso de "não reconheci".
            reconheceu_a_obra=bool(bruto.get("reconheceu_a_obra", True)),
            modelo=modelo,
        )

    # ----------------------------------------------------------------------- #
    # Funções internas
    # ----------------------------------------------------------------------- #

    def conferir_se_cabe(self, texto: str, contexto_do_modelo: int) -> None:
        """Levanta ``TextoLongoDemais`` se o texto não couber no modelo.

        Feito **antes** da chamada: descobrir isso pela recusa da API significaria
        ter gastado a chamada para nada.
        """
        conferir_se_cabe(texto, contexto_do_modelo)

    def _conversar(
        self,
        modelo: str,
        instrucao: str,
        pedido: str | PedidoComCapitulo,
        *,
        operacao: str,
        usar_busca_web: bool = False,
        temperatura: float | None = None,
        sessao_de_cache: str | None = None,
        alternativos: Sequence[str] = (),
        esperar_json: bool | None = None,
    ) -> str:
        """Faz uma chamada de conversa e devolve o texto da resposta.

        ``operacao`` diz qual passo do fluxo chamou (``extracao``, ``estado``...): vai junto do
        consumo informado ao ``ao_usar`` (item 4.3, "Custo das chamadas de IA"), e é a chave do
        **perfil da tarefa** (``tarefas.PERFIS``, item 4.10): temperatura, limite de saída e raciocínio.
        Uma ``temperatura`` explícita vence a do perfil.

        ``sessao_de_cache`` e ``alternativos`` são do 4.10 (LM2.5 e LM2.6): quem os usa passa, e quem não
        os usa continua como antes.

        A chamada **se defende** (4.10, E2): repete uma vez no erro de rede passageiro (LM5), tira os parâmetros opcionais
        que o modelo recusar (LM4), repete com mais espaço se a resposta foi cortada (LM6) e **anota o consumo de cada
        resposta recebida**, inclusive as repetições (LM7). ``esperar_json`` diz que o chamador vai ler JSON: resposta que
        não é JSON ganha uma segunda tentativa. Sem informar, vale ``True`` para as tarefas que têm esquema no perfil.

        ``usar_busca_web`` liga o plugin de busca do OpenRouter — o modelo
        pode consultar a internet antes de responder. Custa mais e só faz
        sentido quando não há texto do livro na própria chamada para o
        modelo se basear (``sugerir_perfil_renderizacao``); as demais
        operações desta classe nunca precisam disso.
        """
        if not modelo:
            raise ModeloNaoEscolhido(
                "Nenhum modelo foi escolhido. Configure um em /configuracao."
            )
        if not self._chave_api:
            raise ChaveDeApiAusente(
                "Não há chave de API do OpenRouter configurada. Envie a sua no "
                "header X-Chave-API-OpenRouter ou defina a variável de ambiente "
                "CHAVE_API_OPENROUTER no servidor."
            )

        perfil = perfil_da(operacao)
        if temperatura is not None:
            perfil = replace(perfil, temperatura=temperatura)
        capacidades = obter_capacidades(modelo)
        nao_aceitos = _parametros_recusados_por(modelo)
        corpo = _corpo_da_chamada(
            modelo,
            instrucao,
            _mensagem_do_usuario(modelo, pedido, com_cache=perfil.cache_do_capitulo and "cache_control" not in nao_aceitos),
            perfil,
            capacidades,
            sessao_de_cache=sessao_de_cache,
            # O reserva da configuração vai em toda chamada de texto; o corpo tira o repetido e o igual ao principal (LM2.6, LM13).
            alternativos=(*alternativos, *([self._modelo_reserva] if self._modelo_reserva else [])),
            usar_busca_web=usar_busca_web,
            nao_aceitos=nao_aceitos,
        )
        if esperar_json is None:
            esperar_json = perfil.esquema is not None

        dados, corpo = self._enviar_conversa(modelo, corpo)
        texto, motivo_do_fim = _ler_resposta(dados, modelo)
        self._avisar_uso(operacao, modelo, dados)

        if motivo_do_fim == "length":
            # A resposta foi cortada pelo limite: uma segunda tentativa com mais espaço. Nunca se devolve um JSON cortado (LM6).
            limite = corpo["max_tokens"]
            novo_limite = int(limite * FATOR_DO_LIMITE_NA_REPETICAO)
            if capacidades is not None and capacidades.saida_maxima:
                novo_limite = min(novo_limite, capacidades.saida_maxima)
            if novo_limite > limite:
                dados, corpo = self._enviar_conversa(modelo, {**corpo, "max_tokens": novo_limite})
                texto, motivo_do_fim = _ler_resposta(dados, modelo)
                self._avisar_uso(operacao, modelo, dados)
                limite = novo_limite
            if motivo_do_fim == "length":
                raise ErroDoProvedorIA(
                    f"A resposta do modelo {modelo} foi cortada por passar do limite de {limite} tokens. "
                    "Escolha outro modelo ou um capítulo menor."
                )
        elif esperar_json and _extrair_json(texto) is None:
            # Modelo que respondeu em prosa em vez de JSON: um pedido igual costuma dar certo. Só na segunda falha o chamador
            # levanta "O modelo não devolveu JSON" (LM6). As duas respostas foram pagas, então as duas são anotadas.
            dados, corpo = self._enviar_conversa(modelo, corpo)
            texto, motivo_do_fim = _ler_resposta(dados, modelo)
            self._avisar_uso(operacao, modelo, dados)
            if motivo_do_fim == "length":
                raise ErroDoProvedorIA(
                    f"A resposta do modelo {modelo} foi cortada por passar do limite de {corpo['max_tokens']} tokens. "
                    "Escolha outro modelo ou um capítulo menor."
                )

        return texto

    def _enviar_conversa(self, modelo: str, corpo: dict) -> tuple[dict, dict]:
        """Manda o pedido de conversa e devolve ``(resposta, corpo que de fato foi aceito)``.

        Cobre o caso do **parâmetro opcional que o modelo recusa** (LM4): o catálogo diz que o modelo aceita, mas o
        provedor responde 400, 404 ou 422 citando ``reasoning``, ``response_format`` etc. Em vez de derrubar a leitura, repete
        **uma vez** sem nenhum opcional e **memoriza** o que esse modelo recusou, para as próximas chamadas já o omitirem.
        Outros erros (401, 402, 403, 5xx, ou 4xx sem essas palavras) seguem como sempre: não são culpa de um opcional.
        """
        try:
            return self._pedir("POST", "/chat/completions", json=corpo, autenticado=True, tentar_de_novo=True), corpo
        except ErroHttpDoProvedor as erro:
            if erro.codigo not in CODIGOS_DE_PARAMETRO_RECUSADO:
                raise
            recusados = _parametros_citados_no_erro(corpo, erro.corpo)
            if not recusados:
                raise

        _memorizar_recusa(modelo, recusados)
        simples = _sem_parametros_opcionais(corpo)
        return self._pedir("POST", "/chat/completions", json=simples, autenticado=True, tentar_de_novo=True), simples

    def _avisar_uso(self, operacao: str, modelo: str, dados: dict) -> None:
        """Passa ao ``ao_usar`` o que a chamada consumiu. **Nunca derruba a chamada.**

        A resposta da IA já foi paga e está em mãos: se anotar o consumo falhar, perde-se uma linha de
        métrica, não o capítulo analisado. Por isso qualquer erro aqui só vai para o log.
        """
        if self._ao_usar is None:
            return
        try:
            self._ao_usar(_interpretar_uso(operacao, modelo, dados))
        except Exception:  # noqa: BLE001 - de propósito: métrica nunca derruba a chamada
            logging.getLogger(__name__).exception("Não foi possível anotar o consumo da chamada à IA.")

    def _pedir(
        self,
        metodo: str,
        caminho: str,
        json: dict | None = None,
        autenticado: bool = False,
        tentar_de_novo: bool = False,
    ) -> dict:
        """Faz a chamada HTTP, traduzindo qualquer falha em ``ErroDoProvedorIA``.

        Traduzir aqui é o que permite às rotas responderem com uma mensagem que dá
        para mostrar na tela, em vez de deixar escapar um erro de rede ou um JSON
        inesperado como erro 500.

        ``tentar_de_novo`` (LM5) repete **uma vez** a chamada que falhou por motivo passageiro: conexão que caiu
        (``Server disconnected``), servidor sobrecarregado (429, 500, 502, 503, 504). Só a conversa liga isto: a
        geração de imagem cobra por tentativa e tem o seu próprio tratamento.
        """
        cabecalhos = {}
        if autenticado:
            cabecalhos["Authorization"] = f"Bearer {self._chave_api}"

        tentativas = TENTATIVAS if tentar_de_novo else 1
        for numero in range(1, tentativas + 1):
            ainda_ha_tentativa = numero < tentativas
            try:
                resposta = self._cliente.request(
                    metodo, caminho, json=json, headers=cabecalhos
                )
            except httpx.HTTPError as erro:
                if ainda_ha_tentativa and isinstance(erro, ERROS_DE_REDE_QUE_SE_REPETEM):
                    self._dormir(ESPERA_ENTRE_TENTATIVAS)
                    continue
                if isinstance(erro, httpx.TimeoutException):
                    # Não se repete: já esperou o tempo todo (até 180 s), e dobrar seria esperar 6 minutos.
                    raise ErroDoProvedorIA(
                        "O OpenRouter não respondeu no tempo esperado. Modelos gratuitos "
                        "ficam em fila; vale tentar de novo."
                    ) from erro
                raise ErroDoProvedorIA(
                    f"Não foi possível falar com o OpenRouter: {erro}"
                ) from erro

            if ainda_ha_tentativa and resposta.status_code in STATUS_QUE_SE_REPETEM:
                self._dormir(_espera_antes_de_repetir(resposta))
                continue
            break

        if resposta.status_code == 401:
            raise ChaveDeApiAusente(
                "O OpenRouter recusou a chave de API. Verifique se ela está certa."
            )
        if resposta.status_code >= 400:
            raise ErroHttpDoProvedor(
                resposta.status_code,
                resposta.text,
                f"O OpenRouter respondeu {resposta.status_code}: {_resumir(resposta.text)}",
            )

        try:
            return resposta.json()
        except ValueError as erro:
            raise ErroDoProvedorIA(
                "O OpenRouter respondeu algo que não é JSON."
            ) from erro

    def _pedir_audio(self, corpo: dict) -> tuple[bytes, httpx.Headers]:
        """``POST /audio/speech``: devolve os bytes do áudio e os cabeçalhos, traduzindo qualquer falha em ``ErroDoProvedorIA``.

        A resposta é o **áudio cru**, não JSON; já os erros (status 400 ou mais) vêm em JSON."""
        try:
            resposta = self._cliente.post("/audio/speech", json=corpo, headers={"Authorization": f"Bearer {self._chave_api}"})
        except httpx.TimeoutException as erro:
            raise ErroDoProvedorIA("O OpenRouter não respondeu no tempo esperado ao narrar um trecho.") from erro
        except httpx.HTTPError as erro:
            raise ErroDoProvedorIA(f"Não foi possível falar com o OpenRouter: {erro}") from erro

        if resposta.status_code == 401:
            raise ChaveDeApiAusente("O OpenRouter recusou a chave de API. Verifique se ela está certa.")
        if resposta.status_code == 402:
            raise ErroHttpDoProvedor(402, resposta.text, "O OpenRouter recusou por falta de saldo (402). Adicione créditos ou escolha um modelo gratuito.")
        if resposta.status_code >= 400:
            detalhe = _resumir(resposta.text)
            if "voice" in resposta.text.lower():
                detalhe = f"{detalhe} — este modelo pode exigir uma voz (ou não ter a que foi escolhida): confira em Configurações → Narração."
            raise ErroHttpDoProvedor(resposta.status_code, resposta.text, f"O OpenRouter respondeu {resposta.status_code}: {detalhe}")
        if not resposta.content or "json" in resposta.headers.get("content-type", ""):
            raise ErroDoProvedorIA("O OpenRouter não devolveu um áudio para este trecho.")
        return resposta.content, resposta.headers


def _mensagem_do_usuario(modelo: str, pedido: str | PedidoComCapitulo, *, com_cache: bool) -> str | list[dict]:
    """O ``content`` da mensagem do usuário (LM9).

    - ``str``: como veio.
    - ``PedidoComCapitulo``: o capítulo **antes** do que varia. Modelos ``anthropic/...`` precisam de um bloco marcado com
      ``cache_control`` (o cache deles é explícito; a documentação do OpenRouter indica "book chapters" como o uso certo) e recebem uma
      **lista de dois blocos**, com **um** ponto de cache no fim do capítulo. Os demais (OpenAI, DeepSeek, Gemini) cacheiam sozinhos o
      prefixo: recebem um texto único.
    """
    if isinstance(pedido, str):
        return pedido
    abertura = f"TEXTO DO CAPÍTULO:\n{pedido.capitulo}{RODAPE_DO_CAPITULO}"
    if com_cache and modelo.startswith("anthropic/"):
        return [
            {"type": "text", "text": abertura, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": pedido.variavel},
        ]
    return abertura + pedido.variavel


def _sessao_de_cache(id_do_capitulo: int | None, texto: str) -> str | None:
    """A chave de cache das leituras de um capítulo (LM11), ou ``None`` sem id.

    Muda quando o texto do capítulo muda (a leitura nova não pode herdar o cache da velha). A chave **padrão** do OpenRouter é um hash
    da primeira mensagem do usuário, que aqui varia a cada elemento: fixar a sessão é o que faz as leituras do capítulo se acharem."""
    if id_do_capitulo is None:
        return None
    return f"cap-{id_do_capitulo}-{hashlib.sha1(texto.encode()).hexdigest()[:10]}"


FOLGA_DE_RACIOCINIO = 4000
"""Tokens somados ao ``max_tokens`` quando o modelo vai raciocinar (LM3).

Na maioria dos provedores os tokens de raciocínio saem do **mesmo** teto da resposta. Sem folga, o modelo "pensaria" até o limite e
devolveria uma resposta vazia."""

MAXIMO_DE_ALTERNATIVOS = 2
"""Quantos modelos reserva o OpenRouter recebe no campo ``models`` (LM2.6)."""

TAMANHO_MAXIMO_DA_SESSAO = 256
"""O ``session_id`` do OpenRouter aceita até 256 caracteres (LM2.5)."""

ESFORCO_MINIMO_PADRAO = "low"
"""O esforço que se manda quando o raciocínio é obrigatório e o catálogo não lista os esforços aceitos. É o mais aceito pelos modelos."""


TENTATIVAS = 2
"""Quantas vezes a conversa é tentada no erro de rede passageiro: a original e **uma** repetição (LM5)."""

ESPERA_ENTRE_TENTATIVAS = 2.0
"""Segundos de espera antes da repetição (LM5)."""

ESPERA_MAXIMA_DO_RETRY_AFTER = 10.0
"""Num 429 o OpenRouter pode pedir uma espera (``Retry-After``); acima disto o servidor não espera (LM5)."""

ERROS_DE_REDE_QUE_SE_REPETEM = (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.ConnectTimeout)
"""A conexão caiu ou não chegou a abrir (o ``Server disconnected`` do ``claude-haiku-4.5``). **Fora** daqui, de propósito, o
``ReadTimeout``: o servidor já esperou até ``TEMPO_LIMITE`` e dobrar a espera seria 6 minutos (LM5)."""

STATUS_QUE_SE_REPETEM = frozenset({429, 500, 502, 503, 504})
"""Falhas do lado do provedor que costumam passar sozinhas. 401 e 402 (chave e saldo) e os outros 4xx nunca se repetem (LM5)."""

FATOR_DO_LIMITE_NA_REPETICAO = 1.5
"""Resposta cortada por ``finish_reason = length``: a repetição ganha 50% a mais de espaço (LM6)."""

CODIGOS_DE_PARAMETRO_RECUSADO = frozenset({400, 404, 422})
"""Os códigos com que um provedor costuma recusar um parâmetro que não conhece (LM4)."""

_PALAVRAS_DE_PARAMETRO_OPCIONAL = {
    "reasoning": "reasoning",
    "response_format": "response_format",
    "json_schema": "response_format",
    "structured": "response_format",
    "require_parameters": "response_format",
    "session_id": "session_id",
    "cache_control": "cache_control",
}
"""Palavra que aparece na mensagem de erro -> o parâmetro opcional a que ela se refere (LM4). ``provider`` vai junto de ``response_format``."""

_PARAMETROS_OPCIONAIS = ("reasoning", "response_format", "session_id", "models", "cache_control")
"""Os parâmetros opcionais da conversa (LM4): os que o catálogo diz que o modelo aceita, mas o provedor pode recusar."""

_NAO_ACEITA: dict[str, set[str]] = {}
_trava_do_nao_aceita = threading.Lock()
"""Por modelo, os parâmetros opcionais que o provedor já recusou (LM4). Vive no módulo, e não no provedor: o provedor é
criado a cada pedido, e o que um modelo recusa hoje ele recusa no próximo."""


def limpar_parametros_recusados() -> None:
    """Esquece o que os modelos recusaram. Os testes chamam isto para um teste não herdar a memória do outro."""
    with _trava_do_nao_aceita:
        _NAO_ACEITA.clear()


def _parametros_recusados_por(modelo: str) -> frozenset[str]:
    with _trava_do_nao_aceita:
        return frozenset(_NAO_ACEITA.get(modelo, ()))


def _memorizar_recusa(modelo: str, parametros: Collection[str]) -> None:
    """Guarda que ``modelo`` recusou ``parametros`` e avisa no log **uma vez** por (modelo, parâmetro)."""
    with _trava_do_nao_aceita:
        ja_sabidos = _NAO_ACEITA.setdefault(modelo, set())
        novos = sorted(set(parametros) - ja_sabidos)
        ja_sabidos.update(novos)
    for parametro in novos:
        logging.getLogger(__name__).warning(
            "O modelo %s recusou o parâmetro opcional %r; as próximas chamadas já o omitem.", modelo, parametro
        )


def _opcionais_presentes(corpo: dict) -> set[str]:
    """Quais parâmetros opcionais este corpo leva."""
    presentes = {p for p in ("reasoning", "response_format", "session_id", "models") if p in corpo}
    for mensagem in corpo.get("messages", []):
        conteudo = mensagem.get("content")
        if isinstance(conteudo, list) and any(isinstance(b, dict) and "cache_control" in b for b in conteudo):
            presentes.add("cache_control")
    return presentes


def _parametros_citados_no_erro(corpo: dict, texto_do_erro: str) -> set[str]:
    """Os parâmetros opcionais do ``corpo`` a que o erro se refere; **vazio** se o erro não é de parâmetro opcional (LM4).

    O erro é de parâmetro se o texto (em minúsculas) tem alguma das palavras de ``_PALAVRAS_DE_PARAMETRO_OPCIONAL`` ou
    ``no endpoints found`` (o ``require_parameters`` sem nenhum provedor que aceite tudo). Se ele nomeia o parâmetro, é esse; se
    não nomeia (o ``no endpoints found``), valem todos os opcionais que o corpo levava.
    """
    presentes = _opcionais_presentes(corpo)
    if not presentes:
        return set()
    texto = texto_do_erro.lower()
    citados = {parametro for palavra, parametro in _PALAVRAS_DE_PARAMETRO_OPCIONAL.items() if palavra in texto}
    if not citados and "no endpoints found" not in texto:
        return set()
    return (citados & presentes) or presentes


def _sem_parametros_opcionais(corpo: dict) -> dict:
    """O corpo só com o essencial: ``model``, ``messages``, ``usage``, ``temperature`` e ``max_tokens`` (e a busca na web, se pedida).

    O ``cache_control`` sai de dentro dos blocos da mensagem; o texto deles fica."""
    simples = {c: v for c, v in corpo.items() if c not in ("reasoning", "response_format", "provider", "session_id", "models")}
    simples["messages"] = [
        {
            **mensagem,
            "content": [{c: v for c, v in bloco.items() if c != "cache_control"} for bloco in mensagem["content"]]
            if isinstance(mensagem.get("content"), list)
            else mensagem.get("content"),
        }
        for mensagem in corpo["messages"]
    ]
    return simples


def _ler_resposta(dados: dict, modelo: str) -> tuple[str, str | None]:
    """O texto da resposta e o ``finish_reason`` (``stop``, ``length``...; ``None`` se o provedor não disse)."""
    try:
        escolha = dados["choices"][0]
        texto = escolha["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as erro:
        raise ErroDoProvedorIA(f"O modelo {modelo} respondeu num formato inesperado.") from erro
    motivo = escolha.get("finish_reason")
    return texto, motivo if isinstance(motivo, str) else None


def _espera_antes_de_repetir(resposta: httpx.Response) -> float:
    """Quantos segundos esperar antes de repetir. No 429 vale o ``Retry-After`` do provedor, limitado a 10 s (LM5)."""
    if resposta.status_code == 429:
        try:
            segundos = float(resposta.headers.get("Retry-After"))
        except (TypeError, ValueError):
            return ESPERA_ENTRE_TENTATIVAS
        return min(max(segundos, 0.0), ESPERA_MAXIMA_DO_RETRY_AFTER)
    return ESPERA_ENTRE_TENTATIVAS


def _esforco_de_raciocinio(nivel: NivelDeRaciocinio, capacidades: Capacidades) -> str | None:
    """O ``reasoning.effort`` que a chamada deve levar, ou ``None`` se o modelo não tem raciocínio (nenhum campo, LM2.3).

    Pede-se um nível, mas **o modelo manda no que aceita**:

    - ``NENHUM``: desliga o raciocínio (``none``) se o modelo deixa; se ele é obrigatório, o **menor** esforço que o catálogo lista.
    - os outros: o esforço pedido, se o modelo o aceita (ou se o catálogo não diz quais aceita); senão o **mais próximo acima**; e,
      se não há nenhum acima, o mais alto que ele tem.
    """
    if not capacidades.raciocinio_suportado:
        return None

    aceitos = [e for e in ORDEM_DOS_ESFORCOS if e in capacidades.esforcos]

    if nivel is NivelDeRaciocinio.NENHUM:
        if not capacidades.raciocinio_obrigatorio:
            return "none"
        return aceitos[0] if aceitos else ESFORCO_MINIMO_PADRAO

    if not aceitos or nivel.value in aceitos:
        return nivel.value
    acima = [e for e in aceitos if ORDEM_DOS_ESFORCOS.index(e) > ORDEM_DOS_ESFORCOS.index(nivel.value)]
    return acima[0] if acima else aceitos[-1]


def _corpo_da_chamada(
    modelo: str,
    instrucao: str,
    pedido: str | list[dict],
    perfil: PerfilDaTarefa,
    capacidades: Capacidades | None,
    *,
    sessao_de_cache: str | None = None,
    alternativos: Sequence[str] = (),
    usar_busca_web: bool = False,
    esquemas: Mapping[str, dict] | None = None,
    nao_aceitos: Collection[str] = (),
) -> dict:
    """Monta o corpo do ``POST /chat/completions`` (LM2). Função **pura**: sem rede, para testar sem transporte.

    O que vai, em ordem: ``model``, ``messages``, ``usage``, ``temperature``, ``max_tokens`` (com a folga do raciocínio, LM3),
    ``reasoning``, ``response_format`` (com ``provider.require_parameters``), ``session_id``, ``models`` e ``plugins``. Cada parâmetro
    opcional só entra se o **catálogo diz que o modelo o aceita**: mandar um que ele não conhece é a forma de derrubar a leitura.

    Sem ``capacidades`` (catálogo fora do ar ou modelo desconhecido) o corpo é o **mínimo**: nada opcional, só o limite de saída do
    perfil. A busca na web (``plugins``) fica, porque não depende do catálogo: é o que a tarefa pediu.
    """
    corpo: dict = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": instrucao},
            {"role": "user", "content": pedido},
        ],
        # Pede o bloco "usage" completo, com o custo em dólares (item 4.3).
        "usage": {"include": True},
    }
    if perfil.temperatura is not None:
        corpo["temperature"] = perfil.temperatura

    limite = perfil.limite_de_saida
    esforco = None
    if capacidades is not None and "reasoning" not in nao_aceitos:
        esforco = _esforco_de_raciocinio(perfil.raciocinio, capacidades)
    if esforco is not None and esforco != "none":
        limite += FOLGA_DE_RACIOCINIO
    if capacidades is not None and capacidades.saida_maxima:
        limite = min(limite, capacidades.saida_maxima)
    corpo["max_tokens"] = limite

    if esforco is not None:
        corpo["reasoning"] = {"effort": esforco, "exclude": True}  # o servidor nunca usa o texto do raciocínio

    if capacidades is not None:
        esquema = (esquemas if esquemas is not None else esquemas_json.ESQUEMAS).get(perfil.esquema or "")
        if esquema is not None and capacidades.estruturado and "response_format" not in nao_aceitos:
            corpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": perfil.esquema, "strict": True, "schema": esquema},
            }
            # Sem isto o roteamento poderia escolher um provedor que ignora o esquema.
            corpo["provider"] = {"require_parameters": True}

        if sessao_de_cache and "session_id" not in nao_aceitos:
            corpo["session_id"] = sessao_de_cache[:TAMANHO_MAXIMO_DA_SESSAO]

        reservas = [m for m in dict.fromkeys(alternativos) if m and m != modelo][:MAXIMO_DE_ALTERNATIVOS]
        if reservas and "models" not in nao_aceitos:
            corpo["models"] = [modelo, *reservas]

    if usar_busca_web:
        corpo["plugins"] = [{"id": "web"}]
    return corpo


def estimar_tokens(texto: str) -> int:
    """Estima quantos tokens um texto ocupa.

    Estimativa e não contagem: contar de verdade exigiria o tokenizador de cada
    modelo, e a decisão que isto alimenta — "cabe ou não cabe" — tem folga
    suficiente para não depender dessa precisão.
    """
    return len(texto) // CARACTERES_POR_TOKEN


def conferir_se_cabe(texto: str, contexto_do_modelo: int) -> None:
    """Levanta ``TextoLongoDemais`` se o texto não couber no modelo.

    Função livre, e não só método de ``ProvedorOpenRouter``, porque a rota que
    processa um capítulo (item 6.7) precisa da mesma checagem antes de chamar
    **qualquer** provedor, inclusive o falso dos testes — a estimativa não depende
    de nenhum detalhe de um fornecedor específico.
    """
    if contexto_do_modelo <= 0:
        return

    estimados = estimar_tokens(texto)
    if estimados + FOLGA_DE_TOKENS > contexto_do_modelo:
        raise TextoLongoDemais(
            f"O texto tem cerca de {estimados} tokens e o modelo aceita "
            f"{contexto_do_modelo}. Escolha um modelo com janela de contexto "
            f"maior — dos modelos gratuitos, todos os testados aceitam pelo "
            f"menos 32 mil."
        )


def _e_modelo_de_texto(bruto: dict) -> bool:
    """Descarta modelos de imagem, áudio e música.

    O critério é a **saída**: um modelo serve aqui se produz texto e nada além de
    texto. A entrada pode incluir imagem ou vídeo sem problema — um modelo
    multimodal continua sabendo ler um capítulo.

    Olhar só para "produz texto" não basta, e isso apareceu numa chamada real:
    ``google/lyria-3-pro-preview`` é um modelo de música que declara
    ``output_modalities: ["text", "audio"]``. Ele produz texto, mas não é o que se
    quer numa lista de onde escolher quem vai ler um capítulo de livro.

    Um modelo que produz texto **e** imagem também fica de fora. Se algum dia
    fizer sentido usar um deles, o id pode ser cadastrado direto em
    ``/configuracao`` — o filtro governa a lista de escolha, não o que é aceito.
    """
    arquitetura = bruto.get("architecture") or {}
    saidas = set(arquitetura.get("output_modalities") or [])

    # Sem a informação, assume que é de texto. Medido na resposta real: os 458
    # modelos declaram modalidades, então este caminho não é exercitado hoje.
    # Fica como proteção: se o campo desaparecer da API, é melhor a lista vir
    # completa demais do que vazia, que deixaria o usuário sem como configurar.
    if not saidas:
        return True

    return saidas == {"text"}


def _e_gratuito(bruto: dict) -> bool:
    """Um modelo é gratuito quando o preço do prompt é zero."""
    preco = (bruto.get("pricing") or {}).get("prompt")
    try:
        return float(preco) == 0.0
    except (TypeError, ValueError):
        return False


def _suporta_json(bruto: dict) -> bool:
    """Se o modelo aceita resposta estruturada/JSON (item 4.3).

    ``supported_parameters`` é a lista de parâmetros que o modelo aceita na
    chamada; ``response_format``/``structured_outputs`` são os dois nomes
    usados pelo OpenRouter para essa capacidade, confirmados ao vivo contra
    o `/models` antes de implementar este filtro.
    """
    suportados = set((bruto.get("supported_parameters") or []))
    return bool(suportados & {"response_format", "structured_outputs"})


def _interpretar_uso(operacao: str, modelo: str, dados: dict) -> UsoDaChamada:
    """Lê o bloco ``usage`` da resposta. Campo ausente ou estranho vira ``None``, nunca erro nem zero."""
    uso = dados.get("usage") if isinstance(dados.get("usage"), dict) else {}

    def inteiro(chave: str) -> int | None:
        valor = uso.get(chave)
        return valor if isinstance(valor, int) and not isinstance(valor, bool) else None

    custo = None
    bruto_custo = uso.get("cost")
    if isinstance(bruto_custo, (int, float, str)) and not isinstance(bruto_custo, bool):
        try:
            custo = Decimal(str(bruto_custo))
        except InvalidOperation:
            custo = None

    def inteiro_de(grupo: str, chave: str) -> int | None:
        detalhes = uso.get(grupo)
        valor = detalhes.get(chave) if isinstance(detalhes, dict) else None
        return valor if isinstance(valor, int) and not isinstance(valor, bool) else None

    id_da_geracao = dados.get("id")
    # O modelo que **respondeu** pode ser outro: com ``models`` (LM2.6) o OpenRouter tenta a alternativa e cobra o dela (LM7).
    modelo_que_respondeu = dados.get("model")
    return UsoDaChamada(
        operacao=operacao,
        modelo=modelo_que_respondeu if isinstance(modelo_que_respondeu, str) and modelo_que_respondeu else modelo,
        tokens_entrada=inteiro("prompt_tokens"),
        tokens_saida=inteiro("completion_tokens"),
        custo=custo,
        id_da_geracao=id_da_geracao if isinstance(id_da_geracao, str) else None,
        tokens_em_cache=inteiro_de("prompt_tokens_details", "cached_tokens"),
        tokens_de_raciocinio=inteiro_de("completion_tokens_details", "reasoning_tokens"),
    )


def _custo_de_saida(bruto: dict) -> float:
    """Preço por token de saída (``pricing.completion``, item 4.3)."""
    preco = (bruto.get("pricing") or {}).get("completion")
    try:
        return float(preco)
    except (TypeError, ValueError):
        return 0.0


def _numero_ou_nulo(valor: object) -> float | None:
    """O número em ``valor`` (que o OpenRouter manda como texto), ou ``None`` se não é número."""
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _e_moderado(bruto: dict) -> bool:
    """Se o modelo é moderado pelo provedor (``top_provider.is_moderated``, item 4.3)."""
    return bool((bruto.get("top_provider") or {}).get("is_moderated"))


def _interpretar_elementos(bruto: dict) -> list[ElementoSugerido]:
    """Lê a lista de elementos de dentro do JSON já interpretado.

    Elementos com tipo desconhecido ou sem nome são descartados em silêncio — é
    sugestão, e uma entrada malformada não deveria derrubar as outras vinte.
    """
    sugeridos = []
    for entrada in bruto.get("elementos") or []:
        if not isinstance(entrada, dict):
            continue
        nome = (entrada.get("nome") or "").strip()
        if not nome:
            continue
        try:
            tipo = TipoElemento[(entrada.get("tipo") or "").strip().upper()]
        except KeyError:
            continue

        sugeridos.append(
            ElementoSugerido(
                tipo=tipo,
                nome=nome,
                descricao=_texto_ou_nulo(entrada.get("descricao")),
                manter_estado_atual=bool(entrada.get("manter_estado_atual")),
            )
        )

    return sugeridos


def _interpretar_cenas_sugeridas(bruto: dict) -> list[CenaSugerida]:
    """Lê a lista de cenas sugeridas de dentro do JSON já interpretado.

    Cada uma vira uma ``CenaSugerida``. Mesma tolerância de
    ``_interpretar_elementos``: uma entrada malformada, ou sem nenhum
    participante, é descartada em silêncio em vez de derrubar as outras.
    """
    sugeridos = []
    for entrada in bruto.get("cenas") or []:
        if not isinstance(entrada, dict):
            continue
        titulo = (entrada.get("titulo") or "").strip()
        if not titulo:
            continue

        participantes = []
        for participante in entrada.get("participantes") or []:
            if not isinstance(participante, dict):
                continue
            nome = (participante.get("nome") or "").strip()
            if not nome:
                continue
            try:
                tipo = TipoElemento[(participante.get("tipo") or "").strip().upper()]
            except KeyError:
                continue
            participantes.append(ParticipanteSugerido(tipo=tipo, nome=nome))

        if not participantes:
            continue

        sugeridos.append(
            CenaSugerida(
                titulo=titulo,
                descricao=_texto_ou_nulo(entrada.get("descricao")),
                horario=_texto_ou_nulo(entrada.get("horario")),
                clima=_texto_ou_nulo(entrada.get("clima")),
                humor=_texto_ou_nulo(entrada.get("humor")),
                participantes=participantes,
                trecho_ancora=_texto_ou_nulo(entrada.get("trecho_ancora")),
                trecho=_texto_ou_nulo(entrada.get("trecho")),
            )
        )

    return sugeridos


def _interpretar_estado(resposta: str) -> str:
    """Lê o JSON da leitura profunda de um elemento (fase 2, item 4.4).

    Mesma leitura tolerante de ``_interpretar_elementos``: tira cerca de
    markdown e procura o primeiro objeto JSON do texto.
    """
    bruto = _extrair_json(resposta)
    if bruto is None:
        raise ErroDoProvedorIA(
            "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
            "pequenos não seguem bem instruções de formato."
        )

    aparencia_fixa = _texto_ou_nulo(bruto.get("aparencia_fixa"))
    instante = _texto_ou_nulo(bruto.get("instante"))
    ambiente = _texto_ou_nulo(bruto.get("ambiente"))
    if aparencia_fixa is None and instante is None:
        # Resposta no formato antigo (um campo só): ainda vale, para não perder o que o modelo escreveu.
        descricao = _texto_ou_nulo(bruto.get("descricao"))
        if descricao is None:
            raise ErroDoProvedorIA(
                "O modelo devolveu um JSON sem os campos 'aparencia_fixa' e 'instante'."
            )
        return descricao if ambiente is None else f"{descricao}\n{ROTULO_DO_AMBIENTE} {ambiente}"

    linhas = []
    if aparencia_fixa:
        linhas.append(f"{ROTULO_DA_APARENCIA_FIXA} {aparencia_fixa}")
    if instante:
        linhas.append(f"{ROTULO_DO_INSTANTE} {instante}")
    if ambiente:
        linhas.append(f"{ROTULO_DO_AMBIENTE} {ambiente}")
    return "\n".join(linhas)


def _interpretar_identidade(resposta: str) -> str | None:
    """Lê o JSON da leitura profunda de identidade (fase 2b, item 4.4).

    Diferente de ``_interpretar_estado``, ``None`` aqui é uma resposta válida
    e comum — significa "nada de novo neste capítulo", não uma falha.
    """
    bruto = _extrair_json(resposta)
    if bruto is None:
        raise ErroDoProvedorIA(
            "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
            "pequenos não seguem bem instruções de formato."
        )
    return _texto_ou_nulo(bruto.get("descricao"))


def _interpretar_contexto(resposta: str) -> str:
    """Lê o JSON da fundamentação de um frame do tipo CENA (item 4.4).

    Mesma leitura tolerante das demais interpretações desta camada.
    """
    bruto = _extrair_json(resposta)
    if bruto is None:
        raise ErroDoProvedorIA(
            "O modelo não devolveu JSON. Tente outro modelo: alguns modelos "
            "pequenos não seguem bem instruções de formato."
        )

    contexto = _texto_ou_nulo(bruto.get("contexto"))
    if contexto is None:
        raise ErroDoProvedorIA(
            "O modelo devolveu um JSON sem o campo 'contexto'."
        )
    return contexto


TENTATIVAS_DA_SUAVIZACAO = 2
"""Quantas vezes se pede a suavização se o modelo não apontar trocas válidas: a primeira e mais uma."""

TAMANHO_MAXIMO_DE_UMA_TROCA = 200
"""O maior trecho (em caracteres) que uma troca pode substituir: trocar uma frase inteira, ou o prompt todo, não é suavizar."""

FRACAO_MAXIMA_TROCADA = 0.5
"""No máximo metade do texto pode ser trocada: acima disso o modelo reescreveu o prompt, em vez de suavizá-lo."""


CONTRADICOES_CONHECIDAS = (
    (
        re.compile(r"\b(ponytail|tied|braid|braided|bun|pulled back|secured|bound)\b", re.I),
        re.compile(
            r"hair[^,.;]{0,30}\b(falling|cascading|flowing|draped|spilling)\b[^,.;]{0,25}"
            r"\b(over|across|around)\b[^,.;]{0,15}\b(body|torso|chest|breasts?)\b",
            re.I,
        ),
        "o cabelo está preso no prompt e a troca o faz cair sobre o corpo (cubra com sombra, enquadramento ou o braço)",
    ),
    (
        re.compile(r"\barms? (raised|up|overhead|stretched up)\b|\braised arms\b", re.I),
        re.compile(r"\barms? (crossed|folded)\b|\bcrossed arms\b|\b(one|an) arm across\b", re.I),
        "os braços estão levantados no prompt e a troca os cruza (cubra com sombra ou enquadramento)",
    ),
)
"""Pares (o que o prompt original diz, o que a troca não pode dizer, o motivo) que os modelos de suavização violaram
em testes reais (02/10/2026): cobrir uma pessoa de cabelo preso com "cabelo caindo sobre o corpo", ou cruzar braços já
levantados. É uma rede de segurança fácil de estender; a regra geral (não contradizer o prompt) está na instrução."""


def _aplicar_trocas(texto: str, resposta: str) -> tuple[str | None, str | None]:
    """Aplica ao ``texto`` as trocas que o modelo apontou. Devolve ``(texto novo, None)`` ou ``(None, motivo)``.

    Cada troca é ``{"trecho": ..., "novo": ...}``. Serve se: há pelo menos uma; todo ``trecho`` existe **literalmente** no
    texto; ``trecho`` e ``novo`` não são vazios nem iguais; nenhuma troca passa de ``TAMANHO_MAXIMO_DE_UMA_TROCA``;
    duas trocas não se sobrepõem; o total trocado não passa de ``FRACAO_MAXIMA_TROCADA`` do texto; e nenhum ``novo`` cai
    em ``CONTRADICOES_CONHECIDAS``. O que fica fora das trocas é copiado **sem alteração**. O ``motivo`` só vem quando
    há algo a dizer ao modelo na nova tentativa (hoje, as contradições); nos outros casos é ``None``.
    """
    dado = _extrair_json(resposta)
    trocas = dado.get("trocas") if dado else None
    if not isinstance(trocas, list) or not trocas:
        return None, None

    achadas: list[tuple[int, int, str]] = []  # (início, fim, novo)
    for troca in trocas:
        if not isinstance(troca, dict):
            return None, None
        trecho, novo = troca.get("trecho"), troca.get("novo")
        if not (isinstance(trecho, str) and isinstance(novo, str)):
            return None, None
        trecho, novo = trecho.strip(), novo.strip()
        if not trecho or not novo or trecho == novo or len(trecho) > TAMANHO_MAXIMO_DE_UMA_TROCA:
            return None, None
        inicio = texto.find(trecho)
        if inicio == -1:
            return None, None
        for no_original, no_novo, motivo in CONTRADICOES_CONHECIDAS:
            if no_original.search(texto) and no_novo.search(novo):
                return None, motivo
        achadas.append((inicio, inicio + len(trecho), novo))

    achadas.sort()
    for (_, fim_anterior, _), (inicio_seguinte, _, _) in zip(achadas, achadas[1:]):
        if inicio_seguinte < fim_anterior:
            return None, None  # duas trocas no mesmo pedaço
    if sum(fim - inicio for inicio, fim, _ in achadas) > len(texto) * FRACAO_MAXIMA_TROCADA:
        return None, None

    pedacos: list[str] = []
    cursor = 0
    for inicio, fim, novo in achadas:
        pedacos.append(texto[cursor:inicio])
        pedacos.append(novo)
        cursor = fim
    pedacos.append(texto[cursor:])
    return "".join(pedacos), None


def _extrair_json(resposta: str) -> dict | None:
    """Acha o objeto JSON dentro da resposta do modelo."""
    limpo = re.sub(r"^\s*```(?:json)?|```\s*$", "", resposta.strip(), flags=re.MULTILINE)

    try:
        carregado = json.loads(limpo)
    except ValueError:
        inicio, fim = limpo.find("{"), limpo.rfind("}")
        if inicio == -1 or fim <= inicio:
            return None
        try:
            carregado = json.loads(limpo[inicio : fim + 1])
        except ValueError:
            return None

    return carregado if isinstance(carregado, dict) else None


_PALAVRAS_DE_NULO = {"nulo", "null", "none", "n/a", "não informado", "nao informado"}
"""Palavras que alguns modelos escrevem como texto em vez de usar `null` de
verdade no JSON — achado testando `sugerir_perfil_renderizacao` com
`perplexity/sonar-pro`, que devolveu `"artista_referencia": "nulo"` como
string. Sem isso, esse texto vazaria como se fosse um valor real."""


def _texto_ou_nulo(valor) -> str | None:
    """Normaliza um campo de texto opcional vindo do modelo."""
    if not isinstance(valor, str):
        return None
    limpo = valor.strip()
    if not limpo or limpo.lower() in _PALAVRAS_DE_NULO:
        return None
    return limpo


def _interpretar_categoria(
    valor, *, padrao: CategoriaEstilo | None
) -> CategoriaEstilo | None:
    """Lê a categoria de estilo devolvida pelo modelo.

    Se o modelo devolver um identificador que não bate com nenhuma categoria
    conhecida (ou não devolver nada), cai no que foi pedido (``padrao``) — que
    é a própria categoria escolhida pelo usuário, quando houve uma. Só fica
    ``None`` de fato quando ninguém, nem o usuário nem o modelo, escolheu uma.
    """
    if isinstance(valor, str):
        try:
            return CategoriaEstilo[valor.strip().upper()]
        except KeyError:
            pass
    return padrao


def _resumir(texto: str, limite: int = 200) -> str:
    """Encurta o corpo de uma resposta de erro para caber numa mensagem."""
    achatado = " ".join(texto.split())
    return achatado if len(achatado) <= limite else achatado[:limite] + "…"
