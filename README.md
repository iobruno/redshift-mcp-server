# redshift-mcp-server

A `uv` project wrapping [`awslabs.redshift-mcp-server`](https://awslabs.github.io/mcp/servers/redshift-mcp-server) —
the AWS Labs MCP server that lets an LLM (e.g. Claude) query **Amazon Redshift**
(provisioned clusters and Serverless workgroups) through the Redshift Data API.

## 1. What this is

`awslabs-redshift-mcp-server` is installed as a pinned dependency (`0.0.29`).
It's a Python program whose entrypoint is essentially:

```python
def main():
    mcp.run()
```

`mcp.run()` with no arguments means the server speaks **stdio only** — it reads
MCP (JSON-RPC 2.0) requests from stdin and writes responses to stdout. There's
no network port involved. That also means *the client has to launch the
process itself* to hold those pipes — which is exactly what the two options in
section 4 do.

> Running it over HTTP (e.g. to containerize it and share it via ECS) requires
> fronting it with a stdio→HTTP bridge such as `mcp-proxy`. That's a separate,
> later step — not covered by this README.

## 2. The tools this server exposes

| Tool | Params | What it does |
|---|---|---|
| `list_clusters` | *(none)* | Discovers clusters and serverless workgroups — gives you the `cluster_identifier` to use everywhere else |
| `list_databases` | `cluster_identifier`, `database_name` | List databases |
| `list_schemas` | `cluster_identifier`, `schema_database_name` | List schemas |
| `list_tables` | `cluster_identifier`, `table_database_name`, `table_schema_name` | List tables |
| `list_columns` | `cluster_identifier`, + db/schema/table | List columns |
| `execute_query` | `cluster_identifier`, `database_name`, `sql` | Runs SQL (read-only guarded) |
| `review_cluster` | `cluster_identifier`, `database_name` | Diagnostics (needs superuser) |

`cluster_identifier` is not something you pick freely — always start by calling
`list_clusters` and use the identifier it returns for your target workgroup
(e.g. `default-workgroup`) in every subsequent call.

## 3. Prerequisites

- [`uv`](https://docs.astral.sh/uv/) installed (`brew install uv`)
- AWS credentials for the `cp-dev` profile (already in `~/.aws/credentials`)
- Node.js/`npx` available, if you want to use the MCP Inspector UI (Option A below)
- Docker Desktop, if you want to run it in a container (§5)

Export the profile and region before running anything:

```bash
export AWS_PROFILE=cp-dev
export AWS_REGION=us-west-2
```

Install the dependencies (already locked in `uv.lock`, this just syncs the venv):

```bash
uv sync
```

## 4. Running it locally over stdio

### MCP Inspector (recommended; clickable UI)

This launches the server for you over stdio and gives you a browser UI to call
tools by hand — no need to write raw JSON-RPC.

```bash
npx @modelcontextprotocol/inspector uv run awslabs.redshift-mcp-server
```

Then in the browser tab it opens:

1. Click **Connect**.
2. **Tools** tab → run **`list_clusters`** → copy the `cluster_identifier` for
   `cpas-redshift-dev-prodclone` from the result.
3. Run **`execute_query`** with:
   - `cluster_identifier` = `cpas-redshift-dev-prodclone`
   - `database_name` = `dev`
   - `sql` = `SELECT current_date, 1+1 AS two;`

A successful result confirms the server, your AWS credentials, and the
workgroup are all wired up correctly end-to-end.

> ⚠️ Don't reach for `SELECT count(*) FROM awsdatacatalog.nyc_tlc_raw.zone_lookup;`
> as your first smoke test — that's a Redshift Spectrum (external) table, and
> **it will fail through this tool**. See [§6](#6-known-limitation-spectrumawsdatacatalog-external-tables-fail)
> for why, and how to still get that data.


## 5. Running it in Docker (Streamable HTTP) + connecting Claude Desktop

This is the setup meant to carry forward to ECR/ECS later — the container built
here is the same artifact that would get pushed there, just run locally for now.

### Why this isn't just "docker run the stdio server"

`awslabs.redshift-mcp-server`'s `main()` is a bare `mcp.run()` — stdio only.
The underlying `mcp` SDK (`mcp==1.28.1`, the same dependency this package
already pulls in) supports Streamable HTTP out of the box
(`mcp.server.fastmcp.server.FastMCP.run(transport="streamable-http")`), so
`server_http.py` in this repo just flips settings on the *same* `mcp` instance
awslabs already built (reusing all its tools/SQL-guard unchanged) and runs it
that way instead. No proxy process (e.g. `mcp-proxy`) is needed on the server
side for this.

Two things `server_http.py` has to override, or the container silently breaks:

- **DNS-rebinding protection.** FastMCP auto-enables a loopback-only
  `Host`-header allowlist whenever the bind host defaults to `127.0.0.1` (which
  is what upstream's `FastMCP(...)` call uses). It's disabled explicitly here
  since the container binds `0.0.0.0`. Leaving it enabled works today but would
  reject every request once this sits behind an ALB, so it's turned off now
  rather than resurfacing as a "works locally, fails in ECS" bug later.
- **`FASTMCP_HOST`/`FASTMCP_PORT` env vars don't work** — awslabs constructs
  `FastMCP(...)` with explicit host/port defaults that beat pydantic-settings'
  env resolution. `server_http.py` doesn't set host/port itself either —
  it just exposes the ASGI app (`app = mcp.streamable_http_app()`); the
  `Dockerfile`'s `CMD` runs it via the `uvicorn` CLI directly, with `--host`
  hardcoded to `0.0.0.0` (access control belongs at the ALB/security-group
  layer, not the bind address — there's no other value that would still be
  reachable through a container's port mapping anyway) and `--port`/
  `--workers` read from `REDSHIFT_MCP_PORT`/`REDSHIFT_MCP_WORKERS` via shell
  substitution in the `CMD` line itself.

`stateless_http = True` is also set, so there's no `Mcp-Session-Id` to pin —
multiple replicas can later sit behind a load balancer with no sticky sessions.

### Build and run

The `Dockerfile` is a two-stage build:

- **`builder`** — `ghcr.io/astral-sh/uv:python3.13-trixie-slim` (uv is
  preinstalled). Locks dependencies via `uv export --frozen` (respecting
  `uv.lock` exactly) into a `requirements.txt`, then `uv pip install --system`
  installs them straight into that stage's system Python — no project-local
  `.venv`.
- **`runner`** — plain `python:3.13-slim` plus `curl` (for the compose
  healthcheck below). Copies over just the installed `site-packages` and
  `server_http.py` from the builder. Runs as `CMD ["python", "server_http.py"]`
  — no venv path, no `PATH` overrides, no non-root user; the container itself
  is the isolation boundary.

Running it is via **Docker Compose** (`compose.yaml`), which also owns the
healthcheck (moved out of the `Dockerfile` — Compose's `healthcheck:` key
covers the same job):

```bash
docker compose up -d
```

`compose.yaml` reads `.env` automatically for variable substitution — no
`--env-file` flag needed. `AWS_REGION` and `AWS_PROFILE` already default
to `us-west-2`/`cp-dev` in `compose.yaml` if left unset; `.env` only needs the
two credential values. `.env` is git-ignored (`.gitignore`'s `.env`/`*.env`
patterns); `.env.example` is the tracked template.

Verified working end-to-end against `cpas-redshift-dev-prodclone`. boto3 supports
plain `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars natively — no
`~/.aws` mount needed.

`FASTMCP_LOG_LEVEL=INFO` is what actually makes tool calls visible in
`docker logs`. Without it, `awslabs.redshift_mcp_server` defaults to
`WARNING` (`consts.py:DEFAULT_LOG_LEVEL`) — you'd only see uvicorn's own
HTTP access log (`POST /mcp 200 OK`), not what the tool call actually did
(which cluster/database, session reuse vs. new session, discovery counts).
`DEBUG` is available too for SQL/statement-level detail, but `INFO` is the
right default here.

> ⚠️ **Don't also set `AWS_PROFILE`.** `redshift.py` always does
> `boto3.Session(profile_name=os.environ.get('AWS_PROFILE'), ...)`. Verified
> directly in the installed SDKs:
> - `boto3/session.py`: if `profile_name is not None`,
>   `self._session.set_config_variable('profile', profile_name)`.
> - `botocore/credentials.py`: `disable_env_vars =
>   session.instance_variables().get('profile') is not None`, and when that's
>   true, **the plain env-var credential provider is removed from the
>   resolver chain entirely** — even if `AWS_ACCESS_KEY_ID`/
>   `AWS_SECRET_ACCESS_KEY` are also set.
>
> So if `AWS_PROFILE` ends up set to anything (including via `.env`), boto3
> goes looking for that named profile in `~/.aws/config`/`credentials`
> instead of reading the plain keys, which fails with no mount present. Just
> leave `AWS_PROFILE` out of `.env`/`compose.yaml` entirely.

No `AWS_SESSION_TOKEN` is needed for a static long-term key pair. If you use
temporary/SSO-derived credentials instead, add it to `.env` and reference it
as another `environment:` entry in `compose.yaml`.


#### Alternative: mounting `~/.aws` with a named profile

If you'd rather not pass raw keys as env vars, add a read-only volume mount
and point `AWS_PROFILE` at a named profile instead — e.g. in `compose.yaml`:

```yaml
    volumes:
      - ~/.aws:/root/.aws:ro
    environment:
      AWS_PROFILE: ${AWS_PROFILE:-cp-dev}
      AWS_REGION: ${AWS_REGION:-us-west-2}
```

**Verify it's up:**

```bash
curl -s http://localhost:8000/health
# {"message":"Redshift MCP Server is up!"}

docker compose ps
# STATUS should read "Up ... (healthy)"
```

`/health` is a custom route added in `server_http.py` — the ALB (and the
`curl`-based healthcheck in `compose.yaml`) can't probe `/mcp` directly,
since that path requires a full MCP `initialize` handshake, not a plain
`GET`.

**Smoke test the MCP endpoint directly**, same idea as §4's Option B but over
HTTP instead of stdio pipes — no `sleep`-to-hold-stdin-open trick needed here,
since HTTP naturally waits for the response:

```bash
curl -sS -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0.0.0"}}}'
```

Then, with no session ID required (stateless mode):

```bash
curl -sS -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"execute_query","arguments":{"cluster_identifier":"cpas-redshift-dev-prodclone","database_name":"dev","sql":"SELECT current_date, 1+1 AS two;"}}}'
```

This was verified working end-to-end against `cpas-redshift-dev-prodclone`/`dev`.

### Connecting Claude Desktop

Claude Desktop's `claude_desktop_config.json` only launches **stdio**
processes — it has no field for a plain HTTP URL (adding one is liable to be
silently dropped rather than erroring). Its Custom Connector UI *does* accept
URLs, but only `https://`, rejecting `http://` even for `localhost` — so it
can't be used for local testing either. The bridge for local testing is
[`mcp-remote`](https://github.com/geelen/mcp-remote), an `npx` package that
Claude Desktop launches as a stdio subprocess, which in turn speaks HTTP to
the container:

```json
{
  "mcpServers": {
    "redshift": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@0.1.38",
        "http://localhost:8000/mcp",
        "--allow-http",
        "--transport",
        "http-only"
      ]
    }
  }
}
```

Add this `mcpServers` entry to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json` — merge it
into whatever else is already in that file, don't replace the file) via
Settings → Developer → Edit Config, then **fully quit and restart** Claude
Desktop (not just close the window). The `redshift` server should then show up
with its tools available.

Notes on the flags:

- `--allow-http` is required — without it, `mcp-remote` refuses a non-TLS URL.
- Pin the version (`@0.1.38` or later). Versions `0.0.5`–`0.1.15` have
  [CVE-2025-6514](https://security.snyk.io/package/npm/mcp-remote) (remote code
  execution).
- `--transport http-only` skips an SSE compatibility probe that isn't needed
  here, since the container only serves Streamable HTTP.

This `mcp-remote` hop is throwaway — purely a local-testing convenience. Once
this is on ECS behind real TLS, teammates will add it directly as a Custom
Connector (`https://` URL), no bridge involved.

### Verifying the connection in the app

Once Desktop restarts, confirm it picked up the server and configure tool
permissions:

1. In the message box, click the **"+" / "Add files, connectors, and more"**
   icon (bottom-left) → hover **Connectors** — `redshift` should be listed with
   a toggle, already on. That menu is just an on/off switch for the
   conversation; it doesn't show individual tools.
2. To see the tools and set permissions, go to **"+" → Manage connectors →
   redshift**. Under **Tool permissions**, each of the 6 tools
   (`list_clusters`, `list_databases`, `list_schemas`, `list_tables`,
   `list_columns`, `execute_query`) defaults to **"Needs approval"** — a
   confirmation dialog per call. Switch the header dropdown to **"Always
   allow"** to apply it to all of them at once, or set them individually via
   the checkmark icon per row.
3. `review_cluster` (the 7th tool from §2) does **not** appear in this list —
   it needs Redshift superuser and isn't exercised by the flows in this
   README; not a bug if you don't see it.

If `redshift` doesn't show up at all after a restart, or every tool call
fails, check that the **Docker container is actually running** —
`docker ps` should show `redshift-mcp-server` as `healthy`. The connector entry in
Desktop is static config; nothing there detects whether the container behind
it is up.

### Current limitation: no auth on the container

The container has no authentication in front of it yet. It binds `0.0.0.0`
inside the container, but only `-p 8000:8000` on your machine exposes it —
don't expose this port beyond localhost as-is. Auth (and TLS, and the
IAM-task-role wiring) for the shared ECS deployment is a separate, later piece
of work.
