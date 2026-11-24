"""Einkaufsliste: gemeinsame Liste, gespeichert in data/apps/einkaufsliste/items.json."""

import secrets
import threading

from fastapi import APIRouter, HTTPException, Request

from app.plugins import context

ctx = context(__file__)
router = APIRouter()

MAX_ITEMS = 200
_lock = threading.Lock()


def _items() -> list[dict]:
    return ctx.load("items", [])


def _change(fn) -> list[dict]:
    with _lock:
        items = _items()
        items = fn(items)
        ctx.save(items, "items")
        return items


@router.get("/items")
def get_items() -> dict:
    return {"items": _items()}


@router.post("/items")
async def add_items(request: Request) -> dict:
    body = await request.json()
    names = [" ".join(part.split())[:60] for part in str(body.get("text") or "").split(",")]
    names = [name for name in names if name]
    if not names:
        raise HTTPException(status_code=400, detail="Bitte etwas eintippen")

    def add(items: list[dict]) -> list[dict]:
        existing = {item["text"].lower(): item for item in items}
        for name in names:
            if name.lower() in existing:
                existing[name.lower()]["done"] = False  # schon drauf: wieder offen
            else:
                item = {"id": secrets.token_hex(4), "text": name, "done": False}
                items.append(item)
                existing[name.lower()] = item
        if len(items) > MAX_ITEMS:
            raise HTTPException(status_code=400, detail="Die Liste ist voll")
        return items

    return {"items": _change(add)}


@router.post("/items/{item_id}/toggle")
def toggle(item_id: str) -> dict:
    def flip(items: list[dict]) -> list[dict]:
        for item in items:
            if item["id"] == item_id:
                item["done"] = not item["done"]
        return items

    return {"items": _change(flip)}


@router.delete("/items/{item_id}")
def delete(item_id: str) -> dict:
    return {"items": _change(lambda items: [item for item in items if item["id"] != item_id])}


@router.post("/clear-done")
def clear_done() -> dict:
    return {"items": _change(lambda items: [item for item in items if not item["done"]])}


def dashboard() -> dict | None:
    open_items = [item for item in _items() if not item["done"]]
    if not open_items:
        return None
    return {"title": "Einkaufen", "meta": f"{len(open_items)} offen", "items": [{"text": item["text"]} for item in open_items]}
