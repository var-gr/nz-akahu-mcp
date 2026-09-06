# CLAUDE.md

Guidance for working in this repository.

## What this is

Unofficial MCP server for the Akahu open-finance API (NZ). 14 tools as thin
wrappers over Akahu Personal-App endpoints. Serves token-gated streamable HTTP
(Docker) or stdio (local).

Design line: **primitives only.** Analytical questions are the LLM's job over
raw transaction data. Do not add analytical/forecasting tools.

## Commands

All commands use `uv`.

```bash
uv sync --extra dev
uv run pytest
uv run pytest tests/test_auth.py
uv run ruff check .
uv run mypy src
uv run nz-akahu-mcp --gen-token
uv run nz-akahu-mcp
uv run nz-akahu-mcp --http
docker compose up --build
```

pytest enforces `--cov-fail-under=100` on line and branch coverage. mypy is
strict.

## Architecture

```
src/nz_akahu_mcp/
├── server.py        Root FastMCP server; stdio or HTTP
├── auth.py          MCP_AUTH_TOKEN gate (query + Bearer), log redaction
├── tools/
│   ├── accounts.py        6 tools under acct/*
│   ├── transactions.py    6 tools under txn/*
│   └── identity.py        2 tools under id/*
├── client.py        AkahuClient: httpx + 3-attempt retry/backoff
├── models.py        Pydantic shapes; aliases for Akahu _id / _account
├── config.py        AkahuConfig (AKAHU_*) and HttpConfig (MCP_*)
├── deps.py          Process-wide AkahuClient cache
├── safety.py        @require_write_consent + 3-layer safety
└── formatting.py    format_money, mask_account, parse_iso_date
```

HTTP: `build_http_app` / `run_http` wrap FastMCP `http_app` with
`TokenAuthMiddleware`. `GET /healthz` is public. `/mcp` requires
`?token=` or `Authorization: Bearer`. Docker default is `MCP_TRANSPORT=http`.

## Three-layer write safety

Every write tool is decorated with `@require_write_consent`.

1. **Read-only refusal.** `AKAHU_READ_ONLY=true` (default) raises `ReadOnlyError`.
2. **Per-call elicitation.** `ctx.elicit()`. Decline/cancel raises.
3. **Automation bypass.** `automatable=True` and `AKAHU_AUTOMATION_BYPASS=true`
   skips layer 2.

`AKAHU_READ_ONLY=true` + `AKAHU_AUTOMATION_BYPASS=true` is rejected at startup.

New write tools: `automatable=False` unless the action is idempotent,
rate-limited, and free of third-party side effects.

## FastMCP docstring parsing

The `Returns:` block is dropped when an `Args:` block is present. Output shape
docs go in the body paragraph between the summary and `Args:`.

## Akahu API constraints

- Personal Apps only. Do not add app-scoped, payments, or webhook tools.
- Two-header auth: `Authorization: Bearer <user_token>` and `X-Akahu-Id: <app_token>`.
- Transactions are formatted in NZD. Pair with `get_account` for other currencies.
- Account numbers are masked via `mask_account`.

## Testing

- `fake_env` / `writable_env` / `bypass_env` in `tests/conftest.py`
- `ctx_factory()` for elicit accept/decline/cancel
- HTTP traffic via `respx_mock`
- Auth tests hit `TokenAuthMiddleware` directly; HTTP wiring uses Starlette TestClient

## HTTP auth

`MCP_AUTH_TOKEN` is the proxy secret (not an Akahu token). Fail-closed in HTTP
mode. Constant-time SHA-256 compare. Query `token` and Bearer both work.
`MCP_ALLOWED_HOSTS` is an optional Host allow-list.

## Style

- No emojis. No em dashes. Comments explain why, not what.
- Docs are functional, not retrospective.
