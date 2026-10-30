"""Sprachschach auf dem Fernseher: chess.com im TV-Browser, darueber die
grosse Anzeige der Brettstimme-Erweiterung (extensions/brettstimme).

- Partien startet die Fernbedienung (Bot oder online, mit deinem Account).
- Ansagen spricht Jarvis mit seiner Stimme ueber den Fernseher.
- Deine Zuege sprichst du ins Handy; die Erkennung kommt hierher und geht an
  die Erweiterung, die nachfragt und den Zug auf chess.com ausfuehrt.

Die Erweiterung wird nicht als Chrome-Erweiterung geladen, sondern per
DevTools-Protokoll in chess.com eingespielt - gleiche Dateien, gleiches
Verhalten wie am PC. Sie macht keine Zugvorschlaege und rechnet nichts aus.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from app import tts
from app.config import ROOT_DIR, Config
from app.tv_browser import CDPError, browser

logger = logging.getLogger(__name__)

EXTENSION_DIR = ROOT_DIR / "extensions" / "brettstimme" / "src"
EXTENSION_FILES = ["parser.js", "stimme.js", "anzeige.js", "main.js"]
BOTS_FILE = ROOT_DIR / "app" / "chess_bots_seed.json"
BOT_IMAGE_PREFIXES = {
    "U:": "https://images.chesscomfiles.com/uploads/v1/user/",
    "A:": "https://assets-bots.chess.com/image/",
}
GROUP_NAMES = {
    "The Cryptids": "Kryptiden",
    "New to Chess": "Neu im Schach",
    "Beginner": "Anfänger",
    "Intermediate": "Mittelstufe",
    "Advanced": "Fortgeschritten",
    "Master": "Meister",
    "Adaptive": "Passt sich an",
    "Athletes": "Sportler",
    "Musicians": "Musiker",
    "Creators": "Creator",
    "Top Players": "Top-Spieler",
    "Personalities": "Persönlichkeiten",
    "Visualization": "Blindschach",
}
ONLINE_TIMES = [(1, 0), (1, 1), (2, 1), (3, 0), (3, 2), (5, 0), (10, 0), (10, 5), (15, 10), (30, 0)]
BOT_TIMES = [None, (10, 0), (15, 10), (30, 0)]

state: dict = {
    "mode": None,        # None | "bot" | "online"
    "label": "",         # z.B. "Elani (400)" oder "10 min online"
    "starting": False,
    "error": None,
    "status": {},        # letzter Stand der Erweiterung (Phase, Hinweis, ...)
    "heard": "",         # zuletzt vom Handy gehoert
}

_speaker: tts.Speaker | None = None
_cfg: Config | None = None


def bots() -> list[dict]:
    groups = json.loads(BOTS_FILE.read_text(encoding="utf-8"))
    result = []
    for group in groups:
        items = []
        for name, rating, image in group["bots"]:
            for short, prefix in BOT_IMAGE_PREFIXES.items():
                if image.startswith(short):
                    image = prefix + image[len(short):]
            items.append({"name": name, "rating": rating, "image": image})
        result.append({"group": group["group"], "label": GROUP_NAMES.get(group["group"], group["group"]), "bots": items})
    return result


def public_state() -> dict:
    from app import tv_browser

    return {
        **state,
        "browser_open": tv_browser.is_running(),
        "url": browser.url,
        "online_times": [f"{b}|{i}" for b, i in ONLINE_TIMES],
    }


# ---------- Bruecke zur Erweiterung ----------


def setup(cfg: Config) -> None:
    """Einmal beim Start des Dienstes: Ereignisse des TV-Browsers abonnieren."""
    global _cfg
    _cfg = cfg
    browser.on("Runtime.bindingCalled", _on_binding)
    browser.on("Page.loadEventFired", _on_load)
    browser.on_connect(_inject_if_chess)


def _speaker_for() -> tts.Speaker:
    global _speaker
    if _speaker is None:
        _speaker = tts.Speaker(_cfg)
    return _speaker


async def _on_binding(params: dict) -> None:
    if params.get("name") != "jarvisBridge":
        return
    try:
        msg = json.loads(params.get("payload") or "{}")
    except ValueError:
        return
    kind = msg.get("type")
    if kind == "status":
        msg.pop("type", None)
        state["status"] = msg
    elif kind == "sprich":
        await asyncio.to_thread(_speaker_for().say, str(msg.get("text", "")), int(msg.get("mal") or 1))
        with contextlib.suppress(CDPError):
            await browser.evaluate(f"window.__jarvisChess && window.__jarvisChess.fertig({int(msg.get('id', 0))})")
    elif kind == "verstummen":
        _speaker_for().stop()


async def _on_load(_params: dict) -> None:
    await _inject_if_chess()


async def _inject_if_chess() -> None:
    if not state["mode"]:
        return
    with contextlib.suppress(CDPError):
        await inject()


async def inject() -> bool:
    """Erweiterung in die offene chess.com-Seite einspielen (einmal pro Seite)."""
    info = await browser.page_info()
    if "chess.com" not in info["url"]:
        return False
    # Cookie-Hinweis von chess.com: nur notwendige Cookies (sonst liegt er
    # ueber dem Brett)
    await browser.evaluate("document.querySelector('#onetrust-reject-all-handler')?.click()")
    loaded = await browser.evaluate("!!window.__brettstimmeGeladen")
    if not loaded:
        for name in EXTENSION_FILES:
            source = (EXTENSION_DIR / name).read_text(encoding="utf-8")
            await browser.evaluate(source)
        logger.info("Brettstimme in %s eingespielt", info["url"])
    return True


async def _activate_when_ready() -> None:
    """Sobald ein Brett mit Partie da ist: Anzeige oeffnen und loslegen."""
    for _ in range(240):  # bis zu 2 Minuten (Online-Gegnersuche)
        if not state["mode"]:
            return
        with contextlib.suppress(CDPError):
            await inject()
            ready = await browser.evaluate(
                "(() => { const b = [...document.querySelectorAll('wc-chess-board, chess-board')].find(x => x.game);"
                " try { return !!(b && b.game.getPlayingAs()); } catch (e) { return false; } })()"
            )
            if ready:
                await browser.evaluate("Brettstimme.steuer.aktivieren(); Brettstimme.anzeige.oeffnen(); Brettstimme.steuer.status();")
                return
        await asyncio.sleep(0.5)


# ---------- Partien starten ----------

_BOT_SCRIPT = r"""
(async (name, group, color, time) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const until = async (fn, ms = 10000) => { const end = Date.now() + ms; while (Date.now() < end) { const v = fn(); if (v) return v; await sleep(150); } return null; };
  // Auf dem Pi braucht die Bot-Liste von chess.com mitunter 15-20 Sekunden
  if (!await until(() => document.querySelector('.bot-group-accordion-component'), 45000)) return 'Die Bot-Auswahl von chess.com ist nicht zu sehen';
  await sleep(500);
  let li = null;
  const accs = [...document.querySelectorAll('.bot-group-accordion-component')];
  // Zuerst die Gruppe, in der der Bot laut Liste steht
  accs.sort((a, b) => (b.textContent.includes(group) ? 1 : 0) - (a.textContent.includes(group) ? 1 : 0));
  for (const acc of accs) {
    li = acc.querySelector(`.bot-component[data-bot-selection-name="${CSS.escape(name)}"]`);
    if (li) break;
    const toggle = acc.querySelector('.bot-group-accordion-toggleClickArea');
    if (toggle && !toggle.classList.contains('bot-group-accordion-toggleClickAreaExpanded')) {
      toggle.click();
      li = await until(() => acc.querySelector(`.bot-component[data-bot-selection-name="${CSS.escape(name)}"]`), 4000);
      if (li) break;
    }
  }
  if (!li) return `Bot „${name}“ nicht gefunden`;
  li.querySelector('img').click();
  const shown = await until(() => { const n = document.querySelector('.selected-bot-introduction-info .cc-heading-xx-small'); return n && n.textContent.trim() === name; }, 10000);
  if (!shown) return `Bot „${name}“ ließ sich nicht auswählen`;
  const sides = document.querySelectorAll('.play-side-selector-option');
  const index = { w: 0, r: 1, b: 2 }[color];
  if (sides.length === 3 && index !== undefined) { sides[index].click(); await sleep(200); }
  if (time) {
    const [base, inc] = time;
    const button = [...document.querySelectorAll('.time-selector-button-button')].find((b) => {
      const n = (b.textContent.match(/\d+/g) || []).map(Number);
      return n[0] === base && (n[1] || 0) === inc;
    });
    if (button) { button.click(); await sleep(200); }
  } else {
    const none = document.querySelector('.mode-selection-container-no-timer-button');
    if (none) { none.click(); await sleep(200); }
  }
  const play = await until(() => document.querySelector('.bot-selection-cta-button-button'), 10000);
  if (!play) return 'Der Spielen-Knopf fehlt';
  play.click();
  return 'ok';
})
"""

_ONLINE_SCRIPT = r"""
(async (base, inc) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const until = async (fn, ms = 10000) => { const end = Date.now() + ms; while (Date.now() < end) { const v = fn(); if (v) return v; await sleep(150); } return null; };
  const matches = (b) => { const n = (b.textContent.match(/\d+/g) || []).map(Number); return n[0] === base && (n[1] || 0) === inc; };
  const dropdown = await until(() => [...document.querySelectorAll('button.cc-dropdown-button-component')].find((b) => /\d/.test(b.textContent)));
  if (!dropdown) return 'Die Zeitauswahl von chess.com ist nicht zu sehen';
  if (!matches(dropdown)) {
    dropdown.click();
    const option = await until(() => [...document.querySelectorAll('.time-selector-button-button, button')].find((b) => b !== dropdown && /cc-button-secondary/.test(b.className) && matches(b)), 4000);
    if (!option) return `Bedenkzeit ${base}|${inc} gibt es hier nicht`;
    option.click();
    await sleep(400);
  }
  const panel = dropdown.closest('section, .tabs-component, [class*="new-game"], [class*="sidebar"]') || document;
  const start = [...panel.querySelectorAll('button')].find((b) => /cc-button-primary/.test(b.className) && b.offsetParent);
  if (!start) return 'Der Start-Knopf fehlt';
  start.click();
  return 'ok';
})
"""


async def start_bot(cfg: Config, name: str, color: str, time_control: tuple[int, int] | None) -> None:
    found = {b["name"]: (g["group"], b) for g in bots() for b in g["bots"]}
    if name not in found:
        raise ValueError("Unbekannter Bot")
    group, bot = found[name]
    rating = bot["rating"]
    args = ", ".join(json.dumps(v) for v in (name, group, color, list(time_control) if time_control else None))
    await _start(cfg, "bot", f"{name} ({rating})" if rating else name, "https://www.chess.com/play/computer", f"{_BOT_SCRIPT}({args})")


async def start_online(cfg: Config, time_control: tuple[int, int]) -> None:
    if time_control not in ONLINE_TIMES:
        raise ValueError("Diese Bedenkzeit gibt es nicht")
    base, inc = time_control
    label = f"{base} min online" if not inc else f"{base}+{inc} online"
    await _start(cfg, "online", label, "https://www.chess.com/play/online", f"{_ONLINE_SCRIPT}({base}, {inc})")


async def _start(cfg: Config, mode: str, label: str, url: str, script: str) -> None:
    if state["starting"]:
        raise ValueError("Eine Partie wird gerade gestartet")
    state.update(mode=mode, label=label, starting=True, error=None, status={}, heard="")
    asyncio.get_running_loop().run_in_executor(None, _speaker_for().warm_up)
    try:
        await browser.open(cfg, url)
        await browser.navigate(url)
        await _wait_for_url(url)
        await asyncio.sleep(1.5)
        result = await browser.evaluate(script, await_promise=True, timeout=90)
        if result != "ok":
            raise ValueError(result or "chess.com hat nicht reagiert")
        asyncio.create_task(_activate_when_ready())
    except (CDPError, ValueError) as exc:
        state["error"] = str(exc)
        raise ValueError(str(exc)) from exc
    finally:
        state["starting"] = False


async def _wait_for_url(prefix: str) -> None:
    # Nicht auf "complete" warten: Werbung und Tracker halten das auf dem Pi
    # oft ewig auf - bedienbar ist die Seite schon vorher
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        with contextlib.suppress(CDPError):
            ok = await browser.evaluate(f"location.href.startsWith({json.dumps(prefix)}) && document.readyState !== 'loading'")
            if ok:
                return
        await asyncio.sleep(0.4)
    raise ValueError("chess.com lädt nicht")


# ---------- Waehrend der Partie ----------


async def heard(alternatives: list[str]) -> None:
    """Spracherkennung vom Handy (beste Variante zuerst)."""
    alts = [str(a).strip() for a in alternatives if str(a).strip()][:5]
    if not alts:
        return
    state["heard"] = alts[0]
    await browser.evaluate(f"Brettstimme.hoere({json.dumps(alts)})")


async def action(name: str, value=None) -> None:
    scripts = {
        "ja": "Brettstimme.steuer.ja()",
        "nein": "Brettstimme.steuer.nein()",
        "wiederholen": "Brettstimme.steuer.wiederholen()",
        "anzeige": "Brettstimme.anzeige.istOffen() ? Brettstimme.anzeige.schliessen() : Brettstimme.anzeige.oeffnen()",
    }
    if name == "option":
        await browser.evaluate(f"Brettstimme.steuer.option({int(value)})")
    elif name == "tippen":
        state["heard"] = str(value or "")
        await browser.evaluate(f"Brettstimme.steuer.tippe({json.dumps(str(value or ''))})")
    elif name in scripts:
        await browser.evaluate(scripts[name])
    else:
        raise ValueError("Unbekannte Aktion")


async def end() -> None:
    state.update(mode=None, label="", starting=False, error=None, status={}, heard="")
    if _speaker is not None:
        _speaker.stop()
    await browser.close()
