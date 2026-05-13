"""Health checks das dependencias da aplicacao.

Funcoes puras (recebem o cliente, retornam dict). Sem retry, sem logging
em sucesso (health check roda toda hora - poluiria os logs). Apenas
WARNING quando degradado.

Contrato de retorno de cada check_*:
    {
        "status": "ok" | "down",
        "detail": str,         # mensagem curta pra dashboards
        "duration_ms": int,    # tempo do check
    }

Usado pelo endpoint /health/ready em main.py.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


def _now_ms() -> float:
    return time.perf_counter() * 1000


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
def check_database(db: Any) -> dict[str, Any]:
    """Ping no Azure SQL via SELECT 1.

    Pega: cold start (Serverless), firewall mal configurado, credentials
    erradas, ODBC driver ausente, network blocking.
    """
    start = _now_ms()
    try:
        row = db.execute_read_one("SELECT 1", ())
        duration = int(_now_ms() - start)
        if row is None:
            return _down("sql", "SELECT 1 retornou None (conexao falhou silenciosamente)", duration)
        return {"status": "ok", "detail": "SELECT 1 OK", "duration_ms": duration}
    except Exception as exc:
        duration = int(_now_ms() - start)
        return _down("sql", f"{type(exc).__name__}: {str(exc)[:120]}", duration)


# ---------------------------------------------------------------------------
# Infobip
# ---------------------------------------------------------------------------
def check_infobip(client: Any, sender_number: str) -> dict[str, Any]:
    """Confere que o InfobipClient foi inicializado e tem sender configurado.

    NAO pinga a API Infobip real - testaria a rede deles, nao a nossa.
    O retry transient + DLQ cobrem falhas transient da API em runtime.
    """
    start = _now_ms()

    if client is None:
        return _down("infobip", "InfobipClient nao inicializado (secrets ausentes ou erro no startup)", int(_now_ms() - start))

    if not sender_number:
        return _down("infobip", "INFOBIP-SENDER vazio (mensagens outbound nao funcionariam)", int(_now_ms() - start))

    return {
        "status": "ok",
        "detail": f"client inicializado, sender={sender_number[:4]}...{sender_number[-2:]}",
        "duration_ms": int(_now_ms() - start),
    }


# ---------------------------------------------------------------------------
# Storage Queue (DLQ)
# ---------------------------------------------------------------------------
def check_storage(dlq: Any) -> dict[str, Any]:
    """Ping leve no Azure Storage Queue via get_queue_properties.

    Pega: connection string errada, fila inexistente (apesar do
    create_queue idempotente no startup), credentials Storage Account
    invalidas, network blocking.
    """
    start = _now_ms()

    if dlq is None or dlq.queue is None:
        return _down("storage", "DLQClient.queue=None (connection string ausente ou erro no startup)", int(_now_ms() - start))

    try:
        # get_queue_properties eh light - so retorna metadata
        dlq.queue.get_queue_properties()
        duration = int(_now_ms() - start)
        return {"status": "ok", "detail": "Storage Queue acessivel", "duration_ms": duration}
    except Exception as exc:
        duration = int(_now_ms() - start)
        return _down("storage", f"{type(exc).__name__}: {str(exc)[:120]}", duration)


# ---------------------------------------------------------------------------
# Key Vault
# ---------------------------------------------------------------------------
def check_keyvault(settings: Any, sentinel_secret: str = "INFOBIP-API-KEY") -> dict[str, Any]:
    """Tenta ler um secret arbitrario do Key Vault.

    Settings tem cache local - na maioria das chamadas isso eh in-memory
    e rapido. Mas se Settings cair (Managed Identity revogada, Key Vault
    inacessivel), o caminho de get_secret levanta.

    Reutilizamos INFOBIP-API-KEY como sentinel - eh um secret que sempre
    existe em qualquer ambiente bem configurado.
    """
    start = _now_ms()
    try:
        value = settings.get_secret(sentinel_secret)
        duration = int(_now_ms() - start)
        if not value:
            return _down("keyvault", f"secret '{sentinel_secret}' ausente ou vazio", duration)
        return {"status": "ok", "detail": "Key Vault acessivel", "duration_ms": duration}
    except Exception as exc:
        duration = int(_now_ms() - start)
        return _down("keyvault", f"{type(exc).__name__}: {str(exc)[:120]}", duration)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _down(component: str, detail: str, duration_ms: int) -> dict[str, Any]:
    """Helper para retornar status down com log estruturado."""
    logger.warning(
        f"health check degradado: {component}",
        extra={"custom_dimensions": {
            ld.OPERATION: "health_check",
            ld.COMPONENT: component,
            ld.RESULT: "down",
            ld.DURATION_MS: duration_ms,
            "detail": detail,
        }},
    )
    return {"status": "down", "detail": detail, "duration_ms": duration_ms}
