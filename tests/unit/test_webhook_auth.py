"""Testes para verify_infobip_basic_auth + POST /bot.

Cobre o checkpoint de seguranca do webhook inbound do Infobip.

Politica:
- Auth correta: 200 + processa payload
- Credenciais erradas: 401
- Secrets INFOBIP-WEBHOOK-USER ou INFOBIP-WEBHOOK-PASSWORD ausentes: 503
  (fail-safe - sem auth configurada == sem servico)
- Payload mal formado: 422 (Pydantic)

Skill: aplicada do catalogo "Tipo 1 - Endpoint FastAPI com Basic Auth".
"""

from __future__ import annotations


# Payload minimo valido para POST /bot. Usado em testes de auth onde
# o payload em si nao eh o ponto - so precisa passar pelo Pydantic.
VALID_PAYLOAD_EMPTY: dict = {"results": [], "messageCount": 0}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_bot_webhook_returns_200_with_correct_auth_and_empty_results(client):
    """Auth correta + payload sem mensagens -> 200 {"status": "ok"}.

    Confirma que o webhook responde rapido quando nao ha o que processar.
    """
    response = client.post(
        "/bot",
        json=VALID_PAYLOAD_EMPTY,
        auth=("webhook-user", "webhook-pass"),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 401 - credenciais erradas ou ausentes
# ---------------------------------------------------------------------------
def test_bot_webhook_returns_401_without_authorization_header(client):
    response = client.post("/bot", json=VALID_PAYLOAD_EMPTY)
    assert response.status_code == 401


def test_bot_webhook_returns_401_with_wrong_user(client):
    response = client.post(
        "/bot",
        json=VALID_PAYLOAD_EMPTY,
        auth=("user-errado", "webhook-pass"),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


def test_bot_webhook_returns_401_with_wrong_password(client):
    response = client.post(
        "/bot",
        json=VALID_PAYLOAD_EMPTY,
        auth=("webhook-user", "senha-errada"),
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 503 - fail-safe quando secrets ausentes
# ---------------------------------------------------------------------------
def test_bot_webhook_returns_503_when_webhook_user_missing(client, mock_settings):
    """Sem INFOBIP-WEBHOOK-USER no Key Vault, app NAO aceita webhook."""
    mock_settings.set("INFOBIP-WEBHOOK-USER", None)

    response = client.post(
        "/bot",
        json=VALID_PAYLOAD_EMPTY,
        auth=("qualquer", "coisa"),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "webhook auth not configured"


def test_bot_webhook_returns_503_when_webhook_password_missing(client, mock_settings):
    mock_settings.set("INFOBIP-WEBHOOK-PASSWORD", None)

    response = client.post(
        "/bot",
        json=VALID_PAYLOAD_EMPTY,
        auth=("webhook-user", "qualquer"),
    )

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 422 - validacao Pydantic do payload inbound
# ---------------------------------------------------------------------------
def test_bot_webhook_returns_422_when_payload_missing_results_field(client):
    """Pydantic deve rejeitar payload sem 'results' obrigatorio."""
    invalid_payload = {"messageCount": 0}  # falta 'results'

    response = client.post(
        "/bot",
        json=invalid_payload,
        auth=("webhook-user", "webhook-pass"),
    )

    assert response.status_code == 422
    # Pydantic indica qual campo falhou
    errors = response.json()["detail"]
    assert any("results" in str(e.get("loc", "")) for e in errors)
