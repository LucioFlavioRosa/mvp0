"""Routers FastAPI agrupados por responsabilidade.

main.py monta o app, configura middleware/lifespan e faz include_router
de cada um destes modulos. Singletons (bot, dispatch_service, infobip,
dlq, sequence_queue, settings, sender_number) vivem em app.state e sao
acessados via request.app.state nos handlers.
"""

from app.api.health import router as health_router
from app.api.webhook import router as webhook_router
from app.api.admin import router as admin_router
from app.api.dispatch import router as dispatch_router

__all__ = [
    "health_router",
    "webhook_router",
    "admin_router",
    "dispatch_router",
]
