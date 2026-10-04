"""Os 10 perfis de renderização de fábrica (PF1 a PF6 — item 4.5 da especificação).

**Por que existem.** A pessoa não deve montar a técnica de um estilo: ela escolhe o perfil ("Anime") e pronto. Cada perfil de
fábrica já vem com o ``estilo``, a ``iluminacao`` e a ``paleta`` **escritos para combinar com a categoria**, e a categoria
escolhe o bloco técnico em inglês (``imagineer/ia/blocos_tecnicos.py``) que o servidor cola ao fim do prompt. Como ninguém
digita nada, o texto do perfil nunca contradiz o bloco (o problema do teste C de 04/10/2026).

**Por que a função é idempotente e usa SQL "cru".** Ela é chamada pela migração (que não pode depender dos modelos de hoje:
eles mudam, a migração é fotografia de um momento) e pelos testes (que criam as tabelas sem migração). Cria o que falta e
**reescreve os textos** dos perfis de fábrica, que são travados (a API recusa editá-los) e por isso nunca foram mexidos à mão.
Mudar um texto daqui depois é escrever uma migração de uma linha que a chama de novo.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from imagineer.modelos import CategoriaEstilo


@dataclass(frozen=True)
class PerfilDeFabrica:
    """Um perfil pronto, com tudo o que o prompt precisa saber do estilo (a técnica fica no bloco da categoria)."""

    nome: str
    categoria: CategoriaEstilo
    estilo: str
    iluminacao: str
    paleta: str


PERFIS_DE_FABRICA: tuple[PerfilDeFabrica, ...] = (
    PerfilDeFabrica(
        nome="Fotorrealista cinematográfico",
        categoria=CategoriaEstilo.FOTORREALISTA_CINEMATOGRAFICO,
        estilo="still de cinema realista: fotografia em película com grão fino, profundidade de campo rasa e textura natural de pele e tecido",
        iluminacao="luz motivada e direcional, contraste suave, queda de luz realista e leve névoa atmosférica",
        paleta="cores naturais e contidas, com correção de cor de filme: sombras levemente frias e tons de pele quentes",
    ),
    PerfilDeFabrica(
        nome="Pintura a óleo",
        categoria=CategoriaEstilo.PINTURA_A_OLEO,
        estilo="pintura a óleo clássica sobre tela: pinceladas grossas e visíveis, empasto com relevo de tinta e modelado em claro-escuro",
        iluminacao="claro-escuro dramático, luz lateral quente e sombras profundas e translúcidas",
        paleta="pigmentos terrosos e quentes: ocre, siena queimada, verde-oliva, azul-acinzentado e toques de dourado",
    ),
    PerfilDeFabrica(
        nome="Aquarela",
        categoria=CategoriaEstilo.AQUARELA,
        estilo="aquarela sobre papel de textura visível: lavagens transparentes, bordas suaves que se diluem e áreas de papel em branco como luz",
        iluminacao="luz suave e difusa, sem sombras duras; os brilhos são o próprio branco do papel",
        paleta="pigmentos translúcidos e delicados, em lavagens claras: azul-cobalto, sépia, rosa-pálido e verde-musgo",
    ),
    PerfilDeFabrica(
        nome="Arte digital conceitual",
        categoria=CategoriaEstilo.ARTE_DIGITAL_CONCEITUAL,
        estilo="arte conceitual digital para jogos e cinema: pintura digital polida, silhueta clara e foco narrativo bem definido",
        iluminacao="luz direcional dramática com um ponto focal forte e perspectiva atmosférica em camadas",
        paleta="harmonia de cores rica e controlada, com contraste entre uma cor dominante e uma de destaque",
    ),
    PerfilDeFabrica(
        nome="Quadrinhos",
        categoria=CategoriaEstilo.QUADRINHOS,
        estilo="ilustração de história em quadrinhos e graphic novel: contornos pretos de tinta de espessura variada e composição dinâmica",
        iluminacao="luz recortada de alto contraste, com sombras em hachura ou em preto chapado",
        paleta="cores chapadas ou em retícula, poucas e fortes, com pretos marcantes",
    ),
    PerfilDeFabrica(
        nome="Cartoon e animação 2D",
        categoria=CategoriaEstilo.CARTOON_ANIMACAO,
        estilo="desenho animado 2D: formas simples e geométricas, contornos limpos e poses e proporções expressivas e exageradas",
        iluminacao="sombreamento chapado e limpo, com poucos brilhos e fundos pintados simples",
        paleta="cores vivas, saturadas e bem separadas entre personagem e fundo",
    ),
    PerfilDeFabrica(
        nome="Anime",
        categoria=CategoriaEstilo.ANIME,
        estilo="ilustração de anime de alta qualidade: contornos finos, sombreamento em cel-shading, olhos grandes e expressivos e cabelo em mechas definidas",
        iluminacao="sombras de borda dura e chapadas, céus luminosos e leve brilho difuso (bloom) nas luzes",
        paleta="paleta vibrante e saturada, com fundos pintados em detalhe",
    ),
    PerfilDeFabrica(
        nome="Pixel art",
        categoria=CategoriaEstilo.PIXEL_ART,
        estilo="pixel art de videogame retrô de 16 bits: grade de pixels visível, sem suavização, contorno de um pixel e agrupamentos feitos à mão",
        iluminacao="sombreamento por tramas de pontos (dithering) em vez de degradês, com poucos níveis de luz",
        paleta="paleta restrita de 16 a 32 cores, escolhidas uma a uma",
    ),
    PerfilDeFabrica(
        nome="Gravura clássica",
        categoria=CategoriaEstilo.GRAVURA_CLASSICA,
        estilo="gravura clássica de livro do século XIX: linhas de tinta em hachura cruzada para dar sombra e volume, em moldura com borda fina",
        iluminacao="luz e sombra construídas só por hachuras, com traços que engrossam e afinam",
        paleta="monocromática, preto ou sépia sobre papel envelhecido cor de creme",
    ),
    PerfilDeFabrica(
        nome="Animação 3D",
        categoria=CategoriaEstilo.ANIMACAO_3D,
        estilo="cena de longa-metragem de animação 3D estilizada: formas esculpidas e suaves, proporções levemente exageradas, olhos grandes e pele translúcida",
        iluminacao="iluminação global suave, sombras macias e luz de contorno (rim light), com profundidade de campo rasa",
        paleta="cores ricas e saturadas, com acabamento polido de filme familiar",
    ),
)

_PERFIS = sa.table(
    "perfis_renderizacao",
    sa.column("id", sa.Integer),
    sa.column("nome", sa.String),
    sa.column("estilo", sa.Text),
    sa.column("iluminacao", sa.String),
    sa.column("paleta", sa.String),
    sa.column("categoria_estilo", sa.String),
    sa.column("de_fabrica", sa.Boolean),
)


def garantir_perfis_de_fabrica(conexao: Connection) -> None:
    """Cria os perfis de fábrica que faltam e reescreve os textos dos que já existem. Pode rodar quantas vezes quiser."""
    for perfil in PERFIS_DE_FABRICA:
        textos = {
            "nome": perfil.nome,
            "estilo": perfil.estilo,
            "iluminacao": perfil.iluminacao,
            "paleta": perfil.paleta,
            "de_fabrica": True,
        }
        existente = conexao.execute(
            sa.select(_PERFIS.c.id).where(_PERFIS.c.de_fabrica.is_(True), _PERFIS.c.categoria_estilo == perfil.categoria.value)
        ).scalar()
        if existente is not None:
            conexao.execute(_PERFIS.update().where(_PERFIS.c.id == existente).values(**textos))
            continue
        # O nome é único: um perfil próprio que já se chame assim cede o nome, em vez de a semeadura quebrar.
        conexao.execute(
            _PERFIS.update()
            .where(_PERFIS.c.nome == perfil.nome, _PERFIS.c.de_fabrica.is_not(True))
            .values(nome=f"{perfil.nome} (próprio)")
        )
        conexao.execute(_PERFIS.insert().values(categoria_estilo=perfil.categoria.value, **textos))
