"use strict";

(() => {
  const app = RPiTV.app();
  const { h } = app;
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);
  let poll = null;

  function render(items) {
    const open = items.filter((item) => !item.done);
    const done = items.filter((item) => item.done);
    ref("clear").classList.toggle("hidden", !done.length);
    if (!items.length) {
      ref("list").replaceChildren(h("div", { class: "group-empty" }, "Die Liste ist leer."));
      return;
    }
    ref("list").replaceChildren(
      ...[...open, ...done].map((item) =>
        h(
          "div",
          { class: `ek-row${item.done ? " done" : ""}` },
          h(
            "button",
            { class: "ek-check", type: "button", "aria-label": item.done ? "Wieder offen" : "Abhaken", onclick: () => change(`items/${item.id}/toggle`) },
            item.done ? app.icon("check") : null
          ),
          h("span", { class: "ek-text", onclick: () => change(`items/${item.id}/toggle`) }, item.text),
          h("button", { class: "ek-del", type: "button", "aria-label": "Löschen", onclick: () => remove(item.id) }, app.icon("close"))
        )
      )
    );
  }

  async function change(path) {
    try {
      render((await app.api.post(path, {})).items);
    } catch (err) {
      app.toast(err.message, true);
    }
  }

  async function remove(id) {
    try {
      render((await app.api.del(`items/${id}`)).items);
    } catch (err) {
      app.toast(err.message, true);
    }
  }

  async function load() {
    clearTimeout(poll);
    try {
      render((await app.api.get("items")).items);
    } catch (err) {
      app.toast(err.message, true);
    }
    // Andere im Haushalt aendern die Liste mit - waehrend sie offen ist, nachladen
    if (!document.getElementById("view-app-einkaufsliste").classList.contains("hidden")) poll = setTimeout(load, 5000);
  }

  ref("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = ref("text").value.trim();
    if (!text) return;
    try {
      render((await app.api.post("items", { text })).items);
      ref("text").value = "";
    } catch (err) {
      app.toast(err.message, true);
    }
  });
  ref("clear").addEventListener("click", () => change("clear-done"));
  app.onOpen(load);
})();
