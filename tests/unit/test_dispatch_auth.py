"""Testes para auth Azure AD do /api/dispatch.

Como mocar fastapi-azure-auth corretamente:
- A funcao verify_dispatch_auth em main.py eh assincrona; precisamos sobrescrever
  ela com dependency_overrides do FastAPI antes de chamar o endpoint
- Para testar 401: nao registramos override -> _azure_scheme_instance eh None ->
  cai no branch 503 (sem scheme configurado)
- Para testar 503: forcamos _azure_scheme_instance=None
- Para testar 200: registramos override que retorna um user fake com claims

Skill: aplicada do catalogo "Tipo 1 - Endpoint FastAPI com Basic Auth"
(adaptado para JWT bearer).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


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


# ---------------------------------------------------------------------------
# 503 quando scheme nao inicializado (secrets ausentes)
# ---------------------------------------------------------------------------
def test_dispatch_returns_503_when_azure_scheme_not_initialized(client, mocker):
    """Se AZURE-AD-TENANT-ID ou AZURE-AD-API-CLIENT-ID ausentes, scheme=None,
    qualquer chamada retorna 503 + log critical."""
    import main
    mocker.patch.object(main, "_azure_scheme_instance", None)
    mocker.patch.object(main, "get_init_error", return_value="secrets ausentes")

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
    client, fake_user, mocker,
):
    """Quando override retorna user com claims, endpoint executa e loga oid."""
    import main

    # Override da dependency com user fake
    async def override_auth():
        return fake_user

    main.app.dependency_overrides[main.verify_dispatch_auth] = override_auth

    # Mock dispatch_service para nao executar logica real
    mocker.patch.object(
        main.dispatch_service,
        "enviar_oferta_para_prestadores",
        return_value={"status": "success", "enviados": 1},
    )
    # Spy no logger pra confirmar auditoria
    mock_logger = mocker.patch.object(main, "logger")

    try:
        response = client.post(
            "/api/dispatch",
            json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
            headers={"Authorization": "Bearer fake.token.here"},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "success", "enviados": 1}

        # Confirma que oid do operador foi logado (auditoria LGPD)
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
def test_dispatch_logs_operator_oid_em_caso_de_erro(client, fake_user, mocker):
    """Se dispatch_service levanta, o log de erro deve incluir oid do operador
    para auditoria - sabemos quem disparou mesmo se falhou."""
    import main

    async def override_auth():
        return fake_user

    main.app.dependency_overrides[main.verify_dispatch_auth] = override_auth
    mocker.patch.object(
        main.dispatch_service,
        "enviar_oferta_para_prestadores",
        side_effect=RuntimeError("DB offline"),
    )
    mock_logger = mocker.patch.object(main, "logger")

    try:
        response = client.post(
            "/api/dispatch",
            json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
            headers={"Authorization": "Bearer fake"},
        )

        assert response.status_code == 200  # endpoint nao propaga (ja era)
        assert response.json()["status"] == "error"

        # Confirma que erro foi logado com oid
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
    client, fake_user,
):
    """Mesmo com token valido, payload sem 'pedido_uuid' eh rejeitado por
    Pydantic antes do endpoint executar."""
    import main

    async def override_auth():
        return fake_user

    main.app.dependency_overrides[main.verify_dispatch_auth] = override_auth

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
def test_dispatch_email_do_operador_eh_mascarado_no_log(client, fake_user, mocker):
    """LGPD: email do operador eh PII, deve passar por mask_pii antes do log.
    O log nao pode conter 'operador@aegea.com.br' em claro."""
    import main

    async def override_auth():
        return fake_user

    main.app.dependency_overrides[main.verify_dispatch_auth] = override_auth
    mocker.patch.object(
        main.dispatch_service,
        "enviar_oferta_para_prestadores",
        return_value={"status": "success", "enviados": 1},
    )
    mock_logger = mocker.patch.object(main, "logger")

    try:
        client.post(
            "/api/dispatch",
            json={"pedido_uuid": "ped-1", "parceiros": ["uuid-1"]},
            headers={"Authorization": "Bearer fake"},
        )

        info_calls = mock_logger.info.call_args_list
        dispatch_log = next(c for c in info_calls if "dispatch recebido" in c.args[0])
        dims = dispatch_log.kwargs["extra"]["custom_dimensions"]

        # sender_hash existe (eh o hash) e NAO eh o email em claro
        assert "sender_hash" in dims
        assert "operador@aegea.com.br" not in dims["sender_hash"]
        # Mas inclui o oid (que nao eh PII - eh UUID opaco)
        assert dims["operator_oid"] == "12345678-1234-1234-1234-123456789abc"
    finally:
        main.app.dependency_overrides.clear()
