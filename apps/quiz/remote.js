"use strict";

(() => {
  const app = RPiTV.app();
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);
  const PHASES = { lobby: "Warten auf Mitspieler", question: "Frage läuft", reveal: "Auflösung", final: "Endstand" };
  let rounds = 10;
  let timer = null;

  function visible() {
    return !document.getElementById("view-app-quiz").classList.contains("hidden");
  }

  function render(state) {
    const running = state.phase && state.phase !== "none";
    ref("setup").classList.toggle("hidden", running);
    ref("running").classList.toggle("hidden", !running);
    if (!running) return;
    const q = state.question;
    ref("phase").textContent = q ? `${PHASES[state.phase]} · Frage ${q.number}/${q.total}` : PHASES[state.phase];
    ref("code").textContent = `Code ${state.code}`;
    ref("players").replaceChildren(
      ...(state.ranking.length
        ? state.ranking.map((p) => app.h("span", { class: "qz-chip" }, state.phase === "lobby" ? p.name : `${p.name} · ${p.score}`))
        : [app.h("span", { class: "qz-empty" }, "Noch niemand da – QR-Code auf dem Fernseher scannen")])
    );
    ref("start").classList.toggle("hidden", state.phase !== "lobby");
    ref("start").disabled = !state.ranking.length;
    ref("skip").classList.toggle("hidden", !["question", "reveal"].includes(state.phase));
  }

  async function poll() {
    clearTimeout(timer);
    try {
      render(await app.api.get("state"));
    } catch (err) {
      // naechster Versuch
    }
    if (visible()) timer = setTimeout(poll, 1000);
  }

  async function act(path, body = {}) {
    try {
      render(await app.api.post(path, body));
    } catch (err) {
      app.toast(err.message, true);
    }
    poll();
  }

  ref("rounds").querySelectorAll(".seg-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      rounds = Number(btn.dataset.value);
      ref("rounds").querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
    })
  );
  ref("new").addEventListener("click", () => act("new", { rounds, origin: location.origin }));
  ref("start").addEventListener("click", () => act("start"));
  ref("skip").addEventListener("click", () => act("skip"));
  ref("end").addEventListener("click", async () => {
    if (!window.confirm("Spiel beenden?")) return;
    await act("end");
  });
  app.onOpen(poll);
})();
