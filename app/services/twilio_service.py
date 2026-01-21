import time
import json
import threading
from twilio.rest import Client
from app.core.config import Settings

class TwilioService:
    def __init__(self):
        settings = Settings()
        self.account_sid = settings.get_secret('TWILIO-ACCOUNT-SID')
        self.auth_token = settings.get_secret('TWILIO-AUTH-TOKEN')
        
        raw_number = settings.get_secret('TWILIO-PHONE-NUMBER') or ''
        if raw_number and "whatsapp:" not in raw_number:
            self.phone_number = f"whatsapp:{raw_number}"
        else:
            self.phone_number = raw_number
        
        if self.account_sid and self.auth_token:
            self.client = Client(self.account_sid, self.auth_token)
        else:
            self.client = None
            print("⚠️ TwilioService: Credenciais não encontradas.")

    def enviar_resposta(self, to_number, resposta_bot):
        if not self.client: return

        if "whatsapp:" not in to_number:
            to_number = f"whatsapp:{to_number}"
        
        tipo = resposta_bot.get('tipo')

        if tipo == 'sequencia':
            threading.Thread(
                target=self._processar_sequencia, 
                args=(to_number, resposta_bot.get('mensagens', []))
            ).start()
        else:
            threading.Thread(
                target=self._enviar_unico, 
                args=(to_number, resposta_bot)
            ).start()

    def _processar_sequencia(self, to_number, lista_mensagens):
        for msg in lista_mensagens:
            delay = msg.get('delay', 0)
            if delay > 0:
                time.sleep(delay)
            self._enviar_unico(to_number, msg)

    def _enviar_unico(self, to_number, msg):
        try:
            tipo = msg.get('tipo')
            
            if tipo == 'texto' or tipo == 'combo_inicial':
                conteudo = msg.get('conteudo') or msg.get('texto')
                if conteudo:
                    self.client.messages.create(
                        body=conteudo,
                        from_=self.phone_number,
                        to=to_number
                    )

            elif tipo == 'template':
                sid = msg.get('sid') or msg.get('template_sid')
                variaveis = msg.get('variaveis', {})
                
                self.client.messages.create(
                    content_sid=sid,
                    content_variables=json.dumps(variaveis),
                    from_=self.phone_number,
                    to=to_number
                )
            
            elif tipo == 'media':
                url = msg.get('url')
                legenda = msg.get('legenda', '')
                
                self.client.messages.create(
                    body=legenda,
                    media_url=[url],
                    from_=self.phone_number,
                    to=to_number
                )
                
            print(f"✅ Twilio: Mensagem enviada para {to_number}")

        except Exception as e:
            print(f"🔥 Erro TwilioService ao enviar para {to_number}: {e}")
