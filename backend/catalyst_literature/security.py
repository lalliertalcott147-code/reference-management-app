from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

SESSION_COOKIE = "catalyst_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class SessionManager:
    def __init__(self) -> None:
        self._launch_token = secrets.token_urlsafe(32)
        self._session_token = secrets.token_urlsafe(32)
        self._launch_redeemed = False

    @property
    def launch_token(self) -> str:
        return self._launch_token

    @property
    def session_token(self) -> str:
        return self._session_token

    def redeem_launch_token(self, candidate: str) -> bool:
        if self._launch_redeemed:
            return False
        if not hmac.compare_digest(candidate, self._launch_token):
            return False
        self._launch_redeemed = True
        return True

    def valid_session(self, candidate: str | None) -> bool:
        if candidate is None:
            return False
        return hmac.compare_digest(candidate, self._session_token)


class LocalSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, sessions: SessionManager, origin: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.sessions = sessions
        self.origin = origin.rstrip("/")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        public = path == "/api/health" or path == "/launch" or not path.startswith("/api/")
        if public:
            return self._secure(await call_next(request), path)

        if not self.sessions.valid_session(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse({"detail": "Local session is missing or invalid"}, status_code=401)

        if request.method not in SAFE_METHODS:
            request_origin = request.headers.get("origin")
            if request_origin != self.origin:
                return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)

        return self._secure(await call_next(request), path)

    @staticmethod
    def _secure(response: Response, path: str) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "worker-src 'self' blob:; connect-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        if path.startswith("/api/") or path == "/launch":
            response.headers.setdefault("Cache-Control", "no-store")
        return response
