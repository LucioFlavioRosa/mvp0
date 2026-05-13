"""Testes para schemas Pydantic do projeto.

Cobre apenas o que eh ESPECIFICO do projeto (aliases custom, constraints
semanticos, discriminators). NAO testamos comportamento padrao do Pydantic
(isso eh testado upstream).

Skill: aplicada do catalogo "Tipo 4 - Schema Pydantic".
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


# ===========================================================================
# DLQMessage (app/schemas/dlq.py)
# ===========================================================================

def _dlq_valid_payload() -> dict:
    """Payload minimo valido para DLQMessage. Helper pros testes."""
    return {
        "operation": "send_text",
        "external_service": "infobip",
        "payload": {"to": "5511999", "text": "oi"},
        "sender_hash": "abc123def456",
        "attempts": 2,
        "last_error": "Timeout after 10s",
        "errored_at": datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc),
    }


def test_dlq_message_instancia_com_payload_valido():
    from app.schemas.dlq import DLQMessage

    msg = DLQMessage(**_dlq_valid_payload())

    assert msg.operation == "send_text"
    assert msg.external_service == "infobip"
    assert msg.attempts == 2
    assert msg.sender_hash == "abc123def456"
    assert msg.operation_id is None  # opcional, default None


def test_dlq_message_rejeita_attempts_zero():
    """Constraint ge=1 - DLQMessage so faz sentido se ja tentou ao menos 1x."""
    from app.schemas.dlq import DLQMessage

    payload = _dlq_valid_payload()
    payload["attempts"] = 0

    with pytest.raises(ValidationError) as exc_info:
        DLQMessage(**payload)

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("attempts",) for e in errors)


def test_dlq_message_rejeita_quando_falta_campo_obrigatorio():
    from app.schemas.dlq import DLQMessage

    payload = _dlq_valid_payload()
    del payload["operation"]

    with pytest.raises(ValidationError) as exc_info:
        DLQMessage(**payload)

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("operation",) for e in errors)


def test_dlq_message_aceita_sender_hash_none():
    """download_media nao tem destinatario (eh download de URL), entao
    sender_hash deve ser opcional."""
    from app.schemas.dlq import DLQMessage

    payload = _dlq_valid_payload()
    payload["sender_hash"] = None

    msg = DLQMessage(**payload)
    assert msg.sender_hash is None


def test_dlq_message_serializa_para_json_parseavel():
    """model_dump_json deve produzir JSON valido. Eh o formato que vai
    pra fila Storage Queue - se quebrar, mensagens viram corrompidas."""
    import json
    from app.schemas.dlq import DLQMessage

    msg = DLQMessage(**_dlq_valid_payload())
    serialized = msg.model_dump_json()

    # Volta JSON parseavel
    parsed = json.loads(serialized)
    assert parsed["operation"] == "send_text"
    assert parsed["attempts"] == 2
    assert parsed["payload"] == {"to": "5511999", "text": "oi"}


# ===========================================================================
# InfobipInboundPayload (app/schemas/infobip_webhook.py)
# ===========================================================================

def _infobip_text_payload() -> dict:
    """Payload tipico de webhook inbound do Infobip com mensagem TEXT.

    Note que os campos vem com nomes da API Infobip ('from', 'messageId',
    'receivedAt', 'messageCount') - o schema precisa de aliases pra mapear.
    """
    return {
        "results": [
            {
                "from": "5511999998888",
                "to": "5511777776666",
                "messageId": "msg-abc-123",
                "receivedAt": "2026-05-13T12:00:00Z",
                "message": {"type": "TEXT", "text": "Ola, quero me cadastrar"},
            },
        ],
        "messageCount": 1,
    }


def test_inbound_payload_mapeia_alias_from_para_sender():
    """JSON 'from' -> attr 'sender' (porque 'from' eh keyword em Python)."""
    from app.schemas.infobip_webhook import InfobipInboundPayload

    payload = InfobipInboundPayload(**_infobip_text_payload())

    assert payload.message_count == 1   # alias messageCount -> message_count
    result = payload.results[0]
    assert result.sender == "5511999998888"  # alias from -> sender
    assert result.message_id == "msg-abc-123"  # alias messageId -> message_id


def test_inbound_payload_discriminator_seleciona_text():
    from app.schemas.infobip_webhook import (
        InfobipInboundPayload,
        InfobipMessageText,
    )

    payload = InfobipInboundPayload(**_infobip_text_payload())
    msg = payload.results[0].message

    assert isinstance(msg, InfobipMessageText)
    assert msg.type == "TEXT"
    assert msg.text == "Ola, quero me cadastrar"


def test_inbound_payload_discriminator_seleciona_image():
    """Schema deve escolher InfobipMessageImage quando type='IMAGE'."""
    from app.schemas.infobip_webhook import (
        InfobipInboundPayload,
        InfobipMessageImage,
    )

    payload_dict = _infobip_text_payload()
    payload_dict["results"][0]["message"] = {
        "type": "IMAGE",
        "url": "https://infobip.com/media/cnh.jpg",
        "caption": "Minha CNH",
    }

    payload = InfobipInboundPayload(**payload_dict)
    msg = payload.results[0].message

    assert isinstance(msg, InfobipMessageImage)
    assert msg.type == "IMAGE"
    assert msg.url == "https://infobip.com/media/cnh.jpg"
    assert msg.caption == "Minha CNH"


def test_inbound_payload_rejeita_results_ausente():
    """results eh obrigatorio - se faltar, webhook esta mal formado."""
    from app.schemas.infobip_webhook import InfobipInboundPayload

    with pytest.raises(ValidationError) as exc_info:
        InfobipInboundPayload(messageCount=0)  # falta 'results'

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("results",) for e in errors)
