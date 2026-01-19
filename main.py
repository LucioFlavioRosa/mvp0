import uvicorn
import nest_asyncio
import json
import os
import time
import importlib
import sys
import threading
from google.colab import userdata

# ==============================================================================
# 0. VARIÁVEIS GLOBAIS
# ==============================================================================
BASE_URL = None

# ==============================================================================
# 1. CARREGAMENTO DE SEGREDOS
# ==============================================================================
print("🔑 Carregando segredos do sistema...")
try:
    os.environ["CONNECTION_STRING_AZURE_STORAGE"] = userdata.get('CONNECTION_STRING_AZURE_STORAGE') or ""
    os.environ["TWILIO_ACCOUNT_SID"] = userdata.get('TWILIO_ACCOUNT_SID') or ""
    os.environ["TWILIO_AUTH_TOKEN"] = userdata.get('TWILIO_AUTH_TOKEN') or ""
    os.environ["GOOGLE_MAPS_API_KEY"] = userdata.get('GOOGLE_MAPS_API_KEY') or ""
    NGROK_AUTH_TOKEN = userdata.get('NGROK_TOKEN')
    print("✅ Segredos carregados.")
except Exception as e:
    print(f"❌ Erro ao ler segredos: {e}")

# ==============================================================================
# 2. IMPORTS E RELOAD
# ==============================================================================
import app.bot_engine
import app.modules.onboarding
# ... (seus outros imports de módulos aqui, pode manter os que você já tem)
# Para economizar espaço, mantive os principais, mas certifique-se de que seus módulos estão aqui
importlib.reload(app.bot_engine)

from app.bot_engine import BotEngine
from fastapi import FastAPI, Form, Request, Response, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from pyngrok import ngrok

# ==============================================================================
# 3. INICIALIZAÇÃO DO APP
# ==============================================================================
app = FastAPI()

os.makedirs("arquivos_publicos", exist_ok=True)
app.mount("/publico", StaticFiles(directory="arquivos_publicos"), name="publico")

bot = BotEngine()

try:
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    if sid and token:
        client = Client(sid, token)
    else:
        client = None
except:
    client = None

# ==============================================================================
# 4. FUNÇÃO BACKGROUND (ATUALIZADA COM SUPORTE A TEMPLATES)
# ==============================================================================
def enviar_sequencia_background(mensagens, bot_number, sender_id):
    if not client: return
    global BASE_URL 
    try:
        for item in mensagens:
            # Respeita o delay configurado
            time.sleep(item.get('delay', 2.0)) 
            
            # --- TIPO 1: TEXTO SIMPLES ---
            if item['tipo'] == 'texto':
                client.messages.create(body=item['conteudo'], from_=bot_number, to=f'whatsapp:{sender_id}')
            
            # --- TIPO 2: MÍDIA (FOTO/VÍDEO) ---
            elif item['tipo'] == 'media':
                url_final = item['url']
                
                if not url_final.startswith('http'):
                    if BASE_URL:
                        # Limpeza para evitar links quebrados (publico/publico/...)
                        arquivo_limpo = url_final.replace("publico/", "").lstrip('/')
                        url_final = f"{BASE_URL}/publico/{arquivo_limpo}"
                
                print(f"🔗 Enviando Mídia: {url_final}") 
                
                client.messages.create(
                    body=item.get('legenda', ''), 
                    media_url=[url_final], 
                    from_=bot_number, 
                    to=f'whatsapp:{sender_id}'
                )

            # --- TIPO 3: TEMPLATE (BOTÕES) - NOVO! ---
            elif item['tipo'] == 'template':
                client.messages.create(
                    content_sid=item['sid'],
                    content_variables=json.dumps(item.get('variaveis', {})),
                    from_=bot_number,
                    to=f'whatsapp:{sender_id}'
                )

    except Exception as e:
        print(f"🔥 Erro Background: {e}")


# ==============================================================================
# 5. WEBHOOK
# ==============================================================================
@app.post("/bot")
async def chat_webhook(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    message_body = form_data.get('Body', '').strip()
    sender_id = form_data.get('From', '').replace('whatsapp:', '')
    bot_number = form_data.get('To', '')
    media_url = form_data.get('MediaUrl0')
    
    print(f"🤖 User: {message_body} | Mídia: {media_url}") # Log simplificado

    resposta = bot.processar_mensagem(sender_id, message_body, media_url)
    tipo = resposta.get('tipo')

    resp = MessagingResponse()

    if client and tipo == 'sequencia':
        background_tasks.add_task(enviar_sequencia_background, resposta.get('mensagens', []), bot_number, sender_id)
        return Response(content="", media_type="application/xml")
    
    if client and tipo in ['combo_inicial', 'template']:
        try:
            if tipo == 'combo_inicial':
                client.messages.create(body=resposta['texto'], from_=bot_number, to=f'whatsapp:{sender_id}')
                time.sleep(1)
            client.messages.create(
                content_sid=resposta.get('template_sid') or resposta.get('sid'),
                content_variables=json.dumps(resposta.get('variaveis', {})),
                from_=bot_number, to=f'whatsapp:{sender_id}'
            )
            return Response(content="", media_type="application/xml")
        except:
            pass # Falha silenciosa cai no fallback abaixo

    # Fallback
    if tipo == 'combo_inicial': resp.message(resposta['texto'])
    elif tipo == 'texto': resp.message(resposta['conteudo'])
    elif tipo == 'media':
        msg = resp.message(resposta.get('legenda', ''))
        url_media = resposta['url']
        if not url_media.startswith('http') and BASE_URL:
             url_media = f"{BASE_URL}/publico/{url_media.lstrip('/')}"
        msg.media(url_media)

    return Response(content=str(resp), media_type="application/xml")

# ==============================================================================
# 6. EXECUÇÃO DO SERVIDOR (COM LOOP INFINITO)
# ==============================================================================
def run_server():
    # Roda o servidor Uvicorn
    # log_level="info" ajuda a ver os erros se houver
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    if NGROK_AUTH_TOKEN:
        ngrok.set_auth_token(NGROK_AUTH_TOKEN)
    
    # Limpa processos antigos
    os.system("killall ngrok")
    
    try:
        # 1. Abre o túnel
        tunnel = ngrok.connect(8000)
        public_url = tunnel.public_url
        
        # Atualiza URL Global
        BASE_URL = public_url
        
        print("="*60)
        print(f"🚀 BOT ONLINE: {public_url}/bot")
        print(f"🎥 Teste vídeo: {public_url}/publico/apresentacao.mp4")
        print("👉 Cole a URL no Twilio e mande 'oi' no WhatsApp.")
        print("="*60)
        print("⏳ O servidor está rodando. NÃO PARE ESTA CÉLULA.")
        
        # 2. Inicia o servidor em uma Thread separada
        thread = threading.Thread(target=run_server)
        thread.start()
        
        # 3. MANTÉM A CÉLULA VIVA (O Segredo está aqui 👇)
        while True:
            time.sleep(5) # Espera 5 segundos e repete para sempre
            
    except KeyboardInterrupt:
        print("\n🛑 Servidor parado pelo usuário.")
    except Exception as e:
        print(f"❌ Erro fatal: {e}")
