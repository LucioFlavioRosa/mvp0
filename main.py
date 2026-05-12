import time
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

# Imports da sua aplicação (Certifique-se que as pastas app/ existem)
from app.bot_engine import BotEngine
from app.services.dispatch_service import DispatchService
from app.services.whatsapp_service import DEFAULT_TEMPLATE_LANGUAGE
from app.integrations.infobip import InfobipClient
from app.schemas.infobip_webhook import InfobipInboundPayload
from app.core.config import Settings

# ==============================================================================
# 1. INICIALIZAÇÃO E VARIÁVEIS DE AMBIENTE
# ==============================================================================

app = FastAPI(title="Bot Águas do Pará", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = Settings()

try:
    bot = BotEngine()
    dispatch_service = DispatchService()
    print("OK Motores inicializados (BotEngine e DispatchService).")
except Exception as e:
    print(f"ERRO critico ao iniciar motores: {e}")

try:
    api_key = settings.get_secret("INFOBIP-API-KEY")
    base_url = settings.get_secret("INFOBIP-BASE-URL")
    sender_number = settings.get_secret("INFOBIP-SENDER") or ""

    if api_key and base_url and sender_number:
        client = InfobipClient(api_key=api_key, base_url=base_url)
        print("OK Cliente Infobip autenticado.")
    else:
        client = None
        print("AVISO: Credenciais Infobip nao encontradas no Key Vault.")
except Exception as e:
    client = None
    print(f"ERRO ao iniciar Infobip: {e}")


class DispatchRequest(BaseModel):
    pedido_uuid: str
    parceiros: List[str]


# ==============================================================================
# 2. FUNCAO DE BACKGROUND
# ==============================================================================
def enviar_sequencia_background(mensagens, sender_id):
    """Processa lista de mensagens com delay, sem travar a resposta HTTP."""
    if not client:
        print("ERRO Background: Cliente Infobip offline.")
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
    except Exception as e:
        print(f"Erro na tarefa de Background: {e}")


# ==============================================================================
# 3. ROTAS
# ==============================================================================
@app.get("/")
def health_check():
    """Rota simples para o Azure verificar se o app esta vivo."""
    return {"status": "online", "environment": "Azure Production"}


@app.post("/bot")
async def chat_webhook(payload: InfobipInboundPayload, background_tasks: BackgroundTasks):
    """Webhook principal que recebe mensagens do WhatsApp via Infobip.

    Diferente do Twilio (form-data + TwiML), o Infobip envia JSON estruturado
    e NAO aceita resposta via body - a resposta vai como chamada outbound
    separada via InfobipClient.

    REVISAR MANUALMENTE: este endpoint e publico. Considere configurar
    Basic Auth no portal Infobip e validar no FastAPI antes do deploy.
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

        print(f"Msg recebida de {sender_id}: {message_body}")

        try:
            resposta = bot.processar_mensagem(sender_id, message_body, media_url)
        except Exception as e:
            print(f"Erro no BotEngine: {e}")
            continue

        if not client:
            print("Cliente Infobip offline - nao foi possivel responder.")
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
        except Exception as e:
            # REVISAR MANUALMENTE: sem fallback TwiML, falhas aqui significam
            # que o usuario NAO recebe resposta. Considere retry com tenacity
            # ou enfileiramento para reprocessar.
            print(f"Falha no envio via Infobip: {e}")

    return {"status": "ok"}


@app.post("/api/dispatch")
async def dispatch_order(data: DispatchRequest):
    print(f"API Dispatch: Pedido {data.pedido_uuid} -> {len(data.parceiros)} parceiros.")
    try:
        result = dispatch_service.enviar_oferta_para_prestadores(data.parceiros, data.pedido_uuid)
        return result
    except Exception as e:
        print(f"Erro API Dispatch: {e}")
        return {"status": "error", "message": str(e)}
