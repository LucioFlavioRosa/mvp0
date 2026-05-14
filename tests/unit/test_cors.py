"""Testes para configuracao CORS via env var ALLOWED_ORIGINS."""

from __future__ import annotations

import importlib

import pytest


def _reload_main_with_origins(origins, mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker):
    """Define ALLOWED_ORIGINS, patcha SequenceQueueClient, reload main."""
    if origins is None:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_ORIGINS", origins)

    from unittest.mock import MagicMock
    sq_mock = MagicMock(name="sq_for_cors_test")
    sq_mock.enqueue.return_value = True
    mocker.patch(
        "app.integrations.sequence_queue.SequenceQueueClient",
        return_value=sq_mock,
    )

    import main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    return TestClient(main.app)


def test_cors_preflight_aceita_origin_listado(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
):
    cli = _reload_main_with_origins(
        "https://backoffice-aegea-prod.azurewebsites.net",
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
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
    assert response.headers.get("access-control-allow-origin") == "https://backoffice-aegea-prod.azurewebsites.net"
    assert "POST" in response.headers.get("access-control-allow-methods", "")
    assert "authorization" in response.headers.get("access-control-allow-headers", "").lower()


def test_cors_preflight_rejeita_origin_nao_listado(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
):
    cli = _reload_main_with_origins(
        "https://backoffice-aegea-prod.azurewebsites.net",
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
    )

    response = cli.options(
        "/api/dispatch",
        headers={
            "Origin": "https://site-malicioso.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_env_var_ausente_bloqueia_todas_origens(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
):
    cli = _reload_main_with_origins(
        None,
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
    )

    response = cli.options(
        "/api/dispatch",
        headers={
            "Origin": "https://backoffice-aegea-prod.azurewebsites.net",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_multiplas_origens_separadas_por_virgula(
    mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
):
    cli = _reload_main_with_origins(
        "https://backoffice-aegea-prod.azurewebsites.net,https://backoffice-aegea-staging.azurewebsites.net,https://backoffice-aegea-dev.azurewebsites.net",
        mock_settings, mock_db, mock_infobip, mock_dlq, monkeypatch, mocker,
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
