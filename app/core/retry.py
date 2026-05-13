"""
Retry helper para chamadas HTTP externas.

Centraliza a politica de retry usada em integracoes (Infobip, Azure Blob,
ViaCEP, Google Maps). Politica:

- 2 tentativas TOTAL (initial + 1 retry).
- Backoff exponencial 1s -> 2s (max 5s) com jitter.
- Retry apenas em erros transientes (ver is_transient_http_error).
- Erros 4xx, ValueError, KeyError etc propagam direto (sem retry).

Uso:
    from app.core.retry import transient_retry

    @transient_retry
    def chamar_api_externa(url: str) -> dict:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
"""

from __future__ import annotations

from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)

MAX_ATTEMPTS = 2
WAIT_MIN_SECONDS = 1
WAIT_MAX_SECONDS = 5
WAIT_MULTIPLIER = 1


def is_transient_http_error(exception: BaseException) -> bool:
    """Predicate: retorna True se a exception deve disparar retry.

    Considera transientes:
    - requests.Timeout / requests.ConnectionError (rede)
    - requests.HTTPError com status >= 500 (server-side)
    - googlemaps.exceptions.Timeout / TransportError (Google Maps lib)
    - googlemaps.exceptions.HTTPError com status >= 500
    """
    if isinstance(exception, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exception, requests.HTTPError):
        response = exception.response
        return response is not None and response.status_code >= 500

    try:
        from googlemaps import exceptions as gmaps_exc
    except ImportError:
        return False

    if isinstance(exception, (gmaps_exc.Timeout, gmaps_exc.TransportError)):
        return True
    if isinstance(exception, gmaps_exc.HTTPError):
        status = getattr(exception, "status_code", None)
        return status is not None and status >= 500

    return False


def _log_retry_attempt(retry_state: Any) -> None:
    """Callback executado antes de cada retry. Loga WARNING estruturado."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    error_type = type(exc).__name__ if exc else "unknown"
    status_code = None
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status_code = exc.response.status_code
    elif exc is not None:
        status_code = getattr(exc, "status_code", None)

    sleep_s = 0.0
    if retry_state.next_action is not None:
        sleep_s = round(retry_state.next_action.sleep, 2)

    fn_name = retry_state.fn.__name__ if retry_state.fn else "unknown"

    logger.warning(
        "retry transient: vai tentar de novo",
        extra={"custom_dimensions": {
            ld.OPERATION: "http_retry",
            "function": fn_name,
            "attempt": retry_state.attempt_number,
            "max_attempts": MAX_ATTEMPTS,
            "sleep_seconds": sleep_s,
            "error_type": error_type,
            ld.EXTERNAL_STATUS: status_code,
        }},
    )


transient_retry = retry(
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential(
        multiplier=WAIT_MULTIPLIER,
        min=WAIT_MIN_SECONDS,
        max=WAIT_MAX_SECONDS,
    ),
    retry=retry_if_exception(is_transient_http_error),
    reraise=True,
    before_sleep=_log_retry_attempt,
)
