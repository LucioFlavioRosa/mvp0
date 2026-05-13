"""Testes para utilitarios de telemetria.

Foco:
- mask_pii: determinismo (mesma chave -> mesmo hash); sensibilidade ao salt;
  tratamento de None/empty; truncamento.
- get_logger: retorna logger nomeado.
- get_operation_id: retorna o contextvar (default vazio fora de request).

LGPD/seguranca dependem desses utils. Se mask_pii vira nao-deterministico,
correlacao em App Insights quebra. Se determinismo vaza em fixacao do salt,
hashs viram identificaveis - rotacao de salt e que dah a defesa.

Skill: aplicada do catalogo "Tipo 6 - Funcao pura / utilitario".
"""

from __future__ import annotations

import logging


# ---------------------------------------------------------------------------
# mask_pii - determinismo
# ---------------------------------------------------------------------------
def test_mask_pii_eh_deterministico():
    """Mesmo input + mesmo salt sempre produz mesmo hash.

    Eh esse determinismo que permite agrupar logs do mesmo usuario sem
    expor o identificador. Se quebrar, queries Kusto deixam de correlacionar.
    """
    from app.core.telemetry import mask_pii

    hash_1 = mask_pii("5511999998888")
    hash_2 = mask_pii("5511999998888")

    assert hash_1 == hash_2


def test_mask_pii_retorna_12_chars_hex_por_default():
    from app.core.telemetry import mask_pii

    result = mask_pii("5511999998888")

    assert len(result) == 12
    # hex (so 0-9, a-f)
    assert all(c in "0123456789abcdef" for c in result)


def test_mask_pii_inputs_diferentes_geram_hashs_diferentes():
    """Sanity: hashes nao colidem para inputs comuns.

    Se colidir aqui, indica problema de salt fraco ou algo errado no
    algoritmo - cobre erros de regressao tipo 'salt foi pra constante vazia'.
    """
    from app.core.telemetry import mask_pii

    h1 = mask_pii("5511999998888")
    h2 = mask_pii("5511999998889")  # diferenca em 1 digito
    h3 = mask_pii("user@example.com")

    assert h1 != h2
    assert h1 != h3
    assert h2 != h3


def test_mask_pii_trata_none_e_vazio_como_empty():
    """Documentacao diz: None ou '' viram '<empty>' (nao hash) - permite
    distinguir 'sem PII' de 'hash de PII vazia' em queries Kusto."""
    from app.core.telemetry import mask_pii

    assert mask_pii(None) == "<empty>"
    assert mask_pii("") == "<empty>"


def test_mask_pii_muda_quando_salt_muda(monkeypatch, mocker):
    """Rotacao do LOG_PII_SALT eh a estrategia de invalidacao de hashs
    historicos em caso de vazamento. Confirma que mudar o salt produz
    hashs diferentes para o mesmo input.

    NOTA: telemetry._PII_SALT eh modulo-level, lido no import. Para mudar
    em teste, precisamos reload do modulo.
    """
    import importlib
    from app.core import telemetry

    # Hash com salt original (default do conftest: test-salt-fixed)
    hash_original = telemetry.mask_pii("5511999998888")

    # Trocar o salt e re-importar o modulo
    monkeypatch.setenv("LOG_PII_SALT", "novo-salt-rotacionado")
    importlib.reload(telemetry)

    hash_novo = telemetry.mask_pii("5511999998888")

    assert hash_original != hash_novo


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------
def test_get_logger_retorna_logger_com_nome_correto():
    from app.core.telemetry import get_logger

    logger = get_logger("app.services.test_module")

    assert isinstance(logger, logging.Logger)
    assert logger.name == "app.services.test_module"


def test_get_logger_chamadas_repetidas_retornam_mesma_instancia():
    """Pythoun logging.getLogger eh cached por nome - garantia importante
    pra que filters/handlers configurados no startup persistam."""
    from app.core.telemetry import get_logger

    l1 = get_logger("app.services.test_X")
    l2 = get_logger("app.services.test_X")

    assert l1 is l2


# ---------------------------------------------------------------------------
# get_operation_id
# ---------------------------------------------------------------------------
def test_get_operation_id_retorna_string_fora_de_request():
    """Fora de uma request HTTP (sem middleware setado), retorna o default
    do ContextVar (string vazia)."""
    from app.core.telemetry import get_operation_id

    result = get_operation_id()

    assert isinstance(result, str)
