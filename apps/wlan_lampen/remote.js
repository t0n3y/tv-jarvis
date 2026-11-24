"use strict";

(() => {
  const app = RPiTV.app();
  const { h } = app;
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);
  const SCENE_LABELS = { hell: "Hell", gemuetlich: "Gemütlich", kino: "Kino", konzentration: "Konzentration", aus: "Aus" };
  const COLORS = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#007aff", "#5856d6", "#af52de", "#ff2d55"];
  let devices = [];
  let status = {};
  let sendTimer = null;

  async function send(body, quiet = false) {
    try {
      const result = await app.api.post("set", body);
      const failed = result.results.filter((r) => !r.ok).length;
      if (failed && !quiet) app.toast(`${failed} Lampe(n) nicht erreichbar`, true);
      refreshStatus();
    } catch (err) {
      app.toast(err.message, true);
    }
  }

  // Schieberegler: nicht bei jedem Pixel senden
  function sendSoon(body) {
    clearTimeout(sendTimer);
    sendTimer = setTimeout(() => send(body, true), 250);
  }

  function renderList() {
    if (!devices.length) {
      ref("list").replaceChildren(h("div", { class: "group-empty" }, "Noch keine Lampen gefunden."));
      return;
    }
    ref("list").replaceChildren(
      ...devices.map((device) => {
        const st = status[device.id];
        const sub = !device.found ? "nicht im WLAN gefunden" : st ? (st.online ? (st.on ? "an" : "aus") : "nicht erreichbar") : device.ip;
        return h(
          "button",
          { class: `store-row wl-row${st && st.on ? " on" : ""}`, type: "button", onclick: () => send({ ids: [device.id], on: !(st && st.on) }) },
          h("span", { class: "wl-dot" }),
          h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, device.name), h("span", { class: "store-row-sub" }, sub))
        );
      })
    );
  }

  async function refreshStatus() {
    if (!devices.length) return;
    try {
      const data = await app.api.get("status");
      status = Object.fromEntries(data.status.map((s) => [s.id, s]));
      renderList();
    } catch (err) {
      // Status ist nur Anzeige
    }
  }

  async function load() {
    const data = await app.api.get("devices");
    devices = data.devices;
    ref("scenes").replaceChildren(
      ...data.scenes.map((scene) => h("button", { class: "btn btn-ghost", type: "button", onclick: () => send({ scene }) }, SCENE_LABELS[scene] || scene))
    );
    renderList();
    refreshStatus();
  }

  ref("colors").replaceChildren(
    ...COLORS.map((color) =>
      h("button", { class: "wl-color", type: "button", style: `background:${color}`, "aria-label": color, onclick: () => send({ on: true, color, brightness: Number(ref("brightness").value) }) })
    )
  );
  ref("all-on").addEventListener("click", () => send({ on: true }));
  ref("all-off").addEventListener("click", () => send({ on: false }));
  ref("brightness").addEventListener("input", () => sendSoon({ on: true, brightness: Number(ref("brightness").value) }));
  ref("white").addEventListener("input", () => sendSoon({ on: true, white: Number(ref("white").value), brightness: Number(ref("brightness").value) }));
  ref("discover").addEventListener("click", async () => {
    const button = ref("discover");
    button.disabled = true;
    button.textContent = "Suche … (ca. 20 Sekunden)";
    try {
      const data = await app.api.post("discover", {});
      devices = data.devices;
      app.toast(`${devices.length} Lampen gefunden`);
      renderList();
      refreshStatus();
    } catch (err) {
      app.toast(err.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Lampen suchen";
    }
  });
  app.onOpen(load);
})();
