import pytest
from starlette.types import Message, Receive, Scope, Send

from vault_api.api.middleware import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware

pytestmark = pytest.mark.anyio

HUGE_DIGIT_COUNT = 5000


async def downstream_app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def run(content_length: bytes) -> int:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "headers": [(b"content-length", content_length)]}
    await RequestBodyLimitMiddleware(downstream_app)(scope, receive, send)
    status: int = sent[0]["status"]
    return status


async def test_absurdly_long_content_length_is_refused_not_crashed() -> None:
    assert await run(b"9" * HUGE_DIGIT_COUNT) == 413


async def test_content_length_at_the_limit_is_accepted() -> None:
    assert await run(str(MAX_REQUEST_BODY_BYTES).encode()) == 200
