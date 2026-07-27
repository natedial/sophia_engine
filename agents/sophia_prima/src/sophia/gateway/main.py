"""CLI entrypoint for running the Sophia gateway daemon."""

from __future__ import annotations

import uvicorn

from sophia.config import get_settings
from sophia.gateway.app import create_app


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(),
        host=settings.web_host,
        port=settings.web_port,
    )


if __name__ == "__main__":
    main()
