"""HTTP access control for the MCP endpoint.

Callers present a shared secret via `Authorization: Bearer <token>` or
`?token=<token>`. Comparison is constant-time over SHA-256 digests so token
length does not leak. Query-string tokens are accepted because many MCP
clients only have a URL field; prefer the Bearer header when the client
supports it (query strings show up in access logs unless redacted).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MIN_AUTH_TOKEN_LENGTH = 32
_PUBLIC_PATHS = frozenset({"/healthz", "/healthz/"})
_BEARER_PREFIX = "bearer "
_TOKEN_QUERY_RE = re.compile(r"([?&]token=)[^&\s]+", re.IGNORECASE)
_WEAK_TOKENS = frozenset(
    {
        "changeme",
        "password",
        "secret",
        "token-here",
        "your-token-here",
        "replace-me",
        "changemechangemechangemechangeme",
    }
)


def generate_auth_token() -> str:
    """Return a URL-safe 256-bit token suitable for MCP_AUTH_TOKEN and ?token=."""
    return secrets.token_urlsafe(32)


def digest_token(token: str) -> bytes:
    """SHA-256 digest of a token. Used so compare_digest always sees equal-length inputs."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def tokens_match(presented: str, expected_digest: bytes) -> bool:
    """Constant-time match of a presented token against a precomputed digest."""
    return hmac.compare_digest(digest_token(presented), expected_digest)


def parse_allowed_hosts(raw: str) -> frozenset[str]:
    """Split a comma-separated Host allow-list. Empty input means unrestricted."""
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def require_http_auth_token(token: str) -> str:
    """Reject missing, short, or placeholder tokens. HTTP mode is fail-closed."""
    stripped = token.strip()
    if len(stripped) < MIN_AUTH_TOKEN_LENGTH:
        raise ValueError(
            f"MCP_AUTH_TOKEN must be at least {MIN_AUTH_TOKEN_LENGTH} characters. "
            "Generate one with: nz-akahu-mcp --gen-token"
        )
    if stripped.lower() in _WEAK_TOKENS:
        raise ValueError(
            "MCP_AUTH_TOKEN is a placeholder. Generate one with: nz-akahu-mcp --gen-token"
        )
    return stripped


def extract_presented_token(scope: Scope) -> str:
    """Bearer header wins; otherwise the first `token` query value. Empty if neither."""
    headers = Headers(scope=scope)
    authorization = headers.get("authorization", "")
    if authorization.lower().startswith(_BEARER_PREFIX):
        bearer = authorization[len(_BEARER_PREFIX) :].strip()
        if bearer:
            return bearer
    query = scope.get("query_string", b"")
    query_text = query.decode("latin-1") if isinstance(query, bytes) else str(query)
    values = parse_qs(query_text, keep_blank_values=False).get("token") or []
    if values and values[0]:
        return values[0]
    return ""


def is_public_path(scope: Scope) -> bool:
    """Health checks stay unauthenticated so Docker/K8s probes work."""
    if scope.get("method") != "GET":
        return False
    path = scope.get("path", "")
    return path in _PUBLIC_PATHS


def host_is_allowed(scope: Scope, allowed_hosts: frozenset[str]) -> bool:
    """If an allow-list is set, require the Host header (minus port) to match."""
    if not allowed_hosts:
        return True
    headers = Headers(scope=scope)
    host = headers.get("host", "").split(":")[0].lower()
    return host in allowed_hosts


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized"},
        status_code=401,
        headers={
            "WWW-Authenticate": 'Bearer realm="mcp"',
            "Cache-Control": "no-store",
        },
    )


class TokenAuthMiddleware:
    """ASGI middleware: require the shared MCP_AUTH_TOKEN on every non-public route."""

    def __init__(
        self,
        app: ASGIApp,
        expected_token: str,
        allowed_hosts: frozenset[str] | None = None,
    ) -> None:
        self.app = app
        self.expected_digest = digest_token(expected_token)
        self.allowed_hosts = allowed_hosts or frozenset()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if is_public_path(scope):
            await self.app(scope, receive, send)
            return
        if not host_is_allowed(scope, self.allowed_hosts):
            await _unauthorized()(scope, receive, send)
            return
        presented = extract_presented_token(scope)
        if not tokens_match(presented, self.expected_digest):
            await _unauthorized()(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RedactQueryTokenFilter(logging.Filter):
    """Strip `token=` values out of log records so access logs cannot leak the secret."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _TOKEN_QUERY_RE.sub(r"\1[redacted]", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: _redact_value(value) for key, value in record.args.items()}
            else:
                record.args = tuple(_redact_value(arg) for arg in record.args)
        return True


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return _TOKEN_QUERY_RE.sub(r"\1[redacted]", value)
    return value


def install_log_redaction() -> None:
    """Attach the redaction filter to root and uvicorn loggers."""
    filt = RedactQueryTokenFilter()
    logging.getLogger().addFilter(filt)
    logging.getLogger("uvicorn.access").addFilter(filt)
    logging.getLogger("uvicorn.error").addFilter(filt)
