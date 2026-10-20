"""HTTP API for the External Secrets Operator webhook provider.

``GET /v1/secret?path=<Group/Entry>&property=<name>`` returns a field's raw value or an
attachment's content, or all fields of the entry as a JSON object when ``property`` is empty.
ESO treats a 404 as "secret deleted", so it is only returned when the entry or field really does
not exist.
"""

import hmac
import logging
from collections.abc import Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .store import AmbiguousError, BrokenReferenceError, NotFoundError, Store

log = logging.getLogger(__name__)


def create_app(store: Store, auth_token: Callable[[], str]) -> Starlette:
    def authorized(request: Request) -> bool:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        expected = auth_token().encode()
        return (
            scheme.lower() == "bearer"
            and bool(expected)
            and hmac.compare_digest(token.encode(), expected)
        )

    async def secret(request: Request) -> Response:
        if not authorized(request):
            return PlainTextResponse("unauthorized", 401, {"WWW-Authenticate": "Bearer"})

        path = request.query_params.get("path", "")
        prop = request.query_params.get("property", "")
        if not path.strip("/"):
            return PlainTextResponse("query parameter 'path' is required", 400)

        try:
            # Reloading the database runs the KDF, which takes a while: keep it off the event loop.
            if not prop:
                return JSONResponse(await run_in_threadpool(store.fields, path))
            value = await run_in_threadpool(store.value, path, prop)
        except NotFoundError as e:
            return PlainTextResponse(str(e), 404)
        except AmbiguousError as e:
            return PlainTextResponse(str(e), 409)
        except BrokenReferenceError as e:
            # Not a 404: ESO would delete the Secret.
            log.error("%s: %s", path, e)
            return PlainTextResponse(str(e), 500)

        if isinstance(value, bytes):
            return Response(value, media_type="application/octet-stream")
        return PlainTextResponse(value)

    async def healthz(_: Request) -> Response:
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/v1/secret", secret),
            Route("/healthz", healthz),
        ]
    )
