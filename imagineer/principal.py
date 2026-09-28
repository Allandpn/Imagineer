"""Ponto de entrada da API do Imagineer.

Este módulo tem uma responsabilidade só: criar a aplicação FastAPI e registrar
as rotas. Nenhuma regra de negócio mora aqui — assim dá para ler o arquivo e
entender, em poucas linhas, tudo o que a API expõe.

Para subir em desenvolvimento:
    uvicorn imagineer.principal:aplicacao --reload
"""

from fastapi import FastAPI

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

aplicacao.include_router(saude.rotas)
aplicacao.include_router(livros.rotas)
aplicacao.include_router(capitulos.rotas)
aplicacao.include_router(elementos.rotas_de_livro)
aplicacao.include_router(elementos.rotas_de_capitulo)
aplicacao.include_router(elementos.rotas)
aplicacao.include_router(elementos.rotas_de_estado)
aplicacao.include_router(elementos.rotas_de_sugestao_elemento)
aplicacao.include_router(frame.rotas_de_capitulo)
aplicacao.include_router(frame.rotas)
aplicacao.include_router(perfis_renderizacao.rotas)
aplicacao.include_router(configuracao.rotas)
aplicacao.include_router(prompts.rotas_de_frame)
aplicacao.include_router(prompts.rotas)
aplicacao.include_router(prompts.rotas_de_imagem)
