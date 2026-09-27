"""Plattenschrank: Sammlung (Genres/Schraenke, Platten, Lieblingssongs) und
die Suche fuer neue Platten.

Gespeichert in data/vinyl.json; beim ersten Start wird sie aus
app/vinyl_seed.json befuellt (die Platten von wgv-sv.de/platten).

Neue Musik hinzufuegen laeuft ohne API-Keys:
- Album-/Songsuche, Cover und Tracklisten ueber die iTunes Search API
- das passende YouTube-Video je Song ueber die YouTube-Suche ("<Kuenstler>
  <Song> topic" - die "- Topic"-Videos sind die offiziellen Audiospuren und
  lassen sich fast immer einbetten), yt-dlp als Rueckfallebene
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from app.config import ROOT_DIR

logger = logging.getLogger(__name__)

LIBRARY_FILE = ROOT_DIR / "data" / "vinyl.json"
SEED_FILE = Path(__file__).resolve().parent / "vinyl_seed.json"

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"
# Ohne Consent-Cookie leitet YouTube aus der EU auf eine Einwilligungsseite um
YOUTUBE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}
_VIDEO_ID_RE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")
HTTP_TIMEOUT = 10
YOUTUBE_LOOKUP_WORKERS = 4

# Etikettfarben fuer Platten ohne eigene Farbe
LABEL_COLORS = ["#b8452e", "#3b5bdb", "#7a2e3a", "#c9a24a", "#8c6a3f", "#d9480f", "#e0a526", "#2f9e44", "#495057", "#1c7ed6", "#9c36b5", "#0c8599"]

_lock = threading.Lock()


class VinylError(Exception):
    pass


# ---------- Sammlung ----------

def _load() -> dict:
    for path in (LIBRARY_FILE, SEED_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data.setdefault("genres", [])
        data.setdefault("records", [])
        return data
    return {"genres": [], "records": []}


def _save(data: dict) -> None:
    LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIBRARY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LIBRARY_FILE)


def library() -> dict:
    with _lock:
        return _load()


def find_record(record_id: str) -> dict | None:
    return next((r for r in library()["records"] if r["id"] == record_id), None)


def valid_id(value: str | None) -> bool:
    return bool(value) and bool(_ID_RE.match(value))


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "und")).strip("-")
    return (slug or "schrank")[:32]


def add_genre(name: str) -> dict:
    name = name.strip()[:40]
    if not name:
        raise VinylError("Der Schrank braucht einen Namen")
    with _lock:
        data = _load()
        if any(g["name"].lower() == name.lower() for g in data["genres"]):
            raise VinylError(f"Den Schrank „{name}“ gibt es schon")
        base = _slug(name)
        genre_id, n = base, 2
        while any(g["id"] == genre_id for g in data["genres"]):
            genre_id, n = f"{base}-{n}", n + 1
        genre = {"id": genre_id, "name": name}
        data["genres"].append(genre)
        _save(data)
        return genre


def rename_genre(genre_id: str, name: str) -> None:
    name = name.strip()[:40]
    if not name:
        raise VinylError("Der Schrank braucht einen Namen")
    with _lock:
        data = _load()
        genre = next((g for g in data["genres"] if g["id"] == genre_id), None)
        if genre is None:
            raise VinylError("Diesen Schrank gibt es nicht")
        genre["name"] = name
        _save(data)


def delete_genre(genre_id: str) -> None:
    with _lock:
        data = _load()
        if any(r["genre"] == genre_id for r in data["records"]):
            raise VinylError("Der Schrank ist nicht leer – erst die Platten umräumen oder entfernen")
        data["genres"] = [g for g in data["genres"] if g["id"] != genre_id]
        _save(data)


def add_record(record: dict) -> dict:
    """record: album, artist, year, cover, genre, songs=[{title, artist?, youtube?}].
    Songs ohne YouTube-ID werden hier gesucht (dauert ein paar Sekunden)."""
    album = str(record.get("album") or "").strip()[:120]
    artist = str(record.get("artist") or "").strip()[:120]
    songs_in = record.get("songs") or []
    if not album or not artist:
        raise VinylError("Album und Künstler fehlen")
    if not songs_in:
        raise VinylError("Wähle mindestens einen Song aus")
    genre_id = record.get("genre")
    if genre_id not in {g["id"] for g in library()["genres"]}:
        raise VinylError("Bitte einen Schrank auswählen")

    songs = [
        {
            "title": str(s.get("title") or "").strip()[:160],
            "artist": (str(s["artist"]).strip()[:160] if s.get("artist") and s.get("artist") != artist else None),
            "youtube": s.get("youtube"),
        }
        for s in songs_in[:40]
        if str(s.get("title") or "").strip()
    ]
    missing = [s for s in songs if not s["youtube"]]
    with ThreadPoolExecutor(max_workers=YOUTUBE_LOOKUP_WORKERS) as pool:
        ids = pool.map(lambda s: find_youtube_id(s["artist"] or artist, s["title"]), missing)
        for song, video_id in zip(missing, ids):
            song["youtube"] = video_id
    for song in songs:
        if song["artist"] is None:
            del song["artist"]

    year = record.get("year")
    entry = {
        "id": uuid.uuid4().hex[:10],
        "album": album,
        "artist": artist,
        "year": int(year) if str(year or "").isdigit() else None,
        "cover": record.get("cover") if str(record.get("cover") or "").startswith("https://") else None,
        "color": LABEL_COLORS[sum(map(ord, album + artist)) % len(LABEL_COLORS)],
        "genre": genre_id,
        "songs": songs,
    }
    with _lock:
        data = _load()
        data["records"].append(entry)
        _save(data)
    return entry


def update_record(record_id: str, changes: dict) -> dict:
    with _lock:
        data = _load()
        record = next((r for r in data["records"] if r["id"] == record_id), None)
        if record is None:
            raise VinylError("Diese Platte gibt es nicht")
        if "genre" in changes:
            if changes["genre"] not in {g["id"] for g in data["genres"]}:
                raise VinylError("Diesen Schrank gibt es nicht")
            record["genre"] = changes["genre"]
        if "remove_song" in changes:
            index = int(changes["remove_song"])
            if 0 <= index < len(record["songs"]) and len(record["songs"]) > 1:
                record["songs"].pop(index)
        _save(data)
        return record


def delete_record(record_id: str) -> None:
    with _lock:
        data = _load()
        data["records"] = [r for r in data["records"] if r["id"] != record_id]
        _save(data)


# ---------- Suche: iTunes (Alben, Songs, Cover) ----------

def _artwork(url: str | None) -> str | None:
    return url.replace("100x100bb", "600x600bb") if url else None


def _itunes(url: str, params: dict) -> list[dict]:
    try:
        resp = requests.get(url, params={**params, "country": "DE"}, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        raise VinylError("Die Musiksuche ist gerade nicht erreichbar") from exc


def search(term: str, kind: str) -> list[dict]:
    """kind "album": Alben; kind "song": einzelne Songs (mit ihrem Album)."""
    term = term.strip()
    if not term:
        return []
    entity = "song" if kind == "song" else "album"
    results = _itunes(ITUNES_SEARCH_URL, {"term": term, "entity": entity, "limit": 24})
    items = []
    for r in results:
        item = {
            "collection_id": r.get("collectionId"),
            "album": r.get("collectionName") or "",
            "artist": r.get("artistName") or "",
            "year": (r.get("releaseDate") or "")[:4] or None,
            "cover": _artwork(r.get("artworkUrl100")),
            "track_count": r.get("trackCount"),
        }
        if entity == "song":
            item["song"] = {"title": r.get("trackName") or "", "artist": r.get("artistName") or ""}
        items.append(item)
    return items


def album_tracks(collection_id: int) -> dict:
    results = _itunes(ITUNES_LOOKUP_URL, {"id": collection_id, "entity": "song"})
    if not results:
        raise VinylError("Album nicht gefunden")
    album = results[0]
    tracks = sorted(
        (r for r in results[1:] if r.get("wrapperType") == "track"),
        key=lambda r: (r.get("discNumber") or 1, r.get("trackNumber") or 0),
    )
    return {
        "collection_id": collection_id,
        "album": album.get("collectionName") or "",
        "artist": album.get("artistName") or "",
        "year": (album.get("releaseDate") or "")[:4] or None,
        "cover": _artwork(album.get("artworkUrl100")),
        "tracks": [
            {
                "title": t.get("trackName") or "",
                "artist": t.get("artistName") or "",
                "seconds": round((t.get("trackTimeMillis") or 0) / 1000),
            }
            for t in tracks
        ],
    }


# ---------- Suche: YouTube-Video je Song ----------

def _youtube_search_page(query: str) -> str | None:
    try:
        # sp=EgIQAQ%3D%3D: nur Videos (keine Playlists/Kanaele)
        resp = requests.get(
            YOUTUBE_SEARCH_URL,
            params={"search_query": query, "sp": "EgIQAQ=="},
            headers=YOUTUBE_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("YouTube-Suche fehlgeschlagen (%s)", exc)
        return None
    match = _VIDEO_ID_RE.search(resp.text)
    return match.group(1) if match else None


def _youtube_search_ytdlp(query: str) -> str | None:
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "id", f"ytsearch1:{query}"],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.warning("yt-dlp-Suche fehlgeschlagen (%s)", exc)
        return None
    video_id = result.stdout.strip().splitlines()[:1]
    return video_id[0] if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id[0]) else None


def find_youtube_id(artist: str, title: str) -> str | None:
    query = f"{artist} {title} topic"
    return _youtube_search_page(query) or _youtube_search_ytdlp(query)
