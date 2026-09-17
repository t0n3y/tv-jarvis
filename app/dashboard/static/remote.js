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

async function apiPost(path, body, retried) {
  const headers = { "Content-Type": "application/json" };
  const secret = getSecret();
  if (secret) headers["X-Remote-Secret"] = secret;

  const resp = await fetch(path, { method: "POST", headers, body: JSON.stringify(body || {}) });

  if (resp.status === 401 && !retried) {
    const entered = window.prompt("Fernbedienungs-Passwort erforderlich:");
    if (!entered) throw new Error("Kein Passwort angegeben");
    setSecret(entered);
    return apiPost(path, body, true);
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
  return resp.json();
}

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

bind("btn-power-on", () => apiPost("/api/remote/power", { state: "on" }), "Fernseher wird eingeschaltet …");
bind("btn-power-off", () => apiPost("/api/remote/power", { state: "off" }), "Fernseher wird ausgeschaltet …");

bind("btn-vol-up", () => apiPost("/api/remote/volume", { delta: 1 }));
bind("btn-vol-down", () => apiPost("/api/remote/volume", { delta: -1 }));
bind("btn-mute", () => apiPost("/api/remote/volume", { delta: 0 }));

bind(
  "btn-yt-play",
  () => {
    const url = document.getElementById("yt-url").value.trim();
    if (!url) return Promise.reject(new Error("Bitte einen YouTube-Link eingeben"));
    return apiPost("/api/remote/youtube", { action: "play", url });
  },
  "Video wird gestartet …"
);
bind("btn-yt-pause", () => apiPost("/api/remote/youtube", { action: "pause" }));
bind("btn-yt-resume", () => apiPost("/api/remote/youtube", { action: "resume" }));
bind("btn-yt-stop", () => apiPost("/api/remote/youtube", { action: "stop" }), "Video gestoppt");
