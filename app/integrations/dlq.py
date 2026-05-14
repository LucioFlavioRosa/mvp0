"""
Cliente fino sobre Azure Storage Queue para a Dead-Letter Queue de envios outbound.

Politica (importante):
- Apenas persiste falhas. Sem retry automatico.
- Cada mensagem tem 1 ciclo de vida: enqueue -> admin retry manual -> delete.
- Visibility timeout maior que default (5 min) para o admin processar
  sem a mensagem "reaparecer" pra outro processamento simultaneo.
- TTL fixo em 7 dias (default e max do Storage Queue) - mensagens
  expiram naturalmente se ninguem agir.

Falhas ao enfileirar (Storage Queue indisponivel) sao logadas como CRITICAL
e NAO propagam pro caller - melhor perder a mensagem que travar o caminho
normal.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from azure.storage.queue import QueueClient

from app.core.config import Settings
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld
from app.schemas.dlq import DLQMessage

logger = get_logger(__name__)

QUEUE_NAME = "outbound-dlq"
RECEIVE_VISIBILITY_SECONDS = 300  # 5 min - tempo que admin tem pra processar antes da mensagem reaparecer


class DLQClient:
    """Wrapper sobre Azure Storage Queue. Singleton no startup."""

    def __init__(self) -> None:
        settings = Settings()
        conn_str = settings.get_secret("CONNECTION-STRING-AZURE-STORAGE")
        if not conn_str:
            logger.warning(
                "DLQClient: CONNECTION-STRING-AZURE-STORAGE ausente; DLQ desabilitada",
                extra={"custom_dimensions": {
                    ld.OPERATION: "startup",
                    ld.COMPONENT: "dlq",
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
                "DLQClient: falha ao inicializar Azure Storage Queue",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "startup",
                    ld.COMPONENT: "dlq",
                }},
            )
            self.queue = None

    def enqueue(self, message: DLQMessage) -> bool:
        """Persiste uma falha na DLQ.

        Retorna True se enfileirou, False se DLQ indisponivel.
        Nunca levanta - falha em enqueue eh CRITICAL log, nao excecao.
        """
        if self.queue is None:
            logger.critical(
                "DLQ indisponivel: mensagem perdida sem persistencia",
                extra={"custom_dimensions": {
                    ld.OPERATION: "dlq_enqueue",
                    "target_operation": message.operation,
                    ld.EXTERNAL_SERVICE: message.external_service,
                    ld.SENDER_HASH: message.sender_hash,
                }},
            )
            return False

        try:
            payload_json = message.model_dump_json()
            self.queue.send_message(payload_json)
            logger.info(
                "mensagem enfileirada na DLQ",
                extra={"custom_dimensions": {
                    ld.OPERATION: "dlq_enqueue",
                    "target_operation": message.operation,
                    ld.EXTERNAL_SERVICE: message.external_service,
                    ld.SENDER_HASH: message.sender_hash,
                    "attempts": message.attempts,
                }},
            )
            return True
        except Exception:
            logger.critical(
                "falha ao enfileirar na DLQ - mensagem perdida",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "dlq_enqueue",
                    "target_operation": message.operation,
                    ld.SENDER_HASH: message.sender_hash,
                }},
            )
            return False

    def peek(self, max_messages: int = 32) -> list[dict[str, Any]]:
        """Le mensagens da fila SEM removelas. Util pro endpoint de listagem.

        Retorna lista de dicts com {id, content, dequeue_count, inserted_on}.
        """
        if self.queue is None:
            return []
        max_messages = max(1, min(max_messages, 32))  # Storage Queue: 1..32
        peeked = self.queue.peek_messages(max_messages=max_messages)
        return [
            {
                "id": m.id,
                "content": _safe_parse(m.content),
                "dequeue_count": m.dequeue_count,
                "inserted_on": m.inserted_on.isoformat() if m.inserted_on else None,
            }
            for m in peeked
        ]

    def receive_one(self) -> Optional[dict[str, Any]]:
        """Pega 1 mensagem da fila com visibility timeout (escondida por 5 min).

        Retorna dict com {id, pop_receipt, content} ou None se queue vazia.
        Caller obrigatorio chamar delete() depois de processar.
        """
        if self.queue is None:
            return None
        received = list(self.queue.receive_messages(
            messages_per_page=1,
            visibility_timeout=RECEIVE_VISIBILITY_SECONDS,
        ).by_page().next())
        if not received:
            return None
        m = received[0]
        return {
            "id": m.id,
            "pop_receipt": m.pop_receipt,
            "content": _safe_parse(m.content),
            "dequeue_count": m.dequeue_count,
        }

    def receive_by_id(self, message_id: str) -> Optional[dict[str, Any]]:
        """Pega 1 mensagem por ID. Storage Queue nao tem essa primitiva direta;
        iteramos paginas (32 msgs cada) com visibility_timeout curto ate achar.

        Antes pegava SO a primeira pagina (.by_page().next()) - bug silencioso
        com DLQ > 32 itens: admin retry de msg na pagina 2+ retornava 404
        falso. Agora itera todas as paginas.

        Custo: O(N/32) chamadas Storage Queue pra fila grande, mas eh acionado
        so via admin endpoint manual (raro), nao no caminho critico.

        Trade-off: durante a iteracao, todas as mensagens "tocadas" ficam
        com vis. timeout=5s. Se dois admins fizerem retry simultaneo, o
        segundo pode pegar paginas vazias - em 5s reaparecem, basta refazer.

        Quando acha o alvo: re-aplica vis. timeout=RECEIVE_VISIBILITY_SECONDS
        (5min) e devolve com pop_receipt atualizado (caso contrario delete
        posterior falharia com 'pop receipt mismatch').
        """
        if self.queue is None:
            return None
        try:
            pager = self.queue.receive_messages(
                messages_per_page=32,
                visibility_timeout=5,  # curto - so pra inspecionar
            ).by_page()
            for page in pager:
                for m in page:
                    if m.id == message_id:
                        updated = self.queue.update_message(
                            message=m,
                            visibility_timeout=RECEIVE_VISIBILITY_SECONDS,
                        )
                        return {
                            "id": m.id,
                            "pop_receipt": updated.pop_receipt,
                            "content": _safe_parse(m.content),
                            "dequeue_count": m.dequeue_count,
                        }
        except Exception:
            logger.error(
                "falha ao iterar paginas da DLQ buscando message_id",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "dlq_receive_by_id",
                    "message_id": message_id,
                }},
            )
        return None

    def delete(self, message_id: str, pop_receipt: str) -> bool:
        """Remove definitivamente da fila. Sempre chamado apos retry manual
        (sucesso ou falha) para evitar mensagens fantasmas."""
        if self.queue is None:
            return False
        try:
            self.queue.delete_message(message_id, pop_receipt)
            return True
        except Exception:
            logger.error(
                "falha ao deletar mensagem da DLQ",
                exc_info=True,
                extra={"custom_dimensions": {
                    ld.OPERATION: "dlq_delete",
                    "message_id": message_id,
                }},
            )
            return False


def _safe_parse(content: str) -> dict[str, Any]:
    """Tenta parsear o JSON da mensagem; em erro, retorna dict com raw."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": content}
