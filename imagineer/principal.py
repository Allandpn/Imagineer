"""Ponto de entrada da API do Imagineer.

Este módulo tem uma responsabilidade só: criar a aplicação FastAPI e registrar
as rotas. Nenhuma regra de negócio mora aqui — assim dá para ler o arquivo e
entender, em poucas linhas, tudo o que a API expõe.

Para subir em desenvolvimento:
    uvicorn imagineer.principal:aplicacao --reload
"""

from fastapi import FastAPI

from imagineer.rotas import saude

aplicacao = FastAPI(
    title="Imagineer",
    description=(
        "Gera prompts de imagem a partir de e-books, para dar apoio visual à "
        "leitura de quem tem afantasia."
    ),
    version="0.1.0",
)

aplicacao.include_router(saude.rotas)
