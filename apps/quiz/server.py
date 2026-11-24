"""Quiz: Fragen auf dem Fernseher, Antworten von den Handys der Mitspieler.

Gastgeber (Fernbedienung, mit Passwort): /api/apps/quiz/...
Fernseher (tv.html, vom Pi selbst):      /api/apps/quiz/tv
Mitspieler (play.html, OHNE Passwort):   /api/apps/quiz/public/...
Die Fragen liegen in _fragen.json (wird nie ausgeliefert) und optional in
data/apps/quiz/fragen.json (eigene Fragen)."""

import asyncio
import json
import random
import secrets
import time

from fastapi import APIRouter, HTTPException, Request

from app.plugins import context

ctx = context(__file__)
router = APIRouter()
public_router = APIRouter()

QUESTION_SECONDS = 20
REVEAL_SECONDS = 8
MAX_PLAYERS = 12
ROUND_CHOICES = (5, 10, 15, 20)
game: dict | None = None
_task: asyncio.Task | None = None


def _pool() -> list[dict]:
    questions = json.loads((ctx.dir / "_fragen.json").read_text(encoding="utf-8"))
    own = ctx.load("fragen", [])
    if isinstance(own, list):
        questions += [q for q in own if isinstance(q, dict) and q.get("q") and len(q.get("a") or []) >= 2]
    return questions


def _prepare(rounds: int) -> list[dict]:
    chosen = random.sample(_pool(), k=min(rounds, len(_pool())))
    prepared = []
    for item in chosen:
        answers = [str(a) for a in item["a"][:4]]
        correct = answers[0]
        random.shuffle(answers)
        prepared.append({"q": item["q"], "cat": item.get("cat", ""), "answers": answers, "correct": answers.index(correct)})
    return prepared


def _ranking() -> list[dict]:
    players = sorted(game["players"].values(), key=lambda p: (-p["score"], p["joined"]))
    return [{"name": p["name"], "score": p["score"], "gained": p.get("gained", 0)} for p in players]


def _question_public(include_correct: bool) -> dict | None:
    if game["phase"] not in ("question", "reveal"):
        return None
    q = game["questions"][game["index"]]
    data = {"text": q["q"], "cat": q["cat"], "answers": q["answers"], "number": game["index"] + 1, "total": len(game["questions"])}
    if include_correct:
        data["correct"] = q["correct"]
        counts = [0] * len(q["answers"])
        for player in game["players"].values():
            if player.get("answer") is not None:
                counts[player["answer"]] += 1
        data["counts"] = counts
    return data


def _common() -> dict:
    remaining = max(0.0, game["ends_at"] - time.time()) if game["phase"] == "question" else 0
    return {
        "code": game["code"],
        "phase": game["phase"],
        "remaining": round(remaining, 1),
        "seconds": QUESTION_SECONDS,
        "answered": sum(1 for p in game["players"].values() if p.get("answer") is not None),
        "players": [p["name"] for p in game["players"].values()],
        "ranking": _ranking(),
    }


async def _run() -> None:
    """Spielablauf: Frage (20 s oder bis alle geantwortet haben) -> Aufloesung."""
    for index in range(len(game["questions"])):
        game.update(index=index, phase="question", started_at=time.time(), ends_at=time.time() + QUESTION_SECONDS, skip=False)
        for player in game["players"].values():
            player.update(answer=None, gained=0)
        while time.time() < game["ends_at"] and not game["skip"]:
            if game["players"] and all(p.get("answer") is not None for p in game["players"].values()):
                break
            await asyncio.sleep(0.25)
        correct = game["questions"][index]["correct"]
        for player in game["players"].values():
            if player.get("answer") == correct:
                speed = max(0.0, 1 - (player["answered_at"] - game["started_at"]) / QUESTION_SECONDS)
                player["gained"] = 500 + round(500 * speed)
                player["score"] += player["gained"]
        game.update(phase="reveal", skip=False)
        reveal_end = time.time() + REVEAL_SECONDS
        while time.time() < reveal_end and not game["skip"]:
            await asyncio.sleep(0.25)
    game["phase"] = "final"


# ---------- Gastgeber (Fernbedienung) ----------

@router.post("/new")
async def new_game(request: Request) -> dict:
    global game, _task
    body = await request.json()
    rounds = int(body.get("rounds") or 10)
    if rounds not in ROUND_CHOICES:
        rounds = 10
    origin = str(body.get("origin") or "").rstrip("/")
    if not origin.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Adresse fehlt")
    if _task and not _task.done():
        _task.cancel()
    game = {
        "code": f"{secrets.randbelow(9000) + 1000}",
        "phase": "lobby",
        "players": {},
        "questions": await asyncio.to_thread(_prepare, rounds),
        "index": 0,
        "ends_at": 0.0,
        "join_url": "",
        "skip": False,
    }
    game["join_url"] = f"{origin}/apps/quiz/play.html?c={game['code']}"
    await ctx.show_on_tv("tv.html")
    return host_state()


@router.get("/state")
def host_state() -> dict:
    if not game:
        return {"phase": "none"}
    return {**_common(), "join_url": game["join_url"], "question": _question_public(game["phase"] == "reveal")}


@router.post("/start")
async def start() -> dict:
    global _task
    if not game or game["phase"] != "lobby":
        raise HTTPException(status_code=409, detail="Kein Spiel in der Warteschlange")
    if not game["players"]:
        raise HTTPException(status_code=400, detail="Noch niemand ist beigetreten")
    _task = asyncio.get_running_loop().create_task(_run())
    return {"ok": True}


@router.post("/skip")
def skip() -> dict:
    if game:
        game["skip"] = True
    return {"ok": True}


@router.post("/end")
async def end() -> dict:
    global game
    if _task and not _task.done():
        _task.cancel()
    game = None
    await ctx.close_tv()
    return {"ok": True}


@router.get("/tv")
def tv_state() -> dict:
    """Fuer tv.html (laeuft auf dem Pi, darf ohne Passwort)."""
    return host_state()


# ---------- Mitspieler (ohne Passwort) ----------

def _player(token: str) -> dict:
    if not game or token not in game["players"]:
        raise HTTPException(status_code=404, detail="Nicht (mehr) im Spiel")
    return game["players"][token]


@public_router.post("/join")
async def join(request: Request) -> dict:
    body = await request.json()
    if not game or str(body.get("code") or "").strip() != game["code"]:
        raise HTTPException(status_code=404, detail="Kein Spiel mit diesem Code")
    if game["phase"] == "final":
        raise HTTPException(status_code=409, detail="Das Spiel ist schon vorbei")
    name = " ".join(str(body.get("name") or "").split())[:16]
    if not name:
        raise HTTPException(status_code=400, detail="Bitte einen Namen eingeben")
    if any(p["name"].lower() == name.lower() for p in game["players"].values()):
        raise HTTPException(status_code=409, detail="Den Namen gibt es schon")
    if len(game["players"]) >= MAX_PLAYERS:
        raise HTTPException(status_code=409, detail="Das Spiel ist voll")
    token = secrets.token_urlsafe(12)
    game["players"][token] = {"name": name, "score": 0, "answer": None, "answered_at": 0.0, "gained": 0, "joined": time.time()}
    return {"token": token, "name": name}


@public_router.get("/state")
def player_state(token: str = "") -> dict:
    if not game:
        return {"phase": "none"}
    player = _player(token)
    ranking = _ranking()
    rank = next((i + 1 for i, p in enumerate(ranking) if p["name"] == player["name"]), None)
    return {
        **{k: v for k, v in _common().items() if k in ("phase", "remaining", "seconds")},
        "name": player["name"],
        "score": player["score"],
        "rank": rank,
        "players": len(game["players"]),
        "answer": player.get("answer"),
        "gained": player.get("gained", 0),
        "question": _question_public(game["phase"] == "reveal"),
    }


@public_router.post("/answer")
async def answer(request: Request) -> dict:
    body = await request.json()
    player = _player(str(body.get("token") or ""))
    if game["phase"] != "question" or time.time() > game["ends_at"]:
        raise HTTPException(status_code=409, detail="Gerade keine Frage offen")
    if player.get("answer") is not None:
        raise HTTPException(status_code=409, detail="Du hast schon geantwortet")
    choice = int(body.get("choice"))
    if not 0 <= choice < len(game["questions"][game["index"]]["answers"]):
        raise HTTPException(status_code=400, detail="Ungültige Antwort")
    player.update(answer=choice, answered_at=time.time())
    return {"ok": True}


def test() -> str:
    return f"{len(_pool())} Fragen bereit"
