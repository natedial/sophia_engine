"""CLI entrypoint for running the Sophia Forge API locally."""

from __future__ import annotations

import argparse

from sophia_forge.config import ForgeSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Sophia Forge API service.")
    parser.add_argument("--host", default=None, help="Override bind host")
    parser.add_argument("--port", type=int, default=None, help="Override bind port")
    args = parser.parse_args()

    settings = ForgeSettings()
    host = args.host or settings.bind_host
    port = args.port or settings.bind_port

    import uvicorn

    uvicorn.run(
        "sophia_forge.api.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
