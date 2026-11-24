"""Comics & PDFs fuer den eigenen Reader (comics.bassbunkerfm.de).

Die Dateien liegen in der Jellyfin-Bibliothek "Comics" (Typ Buecher, also
auch in Jellyfin sichtbar), ein Unterordner pro Reihe:
    <Comics>/<Reihe>/<Heft>.cbz|.cbr|.cb7|.pdf

Der Reader holt die Seiten einzeln als Bild:
  - CBZ:      direkt aus dem ZIP
  - CBR/CB7:  einmal mit 7-Zip in den Zwischenspeicher entpacken
  - PDF:      Seite fuer Seite mit pdftoppm rendern (und zwischenspeichern)
Der Zwischenspeicher (data/comic-cache) wird auf CACHE_LIMIT_BYTES begrenzt.
Der Lesestand je Heft steht in data/comics_progress.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from app import jellyfin_client, media_upload
from app.config import ROOT_DIR, Config

logger = logging.getLogger(__name__)

COMIC_EXTENSIONS = {".cbz", ".cbr", ".cb7", ".pdf", ".zip", ".rar"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif"}
CACHE_DIR = ROOT_DIR / "data" / "comic-cache"
INDEX_FILE = ROOT_DIR / "data" / "comics_index.json"
PROGRESS_FILE = ROOT_DIR / "data" / "comics_progress.json"
CACHE_LIMIT_BYTES = 3 * 1024**3
PDF_PAGE_HEIGHT = 2000  # Pixel - scharf auch auf dem iPad
LIBRARY_NAME = "Comics"

_lock = threading.Lock()
_book_locks: dict[str, threading.Lock] = {}
_root: Path | None = None


class ComicError(RuntimeError):
    pass


# ---------- Bibliothek ----------

def root(cfg: Config) -> Path:
    """Ordner der Jellyfin-Bibliothek "Comics" - legt beides bei Bedarf an."""
    global _root
    if _root is not None:
        return _root
    folders = jellyfin_client._request(cfg, "GET", "/Library/VirtualFolders").json()
    books = next((f for f in folders if f.get("CollectionType") == "books" and f.get("Locations")), None)
    if books:
        _root = Path(books["Locations"][0])
    else:
        movies = next((f for f in folders if f.get("CollectionType") == "movies" and f.get("Locations")), None)
        if not movies:
            raise ComicError("Keine Jellyfin-Bibliothek gefunden")
        _root = Path(movies["Locations"][0]).parent / LIBRARY_NAME
        _root.mkdir(parents=True, exist_ok=True)
        # Auch in Jellyfin als Buecher-Bibliothek
        jellyfin_client._request(
            cfg, "POST", "/Library/VirtualFolders",
            params={"name": LIBRARY_NAME, "collectionType": "books", "paths": str(_root), "refreshLibrary": "true"},
        )
        logger.info("Jellyfin-Bibliothek %s angelegt: %s", LIBRARY_NAME, _root)
    _root.mkdir(parents=True, exist_ok=True)
    return _root


def _book_id(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def _natural(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _archive_pages(path: Path) -> list[str]:
    if path.suffix.lower() in (".cbz", ".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except zipfile.BadZipFile:
            names = None
        if names is not None:
            return sorted(
                (n for n in names if Path(n).suffix.lower() in IMAGE_EXTENSIONS and "__MACOSX" not in n and not Path(n).name.startswith(".")),
                key=_natural,
            )
    # CBR/CB7 (oder falsch benanntes CBZ): mit 7-Zip auflisten
    result = subprocess.run(["7z", "l", "-slt", "-ba", str(path)], capture_output=True, text=True, timeout=60)
    names = [line[7:] for line in result.stdout.splitlines() if line.startswith("Path = ")]
    return sorted((n for n in names if Path(n).suffix.lower() in IMAGE_EXTENSIONS and "__MACOSX" not in n), key=_natural)


def _pdf_pages(path: Path) -> int:
    result = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=30)
    match = re.search(r"^Pages:\s+(\d+)", result.stdout, re.M)
    return int(match.group(1)) if match else 0


def _scan(cfg: Config) -> dict[str, dict]:
    """Alle Hefte samt Seitenzahl. Die Seitenzahl wird nur fuer neue oder
    geaenderte Dateien neu ermittelt."""
    base = root(cfg)
    index = _load_json(INDEX_FILE)
    books: dict[str, dict] = {}
    changed = False
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in COMIC_EXTENSIONS or any(p.startswith(".") for p in path.relative_to(base).parts):
            continue
        rel = path.relative_to(base).as_posix()
        stat = path.stat()
        key = f"{stat.st_size}:{int(stat.st_mtime)}"
        entry = index.get(rel)
        if not entry or entry.get("key") != key:
            try:
                if path.suffix.lower() == ".pdf":
                    entry = {"key": key, "kind": "pdf", "pages": _pdf_pages(path)}
                else:
                    names = _archive_pages(path)
                    entry = {"key": key, "kind": "archive", "pages": len(names), "names": names}
            except (subprocess.SubprocessError, OSError) as exc:
                logger.warning("Comic nicht lesbar: %s (%s)", rel, exc)
                continue
            index[rel] = entry
            changed = True
        if not entry.get("pages"):
            continue
        parts = rel.split("/")
        books[_book_id(rel)] = {
            "id": _book_id(rel),
            "rel": rel,
            "title": Path(parts[-1]).stem,
            "series": parts[-2] if len(parts) > 1 else "",
            "kind": entry["kind"],
            "pages": entry["pages"],
            "names": entry.get("names"),
            "modified": stat.st_mtime,
            # Zwischenspeicher je Dateistand: ersetzt man ein Heft unter
            # gleichem Namen, werden die Seiten neu erzeugt
            "cache": f"{_book_id(rel)}-{hashlib.sha1(key.encode()).hexdigest()[:8]}",
        }
    known = {b["rel"] for b in books.values()}
    if changed or any(rel not in known for rel in index):
        _save_json(INDEX_FILE, {rel: e for rel, e in index.items() if rel in known})
    return books


def library(cfg: Config) -> dict:
    with _lock:
        books = _scan(cfg)
    progress = _load_json(PROGRESS_FILE)
    items = []
    for b in books.values():
        p = progress.get(b["id"], {})
        items.append({
            "id": b["id"],
            "title": b["title"],
            "series": b["series"],
            "pages": b["pages"],
            "kind": b["kind"],
            # Teil der Bild-Adressen: ersetzt man ein Heft, holt der Browser es neu
            "version": b["cache"].rsplit("-", 1)[1],
            "page": p.get("page", 0),
            "read_at": p.get("updated"),
            "modified": b["modified"],
        })
    items.sort(key=lambda i: (i["series"].lower(), _natural(i["title"])))
    return {"books": items}


def _book(cfg: Config, book_id: str) -> dict:
    with _lock:
        books = _scan(cfg)
    if book_id not in books:
        raise ComicError("Heft nicht gefunden")
    return books[book_id]


# ---------- Seiten ----------

def _touch(path: Path) -> Path:
    path.touch()  # fuer das Aufraeumen: zuletzt benutzt
    return path


def _cleanup_cache() -> None:
    files = [p for p in CACHE_DIR.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if total <= CACHE_LIMIT_BYTES:
        return
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
        if total <= CACHE_LIMIT_BYTES * 0.8:
            break


def page(cfg: Config, book_id: str, number: int) -> tuple[bytes | Path, str]:
    """Seite <number> (ab 0) als Bild: (Bytes oder Datei, MIME-Typ)."""
    book = _book(cfg, book_id)
    if not 0 <= number < book["pages"]:
        raise ComicError("Diese Seite gibt es nicht")
    source = root(cfg) / book["rel"]
    cache = CACHE_DIR / book["cache"]
    lock = _book_locks.setdefault(book_id, threading.Lock())

    if book["kind"] == "pdf":
        target = cache / f"{number + 1:05d}.jpg"
        with lock:
            if not target.exists():
                cache.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["pdftoppm", "-jpeg", "-jpegopt", "quality=88", "-f", str(number + 1), "-l", str(number + 1),
                     "-scale-to-y", str(PDF_PAGE_HEIGHT), "-scale-to-x", "-1", "-singlefile", str(source), str(target.with_suffix(""))],
                    check=True, capture_output=True, timeout=120,
                )
                _cleanup_cache()
        return _touch(target), "image/jpeg"

    name = book["names"][number]
    mime = MIME.get(Path(name).suffix.lower(), "application/octet-stream")
    if source.suffix.lower() in (".cbz", ".zip") and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            return z.read(name), mime
    # CBR/CB7: einmal komplett entpacken, danach aus dem Zwischenspeicher
    target = cache / name
    with lock:
        if not target.exists():
            cache.mkdir(parents=True, exist_ok=True)
            subprocess.run(["7z", "x", "-y", f"-o{cache}", str(source)], check=True, capture_output=True, timeout=600)
            _cleanup_cache()
    if not target.exists():
        raise ComicError("Seite ließ sich nicht entpacken")
    return _touch(target), mime


# ---------- Lesestand ----------

def save_progress(book_id: str, number: int) -> None:
    with _lock:
        progress = _load_json(PROGRESS_FILE)
        progress[book_id] = {"page": max(0, int(number)), "updated": time.time()}
        _save_json(PROGRESS_FILE, progress)


def delete_book(cfg: Config, book_id: str) -> None:
    book = _book(cfg, book_id)
    (root(cfg) / book["rel"]).unlink()
    shutil.rmtree(CACHE_DIR / book["cache"], ignore_errors=True)
