"""
Serviço de envio de mensagens WhatsApp via Infobip.

Interface pública (`enviar_resposta`) preservada da implementação antiga
com Twilio, pra que `DispatchService` e outros chamadores não precisem
mudar lógica de negócio. Internamente usa o `InfobipClient`.
"""

import threading
import time

from app.core.config import Settings
from app.integrations.infobip import InfobipClient

# Idioma padrão dos templates cadastrados no portal Infobip.
# Ajustar se os templates forem em outro idioma.
DEFAULT_TEMPLATE_LANGUAGE = "pt_BR"


class WhatsAppService:
    def __init__(self):
        settings = Settings()
        api_key = settings.get_secret("INFOBIP-API-KEY")
        base_url = settings.get_secret("INFOBIP-BASE-URL")
        self.sender = settings.get_secret("INFOBIP-SENDER") or ""

        if api_key and base_url and self.sender:
            self.client = InfobipClient(api_key=api_key, base_url=base_url)
        else:
            self.client = None
            print("⚠️ WhatsAppService: Credenciais Infobip não encontradas.")

    def enviar_resposta(self, to_number, resposta_bot):
        if not self.client:
            return

        # Infobip usa E164 sem prefixo — strip "whatsapp:" caso o caller passe.
        to_number = _strip_whatsapp_prefix(to_number)

        tipo = resposta_bot.get("tipo")

        if tipo == "sequencia":
            threading.Thread(
                target=self._processar_sequencia,
                args=(to_number, resposta_bot.get("mensagens", [])),
            ).start()
        else:
            threading.Thread(
                target=self._enviar_unico,
                args=(to_number, resposta_bot),
            ).start()

    def _processar_sequencia(self, to_number, lista_mensagens):
        for msg in lista_mensagens:
            delay = msg.get("delay", 0)
            if delay > 0:
                time.sleep(delay)
            self._enviar_unico(to_number, msg)

    def _enviar_unico(self, to_number, msg):
        try:
            tipo = msg.get("tipo")

            if tipo == "texto" or tipo == "combo_inicial":
                conteudo = msg.get("conteudo") or msg.get("texto")
                if conteudo:
                    self.client.send_text(
                        sender=self.sender,
                        to=to_number,
                        text=conteudo,
                    )

            elif tipo == "template":
                # Infobip usa templateName (string) + placeholders (lista posicional),
                # em vez do content_sid + content_variables (dict) do Twilio.
                template_name = msg.get("template_name") or msg.get("sid")
                placeholders = msg.get("placeholders") or _dict_to_positional_list(
                    msg.get("variaveis", {})
                )
                language = msg.get("language", DEFAULT_TEMPLATE_LANGUAGE)

                self.client.send_template(
                    sender=self.sender,
                    to=to_number,
                    template_name=template_name,
                    language=language,
                    placeholders=placeholders,
                )

            elif tipo == "media":
                url = msg.get("url")
                legenda = msg.get("legenda", "")
                self.client.send_image(
                    sender=self.sender,
                    to=to_number,
                    media_url=url,
                    caption=legenda or None,
                )

            print(f"✅ Infobip: Mensagem enviada para {to_number}")

        except Exception as e:
            # Infobip retorna 200 com erro no body em alguns casos, mas erros HTTP
            # 4xx/5xx chegam aqui via requests.raise_for_status no InfobipClient.
            print(f"🔥 Erro WhatsAppService ao enviar para {to_number}: {e}")


def _strip_whatsapp_prefix(number: str) -> str:
    if number and number.startswith("whatsapp:"):
        return number[len("whatsapp:"):].lstrip("+")
    return number.lstrip("+") if number else number


def _dict_to_positional_list(variaveis: dict) -> list[str]:
    """Converte {'1': 'a', '2': 'b'} em ['a', 'b'] ordenado por chave numérica.

    Fallback pra retrocompatibilidade com chamadores que ainda passam dict
    no estilo Twilio. Idealmente, callers já enviam `placeholders` direto.
    """
    if not variaveis:
        return []
    try:
        return [str(variaveis[str(i)]) for i in sorted(int(k) for k in variaveis.keys())]
    except (ValueError, KeyError):
        # Chaves não-numéricas: cai pra ordem de inserção
        return [str(v) for v in variaveis.values()]
