"""ASGI middleware: request body size limit and no-store caching."""

from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The largest valid item is about 160 KB when a client escapes every character as
# \uXXXX surrogate pairs (json.dumps default); 256 KiB leaves headroom above that.
MAX_REQUEST_BODY_BYTES = 256 * 1024
TOO_LARGE_DETAIL = "Request body too large"
CONTENT_LENGTH_HEADER = b"content-length"
NO_STORE = "no-store"


def _too_large() -> HTTPException:
    return HTTPException(status_code=413, detail=TOO_LARGE_DETAIL)


def _declares_too_large(scope: Scope, max_body_bytes: int) -> bool:
    """True if `Content-Length` declares more than the limit.

    Lengths with more digits than the limit are over it by definition; checking that
    first avoids converting absurdly long digit strings. Non-numeric values are left to
    the counting path.
    """
    for name, value in scope["headers"]:
        if name == CONTENT_LENGTH_HEADER and value.isdigit():
            return len(value) > len(str(max_body_bytes)) or int(value) > max_body_bytes
    return False


class RequestBodyLimitMiddleware:
    """Refuse request bodies over the limit with 413.

    A declared `Content-Length` is checked before the app runs. Bodies without one
    (chunked uploads) are counted as they arrive and cut off once over the limit.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if _declares_too_large(scope, self.max_body_bytes):
            response = JSONResponse({"detail": TOO_LARGE_DETAIL}, status_code=413)
            await response(scope, receive, send)
            return

        received_bytes = 0

        async def counting_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    # Raised while the app reads the body; FastAPI turns it into a 413.
                    raise _too_large()
            return message

        await self.app(scope, counting_receive, send)


class NoStoreMiddleware:
    """Mark every HTTP response `Cache-Control: no-store`.

    Responses carry decrypted credentials or access tokens (RFC 6749 section 5.1 requires
    no-store for token responses), and error responses must not be cached either.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = NO_STORE
            await send(message)

        await self.app(scope, receive, send_with_no_store)
