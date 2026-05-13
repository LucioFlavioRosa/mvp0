"""Testes para verify_admin_basic_auth + endpoints /admin/dlq*.

Cobre:
- Basic Auth happy path
- 401 sem header / credenciais erradas
- 503 fail-safe quando ADMIN-USER ou ADMIN-PASSWORD ausentes no Key Vault
- GET /admin/dlq: peek com fila vazia, com dados, e borda do limit
- POST /admin/dlq/retry/{id}: 404 se mensagem nao existe, 200 + delete obrigatorio
  quando existe

Skill: aplicada do catalogo "Tipo 1 - Endpoint FastAPI com Basic Auth"
em references/test-types.md.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# GET /admin/dlq - happy path + auth
# ---------------------------------------------------------------------------
def test_admin_dlq_list_returns_empty_with_correct_auth(client, mock_dlq):
    mock_dlq.peek.return_value = []

    response = client.get("/admin/dlq", auth=("admin-user", "admin-pass"))

    assert response.status_code == 200
    assert response.json() == {"count": 0, "messages": []}
    mock_dlq.peek.assert_called_once_with(max_messages=32)


def test_admin_dlq_list_returns_messages_with_correct_auth(client, mock_dlq):
    fake_msgs = [
        {
            "id": "msg-1",
            "content": {"operation": "send_text", "external_service": "infobip"},
            "dequeue_count": 1,
            "inserted_on": "2026-05-13T12:00:00+00:00",
        },
        {
            "id": "msg-2",
            "content": {"operation": "download_media"},
            "dequeue_count": 1,
            "inserted_on": "2026-05-13T12:01:00+00:00",
        },
    ]
    mock_dlq.peek.return_value = fake_msgs

    response = client.get("/admin/dlq", auth=("admin-user", "admin-pass"))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["messages"] == fake_msgs


# ---------------------------------------------------------------------------
# GET /admin/dlq - 401 (credenciais invalidas)
# ---------------------------------------------------------------------------
def test_admin_dlq_returns_401_without_authorization_header(client):
    response = client.get("/admin/dlq")
    assert response.status_code == 401


def test_admin_dlq_returns_401_with_wrong_user(client):
    response = client.get("/admin/dlq", auth=("user-errado", "admin-pass"))
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


def test_admin_dlq_returns_401_with_wrong_password(client):
    response = client.get("/admin/dlq", auth=("admin-user", "senha-errada"))
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


# ---------------------------------------------------------------------------
# GET /admin/dlq - 503 (fail-safe: secrets ausentes)
# ---------------------------------------------------------------------------
def test_admin_dlq_returns_503_when_admin_user_missing(client, mock_settings):
    mock_settings.set("ADMIN-USER", None)

    response = client.get("/admin/dlq", auth=("qualquer", "coisa"))

    assert response.status_code == 503
    assert response.json()["detail"] == "admin auth not configured"


def test_admin_dlq_returns_503_when_admin_password_missing(client, mock_settings):
    mock_settings.set("ADMIN-PASSWORD", None)

    response = client.get("/admin/dlq", auth=("admin-user", "qualquer"))

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /admin/dlq - borda do limit (clampa entre 1 e 32)
# ---------------------------------------------------------------------------
def test_admin_dlq_clamps_limit_above_32(client, mock_dlq):
    """limit=100 vira 32 (max da Storage Queue)."""
    mock_dlq.peek.return_value = []

    response = client.get(
        "/admin/dlq?limit=100",
        auth=("admin-user", "admin-pass"),
    )

    assert response.status_code == 200
    mock_dlq.peek.assert_called_once_with(max_messages=32)


def test_admin_dlq_clamps_limit_below_1(client, mock_dlq):
    """limit=0 vira 1 (min)."""
    mock_dlq.peek.return_value = []

    response = client.get(
        "/admin/dlq?limit=0",
        auth=("admin-user", "admin-pass"),
    )

    assert response.status_code == 200
    mock_dlq.peek.assert_called_once_with(max_messages=1)


# ---------------------------------------------------------------------------
# POST /admin/dlq/retry/{id} - 404 quando mensagem nao existe
# ---------------------------------------------------------------------------
def test_admin_dlq_retry_returns_404_when_message_not_found(client, mock_dlq):
    mock_dlq.receive_by_id.return_value = None

    response = client.post(
        "/admin/dlq/retry/msg-fantasma",
        auth=("admin-user", "admin-pass"),
    )

    assert response.status_code == 404
    # Politica: nao deleta o que nao recebeu - delete soh acontece pos-receive
    mock_dlq.delete.assert_not_called()


# ---------------------------------------------------------------------------
# POST /admin/dlq/retry/{id} - happy path + delete obrigatorio
# ---------------------------------------------------------------------------
def test_admin_dlq_retry_calls_delete_after_retry_succeeds(client, mock_dlq):
    """Politica: delete eh OBRIGATORIO apos retry, mesmo se retry falhar."""
    mock_dlq.receive_by_id.return_value = {
        "id": "msg-1",
        "pop_receipt": "receipt-abc",
        "content": {
            "operation": "operation_invalida",  # forca retry a falhar
            "external_service": "infobip",
            "payload": {},
            "attempts": 2,
            "last_error": "Timeout",
        },
        "dequeue_count": 1,
    }
    mock_dlq.delete.return_value = True

    response = client.post(
        "/admin/dlq/retry/msg-1",
        auth=("admin-user", "admin-pass"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message_id"] == "msg-1"
    assert body["deleted"] is True
    # Confirma a politica de delete obrigatorio
    mock_dlq.delete.assert_called_once_with("msg-1", "receipt-abc")


def test_admin_dlq_retry_returns_401_without_auth(client):
    response = client.post("/admin/dlq/retry/msg-1")
    assert response.status_code == 401
