"use strict";

(() => {
  const app = RPiTV.app();
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);
  const PRESETS = [15, 30, 45, 60, 90, 120];
  let endsAt = 0;
  let tick = null;

  function render() {
    const active = endsAt > Date.now();
    const left = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
    ref("time").textContent = active ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "Aus";
    ref("sub").textContent = active
      ? `Um ${new Date(endsAt).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} geht alles aus`
      : "Wähle, wann alles ausgehen soll.";
    ref("cancel").classList.toggle("hidden", !active);
    app.el.querySelectorAll(".st-grid .btn").forEach((btn) => btn.classList.toggle("btn-primary", false));
  }

  function apply(state) {
    endsAt = state.active ? Date.now() + state.remaining * 1000 : 0;
    clearInterval(tick);
    if (state.active) tick = setInterval(render, 1000);
    render();
  }

  ref("presets").replaceChildren(
    ...PRESETS.map((minutes) =>
      app.h(
        "button",
        {
          class: "btn btn-ghost",
          type: "button",
          onclick: async () => {
            try {
              apply(await app.api.post("start", { minutes }));
              app.toast(`Alles aus in ${minutes} Minuten`);
            } catch (err) {
              app.toast(err.message, true);
            }
          },
        },
        minutes < 60 ? `${minutes} min` : `${minutes / 60} Std.`
      )
    )
  );
  ref("cancel").addEventListener("click", async () => {
    apply(await app.api.post("cancel", {}));
    app.toast("Timer abgebrochen");
  });
  app.onOpen(async () => apply(await app.api.get("state")));
})();
