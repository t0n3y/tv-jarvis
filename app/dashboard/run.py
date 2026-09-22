"""Startet den Dashboard-Server mit Host/Port aus config.yaml.

    python -m app.dashboard.run
"""

from __future__ import annotations

import socket

import uvicorn

from app.config import get_config


def _dual_stack_socket(port: int) -> socket.socket:
    # asyncio setzt bei host="::" IPV6_V6ONLY - der Server waere dann per IPv4
    # nicht mehr erreichbar. Ein selbst gebundener Socket mit V6ONLY=0 nimmt
    # beides an (IPv4-Clients erscheinen als ::ffff:a.b.c.d).
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    return sock


def main() -> None:
    cfg = get_config()
    server = uvicorn.Server(
        uvicorn.Config(
            "app.dashboard.server:app",
            host=cfg.dashboard.host,
            port=cfg.dashboard.port,
            log_level="info",
        )
    )
    if cfg.dashboard.host == "::":
        server.run(sockets=[_dual_stack_socket(cfg.dashboard.port)])
    else:
        server.run()


if __name__ == "__main__":
    main()
