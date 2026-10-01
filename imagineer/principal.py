"""Ponto de entrada da API do Imagineer.

Este módulo tem uma responsabilidade só: criar a aplicação FastAPI e registrar
as rotas. Nenhuma regra de negócio mora aqui — assim dá para ler o arquivo e
entender, em poucas linhas, tudo o que a API expõe.

Para subir em desenvolvimento:
    uvicorn imagineer.principal:aplicacao --reload
"""

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

# Registra o ouvinte que sobe a revisão do livro a cada gravação (item 6.9). O simples import
# basta: o decorador do módulo faz o registro.
from imagineer.banco import revisao  # noqa: F401
from imagineer.rotas import (
    capitulos,
    configuracao,
    elementos,
    frame,
    livros,
    perfis_renderizacao,
    prompts,
    saude,
)

aplicacao = FastAPI(
    title="Imagineer",
    description=(
        "Gera prompts de imagem a partir de e-books, para dar apoio visual à "
        "leitura de quem tem afantasia."
    ),
    version="0.1.0",
)

# Compressão das respostas (item 6.9). O texto de um capítulo chega a ~110 KB e comprime bem; só
# vale a pena acima de ~1 KB (abaixo disso o cabeçalho pesa mais que o ganho). As imagens (PNG,
# JPEG, WebP, GIF) já vêm comprimidas e ficam de fora sozinhas: a lista de tipos excluídos
# é o padrão do Starlette, então não há nada a configurar para elas.
aplicacao.add_middleware(GZipMiddleware, minimum_size=1000)

aplicacao.include_router(saude.rotas)
aplicacao.include_router(livros.rotas)
aplicacao.include_router(capitulos.rotas)
aplicacao.include_router(elementos.rotas_de_livro)
aplicacao.include_router(elementos.rotas_de_capitulo)
aplicacao.include_router(elementos.rotas)
aplicacao.include_router(elementos.rotas_de_estado)
aplicacao.include_router(elementos.rotas_de_sugestao_elemento)
aplicacao.include_router(elementos.rotas_de_sugestao_cena)
aplicacao.include_router(elementos.rotas_de_identidade)
aplicacao.include_router(frame.rotas_de_capitulo)
aplicacao.include_router(frame.rotas)
aplicacao.include_router(perfis_renderizacao.rotas)
aplicacao.include_router(configuracao.rotas)
aplicacao.include_router(prompts.rotas_de_frame)
aplicacao.include_router(prompts.rotas)
aplicacao.include_router(prompts.rotas_de_imagem)
