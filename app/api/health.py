"""Liveness e readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.core import health
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)

router = APIRouter()


@router.get("/")
def health_check():
    """Liveness probe: responde 200 enquanto o processo esta vivo.

    NAO checa dependencias - se DB ou Storage caem, o processo continua
    rodando e atendendo /, mas /health/ready deve falhar.
    """
    return {"status": "online", "environment": "Azure Production"}


@router.get("/health/ready")
def health_ready(request: Request, response: Response):
    """Readiness probe: checa todas as dependencias criticas.

    - SQL via SELECT 1
    - InfobipClient inicializado + sender configurado
    - Storage Queue acessivel (DLQ)
    - Key Vault acessivel (le secret sentinel)

    Retorna 200 se TODOS os checks OK; 503 se qualquer um falhar.
    Sem auth: readiness probe do App Service nao envia credentials.
    """
    state = request.app.state
    bot = getattr(state, "bot", None)
    infobip_client = getattr(state, "infobip_client", None)
    sender_number = getattr(state, "sender_number", "")
    dlq = getattr(state, "dlq", None)
    settings = getattr(state, "settings", None)

    checks = {
        "sql": health.check_database(bot.db) if bot else health._down("sql", "BotEngine nao inicializado", 0),
        "infobip": health.check_infobip(infobip_client, sender_number),
        "storage": health.check_storage(dlq),
        "keyvault": health.check_keyvault(settings),
    }

    all_ok = all(c["status"] == "ok" for c in checks.values())
    overall_status = "ok" if all_ok else "degraded"
    total_duration = sum(c["duration_ms"] for c in checks.values())

    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        failed = [name for name, c in checks.items() if c["status"] != "ok"]
        logger.warning("health/ready degradado", extra={"custom_dimensions": {
            ld.OPERATION: "health_ready",
            ld.RESULT: "degraded",
            "failed_checks": failed,
            ld.DURATION_MS: total_duration,
        }})

    return {
        "status": overall_status,
        "checks": checks,
        "duration_ms": total_duration,
    }
