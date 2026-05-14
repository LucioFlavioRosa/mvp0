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

Inicializacao do scheme:
- O modulo NAO le secrets no import (evita network I/O em cada boot de
  Gunicorn worker antes do app inicializar).
- main.py chama configure_azure_auth(settings) no startup do lifespan,
  usando o Settings ja populado em app.state.settings (mesma instancia
  singleton, sem dupla chamada Key Vault).
- Endpoints que dependem do scheme leem dinamicamente via get_azure_scheme()
  - se chamado antes do configure, retorna None e o endpoint cai em 503.

Detalhes em docs/AUTH-AZURE-AD.md.
"""

from __future__ import annotations

from typing import Optional

from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


# Estado global do scheme. Populado por configure_azure_auth() no lifespan startup.
_azure_scheme: Optional[SingleTenantAzureAuthorizationCodeBearer] = None
_init_error: Optional[str] = None


def configure_azure_auth(settings) -> bool:
    """Inicializa o scheme JWT do Azure AD usando secrets do Settings.

    Chamado uma vez no lifespan startup do main.py. Apos sucesso,
    get_azure_scheme() retorna o scheme; antes disso retorna None.

    Args:
        settings: instancia Settings (do app.state.settings).

    Returns:
        True se scheme foi configurado, False se algum secret ausente ou
        erro. Em ambos os casos o estado fica em _init_error para o
        endpoint retornar 503 com detalhe util.
    """
    global _azure_scheme, _init_error

    tenant_id = settings.get_secret("AZURE-AD-TENANT-ID")
    api_client_id = settings.get_secret("AZURE-AD-API-CLIENT-ID")

    missing = [k for k, v in {
        "AZURE-AD-TENANT-ID": tenant_id,
        "AZURE-AD-API-CLIENT-ID": api_client_id,
    }.items() if not v]

    if missing:
        _init_error = f"secrets ausentes: {missing}"
        _azure_scheme = None
        logger.warning(
            "Azure AD auth nao inicializado",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "azure_auth",
                ld.MISSING_SECRETS: missing,
            }},
        )
        return False

    try:
        _azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
            app_client_id=api_client_id,
            tenant_id=tenant_id,
            scopes={
                f"api://{api_client_id}/dispatch.write": "Disparar oferta de servico a parceiros",
            },
            # Operadores logam via MSAL no backoffice e enviam tokens delegados.
            # allow_guest_users=False: apenas membros do tenant Aegea (convidados
            # externos sao bloqueados).
            allow_guest_users=False,
        )
        _init_error = None
        logger.info(
            "Azure AD auth inicializado",
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "azure_auth",
                "tenant_id_suffix": tenant_id[-4:] if tenant_id else "",
            }},
        )
        return True
    except Exception as exc:
        _azure_scheme = None
        _init_error = f"erro inicializando scheme: {type(exc).__name__}"
        logger.error(
            "erro ao inicializar Azure AD auth",
            exc_info=True,
            extra={"custom_dimensions": {
                ld.OPERATION: "startup",
                ld.COMPONENT: "azure_auth",
            }},
        )
        return False


def get_azure_scheme() -> Optional[SingleTenantAzureAuthorizationCodeBearer]:
    """Retorna o scheme JWT atualmente configurado ou None.

    Endpoints devem chamar este getter dinamicamente em cada request (e
    NAO cachear no escopo do modulo) para que a configuracao via lifespan
    seja vista assim que disponivel.
    """
    return _azure_scheme


def get_init_error() -> Optional[str]:
    """Mensagem de erro do startup, util pro endpoint retornar 503 com detalhe."""
    return _init_error
