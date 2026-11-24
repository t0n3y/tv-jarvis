"""Schlaf-Timer: nach X Minuten leiser werden, dann alles aus."""

import asyncio
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from app import audio_control
from app.plugins import context

ctx = context(__file__)
router = APIRouter()

FADE_SECONDS = 60
FADE_STEPS = 12
MAX_MINUTES = 240
state = {"ends_at": 0.0, "minutes": 0}


def _remaining() -> float:
    return max(0.0, state["ends_at"] - time.time()) if state["ends_at"] else 0.0


def _public() -> dict:
    return {"active": bool(state["ends_at"]), "remaining": round(_remaining()), "minutes": state["minutes"]}


@router.get("/state")
def get_state() -> dict:
    return _public()


@router.post("/start")
async def start(request: Request) -> dict:
    body = await request.json()
    try:
        minutes = int(body.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    if not 1 <= minutes <= MAX_MINUTES:
        raise HTTPException(status_code=400, detail="Zwischen 1 und 240 Minuten")
    state.update(ends_at=time.time() + minutes * 60, minutes=minutes)
    ctx.log.info("Schlaf-Timer: %s Minuten", minutes)
    return _public()


@router.post("/cancel")
def cancel() -> dict:
    state.update(ends_at=0.0, minutes=0)
    return _public()


def _set_volume(percent: int) -> None:
    audio_control._wpctl("set-volume", audio_control.SINK, f"{max(0, percent)}%")


async def _fade_and_power_off() -> None:
    volume = await asyncio.to_thread(audio_control.get_volume)
    start = volume["percent"] if volume else None
    if start:
        for step in range(1, FADE_STEPS + 1):
            if not state["ends_at"]:
                await asyncio.to_thread(_set_volume, start)  # abgebrochen
                return
            await asyncio.to_thread(_set_volume, round(start * (1 - step / FADE_STEPS)))
            await asyncio.sleep(FADE_SECONDS / FADE_STEPS)
    state.update(ends_at=0.0, minutes=0)
    ctx.log.info("Schlaf-Timer: alles aus")
    try:
        await ctx.power(False)
    finally:
        if start:
            await asyncio.to_thread(_set_volume, start)


async def background() -> None:
    while True:
        await asyncio.sleep(2)
        if state["ends_at"] and _remaining() <= FADE_SECONDS:
            await _fade_and_power_off()


def dashboard() -> dict | None:
    if not state["ends_at"]:
        return None
    end = datetime.fromtimestamp(state["ends_at"]).strftime("%H:%M")
    minutes = max(1, round(_remaining() / 60))
    return {"title": "Schlaf-Timer", "meta": f"noch {minutes} min", "items": [{"time": end, "text": "Fernseher geht aus"}]}
