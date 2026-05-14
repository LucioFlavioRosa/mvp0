"""Fixtures globais para testes unitarios do mvp0."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("AZURE_KEYVAULT_URL", "https://kv-test.vault.azure.net")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_PII_SALT", "test-salt-fixed")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    yield


@pytest.fixture(autouse=True)
def disable_rate_limiter():
    try:
        from app.core.rate_limit import limiter
        limiter.enabled = False
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def disable_sequence_worker(mocker):
    try:
        mocker.patch("app.services.sequence_worker.start_worker", return_value=None)
        mocker.patch("app.services.sequence_worker.stop_worker", return_value=None)
    except (ModuleNotFoundError, AttributeError):
        pass


class FakeSettings:
    def __init__(self):
        self._secrets = {
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

    def get_secret(self, name):
        return self._secrets.get(name)

    def get_all_secrets(self, names):
        return {n: self._secrets[n] for n in names if n in self._secrets}

    def set(self, name, value):
        if value is None:
            self._secrets.pop(name, None)
        else:
            self._secrets[name] = value


@pytest.fixture
def mock_settings(mocker):
    """Patcha Settings via singleton bypass + name patch."""
    fake = FakeSettings()
    from app.core.config import Settings as _RealSettings
    mocker.patch.object(_RealSettings, "_instance", fake)
    mocker.patch("app.core.config.Settings", return_value=fake)
    return fake


@pytest.fixture
def mock_db(mocker):
    db = MagicMock(name="DatabaseManager")
    db.execute_read_one.return_value = None
    db.execute_write.return_value = True
    db.execute_write_with_rowcount.return_value = 1
    db.execute_transaction.return_value = True
    mocker.patch("app.core.database.DatabaseManager", return_value=db)
    return db


@pytest.fixture
def mock_infobip(mocker):
    client = MagicMock(name="InfobipClient")
    s = {"messages": [{"status": {"groupName": "PENDING"}}]}
    client.send_text.return_value = s
    client.send_image.return_value = s
    client.send_template.return_value = s
    mocker.patch("app.integrations.infobip.InfobipClient", return_value=client)
    return client


@pytest.fixture
def mock_dlq(mocker):
    dlq = MagicMock(name="DLQClient")
    dlq.enqueue.return_value = True
    dlq.peek.return_value = []
    dlq.receive_one.return_value = None
    dlq.receive_by_id.return_value = None
    dlq.delete.return_value = True
    mocker.patch("app.integrations.dlq.DLQClient", return_value=dlq)
    return dlq


@pytest.fixture
def client(mock_settings, mock_db, mock_infobip, mock_dlq, mocker):
    from fastapi.testclient import TestClient
    import importlib
    sq_mock = MagicMock(name="sequence_queue_in_main")
    sq_mock.enqueue.return_value = True
    mocker.patch(
        "app.integrations.sequence_queue.SequenceQueueClient",
        return_value=sq_mock,
    )
    import main
    importlib.reload(main)
    return TestClient(main.app)
