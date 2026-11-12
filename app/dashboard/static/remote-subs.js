"use strict";

/* ============================================================
   Fernbedienung: YouTube-Abos (neueste Videos der abonnierten Kanaele).
   Antippen spielt das Video auf dem Fernseher. Nutzt die Helfer aus
   remote.js ($, h, icon, api, toast, setBackground, formatTime, poll).
   ============================================================ */

const subs = { loaded: false, loading: false };

function timeAgo(timestamp) {
  if (!timestamp) return "";
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - timestamp) / 60));
  if (minutes < 60) return `vor ${minutes} Min.`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `vor ${hours} Std.`;
  const days = Math.round(hours / 24);
  if (days < 7) return days === 1 ? "gestern" : `vor ${days} Tagen`;
  const weeks = Math.round(days / 7);
  return weeks === 1 ? "vor 1 Woche" : `vor ${weeks} Wochen`;
}

async function playSubscription(video) {
  try {
    await api.post("/api/remote/youtube", { action: "play", url: video.id });
    toast("Läuft gleich auf dem Fernseher");
    poll();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderSubscriptions(videos) {
  $("subs-list").replaceChildren(
    ...videos.map((video) => {
      const thumb = h(
        "span",
        { class: "subs-thumb" },
        video.live ? h("span", { class: "subs-badge live" }, "LIVE") : video.duration ? h("span", { class: "subs-badge" }, formatTime(video.duration)) : null
      );
      setBackground(thumb, video.thumbnail);
      return h(
        "button",
        { class: "subs-row", type: "button", onclick: () => playSubscription(video) },
        thumb,
        h(
          "span",
          { class: "subs-text" },
          h("span", { class: "subs-title" }, video.title),
          h("span", { class: "subs-meta" }, [video.channel, timeAgo(video.timestamp)].filter(Boolean).join(" · "))
        )
      );
    })
  );
}

async function loadSubscriptions(force = false) {
  if (subs.loading) return;
  subs.loading = true;
  const box = $("subs-list");
  const button = $("subs-refresh");
  button.disabled = true;
  if (!subs.loaded) box.replaceChildren(h("div", { class: "subs-empty" }, "Abos werden geladen …"));
  try {
    const data = await api.get(`/api/remote/youtube/subscriptions${force ? "?force=true" : ""}`);
    renderSubscriptions(data.videos || []);
    subs.loaded = true;
  } catch (err) {
    if (!subs.loaded) box.replaceChildren(h("div", { class: "subs-empty" }, err.message));
    else toast(err.message, true);
  } finally {
    subs.loading = false;
    button.disabled = false;
  }
}

onTap($("subs-refresh"), () => loadSubscriptions(true));
VIEW_HOOKS.youtube = () => loadSubscriptions(false);
