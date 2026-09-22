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
  settings: () => loadSettings(),
};

function showView(name) {
  if (!$(`view-${name}`)) name = "home";
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("hidden", el.id !== `view-${name}`));
  currentView = name;
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
  if (currentView === "home") {
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (history.state && history.state.view && history.state.view !== "home") history.back();
  else showView("home");
}

window.addEventListener("popstate", (event) => {
  closeSheet();
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
  const radioState = state.radio || {};
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
  const endpoint = kind === "jellyfin" ? "/api/remote/jellyfin" : "/api/remote/youtube";
  const action = media.playing ? "pause" : "resume";
  holdPlaying(kind, !media.playing);
  await api.post(endpoint, { action });
}

async function toggleActiveMedia() {
  const media = activeMedia();
  if (media && (media.kind === "jellyfin" || media.kind === "youtube")) {
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

// ---------- Einstellungen ----------

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
