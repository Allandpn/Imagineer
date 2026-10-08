"""Os esquemas JSON das respostas de leitura (item 4.10, LM8).

**Ainda vazio de propósito:** os esquemas são a etapa E4. Este módulo existe desde a E1 só para que ``_corpo_da_chamada`` já saiba onde
procurá-los: com ``ESQUEMAS`` vazio, nenhum pedido leva ``response_format`` e o interpretador tolerante (``_extrair_json``) continua
valendo, como antes.
"""

ESQUEMAS: dict[str, dict] = {}
"""Nome do esquema (o ``esquema`` de ``PerfilDaTarefa``) -> o JSON Schema em modo estrito."""
