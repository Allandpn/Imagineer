"""Revisão de fidelidade dos prompts (FD1 a FD5, item 4.5): o que a IA **recebe** em cada etapa.

Os testes conferem o pedido que chega ao provedor (o ``ProvedorFalso`` guarda cada chamada), não a qualidade da resposta: a qualidade
se vê comparando prompts do mesmo frame em livro real (FD9).
"""

import json

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.ia import openrouter
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.modelos import Elemento, TipoElemento
from imagineer.servicos.aparencia_de_elemento import aparencia_fixa_de
from imagineer.servicos.perfis_de_fabrica import PERFIS_DE_FABRICA
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import _frame, _perfil
from testes.teste_rotas_sugestoes import _livro_com_capitulos

ESTADO_LIDO = "Aparência fixa: cabelo escuro e comprido, pele clara.\nNeste instante: capa de pele, olhar baixo.\nOnde está: um pátio de pedra."


def _preparar(cliente: TestClient, usar_provedor_falso, provedor: ProvedorFalso, capitulos: int = 3):
    """Livro com capítulos, perfil padrão e os modelos escolhidos; devolve o livro."""
    usar_provedor_falso(provedor)
    livro = _livro_com_capitulos(cliente, capitulos=capitulos)
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_extracao": MODELO_FALSO, "modelo_prompt": MODELO_FALSO})
    return livro


def _elemento(cliente: TestClient, livro_id: int, nome: str = "Jon", identidade: str | None = "Bastardo.", estado: dict | None = None) -> dict:
    corpo = {"tipo": "PERSONAGEM", "nome": nome, "descricao": identidade}
    if estado is not None:
        corpo["estado_inicial"] = estado
    resposta = cliente.post(f"/livros/{livro_id}/elementos", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _novo_estado(cliente: TestClient, elemento_id: int, capitulo_id: int, descricao: str = "Jon está assim.") -> dict:
    resposta = cliente.post(f"/elementos/{elemento_id}/estados", json={"capitulo_id": capitulo_id, "descricao": descricao})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _prompt_do_estado(cliente: TestClient, capitulo_id: int, estado_id: int) -> None:
    frame = _frame(cliente, capitulo_id, [estado_id], tipo="PERSONAGEM")
    assert cliente.post(f"/frames/{frame['id']}/prompts", json={}).status_code == 201


# --------------------------------------------------------------------------- #
# A "Aparência fixa" de uma descrição
# --------------------------------------------------------------------------- #


def teste_aparencia_fixa_e_so_a_primeira_parte_sem_o_rotulo() -> None:
    assert aparencia_fixa_de(ESTADO_LIDO) == "cabelo escuro e comprido, pele clara."


def teste_aparencia_fixa_aceita_texto_em_varias_linhas_ate_o_proximo_rotulo() -> None:
    texto = "Aparência fixa: cabelo escuro\ne comprido.\nNeste instante: de capa."

    assert aparencia_fixa_de(texto) == "cabelo escuro e comprido."


def teste_formato_antigo_sem_rotulos_nao_tem_aparencia_fixa() -> None:
    # Sem como separar o fixo do instante, é melhor não mandar nada do que mandar roupa e pose como traço permanente.
    assert aparencia_fixa_de("Um homem de capa, de pé no pátio.") is None
    assert aparencia_fixa_de(None) is None
    assert aparencia_fixa_de("Neste instante: de capa.") is None


# --------------------------------------------------------------------------- #
# FD1 — o rascunho de identidade não é aparência
# --------------------------------------------------------------------------- #


def teste_o_rascunho_de_identidade_nao_vai_como_estado_ja_registrado(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p")
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1 = livro["capitulos"][0]
    # O estado nasce com o texto da identidade (como ao confirmar uma sugestão): é só um rascunho.
    jon = _elemento(cliente, livro["id"], identidade="jovem nobre exilado", estado={"capitulo_id": c1["id"], "descricao": "jovem nobre exilado"})

    _prompt_do_estado(cliente, c1["id"], jon["estados"][0]["id"])

    assert provedor.chamadas_de_estado[0]["estado_atual"] is None


def teste_o_rascunho_vindo_de_uma_sugestao_tambem_e_reconhecido(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    from imagineer.modelos import Capitulo, EstadoElemento, SugestaoDeElemento
    from imagineer.servicos.aparencia_de_elemento import e_rascunho_de_identidade

    livro = _livro_com_capitulos(cliente, capitulos=1)
    jon = _elemento(cliente, livro["id"], identidade="outra identidade")
    elemento = sessao_com_tabelas.get(Elemento, jon["id"])
    capitulo = sessao_com_tabelas.get(Capitulo, livro["capitulos"][0]["id"])
    sessao_com_tabelas.add(
        SugestaoDeElemento(
            capitulo_id=capitulo.id, tipo=TipoElemento.PERSONAGEM, nome="Jon", descricao="Filho de Eddard, criado em Winterfell.",
            modelo="x", elemento_id=elemento.id,
        )
    )
    estado = EstadoElemento(elemento_id=elemento.id, capitulo_id=capitulo.id, descricao="Filho de  Eddard,\ncriado em Winterfell.")
    sessao_com_tabelas.add(estado)
    sessao_com_tabelas.commit()

    assert e_rascunho_de_identidade(sessao_com_tabelas, estado) is True  # igual à identidade da sugestão, sem contar espaços

    estado.confirmado_pela_leitura_profunda = True
    assert e_rascunho_de_identidade(sessao_com_tabelas, estado) is False  # depois da leitura profunda já é aparência


def teste_o_estado_digitado_a_mao_continua_indo_como_registrado(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p")
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1 = livro["capitulos"][0]
    jon = _elemento(cliente, livro["id"], estado={"capitulo_id": c1["id"], "descricao": "barba rala, olhos cinzentos"})

    _prompt_do_estado(cliente, c1["id"], jon["estados"][0]["id"])

    assert provedor.chamadas_de_estado[0]["estado_atual"] == "barba rala, olhos cinzentos"


def teste_estado_ja_lido_volta_como_registrado_na_releitura(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p", estado=ESTADO_LIDO)
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    cliente.put("/configuracao", json={"prioridade_ia": "QUALIDADE"})
    c1 = livro["capitulos"][0]
    jon = _elemento(cliente, livro["id"], identidade="Bastardo.", estado={"capitulo_id": c1["id"], "descricao": "Bastardo."})
    estado_id = jon["estados"][0]["id"]

    _prompt_do_estado(cliente, c1["id"], estado_id)
    _prompt_do_estado(cliente, c1["id"], estado_id)

    assert provedor.chamadas_de_estado[0]["estado_atual"] is None  # primeira leitura: era só o rascunho
    assert provedor.chamadas_de_estado[1]["estado_atual"] == ESTADO_LIDO  # a segunda parte do que a primeira leu


# --------------------------------------------------------------------------- #
# FD2 — a aparência dos capítulos anteriores
# --------------------------------------------------------------------------- #


def teste_a_releitura_recebe_a_aparencia_fixa_do_capitulo_anterior(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p", estado=ESTADO_LIDO)
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1, c2, c3 = livro["capitulos"]
    jon = _elemento(cliente, livro["id"], estado={"capitulo_id": c1["id"], "descricao": "digitado"})
    _prompt_do_estado(cliente, c1["id"], jon["estados"][0]["id"])  # lê o capítulo 1: agora o estado é "lido"
    estado_do_c3 = _novo_estado(cliente, jon["id"], c3["id"])

    _prompt_do_estado(cliente, c3["id"], estado_do_c3["id"])

    primeira, segunda = provedor.chamadas_de_estado
    assert primeira["aparencia_anterior"] is None  # no capítulo 1 não havia nada antes
    assert segunda["aparencia_anterior"] == "cabelo escuro e comprido, pele clara."  # sem roupa, pose nem lugar


def teste_estado_ainda_nao_lido_nao_serve_de_aparencia_anterior(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p")
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1, _c2, c3 = livro["capitulos"]
    jon = _elemento(cliente, livro["id"], estado={"capitulo_id": c1["id"], "descricao": ESTADO_LIDO})  # existe, mas nunca foi lido
    estado_do_c3 = _novo_estado(cliente, jon["id"], c3["id"])

    _prompt_do_estado(cliente, c3["id"], estado_do_c3["id"])

    assert provedor.chamadas_de_estado[0]["aparencia_anterior"] is None


def teste_capitulo_posterior_nao_orienta_a_leitura_de_um_anterior(cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session) -> None:
    from imagineer.modelos import EstadoElemento

    provedor = ProvedorFalso(prompt="p", estado=ESTADO_LIDO)
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1, _c2, c3 = livro["capitulos"]
    jon = _elemento(cliente, livro["id"], estado={"capitulo_id": c3["id"], "descricao": "digitado"})
    _prompt_do_estado(cliente, c3["id"], jon["estados"][0]["id"])  # o capítulo 3 já foi lido
    estado_do_c1 = _novo_estado(cliente, jon["id"], c1["id"])

    _prompt_do_estado(cliente, c1["id"], estado_do_c1["id"])

    assert provedor.chamadas_de_estado[1]["aparencia_anterior"] is None  # o que o livro ainda não mostrou não vale
    assert sessao_com_tabelas.get(EstadoElemento, estado_do_c1["id"]) is not None


# --------------------------------------------------------------------------- #
# FD3 — a identidade acumulada chega à IA
# --------------------------------------------------------------------------- #


def teste_o_prompt_recebe_a_identidade_vigente_ate_o_capitulo_do_frame(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p")
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1, c2, c3 = livro["capitulos"]
    jon = _elemento(cliente, livro["id"], identidade="Bastardo.", estado={"capitulo_id": c1["id"], "descricao": "digitado"})
    cliente.post(f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c2["id"], "descricao": "Agora é Lorde Comandante."})
    estado_do_c3 = _novo_estado(cliente, jon["id"], c3["id"])

    _prompt_do_estado(cliente, c1["id"], jon["estados"][0]["id"])
    _prompt_do_estado(cliente, c3["id"], estado_do_c3["id"])

    antes, depois = provedor.chamadas_de_prompt
    assert antes["elementos"][0].startswith("Jon (Bastardo.):")  # no capítulo 1 o acréscimo do 2 ainda não aconteceu
    assert depois["elementos"][0].startswith("Jon (Bastardo. Agora é Lorde Comandante.):")


def teste_a_leitura_profunda_tambem_recebe_a_identidade_vigente(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p")
    livro = _preparar(cliente, usar_provedor_falso, provedor)
    c1, c2, c3 = livro["capitulos"]
    jon = _elemento(cliente, livro["id"], identidade="Bastardo.", estado={"capitulo_id": c1["id"], "descricao": "digitado"})
    cliente.post(f"/elementos/{jon['id']}/historico-identidade", json={"capitulo_id": c2["id"], "descricao": "Agora é Lorde Comandante."})
    estado_do_c3 = _novo_estado(cliente, jon["id"], c3["id"])

    _prompt_do_estado(cliente, c3["id"], estado_do_c3["id"])

    assert provedor.chamadas_de_estado[0]["descricao_do_elemento"] == "Bastardo. Agora é Lorde Comandante."


def teste_a_identidade_muito_longa_vai_resumida(cliente: TestClient, usar_provedor_falso) -> None:
    provedor = ProvedorFalso(prompt="p")
    livro = _preparar(cliente, usar_provedor_falso, provedor, capitulos=1)
    c1 = livro["capitulos"][0]
    longa = " ".join(["palavra"] * 200)
    jon = _elemento(cliente, livro["id"], identidade=longa, estado={"capitulo_id": c1["id"], "descricao": "digitado"})

    _prompt_do_estado(cliente, c1["id"], jon["estados"][0]["id"])

    linha = provedor.chamadas_de_prompt[0]["elementos"][0]
    assert linha.startswith("Jon (palavra") and "…" in linha
    assert len(linha.split("):")[0]) < 340


# --------------------------------------------------------------------------- #
# FD4 — a luz vem da cena
# --------------------------------------------------------------------------- #


def teste_a_instrucao_do_prompt_diz_que_a_fonte_de_luz_e_da_cena() -> None:
    instrucao = openrouter._INSTRUCAO_DE_PROMPT

    assert "fonte de luz vem \\\nsempre da cena" in instrucao or "fonte de luz vem sempre da cena" in " ".join(instrucao.replace("\\\n", "").split())
    assert "convenção de renderização" in instrucao


def teste_a_instrucao_do_perfil_pede_so_a_convencao_da_luz() -> None:
    instrucao = " ".join(openrouter._INSTRUCAO_DE_PERFIL.replace("\\\n", "").split())

    assert "nunca a fonte" in instrucao
    assert "luz de vela, alto contraste" not in instrucao  # o exemplo antigo ensinava o erro


def teste_os_perfis_de_fabrica_nao_citam_fonte_de_luz() -> None:
    fontes = ("vela", "luar", "lua", "sol ", "sol,", "pôr do sol", "lâmpada", "lampada", "fogueira", "neon", "tocha", "janela")
    for perfil in PERFIS_DE_FABRICA:
        iluminacao = perfil.iluminacao.lower() + " "
        assert not any(fonte in iluminacao for fonte in fontes), (perfil.nome, perfil.iluminacao)


def teste_a_migracao_da_iluminacao_encadeia_e_chama_a_semeadura() -> None:
    from pathlib import Path

    texto = (Path(__file__).parent.parent / "migracoes" / "versions" / "f6a7b8c9d0e1_iluminacao_dos_perfis_de_fabrica.py").read_text(encoding="utf-8")

    assert "down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'" in texto
    assert "garantir_perfis_de_fabrica(op.get_bind())" in texto


# --------------------------------------------------------------------------- #
# FD5 — a temperatura de cada chamada
# --------------------------------------------------------------------------- #


def _provedor_que_guarda_o_pedido(conteudo: str):
    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": conteudo}}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave-de-teste", cliente=cliente), pedidos


def teste_extracao_leitura_profunda_e_fundamentacao_usam_temperatura_baixa() -> None:
    chamadas = {
        "extracao": ('{"elementos": [], "cenas": []}', lambda p: p.extrair_elementos("texto", [], "m/x")),
        "estado": ('{"aparencia_fixa": "a", "instante": "b", "ambiente": null}', lambda p: p.sugerir_estado("t", TipoElemento.PERSONAGEM, "Jon", None, None, "m/x")),
        "identidade": ('{"descricao": null}', lambda p: p.sugerir_identidade("t", TipoElemento.PERSONAGEM, "Jon", None, "m/x")),
        "fundamentacao": ('{"contexto": "c"}', lambda p: p.fundamentar_frame("t", "No pátio", None, None, None, None, [], "m/x")),
    }
    for nome, (resposta, chamar) in chamadas.items():
        provedor, pedidos = _provedor_que_guarda_o_pedido(resposta)

        chamar(provedor)

        assert pedidos[0]["temperature"] == 0.2, nome


def teste_a_montagem_do_prompt_usa_temperatura_um_pouco_maior() -> None:
    provedor, pedidos = _provedor_que_guarda_o_pedido("a prompt")

    provedor.montar_prompt("cena", ["Jon: x"], "estilo", "m/x")

    assert pedidos[0]["temperature"] == 0.4


def teste_o_pedido_da_leitura_profunda_leva_a_aparencia_estabelecida() -> None:
    provedor, pedidos = _provedor_que_guarda_o_pedido('{"aparencia_fixa": "a", "instante": "b", "ambiente": null}')

    provedor.sugerir_estado("t", TipoElemento.PERSONAGEM, "Jon", None, None, "m/x", aparencia_anterior="cabelo escuro")
    provedor.sugerir_estado("t", TipoElemento.PERSONAGEM, "Jon", None, None, "m/x")

    com, sem = (p["messages"][1]["content"] for p in pedidos)
    assert "APARÊNCIA ESTABELECIDA ATÉ AQUI (traços fixos de capítulos anteriores): cabelo escuro" in com
    assert "APARÊNCIA ESTABELECIDA ATÉ AQUI (traços fixos de capítulos anteriores): (nenhuma ainda)" in sem
    assert "APARÊNCIA ESTABELECIDA" in pedidos[0]["messages"][0]["content"]  # e a instrução explica o que fazer com ela
