"""Sanity tests da infraestrutura de testes.

Estes testes NAO validam logica de negocio. Eles existem para garantir que:
1. O conftest.py carrega sem erro
2. As fixtures principais (client, mock_settings) funcionam
3. main.py eh importavel com os mocks aplicados (TestClient nao explode)

Quando os testes P0 reais forem cobrindo (test/cover-webhook-auth,
test/cover-admin-auth, etc), estes sanity tests podem ser mantidos como
smoke do CI ou removidos. Recomendo manter - sao baratos e pegam
regressao do conftest.
"""

from __future__ import annotations


def test_test_client_loads_without_error(client):
    """Verifica que a fixture client instancia o TestClient sem explodir.

    Indiretamente valida:
    - conftest.py carrega
    - mock_settings, mock_db, mock_infobip, mock_dlq funcionam
    - main.py importa OK com os mocks aplicados
    - configure_telemetry() roda sem APPLICATIONINSIGHTS_CONNECTION_STRING
    """
    assert client is not None


def test_health_check_endpoint_returns_200(client):
    """GET / retorna 200 + payload de health.

    Confere que main.app roda e responde no endpoint mais simples - sem
    auth, sem DB, sem chamada externa.
    """
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "online", "environment": "Azure Production"}


def test_mock_settings_returns_defaults_and_accepts_overrides(mock_settings):
    """FakeSettings devolve defaults e aceita .set() para sobrescrever.

    Este eh o contrato que os testes reais vao usar. Se quebrar, todos
    os testes que dependem de mock_settings quebram.
    """
    # Defaults conhecidos do conftest
    assert mock_settings.get_secret("INFOBIP-API-KEY") == "fake-infobip-key"
    assert mock_settings.get_secret("ADMIN-USER") == "admin-user"
    assert mock_settings.get_secret("ADMIN-PASSWORD") == "admin-pass"

    # Secret nao existente retorna None
    assert mock_settings.get_secret("NAO-EXISTE") is None

    # Override funciona
    mock_settings.set("ADMIN-USER", "outro-user")
    assert mock_settings.get_secret("ADMIN-USER") == "outro-user"

    # Remover (passa None) funciona
    mock_settings.set("ADMIN-USER", None)
    assert mock_settings.get_secret("ADMIN-USER") is None
