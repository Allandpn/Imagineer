"""Uma análise de IA por capítulo de cada vez (item 6.7, "Uma análise por capítulo de cada vez").

Duas análises simultâneas do mesmo capítulo eram duas cobranças e duas levas de sugestões repetidas. Em
vez de a segunda **esperar** (prenderia o pedido por minutos e esconderia do app que há uma análise
rolando), ela é **recusada na hora**, sem gastar IA.

**Limite conhecido:** a trava mora na **memória do processo**, então só vale com **um** processo da API
(como é hoje: o ``uvicorn`` do container). Com vários processos, teria de virar uma marca no banco.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_em_andamento: set[int] = set()
_guarda = threading.Lock()


class AnaliseEmAndamento(Exception):
    """Já existe uma análise deste capítulo rodando."""


@contextmanager
def analise_exclusiva(capitulo_id: int) -> Iterator[None]:
    """Reserva o capítulo para uma análise; levanta ``AnaliseEmAndamento`` se já estiver reservado.

    A reserva é devolvida ao sair do bloco, **inclusive se a análise falhar**: uma IA que dá erro não
    pode deixar o capítulo travado para sempre.
    """
    with _guarda:
        if capitulo_id in _em_andamento:
            raise AnaliseEmAndamento(capitulo_id)
        _em_andamento.add(capitulo_id)
    try:
        yield
    finally:
        with _guarda:
            _em_andamento.discard(capitulo_id)
