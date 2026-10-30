"use strict";

/* ============================================================
   Fernbedienung: Sprachschach (chess.com auf dem Fernseher) und
   TV-Browser (Live-Bild vom Fernseher, Handy als Touchpad + Tastatur).
   Nutzt die Helfer aus remote.js ($, h, icon, api, toast, onTap ...).
   ============================================================ */

const CHESS_POLL_MS = 700;
const BOT_TIMES = [
  { label: "Ohne Zeit", value: null },
  { label: "10 min", value: [10, 0] },
  { label: "15 | 10", value: [15, 10] },
  { label: "30 min", value: [30, 0] },
];
const ONLINE_TIMES = [
  { label: "1 min", value: [1, 0], kind: "Bullet" },
  { label: "1 | 1", value: [1, 1], kind: "Bullet" },
  { label: "2 | 1", value: [2, 1], kind: "Bullet" },
  { label: "3 min", value: [3, 0], kind: "Blitz" },
  { label: "3 | 2", value: [3, 2], kind: "Blitz" },
  { label: "5 min", value: [5, 0], kind: "Blitz" },
  { label: "10 min", value: [10, 0], kind: "Schnellschach" },
  { label: "10 | 5", value: [10, 5], kind: "Schnellschach" },
  { label: "15 | 10", value: [15, 10], kind: "Schnellschach" },
  { label: "30 min", value: [30, 0], kind: "Schnellschach" },
];

const cs = {
  mode: "bot",
  bot: null,
  color: "r",
  botTime: 0,
  onlineTime: 6,
  groups: null,
  state: {},
  timer: null,
  listening: false,
  recognition: null,
};

const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

// ---------- Auswahl ----------

function chessTimes() {
  const list = cs.mode === "bot" ? BOT_TIMES : ONLINE_TIMES;
  const selected = cs.mode === "bot" ? cs.botTime : cs.onlineTime;
  $("chess-times").replaceChildren(
    ...list.map((t, i) =>
      h(
        "button",
        {
          class: i === selected ? "chip active" : "chip",
          type: "button",
          onclick: () => {
            if (cs.mode === "bot") cs.botTime = i;
            else cs.onlineTime = i;
            chessTimes();
          },
        },
        t.label
      )
    )
  );
}

function chessPickHead() {
  const head = $("chess-pick-head");
  if (cs.mode === "online") {
    head.replaceChildren(
      h("div", { class: "chess-pick-icon" }, icon("globe")),
      h("div", null, h("div", { class: "chess-pick-name" }, "Online gegen Menschen"), h("div", { class: "chess-pick-sub" }, "Gewertet – zählt für deine Elo"))
    );
    return;
  }
  if (!cs.bot) {
    head.replaceChildren(h("div", { class: "chess-pick-sub" }, "Wähle unten einen Bot aus."));
    return;
  }
  const avatar = h("span", { class: "chess-avatar large" });
  setBackground(avatar, cs.bot.image);
  head.replaceChildren(
    avatar,
    h("div", null, h("div", { class: "chess-pick-name" }, cs.bot.name), h("div", { class: "chess-pick-sub" }, cs.bot.rating ? `Wertung ${cs.bot.rating}` : "Bot"))
  );
}

function renderChessSetup() {
  document.querySelectorAll("#chess-mode .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === cs.mode));
  document.querySelectorAll("#chess-color .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.color === cs.color));
  $("chess-pick").classList.toggle("online", cs.mode === "online");
  $("chess-bots").classList.toggle("hidden", cs.mode !== "bot");
  $("chess-start").disabled = cs.mode === "bot" && !cs.bot;
  chessPickHead();
  chessTimes();
}

function renderBots() {
  if (!cs.groups) return;
  $("chess-bots").replaceChildren(
    ...cs.groups.map((group) =>
      h(
        "div",
        { class: "chess-group" },
        h("div", { class: "chess-group-title" }, group.label, h("span", null, `${group.bots.length}`)),
        h(
          "div",
          { class: "chess-rail" },
          ...group.bots.map((bot) => {
            const avatar = h("span", { class: "chess-avatar" });
            setBackground(avatar, bot.image);
            return h(
              "button",
              {
                class: cs.bot && cs.bot.name === bot.name ? "chess-bot active" : "chess-bot",
                type: "button",
                onclick: (event) => {
                  cs.bot = bot;
                  renderChessSetup();
                  document.querySelectorAll(".chess-bot.active").forEach((el) => el.classList.remove("active"));
                  event.currentTarget.classList.add("active");
                  window.scrollTo({ top: 0, behavior: "smooth" });
                },
              },
              avatar,
              h("span", { class: "chess-bot-name" }, bot.name),
              h("span", { class: "chess-bot-rating" }, bot.rating || "–")
            );
          })
        )
      )
    )
  );
}

document.querySelectorAll("#chess-mode .seg-btn").forEach((b) =>
  b.addEventListener("click", () => {
    cs.mode = b.dataset.mode;
    renderChessSetup();
  })
);
document.querySelectorAll("#chess-color .seg-btn").forEach((b) =>
  b.addEventListener("click", () => {
    cs.color = b.dataset.color;
    renderChessSetup();
  })
);

onTap($("chess-start"), async () => {
  const button = $("chess-start");
  button.disabled = true;
  setIcon(button, "play", "Wird gestartet …");
  try {
    const body =
      cs.mode === "bot"
        ? { mode: "bot", bot: cs.bot.name, color: cs.color, time: BOT_TIMES[cs.botTime].value }
        : { mode: "online", time: ONLINE_TIMES[cs.onlineTime].value };
    cs.state = await api.post("/api/remote/chess/start", body);
    toast(cs.mode === "bot" ? `${cs.bot.name} wartet auf dem Fernseher` : "Gegner wird gesucht …");
    renderChessGame();
  } catch (err) {
    toast(err.message, true);
  } finally {
    setIcon(button, "play", "Partie starten");
    button.disabled = cs.mode === "bot" && !cs.bot;
  }
});

// ---------- Laufende Partie ----------

const PHASE_TEXT = {
  warten: "Warte auf den Gegner …",
  zug: "Du bist dran – sag deinen Zug",
  bestaetigen: "Richtig so?",
  auswahl: "Welche Figur?",
  ende: "Partie beendet",
};

function renderChessGame() {
  const st = cs.state || {};
  const s = st.status || {};
  const inGame = !!st.mode;
  $("chess-setup").classList.toggle("hidden", inGame);
  $("chess-game").classList.toggle("hidden", !inGame);
  if (!inGame) return;

  const color = s.spieltAls === "w" ? "Du spielst Weiß" : s.spieltAls === "b" ? "Du spielst Schwarz" : "";
  $("chess-label").textContent = [st.label, color].filter(Boolean).join(" · ");
  let prompt = st.starting ? "Wird gestartet …" : st.mode === "online" && !s.partie ? "Gegner wird gesucht …" : PHASE_TEXT[s.phase] || "Partie wird vorbereitet …";
  if (s.phase === "bestaetigen" && s.offenerZug) prompt = `${s.offenerZug} – richtig?`;
  if (st.error) prompt = st.error;
  $("chess-prompt").textContent = prompt;
  $("chess-last").textContent = s.gegnerzug ? `Gegner: ${s.gegnerzug}` : "";

  const myTurn = ["zug", "bestaetigen", "auswahl"].includes(s.phase);
  $("chess-mic").classList.toggle("ready", myTurn);
  $("chess-mic").classList.toggle("listening", cs.listening);
  $("chess-confirm").classList.toggle("hidden", s.phase !== "bestaetigen");
  const options = $("chess-options");
  options.classList.toggle("hidden", s.phase !== "auswahl" || !s.optionen);
  if (s.phase === "auswahl" && s.optionen) {
    const key = s.optionen.join("|");
    if (options.dataset.key !== key) {
      options.dataset.key = key;
      options.replaceChildren(
        ...s.optionen.map((text, i) => h("button", { class: "btn btn-ghost", type: "button", onclick: () => chessAction("option", i) }, text))
      );
    }
  }
  if (!cs.listening && st.heard) $("chess-heard").textContent = `„${st.heard}“`;
}

async function pollChess() {
  clearTimeout(cs.timer);
  try {
    cs.state = await api.get("/api/remote/chess");
    renderChessGame();
  } catch (err) {
    // naechster Versuch
  }
  if (currentView === "chess") cs.timer = setTimeout(pollChess, CHESS_POLL_MS);
}

async function loadChess() {
  if (!cs.groups) {
    try {
      const data = await api.get("/api/remote/chess?bots=true");
      cs.groups = data.bots;
      cs.state = data;
    } catch (err) {
      toast(err.message, true);
    }
  }
  renderChessSetup();
  renderBots();
  pollChess();
}

async function chessAction(action, value) {
  try {
    cs.state = await api.post("/api/remote/chess/action", { action, value });
    renderChessGame();
  } catch (err) {
    toast(err.message, true);
  }
}

onTap($("chess-yes"), () => chessAction("ja"));
onTap($("chess-no"), () => chessAction("nein"));
onTap($("chess-repeat"), () => chessAction("wiederholen"));
onTap($("chess-board"), () => chessAction("anzeige"));
onTap($("chess-end"), async () => {
  await chessAction("beenden");
  toast("Schach beendet");
});

$("chess-type").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("chess-type-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  chessAction("tippen", text);
});

// Spracherkennung auf dem Handy (Safari: nur ueber HTTPS, d.h. ueber die
// Cloudflare-Adresse). Ein Tipp = ein Zug bzw. ein "Ja"/"Nein".
function stopListening() {
  cs.listening = false;
  if (cs.recognition) {
    try { cs.recognition.abort(); } catch (err) {}
    cs.recognition = null;
  }
  $("chess-mic-label").textContent = "Tippen und Zug sagen";
  renderChessGame();
}

function startListening() {
  if (!SpeechRec) {
    toast(window.isSecureContext ? "Spracherkennung gibt es in diesem Browser nicht – tippe den Zug oder nutze das Diktier-Mikrofon der Tastatur" : "Sprechen geht nur über die https-Adresse der Fernbedienung", true);
    $("chess-type-input").focus();
    return;
  }
  const rec = new SpeechRec();
  rec.lang = "de-DE";
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 5;
  cs.recognition = rec;
  cs.listening = true;
  $("chess-mic-label").textContent = "Ich höre zu …";
  $("chess-heard").textContent = " ";
  rec.onresult = (event) => {
    const result = event.results[event.results.length - 1];
    const alternatives = [...result].map((a) => a.transcript.trim()).filter(Boolean);
    $("chess-heard").textContent = alternatives[0] ? `„${alternatives[0]}“` : " ";
    if (result.isFinal) {
      stopListening();
      api.post("/api/remote/chess/heard", { alternatives }).catch((err) => toast(err.message, true));
    }
  };
  rec.onerror = (event) => {
    if (event.error === "not-allowed") toast("Mikrofon ist nicht erlaubt – in den Safari-Einstellungen freigeben", true);
    else if (event.error !== "no-speech" && event.error !== "aborted") toast(`Spracherkennung: ${event.error}`, true);
    stopListening();
  };
  rec.onend = () => {
    if (cs.listening) stopListening();
  };
  try {
    rec.start();
  } catch (err) {
    stopListening();
  }
  renderChessGame();
}

$("chess-mic").addEventListener("click", () => (cs.listening ? stopListening() : startListening()));

VIEW_HOOKS.chess = () => loadChess();

// ---------- TV-Browser ----------

const tvb = { ws: null, retry: null, frameSize: null, pointer: null, scrollAcc: { dx: 0, dy: 0 }, scrollRaf: 0, lastUrl: "" };

function browserWsUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const secret = getSecret();
  return `${proto}://${location.host}/ws/remote/browser${secret ? `?secret=${encodeURIComponent(secret)}` : ""}`;
}

function setBrowserOpen(open) {
  $("tvb-empty").classList.toggle("hidden", open);
  $("tvb-screen").classList.toggle("live", open);
}

function connectBrowser() {
  if (tvb.ws || currentView !== "browser") return;
  const ws = new WebSocket(browserWsUrl());
  tvb.ws = ws;
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type !== "frame") return;
    $("tvb-img").src = `data:image/jpeg;base64,${msg.data}`;
    tvb.frameSize = { w: msg.w, h: msg.h };
    setBrowserOpen(true);
    if (msg.url && msg.url !== tvb.lastUrl && document.activeElement !== $("tvb-url")) {
      tvb.lastUrl = msg.url;
      $("tvb-url").value = msg.url;
    }
  };
  ws.onclose = () => {
    tvb.ws = null;
    if (currentView === "browser") tvb.retry = setTimeout(connectBrowser, 2000);
  };
}

function disconnectBrowser() {
  clearTimeout(tvb.retry);
  if (tvb.ws) {
    const ws = tvb.ws;
    tvb.ws = null;
    ws.onclose = null;
    ws.close();
  }
}

function sendBrowser(msg) {
  if (tvb.ws && tvb.ws.readyState === WebSocket.OPEN) tvb.ws.send(JSON.stringify(msg));
}

async function browserAction(action, extra) {
  try {
    const info = await api.post("/api/remote/browser", { action, ...extra });
    setBrowserOpen(info.open);
    if (info.url) $("tvb-url").value = info.url;
    connectBrowser();
    return info;
  } catch (err) {
    toast(err.message, true);
    return null;
  }
}

async function loadBrowser() {
  try {
    const info = await api.get("/api/remote/browser");
    setBrowserOpen(info.open);
    if (info.url) $("tvb-url").value = info.url;
  } catch (err) {
    toast(err.message, true);
  }
  connectBrowser();
}

$("tvb-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const url = $("tvb-url").value.trim();
  $("tvb-url").blur();
  browserAction(tvb.ws && $("tvb-screen").classList.contains("live") ? "navigate" : "open", { url });
});
onTap($("tvb-open"), () => browserAction("open", { url: $("tvb-url").value.trim() }));
onTap($("tvb-back"), () => browserAction("back"));
onTap($("tvb-forward"), () => browserAction("forward"));
onTap($("tvb-reload"), () => browserAction("reload"));
onTap($("tvb-close"), async () => {
  await browserAction("close");
  setBrowserOpen(false);
  $("tvb-img").removeAttribute("src");
});
document.querySelectorAll(".tvb-keys [data-key]").forEach((b) => b.addEventListener("click", () => sendBrowser({ type: "key", key: b.dataset.key })));

// Bild antippen = Klick, wischen = scrollen (wie ein Touchscreen)
function relativePoint(event) {
  const rect = $("tvb-img").getBoundingClientRect();
  return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height, rect };
}

const screenImg = $("tvb-img");
screenImg.addEventListener("pointerdown", (event) => {
  tvb.pointer = { x: event.clientX, y: event.clientY, start: relativePoint(event), moved: false };
  screenImg.setPointerCapture(event.pointerId);
});
screenImg.addEventListener("pointermove", (event) => {
  const p = tvb.pointer;
  if (!p) return;
  const dx = event.clientX - p.x;
  const dy = event.clientY - p.y;
  if (!p.moved && Math.hypot(dx, dy) < 8) return;
  p.moved = true;
  p.x = event.clientX;
  p.y = event.clientY;
  // Bildschirm-Pixel des Handys -> Pixel auf dem Fernseher
  const scale = tvb.frameSize ? tvb.frameSize.w / p.start.rect.width : 2;
  tvb.scrollAcc.dx -= dx * scale;
  tvb.scrollAcc.dy -= dy * scale;
  if (!tvb.scrollRaf) {
    tvb.scrollRaf = requestAnimationFrame(() => {
      tvb.scrollRaf = 0;
      sendBrowser({ type: "scroll", x: p.start.x, y: p.start.y, dx: tvb.scrollAcc.dx, dy: tvb.scrollAcc.dy });
      tvb.scrollAcc = { dx: 0, dy: 0 };
    });
  }
});
screenImg.addEventListener("pointerup", (event) => {
  const p = tvb.pointer;
  tvb.pointer = null;
  if (p && !p.moved) {
    const point = relativePoint(event);
    sendBrowser({ type: "tap", x: point.x, y: point.y });
  }
});
screenImg.addEventListener("pointercancel", () => (tvb.pointer = null));

// Tastatur: jede Taste geht sofort an das Feld, das auf dem Fernseher den
// Fokus hat (z.B. das Passwortfeld von chess.com). Hier bleibt nichts stehen.
const kbd = $("tvb-input");
onTap($("tvb-kbd"), () => kbd.focus());
kbd.addEventListener("beforeinput", (event) => {
  event.preventDefault();
  if (event.inputType === "insertText" || event.inputType === "insertReplacementText" || event.inputType === "insertFromPaste") {
    const text = event.data || (event.dataTransfer && event.dataTransfer.getData("text")) || "";
    if (text) sendBrowser({ type: "text", text });
  } else if (event.inputType === "deleteContentBackward") {
    sendBrowser({ type: "key", key: "Backspace" });
  } else if (event.inputType === "insertLineBreak" || event.inputType === "insertParagraph") {
    sendBrowser({ type: "key", key: "Enter" });
  }
});
kbd.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    sendBrowser({ type: "key", key: "Enter" });
  } else if (event.key === "Tab") {
    event.preventDefault();
    sendBrowser({ type: "key", key: "Tab" });
  }
});
kbd.addEventListener("input", () => (kbd.value = ""));

VIEW_HOOKS.browser = () => loadBrowser();

// Beim Verlassen der Ansichten Verbindungen/Abfragen beenden
window.addEventListener("popstate", () => {
  if (currentView !== "browser") disconnectBrowser();
  if (currentView !== "chess") {
    clearTimeout(cs.timer);
    if (cs.listening) stopListening();
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") disconnectBrowser();
  else if (currentView === "browser") connectBrowser();
});
