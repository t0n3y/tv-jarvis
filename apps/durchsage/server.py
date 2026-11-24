"""Durchsage: Text vom Handy wird ueber den Fernseher gesprochen."""

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from app import radio
from app.plugins import context

ctx = context(__file__)
router = APIRouter()

DEFAULT_PRESETS = ["Essen ist fertig!", "Kommst du bitte mal?", "Wir fahren in fünf Minuten los.", "Gute Nacht!"]
MAX_HISTORY = 6
_lock = asyncio.Lock()


def _presets() -> list[str]:
    saved = ctx.settings().get("presets")
    return saved if isinstance(saved, list) and saved else DEFAULT_PRESETS


@router.get("/info")
def info() -> dict:
    return {"presets": _presets(), "history": ctx.load("history", []), "tv_on": ctx.tv_is_on()}


@router.post("/say")
async def say(request: Request) -> dict:
    body = await request.json()
    text = " ".join(str(body.get("text") or "").split())[:300]
    if not text:
        raise HTTPException(status_code=400, detail="Bitte etwas eintippen")
    if _lock.locked():
        raise HTTPException(status_code=409, detail="Es läuft gerade schon eine Durchsage")
    async with _lock:
        if not ctx.tv_is_on():
            if not body.get("power_on"):
                raise HTTPException(status_code=409, detail="Der Fernseher ist aus – Schalter „Fernseher dafür einschalten“ antippen")
            await ctx.power(True)
        radio_was_on = await asyncio.to_thread(radio.is_playing)
        if radio_was_on:
            await asyncio.to_thread(radio.stop)
        try:
            await asyncio.to_thread(ctx.say, text)
        finally:
            if radio_was_on:
                await asyncio.to_thread(radio.start, ctx.config)
    history = [entry for entry in ctx.load("history", []) if entry.get("text") != text]
    ctx.save([{"text": text, "at": time.strftime("%H:%M")}, *history][:MAX_HISTORY], "history")
    ctx.log.info("Durchsage: %s", text)
    return {"ok": True}
