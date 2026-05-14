"""Testes para SequenceQueueClient (wrapper de Azure Storage Queue para
entrega assincrona de sequencias de mensagens WhatsApp).

Patcha Settings DENTRO de sequence_queue (onde eh USADO) e nao na origem,
porque o `from app.core.config import Settings` no topo do modulo cria
binding local que nao acompanha mocker.patch em app.core.config.Settings.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_settings(mocker):
    """FakeSettings patchado direto em sequence_queue.Settings."""
    fake = MagicMock(name="FakeSettings")
    fake.get_secret.return_value = (
        "DefaultEndpointsProtocol=https;AccountName=fake;AccountKey=fake==;"
        "EndpointSuffix=core.windows.net"
    )
    mocker.patch("app.integrations.sequence_queue.Settings", return_value=fake)
    return fake


@pytest.fixture
def queue_client_mock(mocker):
    """Mock do QueueClient.from_connection_string. Retorna o instance mock."""
    qc_instance = MagicMock(name="QueueClient")
    mocker.patch(
        "app.integrations.sequence_queue.QueueClient.from_connection_string",
        return_value=qc_instance,
    )
    return qc_instance


@pytest.fixture
def sq_client(fake_settings, queue_client_mock):
    """SequenceQueueClient instanciado com tudo mockado."""
    from app.integrations.sequence_queue import SequenceQueueClient
    return SequenceQueueClient()


# ===========================================================================
# Inicializacao
# ===========================================================================
def test_init_sem_connection_string_deixa_queue_none(fake_settings, mocker):
    """Sem CONNECTION-STRING-AZURE-STORAGE no Key Vault, queue=None
    (fail-safe: nao quebra import, mas enqueue retorna False)."""
    fake_settings.get_secret.return_value = None
    mocker.patch("app.integrations.sequence_queue.QueueClient.from_connection_string")

    from app.integrations.sequence_queue import SequenceQueueClient
    client = SequenceQueueClient()

    assert client.queue is None


def test_init_cria_queue_idempotente(sq_client, queue_client_mock):
    """No __init__, chama create_queue() pra garantir que existe.
    Operacao eh idempotente no Azure - se ja existe, nao falha."""
    queue_client_mock.create_queue.assert_called_once()


# ===========================================================================
# enqueue
# ===========================================================================
def test_enqueue_serializa_sender_e_sequence_como_json(sq_client, queue_client_mock):
    """enqueue passa dict {sender_id, sequence} serializado pra send_message."""
    sequence = [{"tipo": "texto", "conteudo": "oi", "delay": 1}]

    ok = sq_client.enqueue("5511999998888", sequence)

    assert ok is True
    queue_client_mock.send_message.assert_called_once()
    payload_str = queue_client_mock.send_message.call_args.args[0]
    payload = json.loads(payload_str)
    assert payload["sender_id"] == "5511999998888"
    assert payload["sequence"] == sequence


def test_enqueue_retorna_false_quando_queue_indisponivel(fake_settings, mocker):
    """Se queue=None (connection string ausente), enqueue retorna False
    sem levantar excecao."""
    fake_settings.get_secret.return_value = None
    mocker.patch("app.integrations.sequence_queue.QueueClient.from_connection_string")

    from app.integrations.sequence_queue import SequenceQueueClient
    client = SequenceQueueClient()

    ok = client.enqueue("5511", [{"tipo": "texto"}])

    assert ok is False


def test_enqueue_retorna_false_quando_send_message_falha(sq_client, queue_client_mock):
    """send_message levantando excecao (ex: 503 do Storage Queue) eh
    capturado, logado CRITICAL e retorna False - nao propaga pro caller."""
    queue_client_mock.send_message.side_effect = Exception("storage indisponivel")

    ok = sq_client.enqueue("5511", [{"tipo": "texto"}])

    assert ok is False


# ===========================================================================
# receive_one
# ===========================================================================
def test_receive_one_retorna_none_quando_queue_vazia(sq_client, queue_client_mock):
    """receive_messages devolvendo iterador vazio -> receive_one retorna None."""
    pages_mock = MagicMock()
    pages_mock.by_page.return_value = iter([[]])
    queue_client_mock.receive_messages.return_value = pages_mock

    result = sq_client.receive_one()

    assert result is None


def test_receive_one_devolve_dict_com_id_pop_receipt_content(sq_client, queue_client_mock):
    """Quando ha mensagem, retorna dict com keys necessarias pra
    sequence_worker processar e deletar depois."""
    msg = MagicMock()
    msg.id = "msg-id-123"
    msg.pop_receipt = "pop-receipt-abc"
    msg.content = json.dumps({"sender_id": "5511", "sequence": [{"tipo": "texto"}]})
    msg.dequeue_count = 1
    pages_mock = MagicMock()
    pages_mock.by_page.return_value = iter([[msg]])
    queue_client_mock.receive_messages.return_value = pages_mock

    result = sq_client.receive_one()

    assert result is not None
    assert result["id"] == "msg-id-123"
    assert result["pop_receipt"] == "pop-receipt-abc"
    assert result["content"]["sender_id"] == "5511"
    assert result["dequeue_count"] == 1


# ===========================================================================
# delete
# ===========================================================================
def test_delete_chama_queue_delete_com_id_e_pop_receipt(sq_client, queue_client_mock):
    """delete passa id+pop_receipt pra Storage Queue."""
    ok = sq_client.delete("msg-id", "pop-r")

    assert ok is True
    queue_client_mock.delete_message.assert_called_once_with("msg-id", "pop-r")


def test_delete_retorna_false_em_erro(sq_client, queue_client_mock):
    """delete falhando (pop receipt invalido, msg ja deletada) retorna
    False mas nao levanta."""
    queue_client_mock.delete_message.side_effect = Exception("pop receipt expirado")

    ok = sq_client.delete("msg-id", "pop-r")

    assert ok is False
