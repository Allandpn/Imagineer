"""Os limites do servidor compartilhado (itens CT15 a CT20): tamanho de arquivo, teto da narração, espaço da aplicação e cota por pessoa."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from imagineer.modelos import DONO_ID, AudioDeCapitulo, Capitulo, Limites, SituacaoDoAudio, Usuario
from imagineer.servicos import limites as servico
from imagineer.servicos.acesso import definir_usuario
from imagineer.servicos.limites import BYTES_POR_GB, exigir_espaco, obter_limites, uso_da_pessoa_em_bytes
from testes.teste_imagem_canonica import _retrato_com_duas_imagens
from testes.teste_narracao_por_ia import MODELO, _capitulo, _escolher, _tres_trechos
from testes.teste_rotas_prompts import _diretorio_de_imagens  # noqa: F401  (a pasta de imagens temporária que o cenário usa)
from testes.teste_rotas_prompts import PNG_PEQUENO, _cena_com_referencia, _livro


@pytest.fixture(autouse=True)
def _cache_limpo():
    """Cada teste mede o disco de novo: o total da aplicação fica guardado por alguns segundos."""
    servico.limpar_cache_do_uso()
    yield
    servico.limpar_cache_do_uso()


def _pessoa(sessao: Session, login: str = "maria@exemplo.com") -> Usuario:
    pessoa = Usuario(login=login, nome=login.split("@")[0])
    sessao.add(pessoa)
    sessao.commit()
    return pessoa


# --------------------------------------------------------------------------- #
# CT20: onde se configuram
# --------------------------------------------------------------------------- #


def teste_ct20_os_padroes_sao_os_decididos(cliente: TestClient) -> None:
    corpo = cliente.get("/admin/limites").json()

    assert {k: v for k, v in corpo.items() if not k.startswith(("uso", "recusa"))} == {
        "tamanho_maximo_do_video_mb": 50,
        "tamanho_maximo_do_epub_mb": 60,
        "tamanho_maximo_da_imagem_mb": 15,
        "caracteres_maximos_da_narracao": 100_000,
        "armazenamento_total_em_gb": 20,
        "cota_por_pessoa_em_gb": 5,
    }
    assert corpo["recusa_novos_arquivos_a_partir_de_bytes"] == int(20 * BYTES_POR_GB * 0.9)


def teste_ct20_o_dono_muda_so_o_que_mandou_e_vale_no_pedido_seguinte(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    resposta = cliente.put("/admin/limites", json={"cota_por_pessoa_em_gb": 8})

    assert resposta.status_code == 200
    assert resposta.json()["cota_por_pessoa_em_gb"] == 8 and resposta.json()["tamanho_maximo_do_video_mb"] == 50
    assert sessao_com_tabelas.get(Limites, 1).cota_por_pessoa_em_gb == 8


def teste_ct20_valor_zero_negativo_ou_campo_desconhecido_e_422(cliente: TestClient) -> None:
    for corpo in ({"tamanho_maximo_do_video_mb": 0}, {"cota_por_pessoa_em_gb": -1}, {"tamanho_da_lua": 3}):
        assert cliente.put("/admin/limites", json=corpo).status_code == 422, corpo


def teste_ct20_quem_nao_e_o_dono_recebe_404_ao_ler_e_ao_mudar(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    definir_usuario(sessao_com_tabelas, _pessoa(sessao_com_tabelas).id)

    assert cliente.get("/admin/limites").status_code == 404
    assert cliente.put("/admin/limites", json={"cota_por_pessoa_em_gb": 999}).status_code == 404
    assert obter_limites(sessao_com_tabelas).cota_por_pessoa_em_gb == 5


# --------------------------------------------------------------------------- #
# CT15: tamanho máximo por arquivo
# --------------------------------------------------------------------------- #


def teste_ct15_imagem_acima_do_limite_da_413_e_nada_fica_no_disco(cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens) -> None:
    _, _, _, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    assert cliente.put("/admin/limites", json={"tamanho_maximo_da_imagem_mb": 1}).status_code == 200

    grande = cliente.post(f"/prompts/{prompt['id']}/imagens", files={"arquivo": ("a.png", PNG_PEQUENO + b"\x00" * (1024 * 1024), "image/png")})
    pequena = cliente.post(f"/prompts/{prompt['id']}/imagens", files={"arquivo": ("a.png", PNG_PEQUENO, "image/png")})

    assert grande.status_code == 413 and "1 MB" in grande.json()["detail"]
    assert pequena.status_code == 201


def teste_ct15_a_capa_usa_o_limite_do_epub(cliente: TestClient) -> None:
    livro = _livro(cliente)
    assert cliente.put("/admin/limites", json={"tamanho_maximo_do_epub_mb": 1}).status_code == 200

    resposta = cliente.post(f"/livros/{livro['id']}/capa", files={"arquivo": ("c.png", b"x" * (1024 * 1024 + 1), "image/png")})

    assert resposta.status_code == 413


# --------------------------------------------------------------------------- #
# CT16: narração
# --------------------------------------------------------------------------- #


def teste_ct16_capitulo_acima_do_teto_da_422_antes_de_gastar(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    from imagineer.ia.falso import ProvedorFalso

    provedor = usar_provedor_falso(ProvedorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, _tres_trechos())  # 6.002 caracteres
    _escolher(cliente)
    assert cliente.put("/admin/limites", json={"caracteres_maximos_da_narracao": 5000}).status_code == 200

    resposta = cliente.post(f"/capitulos/{capitulo_id}/audio")

    assert resposta.status_code == 422 and "5000" in resposta.json()["detail"]
    assert provedor.chamadas_de_narracao == []  # nada foi enviado ao provedor
    assert sessao_com_tabelas.query(AudioDeCapitulo).count() == 0


def teste_ct16_uma_geracao_por_vez_por_pessoa_mesmo_em_outro_capitulo(
    cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso, usar_criador_de_sessao_de_teste
) -> None:
    from imagineer.ia.falso import ProvedorFalso

    usar_provedor_falso(ProvedorFalso())
    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto.")
    _escolher(cliente)
    outro = Capitulo(livro_id=sessao_com_tabelas.get(Capitulo, capitulo_id).livro_id, ordem=99, titulo="Outro", texto="Outro texto.")
    sessao_com_tabelas.add(outro)
    sessao_com_tabelas.add(AudioDeCapitulo(capitulo_id=capitulo_id, modelo="m", voz="v", situacao=SituacaoDoAudio.GERANDO))
    sessao_com_tabelas.commit()

    resposta = cliente.post(f"/capitulos/{outro.id}/audio")

    assert resposta.status_code == 409 and "já tem uma narração" in resposta.json()["detail"]


def teste_ct16_geracao_de_outra_pessoa_nao_trava_a_minha(cliente: TestClient, sessao_com_tabelas: Session) -> None:
    from imagineer.servicos.narracao import narracao_em_andamento_da_pessoa

    capitulo_id = _capitulo(cliente, sessao_com_tabelas, "Um texto.")
    sessao_com_tabelas.add(AudioDeCapitulo(capitulo_id=capitulo_id, modelo="m", voz="v", situacao=SituacaoDoAudio.GERANDO))
    sessao_com_tabelas.commit()
    maria = _pessoa(sessao_com_tabelas)

    assert narracao_em_andamento_da_pessoa(sessao_com_tabelas, DONO_ID) is True
    assert narracao_em_andamento_da_pessoa(sessao_com_tabelas, maria.id) is False


# --------------------------------------------------------------------------- #
# CT17: espaço da aplicação
# --------------------------------------------------------------------------- #


def teste_ct17_a_90_por_cento_recusa_novos_arquivos_mas_deixa_ler_e_apagar(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens, monkeypatch
) -> None:
    _, _, _, prompt = _cena_com_referencia(cliente, usar_provedor_falso)
    imagem = cliente.post(f"/prompts/{prompt['id']}/imagens", files={"arquivo": ("a.png", PNG_PEQUENO, "image/png")}).json()
    assert cliente.put("/admin/limites", json={"armazenamento_total_em_gb": 10}).status_code == 200
    monkeypatch.setattr(servico, "uso_da_aplicacao_em_bytes", lambda: int(9.01 * BYTES_POR_GB))

    recusada = cliente.post(f"/prompts/{prompt['id']}/imagens", files={"arquivo": ("a.png", PNG_PEQUENO, "image/png")})
    geracao = cliente.post(f"/prompts/{prompt['id']}/gerar-imagem")

    assert recusada.status_code == 507 and "90%" in recusada.json()["detail"]
    assert geracao.status_code == 507
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 200  # ler segue funcionando
    assert cliente.delete(f"/imagens/{imagem['id']}").status_code == 204  # e apagar também: é como se libera espaço


def teste_ct17_abaixo_dos_90_por_cento_aceita(sessao_com_tabelas: Session, monkeypatch) -> None:
    obter_limites(sessao_com_tabelas).armazenamento_total_em_gb = 10
    monkeypatch.setattr(servico, "uso_da_aplicacao_em_bytes", lambda: int(8.9 * BYTES_POR_GB))

    exigir_espaco(sessao_com_tabelas)  # não levanta


def teste_ct17_o_uso_da_aplicacao_e_a_soma_dos_arquivos_da_pasta(_diretorio_de_imagens) -> None:
    (_diretorio_de_imagens / "a").mkdir(parents=True, exist_ok=True)
    (_diretorio_de_imagens / "a" / "x.bin").write_bytes(b"1" * 100)
    (_diretorio_de_imagens / "y.bin").write_bytes(b"2" * 50)

    assert servico.uso_da_aplicacao_em_bytes() == 150


# --------------------------------------------------------------------------- #
# CT18: cota por pessoa
# --------------------------------------------------------------------------- #


def teste_ct18_o_uso_da_pessoa_soma_o_que_e_dela(cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso) -> None:
    _retrato_com_duas_imagens(cliente, usar_provedor_falso)
    maria = _pessoa(sessao_com_tabelas)

    assert uso_da_pessoa_em_bytes(sessao_com_tabelas, DONO_ID) > 0
    assert uso_da_pessoa_em_bytes(sessao_com_tabelas, maria.id) == 0


def teste_ct18_passou_da_cota_da_pessoa_e_507_e_o_dono_nao_tem_cota(sessao_com_tabelas: Session, monkeypatch) -> None:
    maria = _pessoa(sessao_com_tabelas)
    monkeypatch.setattr(servico, "uso_da_aplicacao_em_bytes", lambda: 0)
    monkeypatch.setattr(servico, "uso_da_pessoa_em_bytes", lambda sessao, usuario_id: 6 * BYTES_POR_GB)  # a cota padrão é de 5 GB

    definir_usuario(sessao_com_tabelas, DONO_ID)
    exigir_espaco(sessao_com_tabelas)  # o dono: sem cota

    definir_usuario(sessao_com_tabelas, maria.id)
    with pytest.raises(Exception) as erro:
        exigir_espaco(sessao_com_tabelas)
    assert erro.value.status_code == 507 and "5 GB" in erro.value.detail
