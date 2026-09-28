"use strict";

/* ============================================================
   JARVIS Fernbedienung
   Aufbau: Grundlagen (DOM, API, Toast) → Navigation → Homescreen →
   Apps (YouTube, Jellyfin, Radio, Einstellungen) → Status-Poll + Dock.
   ============================================================ */

const POLL_MS = 1500;
const SEARCH_DEBOUNCE_MS = 350;
const OPTIMISTIC_HOLD_MS = 2500;
const POWER_HOLD_MS = 15000;
const WEEKDAYS = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const JELLYFIN_RGB = "167, 118, 255";
const YOUTUBE_RGB = "255, 94, 98";
const RADIO_RGB = "79, 216, 255";
const VINYL_RGB = "255, 107, 61";

// ---------- DOM-Helfer ----------

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function setIcon(el, name, label) {
  const key = `${name}|${label || ""}`;
  if (el.dataset.icon === key) return;
  el.dataset.icon = key;
  el.replaceChildren(icon(name), label ? h("span", null, label) : "");
}

function setBackground(el, url) {
  const value = url ? `url("${url.replace(/"/g, "%22")}")` : "";
  if (el.dataset.bg === value) return;
  el.dataset.bg = value;
  el.style.backgroundImage = value;
}

const pad = (n) => String(n).padStart(2, "0");

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(total % 60)}` : `${minutes}:${pad(total % 60)}`;
}

function formatRuntime(seconds) {
  const minutes = Math.round((seconds || 0) / 60);
  if (minutes < 60) return `${minutes} Min.`;
  return `${Math.floor(minutes / 60)} Std. ${minutes % 60} Min.`;
}

// ---------- Secret + API ----------

function getSecret() {
  try {
    return localStorage.getItem("remoteSecret") || "";
  } catch (err) {
    return "";
  }
}

function setSecret(value) {
  try {
    localStorage.setItem("remoteSecret", value);
  } catch (err) {
    // privater Modus o.ae. - dann eben ohne Merken
  }
}

function withSecret(url) {
  const secret = getSecret();
  if (!url || !secret) return url;
  return `${url}${url.includes("?") ? "&" : "?"}secret=${encodeURIComponent(secret)}`;
}

// quiet: Hintergrund-Abfragen (Status-Poll) fragen nie nach dem Passwort,
// sonst wuerde bei falschem Secret alle 1,5 s ein Dialog aufpoppen.
async function apiRequest(method, path, body, { quiet = false, retried = false } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const secret = getSecret();
  if (secret) headers["X-Remote-Secret"] = secret;

  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (resp.status === 401 && !quiet && !retried) {
    const entered = window.prompt("Passwort für die Fernbedienung:");
    if (!entered) throw new Error("Kein Passwort angegeben");
    setSecret(entered);
    return apiRequest(method, path, body, { retried: true });
  }
  if (!resp.ok) {
    let detail = resp.statusText || `Fehler ${resp.status}`;
    try {
      detail = (await resp.json()).detail || detail;
    } catch (err) {
      // Antwort war kein JSON - statusText reicht
    }
    throw new Error(detail);
  }
  return resp.status === 204 ? null : resp.json();
}

const api = {
  get: (path) => apiRequest("GET", path),
  post: (path, body) => apiRequest("POST", path, body || {}),
  patch: (path, body) => apiRequest("PATCH", path, body || {}),
  del: (path) => apiRequest("DELETE", path),
};

// ---------- Rueckmeldungen: Toast + Lautstaerke ----------

let toastTimer = null;

function toast(text, isError = false) {
  const el = $("toast");
  el.textContent = text;
  el.classList.toggle("error", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 4200 : 2600);
}

let volumeTimer = null;

function showVolume(volume) {
  if (!volume) return;
  const hud = $("volume-hud");
  $("vol-fill").style.width = `${Math.min(100, volume.percent)}%`;
  $("vol-label").textContent = volume.muted ? "Stumm" : `${volume.percent}%`;
  hud.classList.toggle("muted", volume.muted);
  hud.classList.add("show");
  clearTimeout(volumeTimer);
  volumeTimer = setTimeout(() => hud.classList.remove("show"), 1800);
}

function onTap(el, handler) {
  el.addEventListener("click", async (event) => {
    try {
      await handler(event);
    } catch (err) {
      toast(err.message || "Fehler", true);
    }
  });
}

// ---------- Globaler Zustand (vom Status-Poll) ----------

let state = { tv_on: false, youtube: {}, jellyfin: {}, radio: {}, jellyfin_error: null };
let playingHold = null;
let powerHold = null;

// Knoepfe reagieren sofort; bis der Kiosk den Befehl bestaetigt hat, wuerde
// der naechste Poll sonst kurz den alten Zustand zurueckmelden.
function holdPlaying(kind, value) {
  playingHold = { kind, value, until: Date.now() + OPTIMISTIC_HOLD_MS };
  if (state[kind]) state[kind].playing = value;
  renderAll();
}

function applyHolds(data) {
  if (playingHold) {
    const media = data[playingHold.kind];
    if (Date.now() > playingHold.until || !media) playingHold = null;
    else if (media.playing === playingHold.value) playingHold = null;
    else media.playing = playingHold.value;
  }
  if (powerHold) {
    if (Date.now() > powerHold.until || data.tv_on === powerHold.value) powerHold = null;
    else data.tv_on = powerHold.value;
  }
}

// ---------- Navigation (mit Browser-History: Wisch-Zurueck klappt) ----------

let currentView = "home";

const VIEW_HOOKS = {
  jellyfin: () => jellyfinLoadHome(),
  radio: () => loadStations(),
  vinyl: () => loadVinyl(),
  clock: () => renderTimer(),
  light: () => loadLight(),
  settings: () => loadSettings(),
};

function showView(name) {
  if (!$(`view-${name}`)) name = "home";
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("hidden", el.id !== `view-${name}`));
  currentView = name;
  document.body.classList.toggle("retro", name === "vinyl");
  $("dock-home").classList.toggle("current", name === "home");
  window.scrollTo(0, 0);
  if (VIEW_HOOKS[name]) VIEW_HOOKS[name]();
}

function openView(name) {
  if (name === currentView) return;
  if (currentView === "home") history.pushState({ view: name }, "");
  else history.replaceState({ view: name }, "");
  showView(name);
}

function goHome() {
  closeSheet();
  closeVinylSheet();
  if (currentView === "home") {
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (history.state && history.state.view && history.state.view !== "home") history.back();
  else showView("home");
}

window.addEventListener("popstate", (event) => {
  closeSheet();
  closeVinylSheet();
  showView((event.state && event.state.view) || "home");
});

document.querySelectorAll("[data-open]").forEach((el) => {
  el.addEventListener("click", () => openView(el.dataset.open));
});
document.querySelectorAll("[data-back]").forEach((el) => el.addEventListener("click", goHome));

// ---------- Homescreen: Uhr, Fernseher, Mini-Player ----------

let userName = null;

function greeting(hour) {
  if (hour < 5) return "Gute Nacht";
  if (hour < 11) return "Guten Morgen";
  if (hour < 17) return "Guten Tag";
  if (hour < 22) return "Guten Abend";
  return "Gute Nacht";
}

function updateClock() {
  const now = new Date();
  $("hero-clock").textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  $("hero-date").textContent = `${WEEKDAYS[now.getDay()]}, ${now.getDate()}. ${MONTHS[now.getMonth()]}`;
  const hello = greeting(now.getHours());
  $("hero-greeting").textContent = userName ? `${hello}, ${userName}` : hello;
}

function renderPower() {
  const on = !!state.tv_on;
  $("tv-pill").classList.toggle("on", on);
  $("tv-pill-label").textContent = on ? "TV an" : "TV aus";
  $("power-state").textContent = on ? "Läuft" : "Aus";
  $("btn-power-on").classList.toggle("active", on);
  $("btn-power-off").classList.toggle("active", !on);
  $("btn-power-off").classList.toggle("off", !on);
}

function setPower(on) {
  powerHold = { value: on, until: Date.now() + POWER_HOLD_MS };
  state.tv_on = on;
  renderPower();
}

onTap($("btn-power-on"), async () => {
  if (state.tv_on) return;
  setPower(true);
  toast("Fernseher wird eingeschaltet …");
  await api.post("/api/remote/power", { state: "on" });
});

onTap($("btn-power-off"), async () => {
  if (!state.tv_on) return;
  setPower(false);
  toast("Fernseher wird ausgeschaltet …");
  await api.post("/api/remote/power", { state: "off" });
});

function activeMedia() {
  const jf = state.jellyfin || {};
  const yt = state.youtube || {};
  const vy = state.vinyl || {};
  const radioState = state.radio || {};
  if (vy.active && vy.record) {
    return {
      kind: "vinyl",
      view: "vinyl",
      playing: !!vy.playing,
      title: vy.title,
      sub: `${vy.artist} · ${vy.record.album}`,
      image: vy.record.cover,
      icon: "vinyl",
      source: "Plattenspieler",
      rgb: VINYL_RGB,
    };
  }
  if (jf.item_id) {
    return {
      kind: "jellyfin",
      view: "jellyfin",
      playing: !!jf.playing,
      title: jf.title,
      sub: jf.subtitle || "Jellyfin",
      image: withSecret(jf.poster || jf.backdrop),
      icon: "jellyfin",
      source: "Jellyfin",
      rgb: JELLYFIN_RGB,
    };
  }
  if (yt.video_id) {
    return {
      kind: "youtube",
      view: "youtube",
      playing: !!yt.playing,
      title: yt.title || "YouTube-Video",
      sub: "YouTube",
      image: yt.thumbnail_url,
      icon: "youtube",
      source: "YouTube",
      rgb: YOUTUBE_RGB,
    };
  }
  if (radioState.playing) {
    return {
      kind: "radio",
      view: "radio",
      playing: true,
      title: radioState.station ? radioState.station.name : "Radio",
      sub: "Live-Radio",
      image: null,
      icon: "radio",
      source: "Radio",
      rgb: RADIO_RGB,
    };
  }
  return null;
}

function playbackIcon(media) {
  if (!media) return "play";
  if (media.kind === "radio") return "stop";
  return media.playing ? "pause" : "play";
}

function renderMini(media) {
  const mini = $("mini-player");
  mini.classList.toggle("hidden", !media);
  if (!media) return;
  mini.style.setProperty("--tint", media.rgb);
  $("mini-source").textContent = media.source;
  $("mini-title").textContent = media.title || "";
  $("mini-sub").textContent = media.sub || "";
  const art = $("mini-art");
  setBackground(art, media.image);
  const artKey = media.image ? "" : media.icon;
  if (art.dataset.icon !== artKey) {
    art.dataset.icon = artKey;
    art.replaceChildren(artKey ? icon(artKey) : "");
  }
  setIcon($("mini-toggle"), playbackIcon(media));
}

$("mini-player").addEventListener("click", (event) => {
  if (event.target.closest("#mini-toggle")) return;
  const media = activeMedia();
  if (media) openView(media.view);
});

onTap($("mini-toggle"), () => toggleActiveMedia());

// ---------- Gemeinsame Abspiel-Steuerung (Karte + Dock) ----------

async function togglePlayback(kind) {
  const media = state[kind] || {};
  const endpoint = { jellyfin: "/api/remote/jellyfin", vinyl: "/api/remote/vinyl" }[kind] || "/api/remote/youtube";
  const action = media.playing ? "pause" : "resume";
  holdPlaying(kind, !media.playing);
  await api.post(endpoint, { action });
}

async function toggleActiveMedia() {
  const media = activeMedia();
  if (media && (media.kind === "jellyfin" || media.kind === "youtube" || media.kind === "vinyl")) {
    await togglePlayback(media.kind);
    return;
  }
  if (media && media.kind === "radio") {
    await api.post("/api/remote/radio", { action: "stop" });
    toast("Radio gestoppt");
  } else if (state.radio && state.radio.station) {
    await api.post("/api/remote/radio", { action: "play", station_id: state.radio.station.id });
    toast(`${state.radio.station.name} läuft`);
  } else {
    toast("Gerade läuft nichts");
    return;
  }
  poll();
}

function createTransport(prefix, kind, endpoint) {
  const range = $(`${prefix}-progress`);
  const cur = $(`${prefix}-cur`);
  const dur = $(`${prefix}-dur`);
  const toggle = $(`${prefix}-toggle`);
  let scrubbing = false;

  function paint() {
    const max = Number(range.max) || 0;
    const value = Number(range.value) || 0;
    range.style.setProperty("--pct", `${max > 0 ? (value / max) * 100 : 0}%`);
    cur.textContent = formatTime(value);
  }

  range.addEventListener("input", () => {
    scrubbing = true;
    paint();
  });
  range.addEventListener("change", async () => {
    try {
      await api.post(endpoint, { action: "seek_to", seconds: Number(range.value) });
    } catch (err) {
      toast(err.message, true);
    } finally {
      scrubbing = false;
    }
  });
  onTap($(`${prefix}-back`), () => api.post(endpoint, { action: "seek", seconds: -10 }));
  onTap($(`${prefix}-fwd`), () => api.post(endpoint, { action: "seek", seconds: 10 }));
  onTap(toggle, () => togglePlayback(kind));

  return {
    update(media) {
      setIcon(toggle, media.playing ? "pause" : "play", media.playing ? "Pause" : "Weiter");
      const max = Math.max(0, Math.floor(media.duration || 0));
      if (Number(range.max) !== max) range.max = String(max);
      dur.textContent = formatTime(max);
      if (!scrubbing) {
        range.value = String(Math.min(Math.floor(media.current_time || 0), max));
        paint();
      }
    },
  };
}

// ---------- YouTube ----------

const ytTransport = createTransport("yt", "youtube", "/api/remote/youtube");

function updateYoutubeClear() {
  const active = !!(state.youtube && state.youtube.video_id);
  $("yt-clear").classList.toggle("hidden", !active && !$("yt-url").value);
}

function renderYoutube() {
  const yt = state.youtube || {};
  const active = !!yt.video_id;
  $("yt-now").classList.toggle("hidden", !active);
  updateYoutubeClear();
  if (!active) return;
  setBackground($("yt-art"), yt.thumbnail_url);
  $("yt-title").textContent = yt.title || "Video wird geladen …";
  ytTransport.update(yt);
}

$("yt-url").addEventListener("input", updateYoutubeClear);
$("yt-url").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("yt-play").click();
});

onTap($("yt-play"), async () => {
  const url = $("yt-url").value.trim();
  if (!url) throw new Error("Bitte zuerst einen YouTube-Link einfügen");
  $("yt-url").blur();
  toast(state.tv_on ? "Startet auf dem Fernseher …" : "Fernseher wird eingeschaltet …");
  await api.post("/api/remote/youtube", { action: "play", url });
  poll();
});

// Das × im Linkfeld leert das Feld UND stoppt das laufende Video
onTap($("yt-clear"), async () => {
  $("yt-url").value = "";
  updateYoutubeClear();
  if (state.youtube && state.youtube.video_id) {
    await api.post("/api/remote/youtube", { action: "stop" });
    toast("Video gestoppt");
    poll();
  }
});

// ---------- Jellyfin ----------

const jf = {
  libraries: [],
  resume: [],
  libraryId: null,
  stack: [],
  search: "",
  seq: 0,
  loaded: false,
  wasActive: false,
  lastErrorId: null,
};

const jfTransport = createTransport("jf", "jellyfin", "/api/remote/jellyfin");
let searchTimer = null;

function resumeFraction(item) {
  if (item.is_folder || item.played || !item.position_seconds || !item.runtime_seconds) return 0;
  return Math.min(1, item.position_seconds / item.runtime_seconds);
}

function jellyfinParentId() {
  return jf.stack.length ? jf.stack[jf.stack.length - 1].id : jf.libraryId;
}

async function jellyfinLoadHome() {
  if (!jf.loaded) renderSkeleton();
  try {
    const data = await api.get("/api/remote/jellyfin/home");
    jf.libraries = data.libraries || [];
    jf.resume = data.resume || [];
    if (!jf.libraries.some((lib) => lib.id === jf.libraryId)) {
      jf.libraryId = jf.libraries.length ? jf.libraries[0].id : null;
      jf.stack = [];
    }
    jf.loaded = true;
    renderResume();
    await jellyfinLoadItems();
  } catch (err) {
    renderJellyfinMessage("film", err.message);
  }
}

async function jellyfinLoadItems() {
  const seq = ++jf.seq;
  renderNavigation();
  const parentId = jellyfinParentId();
  if (!jf.search && !parentId) {
    renderJellyfinMessage("film", "Keine Bibliotheken gefunden.");
    return;
  }
  const query = jf.search ? `search=${encodeURIComponent(jf.search)}` : `parent_id=${encodeURIComponent(parentId)}`;
  try {
    const data = await api.get(`/api/remote/jellyfin/items?${query}`);
    if (seq === jf.seq) renderGrid(data.items || []);
  } catch (err) {
    if (seq === jf.seq) renderJellyfinMessage("film", err.message);
  }
}

function renderNavigation() {
  const atRoot = !jf.search && jf.stack.length === 0;
  $("jf-chips").replaceChildren(
    ...jf.libraries.map((lib) =>
      h(
        "button",
        {
          class: `chip${!jf.search && lib.id === jf.libraryId ? " active" : ""}`,
          type: "button",
          onclick: () => selectLibrary(lib.id),
        },
        lib.name
      )
    )
  );
  $("jf-resume-section").classList.toggle("hidden", !atRoot || jf.resume.length === 0);
  $("jf-crumbs").classList.toggle("hidden", !!jf.search || jf.stack.length === 0);
  if (jf.stack.length) $("jf-crumb-title").textContent = jf.stack[jf.stack.length - 1].name;
}

function selectLibrary(id) {
  clearSearch();
  jf.libraryId = id;
  jf.stack = [];
  jellyfinLoadItems();
}

function posterCard(item, wide = false) {
  const image = wide ? item.backdrop || item.poster : item.poster;
  const media = h(
    "div",
    { class: `poster-img${wide || item.wide ? " wide" : ""}` },
    h("div", { class: "poster-ph" }, icon(item.is_folder ? "folder" : "film"))
  );
  if (image) {
    const img = h("img", { alt: "", loading: "lazy", decoding: "async", src: withSecret(image) });
    img.addEventListener("load", () => img.classList.add("loaded"));
    img.addEventListener("error", () => img.remove());
    media.append(img);
  }
  const fraction = resumeFraction(item);
  if (fraction > 0) {
    media.append(h("div", { class: "poster-progress" }, h("span", { style: `width:${(fraction * 100).toFixed(1)}%` })));
  }
  if (item.played && !item.is_folder) media.append(h("div", { class: "poster-badge" }, icon("check")));
  const sub = item.subtitle || (item.is_folder && item.child_count ? `${item.child_count} Einträge` : "");
  return h(
    "button",
    { class: "poster", type: "button", onclick: () => openJellyfinItem(item) },
    media,
    h("div", { class: "poster-title" }, item.name),
    sub ? h("div", { class: "poster-sub" }, sub) : null
  );
}

function renderResume() {
  $("jf-resume").replaceChildren(...jf.resume.map((item) => posterCard(item, true)));
}

function renderGrid(items) {
  if (!items.length) {
    const text = jf.search ? `Nichts gefunden für „${jf.search}“.` : "Hier ist noch nichts drin.";
    renderJellyfinMessage(jf.search ? "search" : "folder", text);
    return;
  }
  $("jf-empty").classList.add("hidden");
  $("jf-grid").replaceChildren(...items.map((item) => posterCard(item)));
}

function renderJellyfinMessage(iconName, text) {
  $("jf-grid").replaceChildren();
  $("jf-empty").replaceChildren(icon(iconName), h("div", null, text));
  $("jf-empty").classList.remove("hidden");
}

function renderSkeleton() {
  $("jf-empty").classList.add("hidden");
  $("jf-grid").replaceChildren(
    ...Array.from({ length: 6 }, () =>
      h("div", { class: "poster skeleton" }, h("div", { class: "poster-img" }), h("div", { class: "poster-title" }))
    )
  );
}

function openJellyfinItem(item) {
  if (!item.is_folder) {
    openSheet(item);
    return;
  }
  clearSearch();
  jf.stack.push({ id: item.id, name: item.name });
  jellyfinLoadItems();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

onTap($("jf-up"), () => {
  jf.stack.pop();
  jellyfinLoadItems();
});

function clearSearch() {
  clearTimeout(searchTimer);
  $("jf-search").value = "";
  $("jf-search-clear").classList.add("hidden");
  jf.search = "";
}

$("jf-search").addEventListener("input", () => {
  $("jf-search-clear").classList.toggle("hidden", !$("jf-search").value);
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const value = $("jf-search").value.trim();
    if (value === jf.search) return;
    jf.search = value;
    jellyfinLoadItems();
  }, SEARCH_DEBOUNCE_MS);
});

$("jf-search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("jf-search").blur();
});

onTap($("jf-search-clear"), () => {
  clearSearch();
  jellyfinLoadItems();
});

function renderJellyfinNow() {
  const media = state.jellyfin || {};
  const active = !!media.item_id;
  $("jf-now").classList.toggle("hidden", !active);
  if (active) {
    setBackground($("jf-art"), withSecret(media.backdrop || media.poster));
    $("jf-title").textContent = media.title || "";
    $("jf-sub").textContent = media.subtitle || "";
    jfTransport.update(media);
  }
  // Nach dem Ende einer Wiedergabe "Weiterschauen" nachladen (die Position
  // wird serverseitig kurz danach gespeichert)
  if (jf.wasActive && !active && currentView === "jellyfin") setTimeout(jellyfinLoadHome, 1500);
  jf.wasActive = active;

  const error = state.jellyfin_error;
  if (error) {
    if (jf.lastErrorId !== null && error.id !== jf.lastErrorId && error.message) toast(error.message, true);
    jf.lastErrorId = error.id;
  }
}

onTap($("jf-stop"), async () => {
  await api.post("/api/remote/jellyfin", { action: "stop" });
  toast("Wiedergabe gestoppt");
  poll();
});

// ---------- Jellyfin: Detail-Sheet ----------

let sheetItem = null;

function renderSheetMeta(item) {
  const tags = [];
  if (item.type === "Episode" && item.subtitle) tags.push(item.subtitle);
  else if (item.year) tags.push(String(item.year));
  if (item.runtime_seconds) tags.push(formatRuntime(item.runtime_seconds));
  if (item.official_rating) tags.push(item.official_rating);
  if (item.community_rating) tags.push(`★ ${Number(item.community_rating).toFixed(1)}`);
  (item.genres || []).forEach((genre) => tags.push(genre));
  const nodes = tags.map((tag) => h("span", { class: "meta-tag" }, tag));
  if (item.played) nodes.unshift(h("span", { class: "meta-tag accent" }, "Gesehen"));
  $("sheet-meta").replaceChildren(...nodes);

  const fraction = resumeFraction(item);
  $("sheet-progress").classList.toggle("hidden", fraction <= 0);
  $("sheet-progress-fill").style.width = `${(fraction * 100).toFixed(1)}%`;
  $("sheet-play-label").textContent =
    fraction > 0 ? `Fortsetzen ab ${formatTime(item.position_seconds)}` : "Abspielen";
  $("sheet-restart").classList.toggle("hidden", fraction <= 0);
}

function openSheet(item) {
  sheetItem = item;
  setBackground($("sheet-hero"), withSecret(item.backdrop || item.poster));
  $("sheet-title").textContent = item.name;
  $("sheet-overview").textContent = "Lädt …";
  $("sheet-warning").classList.add("hidden");
  renderSheetMeta(item);
  $("sheet-play").disabled = true;
  $("sheet-backdrop").classList.remove("hidden");
  $("sheet").classList.add("open");
  $("sheet").setAttribute("aria-hidden", "false");
  $("sheet").scrollTop = 0;
  loadSheetDetail(item.id);
}

async function loadSheetDetail(id) {
  try {
    const detail = await api.get(`/api/remote/jellyfin/item/${encodeURIComponent(id)}`);
    if (!sheetItem || sheetItem.id !== id) return;
    sheetItem = detail;
    renderSheetMeta(detail);
    $("sheet-overview").textContent = detail.overview || "Keine Beschreibung vorhanden.";
    if (detail.playback_issue) {
      $("sheet-warning").textContent = detail.playback_issue;
      $("sheet-warning").classList.remove("hidden");
      $("sheet-restart").classList.add("hidden");
      return;
    }
    $("sheet-play").disabled = false;
  } catch (err) {
    if (sheetItem && sheetItem.id === id) $("sheet-overview").textContent = err.message;
  }
}

function closeSheet() {
  if (!sheetItem) return;
  sheetItem = null;
  $("sheet").classList.remove("open");
  $("sheet").setAttribute("aria-hidden", "true");
  $("sheet-backdrop").classList.add("hidden");
}

async function playFromSheet(fromStart) {
  if (!sheetItem) return;
  const id = sheetItem.id;
  $("sheet-play").disabled = true;
  $("sheet-restart").disabled = true;
  toast(state.tv_on ? "Startet auf dem Fernseher …" : "Fernseher wird eingeschaltet …");
  try {
    await api.post("/api/remote/jellyfin", { action: "play", item_id: id, from_start: fromStart });
    closeSheet();
    poll();
  } finally {
    $("sheet-play").disabled = false;
    $("sheet-restart").disabled = false;
  }
}

onTap($("sheet-play"), () => playFromSheet(false));
onTap($("sheet-restart"), () => playFromSheet(true));
onTap($("sheet-close"), () => closeSheet());
$("sheet-backdrop").addEventListener("click", closeSheet);

// ---------- Jellyfin: Hochladen ----------
// Dateien gehen in 8-MB-Stuecken an den Pi (app/media_upload.py) und landen
// direkt auf der Jellyfin-Platte. Bricht die Verbindung ab, wird das Stueck
// wiederholt; waehlt man dieselbe Datei spaeter erneut, geht es beim
// bereits empfangenen Stand weiter.

const UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024;
const UPLOAD_MAX_RETRIES = 6;
const UPLOAD_CHUNK_TIMEOUT_MS = 120000;
const UPLOAD_JUNK = /\b(2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|hdtv|dvdrip|x26[45]|h\.?26[45]|hevc|aac|ac3|dts|german|deutsch|dl|multi|remux)\b/i;

const upload = { targets: [], items: [], running: false, open: false, wakeLock: null };

function formatBytes(bytes) {
  const decimal = (value) => value.toFixed(1).replace(".", ",");
  if (bytes >= 1024 ** 4) return `${decimal(bytes / 1024 ** 4)} TB`;
  if (bytes >= 1024 ** 3) return `${decimal(bytes / 1024 ** 3)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  if (seconds < 60) return "noch < 1 Min";
  if (seconds < 3600) return `noch ${Math.round(seconds / 60)} Min`;
  return `noch ${Math.floor(seconds / 3600)} Std ${Math.round((seconds % 3600) / 60)} Min`;
}

// "The.Matrix.1999.1080p.BluRay.x264.mkv" -> Film "The Matrix", 1999
// "Dark.S02E05.German.720p.mkv"         -> Serie "Dark", Staffel 2
function guessFromName(filename) {
  let base = filename.replace(/\.[^.]+$/, "").replace(/[._]+/g, " ").replace(/\s+/g, " ").trim();
  const episode = base.match(/\bS(\d{1,2})\s?E\d{1,3}\b/i) || base.match(/\b(\d{1,2})x\d{2}\b/);
  if (episode) {
    const series = base.slice(0, episode.index).replace(/[-–(\[]+\s*$/, "").trim();
    return { kind: "tvshows", series: series || base, season: Number(episode[1]), title: base, year: "" };
  }
  const junk = base.search(UPLOAD_JUNK);
  if (junk > 0) base = base.slice(0, junk).trim();
  const year = base.match(/[(\[]?\b(19\d\d|20\d\d)\b[)\]]?/);
  let title = year && year.index > 0 ? base.slice(0, year.index) : base;
  title = title.replace(/[-–(\[]+\s*$/, "").trim() || base;
  return { kind: "movies", title, year: year ? year[1] : "", series: title, season: 1 };
}

function uploadTarget(kind) {
  return upload.targets.find((t) => t.kind === kind);
}

async function loadUploadTargets() {
  try {
    const data = await api.get("/api/remote/jellyfin/upload/targets");
    upload.targets = data.targets || [];
    $("up-free").textContent = data.free_bytes ? `${formatBytes(data.free_bytes)} frei auf der Platte` : "";
  } catch (err) {
    $("up-free").textContent = err.message;
  }
}

function openUpload() {
  upload.open = true;
  $("up-backdrop").classList.remove("hidden");
  $("up-sheet").classList.add("open");
  $("up-sheet").setAttribute("aria-hidden", "false");
  loadUploadTargets();
  renderUploads();
}

function closeUpload() {
  if (!upload.open) return;
  upload.open = false;
  $("up-sheet").classList.remove("open");
  $("up-sheet").setAttribute("aria-hidden", "true");
  $("up-backdrop").classList.add("hidden");
}

onTap($("up-open"), () => openUpload());
onTap($("up-close"), () => closeUpload());
$("up-backdrop").addEventListener("click", closeUpload);

$("up-input").addEventListener("change", () => {
  const files = [...$("up-input").files];
  $("up-input").value = "";
  for (const file of files) {
    upload.items.push({ file, status: "ready", received: 0, ...guessFromName(file.name) });
  }
  renderUploads();
});

function uploadField(item, key, placeholder, props = {}) {
  const input = h("input", { placeholder, autocomplete: "off", ...props });
  input.value = item[key] ?? "";
  input.addEventListener("input", () => {
    item[key] = input.value;
  });
  return input;
}

function uploadItemView(item, index) {
  const busy = item.status === "uploading";
  const head = h(
    "div",
    { class: "up-item-head" },
    h("div", { class: "up-item-name" }, item.file.name),
    h("div", { class: "up-item-size" }, formatBytes(item.file.size)),
    busy || item.status === "done"
      ? null
      : h(
          "button",
          {
            class: "up-remove",
            type: "button",
            "aria-label": "Entfernen",
            onclick: () => {
              if (item.id && item.status !== "done") api.del(`/api/remote/jellyfin/upload/${item.id}`).catch(() => {});
              upload.items.splice(index, 1);
              renderUploads();
            },
          },
          icon("close")
        )
  );
  const children = [head];

  if (item.status === "ready" || item.status === "error") {
    children.push(
      h(
        "div",
        { class: "up-kind" },
        ...[
          ["movies", "Film"],
          ["tvshows", "Serie"],
        ].map(([kind, label]) =>
          h(
            "button",
            {
              type: "button",
              class: item.kind === kind ? "active" : "",
              onclick: () => {
                item.kind = kind;
                renderUploads();
              },
            },
            label
          )
        )
      )
    );
    children.push(
      item.kind === "movies"
        ? h("div", { class: "up-fields" }, uploadField(item, "title", "Filmtitel"), uploadField(item, "year", "Jahr", { inputmode: "numeric", maxlength: "4" }))
        : h("div", { class: "up-fields" }, uploadField(item, "series", "Serie"), uploadField(item, "season", "Staffel", { inputmode: "numeric", maxlength: "2" }))
    );
  }

  if (item.status !== "ready") {
    const fraction = item.file.size ? item.received / item.file.size : 0;
    const bar = h("div", { class: "up-bar" }, h("span", { style: `width:${(fraction * 100).toFixed(1)}%` }));
    let left = `${Math.floor(fraction * 100)} %`;
    let right = "";
    if (item.status === "uploading") right = [item.speed ? `${formatBytes(item.speed)}/s` : "", formatEta(item.eta)].filter(Boolean).join(" · ");
    if (item.status === "queued") left = "Wartet …";
    if (item.status === "finishing") left = "Wird in Jellyfin eingetragen …";
    if (item.status === "done") left = `✓ In Jellyfin: ${item.result.name}`;
    if (item.status === "error") left = item.message;
    if (item.status !== "done") children.push(bar);
    children.push(h("div", { class: "up-status" }, h("span", null, left), h("span", null, right)));
    if (item.status === "done" && item.result.warning) children.push(h("div", { class: "up-warning" }, item.result.warning));
  }
  return h("div", { class: `up-item ${item.status}` }, ...children);
}

function renderUploads() {
  $("up-open").classList.toggle("busy", upload.running);
  if (!upload.open) return;
  $("up-list").replaceChildren(...upload.items.map(uploadItemView));
  const waiting = upload.items.filter((i) => i.status === "ready" || i.status === "error").length;
  $("up-start").classList.toggle("hidden", !waiting || upload.running);
  $("up-start-label").textContent = waiting > 1 ? `${waiting} Dateien hochladen` : "Hochladen";
}

async function putChunk(id, offset, blob) {
  const headers = { "Content-Type": "application/octet-stream" };
  const secret = getSecret();
  if (secret) headers["X-Remote-Secret"] = secret;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_CHUNK_TIMEOUT_MS);
  try {
    const resp = await fetch(`/api/remote/jellyfin/upload/${id}?offset=${offset}`, {
      method: "PUT",
      headers,
      body: blob,
      signal: controller.signal,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(data.detail || `Fehler ${resp.status}`);
      err.fatal = resp.status === 400;
      throw err;
    }
    return data.received;
  } finally {
    clearTimeout(timer);
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function uploadOne(item) {
  const target = uploadTarget(item.kind);
  if (!target) throw new Error("Jellyfin-Bibliothek nicht gefunden");
  const started = await api.post("/api/remote/jellyfin/upload", {
    target: target.id,
    filename: item.file.name,
    size: item.file.size,
    modified: item.file.lastModified,
    title: item.title,
    year: item.year,
    series: item.series,
    season: item.season,
  });
  item.id = started.id;
  item.received = started.received;
  item.status = "uploading";
  renderUploads();

  let retries = 0;
  let windowStart = performance.now();
  let windowBytes = 0;
  while (item.received < item.file.size) {
    const end = Math.min(item.file.size, item.received + UPLOAD_CHUNK_BYTES);
    const before = item.received;
    try {
      item.received = await putChunk(item.id, item.received, item.file.slice(item.received, end));
      retries = 0;
    } catch (err) {
      if (err.fatal || ++retries > UPLOAD_MAX_RETRIES) throw err;
      await sleep(1500 * retries);
      continue;
    }
    windowBytes += Math.max(0, item.received - before);
    const elapsed = (performance.now() - windowStart) / 1000;
    if (elapsed >= 2) {
      item.speed = windowBytes / elapsed;
      item.eta = (item.file.size - item.received) / item.speed;
      windowStart = performance.now();
      windowBytes = 0;
    }
    renderUploads();
  }

  item.status = "finishing";
  renderUploads();
  item.result = await api.post(`/api/remote/jellyfin/upload/${item.id}/finish`);
  item.status = "done";
}

async function keepAwake(on) {
  try {
    if (on && !upload.wakeLock && navigator.wakeLock) upload.wakeLock = await navigator.wakeLock.request("screen");
    if (!on && upload.wakeLock) {
      await upload.wakeLock.release();
      upload.wakeLock = null;
    }
  } catch (err) {
    // Bildschirmsperre nicht verfuegbar - dann eben ohne
  }
}

async function runUploads() {
  if (upload.running) return;
  if (!upload.targets.length) await loadUploadTargets();
  document.activeElement.blur();
  upload.items.forEach((i) => {
    if (i.status === "ready" || i.status === "error") i.status = "queued";
  });
  upload.running = true;
  keepAwake(true);
  renderUploads();
  let done = 0;
  for (const item of upload.items) {
    if (item.status !== "queued") continue;
    try {
      await uploadOne(item);
      done += 1;
    } catch (err) {
      item.status = "error";
      item.message = err.message || "Upload fehlgeschlagen";
    }
    renderUploads();
  }
  upload.running = false;
  keepAwake(false);
  renderUploads();
  loadUploadTargets();
  if (done) {
    toast(done === 1 ? "Upload fertig – Jellyfin liest die Datei ein" : `${done} Uploads fertig – Jellyfin liest sie ein`);
    // Neue Filme erscheinen nach dem Einlesen (dauert ein paar Sekunden)
    setTimeout(() => {
      if (currentView === "jellyfin") jellyfinLoadHome();
    }, 8000);
  }
}

onTap($("up-start"), () => runUploads());

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && upload.running) keepAwake(true);
});

window.addEventListener("beforeunload", (event) => {
  if (upload.running) event.preventDefault();
});

// ---------- Radio ----------

let stations = [];
let radioRenderKey = "";

function stationInitials(name) {
  const words = name.replace(/[^\p{L}\p{N} ]/gu, " ").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

async function loadStations() {
  try {
    const data = await api.get("/api/remote/radio/stations");
    stations = data.stations || [];
    radioRenderKey = "";
    renderRadio();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderRadio() {
  const radioState = state.radio || {};
  const playing = !!radioState.playing;
  const currentId = radioState.station ? radioState.station.id : null;
  const key = `${playing}|${currentId}|${stations.map((s) => s.id).join(",")}`;
  if (key === radioRenderKey) return;
  radioRenderKey = key;

  $("radio-hero").classList.toggle("playing", playing);
  $("radio-station").textContent = radioState.station ? radioState.station.name : "Kein Sender";
  $("radio-status").textContent = playing ? "Live · läuft" : "Gestoppt";
  setIcon($("radio-toggle"), playing ? "stop" : "play", playing ? "Stoppen" : "Abspielen");

  $("station-list").replaceChildren(
    ...stations.map((station) => {
      const active = playing && station.id === currentId;
      let sub = "Live-Stream";
      if (active) sub = "Läuft gerade";
      else if (station.id === currentId) sub = "Zuletzt gehört";
      return h(
        "button",
        { class: `row${active ? " active" : ""}`, type: "button", onclick: () => playStation(station) },
        h("span", { class: "row-badge" }, stationInitials(station.name)),
        h("span", { class: "row-main" }, h("div", null, station.name), h("div", { class: "row-sub" }, sub)),
        active ? h("span", { class: "playing" }, h("span", { class: "eq" }, h("span"), h("span"), h("span"))) : null
      );
    })
  );
}

async function playStation(station) {
  try {
    await api.post("/api/remote/radio", { action: "play", station_id: station.id });
    toast(`${station.name} läuft`);
    poll();
  } catch (err) {
    toast(err.message, true);
  }
}

onTap($("radio-toggle"), async () => {
  const radioState = state.radio || {};
  if (radioState.playing) {
    await api.post("/api/remote/radio", { action: "stop" });
    toast("Radio gestoppt");
  } else {
    const station = radioState.station || stations[0];
    if (!station) throw new Error("Noch kein Sender angelegt");
    await api.post("/api/remote/radio", { action: "play", station_id: station.id });
    toast(`${station.name} läuft`);
  }
  poll();
});

// ---------- Plattenschrank ----------

const VINYL_SEARCH_DEBOUNCE_MS = 400;
const vinyl = {
  lib: null,
  renderKey: "",
  titleKey: "",
  lastErrorId: null,
  scrubbing: false,
  sheetOpen: false,
  add: null,
  lastGenre: null,
};
let vinylSearchTimer = null;

async function loadVinyl() {
  try {
    vinyl.lib = await api.get("/api/remote/vinyl/library");
    vinyl.renderKey = "";
    renderCabinets();
  } catch (err) {
    toast(err.message, true);
  }
}

function playingRecordId() {
  const vy = state.vinyl || {};
  return vy.active && vy.record ? vy.record.id : null;
}

function coverUrl(url) {
  return url ? `url("${url.replace(/"/g, "%22")}")` : "";
}

// Huelle mit herausschauender Platte (Schrank + Sheet)
function sleeveMedia(record) {
  const art = h("div", { class: `sleeve-art${record.cover ? " has-cover" : ""}` }, h("span", null, record.album));
  art.style.backgroundImage = coverUrl(record.cover);
  return h("div", { class: "sleeve-media", style: `--label:${record.color || "#b8452e"}` }, h("div", { class: "sleeve-disc" }), art);
}

function renderCabinets() {
  if (!vinyl.lib) return;
  const playingId = playingRecordId();
  const key = `${JSON.stringify(vinyl.lib)}|${playingId}`;
  if (key === vinyl.renderKey) return;
  vinyl.renderKey = key;

  const { genres, records } = vinyl.lib;
  $("vy-cabinets").replaceChildren(
    ...genres.map((genre) => {
      const inside = records.filter((r) => r.genre === genre.id);
      const songCount = inside.reduce((n, r) => n + r.songs.length, 0);
      const crate = inside.length
        ? h(
            "div",
            { class: "crate" },
            ...inside.map((record) => {
              const el = h(
                "button",
                { class: `sleeve${record.id === playingId ? " playing" : ""}`, type: "button", onclick: () => openRecordSheet(record) },
                sleeveMedia(record),
                h("div", { class: "sleeve-title" }, record.album),
                h("div", { class: "sleeve-artist" }, record.artist)
              );
              return el;
            })
          )
        : h("div", { class: "crate-empty" }, "Noch leer – stell eine Platte hinein.");
      return h(
        "div",
        { class: "cabinet" },
        h(
          "div",
          { class: "cabinet-head" },
          h(
            "div",
            { class: "brass-plate" },
            h("span", { class: "plate-name" }, genre.name),
            h("span", { class: "plate-count" }, `${inside.length} ${inside.length === 1 ? "Platte" : "Platten"} · ${songCount} Songs`)
          ),
          h(
            "div",
            { class: "cabinet-actions" },
            inside.length
              ? h("button", { class: "knob-btn", type: "button", "aria-label": `${genre.name} abspielen`, onclick: () => playVinyl({ genre_id: genre.id }) }, icon("play"))
              : null,
            inside.length
              ? h("button", { class: "knob-btn", type: "button", "aria-label": `${genre.name} mischen`, onclick: () => playVinyl({ genre_id: genre.id, shuffle: true }) }, icon("shuffle"))
              : null,
            h("button", { class: "knob-btn", type: "button", "aria-label": `${genre.name} bearbeiten`, onclick: () => openCabinetSheet(genre) }, icon("more"))
          )
        ),
        h("div", { class: "cabinet-body" }, crate, h("div", { class: "shelf" }))
      );
    })
  );
}

async function playVinyl(body) {
  try {
    toast(state.tv_on ? "Platte wird aufgelegt …" : "Fernseher wird eingeschaltet …");
    await api.post("/api/remote/vinyl", { action: "play", ...body });
    closeVinylSheet();
    poll();
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- Plattenschrank: Hi-Fi-Deck ----------

function renderVinylNow() {
  const vy = state.vinyl || {};
  const active = !!(vy.active && vy.record);
  $("hifi").classList.toggle("hidden", !active);
  if (vinyl.lib && currentView === "vinyl") renderCabinets();

  const error = state.vinyl_error;
  if (error) {
    if (vinyl.lastErrorId !== null && error.id !== vinyl.lastErrorId && error.message) toast(error.message, true);
    vinyl.lastErrorId = error.id;
  }
  if (!active) return;

  $("hifi").classList.toggle("playing", !!vy.playing);
  $("vfd-track").textContent = `${pad(vy.position + 1)}/${pad(vy.queue_length)}`;
  $("vfd-state").textContent = vy.playing ? "▶ PLAY" : "❚❚ PAUSE";
  $("vfd-time").textContent = formatTime(vy.current_time);
  $("vfd-sub").textContent = `${vy.artist} · ${vy.record.album}`;
  setIcon($("hifi-toggle"), vy.playing ? "pause" : "play", vy.playing ? "Pause" : "Play");

  const disc = $("hifi-disc");
  disc.style.setProperty("--label", vy.record.color || "#b8452e");
  disc.firstElementChild.style.backgroundImage = coverUrl(vy.record.cover);

  const titleKey = `${vy.title}|${vy.position}`;
  if (titleKey !== vinyl.titleKey) {
    vinyl.titleKey = titleKey;
    const box = document.querySelector(".vfd-title");
    const span = $("vfd-title");
    span.textContent = vy.title;
    box.classList.remove("scroll");
    requestAnimationFrame(() => {
      const overflow = span.scrollWidth - box.clientWidth;
      if (overflow > 0) {
        box.style.setProperty("--scroll-by", `${-(overflow + 40)}px`);
        box.style.setProperty("--scroll-s", `${Math.max(6, overflow / 18)}s`);
        box.classList.add("scroll");
      }
    });
  }

  const range = $("hifi-progress");
  const max = Math.max(0, Math.floor(vy.duration || 0));
  if (Number(range.max) !== max) range.max = String(max);
  if (!vinyl.scrubbing) range.value = String(Math.min(Math.floor(vy.current_time || 0), max));
  range.style.setProperty("--pct", `${max > 0 ? (Number(range.value) / max) * 100 : 0}%`);
}

$("hifi-progress").addEventListener("input", () => {
  vinyl.scrubbing = true;
  const range = $("hifi-progress");
  const max = Number(range.max) || 0;
  range.style.setProperty("--pct", `${max > 0 ? (Number(range.value) / max) * 100 : 0}%`);
  $("vfd-time").textContent = formatTime(Number(range.value));
});

$("hifi-progress").addEventListener("change", async () => {
  try {
    await api.post("/api/remote/vinyl", { action: "seek_to", seconds: Number($("hifi-progress").value) });
  } catch (err) {
    toast(err.message, true);
  } finally {
    vinyl.scrubbing = false;
  }
});

onTap($("hifi-toggle"), () => togglePlayback("vinyl"));
onTap($("hifi-prev"), async () => {
  await api.post("/api/remote/vinyl", { action: "prev" });
  poll();
});
onTap($("hifi-next"), async () => {
  await api.post("/api/remote/vinyl", { action: "next" });
  poll();
});
onTap($("hifi-stop"), async () => {
  await api.post("/api/remote/vinyl", { action: "stop" });
  toast("Platte gestoppt");
  poll();
});
onTap($("vy-shuffle-all"), () => playVinyl({ shuffle: true }));

// ---------- Plattenschrank: Sheet ----------

function openVinylSheet(...children) {
  $("vy-sheet-body").replaceChildren(...children);
  if (!vinyl.sheetOpen) {
    vinyl.sheetOpen = true;
    $("vy-sheet-backdrop").classList.remove("hidden");
    $("vy-sheet").classList.add("open");
    $("vy-sheet").setAttribute("aria-hidden", "false");
  }
  $("vy-sheet").scrollTop = 0;
}

function closeVinylSheet() {
  if (!vinyl.sheetOpen) return;
  vinyl.sheetOpen = false;
  vinyl.add = null;
  clearTimeout(vinylSearchTimer);
  $("vy-sheet").classList.remove("open");
  $("vy-sheet").setAttribute("aria-hidden", "true");
  $("vy-sheet-backdrop").classList.add("hidden");
}

onTap($("vy-sheet-close"), () => closeVinylSheet());
$("vy-sheet-backdrop").addEventListener("click", closeVinylSheet);

function openRecordSheet(record) {
  const playing = state.vinyl && state.vinyl.active && state.vinyl.record && state.vinyl.record.id === record.id;
  const meta = [record.artist, record.year].filter(Boolean).join(" · ");
  const tracks = record.songs.map((song, index) =>
    h(
      "button",
      {
        class: `rs-track${song.youtube ? "" : " missing"}${playing && state.vinyl.song_index === index ? " current" : ""}`,
        type: "button",
        onclick: () =>
          song.youtube ? playVinyl({ record_id: record.id, song_index: index }) : toast("Für diesen Song wurde kein YouTube-Video gefunden", true),
      },
      h("span", { class: "rs-nr" }, pad(index + 1)),
      h("span", { class: "rs-track-main" }, h("div", null, song.title), song.artist ? h("div", { class: "rs-track-sub" }, song.artist) : null),
      icon(song.youtube ? "play" : "close")
    )
  );
  const select = h(
    "select",
    { class: "rs-select", "aria-label": "Schrank" },
    ...vinyl.lib.genres.map((g) => h("option", { value: g.id, selected: g.id === record.genre }, g.name))
  );
  select.addEventListener("change", async () => {
    try {
      await api.patch(`/api/remote/vinyl/records/${encodeURIComponent(record.id)}`, { genre: select.value });
      const genre = vinyl.lib.genres.find((g) => g.id === select.value);
      toast(`Steht jetzt im Schrank „${genre ? genre.name : ""}“`);
      loadVinyl();
    } catch (err) {
      toast(err.message, true);
    }
  });

  openVinylSheet(
    h("div", { class: "rs-hero" }, sleeveMedia(record)),
    h("div", { class: "retro-kicker" }, `${record.songs.length} ${record.songs.length === 1 ? "Lieblingssong" : "Lieblingssongs"}`),
    h("div", { class: "rs-title" }, record.album),
    h("div", { class: "rs-meta" }, meta),
    h(
      "div",
      { class: "rs-actions" },
      h("button", { class: "retro-btn retro-btn-accent", type: "button", onclick: () => playVinyl({ record_id: record.id }) }, icon("vinyl"), "Platte auflegen"),
      h("button", { class: "retro-btn", type: "button", onclick: () => playVinyl({ record_id: record.id, shuffle: true }) }, icon("shuffle"), "Mischen")
    ),
    h("div", { class: "rs-list" }, ...tracks),
    h("div", { class: "rs-section" }, "Steht im Schrank"),
    h(
      "div",
      { class: "rs-manage" },
      select,
      h(
        "button",
        {
          class: "rs-danger",
          type: "button",
          "aria-label": "Platte entfernen",
          onclick: async () => {
            if (!window.confirm(`„${record.album}“ aus dem Schrank nehmen?`)) return;
            try {
              await api.del(`/api/remote/vinyl/records/${encodeURIComponent(record.id)}`);
              toast("Platte entfernt");
              closeVinylSheet();
              loadVinyl();
            } catch (err) {
              toast(err.message, true);
            }
          },
        },
        icon("trash")
      )
    )
  );
}

function openCabinetSheet(genre) {
  const count = vinyl.lib.records.filter((r) => r.genre === genre.id).length;
  openVinylSheet(
    h("div", { class: "retro-kicker" }, "Schrank"),
    h("div", { class: "rs-title" }, genre.name),
    h("div", { class: "rs-meta" }, `${count} ${count === 1 ? "Platte" : "Platten"}`),
    h(
      "button",
      {
        class: "retro-btn retro-btn-block",
        type: "button",
        onclick: async () => {
          const name = window.prompt("Neuer Name für den Schrank:", genre.name);
          if (!name || name.trim() === genre.name) return;
          try {
            await api.patch(`/api/remote/vinyl/genres/${encodeURIComponent(genre.id)}`, { name });
            toast("Schrank umbenannt");
            closeVinylSheet();
            loadVinyl();
          } catch (err) {
            toast(err.message, true);
          }
        },
      },
      "Umbenennen"
    ),
    h(
      "button",
      {
        class: "retro-btn retro-btn-block retro-btn-ghost",
        type: "button",
        onclick: async () => {
          if (count) {
            toast("Erst die Platten in einen anderen Schrank stellen oder entfernen", true);
            return;
          }
          if (!window.confirm(`Schrank „${genre.name}“ abbauen?`)) return;
          try {
            await api.del(`/api/remote/vinyl/genres/${encodeURIComponent(genre.id)}`);
            toast("Schrank abgebaut");
            closeVinylSheet();
            loadVinyl();
          } catch (err) {
            toast(err.message, true);
          }
        },
      },
      icon("trash"),
      "Schrank abbauen"
    )
  );
}

async function createCabinet() {
  const name = window.prompt("Name des neuen Schranks (z. B. Hip-Hop, Klassik):");
  if (!name || !name.trim()) return null;
  const genre = await api.post("/api/remote/vinyl/genres", { name });
  vinyl.lib = await api.get("/api/remote/vinyl/library");
  vinyl.renderKey = "";
  renderCabinets();
  toast(`Schrank „${genre.name}“ steht bereit`);
  return genre;
}

onTap($("vy-new-cabinet"), () => createCabinet());

// ---------- Plattenschrank: neue Platte hinzufuegen ----------
// Suche (iTunes) → Album mit Tracklist → Lieblingssongs + Schrank waehlen →
// der Pi sucht zu jedem Song das YouTube-Video und stellt die Platte ein.

onTap($("vy-add"), () => {
  vinyl.add = { kind: "album", term: "", results: [], seq: 0, album: null, selected: new Set(), genre: vinyl.lastGenre };
  renderAddSearch();
  setTimeout(() => {
    const input = $("vy-add-input");
    if (input) input.focus();
  }, 350);
});

function renderAddSearch() {
  const add = vinyl.add;
  const input = h("input", {
    id: "vy-add-input",
    type: "search",
    placeholder: add.kind === "album" ? "Album oder Künstler suchen" : "Songtitel oder Künstler suchen",
    autocomplete: "off",
    enterkeyhint: "search",
  });
  input.value = add.term;
  input.addEventListener("input", () => {
    clearTimeout(vinylSearchTimer);
    vinylSearchTimer = setTimeout(() => runAddSearch(input.value.trim()), VINYL_SEARCH_DEBOUNCE_MS);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") input.blur();
  });

  const seg = h(
    "div",
    { class: "rs-seg" },
    ...[
      ["album", "Album"],
      ["song", "Einzelner Song"],
    ].map(([kind, label]) =>
      h(
        "button",
        {
          type: "button",
          class: add.kind === kind ? "active" : "",
          onclick: () => {
            if (add.kind === kind) return;
            add.kind = kind;
            add.results = [];
            renderAddSearch();
            if (add.term) runAddSearch(add.term, true);
          },
        },
        label
      )
    )
  );

  openVinylSheet(
    h("div", { class: "retro-kicker" }, "Neue Platte"),
    h("div", { class: "rs-title" }, "Was kommt in den Schrank?"),
    seg,
    h("label", { class: "field" }, icon("search"), input),
    h("div", { class: "rs-list", id: "vy-add-results" })
  );
  renderAddResults();
}

async function runAddSearch(term, force = false) {
  const add = vinyl.add;
  if (!add || (term === add.term && !force)) return;
  add.term = term;
  const seq = ++add.seq;
  if (!term) {
    add.results = [];
    renderAddResults();
    return;
  }
  const box = $("vy-add-results");
  if (box) box.replaceChildren(h("div", { class: "rs-empty" }, "Suche …"));
  try {
    const data = await api.get(`/api/remote/vinyl/search?kind=${add.kind}&q=${encodeURIComponent(term)}`);
    if (vinyl.add !== add || seq !== add.seq) return;
    add.results = data.results || [];
    renderAddResults();
  } catch (err) {
    if (vinyl.add === add) toast(err.message, true);
  }
}

function renderAddResults() {
  const add = vinyl.add;
  const box = $("vy-add-results");
  if (!add || !box) return;
  if (!add.term) {
    box.replaceChildren(h("div", { class: "rs-empty" }, "Tipp: Albumname und Künstler zusammen finden am schnellsten."));
    return;
  }
  if (!add.results.length) {
    box.replaceChildren(h("div", { class: "rs-empty" }, `Nichts gefunden für „${add.term}“.`));
    return;
  }
  box.replaceChildren(
    ...add.results.map((result) => {
      const thumb = h("span", { class: "rs-thumb" });
      thumb.style.backgroundImage = coverUrl(result.cover);
      const title = result.song ? result.song.title : result.album;
      const sub = result.song
        ? `${result.song.artist} · ${result.album}`
        : [result.artist, result.year, result.track_count ? `${result.track_count} Titel` : null].filter(Boolean).join(" · ");
      return h(
        "button",
        { class: "rs-result", type: "button", onclick: () => openAddAlbum(result) },
        thumb,
        h("span", { class: "rs-track-main" }, h("div", { class: "rs-result-title" }, title), h("div", { class: "rs-result-sub" }, sub))
      );
    })
  );
}

async function openAddAlbum(result) {
  const add = vinyl.add;
  openVinylSheet(h("div", { class: "rs-busy" }, h("div", { class: "hifi-disc" }, h("span")), "Tracklist wird geladen …"));
  try {
    const album = await api.get(`/api/remote/vinyl/album/${encodeURIComponent(result.collection_id)}`);
    if (vinyl.add !== add) return;
    add.album = album;
    add.selected = new Set();
    if (result.song) {
      const index = album.tracks.findIndex((t) => t.title === result.song.title);
      if (index >= 0) add.selected.add(index);
    }
    if (!add.genre && vinyl.lib && vinyl.lib.genres.length) add.genre = vinyl.lib.genres[0].id;
    renderAddAlbum();
  } catch (err) {
    toast(err.message, true);
    renderAddSearch();
  }
}

function renderAddAlbum() {
  const add = vinyl.add;
  const album = add.album;
  const record = { album: album.album, cover: album.cover, color: "#b8452e" };

  const tracks = album.tracks.map((track, index) =>
    h(
      "button",
      {
        class: `rs-track${add.selected.has(index) ? " selected" : ""}`,
        type: "button",
        onclick: () => {
          if (add.selected.has(index)) add.selected.delete(index);
          else add.selected.add(index);
          renderAddAlbum();
        },
      },
      h("span", { class: "rs-check" }, icon("check")),
      h(
        "span",
        { class: "rs-track-main" },
        h("div", null, track.title),
        track.artist && track.artist !== album.artist ? h("div", { class: "rs-track-sub" }, track.artist) : null
      ),
      h("span", { class: "rs-nr" }, track.seconds ? formatTime(track.seconds) : "")
    )
  );

  const genres = (vinyl.lib ? vinyl.lib.genres : []).map((genre) =>
    h(
      "button",
      {
        class: `rs-chip${add.genre === genre.id ? " active" : ""}`,
        type: "button",
        onclick: () => {
          add.genre = genre.id;
          renderAddAlbum();
        },
      },
      genre.name
    )
  );
  genres.push(
    h(
      "button",
      {
        class: "rs-chip new",
        type: "button",
        onclick: async () => {
          try {
            const genre = await createCabinet();
            if (genre && vinyl.add === add) {
              add.genre = genre.id;
              renderAddAlbum();
            }
          } catch (err) {
            toast(err.message, true);
          }
        },
      },
      "+ Neuer Schrank"
    )
  );

  const count = add.selected.size;
  const allSelected = count === album.tracks.length;
  const save = h(
    "button",
    { class: "retro-btn retro-btn-accent retro-btn-block", type: "button", onclick: saveAddAlbum },
    icon("vinyl"),
    count ? `In den Schrank stellen (${count})` : "Songs auswählen"
  );
  save.disabled = !count || !add.genre;
  const scrollTop = $("vy-sheet").scrollTop;

  openVinylSheet(
    h("button", { class: "retro-back", type: "button", onclick: renderAddSearch }, icon("back"), "Zur Suche"),
    h("div", { class: "rs-hero" }, sleeveMedia(record)),
    h("div", { class: "rs-title" }, album.album),
    h("div", { class: "rs-meta" }, [album.artist, album.year].filter(Boolean).join(" · ")),
    h(
      "div",
      { class: "rs-section", style: "display:flex;justify-content:space-between;align-items:center" },
      "Deine Lieblingssongs",
      h(
        "button",
        {
          class: "rs-chip",
          type: "button",
          onclick: () => {
            add.selected = allSelected ? new Set() : new Set(album.tracks.map((_, i) => i));
            renderAddAlbum();
          },
        },
        allSelected ? "Keine" : "Alle"
      )
    ),
    h("div", { class: "rs-list" }, ...tracks),
    h("div", { class: "rs-section" }, "In welchen Schrank?"),
    h("div", { class: "rs-chips" }, ...genres),
    h("div", { class: "rs-footer" }, save)
  );
  // Beim Antippen einzelner Songs nicht jedes Mal nach oben springen
  $("vy-sheet").scrollTop = scrollTop;
}

async function saveAddAlbum() {
  const add = vinyl.add;
  const album = add.album;
  const songs = [...add.selected].sort((a, b) => a - b).map((i) => ({ title: album.tracks[i].title, artist: album.tracks[i].artist }));
  vinyl.lastGenre = add.genre;
  openVinylSheet(
    h(
      "div",
      { class: "rs-busy" },
      h("div", { class: "hifi-disc" }, h("span")),
      h("div", { class: "rs-title" }, "Einen Moment …"),
      h("div", null, `Jarvis sucht ${songs.length === 1 ? "den Song" : `die ${songs.length} Songs`} auf YouTube.`)
    )
  );
  try {
    const record = await api.post("/api/remote/vinyl/records", {
      album: album.album,
      artist: album.artist,
      year: album.year,
      cover: album.cover,
      genre: add.genre,
      songs,
    });
    const missing = record.songs.filter((s) => !s.youtube).length;
    const genre = vinyl.lib.genres.find((g) => g.id === record.genre);
    toast(
      missing ? `${missing} Song(s) ohne YouTube-Video – die übrigen stehen im Schrank` : `„${record.album}“ steht jetzt in „${genre ? genre.name : ""}“`,
      missing > 0
    );
    closeVinylSheet();
    loadVinyl();
  } catch (err) {
    toast(err.message, true);
    if (vinyl.add === add) renderAddAlbum();
  }
}

// ---------- Uhr & Timer ----------
// Den Timer fuehrt der Server; hier wird nur aus der gemeldeten Restzeit
// weitergezaehlt. Laeuft er ab, pausiert der Server alles und der Fernseher
// piept - bis die Fernbedienung geoeffnet wird (dann "ack").

const TIMER_PRESETS = [1, 3, 5, 10, 15, 20, 30, 60];
const TIMER_FINAL_SECONDS = 10;
// "Geoeffnet" = Seite neu geladen oder aus dem Hintergrund geholt. War sie
// die ganze Zeit offen (iPad auf dem Tisch), piept es bis zum ersten Tippen.
const TIMER_ACK_WINDOW_MS = 8000;

let timerEndsAt = 0;
let timerSource = null;
let timerAckedId = null;
let remoteOpenedAt = Date.now();

function timerInfo() {
  return state.timer || { state: "idle", duration: 0, remaining_ms: 0 };
}

function formatCountdown(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours ? `${hours}:${pad(minutes)}:${pad(total % 60)}` : `${minutes}:${pad(total % 60)}`;
}

function timerLabel(seconds) {
  if (seconds < 60) return `${seconds}-Sekunden-Timer`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (!hours) return `${minutes}-Minuten-Timer`;
  return minutes ? `Timer · ${hours} Std ${minutes} Min` : `${hours}-Stunden-Timer`;
}

function timerRemaining(t) {
  if (t.state === "running") return Math.max(0, (timerEndsAt - performance.now()) / 1000);
  if (t.state === "paused") return (t.remaining_ms || 0) / 1000;
  return 0;
}

function applyTimer(timer) {
  state.timer = timer;
  syncTimerFromState();
}

function syncTimerFromState() {
  const t = timerInfo();
  if (t !== timerSource) {
    timerSource = t;
    timerEndsAt = performance.now() + (t.remaining_ms || 0);
  }
  renderTimer();
}

function renderTimer() {
  const t = timerInfo();
  const active = t.state === "running" || t.state === "paused";
  const remaining = timerRemaining(t);
  const fraction = t.duration > 0 ? Math.min(1, remaining / t.duration) : 0;
  const final = t.state === "running" && remaining <= TIMER_FINAL_SECONDS;

  const pill = $("timer-pill");
  pill.classList.toggle("hidden", !active);
  pill.classList.toggle("paused", t.state === "paused");
  pill.classList.toggle("final", final);
  $("timer-pill-time").textContent = formatCountdown(remaining);

  if (currentView === "clock") {
    $("timer-setup").classList.toggle("hidden", active);
    $("timer-run").classList.toggle("hidden", !active);
    $("timer-run").classList.toggle("paused", t.state === "paused");
    $("timer-run").classList.toggle("final", final);
    if (active) {
      $("timer-countdown").textContent = formatCountdown(remaining);
      $("timer-ring-fill").style.strokeDashoffset = String(Math.round(1000 * (1 - fraction)));
      $("timer-label").textContent = timerLabel(t.duration);
      const end = new Date(Date.now() + remaining * 1000);
      $("timer-sub").textContent = t.state === "paused" ? "Pausiert" : `Fertig um ${pad(end.getHours())}:${pad(end.getMinutes())}`;
      setIcon($("timer-toggle"), t.state === "paused" ? "play" : "pause", t.state === "paused" ? "Weiter" : "Pause");
    }
    const full = $("ck-fullscreen");
    full.classList.toggle("active", !!t.clock_screen);
    setIcon(full, "tv", t.clock_screen ? "Vollbild beenden" : "Auf dem Fernseher zeigen");
  }

  const ringing = t.state === "ringing";
  $("timer-modal").classList.toggle("hidden", !ringing);
  if (ringing) {
    $("tm-label").textContent = timerLabel(t.duration);
    $("tm-restart-label").textContent = `Neu starten · ${formatCountdown(t.duration)}`;
    const justOpened = Date.now() - remoteOpenedAt < TIMER_ACK_WINDOW_MS && document.visibilityState === "visible";
    if (!t.acknowledged && justOpened) acknowledgeTimer();
  }
}

// Fernbedienung ist offen -> Alarmton auf dem Fernseher aus
function acknowledgeTimer() {
  const t = timerInfo();
  if (t.state !== "ringing" || t.acknowledged || timerAckedId === t.id) return;
  timerAckedId = t.id;
  apiRequest("POST", "/api/remote/timer", { action: "ack" }, { quiet: true }).catch(() => {
    timerAckedId = null;
  });
}

function tickClock() {
  if (currentView === "clock") {
    const now = new Date();
    $("ck-hm").textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    $("ck-sec").textContent = pad(now.getSeconds());
    $("ck-date").textContent = `${WEEKDAYS[now.getDay()]}, ${now.getDate()}. ${MONTHS[now.getMonth()]}`;
  }
  const t = timerInfo();
  if (t.state === "running" || currentView === "clock") renderTimer();
}

async function timerAction(body, message) {
  const result = await api.post("/api/remote/timer", body);
  applyTimer(result.timer);
  if (message) toast(message);
}

async function startTimer(seconds) {
  const message = state.tv_on ? "Timer läuft auf dem Fernseher" : "Fernseher wird eingeschaltet …";
  await timerAction({ action: "start", seconds }, message);
}

$("timer-presets").replaceChildren(
  ...TIMER_PRESETS.map((minutes) =>
    h(
      "button",
      { class: "timer-preset", type: "button", onclick: () => startTimer(minutes * 60).catch((err) => toast(err.message, true)) },
      minutes >= 60 ? String(minutes / 60) : String(minutes),
      h("small", null, minutes >= 60 ? "Std" : "Min")
    )
  )
);

onTap($("timer-start"), () => {
  const minutes = Math.max(0, Math.floor(Number($("timer-min").value) || 0));
  const seconds = Math.max(0, Math.min(59, Math.floor(Number($("timer-sec").value) || 0)));
  const total = minutes * 60 + seconds;
  if (!total) throw new Error("Bitte eine Zeit eingeben");
  document.activeElement.blur();
  return startTimer(total);
});

["timer-min", "timer-sec"].forEach((id) =>
  $(id).addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("timer-start").click();
  })
);

onTap($("timer-toggle"), () => timerAction({ action: timerInfo().state === "paused" ? "resume" : "pause" }));
onTap($("timer-add"), () => timerAction({ action: "add", seconds: 60 }, "+1 Minute"));
onTap($("timer-cancel"), () => timerAction({ action: "cancel" }, "Timer gestoppt"));
onTap($("timer-pill"), () => openView("clock"));

onTap($("ck-fullscreen"), async () => {
  const show = !timerInfo().clock_screen;
  const result = await api.post("/api/remote/clock", { show });
  applyTimer(result.timer);
  if (show) toast(state.tv_on ? "Uhr im Vollbild" : "Fernseher wird eingeschaltet …");
});

$("timer-modal").addEventListener("pointerdown", acknowledgeTimer);
onTap($("tm-stop"), () => timerAction({ action: "dismiss" }, "Timer beendet"));
onTap($("tm-restart"), () => timerAction({ action: "restart" }, "Timer läuft wieder"));

setInterval(tickClock, 250);

// ---------- Licht ----------

const LIGHT_SWATCHES = [
  ["Rot", "#ff1a1a"],
  ["Orange", "#ff5a00"],
  ["Warmweiß", "#ff9a3c"],
  ["Weiß", "#ffffff"],
  ["Grün", "#00ff4c"],
  ["Cyan", "#00e1ff"],
  ["Blau", "#1a3bff"],
  ["Lila", "#9a2bff"],
  ["Pink", "#ff2bb4"],
];
// Standlicht steht mit in der Soft-Gruppe, sonst stuende es allein in einer Zeile
const LIGHT_GROUPS = [
  { id: "soft", name: "Soft", sub: "Standlicht & weiche Verläufe", members: ["static", "soft"] },
  { id: "hard", name: "Hard", sub: "harte Wechsel auf dem Schlag", members: ["hard"] },
  { id: "ramp", name: "Ramp", sub: "dimmt im Takt hoch", members: ["ramp"] },
];
const LIGHT_HOLD_MS = 2000;
const LIGHT_THROTTLE_MS = 90;
const TAP_RESET_MS = 2000;
const TAP_MAX = 8;
const BPM_MIN = 40;
const BPM_MAX = 220;

let light = null;
let lightEffects = [];
let lightHoldUntil = 0;
let lightSeq = 0;
let lightDragging = null;
let taps = [];

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

function clampBpm(bpm) {
  return Math.min(BPM_MAX, Math.max(BPM_MIN, Math.round(bpm)));
}

// Regler senden waehrend des Ziehens hoechstens alle LIGHT_THROTTLE_MS
function throttle(fn, ms) {
  let last = 0;
  let timer = null;
  let pending;
  return (arg) => {
    pending = arg;
    const wait = last + ms - Date.now();
    if (wait <= 0) {
      last = Date.now();
      fn(pending);
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = null;
        last = Date.now();
        fn(pending);
      }, wait);
    }
  };
}

async function lightSend(changes) {
  if (!light) return;
  // Sofort anzeigen; der Status-Poll darf den lokalen Stand kurz nicht ueberschreiben
  lightHoldUntil = Date.now() + LIGHT_HOLD_MS;
  const { tap, ...visible } = changes;
  Object.assign(light, visible);
  renderLight();
  const seq = ++lightSeq;
  try {
    const result = await api.post("/api/remote/light", changes);
    if (seq === lightSeq) {
      light = result;
      renderLight();
    }
  } catch (err) {
    toast(err.message, true);
  }
}

const sendThrottled = throttle(lightSend, LIGHT_THROTTLE_MS);

async function loadLight() {
  try {
    const data = await api.get("/api/remote/light");
    const { effects, ...rest } = data;
    if (!lightEffects.length) {
      lightEffects = effects || [];
      buildEffectTiles();
    }
    light = rest;
    renderLight();
  } catch (err) {
    toast(err.message, true);
  }
}

function buildSwatches() {
  const custom = h("input", { type: "color", id: "light-custom", "aria-label": "Eigene Farbe" });
  custom.addEventListener("input", () => sendThrottled({ color: custom.value, on: true }));
  $("light-swatches").replaceChildren(
    ...LIGHT_SWATCHES.map(([name, hex]) =>
      h("button", {
        class: "swatch",
        type: "button",
        style: `--swatch:${hex}`,
        "data-color": hex,
        "aria-label": name,
        onclick: () => lightSend({ color: hex, on: true }),
      })
    ),
    h("label", { class: "swatch swatch-custom", "aria-label": "Eigene Farbe" }, custom)
  );
}

function buildEffectTiles() {
  $("light-effects").replaceChildren(
    ...LIGHT_GROUPS.map((group) => {
      const effects = lightEffects.filter((effect) => group.members.includes(effect.group));
      return h(
        "div",
        null,
        h("div", { class: "fx-group-label" }, group.name, h("span", null, group.sub)),
        h(
          "div",
          { class: "fx-grid" },
          ...effects.map((effect) =>
            h(
              "button",
              {
                class: `fx-tile fx-${effect.group}`,
                type: "button",
                "data-effect": effect.id,
                onclick: () => lightSend({ effect: effect.id, on: true }),
              },
              h("span", { class: "fx-preview" }, h("i"), h("i"), h("i"), h("i")),
              h("span", { class: "fx-name" }, effect.name)
            )
          )
        )
      );
    })
  );
}

function paintRange(range) {
  const min = Number(range.min) || 0;
  const max = Number(range.max) || 100;
  range.style.setProperty("--pct", `${((Number(range.value) - min) / (max - min)) * 100}%`);
}

function renderLight() {
  if (!light) return;
  const view = $("view-light");
  const effect = lightEffects.find((e) => e.id === light.effect);
  const animated = light.on && light.effect !== "static";
  view.style.setProperty("--lamp", hexToRgb(light.color));
  view.style.setProperty("--beat", `${(60 / light.bpm).toFixed(3)}s`);

  const hero = $("light-hero");
  hero.classList.toggle("on", light.on);
  hero.classList.toggle("off", !light.on);
  hero.classList.toggle("animated", animated);
  hero.style.setProperty("--orb-level", String(Math.max(0.3, light.brightness / 100)));
  $("light-kicker").textContent = light.on ? (animated ? `An · ${Math.round(light.bpm)} BPM` : "An") : "Aus";
  $("light-effect-name").textContent = effect ? effect.name : "Standlicht";
  setIcon($("light-power"), "power", light.on ? "Ausschalten" : "Einschalten");

  if (lightDragging !== "brightness") {
    $("light-brightness").value = String(light.brightness);
    paintRange($("light-brightness"));
  }
  $("light-brightness-label").textContent = `${light.brightness}%`;

  if (lightDragging !== "bpm") {
    $("light-bpm-range").value = String(Math.round(light.bpm));
    paintRange($("light-bpm-range"));
  }
  $("light-bpm").textContent = String(Math.round(light.bpm));

  document.querySelectorAll("#light-swatches .swatch[data-color]").forEach((el) => {
    el.classList.toggle("active", el.dataset.color === light.color);
  });
  const custom = $("light-custom");
  if (custom && document.activeElement !== custom) custom.value = light.color;
  document.querySelectorAll("#light-effects .fx-tile").forEach((el) => {
    el.classList.toggle("active", el.dataset.effect === light.effect);
  });

  $("light-fixtures").textContent = String(light.fixtures);
  const addresses = (light.addresses || []).map((a) => `d${String(a).padStart(3, "0")}`);
  $("light-addresses").textContent = `${addresses.length > 1 ? "DMX-Adressen" : "DMX-Adresse"} ${addresses.join(", ")}`;

  $("light-error").classList.toggle("hidden", !light.error);
  $("light-error").textContent = light.error || "";
}

function syncLightFromPoll() {
  if (!state.light || !light || lightDragging || Date.now() < lightHoldUntil) return;
  light = state.light;
  renderLight();
}

function bindLightRange(id, key, toValue) {
  const range = $(id);
  range.addEventListener("input", () => {
    lightDragging = key;
    paintRange(range);
    const value = toValue(Number(range.value));
    if (key === "brightness") $("light-brightness-label").textContent = `${value}%`;
    else $("light-bpm").textContent = String(value);
    sendThrottled({ [key]: value });
  });
  range.addEventListener("change", () => {
    lightDragging = null;
    lightSend({ [key]: toValue(Number(range.value)) });
  });
}

bindLightRange("light-brightness", "brightness", (v) => v);
bindLightRange("light-bpm-range", "bpm", clampBpm);

onTap($("light-power"), () => lightSend({ on: !(light && light.on) }));
onTap($("bpm-half"), () => lightSend({ bpm: clampBpm(light.bpm / 2) }));
onTap($("bpm-double"), () => lightSend({ bpm: clampBpm(light.bpm * 2) }));
onTap($("fixtures-minus"), () => lightSend({ fixtures: Math.max(1, light.fixtures - 1) }));
onTap($("fixtures-plus"), () => lightSend({ fixtures: Math.min(8, light.fixtures + 1) }));

// Tap-Sync: jeder Tipp legt den Schlag auf "jetzt", ab dem zweiten Tipp wird
// aus den Abstaenden (Mittel der letzten Taps) das Tempo berechnet.
function restartBeatAnimation() {
  const el = $("tap-beat");
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
}

$("tap-btn").addEventListener("pointerdown", (event) => {
  event.preventDefault();
  if (!light) return;
  const now = performance.now();
  if (taps.length && now - taps[taps.length - 1] > TAP_RESET_MS) taps = [];
  taps.push(now);
  taps = taps.slice(-TAP_MAX);
  const changes = { tap: true };
  if (taps.length >= 2) {
    const average = (taps[taps.length - 1] - taps[0]) / (taps.length - 1);
    changes.bpm = clampBpm(60000 / average);
    $("tap-hint").textContent = `${taps.length} Taps · ${changes.bpm} BPM`;
  } else {
    $("tap-hint").textContent = "Weiter im Takt tippen …";
  }
  $("tap-btn").classList.add("pressed");
  restartBeatAnimation();
  lightSend(changes);
});

["pointerup", "pointercancel", "pointerleave"].forEach((type) =>
  $("tap-btn").addEventListener(type, () => $("tap-btn").classList.remove("pressed"))
);

buildSwatches();

// ---------- Einstellungen ----------

// ---------- Einstellungen: Schule (Kurse fuer den Vertretungsplan) ----------

let courses = [];

async function loadSchool() {
  try {
    const data = await api.get("/api/remote/school");
    courses = data.kurse || [];
    $("school-kicker").textContent = data.klasse ? `Meine Kurse · ${data.klasse}` : "Meine Kurse";
    renderCourses();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderCourses() {
  const box = $("course-chips");
  if (!courses.length) {
    box.replaceChildren(h("div", { class: "course-empty" }, "Noch keine Kurse – es werden alle angezeigt."));
    return;
  }
  box.replaceChildren(
    ...courses.map((course) =>
      h(
        "button",
        { class: "course-chip", type: "button", "aria-label": `${course} entfernen`, onclick: () => saveCourses(courses.filter((c) => c !== course)) },
        course,
        icon("close")
      )
    )
  );
}

async function saveCourses(next) {
  const data = await api.post("/api/remote/school", { kurse: next }).catch((err) => {
    toast(err.message, true);
    return null;
  });
  if (!data) return;
  courses = data.kurse || [];
  renderCourses();
  toast("Kurse gespeichert – der Fernseher aktualisiert gleich");
}

function addCourse() {
  const input = $("course-input");
  // Mehrere auf einmal: "BI G1, D G2"
  const added = input.value
    .split(/[,;\n]+/)
    .map((c) => c.trim().replace(/\s+/g, " ").toUpperCase())
    .filter(Boolean);
  if (!added.length) return;
  input.value = "";
  saveCourses([...courses, ...added.filter((c) => !courses.includes(c))]);
}

onTap($("course-add"), () => addCourse());
$("course-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addCourse();
  }
});

async function loadSettings() {
  try {
    const schedule = await api.get("/api/remote/schedule");
    $("sched-enabled").checked = !!schedule.enabled;
    $("sched-weekday-wake").value = schedule.weekday.wake_time;
    $("sched-weekday-leave").value = schedule.weekday.leave_time;
    $("sched-weekend-wake").value = schedule.weekend.wake_time;
    $("sched-weekend-leave").value = schedule.weekend.leave_time;
  } catch (err) {
    toast(err.message, true);
  }
  loadSettingsStations();
  loadSchool();
}

async function loadSettingsStations() {
  try {
    const data = await api.get("/api/remote/radio/stations");
    stations = data.stations || [];
    const list = $("settings-station-list");
    if (!stations.length) {
      list.replaceChildren(h("div", { class: "group-empty" }, "Noch keine Sender angelegt."));
      return;
    }
    list.replaceChildren(
      ...stations.map((station) =>
        h(
          "div",
          { class: "group-row" },
          h("span", { class: "row-label" }, h("span", { class: "row-badge" }, stationInitials(station.name)), station.name),
          h(
            "button",
            {
              class: "station-delete",
              type: "button",
              "aria-label": `${station.name} entfernen`,
              onclick: () => deleteStation(station),
            },
            icon("trash")
          )
        )
      )
    );
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteStation(station) {
  if (!window.confirm(`„${station.name}“ wirklich entfernen?`)) return;
  try {
    await api.del(`/api/remote/radio/stations/${encodeURIComponent(station.id)}`);
    toast("Sender entfernt");
    loadSettingsStations();
  } catch (err) {
    toast(err.message, true);
  }
}

onTap($("btn-schedule-save"), async () => {
  await api.post("/api/remote/schedule", {
    enabled: $("sched-enabled").checked,
    weekday: { wake_time: $("sched-weekday-wake").value, leave_time: $("sched-weekday-leave").value },
    weekend: { wake_time: $("sched-weekend-wake").value, leave_time: $("sched-weekend-leave").value },
  });
  toast("Zeitplan gespeichert");
});

onTap($("btn-add-station"), async () => {
  const name = $("new-station-name").value.trim();
  const url = $("new-station-url").value.trim();
  if (!name || !url) throw new Error("Bitte Name und Stream-URL angeben");
  await api.post("/api/remote/radio/stations", { name, url });
  $("new-station-name").value = "";
  $("new-station-url").value = "";
  toast("Sender hinzugefügt");
  loadSettingsStations();
});

// ---------- Dock ----------

function renderDock(media) {
  const button = $("dock-play");
  button.classList.toggle("idle", !media || (media.kind !== "radio" && !media.playing));
  setIcon(button, playbackIcon(media));
}

async function changeVolume(delta) {
  const result = await api.post("/api/remote/volume", { delta });
  showVolume(result && result.volume);
}

onTap($("dock-home"), () => goHome());
onTap($("dock-play"), () => toggleActiveMedia());
onTap($("dock-vol-up"), () => changeVolume(1));
onTap($("dock-vol-down"), () => changeVolume(-1));
onTap($("dock-mute"), () => changeVolume(0));

// ---------- Status-Poll ----------

function renderAll() {
  const media = activeMedia();
  renderPower();
  renderMini(media);
  renderDock(media);
  renderYoutube();
  renderJellyfinNow();
  renderRadio();
  renderVinylNow();
  syncTimerFromState();
  syncLightFromPoll();
}

let pollTimer = null;
let pollInFlight = false;

async function poll() {
  if (pollInFlight) return;
  clearTimeout(pollTimer);
  pollInFlight = true;
  try {
    if (document.visibilityState !== "hidden") {
      const data = await apiRequest("GET", "/api/remote/now-playing", undefined, { quiet: true });
      applyHolds(data);
      state = data;
      renderAll();
    }
  } catch (err) {
    // offline oder Secret fehlt - der naechste Durchlauf versucht es erneut
  } finally {
    pollInFlight = false;
    pollTimer = setTimeout(poll, POLL_MS);
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    remoteOpenedAt = Date.now();
    updateClock();
    poll();
  }
});

async function loadInfo() {
  try {
    const info = await api.get("/api/remote/info");
    userName = info.name || null;
    updateClock();
  } catch (err) {
    toast(err.message, true);
  }
}

history.replaceState({ view: "home" }, "");
updateClock();
setInterval(updateClock, 5000);
renderAll();
loadInfo();
poll();
