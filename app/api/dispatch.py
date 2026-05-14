"""Dispatch de oferta a parceiros (POST /api/dispatch).

Auth: Bearer JWT do Azure AD (tenant Aegea). Operador autentica via SSO
no backoffice (MSAL.js), backoffice envia token delegado nesta chamada.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    DispatchRequest,
    get_dispatch_service,
    verify_dispatch_auth,
)
from app.core.rate_limit import limiter
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld

logger = get_logger(__name__)

router = APIRouter(prefix="/api")


@router.post("/dispatch")
@limiter.limit("10/minute")
async def dispatch_order(
    request: Request,
    data: DispatchRequest,
    user=Depends(verify_dispatch_auth),
    dispatch_service=Depends(get_dispatch_service),
):
    """Dispara oferta de servico a uma lista de parceiros via WhatsApp.

    Body: {pedido_uuid: str, parceiros: list[str]}. Operador identificado
    pelas claims oid + preferred_username do JWT (mascaradas no log).
    get_dispatch_service levanta 503 se DispatchService nao inicializou.
    """
    operator_oid = user.claims.get("oid", "unknown") if user else "unknown"
    operator_email = user.claims.get("preferred_username") or user.claims.get("email", "unknown")

    logger.info("dispatch recebido", extra={"custom_dimensions": {
        ld.OPERATION: "dispatch",
        ld.PEDIDO_ID: data.pedido_uuid,
        "parceiros_count": len(data.parceiros),
        "operator_oid": operator_oid,
        ld.SENDER_HASH: mask_pii(operator_email),
    }})

    try:
        result = dispatch_service.enviar_oferta_para_prestadores(data.parceiros, data.pedido_uuid)
        return result
    except Exception:
        logger.error("erro em dispatch", exc_info=True,
                     extra={"custom_dimensions": {
                         ld.OPERATION: "dispatch",
                         ld.PEDIDO_ID: data.pedido_uuid,
                         "operator_oid": operator_oid,
                     }})
        return {"status": "error", "message": "internal_error"}
