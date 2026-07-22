"""Liveness route for ALBs and `docker healthcheck`."""

from awslabs.redshift_mcp_server.server import mcp
from starlette.responses import JSONResponse


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):  # ruff: ignore[unused-async] -- custom_route requires an async handler
    """Liveness probe for ALBs and `docker healthcheck`.

    ALBs (and `docker healthcheck`) can't probe /mcp directly -- it requires
    a full MCP initialize handshake, not a plain GET. This route is a
    trivial liveness check instead, added via the SDK's supported
    custom_route hook.
    """
    return JSONResponse({"message": "Redshift MCP Server is up!"}, status_code=200)
