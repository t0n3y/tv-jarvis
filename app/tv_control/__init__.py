from __future__ import annotations

from app.config import Config
from app.tv_control.base import TVController


def get_controller(cfg: Config) -> TVController:
    if cfg.tv_control.backend == "smart_plug":
        from app.tv_control.smart_plug import SmartPlugController
        return SmartPlugController(cfg)

    from app.tv_control.cec import CECController
    return CECController(cfg)
