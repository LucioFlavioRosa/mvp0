# Telemetria DEVE ser inicializada antes de criar FastAPI app
# (caso contrario, auto-instrumentacao nao pega o app).
from app.core.telemetry import configure_telemetry
configure_telemetry()

import time
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

from app.bot_engine import BotEngine
from app.services.dispatch_service import DispatchService
from app.services.whatsapp_service import DEFAULT_TEMPLATE_LANGUAGE
from app.integrations.infobip import InfobipClient
from app.schemas.infobip_webhook import InfobipInboundPayload
from app.core.config import Settings
from app.core.telemetry import get_logger, mask_pii, correlation_id_middleware
from app.core import log_dimensions as ld

logger = get_logger(__name__)

# ==============================================================================
# 1. INICIALIZACAO
# ==============================================================================

app = FastAPI(title="Bot Aguas do Para", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
# 3. ROTAS
# ==============================================================================
@app.get("/")
def health_check():
    return {"status": "online", "environment": "Azure Production"}


@app.post("/bot")
async def chat_webhook(payload: InfobipInboundPayload, background_tasks: BackgroundTasks):
    """Webhook principal que recebe mensagens do WhatsApp via Infobip."""
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


@app.post("/api/dispatch")
async def dispatch_order(data: DispatchRequest):
    logger.info("dispatch recebido", extra={"custom_dimensions": {
        ld.OPERATION: "dispatch",
        ld.PEDIDO_ID: data.pedido_uuid,
        "parceiros_count": len(data.parceiros),
    }})
    try:
        result = dispatch_service.enviar_oferta_para_prestadores(data.parceiros, data.pedido_uuid)
        return result
    except Exception:
        logger.error("erro em dispatch", exc_info=True,
                     extra={"custom_dimensions": {
                         ld.OPERATION: "dispatch",
                         ld.PEDIDO_ID: data.pedido_uuid,
                     }})
        return {"status": "error", "message": "internal_error"}
