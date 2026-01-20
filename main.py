import os
import json
import time
from fastapi import FastAPI, Request, Response, BackgroundTasks
from pydantic import BaseModel
from typing import List
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

# Imports da sua aplicação (Certifique-se que as pastas app/ existem)
from app.bot_engine import BotEngine
from app.services.dispatch_service import DispatchService 

# ==============================================================================
# 1. INICIALIZAÇÃO E VARIÁVEIS DE AMBIENTE
# ==============================================================================
print("🚀 Inicializando aplicação no Azure App Service...")

app = FastAPI(title="Bot Águas do Pará", version="1.0.0")

# Instâncias dos Motores
try:
    bot = BotEngine()
    dispatch_service = DispatchService()
    print("✅ Motores inicializados (BotEngine e DispatchService).")
except Exception as e:
    print(f"❌ Erro crítico ao iniciar motores: {e}")

# Cliente Twilio
try:
    # No Azure, estas variáveis devem estar em "Environment Variables"
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    
    if sid and token:
        client = Client(sid, token)
        print("✅ Cliente Twilio autenticado.")
    else:
        client = None
        print("⚠️ AVISO: Credenciais Twilio não encontradas no ambiente.")
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
    
    # Se o número do bot não vier no request, tenta pegar do ambiente
    numero_envio = bot_number if bot_number else os.environ.get("TWILIO_PHONE_NUMBER")
    
    try:
        for item in mensagens:
            # 1. Respeita o Delay configurado
            time.sleep(item.get('delay', 1.0)) 
            
            # Argumentos padrão
            msg_args = {
                'to': f'whatsapp:{sender_id}', 
                'from_': numero_envio
            }
            
            tipo = item.get('tipo')

            # --- CASO A: TEXTO SIMPLES ---
            if tipo == 'texto':
                client.messages.create(body=item['conteudo'], **msg_args)
            
            # --- CASO B: MÍDIA (VÍDEO/FOTO) ---
            # O Segredo: Passamos a URL pública do Blob direto para o Twilio.
            elif tipo == 'media':
                url_blob = item['url'] 
                legenda = item.get('legenda', '')
                
                # O Twilio vai baixar o vídeo dessa URL e entregar como arquivo
                client.messages.create(
                    body=legenda, 
                    media_url=[url_blob], 
                    **msg_args
                )

            # --- CASO C: TEMPLATE (BOTÕES) ---
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
    
    # 1. Parse do Formulário Twilio
    form_data = await request.form()
    message_body = form_data.get('Body', '').strip()
    sender_id = form_data.get('From', '').replace('whatsapp:', '')
    bot_number = form_data.get('To', '') 
    media_url = form_data.get('MediaUrl0') # Se o usuário mandou foto
    
    print(f"📩 Msg recebida de {sender_id}: {message_body}")

    # 2. Processamento Lógico (BotEngine)
    try:
        resposta = bot.processar_mensagem(sender_id, message_body, media_url)
    except Exception as e:
        print(f"🔥 Erro no BotEngine: {e}")
        return Response(content=str(MessagingResponse()), media_type="application/xml")

    tipo = resposta.get('tipo')
    resp = MessagingResponse() # Fallback TwiML

    # 3. Estratégias de Resposta

    # ESTRATÉGIA 1: Sequência (Manda para Background para não dar timeout)
    if client and tipo == 'sequencia':
        background_tasks.add_task(
            enviar_sequencia_background, 
            resposta.get('mensagens', []), 
            bot_number, 
            sender_id
        )
        # Retorna 200 OK vazio para o Twilio não reclamar
        return Response(content="", media_type="application/xml")
    
    # ESTRATÉGIA 2: Envio Imediato via API (Templates ou Combos Rápidos)
    if client and tipo in ['combo_inicial', 'template']:
        try:
            num_envio = bot_number if bot_number else os.environ.get("TWILIO_PHONE_NUMBER")
            
            if tipo == 'combo_inicial':
                client.messages.create(body=resposta['texto'], from_=num_envio, to=f'whatsapp:{sender_id}')
                time.sleep(0.5)
            
            # Envia o Template
            client.messages.create(
                content_sid=resposta.get('template_sid') or resposta.get('sid'),
                content_variables=json.dumps(resposta.get('variaveis', {})),
                from_=num_envio, to=f'whatsapp:{sender_id}'
            )
            return Response(content="", media_type="application/xml")
        except Exception as e:
            print(f"⚠️ Falha no envio imediato API: {e}. Tentando fallback...")
            # Se falhar a API, deixa cair no XML abaixo

    # ESTRATÉGIA 3: Resposta Síncrona TwiML (XML Clássico)
    # Útil para respostas de texto simples muito rápidas
    if tipo == 'combo_inicial': resp.message(resposta['texto'])
    elif tipo == 'texto': resp.message(resposta['conteudo'])
    elif tipo == 'media':
        msg = resp.message(resposta.get('legenda', ''))
        msg.media(resposta['url']) # URL Pública do Blob

    return Response(content=str(resp), media_type="application/xml")

@app.post("/api/dispatch")
async def dispatch_order(data: DispatchRequest):
    """API Interna/Front-end para disparar ofertas para parceiros."""
    print(f"🚀 API Dispatch: Pedido {data.pedido_uuid} -> {len(data.parceiros)} parceiros.")
    
    try:
        # Chama o serviço de disparo
        result = dispatch_service.enviar_oferta_para_prestadores(data.parceiros, data.pedido_uuid)
        return result
    except Exception as e:
        print(f"🔥 Erro API Dispatch: {e}")
        return {"status": "error", "message": str(e)}
