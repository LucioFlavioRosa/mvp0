"""Fixtures globais para testes unitarios do mvp0.

Convencoes:
- Tudo aqui eh mockado, nada toca rede/disco/DB real.
- Para mock granular em teste especifico, usar fixture local (no proprio test_*.py).

Ordem de aplicacao das fixtures:
    env_vars (autouse) -> mock_settings -> mock_db / mock_infobip / mock_dlq -> client
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
    monkeypatch.setenv("LOG_LEVEL", "WARNING")  # silencia logs em testes
    monkeypatch.setenv("LOG_PII_SALT", "test-salt-fixed")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    yield


# ---------------------------------------------------------------------------
# Settings (mock do Key Vault)
# ---------------------------------------------------------------------------
class FakeSettings:
    """Substituto do Settings real. Aceita get/set arbitrarios.

    Uso em teste:
        def test_X(mock_settings):
            mock_settings.set("ADMIN-USER", "custom")  # sobrescreve
            mock_settings.set("ADMIN-PASSWORD", None)  # remove (simula secret ausente)
    """

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {
            # defaults plausiveis - testes especificos sobrescrevem com .set()
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
        """Helper pra teste sobrescrever um secret."""
        if value is None:
            self._secrets.pop(name, None)
        else:
            self._secrets[name] = value


@pytest.fixture
def mock_settings(mocker) -> FakeSettings:
    """Settings mockado retornando dict in-memory.

    NOTA: Patcha Settings ANTES de qualquer import de modulo do projeto que
    instancia Settings() no escopo do modulo. Por isso fixtures dependentes
    de mock_settings devem importar o modulo DENTRO do corpo do teste, nao
    no topo do arquivo.
    """
    fake = FakeSettings()
    mocker.patch("app.core.config.Settings", return_value=fake)
    return fake


# ---------------------------------------------------------------------------
# DatabaseManager (mock SQL)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db(mocker):
    """DatabaseManager mockado.

    Por default:
    - execute_read_one retorna None (sem linha)
    - execute_write retorna True (sucesso)
    - execute_transaction retorna True

    Override em teste especifico:
        mock_db.execute_read_one.return_value = ("uuid-fake", "Nome Fake")
        mock_db.execute_read_one.side_effect = [linha1, linha2, None]  # multiplas
    """
    db = MagicMock(name="DatabaseManager")
    db.execute_read_one.return_value = None
    db.execute_write.return_value = True
    db.execute_transaction.return_value = True
    mocker.patch("app.core.database.DatabaseManager", return_value=db)
    return db


# ---------------------------------------------------------------------------
# InfobipClient (mock HTTP outbound do Infobip)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_infobip(mocker):
    """InfobipClient mockado.

    send_text / send_image / send_template retornam dict de sucesso fake.
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

    enqueue retorna True. peek/receive_* retornam vazio por default.
    """
    dlq = MagicMock(name="DLQClient")
    dlq.enqueue.return_value = True
    dlq.peek.return_value = []
    dlq.receive_one.return_value = None
    dlq.receive_by_id.return_value = None
    dlq.delete.return_value = True
    mocker.patch("app.integrations.dlq.DLQClient", return_value=dlq)
    return dlq


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------
@pytest.fixture
def client(mock_settings, mock_db, mock_infobip, mock_dlq):
    """TestClient com main.app carregado + todos os mocks de Azure aplicados.

    Importa main DENTRO da fixture pra que os patches acima ja estejam
    ativos no momento que main.py roda seus imports e startup.
    """
    from fastapi.testclient import TestClient
    import importlib
    import main
    importlib.reload(main)
    return TestClient(main.app)
