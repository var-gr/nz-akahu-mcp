"""Root FastMCP server. Mounts sub-servers; serves stdio or token-gated HTTP."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from nz_akahu_mcp.auth import (
    TokenAuthMiddleware,
    generate_auth_token,
    install_log_redaction,
    parse_allowed_hosts,
    require_http_auth_token,
)
from nz_akahu_mcp.config import AkahuConfig, HttpConfig
from nz_akahu_mcp.safety import bypass_eligible_tools
from nz_akahu_mcp.tools import accounts, identity, transactions

logger = logging.getLogger(__name__)


def build_server() -> FastMCP[Any]:
    """Construct the root FastMCP server with all sub-servers mounted."""
    mcp: FastMCP[Any] = FastMCP("nz-akahu-mcp")
    mcp.mount(accounts.server, namespace="acct")
    mcp.mount(transactions.server, namespace="txn")
    mcp.mount(identity.server, namespace="id")
    return mcp


def register_health_route(mcp: FastMCP[Any]) -> None:
    """Unauthenticated liveness probe for Docker / reverse proxies."""

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})


def build_http_app(
    *,
    auth_token: str,
    path: str = "/mcp",
    allowed_hosts: frozenset[str] | None = None,
    stateless_http: bool = False,
) -> Any:
    """Starlette app: /healthz public, /mcp gated by MCP_AUTH_TOKEN."""
    token = require_http_auth_token(auth_token)
    mcp = build_server()
    register_health_route(mcp)
    return mcp.http_app(
        path=path,
        stateless_http=stateless_http,
        middleware=[
            Middleware(
                TokenAuthMiddleware,
                expected_token=token,
                allowed_hosts=allowed_hosts or frozenset(),
            )
        ],
    )


def log_startup_banner() -> None:
    """Emit a banner describing the current safety posture."""
    cfg = AkahuConfig()
    if cfg.read_only:
        logger.info(
            "nz-akahu-mcp starting in READ-ONLY mode. All write tools will refuse "
            "until AKAHU_READ_ONLY=false."
        )
        return
    if cfg.automation_bypass:
        eligible = bypass_eligible_tools()
        logger.warning(
            "Automation bypass ENABLED. The following tools will skip the "
            "confirmation prompt: %s. All other writes still require "
            "confirmation. Disable by removing AKAHU_AUTOMATION_BYPASS from .env.",
            ", ".join(eligible),
        )
        return
    logger.info(
        "nz-akahu-mcp starting in WRITE mode. All writes require confirmation "
        "through Claude."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI flags for HTTP mode and token generation."""
    parser = argparse.ArgumentParser(
        prog="nz-akahu-mcp",
        description="Unofficial Akahu MCP server (stdio or token-gated HTTP).",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve MCP over HTTP (requires MCP_AUTH_TOKEN).",
    )
    parser.add_argument(
        "--gen-token",
        action="store_true",
        help="Print a new MCP_AUTH_TOKEN and exit.",
    )
    parser.add_argument("--host", default=None, help="HTTP bind host (default MCP_HOST).")
    parser.add_argument("--port", type=int, default=None, help="HTTP bind port (default MCP_PORT).")
    return parser.parse_args(argv)


def run_http(cfg: HttpConfig, *, host: str | None = None, port: int | None = None) -> None:
    """Bind streamable HTTP with token middleware. Fail closed if the token is weak."""
    try:
        token = require_http_auth_token(cfg.auth_token)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    install_log_redaction()
    mcp = build_server()
    register_health_route(mcp)
    bind_host = host or cfg.host
    bind_port = port if port is not None else cfg.port
    logger.info(
        "HTTP MCP listening on http://%s:%s%s (token auth required; /healthz is public)",
        bind_host,
        bind_port,
        cfg.path,
    )
    mcp.run(
        transport="http",
        host=bind_host,
        port=bind_port,
        path=cfg.path,
        middleware=[
            Middleware(
                TokenAuthMiddleware,
                expected_token=token,
                allowed_hosts=parse_allowed_hosts(cfg.allowed_hosts),
            )
        ],
        show_banner=False,
        stateless_http=cfg.stateless,
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point used by the `nz-akahu-mcp` console script.

    Tests pass `argv=[]` so pytest's own flags are not parsed.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.gen_token:
        print(generate_auth_token())
        return
    logging.basicConfig(
        level=AkahuConfig().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log_startup_banner()
    http_cfg = HttpConfig()
    if args.http or http_cfg.transport == "http":
        run_http(http_cfg, host=args.host, port=args.port)
        return
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
