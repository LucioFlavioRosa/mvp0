"""Testes para DLQClient (app/integrations/dlq.py).

NOTA TECNICA: nao usamos a fixture mock_dlq (que mocka a CLASSE DLQClient).
Aqui queremos o CODIGO REAL do DLQClient para testar a logica de enqueue,
peek, receive_by_id, delete. Mockamos QueueClient (azure-storage-queue) no
nivel de modulo.

Skill: aplicada do catalogo "Tipo 10 - DLQ flow + fail-safe".
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def queue_mock(mocker):
    """Mocka azure.storage.queue.QueueClient para evitar conexao real.

    Os testes injetam comportamento especifico via .return_value / .side_effect.
    """
    queue = MagicMock(name="QueueClient")
    mocker.patch(
        "app.integrations.dlq.QueueClient.from_connection_string",
        return_value=queue,
    )
    return queue


@pytest.fixture
def dlq_client(mock_settings, queue_mock):
    """DLQClient real com QueueClient mockado."""
    from app.integrations.dlq import DLQClient
    return DLQClient()


def _make_dlq_message():
    from app.schemas.dlq import DLQMessage
    return DLQMessage(
        operation="send_text",
        external_service="infobip",
        payload={"to": "5511", "text": "oi"},
        sender_hash="hash123",
        attempts=2,
        last_error="Timeout",
        errored_at=datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# enqueue - happy path
# ---------------------------------------------------------------------------
def test_enqueue_envia_mensagem_serializada_e_retorna_true(dlq_client, queue_mock):
    msg = _make_dlq_message()

    result = dlq_client.enqueue(msg)

    assert result is True
    queue_mock.send_message.assert_called_once()
    # Confirma que enviou JSON serializado da DLQMessage
    sent_payload = queue_mock.send_message.call_args.args[0]
    assert '"operation":"send_text"' in sent_payload
    assert '"attempts":2' in sent_payload


# ---------------------------------------------------------------------------
# enqueue - fail-safe quando Storage Queue indisponivel
# ---------------------------------------------------------------------------
def test_enqueue_eh_fail_safe_quando_queue_indisponivel(dlq_client):
    """Se a queue nao inicializou (conn string ausente OU
    create_queue levantou), enqueue() deve retornar False, NAO levantar
    excecao - caminho normal nao pode quebrar so porque DLQ esta offline.

    Simulamos forcando self.queue=None na instancia (caminho mais robusto
    que mexer em Settings entre testes)."""
    dlq_client.queue = None

    msg = _make_dlq_message()
    result = dlq_client.enqueue(msg)

    assert result is False


def test_enqueue_eh_fail_safe_quando_send_message_levanta(dlq_client, queue_mock):
    """Mesmo se Storage Queue estiver online mas send_message falhar
    (network blip), nao propaga - loga CRITICAL e retorna False."""
    queue_mock.send_message.side_effect = RuntimeError("network blip")

    msg = _make_dlq_message()
    result = dlq_client.enqueue(msg)

    assert result is False  # nao propagou excecao


# ---------------------------------------------------------------------------
# peek
# ---------------------------------------------------------------------------
def test_peek_retorna_lista_vazia_quando_fila_vazia(dlq_client, queue_mock):
    queue_mock.peek_messages.return_value = []

    result = dlq_client.peek(max_messages=10)

    assert result == []


def test_peek_retorna_lista_de_dicts_com_content_parseado(dlq_client, queue_mock):
    """Mensagem na fila esta como JSON string; peek devolve dict ja parseado."""
    fake_msg = MagicMock()
    fake_msg.id = "msg-1"
    fake_msg.content = '{"operation":"send_text","attempts":2}'
    fake_msg.dequeue_count = 1
    fake_msg.inserted_on = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
    queue_mock.peek_messages.return_value = [fake_msg]

    result = dlq_client.peek(max_messages=10)

    assert len(result) == 1
    assert result[0]["id"] == "msg-1"
    assert result[0]["content"]["operation"] == "send_text"  # parsed
    assert result[0]["dequeue_count"] == 1


def test_peek_clampa_max_messages_entre_1_e_32(dlq_client, queue_mock):
    """Storage Queue API max 32 - peek deve clampar pra evitar API error."""
    queue_mock.peek_messages.return_value = []

    dlq_client.peek(max_messages=100)
    queue_mock.peek_messages.assert_called_with(max_messages=32)

    queue_mock.reset_mock()
    dlq_client.peek(max_messages=0)
    queue_mock.peek_messages.assert_called_with(max_messages=1)


# ---------------------------------------------------------------------------
# receive_by_id
# ---------------------------------------------------------------------------
def test_receive_by_id_retorna_none_se_nao_encontrar(dlq_client, queue_mock):
    """Se nenhuma msg na fila tem o ID, retorna None - endpoint admin
    devolve 404 baseado nisso.

    Pos fix `fix/dlq-receive-by-id-pagination`: receive_by_id itera
    `for page in pager: for m in page:` (antes era `.by_page().next()`,
    so a primeira pagina). O mock precisa simular `by_page()` retornando
    um iteravel de paginas, onde cada pagina e iteravel de mensagens.
    """
    fake_msg = MagicMock()
    fake_msg.id = "msg-OUTRO"

    # by_page() retorna iter([page1, page2, ...]); cada pagina e uma lista de msgs
    queue_mock.receive_messages.return_value.by_page.return_value = iter([[fake_msg]])

    result = dlq_client.receive_by_id("msg-PROCURADO")

    assert result is None


def test_receive_by_id_atualiza_pop_receipt_via_update_message(dlq_client, queue_mock):
    """Quando encontra a msg, chama update_message para ESTENDER visibility
    timeout (5 min) e captura o pop_receipt NOVO retornado.

    Bug que ja vimos: se nao capturar o novo pop_receipt, delete() depois
    falha com 'pop receipt mismatch'.

    Pos fix `fix/dlq-receive-by-id-pagination`: o mock simula `by_page()`
    retornando um iteravel de paginas (cada pagina iteravel de msgs),
    em vez de `.by_page().next()` da primeira pagina.
    """
    fake_msg = MagicMock()
    fake_msg.id = "msg-1"
    fake_msg.pop_receipt = "receipt-velho"
    fake_msg.content = '{"operation":"send_text"}'
    fake_msg.dequeue_count = 1

    updated_msg = MagicMock()
    updated_msg.pop_receipt = "receipt-NOVO"  # apos update_message

    queue_mock.receive_messages.return_value.by_page.return_value = iter([[fake_msg]])
    queue_mock.update_message.return_value = updated_msg

    result = dlq_client.receive_by_id("msg-1")

    assert result is not None
    assert result["id"] == "msg-1"
    # CRITICO: pop_receipt eh o NOVO, nao o velho
    assert result["pop_receipt"] == "receipt-NOVO"
    # Confirma que update_message foi chamado para estender visibility timeout
    queue_mock.update_message.assert_called_once()


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------
def test_delete_chama_delete_message_e_retorna_true(dlq_client, queue_mock):
    result = dlq_client.delete("msg-1", "receipt-x")

    assert result is True
    queue_mock.delete_message.assert_called_once_with("msg-1", "receipt-x")


def test_delete_retorna_false_quando_delete_message_levanta(dlq_client, queue_mock):
    """pop receipt mismatch (ex: outro admin processou em paralelo) faz
    delete_message levantar. Logamos error mas nao propagamos - politica
    do projeto eh 'delete obrigatorio' mesmo se falhar (admin investiga)."""
    queue_mock.delete_message.side_effect = RuntimeError("pop receipt mismatch")

    result = dlq_client.delete("msg-1", "receipt-stale")

    assert result is False