import httpx2
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.anyio


async def test_health_reports_ok_when_the_database_answers(client: httpx2.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_reports_unavailable_when_the_database_fails(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing_execute(self: AsyncSession, *args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "OperationalError" in caplog.text


async def test_health_reports_unavailable_on_network_errors(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unreachable(self: AsyncSession, *args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(AsyncSession, "execute", unreachable)

    response = await client.get("/health")

    assert response.status_code == 503
