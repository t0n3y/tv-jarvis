"use strict";

(() => {
  const app = RPiTV.app();
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);
  let busy = false;

  async function say(text) {
    if (busy || !text.trim()) return;
    busy = true;
    ref("say").disabled = true;
    app.toast("Wird durchgesagt …");
    try {
      await app.api.post("say", { text, power_on: ref("power").checked });
      ref("text").value = "";
      app.toast("Durchgesagt");
      load();
    } catch (err) {
      app.toast(err.message, true);
    } finally {
      busy = false;
      ref("say").disabled = false;
    }
  }

  async function load() {
    const info = await app.api.get("info");
    ref("presets").replaceChildren(
      ...info.presets.map((text) => app.h("button", { class: "btn btn-ghost", type: "button", onclick: () => say(text) }, text))
    );
    ref("history-label").classList.toggle("hidden", !info.history.length);
    ref("history").classList.toggle("hidden", !info.history.length);
    ref("history").replaceChildren(
      ...info.history.map((entry) =>
        app.h(
          "button",
          { class: "store-row", type: "button", onclick: () => say(entry.text) },
          app.h("span", { class: "store-row-main" }, app.h("span", { class: "store-row-name" }, entry.text), app.h("span", { class: "store-row-sub" }, `${entry.at} · nochmal antippen`)),
          app.icon("replay")
        )
      )
    );
  }

  ref("say").addEventListener("click", () => say(ref("text").value));
  ref("text").addEventListener("keydown", (event) => {
    if (event.key === "Enter") say(ref("text").value);
  });
  app.onOpen(load);
})();
