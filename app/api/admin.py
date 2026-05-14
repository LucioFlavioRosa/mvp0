"""Endpoints administrativos para inspecao e retry da DLQ."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import verify_admin_basic_auth, executar_retry_dlq
from app.core.rate_limit import limiter
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)

router = APIRouter(prefix="/admin")


def _require_dlq(request: Request):
    """Retorna o DLQClient do app.state ou levanta 503.

    Compartilhado pelos endpoints admin para evitar AttributeError
    silencioso caso DLQClient nao tenha inicializado no startup.
    """
    dlq = getattr(request.app.state, "dlq", None)
    if dlq is None:
        logger.critical(
            "endpoint admin acessado mas DLQClient offline",
            extra={"custom_dimensions": {ld.OPERATION: "admin_dlq"}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dlq client offline",
        )
    return dlq


@router.get("/dlq", dependencies=[Depends(verify_admin_basic_auth)])
@limiter.limit("20/minute")
def admin_dlq_list(request: Request, limit: int = 32):
    """Lista (peek) ate 32 mensagens pendentes na DLQ. Read-only.

    503 se DLQClient nao inicializou no startup (fail-safe).
    """
    dlq = _require_dlq(request)
    limit = max(1, min(limit, 32))
    messages = dlq.peek(max_messages=limit)
    logger.info("admin listou DLQ", extra={"custom_dimensions": {
        ld.OPERATION: "admin_dlq_list",
        "count": len(messages),
    }})
    return {"count": len(messages), "messages": messages}


@router.post("/dlq/retry/{message_id}", dependencies=[Depends(verify_admin_basic_auth)])
@limiter.limit("20/minute")
def admin_dlq_retry(request: Request, message_id: str):
    """Re-executa UMA mensagem da DLQ por ID e deleta no final.

    Politica:
    - 1 unica tentativa manual por mensagem.
    - Delete OBRIGATORIO independente do resultado (sucesso ou falha) -
      evita fila poluida com mensagens fantasmas re-tentando sozinhas.
    - 503 se DLQClient nao inicializou no startup (fail-safe).
    """
    dlq = _require_dlq(request)
    received = dlq.receive_by_id(message_id)
    if received is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="mensagem nao encontrada (pode ter expirado, sido deletada, ou estar com visibility timeout ativo)",
        )

    result = executar_retry_dlq(request, received["content"])
    deleted = dlq.delete(received["id"], received["pop_receipt"])

    logger.info("admin retry DLQ", extra={"custom_dimensions": {
        ld.OPERATION: "admin_dlq_retry",
        "message_id": message_id,
        "target_operation": received["content"].get("operation"),
        ld.RESULT: "success" if result["success"] else "failed",
        "deleted": deleted,
    }})

    return {
        "message_id": message_id,
        "retry_success": result["success"],
        "retry_error": result["error"],
        "deleted": deleted,
    }
