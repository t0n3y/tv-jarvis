"""Upload von Filmen/Serien auf die Jellyfin-Platte (ueber die Fernbedienung).

Jellyfin selbst kann keine Dateien annehmen - ohne das hier muesste die
Platte zum Befuellen jedes Mal abgezogen werden. Filme sind schnell mehrere
GB gross, deshalb in Stuecken und fortsetzbar:

1. start:  Ziel festlegen (Bibliothek + Titel/Serie), liefert eine Upload-ID.
           Dieselbe Datei (Name+Groesse+Aenderungsdatum) an dasselbe Ziel
           setzt einen abgebrochenen Upload fort, statt neu zu beginnen.
2. append: Stueck fuer Stueck an eine versteckte .part-Datei im Zielordner
           anhaengen (liegt auf derselben Platte -> am Ende nur umbenennen).
3. finish: umbenennen, Jellyfin die Bibliothek neu einlesen lassen und
           pruefen, ob der Fernseher das Format direkt abspielen kann.

Ablage so, wie Jellyfin sie am zuverlaessigsten erkennt:
  Filme:  <Filme>/<Titel (Jahr)>.<ext>     (wie die vorhandenen Filme flach)
  Serien: <Serien>/<Serie>/Staffel NN/<Originalname>  (SxxEyy im Namen!)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from app import jellyfin_client
from app.config import ROOT_DIR, Config

logger = logging.getLogger(__name__)

STATE_DIR = ROOT_DIR / "data" / "uploads"
FFPROBE = "/usr/lib/jellyfin-ffmpeg/ffprobe"
MAX_CHUNK_BYTES = 32 * 1024 * 1024
# Etwas Luft lassen, damit die Platte nie randvoll laeuft
FREE_SPACE_RESERVE_BYTES = 2 * 1024**3
STALE_SECONDS = 7 * 24 * 3600
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".ts", ".m2ts", ".wmv", ".mpg", ".mpeg"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_lock = threading.Lock()


class UploadError(Exception):
    pass


# ---------- Ziele ----------

def targets(cfg: Config) -> list[dict]:
    """Die Jellyfin-Bibliotheken fuer Filme und Serien samt Ordner."""
    folders = jellyfin_client._request(cfg, "GET", "/Library/VirtualFolders").json()
    result = []
    for folder in folders:
        kind = folder.get("CollectionType")
        if kind in ("movies", "tvshows") and folder.get("Locations"):
            result.append({
                "id": folder.get("ItemId"),
                "name": folder.get("Name"),
                "kind": kind,
                "path": folder["Locations"][0],
            })
    return result


def free_bytes(cfg: Config) -> int | None:
    found = targets(cfg)
    return shutil.disk_usage(found[0]["path"]).free if found else None


def _clean(name: str, fallback: str = "") -> str:
    name = _UNSAFE.sub(" ", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:150] or fallback


def _final_path(target: dict, body: dict, filename: str) -> Path:
    base = Path(target["path"])
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS:
        raise UploadError(f"„{filename}“ ist keine Videodatei")
    if target["kind"] == "movies":
        title = _clean(body.get("title"))
        if not title:
            raise UploadError("Bitte einen Filmtitel angeben")
        year = str(body.get("year") or "").strip()
        name = f"{title} ({year})" if re.fullmatch(r"(19|20)\d\d", year) else title
        return base / f"{name}{ext}"
    series = _clean(body.get("series"))
    if not series:
        raise UploadError("Bitte den Namen der Serie angeben")
    season = int(body.get("season") or 1)
    if not 0 <= season <= 99:
        raise UploadError("Staffel muss zwischen 0 und 99 liegen")
    return base / series / f"Staffel {season:02d}" / _clean(filename, f"Folge{ext}")


# ---------- Upload-Zustand (data/uploads/<id>.json) ----------

def _meta_path(upload_id: str) -> Path:
    if not _ID_RE.match(upload_id or ""):
        raise UploadError("Unbekannter Upload")
    return STATE_DIR / f"{upload_id}.json"


def _load(upload_id: str) -> dict:
    try:
        return json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UploadError("Dieser Upload ist abgelaufen – bitte die Datei neu auswählen") from exc


def _save(meta: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _meta_path(meta["id"]).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _received(meta: dict) -> int:
    try:
        return Path(meta["part"]).stat().st_size
    except OSError:
        return 0


def _cleanup_stale() -> None:
    if not STATE_DIR.exists():
        return
    for path in STATE_DIR.glob("*.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - meta.get("updated", 0) > STALE_SECONDS:
                Path(meta["part"]).unlink(missing_ok=True)
                path.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            path.unlink(missing_ok=True)


def start(cfg: Config, body: dict) -> dict:
    filename = str(body.get("filename") or "")
    size = int(body.get("size") or 0)
    if size <= 0:
        raise UploadError("Die Datei ist leer")
    target = next((t for t in targets(cfg) if t["id"] == body.get("target")), None)
    if target is None:
        raise UploadError("Bitte „Film“ oder „Serie“ wählen")
    final = _final_path(target, body, filename)
    fingerprint = f"{filename}|{size}|{body.get('modified') or ''}"

    with _lock:
        _cleanup_stale()
        # Abgebrochenen Upload derselben Datei an dasselbe Ziel fortsetzen
        for path in STATE_DIR.glob("*.json") if STATE_DIR.exists() else []:
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("fingerprint") == fingerprint and meta.get("final") == str(final):
                return {"id": meta["id"], "received": _received(meta), "size": size, "name": final.name}

        if final.exists():
            raise UploadError(f"„{final.name}“ gibt es in {target['name']} schon")
        final.parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(final.parent).free
        if size > free - FREE_SPACE_RESERVE_BYTES:
            raise UploadError(f"Nicht genug Platz auf der Platte (frei: {free / 1024**3:.1f} GB)")
        upload_id = uuid.uuid4().hex
        meta = {
            "id": upload_id,
            "fingerprint": fingerprint,
            "final": str(final),
            # versteckt + .part: Jellyfin ignoriert die halbe Datei beim Scannen
            "part": str(final.parent / f".jarvis-upload-{upload_id}.part"),
            "size": size,
            "target_id": target["id"],
            "updated": time.time(),
        }
        Path(meta["part"]).touch()
        _save(meta)
    logger.info("Upload gestartet: %s (%.1f MB)", final, size / 1024**2)
    return {"id": upload_id, "received": 0, "size": size, "name": final.name}


def append(upload_id: str, offset: int, chunk: bytes) -> int:
    """Haengt ein Stueck an. Passt offset nicht (Stueck doppelt oder
    verloren), wird nichts geschrieben - der Client macht ab dem gemeldeten
    Stand weiter."""
    if len(chunk) > MAX_CHUNK_BYTES:
        raise UploadError("Stück zu groß")
    meta = _load(upload_id)
    received = _received(meta)
    if offset != received:
        return received
    if received + len(chunk) > meta["size"]:
        raise UploadError("Mehr Daten als angekündigt")
    with open(meta["part"], "ab") as f:
        f.write(chunk)
    meta["updated"] = time.time()
    _save(meta)
    return received + len(chunk)


def _probe(path: Path) -> str | None:
    """Warnung, wenn der Fernseher das Video nicht direkt abspielen kann
    (Direct Play, siehe jellyfin_client)."""
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    try:
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    video = next((s["codec_name"] for s in streams if s.get("codec_type") == "video"), None)
    audios = [s["codec_name"] for s in streams if s.get("codec_type") == "audio"]
    if video and video not in jellyfin_client.PLAYABLE_VIDEO_CODECS:
        return f"Das Videoformat {video.upper()} kann der Fernseher nicht direkt abspielen (andere Jellyfin-Apps schon)."
    if audios and not any(a in jellyfin_client.PLAYABLE_AUDIO_CODECS for a in audios):
        return f"Die Tonspur ({audios[0].upper()}) kann der Fernseher nicht direkt abspielen (andere Jellyfin-Apps schon)."
    return None


def finish(cfg: Config, upload_id: str) -> dict:
    meta = _load(upload_id)
    received = _received(meta)
    if received != meta["size"]:
        raise UploadError(f"Upload unvollständig ({received} von {meta['size']} Bytes)")
    final = Path(meta["final"])
    with _lock:
        if final.exists():
            raise UploadError(f"„{final.name}“ gibt es schon")
        Path(meta["part"]).rename(final)
        _meta_path(upload_id).unlink(missing_ok=True)
    logger.info("Upload fertig: %s", final)
    try:
        jellyfin_client._request(cfg, "POST", f"/Items/{meta['target_id']}/Refresh", params={"Recursive": "true"})
    except jellyfin_client.JellyfinError as exc:
        logger.warning("Jellyfin-Bibliothek nicht aktualisiert: %s", exc)
    return {"name": final.name, "warning": _probe(final)}


def cancel(upload_id: str) -> None:
    try:
        meta = _load(upload_id)
    except UploadError:
        return
    Path(meta["part"]).unlink(missing_ok=True)
    _meta_path(upload_id).unlink(missing_ok=True)
