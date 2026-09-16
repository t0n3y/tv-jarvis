"""Startet den Dashboard-Server mit Host/Port aus config.yaml.

    python -m app.dashboard.run
"""

from __future__ import annotations

import uvicorn

from app.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "app.dashboard.server:app",
        host=cfg.dashboard.host,
        port=cfg.dashboard.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
