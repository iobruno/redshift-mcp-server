# Builder stage
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_COMPILE_BYTECODE=1 \
    uv export --frozen --no-dev --no-hashes -o requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt

COPY mcpserver/ ./mcpserver/

# Runner stage
FROM python:3.13-slim AS runner

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app /app

EXPOSE 8000

# Shell-form `CMD` (not exec-form) so $REDSHIFT_MCP_PORT/$REDSHIFT_MCP_WORKERS
# expand at container start -- `exec` in front makes uvicorn replace the shell
# as PID 1, so it still receives SIGTERM directly on `docker stop`/ECS task
# stop instead of the shell swallowing it.
ENTRYPOINT exec uvicorn mcpserver.server_http:app --host 0.0.0.0 --port "${REDSHIFT_MCP_PORT:-8000}" --workers "${REDSHIFT_MCP_WORKERS:-4}" --loop uvloop