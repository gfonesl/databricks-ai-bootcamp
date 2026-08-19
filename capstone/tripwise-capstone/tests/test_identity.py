import pytest
from identity import AuthorizationError, Role, authorize, required_role, validate_auth_config


def test_authorization_fails_closed_without_configuration(monkeypatch):
    monkeypatch.setenv("TRIPWISE_AUTH_MODE", "enforce")
    monkeypatch.delenv("TRIPWISE_OWNER_SUBJECTS", raising=False)
    monkeypatch.delenv("TRIPWISE_AUTOMATION_SUBJECTS", raising=False)
    with pytest.raises(RuntimeError, match="authorization is not configured"):
        validate_auth_config()


def test_owner_and_automation_roles_are_separate(monkeypatch):
    monkeypatch.setenv("TRIPWISE_AUTH_MODE", "enforce")
    monkeypatch.setenv("TRIPWISE_OWNER_SUBJECTS", "owner-id")
    monkeypatch.setenv("TRIPWISE_AUTOMATION_SUBJECTS", "automation-id")

    owner = authorize({"x-forwarded-user": "owner-id"}, Role.OWNER)
    automation = authorize({"x-forwarded-user": "automation-id"}, Role.AUTOMATION)

    assert owner.role is Role.OWNER
    assert automation.role is Role.AUTOMATION
    with pytest.raises(AuthorizationError) as error:
        authorize({"x-forwarded-user": "owner-id"}, Role.AUTOMATION)
    assert error.value.status_code == 403


def test_missing_forwarded_identity_is_unauthorized(monkeypatch):
    monkeypatch.setenv("TRIPWISE_AUTH_MODE", "enforce")
    monkeypatch.setenv("TRIPWISE_OWNER_SUBJECTS", "owner-id")
    monkeypatch.setenv("TRIPWISE_AUTOMATION_SUBJECTS", "automation-id")
    with pytest.raises(AuthorizationError) as error:
        authorize({}, Role.OWNER)
    assert error.value.status_code == 401


def test_route_roles_cover_rest_pipeline_and_mcp():
    assert required_role("/api/trips") is Role.OWNER
    assert required_role("/api/pipeline/context") is Role.AUTOMATION
    assert required_role("/mcp") is Role.AUTOMATION
    assert required_role("/healthz") is None
