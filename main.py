import os
import json
import time
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

# Imports da sua aplicação (Certifique-se que as pastas app/ existem)
from app.bot_engine import BotEngine
from app.services.dispatch_service import DispatchService 
from app.core.config import Settings

# ==============================================================================
# 1. INICIALIZAÇÃO E VARIÁVEIS DE AMBIENTE
# ==============================================================================

app = FastAPI(title="Bot Águas do Pará", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, colocar a URL específica do front
    allow_credentials=True,
    allow_methods=["*"],  # Permite GET, POST, OPTIONS, etc.
    allow_headers=["*"],  # Permite todos os headers
)

# Instância global de Settings (Key Vault)
settings = Settings()

# Instâncias dos Motores
try:
    bot = BotEngine()
    dispatch_service = DispatchService()
    print("✅ Motores inicializados (BotEngine e DispatchService).")
except Exception as e:
    print(f"❌ Erro crítico ao iniciar motores: {e}")

# Cliente Twilio
try:
    sid = settings.get_secret("TWILIO-ACCOUNT-SID")
    token = settings.get_secret("TWILIO-AUTH-TOKEN")
    raw_number = settings.get_secret("TWILIO-PHONE-NUMBER") or ''
    if raw_number and "whatsapp:" not in raw_number:
        phone_number = f"whatsapp:{raw_number}"
    else:
        phone_number = raw_number
    if sid and token:
        client = Client(sid, token)
        print("✅ Cliente Twilio autenticado.")
    else:
        client = None
        print("⚠️ AVISO: Credenciais Twilio não encontradas no Key Vault.")
except Exception as e:
    client = None
    print(f"❌ Erro ao iniciar Twilio: {e}")

# Modelo de Dados para a API de Disparo
class DispatchRequest(BaseModel):
    pedido_uuid: str
    parceiros: List[str]

# ==============================================================================
# 2. FUNÇÃO DE BACKGROUND (GERENCIA FILA DE MENSAGENS)
# ==============================================================================
def enviar_sequencia_background(mensagens, bot_number, sender_id):
    """
    Processa lista de mensagens com delay, sem travar a resposta HTTP.
    Ideal para sequências longas ou envio de mídia pesada.
    """
    if not client: 
        print("❌ Erro Background: Cliente Twilio offline.")
        return
    
    # Se o número do bot não vier no request, tenta pegar do Key Vault
    numero_envio = bot_number if bot_number else settings.get_secret("TWILIO_PHONE_NUMBER")
    
    try:
        for item in mensagens:
            time.sleep(item.get('delay', 1.0)) 
            msg_args = {
                'to': f'whatsapp:{sender_id}', 
                'from_': numero_envio
            }
            tipo = item.get('tipo')
            if tipo == 'texto':
                client.messages.create(body=item['conteudo'], **msg_args)
            elif tipo == 'media':
                url_blob = item['url'] 
                legenda = item.get('legenda', '')
                client.messages.create(
                    body=legenda, 
                    media_url=[url_blob], 
                    **msg_args
                )
            elif tipo == 'template':
                client.messages.create(
                    content_sid=item['sid'],
                    content_variables=json.dumps(item.get('variaveis', {})),
                    **msg_args
                )
    except Exception as e:
        print(f"🔥 Erro na tarefa de Background: {e}")

# ==============================================================================
# 3. ROTAS DA APLICAÇÃO
# ==============================================================================
@app.get("/")
def health_check():
    """Rota simples para o Azure verificar se o app está vivo (Ping)."""
    return {"status": "online", "environment": "Azure Production"}

@app.post("/bot")
async def chat_webhook(request: Request, background_tasks: BackgroundTasks):
    """Webhook principal que recebe todas as mensagens do WhatsApp."""
    form_data = await request.form()
    message_body = form_data.get('Body', '').strip()
    sender_id = form_data.get('From', '').replace('whatsapp:', '')
    bot_number = form_data.get('To', '') 
    media_url = form_data.get('MediaUrl0') # Se o usuário mandou foto
    print(f"📩 Msg recebida de {sender_id}: {message_body}")
    try:
        resposta = bot.processar_mensagem(sender_id, message_body, media_url)
    except Exception as e:
        print(f"🔥 Erro no BotEngine: {e}")
        return Response(content=str(MessagingResponse()), media_type="application/xml")
    tipo = resposta.get('tipo')
    resp = MessagingResponse() # Fallback TwiML

    if client and tipo == 'sequencia':
        background_tasks.add_task(
            enviar_sequencia_background, 
            resposta.get('mensagens', []), 
            bot_number, 
            sender_id
        )
        return Response(content="", media_type="application/xml")

    if client and tipo in ['combo_inicial', 'template']:
        try:
            num_envio = bot_number if bot_number else settings.get_secret("TWILIO_PHONE_NUMBER")
            if tipo == 'combo_inicial':
                client.messages.create(body=resposta['texto'], from_=num_envio, to=f'whatsapp:{sender_id}')
                time.sleep(0.5)
            client.messages.create(
                content_sid=resposta.get('template_sid') or resposta.get('sid'),
                content_variables=json.dumps(resposta.get('variaveis', {})),
                from_=num_envio, to=f'whatsapp:{sender_id}'
            )
            return Response(content="", media_type="application/xml")
        except Exception as e:
            print(f"⚠️ Falha no envio imediato API: {e}. Tentando fallback...")

    if tipo == 'combo_inicial': resp.message(resposta['texto'])
    elif tipo == 'texto': resp.message(resposta['conteudo'])
    elif tipo == 'media':
        msg = resp.message(resposta.get('legenda', ''))
        msg.media(resposta['url'])
    return Response(content=str(resp), media_type="application/xml")

@app.post("/api/dispatch")
async def dispatch_order(data: DispatchRequest):
    print(f"🚀 API Dispatch: Pedido {data.pedido_uuid} -> {len(data.parceiros)} parceiros.")
    try:
        result = dispatch_service.enviar_oferta_para_prestadores(data.parceiros, data.pedido_uuid)
        return result
    except Exception as e:
        print(f"🔥 Erro API Dispatch: {e}")
        return {"status": "error", "message": str(e)}
