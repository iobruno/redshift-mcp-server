"""Streamable HTTP entrypoint for awslabs.redshift-mcp-server.

The upstream package (awslabs/redshift_mcp_server/server.py) only exposes a
stdio entrypoint (`main()` is a bare `mcp.run()`). The underlying `mcp` SDK's
FastMCP already supports Streamable HTTP end-to-end -- this module just flips
the relevant settings on the same `mcp` instance and runs it that way, so the
tool definitions, SQL guard, etc. are all reused unchanged.
"""

from os import getenv

from awslabs.redshift_mcp_server.server import mcp
from mcp.server.transport_security import TransportSecuritySettings


def main():
    """Configure the shared `mcp` instance for Streamable HTTP and run it.

    Stateless: no Mcp-Session-Id to pin, so multiple replicas can sit behind
    a load balancer with no sticky sessions required.

    FastMCP auto-enables DNS-rebinding protection with a loopback-only
    allowlist (127.0.0.1/localhost/::1) whenever `host` defaults to
    127.0.0.1, which is what upstream's FastMCP(...) call does. Since we
    rebind to 0.0.0.0 for container use, that allowlist would reject every
    request's Host header. Disable it explicitly.
    """
    mcp.settings.host = getenv("REDSHIFT_MCP_LISTENER", "0.0.0.0")
    mcp.settings.port = int(getenv("REDSHIFT_MCP_PORT", "8000"))
    mcp.settings.stateless_http = True
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
