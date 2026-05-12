"""
Bootstrap de telemetria para Application Insights.

Configura azure-monitor-opentelemetry com auto-instrumentacao de:
- FastAPI (requests inbound)
- requests / httpx (HTTP outbound)
- pyodbc (SQL queries)

Tambem fornece:
- configure_telemetry() - chamado uma vez no startup
- get_logger(name) - logger por modulo
- mask_pii(value) - hash deterministico de identificadores PII
- correlation_id_middleware - injeta operation_id por request
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from contextvars import ContextVar
from typing import Any

_LOG_LEVEL_ENV = "LOG_LEVEL"
_DEFAULT_LOG_LEVEL = "INFO"

# Salt aplicado antes do hash. Rotacionavel via env var.
_PII_SALT = os.getenv("LOG_PII_SALT", "aguasdopara-default-salt")

# Context var pra operation_id (correlation ID)
_operation_id_var: ContextVar[str] = ContextVar("operation_id", default="")


def configure_telemetry() -> None:
    """Inicializa telemetria. Chamar UMA VEZ no startup, antes de criar a FastAPI app."""
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    level = os.getenv(_LOG_LEVEL_ENV, _DEFAULT_LOG_LEVEL).upper()

    if not conn_str:
        # Dev local sem App Insights: stdout estruturado.
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        logging.getLogger().addFilter(_OperationIdFilter())
        return

    # Importa apenas quando ha conn_str (evita erro em dev sem a dep)
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(
        connection_string=conn_str,
        instrumentation_options={
            "azure_sdk": {"enabled": True},
            "fastapi": {"enabled": True},
            "requests": {"enabled": True},
            "urllib3": {"enabled": True},
            "django": {"enabled": False},
            "flask": {"enabled": False},
        },
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addFilter(_OperationIdFilter())


def get_logger(name: str) -> logging.Logger:
    """Logger por modulo. Use logger = get_logger(__name__) no topo do arquivo."""
    return logging.getLogger(name)


def mask_pii(value: Any, length: int = 12) -> str:
    """Hash deterministico de identificador PII (CPF, CNPJ, WhatsApp ID, email).

    Mesmo input sempre gera o mesmo hash - permite correlacionar logs do mesmo
    usuario sem expor o identificador. Trunca em 12 chars hex.
    """
    if value is None or value == "":
        return "<empty>"
    raw = f"{_PII_SALT}|{value}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def get_operation_id() -> str:
    return _operation_id_var.get()


async def correlation_id_middleware(request, call_next):
    """Atribui operation_id por request - registrar via app.middleware('http')."""
    op_id = request.headers.get("x-operation-id") or str(uuid.uuid4())
    token = _operation_id_var.set(op_id)
    try:
        response = await call_next(request)
        response.headers["x-operation-id"] = op_id
        return response
    finally:
        _operation_id_var.reset(token)


class _OperationIdFilter(logging.Filter):
    """Adiciona operation_id automaticamente em toda LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        cd = getattr(record, "custom_dimensions", None) or {}
        cd.setdefault("operation_id", _operation_id_var.get() or "no-operation")
        record.custom_dimensions = cd
        return True
