"""Fixtures globais para testes unitarios do mvp0.

Convencoes:
- Tudo aqui eh mockado, nada toca rede/disco/DB real.
- Para mock granular em teste especifico, usar fixture local (no proprio test_*.py).

Ordem de aplicacao das fixtures:
    env_vars (autouse) -> mock_settings -> mock_db / mock_infobip / mock_dlq -> client

Requisitos do ambiente:
- ODBC driver disponivel no sistema (libodbc.so.2) - pyodbc precisa pra
  importar mesmo que nunca abra conexao. Em GitHub Actions, instalar com
  `apt-get install -y unixodbc` (ja configurado em .github/workflows/tests.yml).
  Em dev local com pyodbc instalado via wheel, normalmente ja vem com a lib.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Ambiente (env vars que main.py / Settings esperam)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    """Define env vars minimas para que imports nao explodam.

    Aplicado automaticamente em todos os testes (autouse=True).
    """
    monkeypatch.setenv("AZURE_KEYVAULT_URL", "https://kv-test.vault.azure.net")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_PII_SALT", "test-salt-fixed")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    yield


@pytest.fixture(autouse=True)
def disable_rate_limiter():
    """Desabilita o rate limiter em TODOS os testes por default.

    Razao: TestClient roda tudo como 127.0.0.1 e nao zera contadores entre
    testes da mesma suite. Sem isso, testes que fazem >N requests batem em
    429 e falham (mesmo testes que nao tem nada a ver com rate limit).

    Para testar comportamento de rate limit, ver tests/unit/test_rate_limit.py
    que tem fixture local para reabilitar. Essa fixture LOCAL eh responsavel
    por restaurar enabled=False no cleanup (esta autouse so seta False antes).
    """
    try:
        from app.core.rate_limit import limiter
        limiter.enabled = False
    except Exception:
        pass
    yield
    # NAO restauramos enabled aqui - fixture enable_rate_limiter local
    # faz isso no cleanup dela. Restaurar aqui causava bug onde "previous"
    # capturava True de teste anterior nao limpo, e o autouse seguinte
    # mantinha True por engano.


# ---------------------------------------------------------------------------
# Settings (mock do Key Vault)
# ---------------------------------------------------------------------------
class FakeSettings:
    """Substituto do Settings real. Aceita get/set arbitrarios.

    Uso em teste:
        def test_X(mock_settings):
            mock_settings.set("ADMIN-USER", "custom")
            mock_settings.set("ADMIN-PASSWORD", None)  # remove
    """

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {
            "INFOBIP-API-KEY": "fake-infobip-key",
            "INFOBIP-BASE-URL": "https://fake.api.infobip.com",
            "INFOBIP-SENDER": "5511999998888",
            "INFOBIP-WEBHOOK-USER": "webhook-user",
            "INFOBIP-WEBHOOK-PASSWORD": "webhook-pass",
            "ADMIN-USER": "admin-user",
            "ADMIN-PASSWORD": "admin-pass",
            "CONNECTION-STRING-AZURE-STORAGE":
                "DefaultEndpointsProtocol=https;AccountName=fake;AccountKey=fake==;"
                "EndpointSuffix=core.windows.net",
            "DB-SERVER": "fake.database.windows.net",
            "DB-NAME": "fake_db",
            "DB-USER": "fake_user",
            "DB-PASSWORD": "fake_pwd",
            "GOOGLE-MAPS-API-KEY": "fake-gmaps-key",
            "VIDEO-URL": "https://fake.blob.core.windows.net/video.mp4",
        }

    def get_secret(self, name: str) -> str | None:
        return self._secrets.get(name)

    def get_all_secrets(self, names: list[str]) -> dict[str, str]:
        return {n: self._secrets[n] for n in names if n in self._secrets}

    def set(self, name: str, value: str | None) -> None:
        if value is None:
            self._secrets.pop(name, None)
        else:
            self._secrets[name] = value


@pytest.fixture
def mock_settings(mocker) -> FakeSettings:
    """Settings mockado retornando dict in-memory."""
    fake = FakeSettings()
    mocker.patch("app.core.config.Settings", return_value=fake)
    return fake


# ---------------------------------------------------------------------------
# DatabaseManager (mock SQL)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db(mocker):
    """DatabaseManager mockado.

    Defaults:
    - execute_read_one retorna None
    - execute_write retorna True
    - execute_write_with_rowcount retorna 1 (1 linha afetada = sucesso)
    - execute_transaction retorna True

    Override em teste especifico:
        mock_db.execute_read_one.return_value = ("uuid", "Nome")
        mock_db.execute_read_one.side_effect = [linha1, linha2, None]
        mock_db.execute_write_with_rowcount.return_value = 0  # simular conflito
    """
    db = MagicMock(name="DatabaseManager")
    db.execute_read_one.return_value = None
    db.execute_write.return_value = True
    db.execute_write_with_rowcount.return_value = 1
    db.execute_transaction.return_value = True
    mocker.patch("app.core.database.DatabaseManager", return_value=db)
    return db


# ---------------------------------------------------------------------------
# InfobipClient (mock HTTP outbound do Infobip)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_infobip(mocker):
    """InfobipClient mockado.

    Para simular falha:
        import requests
        mock_infobip.send_text.side_effect = requests.HTTPError("503")
    """
    client = MagicMock(name="InfobipClient")
    _success = {"messages": [{"status": {"groupName": "PENDING"}}]}
    client.send_text.return_value = _success
    client.send_image.return_value = _success
    client.send_template.return_value = _success
    mocker.patch("app.integrations.infobip.InfobipClient", return_value=client)
    return client


# ---------------------------------------------------------------------------
# DLQ (mock Azure Storage Queue)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_dlq(mocker):
    """DLQClient mockado.

    enqueue=True, peek/receive_*=vazio por default.
    """
    dlq = MagicMock(name="DLQClient")
    dlq.enqueue.return_value = True
    dlq.peek.return_value = []
    dlq.receive_one.return_value = None
    dlq.receive_by_id.return_value = None
    dlq.delete.return_value = True
    mocker.patch("app.integrations.dlq.DLQClient", return_value=dlq)
    return dlq


@pytest.fixture
def client(mock_settings, mock_db, mock_infobip, mock_dlq):
    """TestClient com main.app + mocks aplicados.

    Importa main DENTRO da fixture pra que os patches acima estejam ativos
    quando main.py roda seus imports e startup.
    """
    from fastapi.testclient import TestClient
    import importlib
    import main
    importlib.reload(main)
    return TestClient(main.app)
