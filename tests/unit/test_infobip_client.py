"""Testes para InfobipClient: contrato + retry transient + DLQ enqueue.

Importante: este arquivo NAO usa a fixture mock_infobip (que mocka a CLASSE
InfobipClient). Aqui queremos a classe REAL para testar a logica de retry
e DLQ enqueue. requests-mock intercepta o HTTP no nivel da URL.

Politica testada (alinhada com app/core/retry.py + app/integrations/infobip.py):
- @transient_retry tenta 2x em timeout/connection/5xx; nao retenta 4xx
- Apos retry esgotar, _dispatch enfileira DLQMessage(attempts=2) antes de re-levantar
- 4xx enfileira tambem (attempts=2 pq vai pelo mesmo caminho de exception)

Skill: aplicada do catalogo "Tipo 2 - Cliente HTTP de servico externo".
"""

from __future__ import annotations

import pytest
import requests


# Mocka time.sleep para retry nao esperar 1-5s entre tentativas em teste.
# Aplicado a todos os testes deste arquivo via autouse.
@pytest.fixture(autouse=True)
def no_sleep(mocker):
    mocker.patch("time.sleep")
    mocker.patch("tenacity.nap.time.sleep", create=True)


@pytest.fixture
def infobip_client(mock_dlq):
    """InfobipClient REAL com DLQ mockado.

    base_url alinhada com FakeSettings em conftest para os requests_mock
    matchers funcionarem.
    """
    from app.integrations.infobip import InfobipClient
    return InfobipClient(
        api_key="fake-infobip-key",
        base_url="https://fake.api.infobip.com",
        timeout=1.0,
        dlq=mock_dlq,
    )


# ---------------------------------------------------------------------------
# Happy path - send_text / send_template
# ---------------------------------------------------------------------------
def test_send_text_returns_parsed_response_on_200(infobip_client, requests_mock):
    expected_response = {"messages": [{"status": {"groupName": "PENDING"}}]}
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        json=expected_response,
        status_code=200,
    )

    result = infobip_client.send_text(sender="5511", to="5522", text="oi")

    assert result == expected_response
    assert requests_mock.call_count == 1
    # Authorization header presente
    assert requests_mock.last_request.headers["Authorization"] == "App fake-infobip-key"


def test_send_template_sends_positional_placeholders(infobip_client, requests_mock):
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/template",
        json={"messages": []},
        status_code=200,
    )

    infobip_client.send_template(
        sender="5511",
        to="5522",
        template_name="oferta_servico",
        language="pt_BR",
        placeholders=["Joao", "Encanador", "100"],
    )

    body = requests_mock.last_request.json()
    msg = body["messages"][0]
    assert msg["content"]["templateName"] == "oferta_servico"
    assert msg["content"]["language"] == "pt_BR"
    assert msg["content"]["templateData"]["body"]["placeholders"] == ["Joao", "Encanador", "100"]


# ---------------------------------------------------------------------------
# 4xx - NAO retenta, mas enfileira na DLQ
# ---------------------------------------------------------------------------
def test_4xx_does_not_retry_and_enqueues_dlq(infobip_client, requests_mock, mock_dlq):
    """HTTP 400 = request invalida -> nao adianta retry. Mas enfileira DLQ
    pra visibilidade humana (ex: template_name nao cadastrado no portal)."""
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        status_code=400,
        json={"error": "bad request"},
    )

    with pytest.raises(requests.HTTPError):
        infobip_client.send_text(sender="5511", to="5522", text="oi")

    # Confirma que NAO retentou
    assert requests_mock.call_count == 1
    # Confirma que enfileirou na DLQ
    mock_dlq.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# 5xx transient - retry funciona, retorna sucesso, NAO enfileira
# ---------------------------------------------------------------------------
def test_5xx_then_200_retries_and_succeeds(infobip_client, requests_mock, mock_dlq):
    """1a tentativa: 500. 2a: 200. Resultado: sucesso, sem enqueue."""
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        [
            {"status_code": 500, "json": {"error": "transient"}},
            {"status_code": 200, "json": {"messages": [{"status": "OK"}]}},
        ],
    )

    result = infobip_client.send_text(sender="5511", to="5522", text="oi")

    assert result == {"messages": [{"status": "OK"}]}
    assert requests_mock.call_count == 2
    mock_dlq.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 5xx persistente - retry esgota, levanta + enfileira DLQ
# ---------------------------------------------------------------------------
def test_5xx_persistent_exhausts_retry_and_enqueues_dlq(infobip_client, requests_mock, mock_dlq):
    """500 nas duas tentativas -> levanta HTTPError, DLQ recebe DLQMessage."""
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        status_code=500,
        json={"error": "persistent"},
    )

    with pytest.raises(requests.HTTPError):
        infobip_client.send_text(sender="5511", to="5522", text="oi")

    assert requests_mock.call_count == 2  # 2 tentativas via @transient_retry
    mock_dlq.enqueue.assert_called_once()

    # Valida contrato do DLQMessage enfileirado
    dlq_msg = mock_dlq.enqueue.call_args.args[0]
    assert dlq_msg.operation == "send_text"
    assert dlq_msg.external_service == "infobip"
    assert dlq_msg.attempts == 2
    assert "HTTPError" in dlq_msg.last_error
    assert dlq_msg.payload["path"] == "/whatsapp/1/message/text"
    assert dlq_msg.payload["sender"] == "5511"
    assert dlq_msg.payload["to"] == "5522"
    # sender_hash deve ser hash determinstico do destinatario (mask_pii)
    assert dlq_msg.sender_hash is not None
    assert len(dlq_msg.sender_hash) == 12


# ---------------------------------------------------------------------------
# Timeout - retry transient
# ---------------------------------------------------------------------------
def test_timeout_retries_and_enqueues_on_persistence(infobip_client, requests_mock, mock_dlq):
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        exc=requests.Timeout("timeout"),
    )

    with pytest.raises(requests.Timeout):
        infobip_client.send_text(sender="5511", to="5522", text="oi")

    assert requests_mock.call_count == 2
    mock_dlq.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# ConnectionError - retry transient
# ---------------------------------------------------------------------------
def test_connection_error_retries_and_enqueues_on_persistence(infobip_client, requests_mock, mock_dlq):
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        exc=requests.ConnectionError("network down"),
    )

    with pytest.raises(requests.ConnectionError):
        infobip_client.send_text(sender="5511", to="5522", text="oi")

    assert requests_mock.call_count == 2
    mock_dlq.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# DLQ contract - payload reconstruivel pelo admin retry
# ---------------------------------------------------------------------------
def test_dlq_message_payload_is_complete_for_admin_retry(infobip_client, requests_mock, mock_dlq):
    """O payload enfileirado deve permitir admin reconstruir e re-executar a
    chamada original. Caso contrario o endpoint /admin/dlq/retry nao funciona."""
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/template",
        status_code=500,
    )

    with pytest.raises(requests.HTTPError):
        infobip_client.send_template(
            sender="5511",
            to="5522",
            template_name="oferta_servico",
            language="pt_BR",
            placeholders=["Joao", "Encanador"],
        )

    dlq_msg = mock_dlq.enqueue.call_args.args[0]
    assert dlq_msg.operation == "send_template"
    # Payload precisa ter path + body completos para _executar_retry_dlq reconstruir
    assert dlq_msg.payload["path"] == "/whatsapp/1/message/template"
    body = dlq_msg.payload["body"]
    assert body["messages"][0]["content"]["templateName"] == "oferta_servico"
    assert body["messages"][0]["content"]["templateData"]["body"]["placeholders"] == ["Joao", "Encanador"]
