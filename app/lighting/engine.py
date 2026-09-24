"""Licht-Engine: berechnet BPM-synchrone Effekte fuer mehrere DMX-Scheinwerfer.

Laeuft als Hintergrund-Thread im Dashboard-Dienst (40 Bilder/s) und schreibt
ueber den uDMX-Adapter. Alle Lampen sind gleich gebaut (UKING RGB-Par, 8-Kanal-
Modus) und liegen im 8er-Raster: Lampe 1 auf d001, Lampe 2 auf d009, ... Lampe
8 auf d057. Welche davon wirklich angeschlossen sind, weiss DMX nicht (reine
Einbahnstrasse) - daher stellt man in der Fernbedienung die Anzahl ein, damit
Lauflicht-Effekte keine Luecken fuer fehlende Lampen lassen.

Kanalbelegung (an der echten Lampe ermittelt):
  1 Helligkeit  2 Rot  3 Gruen  4 Blau  5 (ohne Funktion)
  6 Stroboskop  7 Automatikprogramme  8 Programm-Tempo
Die Kanaele 5-8 bleiben auf 0 - alle Effekte rechnet Jarvis selbst, nur so
laufen mehrere Lampen exakt im Takt.
"""

from __future__ import annotations

import colorsys
import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.config import ROOT_DIR
from app.lighting.udmx import UDMX, UDMXError

logger = logging.getLogger(__name__)

STATE_FILE = ROOT_DIR / "data" / "lighting.json"

CHANNELS_PER_FIXTURE = 8
MAX_FIXTURES = 8
FPS = 40
BPM_MIN, BPM_MAX = 40, 220
# Wahrgenommene Helligkeit ist nicht linear: ohne Kurve wirken die unteren
# 50 % des Reglers fast gleich hell und Rampen "springen" am Ende.
GAMMA = 1.8
# Weiche Uebergaenge beim Ein-/Ausschalten und bei Farbwechseln im Standlicht
FADE_SECONDS = 0.15
SAVE_DELAY_SECONDS = 2
RESEND_SECONDS = 1
RETRY_SECONDS = 2

RGB = tuple[float, float, float]


@dataclass
class Frame:
    """Was ein Effekt fuer eine Lampe zu einem Zeitpunkt liefert."""
    level: float        # 0..1, wird mit der Master-Helligkeit multipliziert
    color: RGB | None   # None = die gewaehlte Farbe


@dataclass
class EffectContext:
    beat: float         # fortlaufende Schlaege seit Start (Bruchteil = Position im Schlag)
    index: int          # Lampe 0..n-1
    count: int
    palette: Callable[[int], RGB]


@dataclass
class Effect:
    id: str
    name: str
    group: str          # "static" | "soft" | "hard" | "ramp"
    render: Callable[[EffectContext], Frame]


def _frac(x: float) -> float:
    return x - math.floor(x)


def _cos_pulse(x: float) -> float:
    """0 -> 1 -> 0 ueber eine Periode, weich."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * x)


def _lerp(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))  # type: ignore[return-value]


def _smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def _chase_slots(ctx: EffectContext) -> int:
    # Mit nur einer Lampe wuerde ein Lauflicht dauerhaft leuchten - dann
    # stattdessen jeden zweiten Schlag.
    return max(ctx.count, 2)


# ---------- Effekte ----------
# Soft: weiche, fliessende Bewegungen

def _breathe(ctx: EffectContext) -> Frame:
    return Frame(0.08 + 0.92 * _cos_pulse(ctx.beat / 2), None)


def _wave(ctx: EffectContext) -> Frame:
    return Frame(0.05 + 0.95 * _cos_pulse(ctx.beat / 4 - ctx.index / ctx.count), None)


def _rainbow(ctx: EffectContext) -> Frame:
    hue = ctx.beat / 16 + ctx.index / ctx.count
    return Frame(1.0, colorsys.hsv_to_rgb(_frac(hue), 1, 1))


def _glide(ctx: EffectContext) -> Frame:
    pos = ctx.beat / 4 + ctx.index
    step = math.floor(pos)
    color = _lerp(ctx.palette(step), ctx.palette(step + 1), _smoothstep(_frac(pos)))
    return Frame(1.0, color)


# Hard: harte Wechsel exakt auf dem Schlag

def _flash(ctx: EffectContext) -> Frame:
    return Frame(1.0 if _frac(ctx.beat) < 0.2 else 0.0, None)


def _chase(ctx: EffectContext) -> Frame:
    slots = _chase_slots(ctx)
    return Frame(1.0 if math.floor(ctx.beat) % slots == ctx.index % slots else 0.0, None)


def _jump(ctx: EffectContext) -> Frame:
    return Frame(1.0, ctx.palette(math.floor(ctx.beat) + ctx.index))


def _alternate(ctx: EffectContext) -> Frame:
    return Frame(1.0 if (math.floor(ctx.beat) + ctx.index) % 2 == 0 else 0.0, None)


def _strobe(ctx: EffectContext) -> Frame:
    return Frame(1.0 if _frac(ctx.beat * 4) < 0.3 else 0.0, None)


# Ramp: Helligkeit baut sich auf und bricht auf dem Schlag ab

def _ramp_beat(ctx: EffectContext) -> Frame:
    return Frame(_frac(ctx.beat), None)


def _ramp_bar(ctx: EffectContext) -> Frame:
    return Frame(_frac(ctx.beat / 4), None)


def _ramp_cascade(ctx: EffectContext) -> Frame:
    return Frame(_frac(ctx.beat / 2 - ctx.index / ctx.count), None)


def _ramp_color(ctx: EffectContext) -> Frame:
    return Frame(_frac(ctx.beat), ctx.palette(math.floor(ctx.beat)))


def _buildup(ctx: EffectContext) -> Frame:
    # Wie ein Drop im Club: ueber 4 Takte (16 Schlaege) wird alles heller,
    # die Pulse verdoppeln sich jeden Takt (1, 2, 4, 8 pro Schlag).
    phase = _frac(ctx.beat / 16)
    rate = 2 ** math.floor(phase * 4)
    envelope = 0.25 + 0.75 * phase
    return Frame(envelope * _frac(ctx.beat * rate), None)


EFFECTS: dict[str, Effect] = {
    e.id: e
    for e in [
        Effect("static", "Standlicht", "static", lambda ctx: Frame(1.0, None)),
        Effect("breathe", "Atmen", "soft", _breathe),
        Effect("wave", "Welle", "soft", _wave),
        Effect("rainbow", "Regenbogen", "soft", _rainbow),
        Effect("glide", "Farbgleiten", "soft", _glide),
        Effect("flash", "Beat-Blitz", "hard", _flash),
        Effect("chase", "Lauflicht", "hard", _chase),
        Effect("jump", "Farbsprung", "hard", _jump),
        Effect("alternate", "Wechsler", "hard", _alternate),
        Effect("strobe", "Stroboskop", "hard", _strobe),
        Effect("ramp_beat", "Anstieg", "ramp", _ramp_beat),
        Effect("ramp_bar", "Anstieg lang", "ramp", _ramp_bar),
        Effect("ramp_cascade", "Kaskade", "ramp", _ramp_cascade),
        Effect("ramp_color", "Farbanstieg", "ramp", _ramp_color),
        Effect("buildup", "Build-up", "ramp", _buildup),
    ]
}


def _hex_to_rgb(value: str) -> RGB:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError("Farbe muss #rrggbb sein")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def fixture_address(index: int) -> int:
    return 1 + index * CHANNELS_PER_FIXTURE


class LightEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._dmx = UDMX()
        self._thread: threading.Thread | None = None

        self.on = False
        self.brightness = 80          # 0..100
        self.color: RGB = (1.0, 0.31, 0.0)
        self.effect = "static"
        self.bpm = 120.0
        self.fixtures = 1
        self._load()

        # Takt: beat(t) = origin_beat + (t - origin_time) * bpm / 60
        self._origin_time = time.monotonic()
        self._origin_beat = 0.0

        self._power = 0.0             # 0..1, fuer weiches Ein-/Ausblenden
        self._smoothed: list[list[float]] = [[0.0] * 4 for _ in range(MAX_FIXTURES)]
        self._last_sent: bytes | None = None
        self._last_send_at = 0.0
        self._error: str | None = None
        self._retry_at = 0.0
        self._dirty_at: float | None = None

    # ---------- Zustand ----------

    def _load(self) -> None:
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            self.on = bool(data.get("on", self.on))
            self.brightness = int(data.get("brightness", self.brightness))
            self.color = _hex_to_rgb(data.get("color", _rgb_to_hex(self.color)))
            if data.get("effect") in EFFECTS:
                self.effect = data["effect"]
            self.bpm = float(data.get("bpm", self.bpm))
            self.fixtures = int(data.get("fixtures", self.fixtures))
        except (TypeError, ValueError):
            logger.warning("%s ist beschaedigt - nutze Standardwerte", STATE_FILE)

    def _save(self) -> None:
        data = {
            "on": self.on, "brightness": self.brightness, "color": _rgb_to_hex(self.color),
            "effect": self.effect, "bpm": self.bpm, "fixtures": self.fixtures,
        }
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except OSError as exc:
            logger.warning("Lichtzustand konnte nicht gespeichert werden: %s", exc)

    def _beat(self, now: float) -> float:
        return self._origin_beat + (now - self._origin_time) * self.bpm / 60

    def state(self) -> dict:
        with self._lock:
            return {
                "on": self.on,
                "brightness": self.brightness,
                "color": _rgb_to_hex(self.color),
                "effect": self.effect,
                "bpm": round(self.bpm, 1),
                "fixtures": self.fixtures,
                "addresses": [fixture_address(i) for i in range(self.fixtures)],
                "error": self._error,
            }

    def update(self, changes: dict) -> dict:
        """Uebernimmt Aenderungen aus der Fernbedienung (nur gesetzte Felder).
        tap=True legt den Schlag auf "jetzt" (Tap-Sync)."""
        with self._lock:
            now = time.monotonic()
            if "on" in changes:
                self.on = bool(changes["on"])
            if "brightness" in changes:
                self.brightness = max(0, min(100, int(changes["brightness"])))
            if "color" in changes:
                self.color = _hex_to_rgb(str(changes["color"]))
            if "effect" in changes:
                if changes["effect"] not in EFFECTS:
                    raise ValueError("unbekannter Effekt")
                self.effect = changes["effect"]
            if "fixtures" in changes:
                self.fixtures = max(1, min(MAX_FIXTURES, int(changes["fixtures"])))
            if "bpm" in changes:
                # Position im Takt beibehalten, sonst springt der Effekt beim Regeln
                self._origin_beat = self._beat(now)
                self._origin_time = now
                self.bpm = max(BPM_MIN, min(BPM_MAX, float(changes["bpm"])))
            if changes.get("tap"):
                self._origin_beat = float(round(self._beat(now)))
                self._origin_time = now
            self._dirty_at = now
        self._wake.set()
        return self.state()

    # ---------- Ausgabe ----------

    def _palette(self, step: int) -> RGB:
        """Farbfolge fuer Farbeffekte: startet bei der gewaehlten Farbe und
        dreht in Sechstel-Schritten durch den Farbkreis."""
        hue, _, _ = colorsys.rgb_to_hsv(*self.color)
        return colorsys.hsv_to_rgb(_frac(hue + step / 6), 1, 1)

    def _render(self, now: float, dt: float) -> bytes:
        effect = EFFECTS[self.effect]
        beat = self._beat(now)
        fade = 1 - math.exp(-dt / FADE_SECONDS)
        self._power += ((1.0 if self.on else 0.0) - self._power) * fade
        if not self.on and self._power < 0.002:
            self._power = 0.0
        master = self.brightness / 100 * self._power

        universe = bytearray(CHANNELS_PER_FIXTURE * MAX_FIXTURES)
        for index in range(self.fixtures):
            frame = effect.render(EffectContext(beat, index, self.fixtures, self._palette))
            color = frame.color or self.color
            target = [max(0.0, min(1.0, frame.level)), *color]
            smoothed = self._smoothed[index]
            if effect.group == "static":
                for k in range(4):
                    smoothed[k] += (target[k] - smoothed[k]) * fade
            else:
                smoothed[:] = target
            base = index * CHANNELS_PER_FIXTURE
            universe[base] = round(255 * (smoothed[0] * master) ** GAMMA)
            for k in range(3):
                universe[base + 1 + k] = round(255 * smoothed[1 + k])
        return bytes(universe)

    def _is_idle(self) -> bool:
        """Aus oder Standlicht: nichts zu animieren (Ueberblendung erkennt der
        Aufrufer daran, dass sich das Bild noch aendert)."""
        return not self.on or EFFECTS[self.effect].group == "static"

    def _run(self) -> None:
        last = time.monotonic()
        while True:
            now = time.monotonic()
            # Nach einer Ruhephase (bis 1 s) nicht in einem Schritt ueberblenden
            dt = min(now - last, 2 / FPS)
            last = now
            with self._lock:
                frame = self._render(now, dt)
                idle = self._is_idle()
                save = self._dirty_at is not None and now - self._dirty_at >= SAVE_DELAY_SECONDS
                if save:
                    self._dirty_at = None
            if save:
                self._save()

            # Der uDMX sendet das letzte Bild selbst weiter; regelmaessig neu
            # schicken fuer den Fall, dass er zwischendurch abgesteckt war.
            changed = frame != self._last_sent
            if (changed or now - self._last_send_at >= RESEND_SECONDS) and now >= self._retry_at:
                try:
                    self._dmx.send(1, list(frame))
                    self._last_sent = frame
                    self._last_send_at = now
                    if self._error:
                        logger.info("uDMX wieder erreichbar")
                    self._error = None
                except UDMXError as exc:
                    if str(exc) != self._error:
                        logger.warning("%s", exc)
                    self._error = str(exc)
                    self._retry_at = now + RETRY_SECONDS

            # Standlicht/aus: nichts zu animieren, bis sich etwas aendert
            self._wake.wait(RESEND_SECONDS if idle and not changed else 1 / FPS)
            self._wake.clear()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="light-engine", daemon=True)
            self._thread.start()


_engine: LightEngine | None = None


def get_engine() -> LightEngine:
    global _engine
    if _engine is None:
        _engine = LightEngine()
    return _engine


def effect_catalog() -> list[dict]:
    return [{"id": e.id, "name": e.name, "group": e.group} for e in EFFECTS.values()]
