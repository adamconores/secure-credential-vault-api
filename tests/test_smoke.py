import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vault_api.core.config import DEFAULT_PORT, Settings
from vault_api.db.session import get_engine
from vault_api.main import create_app


def test_settings_read_database_url_from_environment(database_url: str) -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url == database_url


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_DATABASE_URL")

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_settings_reject_out_of_range_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_PORT", "70000")

    with pytest.raises(ValidationError, match="port"):
        Settings(_env_file=None)


def test_settings_ignore_unprefixed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "1234")

    assert Settings(_env_file=None).port == DEFAULT_PORT


def test_engine_never_logs_bound_parameters() -> None:
    assert get_engine().sync_engine.hide_parameters


def test_app_serves_openapi_schema_with_configured_title() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Secure Credential Vault API"
