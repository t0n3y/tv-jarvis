// ---------- Secret / Status / API-Grundfunktionen ----------

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
    // localStorage evtl. nicht verfuegbar (privater Modus) - dann eben ohne
  }
}

function setStatus(text, isError) {
  const el = document.getElementById("status-line");
  el.textContent = text;
  el.style.color = isError ? "var(--accent-warn)" : "";
  if (text) {
    setTimeout(() => {
      if (el.textContent === text) el.textContent = "";
    }, 3000);
  }
}

async function apiRequest(method, path, body, retried) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const secret = getSecret();
  if (secret) headers["X-Remote-Secret"] = secret;

  const resp = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401 && !retried) {
    const entered = window.prompt("Fernbedienungs-Passwort erforderlich:");
    if (!entered) throw new Error("Kein Passwort angegeben");
    setSecret(entered);
    return apiRequest(method, path, body, true);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail || detail;
    } catch (err) {
      // Antwort war kein JSON - egal, statusText reicht als Meldung
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

const apiGet = (path) => apiRequest("GET", path);
const apiPost = (path, body) => apiRequest("POST", path, body || {});
const apiDelete = (path) => apiRequest("DELETE", path);

function bind(id, action, successText) {
  document.getElementById(id).addEventListener("click", async () => {
    try {
      await action();
      if (successText) setStatus(successText);
    } catch (err) {
      setStatus(err.message || "Fehler", true);
    }
  });
}

// ---------- Homescreen / App-Navigation ----------

const VIEWS = ["home", "youtube", "radio", "settings"];

function showView(name) {
  VIEWS.forEach((v) => {
    document.getElementById(`view-${v}`).classList.toggle("hidden", v !== name);
  });
  if (name === "radio") loadRadioStations();
  if (name === "settings") loadSettingsData();
}

document.querySelectorAll("[data-view]").forEach((el) => {
  el.addEventListener("click", () => showView(el.dataset.view));
});
document.querySelectorAll("[data-back]").forEach((el) => {
  el.addEventListener("click", () => showView("home"));
});
document.getElementById("dock-home").addEventListener("click", () => showView("home"));

// ---------- Fernseher (Homescreen) ----------

bind("btn-power-on", () => apiPost("/api/remote/power", { state: "on" }), "Fernseher wird eingeschaltet …");
bind("btn-power-off", () => apiPost("/api/remote/power", { state: "off" }), "Fernseher wird ausgeschaltet …");

// ---------- Lautstaerke (Dock, von ueberall erreichbar) ----------

bind("dock-vol-up", () => apiPost("/api/remote/volume", { delta: 1 }));
bind("dock-vol-down", () => apiPost("/api/remote/volume", { delta: -1 }));
bind("dock-mute", () => apiPost("/api/remote/volume", { delta: 0 }));

// ---------- YouTube-App ----------

let ytState = { video_id: null, title: null, thumbnail_url: null, current_time: 0, duration: 0, playing: false };
let scrubbing = false;

function formatTime(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderYoutubeState() {
  document.getElementById("yt-title").textContent = ytState.title || "Kein Video geladen";
  document.getElementById("yt-thumb").style.backgroundImage = ytState.thumbnail_url
    ? `url(${ytState.thumbnail_url})`
    : "none";

  const progress = document.getElementById("yt-progress");
  if (!scrubbing) {
    progress.max = ytState.duration || 0;
    progress.value = ytState.current_time || 0;
  }
  document.getElementById("yt-time-current").textContent = formatTime(ytState.current_time);
  document.getElementById("yt-time-duration").textContent = formatTime(ytState.duration);

  document.getElementById("btn-play-pause").textContent = ytState.playing ? "Pause" : "Weiter";
}

bind(
  "btn-yt-play",
  () => {
    const url = document.getElementById("yt-url").value.trim();
    if (!url) return Promise.reject(new Error("Bitte einen YouTube-Link eingeben"));
    return apiPost("/api/remote/youtube", { action: "play", url });
  },
  "Video wird gestartet …"
);

bind("btn-play-pause", () => apiPost("/api/remote/youtube", { action: ytState.playing ? "pause" : "resume" }));
bind("btn-seek-back", () => apiPost("/api/remote/youtube", { action: "seek", seconds: -10 }));
bind("btn-seek-fwd", () => apiPost("/api/remote/youtube", { action: "seek", seconds: 10 }));

bind(
  "btn-yt-stop",
  () => {
    document.getElementById("yt-url").value = "";
    return apiPost("/api/remote/youtube", { action: "stop" });
  },
  "Video gestoppt"
);

const ytProgressEl = document.getElementById("yt-progress");
ytProgressEl.addEventListener("input", () => {
  scrubbing = true;
  document.getElementById("yt-time-current").textContent = formatTime(Number(ytProgressEl.value));
});
ytProgressEl.addEventListener("change", () => {
  const seconds = Number(ytProgressEl.value);
  apiPost("/api/remote/youtube", { action: "seek_to", seconds }).catch((err) => setStatus(err.message || "Fehler", true));
  scrubbing = false;
});

// ---------- Radio-App ----------

let radioState = { playing: false, station: null };
let stationsCache = [];

async function loadRadioStations() {
  try {
    const data = await apiGet("/api/remote/radio/stations");
    stationsCache = data.stations || [];
    renderStationList();
  } catch (err) {
    setStatus(err.message || "Fehler beim Laden der Sender", true);
  }
}

function renderStationList() {
  const list = document.getElementById("station-list");
  if (!list) return;
  list.innerHTML = "";
  stationsCache.forEach((station) => {
    const li = document.createElement("li");
    li.className = "station-item";
    const isActive = radioState.playing && radioState.station && radioState.station.id === station.id;
    li.classList.toggle("active", !!isActive);

    const btn = document.createElement("button");
    btn.className = "btn station-btn";
    const nameSpan = document.createElement("span");
    nameSpan.className = "station-name";
    nameSpan.textContent = station.name;
    btn.appendChild(nameSpan);
    btn.addEventListener("click", () => {
      apiPost("/api/remote/radio", { action: "play", station_id: station.id })
        .then(() => setStatus(`${station.name} wird gestartet …`))
        .catch((err) => setStatus(err.message || "Fehler", true));
    });

    li.appendChild(btn);
    list.appendChild(li);
  });
}

bind("btn-radio-stop", () => apiPost("/api/remote/radio", { action: "stop" }), "Radio gestoppt");

// ---------- Einstellungen-App ----------

async function loadSettingsData() {
  try {
    const schedule = await apiGet("/api/remote/schedule");
    document.getElementById("sched-enabled").checked = !!schedule.enabled;
    document.getElementById("sched-weekday-wake").value = schedule.weekday.wake_time;
    document.getElementById("sched-weekday-leave").value = schedule.weekday.leave_time;
    document.getElementById("sched-weekend-wake").value = schedule.weekend.wake_time;
    document.getElementById("sched-weekend-leave").value = schedule.weekend.leave_time;
  } catch (err) {
    setStatus(err.message || "Fehler beim Laden des Zeitplans", true);
  }
  loadSettingsStations();
}

async function loadSettingsStations() {
  try {
    const data = await apiGet("/api/remote/radio/stations");
    stationsCache = data.stations || [];
    const list = document.getElementById("settings-station-list");
    list.innerHTML = "";
    stationsCache.forEach((station) => {
      const li = document.createElement("li");
      li.className = "station-item";

      const nameSpan = document.createElement("span");
      nameSpan.className = "station-name";
      nameSpan.textContent = station.name;

      const delBtn = document.createElement("button");
      delBtn.className = "input-clear-btn";
      delBtn.innerHTML = "&times;";
      delBtn.setAttribute("aria-label", `${station.name} entfernen`);
      delBtn.addEventListener("click", () => {
        apiDelete(`/api/remote/radio/stations/${encodeURIComponent(station.id)}`)
          .then(() => {
            setStatus("Sender entfernt");
            loadSettingsStations();
          })
          .catch((err) => setStatus(err.message || "Fehler", true));
      });

      li.appendChild(nameSpan);
      li.appendChild(delBtn);
      list.appendChild(li);
    });
  } catch (err) {
    setStatus(err.message || "Fehler beim Laden der Sender", true);
  }
}

bind(
  "btn-schedule-save",
  () => {
    const body = {
      enabled: document.getElementById("sched-enabled").checked,
      weekday: {
        wake_time: document.getElementById("sched-weekday-wake").value,
        leave_time: document.getElementById("sched-weekday-leave").value,
      },
      weekend: {
        wake_time: document.getElementById("sched-weekend-wake").value,
        leave_time: document.getElementById("sched-weekend-leave").value,
      },
    };
    return apiPost("/api/remote/schedule", body);
  },
  "Zeitplan gespeichert"
);

bind(
  "btn-add-station",
  () => {
    const nameEl = document.getElementById("new-station-name");
    const urlEl = document.getElementById("new-station-url");
    const name = nameEl.value.trim();
    const url = urlEl.value.trim();
    if (!name || !url) return Promise.reject(new Error("Name und Stream-URL angeben"));
    nameEl.value = "";
    urlEl.value = "";
    return apiPost("/api/remote/radio/stations", { name, url }).then(loadSettingsStations);
  },
  "Sender hinzugefügt"
);

// ---------- Globaler Zustand (Dock-Icon + offene App-Ansicht) ----------

document.getElementById("dock-play-pause").addEventListener("click", async () => {
  try {
    if (ytState.video_id) {
      await apiPost("/api/remote/youtube", { action: ytState.playing ? "pause" : "resume" });
    } else if (radioState.station) {
      await apiPost("/api/remote/radio", {
        action: radioState.playing ? "stop" : "play",
        station_id: radioState.station.id,
      });
    }
  } catch (err) {
    setStatus(err.message || "Fehler", true);
  }
});

function renderDock() {
  const isPlaying = ytState.playing || radioState.playing;
  document.getElementById("dock-play-pause").innerHTML = isPlaying ? "&#10073;&#10073;" : "&#9654;";
}

async function pollNowPlaying() {
  try {
    const data = await apiGet("/api/remote/now-playing");
    ytState = { ...ytState, ...data.youtube };
    radioState = data.radio || { playing: false, station: null };
    renderYoutubeState();
    renderStationList();
    renderDock();
  } catch (err) {
    // Stilles Scheitern (z.B. Secret noch nicht gesetzt) - apiRequest kuemmert
    // sich bereits selbst um den Passwort-Dialog bei 401.
  }
}

showView("home");
renderYoutubeState();
renderDock();
setInterval(pollNowPlaying, 1500);
pollNowPlaying();
