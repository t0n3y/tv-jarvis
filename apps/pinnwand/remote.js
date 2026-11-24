"use strict";

// Laeuft in der Fernbedienung. RPiTV.app() liefert alles, was die App braucht
// (siehe apps/README.md). Alles in eine Funktion packen, damit sich Namen
// nicht mit anderen Apps ueberschneiden.
(() => {
  const app = RPiTV.app();
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);

  async function refresh() {
    const data = await app.api.get("message");
    ref("last").textContent = data.text ? `Zuletzt: „${data.text}“` : "";
  }

  ref("show").addEventListener("click", async () => {
    try {
      await app.api.post("message", { text: ref("text").value });
      await app.tv.open("tv.html");
      app.toast("Läuft auf dem Fernseher");
      refresh();
    } catch (err) {
      app.toast(err.message, true);
    }
  });

  ref("close").addEventListener("click", () => app.tv.close().catch((err) => app.toast(err.message, true)));

  // Bei jedem Oeffnen der App
  app.onOpen(refresh);
})();
