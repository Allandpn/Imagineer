"""Contratos da lixeira (item 7.5b, LX1 a LX10)."""

from datetime import datetime

from pydantic import BaseModel, Field


class ImagemNaLixeira(BaseModel):
    """Uma imagem movida para a lixeira, com o contexto para o usuário reconhecê-la (LX5)."""

    id: int
    prompt_id: int
    frame_id: int
    frame_titulo: str
    frame_tipo: str = Field(description="`CENA` ou `PERSONAGEM` (retrato).")
    nome_do_elemento: str | None = Field(default=None, description="No retrato, o elemento retratado; nulo na cena.")
    capitulo_id: int
    titulo_do_capitulo: str | None = None
    ordem_do_capitulo: int
    livro_id: int
    titulo_do_livro: str
    largura: int | None = None
    altura: int | None = None
    orientacao: str | None = Field(default=None, description="`RETRATO` ou `PAISAGEM` pela imagem real; nulo sem dimensões.")
    modelo: str | None = None
    origem: str = Field(description="`IMPORTADA` ou `GERADA`.")
    sem_filtro_de_seguranca: bool = False
    tamanho_em_bytes: int | None = None
    apagada_em: datetime


class Lixeira(BaseModel):
    """O que a lixeira guarda: as imagens, da apagada mais recentemente para a mais antiga, e o espaço que ocupam (LX5, LX6)."""

    imagens: list[ImagemNaLixeira]
    total_em_bytes: int = Field(description="A soma dos tamanhos das imagens da lixeira, para o usuário decidir se esvazia.")


class LixeiraEsvaziada(BaseModel):
    """O resultado de esvaziar a lixeira (LX5)."""

    removidas: int
    liberados_em_bytes: int


class LivroNaLixeira(BaseModel):
    """Um livro movido para a lixeira, com o que ele leva junto, para a pessoa decidir (LT2)."""

    id: int
    titulo: str
    autor: str | None = None
    apagado_em: datetime
    total_de_capitulos: int
    total_de_imagens: int = Field(description="Imagens do livro (as que estão em prompts dele), ativas ou já na lixeira de imagens.")
    tamanho_das_imagens_em_bytes: int = Field(description="O espaço em disco das imagens do livro: o que se libera ao apagar de vez.")
    tem_capa: bool = False


class LivrosDaLixeira(BaseModel):
    """Os livros da lixeira, do apagado mais recentemente para o mais antigo (LT2)."""

    livros: list[LivroNaLixeira]
    total_em_bytes: int = Field(description="A soma do espaço das imagens de todos os livros da lixeira.")

