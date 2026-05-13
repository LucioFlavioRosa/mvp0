"""
Cliente HTTP fino pra API WhatsApp do Infobip.

Mantém uma única responsabilidade: enviar requisições autenticadas.
Não faz parsing de webhook nem lógica de negócio.

Falhas pós retry transient sao enfileiradas na DLQ (Azure Storage Queue)
antes de propagar pro caller - garante visibilidade de mensagens perdidas
sem retry automatico (politica: 2 tentativas total).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import requests

from app.core.retry import transient_retry
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
from app.integrations.dlq import DLQClient
from app.schemas.dlq import DLQMessage

logger = get_logger(__name__)


class InfobipClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 10.0,
        dlq: Optional[DLQClient] = None,
    ) -> None:
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
        # DLQ e instanciada por default; passar dlq=None desabilita (uso em testes).
        # DLQClient e fail-safe internamente - se Storage Queue indisponivel, vira no-op.
        self._dlq = dlq if dlq is not None else DLQClient()

    def close(self) -> None:
        self._session.close()

    def send_text(self, sender: str, to: str, text: str) -> dict[str, Any]:
        payload = {"from": sender, "to": to, "content": {"text": text}}
        return self._dispatch("send_text", "/whatsapp/1/message/text", payload, sender=sender, to=to)

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
        return self._dispatch("send_image", "/whatsapp/1/message/image", payload, sender=sender, to=to)

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
        return self._dispatch("send_template", "/whatsapp/1/message/template", payload, sender=sender, to=to)

    def _dispatch(
        self,
        operation: str,
        path: str,
        payload: dict[str, Any],
        sender: str,
        to: str,
    ) -> dict[str, Any]:
        """Envia pro Infobip via _post (com retry transient).

        Se pos-retry ainda falhar, enfileira na DLQ antes de re-levantar -
        garante que a mensagem nao se perde silenciosamente.
        """
        try:
            return self._post(path, payload)
        except Exception as exc:
            # Falha apos esgotar retry transient (2 tentativas).
            # Persiste na DLQ antes de propagar - politica de 2 tentativas total
            # com cleanup obrigatorio (sem retry automatico do worker).
            dlq_msg = DLQMessage(
                operation=operation,
                external_service="infobip",
                payload={"path": path, "body": payload, "sender": sender, "to": to},
                sender_hash=mask_pii(to),
                attempts=2,  # retry transient ja consumiu as 2 tentativas
                last_error=f"{type(exc).__name__}: {str(exc)[:200]}",
                errored_at=datetime.now(timezone.utc),
            )
            self._dlq.enqueue(dlq_msg)
            raise

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
