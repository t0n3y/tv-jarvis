"use strict";

(() => {
  const app = RPiTV.app();
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);

  async function load() {
    const info = await app.api.get("info");
    if (!info.folder) ref("status").textContent = "Noch kein Foto-Ordner eingetragen";
    else if (!info.folder_ok) ref("status").textContent = `${info.folder} nicht gefunden`;
    else ref("status").textContent = `${info.count} Fotos · ${info.seconds} s pro Foto${info.showing ? " · läuft" : ""}`;
    ref("start").disabled = !info.count;
    ref("hint").textContent = info.folder ? "Den Ordner, die Zeit bis zum Selbststart und die Uhrzeiten änderst du im App Store." : "Trage im App Store (Bilderrahmen → Einstellungen) den Ordner mit deinen Fotos ein.";
  }

  ref("start").addEventListener("click", async () => {
    try {
      await app.api.post("start", {});
      app.toast("Diashow läuft");
      load();
    } catch (err) {
      app.toast(err.message, true);
    }
  });
  ref("stop").addEventListener("click", async () => {
    await app.api.post("stop", {}).catch((err) => app.toast(err.message, true));
    load();
  });
  app.onOpen(load);
})();
