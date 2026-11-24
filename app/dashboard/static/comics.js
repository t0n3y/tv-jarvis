"use strict";

/* ============================================================
   Comic-Reader (comics.bassbunkerfm.de)
   Bibliothek -> Heft oeffnen -> zwei Seiten nebeneinander mit
   Blaetteranimation (StPageFlip). Seiten kommen einzeln vom Pi
   (/api/comics/<id>/page/<n>) und werden nur rund um die aktuelle
   Seite geladen. Lesestand wird beim Blaettern gespeichert.
   ============================================================ */

const $ = (id) => document.getElementById(id);
const SECRET_KEY = "comicsSecret";
const PRELOAD_BEHIND = 2;
const PRELOAD_AHEAD = 6;
const SAVE_DELAY_MS = 1200;
const CHUNK_BYTES = 8 * 1024 * 1024;
const CHROME_HIDE_MS = 3500;

let books = [];
let current = null; // { book, pages: [div], flip, ratio }
let saveTimer = null;
let chromeTimer = null;
const uploads = [];

// ---------- Grundlagen ----------

function secret() {
  try {
    return localStorage.getItem(SECRET_KEY) || "";
  } catch (err) {
    return "";
  }
}

async function api(method, path, body, retried = false) {
  const headers = {};
  if (secret()) headers["X-Remote-Secret"] = secret();
  let payload;
  if (body instanceof Blob) {
    headers["Content-Type"] = "application/octet-stream";
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const resp = await fetch(path, { method, headers, body: payload });
  if (resp.status === 401 && !retried) {
    const entered = window.prompt("Passwort (wie bei der Fernbedienung):");
    if (entered) {
      try {
        localStorage.setItem(SECRET_KEY, entered.trim());
      } catch (err) {
        // ohne Speicher eben jedes Mal fragen
      }
      return api(method, path, body, true);
    }
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || `Fehler ${resp.status}`);
  return data;
}

function pageUrl(book, n) {
  const s = secret();
  return `/api/comics/${book.id}/page/${n}?v=${book.version || ""}${s ? `&secret=${encodeURIComponent(s)}` : ""}`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

let toastTimer = null;
function toast(text, error = false) {
  const t = $("toast");
  t.textContent = text;
  t.classList.toggle("error", error);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), error ? 4000 : 2500);
}

// ---------- Bibliothek ----------

function card(book) {
  const c = el("button", "card");
  c.type = "button";
  const cover = el("div", "cover");
  cover.style.backgroundImage = `url("${pageUrl(book, 0)}")`;
  if (book.page > 0) {
    const bar = el("div", "progress");
    const fill = el("i");
    fill.style.width = `${Math.min(100, ((book.page + 1) / book.pages) * 100)}%`;
    bar.append(fill);
    cover.append(bar);
  }
  c.append(cover, el("div", "card-title", book.title), el("div", "card-sub", `${book.pages} Seiten`));
  c.addEventListener("click", () => openBook(book));
  return c;
}

function renderLibrary() {
  const reading = books.filter((b) => b.page > 0 && b.page < b.pages - 2).sort((a, b) => (b.read_at || 0) - (a.read_at || 0)).slice(0, 12);
  $("continue-section").classList.toggle("hidden", !reading.length);
  $("continue").replaceChildren(...reading.map(card));

  const groups = new Map();
  for (const b of books) {
    const key = b.series || "Einzelhefte";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(b);
  }
  const shelves = [...groups.entries()].map(([name, list]) => {
    const section = el("section");
    const title = el("h2", null, name);
    title.append(el("span", null, String(list.length)));
    const grid = el("div", "grid");
    grid.append(...list.map(card));
    section.append(title, grid);
    return section;
  });
  $("shelves").replaceChildren(...shelves);
  $("empty").classList.toggle("hidden", books.length > 0);
}

async function loadLibrary() {
  try {
    books = (await api("GET", "/api/comics")).books || [];
    renderLibrary();
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- Reader ----------

function showChrome() {
  $("reader").classList.remove("chrome-hidden");
  clearTimeout(chromeTimer);
  chromeTimer = setTimeout(() => $("reader").classList.add("chrome-hidden"), CHROME_HIDE_MS);
}

function toggleChrome() {
  if ($("reader").classList.contains("chrome-hidden")) showChrome();
  else {
    clearTimeout(chromeTimer);
    $("reader").classList.add("chrome-hidden");
  }
}

function preload(index) {
  if (!current) return;
  const from = Math.max(0, index - PRELOAD_BEHIND);
  const to = Math.min(current.pages.length - 1, index + PRELOAD_AHEAD);
  for (let i = from; i <= to; i++) {
    const img = current.pages[i].querySelector("img");
    if (!img.src) img.src = img.dataset.src;
  }
}

function updateCount(index) {
  const total = current.book.pages;
  // Auf dem Titel liegt eine Seite allein, danach immer zwei
  const right = index === 0 ? null : Math.min(index + 2, total);
  $("r-count").textContent = right && right > index + 1 ? `${index + 1}–${right} / ${total}` : `${index + 1} / ${total}`;
  $("r-slider").value = String(index);
}

function saveSoon(index) {
  clearTimeout(saveTimer);
  const id = current.book.id;
  current.book.page = index;
  saveTimer = setTimeout(() => api("POST", `/api/comics/${id}/progress`, { page: index }).catch(() => {}), SAVE_DELAY_MS);
}

function buildFlip(startPage) {
  const stage = $("stage");
  const old = current.flip;
  if (old) {
    try {
      old.destroy();
    } catch (err) {
      // schon weg
    }
  }
  // Groesse: zwei Seiten nebeneinander muessen in die Buehne passen
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  let pageHeight = height;
  let pageWidth = pageHeight * current.ratio;
  if (pageWidth * 2 > width) {
    pageWidth = width / 2;
    pageHeight = pageWidth / current.ratio;
  }
  const book = el("div", "book");
  stage.replaceChildren(book);
  current.pages.forEach((p) => book.append(p));
  const flip = new St.PageFlip(book, {
    width: Math.floor(pageWidth),
    height: Math.floor(pageHeight),
    size: "fixed",
    showCover: true,
    usePortrait: false,
    drawShadow: true,
    maxShadowOpacity: 0.5,
    flippingTime: 750,
    mobileScrollSupport: false,
    disableFlipByClick: true,
    showPageCorners: true,
    startPage: Math.min(startPage, current.pages.length - 1),
  });
  flip.loadFromHTML(current.pages);
  flip.on("flip", (event) => {
    const index = event.data;
    preload(index);
    updateCount(index);
    saveSoon(index);
  });
  current.flip = flip;
  const index = flip.getCurrentPageIndex();
  preload(index);
  updateCount(index);
}

async function openBook(book) {
  closeBook(false);
  $("library").classList.add("hidden");
  $("reader").classList.remove("hidden");
  $("r-loading").classList.remove("hidden");
  $("r-title").textContent = book.title;
  $("r-series").textContent = book.series;
  $("r-slider").max = String(book.pages - 1);
  history.pushState({ reader: book.id }, "");

  // Seitenverhaeltnis aus der ersten Seite
  let ratio = 2 / 3;
  try {
    const probe = new Image();
    probe.src = pageUrl(book, Math.min(1, book.pages - 1));
    await probe.decode();
    if (probe.naturalWidth && probe.naturalHeight) ratio = Math.min(1, probe.naturalWidth / probe.naturalHeight);
  } catch (err) {
    // Standard-Comicformat
  }
  const pages = Array.from({ length: book.pages }, (_, i) => {
    const page = el("div", "page");
    page.dataset.density = i === 0 || i === book.pages - 1 ? "hard" : "soft";
    const img = el("img");
    img.alt = "";
    img.dataset.src = pageUrl(book, i);
    img.decoding = "async";
    page.append(img);
    return page;
  });
  current = { book, pages, flip: null, ratio };
  buildFlip(book.page || 0);
  $("r-loading").classList.add("hidden");
  showChrome();
}

function closeBook(fromHistory = true) {
  if (!current) return;
  clearTimeout(saveTimer);
  const { book, flip } = current;
  if (flip) {
    api("POST", `/api/comics/${book.id}/progress`, { page: flip.getCurrentPageIndex() }).catch(() => {});
    try {
      flip.destroy();
    } catch (err) {
      // egal
    }
  }
  current = null;
  $("reader").classList.add("hidden");
  $("library").classList.remove("hidden");
  if (!fromHistory && history.state && history.state.reader) history.back();
  loadLibrary();
}

// Tippen und Wischen auf den unsichtbaren Zonen
function bindZone(zone, onTap) {
  let start = null;
  zone.addEventListener("pointerdown", (e) => {
    start = { x: e.clientX, y: e.clientY, t: Date.now() };
  });
  zone.addEventListener("pointerup", (e) => {
    if (!start || !current || !current.flip) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    start = null;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
      if (dx < 0) current.flip.flipNext();
      else current.flip.flipPrev();
    } else if (Math.abs(dx) < 12 && Math.abs(dy) < 12) {
      onTap();
    }
  });
}

bindZone($("tap-prev"), () => current.flip.flipPrev());
bindZone($("tap-next"), () => current.flip.flipNext());
bindZone($("tap-menu"), () => toggleChrome());

document.addEventListener("keydown", (e) => {
  if (!current || !current.flip) return;
  if (e.key === "ArrowRight" || e.key === " ") current.flip.flipNext();
  else if (e.key === "ArrowLeft") current.flip.flipPrev();
  else if (e.key === "Escape") closeBook(false);
});

$("r-slider").addEventListener("input", () => {
  if (!current) return;
  updateCount(Number($("r-slider").value));
  showChrome();
});
$("r-slider").addEventListener("change", () => {
  if (!current || !current.flip) return;
  const index = Number($("r-slider").value);
  preload(index);
  current.flip.turnToPage(index);
  updateCount(current.flip.getCurrentPageIndex());
  saveSoon(current.flip.getCurrentPageIndex());
});

$("r-back").addEventListener("click", () => closeBook(false));
$("r-full").addEventListener("click", () => {
  const root = document.documentElement;
  if (document.fullscreenElement) document.exitFullscreen();
  else if (root.requestFullscreen) root.requestFullscreen().catch(() => toast("Vollbild geht hier nicht – als App zum Home-Bildschirm hinzufügen", true));
  else toast("Vollbild: im Teilen-Menü „Zum Home-Bildschirm“ wählen");
});
$("r-delete").addEventListener("click", async () => {
  if (!current) return;
  const { book } = current;
  if (!window.confirm(`„${book.title}“ wirklich löschen? Die Datei wird von der Platte entfernt.`)) return;
  try {
    await api("DELETE", `/api/comics/${book.id}`);
    toast("Gelöscht");
    closeBook(false);
  } catch (err) {
    toast(err.message, true);
  }
});

window.addEventListener("popstate", () => {
  if (current) closeBook(true);
});

// Drehen/Groesse aendern: Buch neu einpassen, gleiche Seite
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (current && current.flip) buildFlip(current.flip.getCurrentPageIndex());
  }, 250);
});

// ---------- Hochladen (Teile wie in der Fernbedienung) ----------

function guessSeries(filename) {
  return filename
    .replace(/\.[^.]+$/, "")
    .replace(/[._]+/g, " ")
    .replace(/\s*(\(|\[).*$/, "")
    .replace(/\s*(#|vol\.?|band|bd\.?|nr\.?|issue|heft|teil)?\s*\d+\s*$/i, "")
    .replace(/\s*[-–]\s*$/, "")
    .trim();
}

function renderUploads() {
  const box = $("uploads");
  box.classList.toggle("hidden", !uploads.length);
  if (!uploads.length) return;
  const rows = uploads.map((u) => {
    const row = el("div", "up-row");
    row.append(el("div", "up-name", u.file.name));
    const state = u.status === "ready" ? `${(u.file.size / 1024 ** 2).toFixed(0)} MB` : u.status === "done" ? "✓ Fertig" : u.status === "error" ? u.message : `${Math.floor((u.sent / u.file.size) * 100)} %`;
    row.append(el("div", "up-state", state));
    if (u.status === "ready") {
      const input = el("input", "up-series");
      input.placeholder = "Reihe (Ordner), z. B. Asterix";
      input.value = u.series;
      input.addEventListener("input", () => (u.series = input.value));
      row.append(input);
    } else if (u.status !== "done") {
      const bar = el("div", "up-bar");
      const fill = el("i");
      fill.style.width = `${(u.sent / u.file.size) * 100}%`;
      bar.append(fill);
      row.append(bar);
    }
    return row;
  });
  const ready = uploads.some((u) => u.status === "ready");
  if (ready) {
    const go = el("button", "up-go", "Hochladen");
    go.type = "button";
    go.addEventListener("click", runUploads);
    rows.push(go);
  }
  box.replaceChildren(...rows);
}

async function uploadOne(u, target) {
  const started = await api("POST", "/api/remote/jellyfin/upload", {
    target: target.id,
    filename: u.file.name,
    size: u.file.size,
    modified: u.file.lastModified,
    series: u.series,
  });
  u.sent = started.received;
  u.status = "uploading";
  renderUploads();
  while (u.sent < u.file.size) {
    const chunk = u.file.slice(u.sent, Math.min(u.file.size, u.sent + CHUNK_BYTES));
    u.sent = (await api("PUT", `/api/remote/jellyfin/upload/${started.id}?offset=${u.sent}`, chunk)).received;
    renderUploads();
  }
  await api("POST", `/api/remote/jellyfin/upload/${started.id}/finish`);
  u.status = "done";
}

let uploading = false;
async function runUploads() {
  if (uploading) return;
  uploading = true;
  try {
    await api("GET", "/api/comics"); // legt die Comics-Bibliothek bei Bedarf an
    const targets = (await api("GET", "/api/remote/jellyfin/upload/targets")).targets || [];
    const target = targets.find((t) => t.kind === "books");
    if (!target) throw new Error("Comics-Bibliothek nicht gefunden");
    for (const u of uploads) {
      if (u.status !== "ready" && u.status !== "error") continue;
      try {
        await uploadOne(u, target);
      } catch (err) {
        u.status = "error";
        u.message = err.message;
      }
      renderUploads();
    }
  } catch (err) {
    toast(err.message, true);
  } finally {
    uploading = false;
  }
  await loadLibrary();
  setTimeout(() => {
    for (let i = uploads.length - 1; i >= 0; i--) if (uploads[i].status === "done") uploads.splice(i, 1);
    renderUploads();
  }, 3000);
}

$("add-input").addEventListener("change", () => {
  for (const file of $("add-input").files) uploads.push({ file, series: guessSeries(file.name), status: "ready", sent: 0 });
  $("add-input").value = "";
  renderUploads();
});

history.replaceState({}, "");
loadLibrary();
