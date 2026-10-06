"""Quem chamou: a identidade do pedido (itens CT2 a CT4).

Dois modos, em ``IMAGINEER_AUTENTICACAO``:

- ``pessoal`` (o padrão): todo pedido é do **dono**. O cabeçalho de identidade é ignorado — nada muda para quem usa o servidor sozinho.
- ``tailscale``: vale o cabeçalho ``Tailscale-User-Login`` que o ``tailscale serve`` põe no pedido (o e-mail da conta Tailscale de quem chamou, inclusive de
  quem aceitou o compartilhamento do aparelho). **O cabeçalho só é confiável porque o ``serve`` o apaga se vier de fora**; quem alcançasse a porta direto
  o falsificaria. Por isso ele **só é aceito de um proxy confiável** (CT3): de qualquer outro endereço, ou sem o cabeçalho, é 401.
"""

import ipaddress
import logging

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from imagineer.configuracao import obter_configuracoes
from imagineer.modelos import DONO_ID, Usuario

CABECALHO_DO_LOGIN = "tailscale-user-login"
CABECALHO_DO_NOME = "tailscale-user-name"


def redes_confiaveis(texto: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """As redes de ``IMAGINEER_PROXIES_CONFIAVEIS`` (endereços soltos e faixas CIDR). Um item que não é endereço **derruba o servidor** na hora:
    ignorá-lo em silêncio deixaria o proxy sem poder ser reconhecido e todo mundo com 401, sem explicação."""
    redes = []
    for item in (parte.strip() for parte in texto.split(",")):
        if not item:
            continue
        try:
            redes.append(ipaddress.ip_network(item, strict=False))
        except ValueError as erro:
            raise ValueError(f"IMAGINEER_PROXIES_CONFIAVEIS: {item!r} não é um endereço nem uma faixa CIDR.") from erro
    return redes


def origem_confiavel(endereco: str | None, texto_das_redes: str) -> bool:
    """O pedido veio de um proxy confiável? Um endereço ausente ou que não é IP (o cliente de teste) **não** é confiável."""
    if not endereco:
        return False
    try:
        ip = ipaddress.ip_address(endereco)
    except ValueError:
        return False
    return any(ip in rede for rede in redes_confiaveis(texto_das_redes) if ip.version == rede.version)


def resolver_usuario(request: Request, criador: sessionmaker) -> Usuario:
    """O usuário do pedido (CT2). Em modo ``tailscale``, 401 se o cabeçalho não vier de um proxy confiável ou faltar."""
    configuracoes = obter_configuracoes()
    if configuracoes.autenticacao == "pessoal":
        return _dono(criador)

    origem = request.client.host if request.client else None
    if not origem_confiavel(origem, configuracoes.proxies_confiaveis):
        logging.getLogger(__name__).warning("Pedido de %s recusado: o cabeçalho de identidade só vale de um proxy confiável (CT3).", origem)
        raise _nao_autenticado("O servidor só aceita pedidos que passam pelo `tailscale serve`.")
    login = (request.headers.get(CABECALHO_DO_LOGIN) or "").strip().lower()
    if not login:
        raise _nao_autenticado("O pedido chegou sem a identidade do Tailscale (Tailscale-User-Login).")
    return _usuario_do_login(criador, login, (request.headers.get(CABECALHO_DO_NOME) or "").strip() or None, configuracoes.dono_tailscale.strip().lower())


def _nao_autenticado(detalhe: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detalhe)


def _dono(criador: sessionmaker) -> Usuario:
    """O usuário 1. A migração o cria; um banco montado sem ela (só os testes) o ganha aqui, para nenhuma rota depender de a linha existir."""
    with criador() as sessao:
        dono = sessao.get(Usuario, DONO_ID)
        if dono is None:
            dono = Usuario(id=DONO_ID, nome="Dono", dono=True, usa_chaves_do_servidor=True)
            sessao.add(dono)
            sessao.commit()
        return dono


def _usuario_do_login(criador: sessionmaker, login: str, nome: str | None, login_do_dono: str) -> Usuario:
    """O usuário daquele login, criado na primeira visita; o login do dono reivindica a linha 1 (CT4)."""
    try:
        return _procurar_ou_criar(criador, login, nome, login_do_dono)
    except IntegrityError:
        # Duas primeiras visitas da mesma pessoa ao mesmo tempo: a outra criou a linha primeiro. Agora ela existe.
        return _procurar_ou_criar(criador, login, nome, login_do_dono)


def _procurar_ou_criar(criador: sessionmaker, login: str, nome: str | None, login_do_dono: str) -> Usuario:
    with criador() as sessao:
        usuario = sessao.scalar(select(Usuario).where(Usuario.login == login))
        if usuario is None and login == login_do_dono:
            dono = sessao.get(Usuario, DONO_ID)
            if dono is not None:
                dono.login = login
                dono.nome = nome or dono.nome
                usuario = dono
        if usuario is None:
            usuario = Usuario(login=login, nome=nome)
            sessao.add(usuario)
        sessao.commit()
        return usuario
