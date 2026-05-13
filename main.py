# Telemetria DEVE ser inicializada antes de criar FastAPI app
# (caso contrario, auto-instrumentacao nao pega o app).
from app.core.telemetry import configure_telemetry
configure_telemetry()

import os
import secrets
import time
from fastapi import Depends, FastAPI, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import List

from app.bot_engine import BotEngine
from app.services.dispatch_service import DispatchService
from app.services.whatsapp_service import DEFAULT_TEMPLATE_LANGUAGE
from app.services.azure_blob_service import AzureBlobService
from app.integrations.infobip import InfobipClient
from app.integrations.dlq import DLQClient
from app.schemas.infobip_webhook import InfobipInboundPayload
from app.core.config import Settings
from app.core.telemetry import get_logger, mask_pii, correlation_id_middleware
from app.core import log_dimensions as ld
from app.core import health
from app.core.azure_auth import get_azure_scheme, get_init_error
from app.core.rate_limit import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

logger = get_logger(__name__)

# ==============================================================================
# 1. INICIALIZACAO
# ==============================================================================

app = FastAPI(title="Bot Aguas do Para", version="1.0.0")

# Rate limit (slowapi com Redis - ver app/core/rate_limit.py)
# Decorators @limiter.limit("X/min") aplicados nos endpoints abaixo.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS apertado: le lista de origens permitidas da env var ALLOWED_ORIGINS
# (comma-separated). Sem env var configurada, lista vazia (= bloqueia todas
# as origens cross-site, mas backend continua funcionando para requests
# server-to-server sem header Origin).
#
# Origens validas devem ser as URLs HTTPS dos App Services do backoffice:
#   ALLOWED_ORIGINS="https://backoffice-aegea-prod.azurewebsites.net,https://backoffice-aegea-staging.azurewebsites.net,https://backoffice-aegea-dev.azurewebsites.net"
#
# NAO usar wildcard *.azurewebsites.net - qualquer um pode criar
# subdominio Azure e contornar o CORS.
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
if _allowed_origins_raw:
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]
    logger.info("CORS configurado", extra={"custom_dimensions": {
        ld.OPERATION: "startup",
        ld.COMPONENT: "cors",
        "origins_count": len(_allowed_origins),
    }})
else:
    _allowed_origins = []
    logger.critical(
        "ALLOWED_ORIGINS nao configurado - CORS bloqueia TODAS as origens",
        extra={"custom_dimensions": {
            ld.OPERATION: "startup",
            ld.COMPONENT: "cors",
        }},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.middleware("http")(correlation_id_middleware)

settings = Settings()

try:
    bot = BotEngine()
    dispatch_service = DispatchService()
    logger.info("motores inicializados", extra={"custom_dimensions": {
        ld.OPERATION: "startup", ld.COMPONENT: "engines",
    }})
except Exception:
    logger.critical("falha critica ao iniciar motores", exc_info=True,
                    extra={"custom_dimensions": {ld.OPERATION: "startup"}})

try:
    api_key = settings.get_secret("INFOBIP-API-KEY")
    base_url = settings.get_secret("INFOBIP-BASE-URL")
    sender_number = settings.get_secret("INFOBIP-SENDER") or ""

    if api_key and base_url and sender_number:
        client = InfobipClient(api_key=api_key, base_url=base_url)
        logger.info("cliente Infobip autenticado", extra={"custom_dimensions": {
            ld.OPERATION: "startup", ld.COMPONENT: "infobip",
        }})
    else:
        client = None
        missing = [k for k, v in {
            "INFOBIP-API-KEY": api_key,
            "INFOBIP-BASE-URL": base_url,
            "INFOBIP-SENDER": sender_number,
        }.items() if not v]
        logger.warning("credenciais Infobip ausentes", extra={"custom_dimensions": {
            ld.OPERATION: "startup", ld.MISSING_SECRETS: missing,
        }})
except Exception:
    client = None
    logger.error("erro ao iniciar Infobip", exc_info=True,
                 extra={"custom_dimensions": {ld.OPERATION: "startup"}})


class DispatchRequest(BaseModel):
    pedido_uuid: str
    parceiros: List[str]


# ==============================================================================
# 2. BACKGROUND
# ==============================================================================
def enviar_sequencia_background(mensagens, sender_id):
    """Processa lista de mensagens com delay, sem travar a resposta HTTP."""
    if not client:
        logger.warning("background: cliente Infobip offline",
                       extra={"custom_dimensions": {ld.OPERATION: "send_sequence"}})
        return

    try:
        for item in mensagens:
            time.sleep(item.get('delay', 1.0))
            tipo = item.get('tipo')
            if tipo == 'texto':
                client.send_text(sender=sender_number, to=sender_id, text=item['conteudo'])
            elif tipo == 'media':
                client.send_image(
                    sender=sender_number,
                    to=sender_id,
                    media_url=item['url'],
                    caption=item.get('legenda') or None,
                )
            elif tipo == 'template':
                client.send_template(
                    sender=sender_number,
                    to=sender_id,
                    template_name=item.get('template_name') or item.get('sid'),
                    language=item.get('language', DEFAULT_TEMPLATE_LANGUAGE),
                    placeholders=item.get('placeholders') or [],
                )
    except Exception:
        logger.error("falha no envio em background", exc_info=True,
                     extra={"custom_dimensions": {
                         ld.OPERATION: "send_sequence",
                         ld.SENDER_HASH: mask_pii(sender_id),
                     }})


# ==============================================================================
# 3. AUTENTICACAO DO WEBHOOK INFOBIP
# ==============================================================================
# A Infobip envia o header Authorization: Basic <base64(user:password)> em todo
# webhook inbound, conforme configurado no portal (perfil de seguranca Basic Auth).
# Validamos com secrets.compare_digest (constant-time, previne timing attacks).
#
# Fail-safe: se as credenciais nao estiverem configuradas no Key Vault, bloqueamos
# TUDO com 503 + log critical. Sem auth configurada == sem servico.
_basic_auth = HTTPBasic(auto_error=True)


def verify_infobip_basic_auth(
    credentials: HTTPBasicCredentials = Depends(_basic_auth),
) -> None:
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


# ==============================================================================
# 3.1 AUTENTICACAO DOS ENDPOINTS ADMIN (DLQ)
# ==============================================================================
# Endpoints admin (GET /admin/dlq, POST /admin/dlq/retry/...) usam credenciais
# SEPARADAS do webhook Infobip (ADMIN-USER / ADMIN-PASSWORD no Key Vault).
# Mesma logica fail-safe: secrets ausentes -> 503; credenciais invalidas -> 401.
_admin_basic_auth = HTTPBasic(auto_error=True)


def verify_admin_basic_auth(
    credentials: HTTPBasicCredentials = Depends(_admin_basic_auth),
) -> None:
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


# DLQClient singleton para os endpoints admin. Compartilha a mesma fila
# que InfobipClient / AzureBlobService usam pra enfileirar.
_dlq = DLQClient()

# AzureBlobService lazy - so instancia quando endpoint admin precisa fazer
# retry de download_media. Evita acoplamento extra no startup.
_blob_service: AzureBlobService | None = None


def _get_blob_service() -> AzureBlobService:
    global _blob_service
    if _blob_service is None:
        _blob_service = AzureBlobService()
    return _blob_service


def _executar_retry_dlq(content: dict) -> dict:
    """Re-executa uma operacao falhada com base no payload da DLQ.

    Retorna {"success": bool, "error": str | None}. NUNCA propaga excecao -
    o endpoint sempre precisa chegar no delete obrigatorio.
    """
    operation = content.get("operation")
    external_service = content.get("external_service")
    payload = content.get("payload") or {}

    try:
        if external_service == "infobip" and operation in {"send_text", "send_image", "send_template"}:
            if client is None:
                return {"success": False, "error": "infobip client offline"}
            # Re-emite via _post direto - mesma payload e path que falhou antes
            path = payload.get("path")
            body = payload.get("body")
            if not path or not body:
                return {"success": False, "error": "payload incompleto (path/body)"}
            client._post(path, body)
            return {"success": True, "error": None}

        if operation == "download_media":
            media_url = payload.get("media_url")
            container_name = payload.get("container_name")
            blob_name = payload.get("blob_name")
            if not (media_url and container_name and blob_name):
                return {"success": False, "error": "payload incompleto (media_url/container_name/blob_name)"}
            blob_url = _get_blob_service().upload_from_url(media_url, container_name, blob_name)
            if blob_url is None:
                return {"success": False, "error": "upload_from_url retornou None"}
            return {"success": True, "error": None}

        return {"success": False, "error": f"operation nao suportada: {operation}"}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


# ==============================================================================
# 4. ROTAS
# ==============================================================================
@app.get("/")
def health_check():
    """Liveness probe: responde 200 enquanto o processo esta vivo.

    NAO checa dependencias - se DB ou Storage caem, o processo continua
    rodando e atendendo /, mas /health/ready deve falhar.
    """
    return {"status": "online", "environment": "Azure Production"}


@app.get("/health/ready")
def health_ready(response: Response):
    """Readiness probe: checa todas as dependencias criticas.

    - SQL via SELECT 1
    - InfobipClient inicializado + sender configurado
    - Storage Queue acessivel (DLQ)
    - Key Vault acessivel (le secret sentinel)

    Retorna 200 se TODOS os checks OK; 503 se qualquer um falhar.
    Body inclui detalhes de cada check em ambos os casos - permite
    dashboard mostrar qual dependencia esta com problema.

    Sem auth: readiness probe do App Service nao envia credentials.
    """
    checks = {
        "sql": health.check_database(bot.db) if bot else health._down("sql", "BotEngine nao inicializado", 0),
        "infobip": health.check_infobip(client, sender_number),
        "storage": health.check_storage(_dlq),
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


@app.post("/bot", dependencies=[Depends(verify_infobip_basic_auth)])
@limiter.limit("30/minute")
async def chat_webhook(request: Request, payload: InfobipInboundPayload, background_tasks: BackgroundTasks):
    """Webhook principal que recebe mensagens do WhatsApp via Infobip.

    Autenticado via Basic Auth (configurado no portal Infobip + Key Vault).
    """
    for result in payload.results:
        sender_id = result.sender
        message_body = ""
        media_url = None

        if result.message.type == "TEXT":
            message_body = result.message.text.strip()
        elif result.message.type == "IMAGE":
            media_url = result.message.url
            message_body = (result.message.caption or "").strip()

        logger.info("webhook inbound", extra={"custom_dimensions": {
            ld.OPERATION: "webhook_inbound",
            ld.SENDER_HASH: mask_pii(sender_id),
            ld.MESSAGE_TYPE: result.message.type,
            ld.MESSAGE_LEN: len(message_body),
        }})

        try:
            resposta = bot.processar_mensagem(sender_id, message_body, media_url)
        except Exception:
            logger.error("erro no bot engine", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "process_message",
                             ld.SENDER_HASH: mask_pii(sender_id),
                         }})
            continue

        if not client:
            logger.warning("cliente Infobip offline - sem resposta",
                           extra={"custom_dimensions": {
                               ld.OPERATION: "webhook_inbound",
                               ld.SENDER_HASH: mask_pii(sender_id),
                           }})
            continue

        tipo = resposta.get('tipo')

        if tipo == 'sequencia':
            background_tasks.add_task(
                enviar_sequencia_background,
                resposta.get('mensagens', []),
                sender_id,
            )
            continue

        try:
            if tipo == 'combo_inicial':
                client.send_text(
                    sender=sender_number,
                    to=sender_id,
                    text=resposta['texto'],
                )
                time.sleep(0.5)
                client.send_template(
                    sender=sender_number,
                    to=sender_id,
                    template_name=resposta.get('template_name') or resposta.get('template_sid') or resposta.get('sid'),
                    language=resposta.get('language', DEFAULT_TEMPLATE_LANGUAGE),
                    placeholders=resposta.get('placeholders') or [],
                )
            elif tipo == 'template':
                client.send_template(
                    sender=sender_number,
                    to=sender_id,
                    template_name=resposta.get('template_name') or resposta.get('template_sid') or resposta.get('sid'),
                    language=resposta.get('language', DEFAULT_TEMPLATE_LANGUAGE),
                    placeholders=resposta.get('placeholders') or [],
                )
            elif tipo == 'texto':
                client.send_text(
                    sender=sender_number,
                    to=sender_id,
                    text=resposta['conteudo'],
                )
            elif tipo == 'media':
                client.send_image(
                    sender=sender_number,
                    to=sender_id,
                    media_url=resposta['url'],
                    caption=resposta.get('legenda') or None,
                )
        except Exception:
            logger.error("falha no envio outbound via Infobip", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "send_response",
                             ld.TIPO: tipo,
                             ld.SENDER_HASH: mask_pii(sender_id),
                         }})

    return {"status": "ok"}


@app.get("/admin/dlq", dependencies=[Depends(verify_admin_basic_auth)])
@limiter.limit("20/minute")
def admin_dlq_list(request: Request, limit: int = 32):
    """Lista (peek) ate 32 mensagens pendentes na DLQ. NAO remove nem altera
    visibilidade - operacao read-only segura pra inspecao.
    """
    limit = max(1, min(limit, 32))
    messages = _dlq.peek(max_messages=limit)
    logger.info("admin listou DLQ", extra={"custom_dimensions": {
        ld.OPERATION: "admin_dlq_list",
        "count": len(messages),
    }})
    return {"count": len(messages), "messages": messages}




@app.post("/admin/dlq/retry/{message_id}", dependencies=[Depends(verify_admin_basic_auth)])
@limiter.limit("20/minute")
def admin_dlq_retry(request: Request, message_id: str):
    """Re-executa UMA mensagem da DLQ por ID e deleta no final.

    Politica (alinhada com pedido do user):
    - 1 unica tentativa manual por mensagem.
    - Delete OBRIGATORIO independente do resultado (sucesso ou falha) -
      evita fila poluida com mensagens fantasmas re-tentando sozinhas.
    - Resultado retornado ao admin pra eventual nova analise/escalonamento
      humano fora da fila (ex: ticket).
    """
    received = _dlq.receive_by_id(message_id)
    if received is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="mensagem nao encontrada (pode ter expirado, sido deletada, ou estar com visibility timeout ativo)",
        )

    result = _executar_retry_dlq(received["content"])
    deleted = _dlq.delete(received["id"], received["pop_receipt"])

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


# ==============================================================================
# 4.1 AUTH DO /api/dispatch VIA AZURE AD
# ==============================================================================
# Auth dependency wrapper: o scheme pode ser None se AZURE-AD-TENANT-ID ou
# AZURE-AD-API-CLIENT-ID estiverem ausentes no Key Vault. Nesse caso fail-safe:
# 503 + log critical (sem auth configurada == sem dispatch).
#
# Quando scheme esta inicializado, retorna o User do fastapi-azure-auth com
# claims validados (oid, email, name, scp, etc).
_azure_scheme_instance = get_azure_scheme()




async def verify_dispatch_auth(request: Request):
    """Wrapper fail-safe do Azure AD scheme.

    - Se scheme nao inicializado (secrets ausentes): 503 + log critical
    - Se token ausente/invalido/expirado: 401 (fastapi-azure-auth levanta)
    - Se OK: retorna User com claims validados
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


@app.post("/api/dispatch")
@limiter.limit("10/minute")
async def dispatch_order(request: Request, data: DispatchRequest, user=Depends(verify_dispatch_auth)):
    """Disparo de oferta a parceiros via WhatsApp.

    Auth: Bearer JWT do Azure AD (tenant Aegea). Operador autentica via SSO
    no backoffice (MSAL.js), backoffice envia token delegado nesta chamada.
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
