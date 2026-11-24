"use strict";

/* ============================================================
   Fernbedienung: TV-Browser (Live-Bild vom Fernseher, Handy als
   Touchpad + Tastatur). Nutzt die Helfer aus remote.js ($, h, icon,
   api, toast, onTap ...).
   ============================================================ */

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
// Fokus hat (z.B. ein Suchfeld oder Passwortfeld). Hier bleibt nichts stehen.
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
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") disconnectBrowser();
  else if (currentView === "browser") connectBrowser();
});
