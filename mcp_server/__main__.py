"""Entry point for `python -m mcp_server`.

Runs the FastMCP ASGI app under uvicorn.  All configuration is read from
environment variables / .env via `mcp_server.config.get_settings()`.
"""

from __future__ import annotations

import uvicorn

from mcp_server.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "mcp_server.app:http_app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
