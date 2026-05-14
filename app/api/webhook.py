"""Webhook inbound do Infobip (POST /bot)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import verify_infobip_basic_auth
from app.core.rate_limit import limiter
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
from app.schemas.infobip_webhook import InfobipInboundPayload
from app.services.whatsapp_service import DEFAULT_TEMPLATE_LANGUAGE

logger = get_logger(__name__)

router = APIRouter()


@router.post("/bot", dependencies=[Depends(verify_infobip_basic_auth)])
@limiter.limit("30/minute")
async def chat_webhook(request: Request, payload: InfobipInboundPayload):
    """Webhook principal que recebe mensagens do WhatsApp via Infobip.

    Sequencias (com delays entre items) vao pra Storage Queue;
    sequence_worker (thread daemon) consome respeitando os delays.
    Mensagens unicas (texto/template/media) sao enviadas direto via cliente.
    """
    state = request.app.state
    bot = getattr(state, "bot", None)
    client = getattr(state, "infobip_client", None)
    sender_number = getattr(state, "sender_number", "")
    sequence_queue = getattr(state, "sequence_queue", None)

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

        # Sequencias vao pra Storage Queue (worker dedicado processa).
        if tipo == 'sequencia':
            if sequence_queue is not None:
                sequence_queue.enqueue(sender_id, resposta.get('mensagens', []))
            continue

        # combo_inicial = texto + template com delay; tambem vai pra queue
        # (antes tinha time.sleep(0.5) bloqueante no request path).
        if tipo == 'combo_inicial':
            combo_sequence = [
                {
                    'tipo': 'texto',
                    'conteudo': resposta['texto'],
                    'delay': 0,
                },
                {
                    'tipo': 'template',
                    'template_name': resposta.get('template_name') or resposta.get('template_sid') or resposta.get('sid'),
                    'language': resposta.get('language', DEFAULT_TEMPLATE_LANGUAGE),
                    'placeholders': resposta.get('placeholders') or [],
                    'delay': 0.5,
                },
            ]
            if sequence_queue is not None:
                sequence_queue.enqueue(sender_id, combo_sequence)
            continue

        try:
            if tipo == 'template':
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
