"""Waehlt die aktive ToDo-Quelle anhand von config.yaml (todos.provider)."""

from __future__ import annotations

from app.config import Config
from app.sources import todos_icloud_shortcut, todos_notion


def get_todos(cfg: Config) -> list[str]:
    if cfg.todos.provider == "notion":
        return todos_notion.get_todos(cfg)
    return todos_icloud_shortcut.get_todos(cfg)
