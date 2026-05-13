"""Testes para health checks de dependencias + endpoint GET /health/ready.

Cobre:
- 4 funcoes de check em app/core/health.py (SQL, Infobip, Storage, Key Vault)
- Endpoint /health/ready: 200 quando tudo OK, 503 quando qualquer falha

Politica testada:
- Endpoint sem auth (App Service readiness probe nao envia credentials)
- Body sempre tem detalhes de cada check (em 200 ou 503)
- duration_ms incluido para debug
- Falha em qualquer dependencia -> 503

Skill: aplicada do catalogo "Tipo 6 - Funcao pura" (checks) + "Tipo 1 - Endpoint"
(GET /health/ready).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ===========================================================================
# check_database
# ===========================================================================

def test_check_database_retorna_ok_em_select_1_sucesso():
    from app.core.health import check_database
    db = MagicMock()
    db.execute_read_one.return_value = (1,)

    result = check_database(db)

    assert result["status"] == "ok"
    assert "OK" in result["detail"]
    assert "duration_ms" in result
    db.execute_read_one.assert_called_once_with("SELECT 1", ())


def test_check_database_retorna_down_quando_select_retorna_none():
    """execute_read_one retorna None tanto em 'sem linha' quanto em 'erro
    silencioso' - health check trata ambos como falha."""
    from app.core.health import check_database
    db = MagicMock()
    db.execute_read_one.return_value = None

    result = check_database(db)

    assert result["status"] == "down"
    assert "None" in result["detail"]


def test_check_database_retorna_down_quando_query_levanta():
    from app.core.health import check_database
    db = MagicMock()
    db.execute_read_one.side_effect = RuntimeError("ODBC driver missing")

    result = check_database(db)

    assert result["status"] == "down"
    assert "RuntimeError" in result["detail"]
    assert "ODBC driver" in result["detail"]


# ===========================================================================
# check_infobip
# ===========================================================================

def test_check_infobip_retorna_ok_quando_client_e_sender_configurados():
    from app.core.health import check_infobip
    client = MagicMock()

    result = check_infobip(client, sender_number="5511999998888")

    assert result["status"] == "ok"
    # Detail nao deve expor o numero inteiro - so prefixo/sufixo
    assert "5511" in result["detail"]
    assert "88" in result["detail"]


def test_check_infobip_retorna_down_quando_client_none():
    from app.core.health import check_infobip

    result = check_infobip(client=None, sender_number="5511")

    assert result["status"] == "down"
    assert "nao inicializado" in result["detail"]


def test_check_infobip_retorna_down_quando_sender_vazio():
    from app.core.health import check_infobip
    client = MagicMock()

    result = check_infobip(client, sender_number="")

    assert result["status"] == "down"
    assert "INFOBIP-SENDER" in result["detail"]


# ===========================================================================
# check_storage
# ===========================================================================

def test_check_storage_retorna_ok_quando_get_queue_properties_sucede():
    from app.core.health import check_storage
    dlq = MagicMock()
    dlq.queue = MagicMock()
    dlq.queue.get_queue_properties.return_value = {"name": "outbound-dlq"}

    result = check_storage(dlq)

    assert result["status"] == "ok"
    dlq.queue.get_queue_properties.assert_called_once()


def test_check_storage_retorna_down_quando_dlq_none():
    from app.core.health import check_storage

    result = check_storage(dlq=None)

    assert result["status"] == "down"


def test_check_storage_retorna_down_quando_queue_none():
    """DLQClient instanciado mas com queue=None (connection string ausente)."""
    from app.core.health import check_storage
    dlq = MagicMock()
    dlq.queue = None

    result = check_storage(dlq)

    assert result["status"] == "down"
    assert "queue=None" in result["detail"]


def test_check_storage_retorna_down_quando_get_queue_properties_levanta():
    from app.core.health import check_storage
    dlq = MagicMock()
    dlq.queue = MagicMock()
    dlq.queue.get_queue_properties.side_effect = ConnectionError("network")

    result = check_storage(dlq)

    assert result["status"] == "down"
    assert "ConnectionError" in result["detail"]


# ===========================================================================
# check_keyvault
# ===========================================================================

def test_check_keyvault_retorna_ok_quando_secret_existe():
    from app.core.health import check_keyvault
    settings = MagicMock()
    settings.get_secret.return_value = "fake-api-key"

    result = check_keyvault(settings)

    assert result["status"] == "ok"
    settings.get_secret.assert_called_once_with("INFOBIP-API-KEY")


def test_check_keyvault_retorna_down_quando_secret_vazio():
    from app.core.health import check_keyvault
    settings = MagicMock()
    settings.get_secret.return_value = ""

    result = check_keyvault(settings)

    assert result["status"] == "down"
    assert "ausente" in result["detail"] or "vazio" in result["detail"]


def test_check_keyvault_retorna_down_quando_get_secret_levanta():
    """Simula Managed Identity revogada ou Key Vault inacessivel."""
    from app.core.health import check_keyvault
    settings = MagicMock()
    settings.get_secret.side_effect = RuntimeError("ClientAuthenticationError")

    result = check_keyvault(settings)

    assert result["status"] == "down"
    assert "RuntimeError" in result["detail"]


# ===========================================================================
# Endpoint GET /health/ready - 200 happy path
# ===========================================================================

def test_health_ready_retorna_200_quando_todos_checks_ok(client, mocker):
    """Happy path - todas as 4 dependencias OK."""
    mocker.patch("app.core.health.check_database",
                 return_value={"status": "ok", "detail": "SELECT 1 OK", "duration_ms": 5})
    mocker.patch("app.core.health.check_infobip",
                 return_value={"status": "ok", "detail": "client ok", "duration_ms": 1})
    mocker.patch("app.core.health.check_storage",
                 return_value={"status": "ok", "detail": "queue ok", "duration_ms": 12})
    mocker.patch("app.core.health.check_keyvault",
                 return_value={"status": "ok", "detail": "kv ok", "duration_ms": 0})

    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["checks"].keys()) == {"sql", "infobip", "storage", "keyvault"}
    assert body["duration_ms"] == 18  # soma


# ===========================================================================
# Endpoint GET /health/ready - 503 quando 1+ dependencia falha
# ===========================================================================

def test_health_ready_retorna_503_quando_sql_down(client, mocker):
    """SQL down -> 503. Outros checks OK ainda aparecem no body (dashboard)."""
    mocker.patch("app.core.health.check_database",
                 return_value={"status": "down", "detail": "ODBC missing", "duration_ms": 2000})
    mocker.patch("app.core.health.check_infobip",
                 return_value={"status": "ok", "detail": "ok", "duration_ms": 1})
    mocker.patch("app.core.health.check_storage",
                 return_value={"status": "ok", "detail": "ok", "duration_ms": 5})
    mocker.patch("app.core.health.check_keyvault",
                 return_value={"status": "ok", "detail": "ok", "duration_ms": 0})

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    # Body inclui detalhes - dashboard pode mostrar qual check falhou
    assert body["checks"]["sql"]["status"] == "down"
    assert body["checks"]["sql"]["detail"] == "ODBC missing"
    assert body["checks"]["infobip"]["status"] == "ok"


def test_health_ready_retorna_503_quando_multiplas_dependencias_down(client, mocker):
    """SQL + Storage down -> 503. Body lista todas."""
    mocker.patch("app.core.health.check_database",
                 return_value={"status": "down", "detail": "sql err", "duration_ms": 100})
    mocker.patch("app.core.health.check_infobip",
                 return_value={"status": "ok", "detail": "ok", "duration_ms": 1})
    mocker.patch("app.core.health.check_storage",
                 return_value={"status": "down", "detail": "queue err", "duration_ms": 50})
    mocker.patch("app.core.health.check_keyvault",
                 return_value={"status": "ok", "detail": "ok", "duration_ms": 0})

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["sql"]["status"] == "down"
    assert body["checks"]["storage"]["status"] == "down"


def test_health_ready_eh_publico_sem_auth(client):
    """App Service readiness probe nao envia credentials.
    /health/ready NAO pode requerer auth - se requerer, App Service nunca
    considera o app healthy."""
    response = client.get("/health/ready")  # sem auth header
    # 200 ou 503, mas NUNCA 401/503-auth
    assert response.status_code in (200, 503)
