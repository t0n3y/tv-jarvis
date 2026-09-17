const BOOT_DURATION_MS = 4000;
const STATE_POLL_MS = 15000;
const WEEKDAY_NAMES = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];

function $(id) {
  return document.getElementById(id);
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

// ---------- YouTube-Player (gesteuert per WebSocket von /remote.html) ----------

let ytPlayer = null;
let ytReady = false;
const ytPendingQueue = [];

function onYouTubeIframeAPIReady() {
  ytPlayer = new YT.Player("youtube-player", {
    height: "100%",
    width: "100%",
    playerVars: { autoplay: 1, controls: 0, rel: 0 },
    events: {
      onReady: () => {
        ytReady = true;
        ytPendingQueue.splice(0).forEach((fn) => fn());
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

function showPlayerScreen() {
  $("player-screen").classList.remove("hidden");
  $("dashboard").classList.add("hidden");
}

function hidePlayerScreen() {
  $("player-screen").classList.add("hidden");
  $("dashboard").classList.remove("hidden");
}

function handleYoutubeMessage(msg) {
  if (msg.type === "youtube_play") {
    showPlayerScreen();
    withYtPlayer(() => ytPlayer.loadVideoById(msg.video_id));
  } else if (msg.type === "youtube_pause") {
    withYtPlayer(() => ytPlayer.pauseVideo());
  } else if (msg.type === "youtube_resume") {
    withYtPlayer(() => ytPlayer.playVideo());
  } else if (msg.type === "youtube_stop") {
    withYtPlayer(() => ytPlayer.stopVideo());
    hidePlayerScreen();
  }
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "shutdown") {
        playShutdownAnimation();
      } else if (msg.type && msg.type.startsWith("youtube_")) {
        handleYoutubeMessage(msg);
      }
    } catch (err) {
      console.error("WS-Nachricht ungueltig", err);
    }
  };
  ws.onclose = () => {
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
    $("dashboard").classList.remove("hidden");
    refreshState();
  }, BOOT_DURATION_MS);
}

updateClock();
setInterval(updateClock, 1000);
setInterval(refreshState, STATE_POLL_MS);
connectWebSocket();
startBootSequence();
