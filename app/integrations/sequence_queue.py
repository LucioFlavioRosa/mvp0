"""
Cliente fino sobre Azure Storage Queue para entrega assincrona de sequencias
de mensagens WhatsApp (texto+midia+template com delays entre cada item).

Por que existe (vs BackgroundTasks do FastAPI):
- BackgroundTasks roda funcoes sync no thread pool do anyio (~36 threads).
  Cada time.sleep(N) segura uma thread, podendo exaurir o pool com volume
  alto e travar o processamento de novos webhooks.
- Queue persistente desacopla totalmente: webhook so enqueue (microsegundos)
  e libera o worker FastAPI. Um sequence_worker dedicado consome a fila
  com seu proprio pool de threads, isolado do request path.
- Bonus: durabilidade. Se o worker morre durante uma sequencia, a mensagem
  reaparece apos visibility timeout e outro worker pega - sem perda silenciosa.

Politica:
- Enqueue eh fire-and-forget. Falha eh logada como CRITICAL, nao propaga
  pro caller (webhook nao deve quebrar por queue indisponivel).
- Visibility timeout = 5 min, suficiente para a maior sequencia atual
  (~32s de delays acumulados) com folga grande.
- Sequencias com dequeue_count > 5 sao consideradas poison e logadas
  CRITICAL pelo worker (caller decide se deleta ou move pra DLQ).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from azure.storage.queue import QueueClient

from app.core.config import Settings
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)

QUEUE_NAME = "outbound-sequences"
RECEIVE_VISIBILITY_SECONDS = 300  # 5 min, > maior sequencia esperada
POISON_THRESHOLD = 5  # dequeue_count acima disso = considera-se mensagem poison


class SequenceQueueClient:
    """Wrapper sobre Azure Storage Queue para sequencias outbound."""

    def __init__(self) -> None:
        settings = Settings()
        conn_str = settings.get_secret("CONNECTION-STRING-AZURE-STORAGE")
        if not conn_str:
            logger.warning(
                "SequenceQueueClient: CONNECTION-STRING-AZURE-STORAGE ausente; queue desabilitada",
                extra={"custom_dimensions": {
                    ld.OPERATION: "startup",
                    ld.COMPONENT: "sequence_queue",
                    ld.MISSING_SECRETS: ["CONNECTION-STRING-AZURE-STORAGE"],
                }},
            )
            self.queue = None
            return

        try:
            self.queue = QueueClient.from_connection_string(conn_str, QUEUE_NAME)
            self.queue.create_queue()  # idempotente
        except Exception:
            logger.error(
                "SequenceQueueClient: falha ao inicializar Azure Storage Queue",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "startup",
                    ld.COMPONENT: "sequence_queue",
                }},
            )
            self.queue = None

    def enqueue(self, sender_id: str, sequence: list[dict[str, Any]]) -> bool:
        """Enfileira uma sequencia de mensagens para envio assincrono.

        sender_id: numero E.164 sem prefixo whatsapp:
        sequence: lista de dicts no mesmo formato que enviar_sequencia_background
                  consumia (campos: tipo, conteudo|url|template_name, delay, ...)

        Returns:
            True se enfileirou, False se queue indisponivel ou falha.
            Nunca levanta.
        """
        if self.queue is None:
            logger.critical(
                "SequenceQueue indisponivel: sequencia perdida sem persistencia",
                extra={"custom_dimensions": {
                    ld.OPERATION: "sequence_enqueue",
                    "items_count": len(sequence),
                }},
            )
            return False

        try:
            payload = {"sender_id": sender_id, "sequence": sequence}
            self.queue.send_message(json.dumps(payload))
            logger.info(
                "sequencia enfileirada",
                extra={"custom_dimensions": {
                    ld.OPERATION: "sequence_enqueue",
                    "items_count": len(sequence),
                }},
            )
            return True
        except Exception:
            logger.critical(
                "falha ao enfileirar sequencia - mensagem perdida",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "sequence_enqueue",
                    "items_count": len(sequence),
                }},
            )
            return False

    def receive_one(self) -> Optional[dict[str, Any]]:
        """Pega 1 mensagem da fila com visibility timeout (escondida por 5 min).

        Retorna dict com {id, pop_receipt, content, dequeue_count} ou None
        se queue vazia. Caller obrigatorio chamar delete() depois de processar.
        """
        if self.queue is None:
            return None
        try:
            pages = self.queue.receive_messages(
                messages_per_page=1,
                visibility_timeout=RECEIVE_VISIBILITY_SECONDS,
            ).by_page()
            received = list(next(pages, []))
        except Exception:
            logger.error(
                "falha ao receber da SequenceQueue",
                exc_info=True,
                extra={"custom_dimensions": {ld.OPERATION: "sequence_receive"}},
            )
            return None
        if not received:
            return None
        m = received[0]
        return {
            "id": m.id,
            "pop_receipt": m.pop_receipt,
            "content": _safe_parse(m.content),
            "dequeue_count": m.dequeue_count,
        }

    def delete(self, message_id: str, pop_receipt: str) -> bool:
        """Remove a mensagem da fila. Chamado pelo worker apos processar
        a sequencia com sucesso."""
        if self.queue is None:
            return False
        try:
            self.queue.delete_message(message_id, pop_receipt)
            return True
        except Exception:
            logger.error(
                "falha ao deletar mensagem da SequenceQueue",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "sequence_delete",
                    "message_id": message_id,
                }},
            )
            return False


def _safe_parse(content: str) -> dict[str, Any]:
    """Tenta parsear o JSON; em erro, retorna dict com raw."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": content}
