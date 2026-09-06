# nz-akahu-mcp

Unofficial MCP server for the [Akahu](https://akahu.nz) open-finance API
(New Zealand). 14 tools, read-only by default, token-gated HTTP for hosted
use, stdio for local use.

Point an MCP client at:

```text
https://api-mcp-akahu-proxy.vargr.cc/mcp?token=<MCP_AUTH_TOKEN>
```

Or send the same value as `Authorization: Bearer <MCP_AUTH_TOKEN>` (preferred
when the client has a headers field; query strings can leak in access logs).

## Prerequisites

1. An Akahu Personal App + user token from https://my.akahu.nz/developers
2. Docker (hosted) or [`uv`](https://docs.astral.sh/uv/) (local)

## Generate the proxy token

```bash
uv run nz-akahu-mcp --gen-token
# or: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the value in `.env` as `MCP_AUTH_TOKEN`. It must be at least 32 characters.
The process will not start in HTTP mode without it.

## Docker

```bash
cp .env.example .env
# fill AKAHU_APP_TOKEN, AKAHU_USER_TOKEN, MCP_AUTH_TOKEN
docker compose up --build -d
```

The container listens on `8080`. Put TLS in front (Cloudflare tunnel, Caddy,
nginx). Probe `GET /healthz` without a token.

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mcp
# 401
curl -sS -o /dev/null -w "%{http_code}\n" \
  "http://127.0.0.1:8080/mcp?token=$MCP_AUTH_TOKEN"
```

Optional: set `MCP_ALLOWED_HOSTS=api-mcp-akahu-proxy.vargr.cc` so only that
Host header is accepted (health checks on `/healthz` skip this).

## Client config

Claude Code:

```bash
claude mcp add --transport http akahu \
  "https://api-mcp-akahu-proxy.vargr.cc/mcp?token=YOUR_TOKEN"
```

Cursor / other HTTP MCP clients:

```json
{
  "mcpServers": {
    "akahu": {
      "url": "https://api-mcp-akahu-proxy.vargr.cc/mcp?token=YOUR_TOKEN"
    }
  }
}
```

If the client supports headers, prefer:

```json
{
  "mcpServers": {
    "akahu": {
      "url": "https://api-mcp-akahu-proxy.vargr.cc/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

## Local stdio (no Docker)

```bash
export AKAHU_APP_TOKEN=app_token_...
export AKAHU_USER_TOKEN=user_token_...
uv sync --extra dev
uv run pytest
uv run nz-akahu-mcp
```

HTTP without Docker:

```bash
export MCP_AUTH_TOKEN="$(uv run nz-akahu-mcp --gen-token)"
export MCP_TRANSPORT=http
uv run nz-akahu-mcp
# or: uv run nz-akahu-mcp --http --host 0.0.0.0 --port 8080
```

## Auth model

HTTP mode is fail-closed:

- `MCP_AUTH_TOKEN` is required (min 32 chars, placeholders rejected)
- Every path except `GET /healthz` needs a matching token
- Comparison is constant-time over SHA-256 digests
- Access logs redact `token=` query values
- Same 401 body for missing, wrong, or disallowed Host

Akahu credentials stay in server env. They are never accepted from the URL.

## Read-only by default

`AKAHU_READ_ONLY=true` until you flip it. Writes still call `ctx.elicit()`
unless `AKAHU_AUTOMATION_BYPASS=true` (refresh tools only). Remote HTTP
clients that cannot elicit should keep read-only on, or enable bypass only
for unattended refresh.

| Tool | Bypass-eligible |
| --- | --- |
| `accounts/refresh_all_accounts` | yes |
| `accounts/refresh_account` | yes |
| `transactions/report_transaction_issue` | no |
| `identity/verify_name` | no |

`AKAHU_AUTOMATION_BYPASS=true` with `AKAHU_READ_ONLY=true` is rejected at startup.

## Tool reference

### Read tools (10)

**`accounts/`**
- `list_accounts` - all connected accounts (masked, formatted balances)
- `get_account(account_id)` - single account details
- `get_account_balance(account_id)` - balance only
- `get_pending_transactions(account_id)` - not-yet-settled for one account

**`transactions/`**
- `get_transactions(account_id?, start_date?, end_date?, category?, min_amount?, max_amount?, limit=100)`
- `get_transaction(transaction_id)`
- `get_transactions_by_ids(ids)` - batch fetch by Akahu txn id
- `get_pending_transactions` - pending across all accounts
- `search_transactions(query, limit=50)` - substring across description + merchant.name

**`identity/`**
- `get_me`

### Write tools (4)

- `accounts/refresh_all_accounts` *(bypass-eligible)*
- `accounts/refresh_account(account_id)` *(bypass-eligible)*
- `transactions/report_transaction_issue(...)` *(always elicits)*
- `identity/verify_name(...)` *(always elicits)*

## Privacy

- Account numbers are masked: `01-1234-1234567-00` -> `01-****-***4567-00`
- Tokens are never logged
- Outbound traffic is only to `https://api.akahu.io/v1`

## Personal Apps only

App-scoped Akahu endpoints, payments, and webhooks are not exposed. See
https://developers.akahu.nz/docs/personal-apps.

## Disclaimer

Unofficial. Not affiliated with Akahu or any bank. Use at your own risk.

## License

Apache-2.0. See `LICENSE`.
