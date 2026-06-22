from __future__ import annotations

import uvicorn

from generator_api.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "generator_api.app:app",
        host=settings.generator_host,
        port=settings.generator_port,
        workers=1,
    )


if __name__ == "__main__":
    main()
