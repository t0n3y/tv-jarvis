"use strict";

/* ============================================================
   Fernbedienung: Videos von Webseiten auf die Jellyfin-Platte laden.
   Der Pi sucht und laedt (media_grab.py); hier nur Link rein, Video
   waehlen, Film/Serie angeben. Haengt am Upload-Sheet aus remote.js
   (upload, openUpload, loadUploadTargets, formatBytes, formatEta ...).
   ============================================================ */

const GRAB_POLL_ACTIVE_MS = 1500;
const GRAB_POLL_IDLE_MS = 8000;
const GRAB_KIND_LABEL = { hls: "Stream", dash: "Stream", datei: "Datei", seite: "Video" };

const grab = { jobs: [], forms: {}, timer: null };

function grabForm(job) {
  if (!grab.forms[job.id]) {
    const guess = guessFromName(`${job.title || ""}.mp4`);
    grab.forms[job.id] = {
      candidate: 0,
      kind: guess.kind,
      title: guess.title,
      year: guess.year,
      series: guess.series,
      season: guess.season || 1,
      episode: 1,
    };
  }
  return grab.forms[job.id];
}

function candidateLabel(c) {
  const parts = [GRAB_KIND_LABEL[c.kind] || "Video"];
  if (c.height) parts.push(`${c.height}p`);
  try {
    parts.push(new URL(c.url).hostname.replace(/^www\./, ""));
  } catch (err) {
    // egal
  }
  return parts.join(" · ");
}

async function startGrab(job) {
  const form = grabForm(job);
  const target = uploadTarget(form.kind);
  if (!target) {
    toast("Jellyfin-Bibliothek nicht gefunden", true);
    return;
  }
  try {
    const data = await api.post(`/api/remote/jellyfin/grab/${job.id}`, { ...form, target: target.id });
    grab.jobs = data.jobs;
    renderGrab();
    pollGrab();
  } catch (err) {
    toast(err.message, true);
  }
}

async function removeGrab(job) {
  try {
    const data = await api.del(`/api/remote/jellyfin/grab/${job.id}`);
    grab.jobs = data.jobs;
    delete grab.forms[job.id];
    renderGrab();
  } catch (err) {
    toast(err.message, true);
  }
}

function grabJobView(job) {
  let host = job.url;
  try {
    host = new URL(job.url).hostname.replace(/^www\./, "");
  } catch (err) {
    // egal
  }
  const children = [
    h(
      "div",
      { class: "up-item-head" },
      h("div", { class: "up-item-name" }, job.title || host),
      h("button", { class: "up-remove", type: "button", "aria-label": job.status === "laedt" ? "Abbrechen" : "Entfernen", onclick: () => removeGrab(job) }, icon("close"))
    ),
  ];

  if (job.status === "suche") {
    children.push(h("div", { class: "up-bar searching" }, h("span")));
    children.push(h("div", { class: "up-status" }, h("span", null, "Video wird gesucht … (bis zu einer Minute)"), h("span", null, host)));
  }

  if ((job.status === "auswahl" || job.status === "fehler") && job.candidates && job.candidates.length) {
    const form = grabForm(job);
    if (job.candidates.length > 1) {
      children.push(
        h(
          "div",
          { class: "grab-cands" },
          ...job.candidates.map((c, i) =>
            h(
              "button",
              {
                class: form.candidate === i ? "grab-cand active" : "grab-cand",
                type: "button",
                onclick: () => {
                  form.candidate = i;
                  renderGrab();
                },
              },
              candidateLabel(c),
              c.size && c.kind === "datei" ? h("span", null, formatBytes(c.size)) : null
            )
          )
        )
      );
    }
    children.push(
      h(
        "div",
        { class: "up-kind" },
        ...[
          ["movies", "Film"],
          ["tvshows", "Serie"],
        ].map(([kind, label]) =>
          h(
            "button",
            {
              type: "button",
              class: form.kind === kind ? "active" : "",
              onclick: () => {
                form.kind = kind;
                renderGrab();
              },
            },
            label
          )
        )
      )
    );
    children.push(
      form.kind === "movies"
        ? h("div", { class: "up-fields" }, uploadField(form, "title", "Titel"), uploadField(form, "year", "Jahr", { inputmode: "numeric", maxlength: "4" }))
        : h(
            "div",
            { class: "up-fields three" },
            uploadField(form, "series", "Serie"),
            uploadField(form, "season", "Staffel", { inputmode: "numeric", maxlength: "2" }),
            uploadField(form, "episode", "Folge", { inputmode: "numeric", maxlength: "3" })
          )
    );
    children.push(h("button", { class: "btn btn-primary btn-block", type: "button", onclick: () => startGrab(job) }, icon("upload"), "In Jellyfin laden"));
  }

  if (job.status === "wartet") {
    children.push(h("div", { class: "up-status" }, h("span", null, "Wartet auf den vorherigen Download …"), h("span")));
  }

  if (job.status === "laedt") {
    const p = job.progress || {};
    const percent = p.percent || 0;
    children.push(h("div", { class: "up-bar" }, h("span", { style: `width:${percent.toFixed(1)}%` })));
    const right = [p.speed ? `${formatBytes(p.speed)}/s` : "", formatEta(p.eta)].filter(Boolean).join(" · ");
    children.push(h("div", { class: "up-status" }, h("span", null, `${Math.floor(percent)} %${p.total ? ` von ${formatBytes(p.total)}` : ""}`), h("span", null, right)));
  }

  if (job.status === "fertig" && job.result) {
    children.push(h("div", { class: "up-status" }, h("span", null, `✓ In Jellyfin: ${job.result.name}`), h("span")));
    if (job.result.warning) children.push(h("div", { class: "up-warning" }, job.result.warning));
  }

  if (job.status === "fehler" && job.error) {
    children.push(h("div", { class: "up-status" }, h("span", null, job.error), h("span")));
  }

  const css = { fertig: "done", fehler: "error" }[job.status] || "";
  return h("div", { class: `up-item ${css}` }, ...children);
}

function renderGrab() {
  if (!upload.open) return;
  // Waehrend man tippt, nicht die Felder unter den Fingern neu aufbauen
  const active = document.activeElement;
  if (active && active.closest && active.closest("#grab-list") && active.matches("input")) return;
  $("grab-list").replaceChildren(...grab.jobs.map(grabJobView));
}

async function pollGrab() {
  clearTimeout(grab.timer);
  if (!upload.open) return;
  try {
    const data = await api.get("/api/remote/jellyfin/grab");
    grab.jobs = data.jobs || [];
    renderGrab();
  } catch (err) {
    // naechster Versuch
  }
  const busy = grab.jobs.some((j) => ["suche", "wartet", "laedt"].includes(j.status));
  grab.timer = setTimeout(pollGrab, busy ? GRAB_POLL_ACTIVE_MS : GRAB_POLL_IDLE_MS);
}

async function submitGrab(url) {
  try {
    const data = await api.post("/api/remote/jellyfin/grab", { url });
    grab.jobs = data.jobs;
    $("grab-url").value = "";
    document.activeElement && document.activeElement.blur();
    renderGrab();
    pollGrab();
  } catch (err) {
    toast(err.message, true);
  }
}

$("grab-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const url = $("grab-url").value.trim();
  if (!url) {
    toast("Bitte einen Link einfügen", true);
    return;
  }
  submitGrab(url);
});

// Lesezeichen fuer den Laptop: schickt die gerade offene Seite an den Pi
onTap($("grab-bookmark"), async () => {
  const code = `javascript:void(window.open('${location.origin}/remote.html#grab='+encodeURIComponent(location.href)))`;
  try {
    await navigator.clipboard.writeText(code);
    toast("Kopiert – am Laptop als Adresse eines neuen Lesezeichens einfügen");
  } catch (err) {
    window.prompt("Als Adresse eines Lesezeichens einfügen:", code);
  }
});

// Upload-Sheet oeffnet -> Downloads mit anzeigen
const openUploadWithoutGrab = openUpload;
openUpload = function () {
  openUploadWithoutGrab();
  if (!upload.targets.length) loadUploadTargets();
  pollGrab();
};

// Vom Lesezeichen: remote.html#grab=<Seite>
(function grabFromHash() {
  const match = location.hash.match(/^#grab=(.+)$/);
  if (!match) return;
  const url = decodeURIComponent(match[1]);
  history.replaceState(history.state, "", location.pathname);
  openView("jellyfin");
  openUpload();
  submitGrab(url);
})();
