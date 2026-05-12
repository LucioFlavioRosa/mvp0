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

# Cliente Infobip
try:
    api_key = settings.get_secret("INFOBIP-API-KEY")
    base_url = settings.get_secret("INFOBIP-BASE-URL")
    sender_number = settings.get_secret("INFOBIP-SENDER") or ""

    if api_key and base_url and sender_number:
        client = InfobipClient(api_key=api_key, base_url=base_url)
        print("✅ Cliente Infobip autenticado.")
    else:
        client = None
        print("⚠️ AVISO: Credenciais Infobip não encontradas no Key Vault.")
except Exception as e:
    client = None
    print(f"❌ Erro ao iniciar Infobip: {e}")

# Modelo de Dados para a API de Disparo
class DispatchRequest(BaseModel):
    pedido_uuid: str
    parceiros: List[str]

# ==============================================================================
# 2. FUNÇÃO DE BACKGROUND (GERENCIA FILA DE MENSAGENS)
# ==============================================================================
def enviar_sequencia_background(mensagens, sender_id):
    """
    Processa lista de mensagens com delay, sem travar a resposta HTTP.
    Ideal para sequências longas ou envio de mídia pesada.
    """
    if not client:
        print("❌ Erro Background: Cliente Infobip offline.")
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
        print(f"🔥 Erro na tarefa de Background: {e}")

# ==============================================================================
# 3. ROTAS DA APLICAÇÃO
# ==============================================================================
@app.get("/")
def health_check():
    """Rota simples para o Azure verificar se o app está vivo (Ping)."""
    return {"status": "online", "environment": "Azure Production"}

@app.post("/bot")
async def chat_webhook(payload: InfobipInboundPayload, background_tasks: BackgroundTasks):
    """Webhook principal que recebe todas as mensagens do WhatsApp via Infobip.

    Diferente do Twilio (form-data + TwiML), o Infobip envia JSON estruturado
    e NÃO aceita resposta via body — a resposta vai como chamada outbound
    separada via InfobipClient.

    ⚠ REVISAR MANUALMENTE: este endpoint é público. Considere configurar
    Basic Auth no portal Infobip e validar no FastAPI antes do deploy.
    """
    # Infobip sempre manda em batch (results[]), mesmo com 1 mensagem.
    for result in payload.results:
        sender_id = result.sender  # E164 sem prefixo whatsapp:
        message_body = ""
        media_url = None

        if result.message.type == "TEXT":
            message_body = result.message.text.strip()
        elif result.message.type == "IMAGE":
            media_url = result.message.url
            message_body = (result.message.caption or "").strip()

        print(f"📩 Msg recebida de {sender_id}: {message_body}")

        try:
            resposta = bot.processar_mensagem(sender_id, message_body, media_url)
        except Exception as e:
            print(f"🔥 Erro no BotEngine: {e}")
            continue  # No Infobip não há fallback TwiML — só loga e segue

        if not client:
            print("⚠️ Cliente Infobip offline — não foi possível responder.")
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
      