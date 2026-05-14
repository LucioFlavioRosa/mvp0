"""Entrypoint do app FastAPI.

Responsabilidades deste arquivo:
- Inicializar telemetria (antes do FastAPI app, para auto-instrumentacao
  pegar todas as rotas).
- Criar o app com lifespan context manager (substitui @app.on_event
  deprecated): startup cria SequenceQueueClient + sobe sequence_worker;
  shutdown sinaliza stop.
- Configurar CORS, rate limit e correlation_id middleware.
- Inicializar singletons (BotEngine, DispatchService, InfobipClient,
  DLQClient, Settings) e armazenar em app.state - os routers acessam
  via request.app.state.
- Incluir os routers de app/api/ (health, webhook, admin, dispatch).

Sem rotas inline aqui - elas vivem em app/api/*.py agrupadas por contexto.
"""

# Telemetria DEVE ser inicializada antes de criar FastAPI app
# (caso contrario, auto-instrumentacao nao pega o app).
from app.core.telemetry import configure_telemetry
configure_telemetry()

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.api import admin_router, dispatch_router, health_router, webhook_router
from app.bot_engine import BotEngine
from app.core.azure_auth import configure_azure_auth
from app.core.config import Settings
from app.core.rate_limit import limiter, configure_redis_storage
from app.core.telemetry import correlation_id_middleware, get_logger
from app.core import log_dimensions as ld
from app.integrations.dlq import DLQClient
from app.integrations.infobip import InfobipClient
from app.integrations.sequence_queue import SequenceQueueClient
from app.services import sequence_worker
from app.services.dispatch_service import DispatchService

logger = get_logger(__name__)


# ==============================================================================
# 1. LIFESPAN (startup + shutdown)
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Substitui @app.on_event (deprecated). Roda 1x por processo Gunicorn.

    Startup: instancia SequenceQueueClient (cria queue idempotentemente no
    Azure) e sobe o sequence_worker em thread daemon. Shutdown: sinaliza
    stop pro worker.
    """
    # ----- STARTUP -----
    # Configura Redis como storage do rate limiter usando o Settings ja
    # populado em app.state. Evita Settings() inline no module load do
    # rate_limit.py (que rodaria a cada Gunicorn worker boot).
    try:
        redis_conn = app.state.settings.get_secret("REDIS-CONNECTION-STRING")
        configure_redis_storage(redis_conn)
    except Exception:
        logger.error("falha ao configurar Redis no rate limiter", exc_info=True,
                     extra={"custom_dimensions": {ld.OPERATION: "startup"}})

    # Configura Azure AD JWT scheme via mesmo Settings singleton.
    # Antes era inicializado no import de azure_auth.py - tirou-se de la
    # pra evitar I/O Key Vault no boot de cada Gunicorn worker.
    try:
        configure_azure_auth(app.state.settings)
    except Exception:
        logger.error("falha ao configurar Azure AD auth", exc_info=True,
                     extra={"custom_dimensions": {ld.OPERATION: "startup"}})

    try:
        app.state.sequence_queue = SequenceQueueClient()
        sequence_worker.start_worker()
        logger.info("sequence_worker iniciado",
                    extra={"custom_dimensions": {ld.OPERATION: "startup"}})
    except Exception:
        logger.error("falha ao iniciar sequence_worker", exc_info=True,
                     extra={"custom_dimensions": {ld.OPERATION: "startup"}})
        app.state.sequence_queue = None

    yield  # app esta vivo aqui

    # ----- SHUTDOWN -----
    try:
        sequence_worker.stop_worker(timeout=2.0)
    except Exception:
        pass


app = FastAPI(
    title="Bot Aguas do Para",
    version="1.0.0",
    lifespan=lifespan,
)


# ==============================================================================
# 2. MIDDLEWARE: rate limit + CORS + correlation_id
# ==============================================================================
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS apertado via env var ALLOWED_ORIGINS (comma-separated). Sem env var,
# lista vazia (bloqueia todas origens cross-site - fail-safe).
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
if _allowed_origins_raw:
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]
    logger.info("CORS configurado", extra={"custom_dimensions": {
        ld.OPERATION: "startup",
        ld.COMPONENT: "cors",
        "origins_count": len(_allowed_origins),
    }})
else:
    _allowed_origins = []
    logger.critical(
        "ALLOWED_ORIGINS nao configurado - CORS bloqueia TODAS as origens",
        extra={"custom_dimensions": {
            ld.OPERATION: "startup",
            ld.COMPONENT: "cors",
        }},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.middleware("http")(correlation_id_middleware)


# ==============================================================================
# 3. SINGLETONS (state global do app)
# ==============================================================================
# Inicializa Settings, BotEngine, DispatchService, InfobipClient e DLQClient
# uma vez no startup. Cada um eh armazenado em app.state para que routers
# em app/api/ acessem via request.app.state.<nome>.
app.state.settings = Settings()

try:
    app.state.bot = BotEngine()
    app.state.dispatch_service = DispatchService()
    logger.info("motores inicializados", extra={"custom_dimensions": {
        ld.OPERATION: "startup", ld.COMPONENT: "engines",
    }})
except Exception:
    logger.critical("falha critica ao iniciar motores", exc_info=True,
                    extra={"custom_dimensions": {ld.OPERATION: "startup"}})
    app.state.bot = None
    app.state.dispatch_service = None

try:
    _api_key = app.state.settings.get_secret("INFOBIP-API-KEY")
    _base_url = app.state.settings.get_secret("INFOBIP-BASE-URL")
    _sender_number = app.state.settings.get_secret("INFOBIP-SENDER") or ""

    if _api_key and _base_url and _sender_number:
        app.state.infobip_client = InfobipClient(api_key=_api_key, base_url=_base_url)
        app.state.sender_number = _sender_number
        logger.info("cliente Infobip autenticado", extra={"custom_dimensions": {
            ld.OPERATION: "startup", ld.COMPONENT: "infobip",
        }})
    else:
        app.state.infobip_client = None
        app.state.sender_number = ""
        missing = [k for k, v in {
            "INFOBIP-API-KEY": _api_key,
            "INFOBIP-BASE-URL": _base_url,
            "INFOBIP-SENDER": _sender_number,
        }.items() if not v]
        logger.warning("credenciais Infobip ausentes", extra={"custom_dimensions": {
            ld.OPERATION: "startup", ld.MISSING_SECRETS: missing,
        }})
except Exception:
    app.state.infobip_client = None
    app.state.sender_number = ""
    logger.error("erro ao iniciar Infobip", exc_info=True,
                 extra={"custom_dimensions": {ld.OPERATION: "startup"}})

app.state.dlq = DLQClient()
app.state.blob_service = None  # lazy-init pelo helper de retry DLQ
app.state.sequence_queue = None  # populado pelo lifespan no startup


# ==============================================================================
# 4. ROUTERS (rotas em app/api/*.py)
# ==============================================================================
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(admin_router)
app.include_router(dispatch_router)
