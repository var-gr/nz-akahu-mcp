"""HTTP app wiring: healthz public, /mcp gated, CLI flags."""

from __future__ import annotations

import logging

import pytest
from starlette.testclient import TestClient

from tests.test_auth import VALID_TOKEN


def test_healthz_is_public(fake_env: None) -> None:
    from nz_akahu_mcp.server import build_http_app

    app = build_http_app(auth_token=VALID_TOKEN, stateless_http=True)
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_mcp_without_token_is_401(fake_env: None) -> None:
    from nz_akahu_mcp.server import build_http_app

    app = build_http_app(auth_token=VALID_TOKEN, stateless_http=True)
    with TestClient(app) as client:
        response = client.post("/mcp")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_mcp_with_query_token_is_not_401(fake_env: None) -> None:
    from nz_akahu_mcp.server import build_http_app

    app = build_http_app(auth_token=VALID_TOKEN, path="/mcp", stateless_http=True)
    with TestClient(app) as client:
        response = client.post(f"/mcp?token={VALID_TOKEN}", json={})
    assert response.status_code != 401


def test_build_http_app_rejects_short_token(fake_env: None) -> None:
    from nz_akahu_mcp.server import build_http_app

    with pytest.raises(ValueError, match="at least"):
        build_http_app(auth_token="nope")


def test_main_gen_token(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from nz_akahu_mcp.server import main

    main(["--gen-token"])
    out = capsys.readouterr().out.strip()
    assert len(out) >= 32


def test_main_stdio_runs(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_akahu_mcp import server

    called: dict[str, bool] = {"run": False}

    def fake_run(self: object, *args: object, **kwargs: object) -> None:
        called["run"] = True

    monkeypatch.setattr(server.FastMCP, "run", fake_run)
    server.main([])
    assert called["run"] is True


def test_main_http_calls_run_http(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_akahu_mcp import server
    from nz_akahu_mcp.config import HttpConfig

    seen: dict[str, object] = {}

    def fake_run_http(
        cfg: HttpConfig, *, host: str | None = None, port: int | None = None
    ) -> None:
        seen["host"] = host
        seen["port"] = port
        seen["token"] = cfg.auth_token

    monkeypatch.setattr(server, "run_http", fake_run_http)
    monkeypatch.setenv("MCP_AUTH_TOKEN", VALID_TOKEN)
    server.main(["--http", "--host", "127.0.0.1", "--port", "9999"])
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 9999


def test_main_http_via_env_transport(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_akahu_mcp import server

    called = {"http": False}

    def fake_run_http(*args: object, **kwargs: object) -> None:
        called["http"] = True

    monkeypatch.setattr(server, "run_http", fake_run_http)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_TOKEN", VALID_TOKEN)
    server.main([])
    assert called["http"] is True


def test_run_http_exits_without_token(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nz_akahu_mcp.config import HttpConfig
    from nz_akahu_mcp.server import run_http

    monkeypatch.setenv("MCP_AUTH_TOKEN", "")
    with pytest.raises(SystemExit, match="MCP_AUTH_TOKEN"):
        run_http(HttpConfig())


def test_run_http_invokes_fastmcp_run(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_akahu_mcp import server
    from nz_akahu_mcp.config import HttpConfig

    called: dict[str, object] = {}

    def fake_run(self: object, *args: object, **kwargs: object) -> None:
        called["kwargs"] = kwargs

    monkeypatch.setattr(server.FastMCP, "run", fake_run)
    monkeypatch.setenv("MCP_AUTH_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("MCP_STATELESS", "true")
    with caplog.at_level(logging.INFO, logger="nz_akahu_mcp.server"):
        server.run_http(HttpConfig(), host="0.0.0.0", port=8080)
    kwargs = called["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["transport"] == "http"
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8080
    assert kwargs["path"] == "/mcp"
    assert kwargs["stateless_http"] is True
    assert "token auth required" in caplog.text.lower()


def test_parse_args_http_flags() -> None:
    from nz_akahu_mcp.server import parse_args

    args = parse_args(["--http", "--host", "127.0.0.1", "--port", "9"])
    assert args.http is True
    assert args.host == "127.0.0.1"
    assert args.port == 9
    assert args.gen_token is False
