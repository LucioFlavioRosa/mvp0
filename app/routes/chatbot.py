from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import json
import time

from app.core.config import Settings
from app.core.auth import get_bff_token
from app.bot_engine import BotEngine
from app.services.pedidos.dispatch_service import DispatchService 
from app.services.parceiros.parceiro_service import ParceiroService
from app.services.infra.twilio_service import TwilioService 
from app.schemas.chatbot import DispatchRequest, SendMessageRequest

router = APIRouter()
settings = Settings()

# ==============================================================================
# INSTÂNCIAS (SINGLETONS DA ROTA DO CHATBOT)
# ==============================================================================
try:
    bot = BotEngine()
    dispatch_service = DispatchService()
    parceiro_service = ParceiroService()
    twilio_service = TwilioService()
except Exception as e:
    print(f"❌ Erro ao instanciar motores no chatbot router: {e}")

# Cliente nativo do Twilio (Para background tasks manuais)
try:
    sid = settings.get_secret("TWILIO-ACCOUNT-SID")
    token = settings.get_secret("TWILIO-AUTH-TOKEN")
    raw_number = settings.get_secret("TWILIO-PHONE-NUMBER") or ''
    bot_phone_number = f"whatsapp:{raw_number}" if raw_number and "whatsapp:" not in raw_number else raw_number
    client = Client(sid, token) if sid and token else None
except Exception as e:
    client = None

# ==============================================================================
# FUNÇÃO DE SUPORTE (Fila Background)
# ==============================================================================
def enviar_sequencia_background(mensagens, bot_number, sender_id):
    """Envia uma sequência de mensagens simulando tempo de digitação (delay)."""
    if not client: return
    numero_envio = bot_number if bot_number else bot_phone_number
    try:
        for item in mensagens:
            time.sleep(item.get('delay', 1.0)) 
            msg_args = {'to': f'whatsapp:{sender_id}', 'from_': numero_envio}
            tipo = item.get('tipo')
            if tipo == 'texto':
                client.messages.create(body=item['conteudo'], **msg_args)
            elif tipo == 'media':
                client.messages.create(body=item.get('legenda', ''), media_url=[item['url']], **msg_args)
            elif tipo == 'template':
                client.messages.create(content_sid=item['sid'], content_variables=json.dumps(item.get('variaveis', {})), **msg_args)
    except Exception as e:
        print(f"🔥 Erro na tarefa de Background: {e}")

# ==============================================================================
# ROTAS INTERNAS DA API (USADAS PELO PORTAL)
# ==============================================================================
@router.post("/api/dispatch", dependencies=[Depends(get_bff_token)], tags=["Integração"])
async def dispatch_order(data: DispatchRequest):
    print(f"🚀 API Dispatch: Pedido {data.pedido_uuid} -> {len(data.parceiros)} parceiros.")
    return dispatch_service.enviar_oferta_para_prestadores(data.parceiros, data.pedido_uuid)

@router.post("/api/send-message", dependencies=[Depends(get_bff_token)], tags=["Integração"])
async def sendMessage(data: SendMessageRequest):
    try:
        whatsapp_id = parceiro_service.getWhatsappID(data.parceiro_uuid)
        if not whatsapp_id: return {"status": "error", "message": "Parceiro não encontrado."}
        msg_obj = {"tipo": "texto", "conteudo": data.mensagem}
        twilio_service.enviar_resposta(whatsapp_id, msg_obj)
        return {"status": "success", "message": "Mensagem enviada."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==============================================================================
# ROTAS PÚBLICAS (WEBHOOK DO TWILIO)
# ==============================================================================
@router.post("/bot", tags=["Webhook"])
async def chat_webhook(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    message_body = form_data.get('Body', '').strip()
    sender_id = form_data.get('From', '').replace('whatsapp:', '')
    bot_number = form_data.get('To', '') 
    media_url = form_data.get('MediaUrl0')
    
    try:
        resposta = bot.processar_mensagem(sender_id, message_body, media_url)
        tipo = resposta.get('tipo')
        resp = MessagingResponse()

        if client and tipo == 'sequencia':
            background_tasks.add_task(enviar_sequencia_background, resposta.get('mensagens', []), bot_number, sender_id)
            return Response(content="", media_type="application/xml")

        if client and tipo in ['combo_inicial', 'template']:
            num_envio = bot_number if bot_number else bot_phone_number
            if tipo == 'combo_inicial':
                client.messages.create(body=resposta['texto'], from_=num_envio, to=f'whatsapp:{sender_id}')
                time.sleep(0.5)
            client.messages.create(
                content_sid=resposta.get('template_sid') or resposta.get('sid'),
                content_variables=json.dumps(resposta.get('variaveis', {})),
                from_=num_envio, to=f'whatsapp:{sender_id}'
            )
            return Response(content="", media_type="application/xml")

        if tipo == 'combo_inicial': resp.message(resposta['texto'])
        elif tipo == 'texto': resp.message(resposta['conteudo'])
        elif tipo == 'media':
            msg = resp.message(resposta.get('legenda', ''))
            msg.media(resposta['url'])
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print(f"🔥 Erro no BotEngine: {e}")
        return Response(content=str(MessagingResponse()), media_type="application/xml")
