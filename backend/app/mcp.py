from __future__ import annotations

import httpx

from app.core import settings


def call_tool(name: str, arguments: dict) -> dict:
    if not settings.MCP_URL:
        raise RuntimeError("MCP_URL is not set")
    with httpx.Client(timeout=settings.FETCH_TIMEOUT * 3) as client:
        response = client.post(f"{settings.MCP_URL}/mcp/tools/{name}", json=arguments)
        response.raise_for_status()
        return response.json()
