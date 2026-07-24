# Redshift MCP Server (HTTP)

![Python](https://img.shields.io/badge/Python-3.13_|_3.12-4B8BBE.svg?style=flat&logo=python&logoColor=FFD43B&labelColor=306998)
[![uv](https://img.shields.io/badge/astral/uv-261230?style=flat&logo=uv&logoColor=DE5FE9&labelColor=261230)](https://docs.astral.sh/uv/getting-started/installation/)
[![Docker](https://img.shields.io/badge/Docker-329DEE?style=flat&logo=docker&logoColor=white&labelColor=329DEE)](https://docs.docker.com/get-docker/)
[![AWS Redshift](https://img.shields.io/badge/AWS-Redshift-232F3E?style=flat&logo=amazonredshift&logoColor=8C4FFF&labelColor=232F3E)](https://aws.amazon.com/redshift/)

A Dockerized, HTTP-accessible MCP server wrapping
[`awslabs.redshift-mcp-server`](https://awslabs.github.io/mcp/servers/redshift-mcp-server), so
Claude Desktop (or any MCP client) can query Amazon Redshift clusters and serverless workgroups
over Streamable HTTP, via the Redshift Data API.

## Getting Started

**1.** Install dependencies from `pyproject.toml` and activate the created virtualenv:
```shell
uv sync && source .venv/bin/activate
```

**2.** Export the AWS profile and region to use:
```shell
export AWS_PROFILE=...
export AWS_REGION=us-west-2
```

## Containerization

**1.** Copy the env template and set `AWS_PROFILE` to a profile from `~/.aws/credentials`
(mounted read-only into the container):
```shell
cp .env.example .env
```

**2.** Build and run with Docker Compose:
```shell
docker compose up -d --build
```

**3.** Verify it's up:
```shell
curl -s http://localhost:8000/health
# {"message":"Redshift MCP Server is up!"}
```

> Don't expose this port beyond `localhost` as-is — there's no auth in front of it yet.

## Config Claude Desktop

> Requires [Node.js](https://nodejs.org/) installed (`node`/`npx` on `PATH`) — Claude Desktop
> spawns `npx` directly, so make sure it's visible from a GUI-launched process, not just your
> shell (an issue with nvm/asdf-managed Node installs).

Claude Desktop only launches stdio processes, so [`mcp-remote`](https://github.com/geelen/mcp-remote)
bridges it to the container's HTTP endpoint. Add this to `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json` — merge it in,
don't replace the file):

```json
{
  "mcpServers": {
    "redshift": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.1.38", "http://localhost:8000/mcp", "--allow-http", "--transport", "http-only"]
    }
  }
}
```

Pin the version to `@0.1.38` or later — earlier versions have [CVE-2025-6514](https://security.snyk.io/package/npm/mcp-remote).

Fully quit and restart Claude Desktop (not just close the window), then enable the `redshift`
connector and its tool permissions under **"+" → Manage connectors → redshift**.

## TODO's:
- [x] Wrap `awslabs.redshift-mcp-server` with a Streamable HTTP ASGI app (`mcpserver/http_entrypoint.py`)
- [x] Containerize with a multi-stage `Dockerfile`, run via `docker compose`
- [x] Multi-worker `uvicorn` (+ `uvloop`) support for concurrent queries against the same cluster:database
- [x] Connect to Claude Desktop via `mcp-remote`
- [ ] GitHub actions to push Dockerized image to AWS ECR
- [ ] Run Docker image on AWS ECS
- [ ] Setup TLS for the in ALB front of it — Claude's Custom Connector UI requires `https://`
