"""Testes para auth Azure AD do /api/dispatch.

Estrategia de mock:
- verify_dispatch_auth (app.api.deps) eh sobrescrito via
  app.dependency_overrides para retornar um user fake com claims.
- dispatch_service (app.state.dispatch_service) eh sobrescrito via
  app.dependency_overrides[get_dispatch_service] = lambda: mock.
  Isso eh o padrao idiomatico FastAPI - desacopla do app.state durante
  os testes.
- Para 503: forcamos app.api.deps._azure_scheme_instance=None (patch direto
  no modulo onde verify_dispatch_auth realmente le).

Skill: aplicada do catalogo "Tipo 1 - Endpoint FastAPI com Bearer Auth".
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Imports diretos das fontes reais (sem dependencia de re-exports em main.py)
from app.api.deps import get_dispatch_service, verify_dispatch_auth
from app.api import dispatch as dispatch_module


@pytest.fixture
def fake_user():
    """Usuario fake do Azure AD com claims plausiveis."""
    user = MagicMock(name="AzureUser")
    user.claims = {
        "oid": "12345678-1234-1234-1234-123456789abc",
        "preferred_username": "operador@aegea.com.br",
        "name": "Joao Operador",
        "scp": "dispatch.write",
    }
    return user


@pytest.fixture
def override_auth(fake_user):
    """Factory: retorna funcao async que devolve o fake_user, pra usar como
    override de verify_dispatch_auth via app.dependency_overrides."""
    async def _override():
        return fake_user
    return _override


@pytest.fixture
def mock_dispatch_service():
    """Mock do DispatchService injetado via app.dependency_overrides[get_dispatch_service].

    Tests podem customizar .enviar_oferta_para_prestadores.return_value ou
    .side_effect conforme o cenario.
    """
    m = MagicMock(name="DispatchService")
    m.enviar_oferta_para_prestadores.return_value = {"status": "success", "enviados": 1}
    return m


# ---------------------------------------------------------------------------
# 503 quando scheme nao inicializado (secrets ausentes)
# ---------------------------------------------------------------------------
def test_dispatch_returns_503_when_azure_scheme_not_initialized(client, mocker):
    """Se AZURE-AD-TENANT-ID ou AZURE-AD-API-CLIENT-ID ausentes, scheme=None,
    qualquer chamada retorna 503 + log critical.

    O scheme vive em app.core.azure_auth._azure_scheme. verify_dispatch_auth
    le dinamicamente via get_azure_scheme() em cada request, entao patchar
    a fonte aqui basta.
    """
    from app.core import azure_auth
    mocker.patch.object(azure_auth, "_azure_scheme", None)
    mocker.patch.object(azure_auth, "_init_error", "secrets ausentes")

    response = client.post(
        "/api/dispatch",
        json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "dispatch auth not configured"


# ---------------------------------------------------------------------------
# 200 happy path com user mockado
# ---------------------------------------------------------------------------
def test_dispatch_returns_200_with_valid_token_and_logs_operator_oid(
    client, override_auth, mock_dispatch_service, mocker,
):
    """Quando override retorna user com claims, endpoint executa e loga oid."""
    import main

    main.app.dependency_overrides[verify_dispatch_auth] = override_auth
    main.app.dependency_overrides[get_dispatch_service] = lambda: mock_dispatch_service

    mock_logger = mocker.patch.object(dispatch_module, "logger")

    try:
        response = client.post(
            "/api/dispatch",
            json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
            headers={"Authorization": "Bearer fake.token.here"},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "success", "enviados": 1}

        info_calls = mock_logger.info.call_args_list
        dispatch_log = next(c for c in info_calls if "dispatch recebido" in c.args[0])
        dims = dispatch_log.kwargs["extra"]["custom_dimensions"]
        assert dims["operator_oid"] == "12345678-1234-1234-1234-123456789abc"
        assert dims["pedido_id"] == "ped-1"
    finally:
        main.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Erro interno no dispatch_service mantem operator_oid no log de erro
# ---------------------------------------------------------------------------
def test_dispatch_logs_operator_oid_em_caso_de_erro(
    client, override_auth, mock_dispatch_service, mocker,
):
    """Se dispatch_service levanta, o log de erro deve incluir oid do operador
    para auditoria - sabemos quem disparou mesmo se falhou."""
    import main

    mock_dispatch_service.enviar_oferta_para_prestadores.side_effect = RuntimeError("DB offline")

    main.app.dependency_overrides[verify_dispatch_auth] = override_auth
    main.app.dependency_overrides[get_dispatch_service] = lambda: mock_dispatch_service

    mock_logger = mocker.patch.object(dispatch_module, "logger")

    try:
        response = client.post(
            "/api/dispatch",
            json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
            headers={"Authorization": "Bearer fake"},
        )

        assert response.status_code == 200  # endpoint nao propaga (ja era)
        assert response.json()["status"] == "error"

        error_calls = mock_logger.error.call_args_list
        dispatch_err = next(c for c in error_calls if "erro em dispatch" in c.args[0])
        dims = dispatch_err.kwargs["extra"]["custom_dimensions"]
        assert dims["operator_oid"] == "12345678-1234-1234-1234-123456789abc"
    finally:
        main.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Body Pydantic invalido ainda eh 422 (auth nao bypassa validacao)
# ---------------------------------------------------------------------------
def test_dispatch_returns_422_quando_payload_invalido_mesmo_com_token(
    client, override_auth,
):
    """Mesmo com token valido, payload sem 'pedido_uuid' eh rejeitado por
    Pydantic antes do endpoint executar."""
    import main

    main.app.dependency_overrides[verify_dispatch_auth] = override_auth

    try:
        response = client.post(
            "/api/dispatch",
            json={"parceiros": ["uuid-1"]},  # falta pedido_uuid
            headers={"Authorization": "Bearer fake"},
        )

        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("pedido_uuid" in str(e.get("loc", "")) for e in errors)
    finally:
        main.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# operator_email mascarado (mask_pii) no log
# ---------------------------------------------------------------------------
def test_dispatch_email_do_operador_eh_mascarado_no_log(
    client, override_auth, mock_dispatch_service, mocker,
):
    """LGPD: email do operador eh PII, deve passar por mask_pii antes do log.
    O log nao pode conter 'operador@aegea.com.br' em claro."""
    import main

    main.app.dependency_overrides[verify_dispatch_auth] = override_auth
    main.app.dependency_overrides[get_dispatch_service] = lambda: mock_dispatch_service

    mock_logger = mocker.patch.object(dispatch_module, "logger")

    try:
        client.post(
            "/api/dispatch",
            json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
            headers={"Authorization": "Bearer fake"},
        )

        info_calls = mock_logger.info.call_args_list
        dispatch_log = next(c for c in info_calls if "dispatch recebido" in c.args[0])
        dims = dispatch_log.kwargs["extra"]["custom_dimensions"]

        assert "sender_hash" in dims
        assert "operador@aegea.com.br" not in str(dims)
    finally:
        main.app.dependency_overrides.clear()
