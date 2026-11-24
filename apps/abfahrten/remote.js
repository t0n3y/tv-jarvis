"use strict";

(() => {
  const app = RPiTV.app();
  const { h } = app;
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);
  let timer = null;
  let searchTimer = null;

  function minutesUntil(iso) {
    return Math.round((Date.parse(iso) - Date.now()) / 60000);
  }

  function render(data) {
    ref("stop-name").textContent = data.stop ? data.stop.name : "Noch keine gewählt";
    ref("list").classList.toggle("hidden", !data.stop);
    if (!data.stop) {
      ref("hint").textContent = "Suche oben deine Haltestelle.";
      return;
    }
    ref("hint").textContent = "Grau = mit deinem Fußweg nicht mehr erreichbar. Aktualisiert sich jede Minute.";
    if (!data.departures.length) {
      ref("list").replaceChildren(h("div", { class: "group-empty" }, "Gerade keine Abfahrten."));
      return;
    }
    ref("list").replaceChildren(
      ...data.departures.map((dep) => {
        const mins = minutesUntil(dep.when);
        const right = dep.cancelled ? "fällt aus" : mins <= 0 ? "jetzt" : `${mins} min`;
        const sub = [dep.mode, dep.track ? `Gleis ${dep.track}` : "", dep.delay > 0 ? `+${dep.delay} min` : dep.realtime ? "pünktlich" : ""].filter(Boolean).join(" · ");
        return h(
          "div",
          { class: `ab-row${dep.reachable ? "" : " gone"}${dep.cancelled ? " cancelled" : ""}` },
          h("span", { class: "ab-line" }, dep.line || "–"),
          h("span", { class: "ab-main" }, h("span", { class: "ab-dir" }, dep.direction), h("span", { class: "ab-sub" }, `${dep.time}${sub ? ` · ${sub}` : ""}`)),
          h("span", { class: `ab-in${dep.delay > 0 ? " late" : ""}` }, right)
        );
      })
    );
  }

  async function load() {
    clearTimeout(timer);
    try {
      render(await app.api.get("departures"));
    } catch (err) {
      ref("hint").textContent = err.message;
    }
    if (document.getElementById("view-app-abfahrten") && !document.getElementById("view-app-abfahrten").classList.contains("hidden")) {
      timer = setTimeout(load, 60000);
    }
  }

  async function search() {
    const q = ref("query").value.trim();
    const box = ref("results");
    if (q.length < 2) {
      box.classList.add("hidden");
      return;
    }
    try {
      const { stops } = await app.api.get(`search?q=${encodeURIComponent(q)}`);
      box.classList.toggle("hidden", false);
      box.replaceChildren(
        ...(stops.length
          ? stops.map((stop) =>
              h(
                "button",
                {
                  class: "store-row",
                  type: "button",
                  onclick: async () => {
                    await app.api.post("stop", stop);
                    ref("query").value = "";
                    box.classList.add("hidden");
                    app.toast(`${stop.name} gewählt`);
                    load();
                  },
                },
                h("span", { class: "store-row-main" }, h("span", { class: "store-row-name" }, stop.name), stop.area ? h("span", { class: "store-row-sub" }, stop.area) : null),
                app.icon("check")
              )
            )
          : [h("div", { class: "group-empty" }, "Nichts gefunden.")])
      );
    } catch (err) {
      app.toast(err.message, true);
    }
  }

  ref("query").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(search, 400);
  });
  app.onOpen(load);
})();
