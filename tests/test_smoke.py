from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vault_api.core.config import DEFAULT_PORT, Settings, get_settings
from vault_api.db.session import get_engine, get_session_factory
from vault_api.main import create_app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("VAULT_DATABASE_URL", TEST_DATABASE_URL)
    caches = (get_settings, get_engine, get_session_factory)
    for cached in caches:
        cached.cache_clear()
    yield
    for cached in caches:
        cached.cache_clear()


def test_settings_read_database_url_from_environment() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url == TEST_DATABASE_URL


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
