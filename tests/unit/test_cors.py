"""Testes para configuracao CORS via env var ALLOWED_ORIGINS.

Cobre:
- Origin permitido recebe headers Access-Control-Allow-Origin no preflight
- Origin nao listado NAO recebe headers CORS
- Env var ausente bloqueia todas origens

NOTA: precisamos recarregar main DENTRO de cada teste, depois de setar a
env var, para que ela seja lida pelo `os.environ.get("ALLOWED_ORIGINS")`
no escopo do modulo.
"""

from __future__ import annotations

import importlib

import pytest


def _reload_main_with_origins(origins: str | None, mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch):
    """Helper: define ALLOWED_ORIGINS no env, reload main, retorna TestClient.

    `origins` pode ser str comma-separated, "" (vazio) ou None (delete env var).
    """
    if origins is None:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_ORIGINS", origins)

    import main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    return TestClient(main.app)


def test_cors_preflight_aceita_origin_listado(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
):
    """OPTIONS com origin na lista retorna headers CORS completos."""
    cli = _reload_main_with_origins(
        "https://backoffice-aegea-prod.azurewebsites.net",
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
    )

    response = cli.options(
        "/api/dispatch",
        headers={
            "Origin": "https://backoffice-aegea-prod.azurewebsites.net",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )

    assert response.status_code == 200
    # Headers de aceite do preflight
    assert response.headers.get("access-control-allow-origin") == "https://backoffice-aegea-prod.azurewebsites.net"
    assert "POST" in response.headers.get("access-control-allow-methods", "")
    assert "authorization" in response.headers.get("access-control-allow-headers", "").lower()


def test_cors_preflight_rejeita_origin_nao_listado(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
):
    """OPTIONS com origin nao listado NAO retorna Access-Control-Allow-Origin.

    Quando o origin nao bate, FastAPI/Starlette NAO inclui o header CORS.
    O navegador entao bloqueia a request real (CORS error no console).
    """
    cli = _reload_main_with_origins(
        "https://backoffice-aegea-prod.azurewebsites.net",
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
    )

    response = cli.options(
        "/api/dispatch",
        headers={
            "Origin": "https://site-malicioso.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    # Sem header de allow-origin: browser bloqueia
    assert "access-control-allow-origin" not in response.headers


def test_cors_env_var_ausente_bloqueia_todas_origens(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
):
    """Sem ALLOWED_ORIGINS no env, lista vazia = bloqueia todos origins
    cross-site. Fail-safe (consistente com auth secrets ausentes -> 503)."""
    cli = _reload_main_with_origins(
        None,  # delete env var
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
    )

    response = cli.options(
        "/api/dispatch",
        headers={
            "Origin": "https://backoffice-aegea-prod.azurewebsites.net",
            "Access-Control-Request-Method": "POST",
        },
    )

    # Nenhum origin eh aceito quando ALLOWED_ORIGINS esta vazio
    assert "access-control-allow-origin" not in response.headers


def test_cors_multiplas_origens_separadas_por_virgula(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
):
    """ALLOWED_ORIGINS aceita lista comma-separated com varios ambientes."""
    cli = _reload_main_with_origins(
        "https://backoffice-aegea-prod.azurewebsites.net,https://backoffice-aegea-staging.azurewebsites.net,https://backoffice-aegea-dev.azurewebsites.net",
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch,
    )

    for origin in [
        "https://backoffice-aegea-prod.azurewebsites.net",
        "https://backoffice-aegea-staging.azurewebsites.net",
        "https://backoffice-aegea-dev.azurewebsites.net",
    ]:
        response = cli.options(
            "/api/dispatch",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.headers.get("access-control-allow-origin") == origin, f"Origin {origin} nao foi aceito"
