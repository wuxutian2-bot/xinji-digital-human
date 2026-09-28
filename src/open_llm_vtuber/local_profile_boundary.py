"""Browser boundary for the single local profile; this is not authentication."""

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class LocalProfileBoundaryMiddleware:
    def __init__(self, app: ASGIApp, port: int):
        self.app = app
        hosts = ("localhost", "127.0.0.1", "[::1]")
        self.authorities = {f"{host}:{port}" for host in hosts}
        if port in (80, 443):
            self.authorities.update(hosts)
        self.origins = {
            f"{scheme}://{authority}"
            for scheme in ("http", "https")
            for authority in self.authorities
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        origins = headers.getlist("origin")
        allowed = len(hosts) == 1 and hosts[0].lower() in self.authorities
        if origins:
            allowed = (
                allowed and len(origins) == 1 and origins[0].lower() in self.origins
            )
        elif headers.get("sec-fetch-site") == "cross-site":
            allowed = False
        # Origin-less local scripts are supported. Other OS users/processes are
        # outside this boundary; a caller-controlled header is not a login token.
        if not allowed:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await PlainTextResponse(
                    "Local profile origin required", status_code=403
                )(scope, receive, send)
            return
        await self.app(scope, receive, send)
