"""Dependencias compartilhadas pelos routers em app/api/.

Inclui:
- Schemes de auth: HTTPBasic do webhook Infobip, HTTPBasic do admin DLQ,
  Bearer JWT do Azure AD para dispatch.
- Funcoes verify_* que validam credentials e retornam None/User.
- Helper _executar_retry_dlq usado pelo admin retry endpoint.
- Schema Pydantic DispatchRequest.

Todos buscam singletons via request.app.state (settings, infobip_client,
blob_service, etc) - main.py popula esses no startup.
"""

from __future__ import annotations

import secrets
from typing import List

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from app.core.azure_auth import get_azure_scheme, get_init_error
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------
class DispatchRequest(BaseModel):
    pedido_uuid: str
    parceiros: List[str]


# ---------------------------------------------------------------------------
# Auth: webhook Infobip (Basic Auth)
# ---------------------------------------------------------------------------
# A Infobip envia Authorization: Basic <base64(user:password)> em todo
# webhook inbound, conforme configurado no portal. Validamos com
# secrets.compare_digest (constant-time, previne timing attacks).
# Fail-safe: secrets ausentes -> 503 + log critical.
_basic_auth = HTTPBasic(auto_error=True)


def verify_infobip_basic_auth(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(_basic_auth),
) -> None:
    settings = request.app.state.settings
    expected_user = settings.get_secret("INFOBIP-WEBHOOK-USER")
    expected_password = settings.get_secret("INFOBIP-WEBHOOK-PASSWORD")

    if not expected_user or not expected_password:
        logger.critical(
            "credenciais do webhook nao configuradas",
            extra={"custom_dimensions": {
                ld.OPERATION: "webhook_auth",
                ld.MISSING_SECRETS: [
                    k for k, v in {
                        "INFOBIP-WEBHOOK-USER": expected_user,
                        "INFOBIP-WEBHOOK-PASSWORD": expected_password,
                    }.items() if not v
                ],
            }},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook auth not configured",
        )

    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_user.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )

    if not (user_ok and password_ok):
        logger.warning(
            "tentativa de acesso ao webhook com credenciais invalidas",
            extra={"custom_dimensions": {
                ld.OPERATION: "webhook_auth",
                ld.RESULT: "unauthorized",
            }},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


# ---------------------------------------------------------------------------
# Auth: endpoints admin (Basic Auth separada)
# ---------------------------------------------------------------------------
_admin_basic_auth = HTTPBasic(auto_error=True)


def verify_admin_basic_auth(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(_admin_basic_auth),
) -> None:
    settings = request.app.state.settings
    expected_user = settings.get_secret("ADMIN-USER")
    expected_password = settings.get_secret("ADMIN-PASSWORD")

    if not expected_user or not expected_password:
        logger.critical(
            "credenciais admin nao configuradas",
            extra={"custom_dimensions": {
                ld.OPERATION: "admin_auth",
                ld.MISSING_SECRETS: [
                    k for k, v in {
                        "ADMIN-USER": expected_user,
                        "ADMIN-PASSWORD": expected_password,
                    }.items() if not v
                ],
            }},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin auth not configured",
        )

    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_user.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )

    if not (user_ok and password_ok):
        logger.warning(
            "tentativa de acesso admin com credenciais invalidas",
            extra={"custom_dimensions": {
                ld.OPERATION: "admin_auth",
                ld.RESULT: "unauthorized",
            }},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


# ---------------------------------------------------------------------------
# Auth: /api/dispatch via Azure AD JWT (Bearer)
# ---------------------------------------------------------------------------
# Scheme pode ser None se AZURE-AD-TENANT-ID ou AZURE-AD-API-CLIENT-ID
# estiverem ausentes no Key Vault. Nesse caso fail-safe: 503 + log critical.
_azure_scheme_instance = get_azure_scheme()


async def verify_dispatch_auth(request: Request):
    """Wrapper fail-safe do Azure AD scheme.

    - Se scheme nao inicializado (secrets ausentes): 503 + log critical
    - Se token ausente/invalido/expirado: 401 (fastapi-azure-auth levanta)
    - Se OK: retorna User com claims validados (oid, email, name, scp)
    """
    if _azure_scheme_instance is None:
        err = get_init_error() or "Azure AD scheme nao inicializado"
        logger.critical(
            "dispatch auth nao configurada",
            extra={"custom_dimensions": {
                ld.OPERATION: "dispatch_auth",
                "init_error": err,
            }},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dispatch auth not configured",
        )
    return await _azure_scheme_instance(request)


# ---------------------------------------------------------------------------
# Helper: executa retry de UMA mensagem da DLQ
# ---------------------------------------------------------------------------
def executar_retry_dlq(request: Request, content: dict) -> dict:
    """Re-executa uma operacao falhada com base no payload da DLQ.

    Retorna {success: bool, error: str | None}. NUNCA propaga excecao -
    o endpoint sempre precisa chegar no delete obrigatorio.
    """
    state = request.app.state
    infobip_client = getattr(state, "infobip_client", None)

    operation = content.get("operation")
    external_service = content.get("external_service")
    payload = content.get("payload") or {}

    try:
        if external_service == "infobip" and operation in {"send_text", "send_image", "send_template"}:
            if infobip_client is None:
                return {"success": False, "error": "infobip client offline"}
            path = payload.get("path")
            body = payload.get("body")
            if not path or not body:
                return {"success": False, "error": "payload incompleto (path/body)"}
            infobip_client._post(path, body)
            return {"success": True, "error": None}

        if operation == "download_media":
            media_url = payload.get("media_url")
            container_name = payload.get("container_name")
            blob_name = payload.get("blob_name")
            if not (media_url and container_name and blob_name):
                return {"success": False, "error": "payload incompleto (media_url/container_name/blob_name)"}
            blob_service = _get_blob_service(request)
            blob_url = blob_service.upload_from_url(media_url, container_name, blob_name)
            if blob_url is None:
                return {"success": False, "error": "upload_from_url retornou None"}
            return {"success": True, "error": None}

        return {"success": False, "error": f"operation nao suportada: {operation}"}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _get_blob_service(request: Request):
    """Lazy-init do AzureBlobService em app.state (so cria quando precisa)."""
    state = request.app.state
    if not hasattr(state, "blob_service") or state.blob_service is None:
        from app.services.azure_blob_service import AzureBlobService
        state.blob_service = AzureBlobService()
    return state.blob_service


# ---------------------------------------------------------------------------
# State accessors (Depends-friendly): extraem singletons do app.state.
#
# Vantagens vs `request.app.state.X` direto no handler:
# - Validacao "esta inicializado?" centralizada em UM lugar (DRY).
# - Routers ficam testaveis via mocker.dependency_overrides[get_X] = mock,
#   sem precisar tocar em app.state durante o teste.
# - Assinatura da rota declara dependencias explicitamente.
#
# Cada getter levanta HTTPException 503 se a dependencia for None (startup
# falhou). Sequence_queue eh excecao: enqueue eh fail-safe, retorna None.
# ---------------------------------------------------------------------------
def get_settings(request: Request):
    """Retorna o Settings (Key Vault wrapper). Sempre populado no startup."""
    return request.app.state.settings


def get_bot(request: Request):
    """Retorna o BotEngine ou 503 se nao inicializou."""
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        logger.critical(
            "BotEngine offline (falhou no startup)",
            extra={"custom_dimensions": {ld.OPERATION: "get_bot"}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="bot offline",
        )
    return bot


def get_dispatch_service(request: Request):
    """Retorna o DispatchService ou 503 se nao inicializou."""
    svc = getattr(request.app.state, "dispatch_service", None)
    if svc is None:
        logger.critical(
            "DispatchService offline (falhou no startup)",
            extra={"custom_dimensions": {ld.OPERATION: "get_dispatch_service"}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dispatch service offline",
        )
    return svc


def get_infobip_client(request: Request):
    """Retorna o InfobipClient ou 503 se nao inicializou."""
    client = getattr(request.app.state, "infobip_client", None)
    if client is None:
        logger.critical(
            "InfobipClient offline (credenciais ausentes ou erro no startup)",
            extra={"custom_dimensions": {ld.OPERATION: "get_infobip_client"}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="infobip client offline",
        )
    return client


def get_dlq(request: Request):
    """Retorna o DLQClient ou 503 se nao inicializou."""
    dlq = getattr(request.app.state, "dlq", None)
    if dlq is None:
        logger.critical(
            "DLQClient offline (Storage Queue indisponivel no startup)",
            extra={"custom_dimensions": {ld.OPERATION: "get_dlq"}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dlq client offline",
        )
    return dlq


def get_sequence_queue(request: Request):
    """Retorna o SequenceQueueClient ou None.

    Diferente dos outros getters, NAO levanta 503 se ausente - enqueue
    eh fire-and-forget e o handler ja checa `if sequence_queue is not None`.
    Permite o webhook continuar funcionando mesmo sem queue (rara: storage
    indisponivel durante startup mas voltou depois).
    """
    return getattr(request.app.state, "sequence_queue", None)


def get_sender_number(request: Request) -> str:
    return getattr(request.app.state, "sender_number", "")
