"""Tests for the root server: composition, namespaces, startup banner."""

from __future__ import annotations

import logging

import pytest


async def test_root_server_exposes_all_14_tools(fake_env: None) -> None:
    from nz_akahu_mcp.server import build_server

    mcp = build_server()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        # accounts (6)
        "acct_list_accounts",
        "acct_get_account",
        "acct_get_account_balance",
        "acct_get_pending_transactions",
        "acct_refresh_all_accounts",
        "acct_refresh_account",
        # transactions (6)
        "txn_get_transactions",
        "txn_get_transaction",
        "txn_get_transactions_by_ids",
        "txn_get_pending_transactions",
        "txn_search_transactions",
        "txn_report_transaction_issue",
        # identity (2) -- /categories, /parties, /identity/{id}/verify-name are app-scoped
        "id_get_me",
        "id_verify_name",
    }
    assert names == expected


def test_startup_banner_when_bypass_off(
    writable_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_akahu_mcp.server import log_startup_banner

    with caplog.at_level(logging.INFO, logger="nz_akahu_mcp.server"):
        log_startup_banner()
    blob = "\n".join(r.message for r in caplog.records)
    assert "all writes require confirmation" in blob.lower()


def test_startup_banner_when_bypass_on(
    bypass_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_akahu_mcp.server import log_startup_banner

    with caplog.at_level(logging.WARNING, logger="nz_akahu_mcp.server"):
        log_startup_banner()
    blob = "\n".join(r.message for r in caplog.records)
    assert "automation bypass enabled" in blob.lower()
    assert "refresh_all_accounts" in blob
    assert "refresh_account" in blob


def test_startup_banner_when_readonly(
    fake_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    from nz_akahu_mcp.server import log_startup_banner

    with caplog.at_level(logging.INFO, logger="nz_akahu_mcp.server"):
        log_startup_banner()
    blob = "\n".join(r.message for r in caplog.records)
    assert "read-only" in blob.lower()


def test_register_health_route_adds_healthz(fake_env: None) -> None:
    from nz_akahu_mcp.server import build_server, register_health_route

    mcp = build_server()
    register_health_route(mcp)
    paths = [getattr(route, "path", "") for route in mcp._additional_http_routes]
    assert "/healthz" in paths
