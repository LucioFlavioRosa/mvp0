"""Testes para o comportamento de rate limit (slowapi).

Estrategia: cada teste recria limiter zerado + reabilita, evita state
acumulado de testes anteriores que (mesmo desabilitado) registram contagem.
"""

from __future__ import annotations

import pytest

# State global do slowapi nao isola bem entre testes; rodar separado.
# Comando: pytest tests/unit/test_rate_limit.py -m slow
pytestmark = pytest.mark.slow


@pytest.fixture
def fresh_rate_limited_client(mock_settings, mock_db, mock_infobip, mock_dlq):
    """TestClient com main carregado E limiter resetado + habilitado.

    Resetamos AMBAS as instancias (global e do app.state) porque podem
    apontar pra storages diferentes apos reload.
    """
    from fastapi.testclient import TestClient
    import importlib
    import main
    importlib.reload(main)

    from app.core.rate_limit import limiter
    # Reset do storage global
    limiter.reset()
    limiter.enabled = True
    # Reset do storage do app
    main.app.state.limiter.reset()
    main.app.state.limiter.enabled = True

    yield TestClient(main.app)

    # Cleanup - garantir desabilitado pra proximo teste
    limiter.enabled = False
    main.app.state.limiter.enabled = False
    limiter.reset()
    main.app.state.limiter.reset()


def test_admin_dlq_bloqueia_apos_20_requests_no_mesmo_minuto(fresh_rate_limited_client):
    """admin_dlq tem decorator @limiter.limit('20/minute').
    Faz 25 requests, verifica bloqueio nas ultimas."""
    cli = fresh_rate_limited_client
    auth = ("admin-user", "admin-pass")

    status_codes = []
    for _ in range(25):
        r = cli.get("/admin/dlq", auth=auth)
        status_codes.append(r.status_code)

    # Pelo menos uma das primeiras 5 deve ser 200
    assert 200 in status_codes[:5], f"Nenhum 200 nas primeiras 5: {status_codes[:5]}"
    # Pelo menos uma das ultimas 5 deve ser 429
    assert 429 in status_codes[-5:], f"Nenhum 429 nas ultimas 5: {status_codes[-5:]}"


def test_dispatch_bloqueia_apos_10_requests(fresh_rate_limited_client):
    """/api/dispatch tem decorator @limiter.limit('10/minute')."""
    import main
    from unittest.mock import MagicMock

    user = MagicMock()
    user.claims = {"oid": "uuid-test", "preferred_username": "test@aegea.com.br"}

    async def override_auth():
        return user

    main.app.dependency_overrides[main.verify_dispatch_auth] = override_auth

    try:
        status_codes = []
        for _ in range(15):
            r = fresh_rate_limited_client.post(
                "/api/dispatch",
                json={"pedido_uuid": "test", "parceiros": []},
                headers={"Authorization": "Bearer fake"},
            )
            status_codes.append(r.status_code)

        # Primeiras 3 nao devem ser 429
        assert 429 not in status_codes[:3], f"429 cedo demais: {status_codes[:3]}"
        # Ultimas 3 devem ter pelo menos 1 429
        assert 429 in status_codes[-3:], f"Nao bateu 429 ao final: {status_codes[-3:]}"
    finally:
        main.app.dependency_overrides.clear()


def test_health_check_liveness_sem_rate_limit(fresh_rate_limited_client):
    """GET / nao tem @limiter.limit - probe pode bater sem limite."""
    for i in range(50):
        r = fresh_rate_limited_client.get("/")
        assert r.status_code == 200, f"Request {i+1} bloqueada"


def test_health_ready_sem_rate_limit(fresh_rate_limited_client, mocker):
    """GET /health/ready tambem nao tem rate limit."""
    mocker.patch("app.core.health.check_database", return_value={"status": "ok", "detail": "ok", "duration_ms": 1})
    mocker.patch("app.core.health.check_infobip", return_value={"status": "ok", "detail": "ok", "duration_ms": 1})
    mocker.patch("app.core.health.check_storage", return_value={"status": "ok", "detail": "ok", "duration_ms": 1})
    mocker.patch("app.core.health.check_keyvault", return_value={"status": "ok", "detail": "ok", "duration_ms": 1})

    for i in range(50):
        r = fresh_rate_limited_client.get("/health/ready")
        assert r.status_code == 200, f"Request {i+1} bloqueada"
