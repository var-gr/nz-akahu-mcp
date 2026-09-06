"""Tests for HTTP token auth: extraction, comparison, middleware, log redaction."""

from __future__ import annotations

import logging

import pytest
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from nz_akahu_mcp.auth import (
    MIN_AUTH_TOKEN_LENGTH,
    RedactQueryTokenFilter,
    TokenAuthMiddleware,
    digest_token,
    extract_presented_token,
    generate_auth_token,
    host_is_allowed,
    install_log_redaction,
    is_public_path,
    parse_allowed_hosts,
    require_http_auth_token,
    tokens_match,
)

VALID_TOKEN = "a" * MIN_AUTH_TOKEN_LENGTH + "Z1"


async def _ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await JSONResponse({"ok": True})(scope, receive, send)


def _scope(
    *,
    path: str = "/mcp",
    method: str = "POST",
    query: bytes | str = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    scope_type: str = "http",
) -> Scope:
    return {
        "type": scope_type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "scheme": "http",
    }


def test_generate_auth_token_is_url_safe_and_long() -> None:
    token = generate_auth_token()
    assert len(token) >= MIN_AUTH_TOKEN_LENGTH
    assert "/" not in token
    assert "+" not in token
    assert generate_auth_token() != token


def test_require_token_rejects_short() -> None:
    with pytest.raises(ValueError, match="at least"):
        require_http_auth_token("short")


def test_require_token_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError, match="at least"):
        require_http_auth_token("   ")


def test_require_token_rejects_placeholder() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        require_http_auth_token("changemechangemechangemechangeme")


def test_require_token_strips_and_accepts() -> None:
    assert require_http_auth_token(f"  {VALID_TOKEN}  ") == VALID_TOKEN


def test_tokens_match_accepts_equal_and_rejects_other() -> None:
    digest = digest_token(VALID_TOKEN)
    assert tokens_match(VALID_TOKEN, digest) is True
    assert tokens_match(VALID_TOKEN + "x", digest) is False
    assert tokens_match("", digest) is False


def test_parse_allowed_hosts_splits_and_lowers() -> None:
    assert parse_allowed_hosts("") == frozenset()
    assert parse_allowed_hosts(" API.Example.COM , localhost ") == frozenset(
        {"api.example.com", "localhost"}
    )


def test_extract_prefers_bearer_over_query() -> None:
    scope = _scope(
        query=b"token=from-query",
        headers=[(b"authorization", b"Bearer from-header")],
    )
    assert extract_presented_token(scope) == "from-header"


def test_extract_query_when_no_bearer() -> None:
    assert extract_presented_token(_scope(query=b"token=from-query")) == "from-query"


def test_extract_query_string_as_str() -> None:
    assert extract_presented_token(_scope(query="token=str-query")) == "str-query"


def test_extract_empty_when_missing() -> None:
    assert extract_presented_token(_scope()) == ""


def test_extract_ignores_empty_bearer_and_falls_back_to_query() -> None:
    scope = _scope(
        query=b"token=from-query",
        headers=[(b"authorization", b"Bearer   ")],
    )
    assert extract_presented_token(scope) == "from-query"


def test_is_public_path_get_healthz_only() -> None:
    assert is_public_path(_scope(path="/healthz", method="GET")) is True
    assert is_public_path(_scope(path="/healthz/", method="GET")) is True
    assert is_public_path(_scope(path="/healthz", method="POST")) is False
    assert is_public_path(_scope(path="/mcp", method="GET")) is False


def test_host_is_allowed_when_unrestricted() -> None:
    assert host_is_allowed(_scope(), frozenset()) is True


def test_host_is_allowed_strips_port() -> None:
    scope = _scope(headers=[(b"host", b"api.example.com:443")])
    assert host_is_allowed(scope, frozenset({"api.example.com"})) is True
    assert host_is_allowed(scope, frozenset({"other.example"})) is False


def test_middleware_allows_healthz_without_token() -> None:
    app = TokenAuthMiddleware(_ok_app, expected_token=VALID_TOKEN)
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_middleware_rejects_missing_and_wrong_token() -> None:
    app = TokenAuthMiddleware(_ok_app, expected_token=VALID_TOKEN)
    client = TestClient(app)
    missing = client.post("/mcp")
    assert missing.status_code == 401
    assert missing.json() == {"error": "unauthorized"}
    wrong = client.post("/mcp?token=wrong-token-wrong-token-wrong-token")
    assert wrong.status_code == 401


def test_middleware_accepts_query_and_bearer() -> None:
    app = TokenAuthMiddleware(_ok_app, expected_token=VALID_TOKEN)
    client = TestClient(app)
    via_query = client.post(f"/mcp?token={VALID_TOKEN}")
    assert via_query.status_code == 200
    via_header = client.post("/mcp", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert via_header.status_code == 200


def test_middleware_rejects_disallowed_host() -> None:
    app = TokenAuthMiddleware(
        _ok_app,
        expected_token=VALID_TOKEN,
        allowed_hosts=frozenset({"api.example.com"}),
    )
    client = TestClient(app, base_url="http://evil.example")
    response = client.post(f"/mcp?token={VALID_TOKEN}")
    assert response.status_code == 401


def test_middleware_allows_listed_host() -> None:
    app = TokenAuthMiddleware(
        _ok_app,
        expected_token=VALID_TOKEN,
        allowed_hosts=frozenset({"testserver"}),
    )
    client = TestClient(app)
    response = client.post(f"/mcp?token={VALID_TOKEN}")
    assert response.status_code == 200


async def test_middleware_passes_through_non_http() -> None:
    seen: dict[str, str] = {}

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen["type"] = str(scope["type"])

    async def noop_receive() -> dict[str, object]:
        return {"type": "lifespan.startup"}

    async def noop_send(_message: dict[str, object]) -> None:
        return None

    app = TokenAuthMiddleware(inner, expected_token=VALID_TOKEN)
    await app(_scope(scope_type="lifespan"), noop_receive, noop_send)
    assert seen["type"] == "lifespan"


def test_redact_filter_scrubs_query_tokens(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("nz_akahu_mcp.auth.test")
    logger.addFilter(RedactQueryTokenFilter())
    with caplog.at_level(logging.INFO, logger="nz_akahu_mcp.auth.test"):
        logger.info("POST /mcp?token=super-secret-value HTTP/1.1")
        logger.info("other %s", "https://x/mcp?token=abc&foo=1")
        logger.info("dict %(url)s", {"url": "/mcp?token=abc"})
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "super-secret-value" not in blob
    assert "token=[redacted]" in blob
    assert "/mcp?token=abc" not in blob


def test_redact_filter_leaves_non_strings() -> None:
    filt = RedactQueryTokenFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=123,
        args=(99,),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert record.msg == 123
    assert record.args == (99,)


def test_install_log_redaction_attaches_filters() -> None:
    install_log_redaction()
    kinds = {type(f) for f in logging.getLogger("uvicorn.access").filters}
    assert RedactQueryTokenFilter in kinds
