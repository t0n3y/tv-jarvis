"""Server-Teil der App: alles unter /api/apps/pinnwand/...

ctx (siehe app/plugins.py) bietet:
  ctx.settings()            Felder aus app.json, wie im App Store eingetragen
  ctx.secret("NAME")        Geheimnis aus app.json ("secret": "NAME")
  ctx.load(name) / ctx.save(daten, name)   JSON-Speicher in data/apps/pinnwand/
  await ctx.show_on_tv("tv.html") / await ctx.close_tv()
  ctx.say("Text")           mit der Stimme ueber den Fernseher sprechen
  ctx.config                gesamte Konfiguration (Name, Ort, ...)
  ctx.log                   Logger (journalctl -u dashboard.service)
"""

from fastapi import APIRouter, HTTPException, Request

from app.plugins import context

ctx = context(__file__)
router = APIRouter()


@router.get("/message")
def get_message() -> dict:
    data = ctx.load("message", {"text": ""})
    return {"text": data["text"], "signature": ctx.settings().get("signature", "")}


@router.post("/message")
async def set_message(request: Request) -> dict:
    body = await request.json()
    text = str(body.get("text") or "").strip()[:200]
    if not text:
        raise HTTPException(status_code=400, detail="Bitte eine Nachricht eintippen")
    ctx.save({"text": text}, "message")
    ctx.log.info("Neue Nachricht: %s", text)
    return {"ok": True}


def test() -> str:
    """Knopf "Verbindung testen" im App Store (optional)."""
    return f"Läuft - letzte Nachricht: {ctx.load('message', {'text': '–'})['text']}"
