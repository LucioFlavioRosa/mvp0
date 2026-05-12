"""
Vocabulario canonico das custom dimensions usadas nos logs.

Usar essas constantes em vez de strings literais reduz typos e facilita
queries no Application Insights.
"""

# Identificadores (sempre hashed via mask_pii)
SENDER_HASH = "sender_hash"
PARCEIRO_HASH = "parceiro_hash"
PEDIDO_ID = "pedido_id"  # UUIDs nao sao PII, nao precisam mascarar

# Estado e fluxo
OPERATION = "operation"
STEP = "step"
STEP_FROM = "step_from"
STEP_TO = "step_to"
COMPONENT = "component"

# Performance
DURATION_MS = "duration_ms"

# Externa
EXTERNAL_SERVICE = "external_service"
EXTERNAL_STATUS = "external_status"

# Resultado
RESULT = "result"
ERROR_KIND = "error_kind"

# Mensagem
MESSAGE_TYPE = "message_type"
MESSAGE_LEN = "message_len"
TIPO = "tipo"

# Mocks e flags
MOCK = "mock"

# Configuracao faltante
MISSING_SECRETS = "missing_secrets"
