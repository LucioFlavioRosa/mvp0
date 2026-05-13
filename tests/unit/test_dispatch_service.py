"""Testes para DispatchService.enviar_oferta_para_prestadores.

Foco: o caminho que foi truncado uma vez (fix/restore-dispatch-send).

NOTA TECNICA: dispatch_service.py faz `from app.core.database import
DatabaseManager` e `from app.services.whatsapp_service import WhatsAppService`
no topo. Isso copia as referencias pro namespace local no primeiro import,
quebrando patches normais. Estrategia: substituir self.db e self.whatsapp
DIRETAMENTE na instancia apos criada. Robusto a refactors, sem reload.

Skill: aplicada do catalogo "Tipo 3 - Service com DB + chamada externa".
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest


# Tupla padrao retornada pelo SELECT do pedido em PEDIDOS_SERVICO.
# Ordem das colunas:
#   Atividade, Rua, Numero, Bairro, DataLimite, Observacao, Valor, Urgencia
PEDIDO_ROW = (
    "Encanador",
    "Rua das Flores",
    "100",
    "Centro",
    datetime(2026, 5, 15, 14, 0, 0),
    "Vazamento na cozinha",
    150.0,
    "Normal",
)


@pytest.fixture
def dispatch_service(mock_settings):
    """Cria DispatchService com self.db e self.whatsapp substituidos por mocks.

    Estrategia: usar __new__ pra evitar __init__ real (que tentaria criar
    DatabaseManager e WhatsAppService reais e pode disparar threads).
    """
    from app.services.dispatch_service import DispatchService
    service = DispatchService.__new__(DispatchService)
    service.db = MagicMock(name="db")
    service.db.execute_read_one.return_value = None
    service.db.execute_write.return_value = True
    service.whatsapp = MagicMock(name="whatsapp")
    service.TEMPLATE_OFERTA = "oferta_servico"
    return service


# ---------------------------------------------------------------------------
# Happy path - 2 parceiros validos
# ---------------------------------------------------------------------------
def test_dispatch_envia_template_para_dois_parceiros_validos(dispatch_service):
    dispatch_service.db.execute_read_one.side_effect = [
        PEDIDO_ROW,
        ("5511111", "Joao Silva"),
        ("5522222", "Maria Souza"),
    ]
    dispatch_service.db.execute_write.return_value = True

    result = dispatch_service.enviar_oferta_para_prestadores(
        lista_uuids=["uuid-1", "uuid-2"],
        pedido_uuid="pedido-X",
    )

    assert result == {"status": "success", "enviados": 2}
    assert dispatch_service.whatsapp.enviar_resposta.call_count == 2


# ---------------------------------------------------------------------------
# Pedido inexistente - retorna erro, nada enviado
# ---------------------------------------------------------------------------
def test_dispatch_retorna_erro_quando_pedido_nao_existe(dispatch_service):
    dispatch_service.db.execute_read_one.return_value = None

    result = dispatch_service.enviar_oferta_para_prestadores(
        lista_uuids=["uuid-1", "uuid-2"],
        pedido_uuid="pedido-fantasma",
    )

    assert result["status"] == "error"
    assert "pedido-fantasma" in result["message"]
    dispatch_service.whatsapp.enviar_resposta.assert_not_called()


# ---------------------------------------------------------------------------
# Parceiro UUID nao encontrado - pula, continua outros
# ---------------------------------------------------------------------------
def test_dispatch_pula_parceiro_inexistente_e_continua(dispatch_service):
    """Parceiro 1 nao existe (None), parceiro 2 existe.
    Resultado: 1 envio, sem propagar erro."""
    dispatch_service.db.execute_read_one.side_effect = [
        PEDIDO_ROW,
        None,                        # parceiro 1: nao encontrado
        ("5522222", "Maria Souza"),  # parceiro 2: OK
    ]
    dispatch_service.db.execute_write.return_value = True

    result = dispatch_service.enviar_oferta_para_prestadores(
        lista_uuids=["uuid-1", "uuid-2"],
        pedido_uuid="pedido-X",
    )

    assert result == {"status": "success", "enviados": 1}
    assert dispatch_service.whatsapp.enviar_resposta.call_count == 1


# ---------------------------------------------------------------------------
# INSERT em PEDIDOS_DISPAROS falha - pula envio desse parceiro
# ---------------------------------------------------------------------------
def test_dispatch_pula_envio_quando_insert_disparos_falha(dispatch_service):
    dispatch_service.db.execute_read_one.side_effect = [
        PEDIDO_ROW,
        ("5511111", "Joao Silva"),
    ]
    dispatch_service.db.execute_write.return_value = False  # INSERT falha

    result = dispatch_service.enviar_oferta_para_prestadores(
        lista_uuids=["uuid-1"],
        pedido_uuid="pedido-X",
    )

    assert result == {"status": "success", "enviados": 0}
    dispatch_service.whatsapp.enviar_resposta.assert_not_called()


# ---------------------------------------------------------------------------
# Placeholders na ordem correta - contrato do template oferta_servico
# ---------------------------------------------------------------------------
def test_dispatch_envia_placeholders_na_ordem_correta_do_template(dispatch_service):
    """Template 'oferta_servico' espera 9 placeholders posicionais:
    [primeiro_nome, atividade, numero, rua, bairro, data, observacao, valor, urgencia]

    Se a ordem mudar, parceiro recebe campos trocados. Este teste eh a
    defesa contra refactor que troca a ordem.
    """
    dispatch_service.db.execute_read_one.side_effect = [
        PEDIDO_ROW,
        ("5511111", "Joao Silva Santos"),
    ]
    dispatch_service.db.execute_write.return_value = True

    dispatch_service.enviar_oferta_para_prestadores(
        lista_uuids=["uuid-1"],
        pedido_uuid="pedido-X",
    )

    call_args = dispatch_service.whatsapp.enviar_resposta.call_args
    whatsapp_id, msg_template = call_args.args

    assert whatsapp_id == "5511111"
    assert msg_template["tipo"] == "template"
    assert msg_template["template_name"] == "oferta_servico"

    placeholders = msg_template["placeholders"]
    assert len(placeholders) == 9
    assert placeholders[0] == "Joao"                # primeiro_nome
    assert placeholders[1] == "Encanador"           # atividade
    assert placeholders[2] == "100"                 # numero (str)
    assert placeholders[3] == "Rua das Flores"      # rua
    assert placeholders[4] == "Centro"              # bairro
    assert placeholders[5] == "15/05/2026"          # data dd/mm/yyyy
    assert placeholders[6] == "Vazamento na cozinha"  # observacao
    assert placeholders[7] == "150,00"              # valor formatado
    assert placeholders[8] == "Normal"              # urgencia
