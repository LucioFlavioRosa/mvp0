"""
Cliente HTTP fino pra API WhatsApp do Infobip.

Mantém uma única responsabilidade: enviar requisições autenticadas.
Não faz parsing de webhook nem lógica de negócio.
"""

from typing import Any, Optional

import requests

from app.core.retry import transient_retry


class InfobipClient:
    def __init__(self, api_key: str, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"App {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def close(self) -> None:
        self._session.close()

    def send_text(self, sender: str, to: str, text: str) -> dict[str, Any]:
        payload = {"from": sender, "to": to, "content": {"text": text}}
        return self._post("/whatsapp/1/message/text", payload)

    def send_image(
        self,
        sender: str,
        to: str,
        media_url: str,
        caption: Optional[str] = None,
    ) -> dict[str, Any]:
        content: dict[str, Any] = {"mediaUrl": media_url}
        if caption:
            content["caption"] = caption
        payload = {"from": sender, "to": to, "content": content}
        return self._post("/whatsapp/1/message/image", payload)

    def send_template(
        self,
        sender: str,
        to: str,
        template_name: str,
        language: str,
        placeholders: list[str],
    ) -> dict[str, Any]:
        payload = {
            "messages": [
                {
                    "from": sender,
                    "to": to,
                    "content": {
                        "templateName": template_name,
                        "templateData": {"body": {"placeholders": placeholders}},
                        "language": language,
                    },
                }
            ]
        }
        return self._post("/whatsapp/1/message/template", payload)

    @transient_retry
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST autenticado pra API Infobip.

        Decorado com @transient_retry: 2 tentativas em caso de timeout,
        connection error ou HTTP 5xx. 4xx propaga direto (request invalida).
        """
        url = f"{self._base_url}{path}"
        response = self._session.post(url, json=payload, timeout=self._timeout)
        response.raise_for_status()
        return response.json()
