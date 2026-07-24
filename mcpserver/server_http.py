"""Streamable HTTP entrypoint for awslabs.redshift-mcp-server.

The upstream package (awslabs/redshift_mcp_server/server.py) only exposes a
stdio entrypoint (`main()` is a bare `mcp.run()`). The underlying `mcp` SDK's
FastMCP already supports Streamable HTTP end-to-end -- this module just flips
the relevant settings on the same `mcp` instance and exposes the resulting
ASGI app, so the tool definitions, SQL guard, etc. are all reused unchanged.

Host/port/worker count aren't configured here -- the Dockerfile's `CMD` runs
this module's `app` directly via the `uvicorn` CLI, with `--workers` read
from `REDSHIFT_MCP_WORKERS`. Each worker gets its own independent copy of the
awslabs package's per-`cluster:database` session lock, so concurrent queries
against the *same* target can run one per worker instead of all queuing
behind a single shared lock.
"""

from awslabs.redshift_mcp_server.server import mcp
from mcp.server.transport_security import TransportSecuritySettings

from mcpserver import healthcheck

mcp.settings.stateless_http = True
"""No Mcp-Session-Id to pin, so multiple workers/replicas can sit behind a
load balancer with no sticky sessions required.

Set before `app` is built below -- streamable_http_app() reads these lazily
on first call to construct its StreamableHTTPSessionManager.
"""

mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
"""FastMCP auto-enables DNS-rebinding protection with a loopback-only
allowlist (127.0.0.1/localhost/::1) whenever `host` defaults to 127.0.0.1,
which is what upstream's FastMCP(...) call does. Since we rebind to
0.0.0.0 for container use, that allowlist would reject every request's
Host header. Disable it explicitly.
"""

app = mcp.streamable_http_app()
"""Module-level ASGI app -- referenced by uvicorn as an import string
("mcpserver.server_http:app") so each worker process re-imports it fresh
instead of sharing one already-built app object across processes.
"""
