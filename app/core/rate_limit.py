"""Rate limit via slowapi com storage Redis (Azure Cache for Redis).

Por que Redis e nao in-memory:
- Gunicorn roda 4 workers (cada worker = processo Python independente, memoria isolada)
- App Service tem scaling automatico (1 -> N instancias sob carga)
- Sem estado compartilhado, limite "10/min" vira "10/min × workers × instancias"

Redis centraliza o contador. Limite configurado = limite real, independente de escala.

Setup necessario (uma vez):
- Azure Cache for Redis (tier Basic C0 minimo)
- Connection string como secret REDIS-CONNECTION-STRING no Key Vault

Fail-safe: se Redis indisponivel (secret ausente, network down, instancia caiu),
o limiter cai em modo in-memory automaticamente. Logamos CRITICAL mas a app
continua funcionando - perda de eficacia parcial do rate limit eh melhor que
caminho principal quebrar.
"""

from __future__ import annotations

from typing import Optional

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import Settings
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


def _build_storage_uri() -> Optional[str]:
    """Le REDIS-CONNECTION-STRING do Key Vault, converte para URI slowapi.

    Formato Azure Redis: 'host:port,password=xxx,ssl=True,abortConnect=False'
    Formato slowapi/limits espera: 'redis://[:password@]host:port[/db]'

    Retorna None se secret ausente -> fallback in-memory.
    """
    try:
        settings = Settings()
        conn_str = settings.get_secret("REDIS-CONNECTION-STRING")
    except Exception:
        logger.warning(
            "Settings indisponivel para REDIS-CONNECTION-STRING; rate limit em modo in-memory",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
            }},
        )
        return None

    if not conn_str:
        logger.warning(
            "REDIS-CONNECTION-STRING ausente; rate limit em modo in-memory (limite por worker, nao global)",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
                ld.MISSING_SECRETS: ["REDIS-CONNECTION-STRING"],
            }},
        )
        return None

    # Converter formato Azure (host:port,password=X,ssl=True) para redis:// URI
    # Exemplo entrada:
    #   mvp0-redis.redis.cache.windows.net:6380,password=ABC,ssl=True,abortConnect=False
    # Saida:
    #   rediss://:ABC@mvp0-redis.redis.cache.windows.net:6380/0
    try:
        parts = conn_str.split(",")
        host_port = parts[0].strip()
        params = {}
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.strip().lower()] = v.strip()

        password = params.get("password", "")
        # ssl=True usa rediss:// (TLS); senao redis://
        scheme = "rediss" if params.get("ssl", "").lower() == "true" else "redis"

        if password:
            uri = f"{scheme}://:{password}@{host_port}/0"
        else:
            uri = f"{scheme}://{host_port}/0"

        logger.info(
            "Redis connection string configurada para rate limit",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
                "scheme": scheme,
                "host": host_port.split(":")[0],
            }},
        )
        return uri
    except Exception:
        logger.error(
            "Erro ao parsear REDIS-CONNECTION-STRING; rate limit em modo in-memory",
            exc_info=True,
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
            }},
        )
        return None


# Tenta configurar com Redis; cai em in-memory se algo falhar
_storage_uri = _build_storage_uri()

if _storage_uri:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=_storage_uri,
        # Fallback in-memory se Redis cair durante runtime
        in_memory_fallback_enabled=True,
    )
else:
    # In-memory puro (dev local sem Redis, ou Redis nao configurado)
    limiter = Limiter(key_func=get_remote_address)
