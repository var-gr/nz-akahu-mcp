"""Tests for AkahuConfig: env loading, validation, auth headers."""

from __future__ import annotations

import pytest


def test_loads_from_env(fake_env: None) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    assert cfg.app_token == "app_token_test"
    assert cfg.user_token == "user_token_test"
    assert cfg.base_url == "https://api.akahu.io/v1"
    assert cfg.read_only is True
    assert cfg.automation_bypass is False
    assert cfg.request_timeout == 5
    assert cfg.log_level == "INFO"


def test_is_configured_true_when_both_tokens_present(fake_env: None) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    assert AkahuConfig().is_configured is True


def test_is_configured_false_when_app_token_missing(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_APP_TOKEN", "")
    assert AkahuConfig().is_configured is False


def test_is_configured_false_when_user_token_missing(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_USER_TOKEN", "")
    assert AkahuConfig().is_configured is False


def test_auth_headers_contain_both_tokens(fake_env: None) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    headers = cfg.auth_headers
    assert headers["Authorization"] == "Bearer user_token_test"
    assert headers["X-Akahu-Id"] == "app_token_test"


def test_bypass_with_read_only_raises(monkeypatch: pytest.MonkeyPatch, fake_env: None) -> None:
    """Incoherent combination must fail loudly at startup, not silently ignore."""
    from pydantic import ValidationError

    from nz_akahu_mcp.config import AkahuConfig

    monkeypatch.setenv("AKAHU_READ_ONLY", "true")
    monkeypatch.setenv("AKAHU_AUTOMATION_BYPASS", "true")
    with pytest.raises(ValidationError) as exc_info:
        AkahuConfig()
    assert "automation_bypass" in str(exc_info.value).lower()


def test_writable_env_loads(writable_env: None) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    assert cfg.read_only is False
    assert cfg.automation_bypass is False


def test_bypass_env_loads(bypass_env: None) -> None:
    from nz_akahu_mcp.config import AkahuConfig

    cfg = AkahuConfig()
    assert cfg.read_only is False
    assert cfg.automation_bypass is True


def test_http_config_defaults(fake_env: None) -> None:
    from nz_akahu_mcp.config import HttpConfig

    cfg = HttpConfig()
    assert cfg.auth_token == ""
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8080
    assert cfg.path == "/mcp"
    assert cfg.transport == "stdio"
    assert cfg.allowed_hosts == ""
    assert cfg.stateless is False


def test_http_config_from_env(
    monkeypatch: pytest.MonkeyPatch, fake_env: None
) -> None:
    from nz_akahu_mcp.config import HttpConfig

    monkeypatch.setenv("MCP_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "9090")
    monkeypatch.setenv("MCP_PATH", "/mcp")
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("MCP_STATELESS", "true")
    cfg = HttpConfig()
    assert cfg.auth_token == "a" * 40
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9090
    assert cfg.transport == "http"
    assert cfg.allowed_hosts == "api.example.com"
    assert cfg.stateless is True
