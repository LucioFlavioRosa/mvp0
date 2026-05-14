"""Rate limit via slowapi com storage Redis (Azure Cache for Redis).

Por que Redis e nao in-memory:
- Gunicorn roda 4 workers (cada worker = processo Python independente, memoria isolada)
- App Service tem scaling automatico (1 -> N instancias sob carga)
- Sem estado compartilhado, limite "10/min" vira "10/min × workers × instancias"

Redis centraliza o contador. Limite configurado = limite real, independente de escala.

Setup necessario (uma vez):
- Azure Cache for Redis (tier Basic C0 minimo)
- Connection string como secret REDIS-CONNECTION-STRING no Key Vault

Inicializacao do storage URI:
- O modulo NAO le secret no import (evita network I/O em cada boot de
  Gunicorn worker antes do app inicializar). Cria o limiter com memory
  storage default.
- main.py chama configure_redis_storage(conn_str) no startup do lifespan,
  passando o secret ja em maos vindo do mesmo Settings singleton do app.state.
- Antes do primeiro request entrar, o storage Redis ja esta plugado.

Fail-safe: se Redis indisponivel (secret ausente, network down, instancia caiu),
o limiter cai em modo in-memory automaticamente. Logamos CRITICAL mas a app
continua funcionando - perda de eficacia parcial do rate limit eh melhor que
caminho principal quebrar.
"""

from __future__ import annotations

from typing import Optional

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


def _parse_azure_redis_to_uri(conn_str: str) -> Optional[str]:
    """Converte connection string do Azure Cache for Redis em URI slowapi.

    Formato Azure: 'host:port,password=xxx,ssl=True,abortConnect=False'
    Formato slowapi/limits: 'redis://[:password@]host:port[/db]'
    Com SSL: 'rediss://...'
    """
    try:
        parts = conn_str.split(",")
        host_port = parts[0].strip()
        params = {}
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.strip().lower()] = v.strip()

        password = params.get("password", "")
        scheme = "rediss" if params.get("ssl", "").lower() == "true" else "redis"

        if password:
            return f"{scheme}://:{password}@{host_port}/0"
        return f"{scheme}://{host_port}/0"
    except Exception:
        logger.error(
            "Erro ao parsear REDIS-CONNECTION-STRING",
            exc_info=True,
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
            }},
        )
        return None


# Limiter eh criado no import com storage in-memory default. Sem I/O de rede.
# main.py chamara configure_redis_storage() apos Settings estar pronto.
# Os decorators @limiter.limit("X/min") nos handlers funcionam imediatamente
# (em memoria) e migram pra Redis no primeiro request apos configure.
limiter = Limiter(key_func=get_remote_address)


def configure_redis_storage(connection_string: Optional[str]) -> bool:
    """Reconfigura o limiter pra usar Redis como storage compartilhado.

    Deve ser chamado pelo main.py durante o lifespan startup, ANTES do
    primeiro request chegar. slowapi cria o storage na primeira chamada
    de .limit(); reconfigurar antes disso eh seguro.

    Args:
        connection_string: secret REDIS-CONNECTION-STRING (formato Azure
            'host:port,password=X,ssl=True') ou None pra manter in-memory.

    Returns:
        True se Redis foi configurado, False se ficou em in-memory.
    """
    if not connection_string:
        logger.warning(
            "REDIS-CONNECTION-STRING ausente; rate limit em modo in-memory "
            "(limite por worker, nao global)",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
                ld.MISSING_SECRETS: ["REDIS-CONNECTION-STRING"],
            }},
        )
        return False

    uri = _parse_azure_redis_to_uri(connection_string)
    if not uri:
        return False

    # Substitui o storage_uri. Se _storage ja foi acessado (cached_property),
    # invalida o cache pra forcar re-init na proxima chamada.
    try:
        limiter._storage_uri = uri
        if "_storage" in limiter.__dict__:
            del limiter.__dict__["_storage"]
        # Habilita fallback in-memory se Redis cair durante runtime
        limiter.in_memory_fallback_enabled = True

        logger.info(
            "Redis configurado como storage do rate limit",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
                "scheme": uri.split(":", 1)[0],
                "host": uri.split("@")[-1].split("/")[0].split(":")[0] if "@" in uri else "n/a",
            }},
        )
        return True
    except Exception:
        logger.error(
            "Falha ao reconfigurar limiter pra Redis; permanece in-memory",
            exc_info=True,
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "rate_limit",
            }},
        )
        return False
