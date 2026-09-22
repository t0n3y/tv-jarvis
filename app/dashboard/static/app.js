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

function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  $("clock").textContent = `${hh}:${mm}`;
  $("date-label").textContent = `${WEEKDAY_NAMES[now.getDay()]}, ${now.toLocaleDateString("de-DE")}`;
}

function renderWeather(weather) {
  const el = $("weather-content");
  if (!weather) {
    el.innerHTML = `<span class="weather-desc">Keine Wetterdaten verfügbar.</span>`;
    return;
  }
  el.innerHTML = `
    <div class="weather-current">
      <div class="weather-icon">${weather.icon}</div>
      <div>
        <div class="weather-temp">${Math.round(weather.temp_current)}&deg;</div>
        <div class="weather-desc">${weather.description}</div>
      </div>
    </div>
    <div class="weather-range">
      Heute ${Math.round(weather.temp_min)}&deg; / ${Math.round(weather.temp_max)}&deg;
      &middot; Regenwahrscheinlichkeit ${weather.precipitation_probability}%
    </div>`;
}

function renderList(elementId, items, emptyText, mapFn) {
  const el = $(elementId);
  if (!items || items.length === 0) {
    el.innerHTML = `<li class="empty">${emptyText}</li>`;
    return;
  }
  el.innerHTML = items.map(mapFn).join("");
}

function renderEvents(events) {
  renderList("calendar-content", events, "Keine Termine heute.", (e) => {
    const label = e.all_day ? "ganztägig" : e.time_label;
    return `<li><span class="time">${label}</span><span>${e.title}</span></li>`;
  });
}

function renderPlan(state) {
  const panel = $("plan-panel");
  if (!state.is_school_day) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  $("plan-title").textContent = "Stundenplan / Vertretung";
  renderList("plan-content", state.substitution_plan, "Keine Änderungen im Vertretungsplan.", (p) => {
    const parts = [p.subject, p.room].filter(Boolean).join(" · ");
    const separator = parts && p.note ? " — " : "";
    const noteHtml = p.note ? `<span class="note">${p.note}</span>` : "";
    return `<li><span class="time">${p.lesson || ""}</span><span>${parts}${separator}${noteHtml}</span></li>`;
  });
}

function renderTodos(todos) {
  renderList("todos-content", todos, "Keine ToDos für heute.", (t) => `<li><span>${t}</span></li>`);
}

function renderErrors(errors) {
  const el = $("errors");
  if (!errors || errors.length === 0) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.classList.remove("hidden");
  el.textContent = "Hinweise: " + errors.join(" | ");
}

async function refreshState() {
  try {
    const resp = await fetch("/api/state");
    if (!resp.ok) return;
    const state = await resp.json();

    renderWeather(state.weather);
    renderEvents(state.events);
    renderPlan(state);
    renderTodos(state.todos);
    renderErrors(state.errors);

    $("onair").classList.toggle("hidden", !state.radio_playing);
  } catch (err) {
    console.error("Konnte /api/state nicht laden", err);
  }
}

// ---------- Bildschirme: Dashboard / YouTube / Jellyfin ----------

let currentScreen = "dashboard";
let resolveBoot;
// Abspiel-Befehle, die waehrend der Boot-Animation eintreffen (Fernseher wurde
// gerade fuers Abspielen eingeschaltet), starten erst danach.
const bootDone = new Promise((resolve) => {
  resolveBoot = resolve;
});

function showScreen(name) {
  if (currentScreen === "youtube" && name !== "youtube") stopYoutubePlayback();
  if (currentScreen === "jellyfin" && name !== "jellyfin") stopJellyfinPlayback();
  currentScreen = name;
  $("dashboard").classList.toggle("hidden", name !== "dashboard");
  $("player-screen").classList.toggle("hidden", name !== "youtube");
  $("jellyfin-screen").classList.toggle("hidden", name !== "jellyfin");
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
connectWebSocket();
startBootSequence();
