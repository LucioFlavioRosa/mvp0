"""Validacao JWT Azure AD / Entra ID para /api/dispatch.

Usa fastapi-azure-auth (wrapper da MSAL python) que faz:
- Cache das chaves publicas do tenant Azure AD (refresh a cada 24h)
- Validacao offline da assinatura JWT (sem rede a cada request)
- Validacao dos claims padrao (aud, iss, exp, scp)
- Injeta o usuario validado como Depends() no endpoint

Setup necessario no Azure AD (uma vez por ambiente):
- App Registration "Bot Aguas API" (esta API): expose scope dispatch.write
- App Registration "Bot Aguas Backoffice": cliente que vai consumir,
  com permissao no scope acima + admin consent
- 2 secrets no Key Vault: AZURE-AD-TENANT-ID, AZURE-AD-API-CLIENT-ID

Detalhes em docs/AUTH-AZURE-AD.md.
"""

from __future__ import annotations

from typing import Optional

from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

from app.core.config import Settings
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


# Singleton - inicializado uma vez no startup
_azure_scheme: Optional[SingleTenantAzureAuthorizationCodeBearer] = None
_init_error: Optional[str] = None


def _init_scheme() -> Optional[SingleTenantAzureAuthorizationCodeBearer]:
    """Carrega config do Key Vault e cria o validador JWT.

    Retorna None se algum dos 2 secrets estiver ausente (fail-safe -
    endpoint que usa azure_scheme vai falhar com 503 documentado).
    """
    global _init_error
    settings = Settings()

    tenant_id = settings.get_secret("AZURE-AD-TENANT-ID")
    api_client_id = settings.get_secret("AZURE-AD-API-CLIENT-ID")

    missing = [k for k, v in {
        "AZURE-AD-TENANT-ID": tenant_id,
        "AZURE-AD-API-CLIENT-ID": api_client_id,
    }.items() if not v]

    if missing:
        _init_error = f"secrets ausentes: {missing}"
        logger.warning(
            "Azure AD auth nao inicializado",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "azure_auth",
                ld.MISSING_SECRETS: missing,
            }},
        )
        return None

    try:
        scheme = SingleTenantAzureAuthorizationCodeBearer(
            app_client_id=api_client_id,
            tenant_id=tenant_id,
            scopes={
                f"api://{api_client_id}/dispatch.write": "Disparar oferta de servico a parceiros",
            },
            # Operadores logam via MSAL no backoffice e enviam tokens delegados
            # para nossa API. allow_guest_users=False por default (apenas membros
            # do tenant Aegea podem chamar - convidados externos sao bloqueados).
            allow_guest_users=False,
        )
        logger.info(
            "Azure AD auth inicializado",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "azure_auth",
                "tenant_id_suffix": tenant_id[-4:] if tenant_id else "",
            }},
        )
        return scheme
    except Exception as exc:
        _init_error = f"erro inicializando scheme: {type(exc).__name__}"
        logger.error(
            "erro ao inicializar Azure AD auth",
            exc_info=True,
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "azure_auth",
            }},
        )
        return None


def get_azure_scheme() -> Optional[SingleTenantAzureAuthorizationCodeBearer]:
    """Acessor publico do scheme. Usar como `Depends(get_azure_scheme())` nao funciona
    diretamente porque o resultado da chamada nao eh callable. Em main.py expor
    diretamente `azure_scheme` no escopo do modulo.
    """
    return _azure_scheme


def get_init_error() -> Optional[str]:
    """Mensagem de erro do startup, util pro endpoint retornar 503 com detalhe."""
    return _init_error


# Inicializa no import do modulo. Try/except global para tolerar Key Vault
# inacessivel (ex: testes locais, sandbox CI sem credentials Azure).
# Em producao com Managed Identity, _init_scheme() funciona normalmente.
try:
    _azure_scheme = _init_scheme()
except Exception as exc:
    _azure_scheme = None
    _init_error = f"falha global no init: {type(exc).__name__}"
    logger.warning(
        "Azure AD auth init falhou (ambiente sem Key Vault acessivel?)",
        extra={"custom_dimensions": {
            ld.OPERATION: "startup",
            ld.COMPONENT: "azure_auth",
        }},
    )
