const BOOT_DURATION_MS = 4000;
const STATE_POLL_MS = 15000;
const PROGRESS_REPORT_MS = 1000;
const ERROR_DISPLAY_MS = 5000;
const WEEKDAY_NAMES = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];

function $(id) {
  return document.getElementById(id);
}

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

const MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const MAX_LIST_ITEMS = 7;
let dashboardState = null;

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function greeting(hour) {
  if (hour < 5) return "Gute Nacht";
  if (hour < 11) return "Guten Morgen";
  if (hour < 17) return "Guten Tag";
  if (hour < 22) return "Guten Abend";
  return "Gute Nacht";
}

function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  $("clock").textContent = `${hh}:${mm}`;
  $("date-label").textContent = `${WEEKDAY_NAMES[now.getDay()]}, ${now.getDate()}. ${MONTH_NAMES[now.getMonth()]}`;
  $("dash-hello").textContent = greeting(now.getHours());
  // Laufende/vergangene Termine minuetlich neu einfaerben
  if (dashboardState && now.getSeconds() === 0) renderEvents(dashboardState);
}

// ---------- Wetter-Symbole (SVG statt Emoji: der Kiosk hat keine Emoji-Schrift) ----------

const WX_SUN = "#ffc857";
const WX_CLOUD = "#d6e6f3";
const WX_RAIN = "#4fd8ff";

const wxParts = {
  sun: (x = 32, y = 32, r = 11) => {
    const rays = Array.from({ length: 8 }, (_, i) => {
      const a = (i * Math.PI) / 4;
      const x1 = x + Math.cos(a) * (r + 5), y1 = y + Math.sin(a) * (r + 5);
      const x2 = x + Math.cos(a) * (r + 10), y2 = y + Math.sin(a) * (r + 10);
      return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`;
    }).join("");
    return `<g stroke="${WX_SUN}" stroke-width="3.5" stroke-linecap="round">${rays}</g><circle cx="${x}" cy="${y}" r="${r}" fill="${WX_SUN}"/>`;
  },
  moon: (x = 32, y = 30, r = 14) =>
    `<path d="M${x + r * 0.35} ${y - r} A${r} ${r} 0 1 0 ${x + r} ${y + r * 0.45} A${r * 0.8} ${r * 0.8} 0 0 1 ${x + r * 0.35} ${y - r} Z" fill="#e3ecf7"/>`,
  cloud: (dy = 0, fill = WX_CLOUD) =>
    `<path transform="translate(0 ${dy})" d="M18 50h29a10 10 0 0 0 1.4-19.9A14 14 0 0 0 21.6 27.4 11.4 11.4 0 0 0 18 50z" fill="${fill}"/>`,
  drops: (count, len = 7) =>
    `<g stroke="${WX_RAIN}" stroke-width="3.2" stroke-linecap="round">${[24, 33, 42]
      .slice(0, count)
      .map((x) => `<line x1="${x}" y1="49" x2="${x - 3}" y2="${49 + len}"/>`)
      .join("")}</g>`,
  flakes: () =>
    `<g fill="#ffffff">${[
      [24, 53],
      [33, 57],
      [42, 53],
    ]
      .map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.6"/>`)
      .join("")}</g>`,
};

function weatherSvg(key, isDay = true) {
  const small = isDay ? wxParts.sun(22, 22, 8) : wxParts.moon(22, 20, 10);
  const shapes = {
    sun: isDay ? wxParts.sun() : wxParts.moon(),
    "sun-cloud": small + wxParts.cloud(4),
    cloud: wxParts.cloud(0, "#c3d6e6") + wxParts.cloud(-6),
    fog: `<g stroke="#b8c9d8" stroke-width="4" stroke-linecap="round"><line x1="12" y1="26" x2="52" y2="26"/><line x1="16" y1="36" x2="48" y2="36"/><line x1="12" y1="46" x2="52" y2="46"/></g>`,
    drizzle: wxParts.cloud(-8) + wxParts.drops(3, 4),
    rain: wxParts.cloud(-8) + wxParts.drops(3, 9),
    showers: small + wxParts.cloud(-2) + wxParts.drops(2, 6).replace(/y1="49"/g, 'y1="53"').replace(/y2="(\d+)"/g, (m, v) => `y2="${Number(v) + 4}"`),
    sleet: wxParts.cloud(-8) + wxParts.drops(1, 8) + `<circle cx="36" cy="54" r="2.6" fill="#fff"/><circle cx="44" cy="51" r="2.6" fill="#fff"/>`,
    snow: wxParts.cloud(-8) + wxParts.flakes(),
    thunder: wxParts.cloud(-8, "#a9bccd") + `<path d="M34 44 26 56h7l-3 9 11-14h-7l3-7z" fill="#ffd23b"/>`,
  };
  return `<svg viewBox="0 0 64 64" aria-hidden="true">${shapes[key] || shapes.cloud}</svg>`;
}

// ---------- Panels ----------

const EMPTY_ICONS = {
  calendar: `<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>`,
  todos: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="m8.2 12.2 2.6 2.6 5-5.2"/></svg>`,
  plan: `<svg viewBox="0 0 24 24"><path d="M3 9.5 12 5l9 4.5-9 4.5z"/><path d="M7 11.5v4.2c1.4 1.2 3 1.8 5 1.8s3.6-.6 5-1.8v-4.2"/></svg>`,
  weather: `<svg viewBox="0 0 24 24"><path d="M7 18h10a4 4 0 0 0 .6-8A6 6 0 0 0 6.2 9.3 4.4 4.4 0 0 0 7 18z"/></svg>`,
};

function emptyState(el, icon, text, hint) {
  el.innerHTML = `<li class="panel-empty">${EMPTY_ICONS[icon]}<div>${esc(text)}</div>${hint ? `<small>${esc(hint)}</small>` : ""}</li>`;
}

function renderList(el, items, mapFn) {
  const shown = items.slice(0, MAX_LIST_ITEMS);
  const rest = items.length - shown.length;
  el.innerHTML = shown.map(mapFn).join("") + (rest > 0 ? `<li class="more">+ ${rest} weitere</li>` : "");
}

function renderWeather(state) {
  const el = $("weather-content");
  const w = state.weather;
  $("weather-meta").textContent = w && w.city ? w.city : "";
  if (!w) {
    el.innerHTML = `<div class="panel-empty">${EMPTY_ICONS.weather}<div>Wetter wird geladen …</div><small>Der Pi versucht es jede Minute erneut.</small></div>`;
    return;
  }
  const t = (v) => `${Math.round(v)}°`;
  const hours = (w.hourly || [])
    .map(
      (h) => `<div class="wx-hour"><span>${esc(h.time)}</span>${weatherSvg(h.icon, h.is_day)}<b>${t(h.temp)}</b>
        <span class="wx-rain${h.rain >= 10 ? "" : " zero"}">${h.rain} %</span></div>`
    )
    .join("");
  const days = w.daily || [];
  const lo = Math.min(...days.map((d) => d.min), w.temp_min);
  const hi = Math.max(...days.map((d) => d.max), w.temp_max);
  const span = Math.max(1, hi - lo);
  const dayRows = days
    .map((d) => {
      const left = ((d.min - lo) / span) * 100;
      const width = Math.max(4, ((d.max - d.min) / span) * 100);
      return `<div class="wx-day"><span>${esc(d.day)}</span>${weatherSvg(d.icon)}<span class="lo">${t(d.min)}</span>
        <span class="wx-bar"><i style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%"></i></span>
        <span class="hi">${t(d.max)}</span><span class="wx-rain${d.rain >= 10 ? "" : " zero"}">${d.rain} %</span></div>`;
    })
    .join("");
  el.innerHTML = `
    <div class="wx-now">
      <div class="wx-icon-big">${weatherSvg(w.icon, w.is_day)}</div>
      <div>
        <div class="wx-temp">${t(w.temp_current)}</div>
        <div class="wx-desc">${esc(w.description)}</div>
        <div class="wx-sub">Gefühlt ${t(w.temp_feels)} · Wind ${Math.round(w.wind_kmh)} km/h</div>
      </div>
    </div>
    <div class="wx-stats">
      <div class="wx-stat"><span>Heute</span><b>${t(w.temp_min)} / ${t(w.temp_max)}</b></div>
      <div class="wx-stat"><span>Regen</span><b>${w.precipitation_probability} %</b></div>
      <div class="wx-stat"><span>Sonne</span><b>${esc(w.sunrise)} – ${esc(w.sunset)}</b></div>
    </div>
    <div class="wx-hours">${hours}</div>
    <div class="wx-days">${dayRows}</div>`;
}

function renderEvents(state) {
  const el = $("calendar-content");
  const events = state.events || [];
  const missing = (state.not_configured || []).filter((s) => s.includes("Kalender"));
  $("calendar-meta").textContent = events.length ? `${events.length} ${events.length === 1 ? "Termin" : "Termine"}` : "";
  if (!events.length) {
    if (missing.length === 2) emptyState(el, "calendar", "Kalender noch nicht verbunden", "Google-iCal-Adresse und iCloud-Zugang fehlen noch.");
    else emptyState(el, "calendar", "Keine Termine heute", missing.length ? `${missing[0]} ist noch nicht verbunden.` : "");
    return;
  }
  const now = Date.now();
  renderList(el, events, (e) => {
    const start = e.start ? Date.parse(e.start) : null;
    const end = e.end ? Date.parse(e.end) : null;
    const cls = start && end ? (now >= end ? "past" : now >= start ? "now" : "") : "";
    const time = e.all_day ? `<span class="time all-day">Ganztägig</span>` : `<span class="time">${esc(e.time_label)}</span>`;
    return `<li class="${cls}">${time}<span class="item-text">${esc(e.title)}</span></li>`;
  });
}

function renderPlan(state) {
  const panel = $("plan-panel");
  panel.classList.toggle("hidden", !state.is_school_day);
  if (!state.is_school_day) return;
  const el = $("plan-content");
  const plan = state.substitution_plan || [];
  $("plan-meta").textContent = plan.length ? `${plan.length} ${plan.length === 1 ? "Änderung" : "Änderungen"}` : "";
  if ((state.not_configured || []).includes("IServ-Vertretungsplan")) {
    emptyState(el, "plan", "IServ noch nicht verbunden", "Benutzername und Passwort fehlen in der .env auf dem Pi.");
    return;
  }
  if (!plan.length) {
    emptyState(el, "plan", "Keine Änderungen im Vertretungsplan");
    return;
  }
  renderList(el, plan, (p) => {
    const parts = [p.subject, p.room].filter(Boolean).join(" · ");
    const note = p.note ? `<span class="note">${esc(p.note)}</span>` : "";
    return `<li><span class="time">${esc(p.lesson || "–")}</span><span class="item-text">${esc(parts)}${note}</span></li>`;
  });
}

function renderTodos(state) {
  const el = $("todos-content");
  const todos = state.todos || [];
  $("todos-meta").textContent = todos.length ? `${todos.length} offen` : "";
  if (!todos.length) {
    if ((state.not_configured || []).includes("ToDos")) emptyState(el, "todos", "ToDo-Liste noch nicht verbunden", "Der iPhone-Kurzbefehl hat noch keine Notiz geschickt.");
    else emptyState(el, "todos", "Alles erledigt");
    return;
  }
  renderList(el, todos, (t) => `<li><span class="todo-dot"></span><span class="item-text">${esc(t)}</span></li>`);
}

function renderErrors(errors) {
  const el = $("errors");
  if (!errors || errors.length === 0) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.classList.remove("hidden");
  // Nur Quelle + Kurzform, nicht der komplette Python-Fehlertext
  el.textContent = "⚠ " + errors.map((e) => e.split(":")[0] + " nicht erreichbar").join(" · ");
}

function renderSub(state) {
  const parts = [];
  if (state.weather) parts.push(`${Math.round(state.weather.temp_current)}° und ${state.weather.description.toLowerCase()}`);
  const events = (state.events || []).filter((e) => !e.all_day && e.start && Date.parse(e.start) > Date.now());
  if (events.length) parts.push(`nächster Termin ${events[0].time_label}`);
  $("dash-sub").textContent = parts.join(" · ") || " ";
}

async function refreshState() {
  try {
    const resp = await fetch("/api/state");
    if (!resp.ok) return;
    const state = await resp.json();
    dashboardState = state;

    renderWeather(state);
    renderEvents(state);
    renderPlan(state);
    renderTodos(state);
    renderErrors(state.errors);
    renderSub(state);

    $("onair").classList.toggle("hidden", !state.radio_playing);
  } catch (err) {
    console.error("Konnte /api/state nicht laden", err);
  }
}

// ---------- Bildschirme: Dashboard / YouTube / Jellyfin / Plattenspieler ----------

let currentScreen = "dashboard";
let resolveBoot;
// Abspiel-Befehle, die waehrend der Boot-Animation eintreffen (Fernseher wurde
// gerade fuers Abspielen eingeschaltet), starten erst danach.
const bootDone = new Promise((resolve) => {
  resolveBoot = resolve;
});

function showScreen(name) {
  // Waehrend ein Timer laeuft, ist der Vollbild-Countdown die "Startseite"
  if (name === "dashboard" && timer.state !== "idle") name = "clock";
  if (currentScreen === "youtube" && name !== "youtube") stopYoutubePlayback();
  if (currentScreen === "jellyfin" && name !== "jellyfin") stopJellyfinPlayback();
  if (currentScreen === "vinyl" && name !== "vinyl") stopVinylPlayback();
  currentScreen = name;
  $("dashboard").classList.toggle("hidden", name !== "dashboard");
  $("player-screen").classList.toggle("hidden", name !== "youtube");
  $("jellyfin-screen").classList.toggle("hidden", name !== "jellyfin");
  $("vinyl-screen").classList.toggle("hidden", name !== "vinyl");
  $("clock-screen").classList.toggle("hidden", name !== "clock");
  renderClock();
}

// ---------- YouTube (IFrame API) ----------

let ytPlayer = null;
let ytReady = false;
const ytPendingQueue = [];

function suppressCaptions() {
  // cc_load_policy allein reicht bei manchen Videos nicht - YouTube erzwingt
  // Untertitel trotzdem. Deshalb an mehreren Stellen im Lebenszyklus (ready,
  // sobald die Modul-API verfuegbar ist, bei jedem Statuswechsel, jede
  // Sekunde waehrend der Wiedergabe) aktiv das Untertitel-Modul entladen/leeren.
  if (!ytPlayer) return;
  try { ytPlayer.unloadModule("captions"); } catch (err) {}
  try { ytPlayer.setOption("captions", "track", {}); } catch (err) {}
}

function setYoutubePause(show) {
  const overlay = $("yt-pause");
  if (!show) {
    overlay.classList.add("hidden");
    return;
  }
  const data = (ytPlayer && ytPlayer.getVideoData && ytPlayer.getVideoData()) || {};
  $("yt-pause-title").textContent = data.title || "";
  overlay.style.backgroundImage = data.video_id
    ? `url(https://img.youtube.com/vi/${data.video_id}/hqdefault.jpg)`
    : "none";
  overlay.classList.remove("hidden");
}

function onYouTubeIframeAPIReady() {
  createVinylPlayer();
  ytPlayer = new YT.Player("youtube-player", {
    height: "100%",
    width: "100%",
    // cc_load_policy: 0 = Untertitel nicht automatisch einblenden. iv_load_policy/
    // disablekb/fs/modestbranding reduzieren zusaetzliche YouTube-eigene UI.
    playerVars: {
      autoplay: 1,
      controls: 0,
      rel: 0,
      cc_load_policy: 0,
      iv_load_policy: 3,
      disablekb: 1,
      fs: 0,
      modestbranding: 1,
    },
    events: {
      onReady: () => {
        ytReady = true;
        suppressCaptions();
        ytPendingQueue.splice(0).forEach((fn) => fn());
      },
      // onApiChange feuert, sobald z.B. das Untertitel-Modul tatsaechlich
      // verfuegbar ist - genau der Zeitpunkt, an dem unloadModule zuverlaessig wirkt.
      onApiChange: () => suppressCaptions(),
      onStateChange: (event) => {
        suppressCaptions();
        if (currentScreen !== "youtube") return;
        setYoutubePause(event.data === YT.PlayerState.PAUSED || event.data === YT.PlayerState.ENDED);
      },
    },
  });
}

function withYtPlayer(fn) {
  if (ytReady) {
    fn();
  } else {
    ytPendingQueue.push(fn);
  }
}

function stopYoutubePlayback() {
  withYtPlayer(() => ytPlayer.stopVideo());
  setYoutubePause(false);
}

function handleYoutubeMessage(msg) {
  if (msg.type === "youtube_play") {
    bootDone.then(() => {
      showScreen("youtube");
      setYoutubePause(false);
      withYtPlayer(() => {
        ytPlayer.loadVideoById(msg.video_id);
        suppressCaptions();
      });
    });
  } else if (msg.type === "youtube_stop") {
    if (currentScreen === "youtube") showScreen("dashboard");
  } else if (currentScreen === "youtube") {
    if (msg.type === "youtube_pause") {
      withYtPlayer(() => ytPlayer.pauseVideo());
    } else if (msg.type === "youtube_resume") {
      withYtPlayer(() => ytPlayer.playVideo());
    } else if (msg.type === "youtube_seek") {
      withYtPlayer(() => ytPlayer.seekTo(Math.max(0, ytPlayer.getCurrentTime() + msg.seconds), true));
    } else if (msg.type === "youtube_seek_to") {
      withYtPlayer(() => ytPlayer.seekTo(Math.max(0, msg.seconds), true));
    }
  }
}

// ---------- Jellyfin (natives <video> ueber den Stream-Proxy) ----------

const jfVideo = $("jf-video");
let jfCurrent = null;
let jfLoadToken = 0;
let jfErrorTimer = null;

function setJellyfinLoading(show) {
  $("jf-loading").classList.toggle("hidden", !show);
}

function setJellyfinPause(show) {
  const overlay = $("jf-pause");
  if (!show || !jfCurrent) {
    overlay.classList.add("hidden");
    return;
  }
  const duration = Number.isFinite(jfVideo.duration) ? jfVideo.duration : jfCurrent.duration;
  const parts = [jfCurrent.subtitle, `${formatTime(jfVideo.currentTime)} / ${formatTime(duration)}`];
  $("jf-pause-title").textContent = jfCurrent.title || "";
  $("jf-pause-sub").textContent = parts.filter(Boolean).join("  ·  ");
  overlay.style.backgroundImage = jfCurrent.backdrop ? `url("${jfCurrent.backdrop}")` : "none";
  overlay.classList.remove("hidden");
}

function stopJellyfinPlayback() {
  // jfCurrent zuerst leeren: das Entfernen der Quelle loest pause/error-Events
  // aus, die sonst als echter Fehler/Pause gemeldet wuerden.
  jfCurrent = null;
  jfLoadToken += 1;
  setJellyfinPause(false);
  setJellyfinLoading(false);
  jfVideo.pause();
  jfVideo.removeAttribute("src");
  jfVideo.load();
}

function startJellyfin(msg) {
  showScreen("jellyfin");
  clearTimeout(jfErrorTimer);
  $("jf-error").classList.add("hidden");
  jfCurrent = {
    itemId: msg.item_id,
    title: msg.title,
    subtitle: msg.subtitle,
    backdrop: msg.backdrop_url,
    duration: Number(msg.duration) || 0,
  };
  setJellyfinPause(false);
  $("jf-loading-title").textContent = msg.title || "";
  setJellyfinLoading(true);

  const token = ++jfLoadToken;
  const start = Number(msg.start_seconds) || 0;
  jfVideo.addEventListener(
    "loadedmetadata",
    () => {
      if (token !== jfLoadToken) return;
      if (start > 0 && (!jfVideo.duration || start < jfVideo.duration - 5)) jfVideo.currentTime = start;
      jfVideo.play().catch(() => {});
    },
    { once: true }
  );
  jfVideo.src = msg.stream_url;
}

function showJellyfinError(message) {
  jfCurrent = null;
  setJellyfinLoading(false);
  setJellyfinPause(false);
  $("jf-error-text").textContent = message;
  $("jf-error").classList.remove("hidden");
  clearTimeout(jfErrorTimer);
  jfErrorTimer = setTimeout(() => {
    $("jf-error").classList.add("hidden");
    if (currentScreen === "jellyfin") showScreen("dashboard");
  }, ERROR_DISPLAY_MS);
}

jfVideo.addEventListener("playing", () => {
  setJellyfinLoading(false);
  setJellyfinPause(false);
});
jfVideo.addEventListener("waiting", () => {
  if (jfCurrent) setJellyfinLoading(true);
});
jfVideo.addEventListener("seeked", () => {
  if (!jfCurrent || !jfVideo.paused) return;
  setJellyfinLoading(false);
  setJellyfinPause(true);
});
jfVideo.addEventListener("pause", () => {
  if (!jfCurrent || jfVideo.ended) return;
  setJellyfinLoading(false);
  setJellyfinPause(true);
});
jfVideo.addEventListener("ended", () => {
  if (!jfCurrent) return;
  sendWs({ type: "jellyfin_ended", item_id: jfCurrent.itemId });
  showScreen("dashboard");
});
jfVideo.addEventListener("error", () => {
  if (!jfCurrent) return;
  const unsupported = jfVideo.error && jfVideo.error.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED;
  const message = unsupported
    ? "Dieses Video kann der Fernseher nicht direkt abspielen."
    : "Die Wiedergabe ist fehlgeschlagen.";
  sendWs({ type: "jellyfin_error", item_id: jfCurrent.itemId, message });
  showJellyfinError(message);
});

function handleJellyfinMessage(msg) {
  if (msg.type === "jellyfin_play") {
    bootDone.then(() => startJellyfin(msg));
    return;
  }
  if (currentScreen !== "jellyfin" || !jfCurrent) return;
  if (msg.type === "jellyfin_stop") {
    showScreen("dashboard");
  } else if (msg.type === "jellyfin_pause") {
    jfVideo.pause();
  } else if (msg.type === "jellyfin_resume") {
    jfVideo.play().catch(() => {});
  } else if (msg.type === "jellyfin_seek") {
    const end = Number.isFinite(jfVideo.duration) ? jfVideo.duration - 1 : Infinity;
    jfVideo.currentTime = Math.max(0, Math.min(jfVideo.currentTime + Number(msg.seconds || 0), end));
  } else if (msg.type === "jellyfin_seek_to") {
    jfVideo.currentTime = Math.max(0, Number(msg.seconds) || 0);
  }
}

// ---------- Plattenspieler (eigener, versteckter YouTube-Player) ----------
// Die Warteschlange fuehrt der Server; der Kiosk spielt jeweils einen Song
// (vinyl_play mit token) und meldet Fortschritt/Ende/Fehler mit diesem token.

const VINYL_ARM_REST_DEG = 4;
const VINYL_ARM_START_DEG = 34;   // Nadel auf der Einlaufrille
const VINYL_ARM_END_DEG = 52;     // Nadel kurz vor dem Etikett
const VINYL_MAX_TRACKS = 7;
const VINYL_SWAP_MS = 700;

let vinylPlayer = null;
let vinylReady = false;
const vinylPendingQueue = [];
let vinylCurrent = null;
let vinylEndedToken = null;

function createVinylPlayer() {
  vinylPlayer = new YT.Player("vinyl-yt", {
    height: "180",
    width: "320",
    playerVars: { autoplay: 1, controls: 0, rel: 0, cc_load_policy: 0, iv_load_policy: 3, disablekb: 1, fs: 0 },
    events: {
      onReady: () => {
        vinylReady = true;
        vinylPendingQueue.splice(0).forEach((fn) => fn());
      },
      onStateChange: (event) => {
        if (!vinylCurrent) return;
        const S = YT.PlayerState;
        if (event.data === S.PLAYING) setVinylMotion("playing");
        else if (event.data === S.PAUSED) setVinylMotion("paused");
        else if (event.data === S.BUFFERING) setVinylMotion("loading");
        else if (event.data === S.ENDED && vinylEndedToken !== vinylCurrent.token) {
          vinylEndedToken = vinylCurrent.token;
          setVinylMotion("loading");
          sendWs({ type: "vinyl_ended", token: vinylCurrent.token });
        }
      },
      // 2/5/100/101/150: ungueltig, HTML5-Fehler, geloescht, nicht einbettbar
      onError: (event) => {
        if (vinylCurrent) sendWs({ type: "vinyl_error", token: vinylCurrent.token, code: event.data });
      },
    },
  });
}

function withVinylPlayer(fn) {
  if (vinylReady) fn();
  else vinylPendingQueue.push(fn);
}

function setArmAngle(deg, tracking) {
  const arm = $("vy-arm");
  arm.classList.toggle("tracking", tracking);
  arm.style.setProperty("--arm-angle", `${deg}deg`);
}

// "loading": Arm in Ruhe, LED blinkt | "playing": Platte dreht, Nadel liegt auf |
// "paused": Platte steht, Arm abgehoben
function setVinylMotion(mode) {
  const disc = $("vy-disc");
  disc.classList.toggle("spinning", mode !== "loading");
  disc.classList.toggle("paused", mode === "paused");
  $("vy-led").classList.toggle("on", mode !== "loading");
  $("vy-led").classList.toggle("blink", mode === "loading");
  $("vy-pause").classList.toggle("hidden", mode !== "paused");
  if (mode === "playing") updateVinylProgress();
  else setArmAngle(VINYL_ARM_REST_DEG, false);
}

function vinylFraction() {
  if (!vinylReady || !vinylPlayer || typeof vinylPlayer.getDuration !== "function") return 0;
  const duration = vinylPlayer.getDuration();
  return duration > 0 ? Math.min(1, vinylPlayer.getCurrentTime() / duration) : 0;
}

function updateVinylProgress() {
  if (!vinylCurrent || !vinylReady || typeof vinylPlayer.getPlayerState !== "function") return;
  const duration = vinylPlayer.getDuration() || 0;
  const current = vinylPlayer.getCurrentTime() || 0;
  const fraction = vinylFraction();
  $("vy-bar-fill").style.width = `${(fraction * 100).toFixed(2)}%`;
  $("vy-cur").textContent = formatTime(current);
  $("vy-dur").textContent = formatTime(duration);
  if (vinylPlayer.getPlayerState() === YT.PlayerState.PLAYING) {
    setArmAngle(VINYL_ARM_START_DEG + (VINYL_ARM_END_DEG - VINYL_ARM_START_DEG) * fraction, true);
  }
}

function setVinylArtwork(record) {
  const stage = $("vy-stage").parentElement;
  stage.style.setProperty("--vy-label", record.color || "#b8452e");
  const cover = record.cover ? `url("${record.cover.replace(/"/g, "%22")}")` : "";
  $("vy-label").style.backgroundImage = cover;
  $("vy-label").classList.toggle("has-cover", !!record.cover);
  $("vy-label-text").textContent = record.album;
  $("vy-sleeve").style.backgroundImage = cover;
}

function renderVinylInfo(msg) {
  const record = msg.record;
  const bits = ["Seite A", "33⅓ U/min"];
  if (msg.context && msg.context !== record.album) bits.push(msg.context);
  $("vy-kicker").textContent = bits.join(" · ");
  $("vy-title").textContent = msg.title;
  $("vy-title").classList.toggle("long", msg.title.length > 22);
  $("vy-artist").textContent = msg.artist;
  $("vy-album").textContent = record.year ? `${record.album} · ${record.year}` : record.album;
  $("vy-bar-fill").style.width = "0%";
  $("vy-cur").textContent = "0:00";
  $("vy-dur").textContent = "0:00";

  // Tracklist der Platte, Ausschnitt um den aktuellen Song
  const songs = record.songs || [];
  const first = Math.max(0, Math.min(msg.song_index - 2, songs.length - VINYL_MAX_TRACKS));
  const items = songs.slice(first, first + VINYL_MAX_TRACKS).map((title, i) => {
    const li = document.createElement("li");
    const index = first + i;
    li.dataset.nr = String(index + 1).padStart(2, "0");
    li.textContent = title;
    li.classList.toggle("current", index === msg.song_index);
    return li;
  });
  const rest = songs.length - (first + VINYL_MAX_TRACKS);
  if (rest > 0) {
    const li = document.createElement("li");
    li.className = "more";
    li.textContent = `… und ${rest} weitere`;
    items.push(li);
  }
  $("vy-tracks").replaceChildren(...items);

  const next = $("vy-next");
  next.classList.toggle("hidden", !msg.next);
  if (msg.next) {
    next.replaceChildren("Als Nächstes: ", Object.assign(document.createElement("b"), { textContent: msg.next.title }), ` – ${msg.next.artist}`);
  }
}

function startVinyl(msg) {
  const recordChanged = !vinylCurrent || vinylCurrent.record.id !== msg.record.id || currentScreen !== "vinyl";
  vinylCurrent = msg;
  showScreen("vinyl");
  renderVinylInfo(msg);
  setVinylMotion("loading");

  const disc = $("vy-disc");
  if (recordChanged && disc.dataset.record) {
    // Alte Platte runter, neue drauf - erst danach die neue Etikett-Grafik
    disc.classList.add("swap-out");
    setTimeout(() => {
      setVinylArtwork(msg.record);
      disc.classList.remove("swap-out");
    }, VINYL_SWAP_MS);
  } else {
    setVinylArtwork(msg.record);
  }
  disc.dataset.record = msg.record.id;

  withVinylPlayer(() => {
    if (vinylCurrent !== msg) return;
    vinylPlayer.loadVideoById({ videoId: msg.video_id, startSeconds: msg.start || 0 });
  });
}

function stopVinylPlayback() {
  vinylCurrent = null;
  withVinylPlayer(() => vinylPlayer.stopVideo());
  setVinylMotion("loading");
  $("vy-led").classList.remove("blink");
  delete $("vy-disc").dataset.record;
}

function handleVinylMessage(msg) {
  if (msg.type === "vinyl_play") {
    bootDone.then(() => startVinyl(msg));
  } else if (msg.type === "vinyl_stop") {
    if (currentScreen === "vinyl") showScreen("dashboard");
  } else if (currentScreen === "vinyl" && vinylCurrent) {
    if (msg.type === "vinyl_pause") withVinylPlayer(() => vinylPlayer.pauseVideo());
    else if (msg.type === "vinyl_resume") withVinylPlayer(() => vinylPlayer.playVideo());
    else if (msg.type === "vinyl_seek_to") withVinylPlayer(() => vinylPlayer.seekTo(Math.max(0, msg.seconds), true));
  }
}

function reportVinylProgress() {
  if (!vinylCurrent || !vinylReady || typeof vinylPlayer.getPlayerState !== "function") return;
  updateVinylProgress();
  const state = vinylPlayer.getPlayerState();
  if (state !== YT.PlayerState.PLAYING && state !== YT.PlayerState.PAUSED) return;
  sendWs({
    type: "vinyl_progress",
    token: vinylCurrent.token,
    current_time: vinylPlayer.getCurrentTime(),
    duration: vinylPlayer.getDuration(),
    playing: state === YT.PlayerState.PLAYING,
  });
}

// ---------- Uhr + Timer ----------
// Den Timer fuehrt der Server (laeuft auch bei ausgeschaltetem Fernseher);
// der Kiosk rechnet die Anzeige aus der gemeldeten Restzeit hoch.

const TIMER_FINAL_SECONDS = 10;
const ALARM_REPEAT_MS = 1400;
const TIMER_TICK_MS = 250;

let timer = { state: "idle", duration: 0, remaining_ms: 0, acknowledged: false, clock_screen: false };
let timerEndsAt = 0;
let clockPinned = false;
let alarmCtx = null;
let alarmTimer = null;

const pad2 = (n) => String(n).padStart(2, "0");

function formatCountdown(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours ? `${hours}:${pad2(minutes)}:${pad2(total % 60)}` : `${minutes}:${pad2(total % 60)}`;
}

function timerLabel(seconds) {
  if (seconds < 60) return `Timer · ${seconds} Sek`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (!hours) return `Timer · ${minutes} Min`;
  return minutes ? `Timer · ${hours} Std ${minutes} Min` : `Timer · ${hours} Std`;
}

function timerActive() {
  return timer.state === "running" || timer.state === "paused";
}

function timerRemaining() {
  if (timer.state === "running") return Math.max(0, (timerEndsAt - performance.now()) / 1000);
  if (timer.state === "paused") return timer.remaining_ms / 1000;
  return 0;
}

// Alarmton ueber Web Audio (laeuft ueber PipeWire wie YouTube, der Kiosk
// darf dank --autoplay-policy ohne Klick abspielen): dreimal piepen, Pause.
function alarmBeep() {
  const t = alarmCtx.currentTime;
  [0, 0.22, 0.44].forEach((offset) => {
    const osc = alarmCtx.createOscillator();
    const gain = alarmCtx.createGain();
    osc.type = "triangle";
    osc.frequency.value = 988;
    gain.gain.setValueAtTime(0, t + offset);
    gain.gain.linearRampToValueAtTime(0.5, t + offset + 0.015);
    gain.gain.setValueAtTime(0.5, t + offset + 0.13);
    gain.gain.linearRampToValueAtTime(0, t + offset + 0.16);
    osc.connect(gain).connect(alarmCtx.destination);
    osc.start(t + offset);
    osc.stop(t + offset + 0.18);
  });
}

function startAlarm() {
  if (alarmTimer) return;
  alarmCtx = alarmCtx || new AudioContext();
  alarmCtx.resume();
  alarmBeep();
  alarmTimer = setInterval(alarmBeep, ALARM_REPEAT_MS);
}

function stopAlarm() {
  clearInterval(alarmTimer);
  alarmTimer = null;
}

function updateAlarm() {
  const ringing = timer.state === "ringing";
  const alert = $("timer-alert");
  alert.classList.toggle("hidden", !ringing);
  alert.classList.toggle("quiet", ringing && timer.acknowledged);
  if (!ringing || timer.acknowledged) stopAlarm();
  else startAlarm();
  if (ringing) {
    $("ta-label").textContent = timerLabel(timer.duration);
    $("ta-hint").textContent = timer.acknowledged
      ? "Auf der Fernbedienung beenden oder neu starten"
      : "Fernbedienung öffnen, um den Alarm zu beenden";
  }
}

function renderClock() {
  const now = new Date();
  if (currentScreen === "clock") {
    $("cs-hm").textContent = `${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
    $("cs-sec").textContent = pad2(now.getSeconds());
    $("cs-date").textContent = now.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
  }

  const active = timerActive();
  const remaining = timerRemaining();
  const fraction = timer.duration > 0 ? Math.min(1, remaining / timer.duration) : 0;
  const final = timer.state === "running" && remaining <= TIMER_FINAL_SECONDS;

  const screen = $("clock-screen");
  screen.classList.toggle("has-timer", active || timer.state === "ringing");
  screen.classList.toggle("paused", timer.state === "paused");
  screen.classList.toggle("final", final);
  if (active) {
    $("cs-countdown").textContent = formatCountdown(remaining);
    $("cs-ring-fill").style.strokeDashoffset = String(Math.round(1000 * (1 - fraction)));
    $("cs-timer-label").textContent = timerLabel(timer.duration);
    const end = new Date(Date.now() + remaining * 1000);
    $("cs-timer-state").textContent = timer.state === "paused" ? "Pausiert" : `Fertig um ${pad2(end.getHours())}:${pad2(end.getMinutes())}`;
  }

  const notch = $("timer-notch");
  const showNotch = active && currentScreen !== "clock";
  notch.classList.toggle("hidden", !showNotch);
  if (showNotch) {
    notch.classList.toggle("paused", timer.state === "paused");
    notch.classList.toggle("final", final);
    $("tn-time").textContent = formatCountdown(remaining);
    $("tn-fill").style.width = `${(fraction * 100).toFixed(1)}%`;
  }
}

function handleTimerMessage(msg) {
  if (msg.type === "clock_show") {
    clockPinned = true;
    bootDone.then(() => showScreen("clock"));
    return;
  }
  if (msg.type === "clock_hide") {
    clockPinned = false;
    if (currentScreen === "clock") showScreen("dashboard");
    return;
  }
  timer = msg;
  timerEndsAt = performance.now() + (msg.remaining_ms || 0);
  clockPinned = !!msg.clock_screen;
  // Neuer Timer: auf dem Dashboard im Vollbild herunterzaehlen. Laeuft
  // gerade Plattenspieler/YouTube/Jellyfin, bleibt es bei der Notch.
  if (msg.show) {
    bootDone.then(() => {
      if (currentScreen === "dashboard") showScreen("clock");
    });
  }
  if (msg.state === "idle" && currentScreen === "clock" && !clockPinned) showScreen("dashboard");
  updateAlarm();
  renderClock();
}

// ---------- WebSocket + Fortschrittsmeldungen ----------

let wsConn = null;

function sendWs(payload) {
  if (wsConn && wsConn.readyState === WebSocket.OPEN) {
    wsConn.send(JSON.stringify(payload));
  }
}

// Die Fernbedienung sieht die Player selbst nicht - Fortschritt/Titel gehen
// deshalb jede Sekunde an den Server (GET /api/remote/now-playing).
function reportYoutubeProgress() {
  if (!ytReady || !ytPlayer || typeof ytPlayer.getPlayerState !== "function") return;
  const state = ytPlayer.getPlayerState();
  if (state !== YT.PlayerState.PLAYING && state !== YT.PlayerState.PAUSED) return;
  // YouTube laedt das Untertitel-Modul teils asynchron nach und schaltet es
  // dann trotz vorherigem unloadModule() wieder ein.
  suppressCaptions();
  const data = ytPlayer.getVideoData() || {};
  sendWs({
    type: "youtube_progress",
    current_time: ytPlayer.getCurrentTime(),
    duration: ytPlayer.getDuration(),
    playing: state === YT.PlayerState.PLAYING,
    title: data.title || "",
  });
}

function reportJellyfinProgress() {
  if (!jfCurrent || jfVideo.readyState < 1) return;
  sendWs({
    type: "jellyfin_progress",
    item_id: jfCurrent.itemId,
    current_time: jfVideo.currentTime,
    duration: Number.isFinite(jfVideo.duration) ? jfVideo.duration : jfCurrent.duration,
    playing: !jfVideo.paused && !jfVideo.ended,
  });
}

function reportProgress() {
  if (currentScreen === "youtube") reportYoutubeProgress();
  else if (currentScreen === "jellyfin") reportJellyfinProgress();
  else if (currentScreen === "vinyl") reportVinylProgress();
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  wsConn = new WebSocket(`${proto}://${location.host}/ws`);
  wsConn.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "shutdown") {
        playShutdownAnimation();
      } else if (msg.type && msg.type.startsWith("youtube_")) {
        handleYoutubeMessage(msg);
      } else if (msg.type && msg.type.startsWith("jellyfin_")) {
        handleJellyfinMessage(msg);
      } else if (msg.type && msg.type.startsWith("vinyl_")) {
        handleVinylMessage(msg);
      } else if (msg.type === "timer_state" || msg.type === "clock_show" || msg.type === "clock_hide") {
        handleTimerMessage(msg);
      }
    } catch (err) {
      console.error("WS-Nachricht ungueltig", err);
    }
  };
  wsConn.onclose = () => {
    setTimeout(connectWebSocket, 3000);
  };
}

function playShutdownAnimation() {
  $("shutdown-bar-top").classList.add("active");
  $("shutdown-bar-bottom").classList.add("active");
  setTimeout(() => {
    $("shutdown-flash").classList.add("flash");
  }, 1250);
}

function startBootSequence() {
  setTimeout(() => {
    $("boot-screen").classList.add("hidden");
    showScreen(currentScreen);
    resolveBoot();
    refreshState();
  }, BOOT_DURATION_MS);
}

updateClock();
setInterval(updateClock, 1000);
setInterval(refreshState, STATE_POLL_MS);
setInterval(reportProgress, PROGRESS_REPORT_MS);
setInterval(renderClock, TIMER_TICK_MS);
connectWebSocket();
startBootSequence();
