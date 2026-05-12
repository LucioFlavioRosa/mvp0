"""Servico de envio de mensagens WhatsApp via Infobip."""

import threading
import time

from app.core.config import Settings
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
from app.integrations.infobip import InfobipClient

logger = get_logger(__name__)

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
            missing = [k for k, v in {
                "INFOBIP-API-KEY": api_key,
                "INFOBIP-BASE-URL": base_url,
                "INFOBIP-SENDER": self.sender,
            }.items() if not v]
            logger.warning("WhatsAppService: credenciais ausentes",
                           extra={"custom_dimensions": {
                               ld.OPERATION: "startup",
                               ld.MISSING_SECRETS: missing,
                           }})

    def enviar_resposta(self, to_number, resposta_bot):
        if not self.client:
            return

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
        tipo = msg.get("tipo")
        try:
            if tipo == "texto" or tipo == "combo_inicial":
                conteudo = msg.get("conteudo") or msg.get("texto")
                if conteudo:
                    self.client.send_text(
                        sender=self.sender,
                        to=to_number,
                        text=conteudo,
                    )

            elif tipo == "template":
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

            logger.info("mensagem enviada via Infobip", extra={"custom_dimensions": {
                ld.OPERATION: "send_message",
                "to_hash": mask_pii(to_number),
                ld.TIPO: tipo,
                ld.EXTERNAL_SERVICE: "infobip",
            }})

        except Exception:
            logger.error("erro ao enviar via Infobip", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "send_message",
                             "to_hash": mask_pii(to_number),
                             ld.TIPO: tipo,
                             ld.EXTERNAL_SERVICE: "infobip",
                         }})


def _strip_whatsapp_prefix(number: str) -> str:
    if number and number.startswith("whatsapp:"):
        return number[len("whatsapp:"):].lstrip("+")
    return number.lstrip("+") if number else number


def _dict_to_positional_list(variaveis: dict) -> list:
    if not variaveis:
        return []
    try:
        return [str(variaveis[str(i)]) for i in sorted(int(k) for k in variaveis.keys())]
    except (ValueError, KeyError):
        return [str(v) for v in variaveis.values()]
