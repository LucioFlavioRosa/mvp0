"""
Worker em background que consome SequenceQueue e envia cada mensagem
ao Infobip respeitando os delays declarados.

Vive como uma thread daemon dentro do mesmo processo Gunicorn (1 worker
por processo). Com 4 workers Gunicorn, voce tem 4 threads polando a fila
em paralelo - Storage Queue ja serializa via visibility timeout, sem
risco de duplicar processamento da mesma mensagem.

Por que NAO usar BackgroundTasks do FastAPI:
- BackgroundTasks roda funcoes sync no thread pool do anyio (~36 threads).
  time.sleep longo (ex: 30s da validacao CNPJ) segura uma thread ate o
  fim, podendo exaurir o pool em picos.
- Worker dedicado isola o problema: webhook so enqueue (microsegundos),
  worker consome no proprio ritmo. Webhook nunca espera pelo envio.

Politica:
- Worker daemon (morre com o processo, sem cleanup graceful complexo).
- Em shutdown sinalizado: para de pegar mensagens novas, NAO interrompe
  a sequencia em andamento (deixa terminar ou cai junto com o processo).
  Sequencias parciais nao deletadas reaparecem apos visibility timeout.
- Falha durante envio: NAO deleta a mensagem. Storage Queue redeliveria
  apos visibility (5 min). Se dequeue_count > POISON_THRESHOLD, registra
  CRITICAL e deleta (evita loop infinito).
- Sucesso completo: deleta a mensagem da queue.

Idempotencia: se um envio falhar a meio caminho e a mensagem reaparecer,
o usuario VAI receber as primeiras N mensagens duplicadas. Aceitavel a
100/dia (estimado < 0.1% das sequencias). Mitigacao futura: tracker de
sent_index dentro do payload.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from app.core.config import Settings
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
from app.integrations.infobip import InfobipClient
from app.integrations.sequence_queue import SequenceQueueClient, POISON_THRESHOLD

logger = get_logger(__name__)

DEFAULT_TEMPLATE_LANGUAGE = "pt_BR"
POLL_INTERVAL_SECONDS = 2  # entre polls vazios; 2s = ~30 polls/min por worker

# State global do worker. Singleton por processo Gunicorn.
_shutdown = threading.Event()
_worker_thread: Optional[threading.Thread] = None


def _send_item(client: InfobipClient, sender: str, sender_id: str, item: dict[str, Any]) -> None:
    """Envia 1 item da sequencia. Levanta excecao em falha (caller decide retry)."""
    tipo = item.get("tipo")
    if tipo == "texto":
        conteudo = item.get("conteudo") or item.get("texto")
        if conteudo:
            client.send_text(sender=sender, to=sender_id, text=conteudo)
    elif tipo == "media":
        client.send_image(
            sender=sender,
            to=sender_id,
            media_url=item["url"],
            caption=item.get("legenda") or None,
        )
    elif tipo == "template":
        client.send_template(
            sender=sender,
            to=sender_id,
            template_name=item.get("template_name") or item.get("sid"),
            language=item.get("language", DEFAULT_TEMPLATE_LANGUAGE),
            placeholders=item.get("placeholders") or [],
        )


def _process_message(
    client: InfobipClient,
    sender: str,
    queue: SequenceQueueClient,
    msg: dict[str, Any],
) -> None:
    """Processa uma sequencia inteira: respeita delays, envia, deleta da queue."""
    content = msg.get("content") or {}
    sender_id = content.get("sender_id", "")
    sequence = content.get("sequence", [])
    dequeue_count = msg.get("dequeue_count", 0)

    # Poison: dequeue_count alto = sequencia falhando ha tempos. Deleta + alerta.
    if dequeue_count > POISON_THRESHOLD:
        logger.critical(
            "sequencia poison detectada - removendo da fila",
            extra={"custom_dimensions": {
                ld.OPERATION: "sequence_poison",
                ld.SENDER_HASH: mask_pii(sender_id),
                "dequeue_count": dequeue_count,
                "items_count": len(sequence),
            }},
        )
        queue.delete(msg["id"], msg["pop_receipt"])
        return

    try:
        for item in sequence:
            if _shutdown.is_set():
                # Shutdown sinalizado: para imediatamente sem deletar.
                # Storage Queue redeliveria apos visibility timeout.
                logger.info(
                    "sequence_worker: shutdown durante sequencia - msg ficara na queue",
                    extra={"custom_dimensions": {
                        ld.OPERATION: "sequence_interrupted",
                        ld.SENDER_HASH: mask_pii(sender_id),
                    }},
                )
                return
            delay = item.get("delay", 1.0)
            if delay > 0:
                # _shutdown.wait(timeout=delay) e melhor que time.sleep:
                # acorda imediatamente em shutdown ao inves de bloquear.
                if _shutdown.wait(timeout=delay):
                    logger.info(
                        "sequence_worker: shutdown durante delay - msg ficara na queue",
                        extra={"custom_dimensions": {
                            ld.OPERATION: "sequence_interrupted",
                            ld.SENDER_HASH: mask_pii(sender_id),
                        }},
                    )
                    return
            _send_item(client, sender, sender_id, item)

        # Toda a sequencia rolou. Deleta da queue.
        queue.delete(msg["id"], msg["pop_receipt"])
        logger.info(
            "sequencia processada",
            extra={"custom_dimensions": {
                ld.OPERATION: "sequence_processed",
                ld.SENDER_HASH: mask_pii(sender_id),
                "items_count": len(sequence),
            }},
        )

    except Exception:
        # NAO deleta - msg volta a ficar visivel apos visibility timeout.
        # Storage Queue incrementa dequeue_count; eventualmente vira poison.
        logger.error(
            "falha ao processar sequencia (msg ficara na queue para retry)",
            exc_info=True,
            extra={"custom_dimensions": {
                ld.OPERATION: "sequence_failed",
                ld.SENDER_HASH: mask_pii(sender_id),
                "dequeue_count": dequeue_count,
            }},
        )


def _worker_loop() -> None:
    """Loop principal: inicializa Infobip + queue, faz polling em loop."""
    settings = Settings()
    api_key = settings.get_secret("INFOBIP-API-KEY")
    base_url = settings.get_secret("INFOBIP-BASE-URL")
    sender = settings.get_secret("INFOBIP-SENDER") or ""

    if not (api_key and base_url and sender):
        logger.warning(
            "sequence_worker: credenciais Infobip ausentes; worker nao iniciara",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "sequence_worker",
                ld.MISSING_SECRETS: [
                    k for k, v in {
                        "INFOBIP-API-KEY": api_key,
                        "INFOBIP-BASE-URL": base_url,
                        "INFOBIP-SENDER": sender,
                    }.items() if not v
                ],
            }},
        )
        return

    client = InfobipClient(api_key=api_key, base_url=base_url)
    queue = SequenceQueueClient()

    if queue.queue is None:
        logger.warning(
            "sequence_worker: SequenceQueue indisponivel; worker nao iniciara",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "sequence_worker",
            }},
        )
        return

    logger.info(
        "sequence_worker iniciado",
        extra={"custom_dimensions": {
            ld.OPERATION: "startup",
            ld.COMPONENT: "sequence_worker",
        }},
    )

    while not _shutdown.is_set():
        msg = queue.receive_one()
        if msg:
            _process_message(client, sender, queue, msg)
        else:
            # Queue vazia: aguarda antes do proximo poll.
            # wait() acorda imediatamente se _shutdown for setado.
            _shutdown.wait(timeout=POLL_INTERVAL_SECONDS)

    logger.info(
        "sequence_worker encerrado",
        extra={"custom_dimensions": {
            ld.OPERATION: "shutdown",
            ld.COMPONENT: "sequence_worker",
        }},
    )


def start_worker() -> None:
    """Inicia o worker em thread daemon. Idempotente (no-op se ja rodando)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _shutdown.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        daemon=True,
        name="sequence-worker",
    )
    _worker_thread.start()


def stop_worker(timeout: float = 5.0) -> None:
    """Sinaliza shutdown e aguarda thread terminar (com timeout).

    Em producao o processo morre antes do timeout (daemon=True), mas em
    testes garantimos cleanup explicito.
    """
    _shutdown.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=timeout)
