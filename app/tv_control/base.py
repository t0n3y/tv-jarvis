from __future__ import annotations

from abc import ABC, abstractmethod


class TVController(ABC):
    @abstractmethod
    def turn_on(self) -> None:
        ...

    @abstractmethod
    def turn_off(self) -> None:
        ...

    @abstractmethod
    def is_on(self) -> bool | None:
        """True/False wenn bekannt, sonst None (nicht jeder Backend kann das abfragen)."""
        ...
