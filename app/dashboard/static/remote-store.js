"use strict";

/* ============================================================
   Fernbedienung: Einrichtung beim ersten Start, App Store, Name.
   Nutzt die Helfer aus remote.js ($, h, icon, api, toast, onTap,
   openView, showView, VIEW_HOOKS, setSecret, userName, updateClock).
   ============================================================ */

const store = { apps: [], system: null, current: null };

// Symbole, die nur der App Store braucht
document.querySelector("svg.sprite").insertAdjacentHTML(
  "beforeend",
  `<symbol id="i-bag" viewBox="0 0 24 24"><path d="M5 8h14l-1 12.5H6z"/><path d="M9 10.5V7a3 3 0 0 1 6 0v3.5"/></symbol>
  <symbol id="i-school" viewBox="0 0 24 24"><path d="M2.5 9 12 4.5 21.5 9 12 13.5z"/><path d="M6.5 11v5c1.5 1.6 3.4 2.4 5.5 2.4s4-.8 5.5-2.4v-5"/><path d="M21.5 9v5.5"/></symbol>
  <symbol id="i-calendar" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></symbol>
  <symbol id="i-star" viewBox="0 0 24 24"><path d="m12 3.8 2.5 5.1 5.6.8-4 4 .9 5.6-5-2.7-5 2.7.9-5.6-4-4 5.6-.8z"/></symbol>
  <symbol id="i-book" viewBox="0 0 24 24"><path d="M12 6.5c-1.8-1.3-4.3-2-7.5-2v13c3.2 0 5.7.7 7.5 2 1.8-1.3 4.3-2 7.5-2v-13c-3.2 0-5.7.7-7.5 2z"/><path d="M12 6.5v13"/></symbol>`
);

// Kacheln auf dem Homescreen, die zu einer App aus dem Store gehoeren
const TILE_APPS = { jellyfin: "jellyfin", youtube: "youtube", twitch: "twitch", vinyl: "vinyl", light: "light" };

function applyName(name) {
  if (!name) return;
  document.title = name;
  document.querySelector(".wordmark").textContent = name;
  document.querySelector('meta[name="apple-mobile-web-app-title"]').setAttribute("content", name);
}

function applyEnabledApps(enabled) {
  if (!enabled) return;
  for (const [tile, appId] of Object.entries(TILE_APPS)) {
    const el = document.querySelector(`.app-grid [data-open="${tile}"]`);
    if (el) el.classList.toggle("hidden", enabled[appId] === false);
  }
  const comics = document.getElementById("tile-comics");
  if (comics) comics.classList.toggle("hidden", enabled.comics === false);
  document.querySelectorAll(".app-grid [data-plugin]").forEach((tile) => tile.classList.toggle("hidden", !enabled[tile.dataset.plugin]));
}

// ---------- Homescreen: Kacheln Comics + App Store ----------

(function addTiles() {
  const grid = document.querySelector("#view-home .app-grid");
  const settings = grid.querySelector('[data-open="settings"]');
  const comics = h(
    "a",
    { class: "app-tile", id: "tile-comics", href: "/comics.html", style: "--app-rgb: 255, 149, 0" },
    h("span", { class: "app-icon" }, icon("book")),
    h("span", { class: "app-name" }, "Comics")
  );
  const shop = h(
    "button",
    { class: "app-tile", type: "button", style: "--app-rgb: 10, 132, 255", onclick: () => openView("store") },
    h("span", { class: "app-icon" }, icon("bag")),
    h("span", { class: "app-name" }, "App Store")
  );
  grid.insertBefore(comics, settings);
  grid.insertBefore(shop, settings);
})();

// ---------- Ansichten anlegen ----------

const views = document.querySelector("main.views");

views.append(
  h(
    "section",
    { class: "view hidden", id: "view-store" },
    h(
      "div",
      { class: "view-header" },
      h("button", { class: "icon-btn", "aria-label": "Zurück", onclick: () => goHome() }, icon("back")),
      h("h1", null, "App Store")
    ),
    h("p", { class: "store-lead" }, "Schalte ein, was du nutzen möchtest. Jede App hat eine Anleitung zum Einrichten."),
    h("div", { id: "store-list" }),
    h("div", { class: "section-label" }, "App hinzufügen"),
    h(
      "div",
      { class: "card stack" },
      h("label", { class: "field" }, h("input", { id: "store-install-url", type: "url", placeholder: "https://github.com/name/meine-app", autocomplete: "off", autocapitalize: "off", spellcheck: "false" })),
      h("button", { class: "btn btn-ghost btn-block", type: "button", id: "store-install" }, icon("plus"), "Installieren")
    ),
    h("p", { class: "hint" }, "Link zu einem Git-Repo mit einer App für RPi TV. Apps aus dem Netz können alles auf dem Pi tun – nur aus Quellen installieren, denen du vertraust. Eigene Apps bauen: apps/README.md im Projekt.")
  ),
  h(
    "section",
    { class: "view hidden", id: "view-store-app" },
    h(
      "div",
      { class: "view-header" },
      h("button", { class: "icon-btn", "aria-label": "Zurück", onclick: () => openView("store") }, icon("back")),
      h("h1", { id: "store-app-title" }, "")
    ),
    h("div", { id: "store-app-body" })
  )
);

VIEW_HOOKS.store = () => loadStore();
VIEW_HOOKS["store-app"] = () => renderStoreApp();

// ---------- App Store: Liste ----------

async function loadStore() {
  try {
    const data = await api.get("/api/remote/apps");
    store.apps = data.apps;
    renderStore();
  } catch (err) {
    toast(err.message, true);
  }
}

function appBadge(app, big = false) {
  return h("span", { class: `store-badge${big ? " big" : ""}`, style: `--app-rgb: ${app.color}` }, icon(app.icon));
}

function appStatus(app) {
  if (app.error) return "Fehler";
  if (!app.enabled) return "Aus";
  return app.configured ? "An" : "An · Einrichtung fehlt";
}

function renderStore() {
  const categories = [];
  for (const app of store.apps) {
    let group = categories.find((c) => c.name === app.category);
    if (!group) categories.push((group = { name: app.category, apps: [] }));
    group.apps.push(app);
  }
  $("store-list").replaceChildren(
    ...categories.map((category) =>
      h(
        "div",
        { class: "store-cat" },
        h("div", { class: "section-label" }, category.name),
        h(
          "div",
          { class: "group" },
          ...category.apps.map((app) =>
            h(
              "button",
              { class: "store-row", type: "button", onclick: () => openStoreApp(app.id) },
              appBadge(app),
              h(
                "span",
                { class: "store-row-main" },
                h("span", { class: "store-row-name" }, app.name),
                h("span", { class: "store-row-sub" }, app.summary)
              ),
              h("span", { class: `store-state${app.enabled ? (app.configured ? " on" : " warn") : ""}` }, appStatus(app)),
              icon("forward-arrow")
            )
          )
        )
      )
    )
  );
}

function openStoreApp(id) {
  store.current = id;
  if (currentView === "store-app") renderStoreApp();
  else openView("store-app");
}

// ---------- App Store: Detailseite ----------

function fieldInput(field) {
  const attrs = { "data-key": field.key, autocomplete: "off", autocapitalize: "off", spellcheck: "false" };
  if (field.type === "lines") {
    return h("textarea", { ...attrs, class: "store-textarea", rows: 3, placeholder: field.placeholder || "" }, field.value || "");
  }
  const input = h("input", {
    ...attrs,
    type: field.type === "password" ? "password" : field.type === "url" ? "url" : field.type === "number" ? "number" : "text",
    placeholder: field.is_set ? "Gespeichert – leer lassen zum Behalten" : field.placeholder || "",
  });
  input.value = field.value || "";
  return h("label", { class: "field" }, input);
}

function renderStoreApp() {
  const app = store.apps.find((a) => a.id === store.current);
  if (!app) {
    showView("store");
    return;
  }
  $("store-app-title").textContent = app.name;
  const toggle = h("input", { type: "checkbox", id: "store-enabled" });
  toggle.checked = app.enabled;
  toggle.addEventListener("change", () => saveStoreApp(app, { onlyToggle: true }));

  const fields = app.fields.map((field) => {
    const input = fieldInput(field);
    const extra = [];
    if (field.generate) {
      extra.push(
        h("button", {
          class: "btn btn-ghost store-mini",
          type: "button",
          onclick: () => {
            input.querySelector("input").value = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
            input.querySelector("input").type = "text";
          },
        }, "Erzeugen")
      );
    }
    return h(
      "div",
      { class: "store-field" },
      h("div", { class: "store-field-label" }, field.label, field.is_set ? h("span", { class: "store-saved" }, " · gespeichert") : null),
      input,
      ...extra
    );
  });

  const guide = h("ol", { class: "store-guide" });
  for (const step of app.guide) {
    // Anleitungstexte stammen aus app/apps.py (eigener Code), mit etwas HTML
    const li = document.createElement("li");
    li.innerHTML = step;
    guide.append(li);
  }

  $("store-app-body").replaceChildren(
    h(
      "div",
      { class: "store-hero" },
      appBadge(app, true),
      h(
        "div",
        { class: "store-hero-text" },
        h("div", { class: "store-hero-name" }, app.name),
        h("div", { class: "store-hero-cat" }, [app.category, app.author && `von ${app.author}`, app.version && `Version ${app.version}`].filter(Boolean).join(" · "))
      )
    ),
    app.error ? h("div", { class: "store-test bad" }, `Diese App hat einen Fehler: ${app.error}`) : null,
    app.summary ? h("p", { class: "store-summary" }, app.summary) : null,
    h(
      "div",
      { class: "group" },
      h("div", { class: "group-row" }, h("span", { class: "row-label" }, "Auf dem Homescreen & Fernseher"), h("label", { class: "switch" }, toggle, h("span", { class: "switch-slider" })))
    ),
    fields.length ? h("div", { class: "section-label" }, "Einstellungen") : null,
    fields.length ? h("div", { class: "card stack" }, ...fields) : null,
    fields.length ? h("button", { class: "btn btn-primary btn-block", type: "button", onclick: () => saveStoreApp(app) }, icon("check"), "Speichern") : null,
    app.testable ? h("button", { class: "btn btn-ghost btn-block", type: "button", onclick: () => testStoreApp(app) }, "Verbindung testen") : null,
    h("div", { class: "store-test hidden", id: "store-test" }),
    app.guide.length ? h("div", { class: "section-label" }, "So richtest du es ein") : null,
    app.guide.length ? h("div", { class: "card" }, guide) : null,
    app.homepage ? h("a", { class: "btn btn-ghost btn-block", href: app.homepage, target: "_blank", rel: "noopener" }, icon("link"), "Webseite der App") : null,
    app.removable ? h("button", { class: "btn btn-ghost btn-block store-danger", type: "button", onclick: () => removeStoreApp(app) }, icon("trash"), "App entfernen") : null
  );
}

async function removeStoreApp(app) {
  if (!window.confirm(`„${app.name}“ wirklich entfernen? Ihre Einstellungen bleiben gespeichert.`)) return;
  try {
    await api.del(`/api/remote/apps/${app.id}`);
    toast(`${app.name} entfernt`);
    await restartAndWait("Wird neu gestartet …");
  } catch (err) {
    toast(err.message, true);
  }
}

// Dienst neu starten und warten, bis er wieder antwortet - dann neu laden
async function restartAndWait(message, alreadyRestarting = false) {
  if (!alreadyRestarting) await api.post("/api/remote/system/restart", {});
  toast(message || "Wird neu gestartet …");
  await new Promise((r) => setTimeout(r, 4000));
  for (let i = 0; i < 60; i += 1) {
    try {
      const resp = await fetch("/api/setup/status", { cache: "no-store" });
      if (resp.ok) {
        location.reload();
        return;
      }
    } catch (err) {
      // noch nicht wieder da
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  toast("Der Pi braucht ungewöhnlich lange – bitte später neu laden", true);
}

onTap($("store-install"), async () => {
  const input = $("store-install-url");
  const url = input.value.trim();
  if (!url) throw new Error("Bitte einen Link einfügen");
  const button = $("store-install");
  button.disabled = true;
  toast("Installiere … das kann eine Minute dauern");
  try {
    const result = await api.post("/api/remote/apps/install", { url });
    input.value = "";
    if (result.needs_restart) {
      await restartAndWait("Installiert – starte neu …");
    } else {
      await loadStore();
      toast("Installiert – jetzt einschalten");
      openStoreApp(result.id);
    }
  } finally {
    button.disabled = false;
  }
});

async function saveStoreApp(app, { onlyToggle = false } = {}) {
  const values = {};
  if (!onlyToggle) {
    document.querySelectorAll("#store-app-body [data-key]").forEach((el) => (values[el.dataset.key] = el.value));
  }
  try {
    const updated = await api.post(`/api/remote/apps/${app.id}`, { enabled: $("store-enabled").checked, values });
    store.apps = store.apps.map((a) => (a.id === app.id ? updated : a));
    installPluginApps(store.apps);
    applyEnabledApps(Object.fromEntries(store.apps.map((a) => [a.id, a.enabled])));
    toast(onlyToggle ? (updated.enabled ? `${app.name} ist an` : `${app.name} ist aus`) : "Gespeichert");
    if (!onlyToggle) renderStoreApp();
  } catch (err) {
    toast(err.message, true);
  }
}

async function testStoreApp(app) {
  const box = $("store-test");
  box.className = "store-test";
  box.textContent = "Teste …";
  try {
    const result = await api.post(`/api/remote/apps/${app.id}/test`, {});
    box.classList.add("ok");
    box.textContent = result.message;
  } catch (err) {
    box.classList.add("bad");
    box.textContent = err.message;
  }
}

// ---------- Einstellungen: Allgemein ----------

(function addGeneralSettings() {
  const section = $("view-settings");
  const header = section.querySelector(".view-header");
  const nameInput = h("input", { id: "sys-name", type: "text", maxlength: 40, autocomplete: "off" });
  const userInput = h("input", { id: "sys-user", type: "text", maxlength: 40, autocomplete: "off", autocapitalize: "words" });
  const cityInput = h("input", { id: "sys-city", type: "text", maxlength: 80, autocomplete: "off", autocapitalize: "words" });
  header.after(
    h("div", { class: "section-label" }, "Allgemein"),
    h(
      "div",
      { class: "card stack" },
      h("div", { class: "store-field" }, h("div", { class: "store-field-label" }, "Name des Systems"), h("label", { class: "field" }, nameInput)),
      h("div", { class: "store-field" }, h("div", { class: "store-field-label" }, "Dein Vorname"), h("label", { class: "field" }, userInput)),
      h("div", { class: "store-field" }, h("div", { class: "store-field-label" }, "Ort fürs Wetter"), h("label", { class: "field" }, cityInput)),
      h("button", { class: "btn btn-primary btn-block", type: "button", id: "sys-save" }, icon("check"), "Speichern")
    ),
    h(
      "div",
      { class: "group store-actions" },
      h("button", { class: "store-row", type: "button", id: "sys-tv" }, h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Fernseher & Ton testen"), h("span", { class: "store-row-sub", id: "sys-hw" }, "Erkennt den HDMI-Anschluss neu")), icon("forward-arrow")),
      h("button", { class: "store-row", type: "button", id: "sys-password" }, h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Passwort ändern"), h("span", { class: "store-row-sub" }, "Für die Fernbedienung auf allen Geräten")), icon("forward-arrow")),
      h("button", { class: "store-row", type: "button", id: "sys-setup" }, h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Einrichtung erneut starten")), icon("forward-arrow"))
    ),
    h("div", { class: "section-label hidden", id: "sys-tvs-label" }, "Fernseher im Haus"),
    h("div", { class: "group store-actions hidden", id: "sys-tvs" }),
    h("div", { class: "section-label" }, "System"),
    h(
      "div",
      { class: "group store-actions" },
      h("button", { class: "store-row", type: "button", id: "sys-update" }, h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Updates"), h("span", { class: "store-row-sub", id: "sys-update-sub" }, "Antippen zum Prüfen")), icon("forward-arrow")),
      h("button", { class: "store-row", type: "button", id: "sys-backup" }, h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Backup herunterladen"), h("span", { class: "store-row-sub" }, "Einstellungen, Apps, Listen – als eine Datei")), icon("forward-arrow")),
      h("label", { class: "store-row", id: "sys-restore" }, h("input", { type: "file", accept: ".zip,application/zip", id: "sys-restore-file", class: "store-file" }), h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Backup einspielen"), h("span", { class: "store-row-sub" }, "Überschreibt die Einstellungen, danach Neustart")), icon("forward-arrow")),
      h("button", { class: "store-row", type: "button", id: "sys-restart" }, h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, "Neu starten"), h("span", { class: "store-row-sub" }, "Fernseher und Radio laufen danach weiter")), icon("forward-arrow"))
    )
  );

  const previous = VIEW_HOOKS.settings;
  VIEW_HOOKS.settings = () => {
    previous();
    loadSystem();
  };

  onTap($("sys-save"), async () => {
    const profile = await api.post("/api/remote/system", { name: nameInput.value, user_name: userInput.value, city: cityInput.value });
    applyProfile(profile);
    toast("Gespeichert");
  });
  onTap($("sys-tv"), async () => {
    await api.post("/api/remote/system", { detect_hardware: true });
    await api.post("/api/remote/system/test-tv", {});
    toast("Fernseher geht an und sagt Hallo");
    loadSystem();
  });
  onTap($("sys-password"), async () => {
    const system = store.system || (await api.get("/api/remote/system"));
    const entered = window.prompt("Neues Passwort (mind. 8 Zeichen):", system.password_suggestion);
    if (!entered) return;
    await api.post("/api/remote/system", { password: entered });
    setSecret(entered.trim());
    toast("Passwort geändert – auf anderen Geräten neu eingeben");
  });
  onTap($("sys-setup"), async () => openSetup());

  onTap($("sys-restart"), async () => {
    if (!window.confirm("Den Dienst jetzt neu starten?")) return;
    await restartAndWait();
  });

  onTap($("sys-update"), async () => {
    const sub = $("sys-update-sub");
    sub.textContent = "Prüfe …";
    const info = await api.get("/api/remote/system/update");
    if (!info.possible) {
      sub.textContent = info.reason;
      return;
    }
    if (!info.available) {
      sub.textContent = `Aktuell (${info.version})`;
      return;
    }
    sub.textContent = `${info.count} ${info.count === 1 ? "Neuerung" : "Neuerungen"} verfügbar`;
    const list = info.changes.map((c) => `• ${c}`).join("\n");
    if (!window.confirm(`Jetzt aktualisieren?\n\n${list}\n\nDer Pi startet danach kurz neu.`)) return;
    await api.post("/api/remote/system/update", {});
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      let state;
      try {
        state = (await api.get("/api/remote/system/update/state")).state;
      } catch (err) {
        await restartAndWait("Startet neu …", true);
        return;
      }
      sub.textContent = state.error || state.step;
      if (state.error) throw new Error(state.error);
      if (state.done) {
        await restartAndWait("Aktualisiert – startet neu …", true);
        return;
      }
    }
  });

  onTap($("sys-backup"), async () => {
    const secrets = window.confirm("Zugangsdaten (Passwörter, API-Schlüssel) mit ins Backup?\n\nOK = ja (Datei gut aufbewahren!), Abbrechen = ohne.");
    const headers = {};
    if (getSecret()) headers["X-Remote-Secret"] = getSecret();
    const resp = await fetch(`/api/remote/system/backup?secrets=${secrets}`, { headers });
    if (!resp.ok) throw new Error("Backup fehlgeschlagen");
    const blob = await resp.blob();
    const name = (resp.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
    const link = h("a", { href: URL.createObjectURL(blob), download: name ? name[1] : "rpitv-backup.zip" });
    document.body.append(link);
    link.click();
    setTimeout(() => {
      URL.revokeObjectURL(link.href);
      link.remove();
    }, 1000);
  });

  $("sys-restore-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (!window.confirm(`„${file.name}“ einspielen? Die jetzigen Einstellungen werden überschrieben.`)) return;
    try {
      const headers = { "Content-Type": "application/zip" };
      if (getSecret()) headers["X-Remote-Secret"] = getSecret();
      const resp = await fetch("/api/remote/system/backup", { method: "POST", headers, body: file });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || "Einspielen fehlgeschlagen");
      await restartAndWait(`${data.files} Dateien eingespielt – startet neu …`, true);
    } catch (err) {
      toast(err.message, true);
    }
  });
})();

function applyProfile(profile) {
  applyName(profile.name);
  if (profile.user_name !== undefined) {
    userName = profile.user_name || userName;
    updateClock();
  }
}

// Mehrere Fernseher an einem Pi (app/add_tv.py): jeder hat seine eigene
// Fernbedienung auf einem eigenen Port - hier springt man hinueber
function renderTvs(tvs) {
  const show = tvs.length > 1;
  $("sys-tvs-label").classList.toggle("hidden", !show);
  $("sys-tvs").classList.toggle("hidden", !show);
  if (!show) return;
  $("sys-tvs").replaceChildren(
    ...tvs.map((tv) =>
      h(
        tv.current ? "div" : "a",
        { class: "store-row", href: tv.current ? null : `${location.protocol}//${location.hostname}:${tv.port}/remote.html` },
        h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, tv.name), h("span", { class: "store-row-sub" }, tv.current ? "Diese Fernbedienung" : `Fernbedienung öffnen (Port ${tv.port})`)),
        tv.current ? icon("check") : icon("forward-arrow")
      )
    )
  );
}

async function loadSystem() {
  try {
    const system = await api.get("/api/remote/system");
    store.system = system;
    $("sys-name").value = system.name || "";
    $("sys-user").value = system.user_name || "";
    $("sys-city").value = system.city || "";
    renderTvs(system.tvs || []);
    $("sys-hw").textContent = system.hardware.connected
      ? `Fernseher an HDMI ${system.hardware.port} · Ton über HDMI ${system.alsa_device.includes("vc4hdmi1") ? 2 : 1}`
      : "Kein Fernseher am HDMI erkannt";
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- Einrichtungsassistent (erster Start) ----------

const SETUP_DEFAULT_APPS = ["youtube", "twitch", "vinyl", "comics"];
const setup = { step: 0, apps: {}, password: "" };

const setupEl = h("div", { class: "setup hidden", id: "setup" }, h("div", { class: "setup-card", id: "setup-card" }));
document.body.append(setupEl);

const SETUP_STEPS = [
  {
    title: "Willkommen",
    render: () => [
      h("p", { class: "setup-text" }, "In ein paar Schritten ist dein Fernseher eingerichtet. Alles lässt sich später in den Einstellungen und im App Store ändern."),
      setupField("Wie soll dein System heißen?", "setup-name", setup.name || "RPi TV"),
      setupField("Dein Vorname (für die Begrüßung)", "setup-user", setup.user || ""),
      setupField("Ort fürs Wetter", "setup-city", setup.city || ""),
    ],
    next: async () => {
      setup.name = $("setup-name").value.trim() || "RPi TV";
      setup.user = $("setup-user").value.trim();
      setup.city = $("setup-city").value.trim();
      const profile = await api.post("/api/remote/system", { name: setup.name, user_name: setup.user, city: setup.city || undefined });
      applyProfile(profile);
    },
  },
  {
    title: "Fernseher",
    render: () => {
      const status = h("div", { class: "setup-status", id: "setup-hw" }, "Suche den Fernseher …");
      api
        .post("/api/remote/system", { detect_hardware: true })
        .then(() => api.get("/api/remote/system"))
        .then((system) => {
          status.textContent = system.hardware.connected
            ? `Gefunden: Fernseher an HDMI ${system.hardware.port}.`
            : "Kein Fernseher erkannt. Ist er per HDMI angeschlossen? Du kannst trotzdem weitermachen.";
          status.classList.toggle("ok", system.hardware.connected);
        })
        .catch((err) => (status.textContent = err.message));
      return [
        h("p", { class: "setup-text" }, "Der Pi schaltet den Fernseher über HDMI-CEC ein und aus. Mach einen Test: Der Fernseher sollte angehen und dich begrüßen."),
        status,
        h("button", {
          class: "btn btn-ghost btn-block",
          type: "button",
          onclick: async () => {
            try {
              await api.post("/api/remote/system/test-tv", {});
              toast("Fernseher geht an …");
            } catch (err) {
              toast(err.message, true);
            }
          },
        }, icon("tv"), "Fernseher testen"),
        h("p", { class: "hint" }, "Geht er nicht an? Am Fernseher HDMI-CEC einschalten (heißt je nach Marke Anynet+, Bravia Sync, SimpLink oder EasyLink)."),
      ];
    },
  },
  {
    title: "Deine Apps",
    render: () => {
      if (!Object.keys(setup.apps).length) {
        for (const app of store.apps) setup.apps[app.id] = app.enabled || SETUP_DEFAULT_APPS.includes(app.id);
      }
      return [
        h("p", { class: "setup-text" }, "Was möchtest du nutzen? Zugangsdaten trägst du danach im App Store ein – dort steht zu jeder App eine Anleitung."),
        h(
          "div",
          { class: "group" },
          ...store.apps.map((app) => {
            const box = h("input", { type: "checkbox" });
            box.checked = !!setup.apps[app.id];
            box.addEventListener("change", () => (setup.apps[app.id] = box.checked));
            return h(
              "div",
              { class: "group-row" },
              h("span", { class: "row-label" }, appBadge(app), h("span", null, app.name)),
              h("label", { class: "switch" }, box, h("span", { class: "switch-slider" }))
            );
          })
        ),
      ];
    },
    next: async () => {
      await api.post("/api/remote/system", { apps: setup.apps });
    },
  },
  {
    title: "Passwort",
    render: () => {
      setup.password = setup.password || (store.system && store.system.password_suggestion) || "";
      return [
        h("p", { class: "setup-text" }, "Damit nur du deinen Fernseher steuerst, bekommt die Fernbedienung ein Passwort. Auf jedem neuen Handy gibst du es einmal ein."),
        setupField("Passwort (mind. 8 Zeichen)", "setup-password", setup.password),
        h("p", { class: "hint" }, "Am besten jetzt notieren oder im Passwort-Manager speichern."),
      ];
    },
    next: async () => {
      const password = $("setup-password").value.trim();
      if (password.length < 8) throw new Error("Das Passwort braucht mindestens 8 Zeichen");
      await api.post("/api/remote/system", { password });
      setSecret(password);
      await api.post("/api/remote/system", { finish: true });
    },
    nextLabel: "Fertig",
  },
];

function setupField(label, id, value) {
  const input = h("input", { id, type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
  input.value = value;
  return h("div", { class: "store-field" }, h("div", { class: "store-field-label" }, label), h("label", { class: "field" }, input));
}

function renderSetup() {
  const step = SETUP_STEPS[setup.step];
  const next = h("button", { class: "btn btn-primary btn-block", type: "button" }, step.nextLabel || "Weiter");
  onTap(next, async () => {
    next.disabled = true;
    try {
      if (step.next) await step.next();
    } finally {
      next.disabled = false;
    }
    if (setup.step < SETUP_STEPS.length - 1) {
      setup.step += 1;
      renderSetup();
    } else {
      closeSetup();
      toast("Alles eingerichtet");
    }
  });
  $("setup-card").replaceChildren(
    h("div", { class: "setup-dots" }, ...SETUP_STEPS.map((_, i) => h("span", { class: i === setup.step ? "on" : i < setup.step ? "done" : "" }))),
    h("h1", { class: "setup-title" }, step.title),
    ...step.render(),
    h(
      "div",
      { class: "setup-nav" },
      setup.step > 0
        ? h("button", { class: "btn btn-ghost", type: "button", onclick: () => { setup.step -= 1; renderSetup(); } }, "Zurück")
        : null,
      next
    )
  );
  setupEl.scrollTop = 0;
}

async function openSetup() {
  try {
    const [apps, system] = await Promise.all([api.get("/api/remote/apps"), api.get("/api/remote/system")]);
    store.apps = apps.apps;
    store.system = system;
    setup.name = system.name;
    setup.user = system.user_name;
    setup.city = system.city;
  } catch (err) {
    toast(err.message, true);
    return;
  }
  setup.step = 0;
  setup.apps = {};
  setupEl.classList.remove("hidden");
  document.body.classList.add("setup-open");
  renderSetup();
}

function closeSetup() {
  setupEl.classList.add("hidden");
  document.body.classList.remove("setup-open");
  refreshBranding();
}

// ---------- Eigene Apps (Ordner apps/<id>/, Anleitung: apps/README.md) ----------
// Jede App mit remote.html/remote.js bekommt eine Kachel und eine Ansicht.
// In remote.js:   const app = RPiTV.app();
//   app.el                    Inhalt der Ansicht (remote.html steckt schon drin)
//   app.onOpen(fn)            fn() bei jedem Oeffnen der App
//   app.api.get("pfad")       GET /api/apps/<id>/pfad (mit Passwort), .post/.del
//   app.tv.open("tv.html")    Seite der App im Vollbild auf dem Fernseher
//   app.tv.close()            ... und wieder zu
//   app.toast("Text")         kurze Meldung (zweites Argument true = Fehler)
//   app.file("bild.png")      Adresse einer Datei aus dem App-Ordner
//   app.h(tag, attrs, ...kinder), app.icon(name)   kleine DOM-Helfer

const plugin = { handles: {}, loaded: {} };

function pluginHandle(id) {
  if (plugin.handles[id]) return plugin.handles[id];
  const base = `/api/apps/${id}/`;
  const clean = (path) => base + String(path || "").replace(/^\/+/, "");
  const handle = {
    id,
    el: document.getElementById(`app-body-${id}`),
    hooks: [],
    onOpen(fn) {
      handle.hooks.push(fn);
    },
    api: {
      get: (path) => api.get(clean(path)),
      post: (path, body) => api.post(clean(path), body),
      del: (path) => api.del(clean(path)),
    },
    tv: {
      open: (page = "tv.html") => api.post(`/api/remote/apps/${id}/tv`, { action: "open", page }),
      close: () => api.post(`/api/remote/apps/${id}/tv`, { action: "close" }),
    },
    toast,
    file: (name) => `/apps/${id}/${name}`,
    h,
    icon,
  };
  plugin.handles[id] = handle;
  return handle;
}

window.RPiTV = {
  app(id) {
    const own = id || (document.currentScript && document.currentScript.dataset.app);
    if (!own) throw new Error("RPiTV.app(): App unbekannt - nur direkt in remote.js aufrufen");
    return pluginHandle(own);
  },
};

function installPluginApps(apps) {
  const grid = document.querySelector("#view-home .app-grid");
  const before = document.getElementById("tile-comics");
  for (const app of apps) {
    if (!app.plugin || !app.view || app.error || document.getElementById(`view-app-${app.id}`)) continue;
    if (app.icon_svg && !document.getElementById(`i-${app.icon}`)) {
      document.querySelector("svg.sprite").insertAdjacentHTML("beforeend", `<symbol id="i-${app.icon}" viewBox="0 0 24 24">${app.icon_svg}</symbol>`);
    }
    grid.insertBefore(
      h(
        "button",
        { class: "app-tile hidden", type: "button", "data-plugin": app.id, style: `--app-rgb: ${app.color}`, onclick: () => openView(`app-${app.id}`) },
        h("span", { class: "app-icon" }, icon(app.icon)),
        h("span", { class: "app-name" }, app.name)
      ),
      before
    );
    views.append(
      h(
        "section",
        { class: "view hidden plugin-view", id: `view-app-${app.id}`, style: `--tint: ${app.color}` },
        h("div", { class: "view-header" }, h("button", { class: "icon-btn", "aria-label": "Zurück", onclick: () => goHome() }, icon("back")), h("h1", null, app.name)),
        h("div", { class: "app-body", id: `app-body-${app.id}` })
      )
    );
    VIEW_HOOKS[`app-${app.id}`] = () => openPluginApp(app);
  }
}

function loadScript(src, id) {
  return new Promise((resolve, reject) => {
    const script = h("script", { src, "data-app": id });
    script.onload = resolve;
    script.onerror = () => reject(new Error(`${src} ließ sich nicht laden`));
    document.body.append(script);
  });
}

async function openPluginApp(app) {
  const handle = pluginHandle(app.id);
  try {
    if (!plugin.loaded[app.id]) {
      plugin.loaded[app.id] = true;
      if (app.files.includes("remote.css")) document.head.append(h("link", { rel: "stylesheet", href: `/apps/${app.id}/remote.css` }));
      if (app.files.includes("remote.html")) handle.el.innerHTML = await fetch(`/apps/${app.id}/remote.html`).then((r) => r.text());
      if (app.files.includes("remote.js")) await loadScript(`/apps/${app.id}/remote.js`, app.id);
    }
    for (const fn of handle.hooks) await fn();
  } catch (err) {
    toast(err.message || "Die App hat einen Fehler", true);
  }
}

// ---------- Start ----------

async function refreshBranding() {
  try {
    const status = await fetch("/api/setup/status").then((r) => r.json());
    applyName(status.name);
    if (!status.setup_done) {
      openSetup();
      return;
    }
    const data = await api.get("/api/remote/apps");
    store.apps = data.apps;
    installPluginApps(data.apps);
    applyEnabledApps(Object.fromEntries(data.apps.map((a) => [a.id, a.enabled])));
  } catch (err) {
    // offline - beim naechsten Oeffnen erneut
  }
}

refreshBranding();
