"use strict";

/* ============================================================
   Live-Vorschau: der simulierte Pi.
   Beantwortet alle Anfragen von Fernbedienung und Fernseher im Browser.
   Kein Speicher, kein Netz zum Pi - nach dem Neuladen ist alles neu.
   Das Gegenstueck im echten Projekt ist app/dashboard/server.py.
   ============================================================ */

const DEMO_ENABLED = ["youtube", "jellyfin", "twitch", "light", "calendar_google", "todos", "iserv", "abfahrten", "durchsage", "einkaufsliste", "schlaf_timer", "wlan_lampen", "quiz", "pinnwand"];
const FILMS = [
  { id: "f-bbb", name: "Big Buck Bunny", year: 2008, runtime: 635, url: "https://upload.wikimedia.org/wikipedia/commons/transcoded/c/c0/Big_Buck_Bunny_4K.webm/Big_Buck_Bunny_4K.webm.720p.vp9.webm", overview: "Ein großes, gutmütiges Kaninchen nimmt Rache an drei Nagern, die ihm den Tag verderben. Freier Film der Blender Foundation (CC BY 3.0), über Wikimedia Commons." },
  { id: "f-sintel", name: "Sintel", year: 2010, runtime: 888, url: "https://upload.wikimedia.org/wikipedia/commons/transcoded/f/f1/Sintel_movie_4K.webm/Sintel_movie_4K.webm.720p.vp9.webm", overview: "Eine junge Frau sucht ihren verlorenen Drachen. Freier Kurzfilm der Blender Foundation (CC BY 3.0), über Wikimedia Commons." },
];
const QUESTIONS = [
  ["Welcher ist der höchste Berg Deutschlands?", "Zugspitze", "Watzmann", "Feldberg", "Brocken"],
  ["Wie heißt die Hauptstadt von Australien?", "Canberra", "Sydney", "Melbourne", "Perth"],
  ["In welchem Jahr fiel die Berliner Mauer?", "1989", "1990", "1987", "1991"],
  ["Wie viele Planeten hat unser Sonnensystem?", "8", "9", "7", "10"],
  ["Wer malte die „Mona Lisa“?", "Leonardo da Vinci", "Michelangelo", "Raffael", "Botticelli"],
  ["Wie lang ist ein Marathon?", "42,195 km", "40 km", "42 km", "45,195 km"],
  ["Welches ist das größte Tier der Welt?", "Blauwal", "Elefant", "Pottwal", "Walhai"],
  ["Wie viele Minuten hat ein Tag?", "1440", "1240", "1400", "1640"],
  ["Aus welchem Land stammt die Band ABBA?", "Schweden", "Norwegen", "Dänemark", "Finnland"],
  ["Wie lautet das chemische Symbol für Gold?", "Au", "Ag", "Go", "Gd"],
];
const BOTS = ["Mia", "Ben", "Oma Gerda"];
const pad = (n) => String(n).padStart(2, "0");
const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fail = (status, detail) => ({ status, json: { detail } });
const ok = (json = { ok: true }) => ({ status: 200, json });
const NOT_IN_DEMO = "In der Vorschau nicht verfügbar – auf dem echten Pi geht das.";

class DemoServer {
  constructor(data, hooks) {
    this.hooks = hooks; // { power(on), openPage(url), closePage(), speak(text) }
    this.tvSockets = new Set();
    this.pending = null;
    this.apps = data.apps.map((app) => ({ ...app, enabled: DEMO_ENABLED.includes(app.id), configured: true, removable: false }));
    this.effects = data.effects;
    this.profile = { name: "RPi TV", user_name: "Alex", city: "Berlin" };
    this.tvOn = true;
    this.pageOpen = null;
    this.volume = { percent: 35, muted: false };
    this.youtube = { video_id: null, title: null, thumbnail_url: null, current_time: 0, duration: 0, playing: false };
    this.jellyfin = { item_id: null, title: null, subtitle: null, poster: null, backdrop: null, current_time: 0, duration: 0, playing: false };
    this.positions = {};
    this.twitchChannels = [{ login: "beispielkanal", display_name: "Beispielkanal", live: false }];
    this.radio = { playing: false, current_id: "sunshine", stations: [{ id: "sunshine", name: "Sunshine Live", url: "" }, { id: "1live", name: "1LIVE", url: "" }] };
    this.timer = { id: 0, state: "idle", duration: 0, ends_at: 0, remaining: 0, acknowledged: false };
    this.clockScreen = false;
    this.light = { on: false, brightness: 80, color: "#ff8a3d", effect: "static", bpm: 120, fixtures: 2, addresses: ["d001", "d009"], error: null };
    this.schedule = { enabled: true, weekday: { wake_time: "06:30", leave_time: "07:15" }, weekend: { wake_time: "08:30", leave_time: "10:30" } };
    this.school = { klasse: "Q1", kurse: ["MA L1", "D G2", "PA G1"], faecher: { "MA L1": "Mathe", "D G2": "Deutsch", "PA G1": "Pädagogik" } };
    this.todos = [{ text: "Pfandflaschen wegbringen", done: false }, { text: "Oma anrufen", done: false }, { text: "Fahrrad aufpumpen", done: true }];
    // Apps
    this.pinnwand = { text: "Willkommen in der Vorschau!" };
    this.durchsage = { history: [] };
    this.shopping = ["Milch", "Brot", "Äpfel"].map((text, i) => ({ id: `i${i}`, text, done: false }));
    this.sleep = { ends_at: 0, minutes: 0, timer: null };
    this.stop = { id: "demo-hbf", name: "Hauptbahnhof" };
    this.lamps = [
      { id: "l1", name: "Wohnzimmer", ip: "192.168.1.41", found: true, on: true },
      { id: "l2", name: "Sofa", ip: "192.168.1.42", found: true, on: false },
      { id: "l3", name: "Flur", ip: "192.168.1.43", found: true, on: false },
    ];
    this.quiz = null;
  }

  // ---------- Fernseher (Kiosk) ----------

  connectTv(socket) {
    this.tvSockets.add(socket);
    if (this.pending) {
      const message = this.pending;
      this.pending = null;
      socket.deliver(message);
    }
    if (this.timer.state !== "idle") socket.deliver(this.timerMessage(false));
  }

  disconnectTv(socket) {
    this.tvSockets.delete(socket);
  }

  send(message) {
    if (message.type && message.type.endsWith("_play") && this.pageOpen) this.closePage();
    if (!this.tvSockets.size && message.type && message.type.endsWith("_play")) this.pending = message;
    this.tvSockets.forEach((socket) => socket.deliver(message));
  }

  fromTv(msg) {
    if (msg.type === "youtube_progress") {
      Object.assign(this.youtube, { video_id: msg.video_id || this.youtube.video_id, current_time: msg.current_time, duration: msg.duration, playing: msg.playing, title: msg.title || this.youtube.title });
    } else if (msg.type === "jellyfin_progress") {
      Object.assign(this.jellyfin, { current_time: msg.current_time, duration: msg.duration, playing: msg.playing });
      if (msg.item_id) this.positions[msg.item_id] = msg.current_time;
    } else if (msg.type === "jellyfin_ended") {
      this.resetJellyfin();
    }
  }

  mediaUrl(value) {
    const match = value.match(/jellyfin\/stream\/([\w-]+)/);
    const film = match && FILMS.find((f) => f.id === match[1]);
    return film ? film.url : value;
  }

  resetYoutube() {
    Object.assign(this.youtube, { video_id: null, title: null, thumbnail_url: null, current_time: 0, duration: 0, playing: false });
  }

  resetJellyfin() {
    Object.assign(this.jellyfin, { item_id: null, title: null, subtitle: null, current_time: 0, duration: 0, playing: false });
  }

  async ensureOn() {
    if (!this.tvOn) await this.power(true);
  }

  async power(on) {
    if (on === this.tvOn) return;
    if (on) {
      this.tvOn = true;
      this.hooks.power(true);
      return;
    }
    this.radio.playing = false;
    this.resetYoutube();
    this.resetJellyfin();
    this.closePage();
    this.send({ type: "shutdown" });
    await new Promise((r) => setTimeout(r, 1700));
    this.tvOn = false;
    this.hooks.power(false);
  }

  async openPage(appId, page) {
    await this.ensureOn();
    this.radio.playing = false;
    this.pageOpen = appId;
    this.hooks.openPage(`apps/${appId}/${page || "tv.html"}`);
  }

  closePage() {
    this.pageOpen = null;
    this.hooks.closePage();
  }

  speak(text) {
    return this.hooks.speak(text);
  }

  // ---------- Daten fuer das Dashboard ----------

  enabled(id) {
    const app = this.apps.find((a) => a.id === id);
    return !!(app && app.enabled);
  }

  weather() {
    const now = new Date();
    const icons = ["sun-cloud", "cloud", "sun-cloud", "sun", "cloud", "rain"];
    const hourly = icons.map((icon, i) => {
      const t = new Date(now.getTime() + (i + 1) * 2 * 3600000);
      return { time: `${pad(t.getHours())}:00`, icon, is_day: t.getHours() >= 8 && t.getHours() < 17, temp: 4 + Math.round(Math.sin(i) * 3), rain: icon === "rain" ? 60 : 10 };
    });
    const days = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
    const daily = [1, 2, 3].map((d, i) => ({ day: days[(now.getDay() + d) % 7], icon: ["cloud", "sun", "showers"][i], min: [1, -1, 3][i], max: [6, 8, 9][i], rain: [20, 0, 70][i] }));
    return { description: "Leicht bewölkt", icon: "sun-cloud", is_day: now.getHours() >= 8 && now.getHours() < 17, temp_current: 5.4, temp_feels: 2.9, temp_min: 1.2, temp_max: 7.8, precipitation_probability: 20, wind_kmh: 12, city: this.profile.city || "Berlin", sunrise: "07:48", sunset: "16:02", hourly, daily };
  }

  events(offsetDays) {
    const base = new Date();
    base.setDate(base.getDate() + offsetDays);
    const at = (h, m) => new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, m);
    const list = offsetDays === 0
      ? [["Zahnarzt", 9, 30, 10, 15], ["Team-Meeting", 14, 0, 15, 0], ["Kino mit Lena", 20, 15, 22, 30]]
      : [["Joggen", 7, 0, 7, 45], ["Elternabend", 19, 0, 20, 30]];
    return list.map(([title, h1, m1, h2, m2]) => ({ title, time_label: `${pad(h1)}:${pad(m1)}`, all_day: false, source: "Google", start: at(h1, m1).toISOString(), end: at(h2, m2).toISOString() }));
  }

  plan() {
    const today = new Date();
    const tomorrow = new Date(today.getTime() + 86400000);
    return [
      { lesson: "3", subject: "MA L1", subject_name: "Mathe", kind: "Vertretung", room: "B12", note: "Aufgaben im Buch", day: "Heute", date: isoDate(today) },
      { lesson: "5 - 6", subject: "D G2", subject_name: "Deutsch", kind: "Entfall", room: "", note: "", day: "Heute", date: isoDate(today) },
      { lesson: "2", subject: "PA G1", subject_name: "Pädagogik", kind: "Raum-Vertretung", room: "A04", note: "", day: "Morgen", date: isoDate(tomorrow) },
    ];
  }

  state() {
    const day = new Date().getDay();
    return {
      generated_at: new Date().toISOString(),
      weekday: ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"][day],
      is_school_day: day > 0 && day < 6,
      weather: this.weather(),
      events: this.enabled("calendar_google") ? this.events(0) : [],
      events_tomorrow: this.enabled("calendar_google") ? this.events(1) : [],
      substitution_plan: this.enabled("iserv") ? this.plan() : [],
      todo_entries: this.todos,
      todos: this.todos.filter((t) => !t.done).map((t) => t.text),
      errors: [],
      not_configured: [],
      radio_playing: this.radio.playing,
      name: this.profile.name,
      user_name: this.profile.user_name,
      apps: Object.fromEntries(this.apps.map((a) => [a.id, a.enabled])),
    };
  }

  departures() {
    const now = Date.now();
    const lines = [["RE 6", "Minden", 20, 4, "Zug"], ["S 1", "Flughafen", 15, 9, "S-Bahn"], ["Bus 250", "Rathaus", 10, 2, "Bus"], ["RB 71", "Bielefeld", 30, 17, "Zug"]];
    const result = [];
    lines.forEach(([line, direction, every, offset, mode], li) => {
      for (let k = 0; k < 4; k += 1) {
        const minute = Math.ceil((now / 60000 - offset) / every) * every + offset + k * every;
        const when = new Date(minute * 60000);
        const delay = li === 0 && k === 0 ? 4 : 0;
        result.push({ line, direction, mode, when: new Date(when.getTime() + delay * 60000).toISOString(), time: hhmm(when), delay, track: mode === "Bus" ? "" : String(li + 1), cancelled: li === 3 && k === 1, realtime: true, reachable: true });
      }
    });
    return result.sort((a, b) => Date.parse(a.when) - Date.parse(b.when)).slice(0, 14);
  }

  panels() {
    const panels = [];
    const color = (id) => (this.apps.find((a) => a.id === id) || {}).color;
    if (this.enabled("abfahrten")) {
      panels.push({ id: "abfahrten", title: "Abfahrten", meta: this.stop.name, empty: "", color: color("abfahrten"), items: this.departures().slice(0, 6).map((d) => ({ time: d.time, text: `${d.line} → ${d.direction}`, note: d.cancelled ? "fällt aus" : [d.delay ? `+${d.delay}` : "", d.track ? `Gl. ${d.track}` : ""].filter(Boolean).join(" · "), strike: d.cancelled })) });
    }
    const open = this.shopping.filter((i) => !i.done);
    if (this.enabled("einkaufsliste") && open.length) {
      panels.push({ id: "einkaufsliste", title: "Einkaufen", meta: `${open.length} offen`, empty: "", color: color("einkaufsliste"), items: open.map((i) => ({ time: "", text: i.text, note: "", strike: false })) });
    }
    if (this.enabled("schlaf_timer") && this.sleep.ends_at) {
      const left = Math.max(1, Math.round((this.sleep.ends_at - Date.now()) / 60000));
      panels.push({ id: "schlaf_timer", title: "Schlaf-Timer", meta: `noch ${left} min`, empty: "", color: color("schlaf_timer"), items: [{ time: hhmm(new Date(this.sleep.ends_at)), text: "Fernseher geht aus", note: "", strike: false }] });
    }
    return panels;
  }

  briefingText() {
    const now = new Date();
    const events = this.events(0).map((e) => `um ${e.time_label.replace(":", " Uhr ")} ${e.title}`).join(", ");
    return `Guten Morgen${this.profile.user_name ? `, ${this.profile.user_name}` : ""}! Heute ist ${this.state().weekday}. Draußen sind es 5 Grad, leicht bewölkt. Du hast drei Termine: ${events}. In der dritten Stunde hast du Vertretung in Mathe. Der Deutschkurs in der fünften und sechsten Stunde fällt aus. Ich wünsche dir einen schönen Tag!`;
  }

  // ---------- Timer ----------

  timerPublic() {
    const remaining = this.timer.state === "running" ? Math.max(0, this.timer.ends_at - Date.now()) : this.timer.state === "paused" ? this.timer.remaining : 0;
    return { id: this.timer.id, state: this.timer.state, duration: this.timer.duration, remaining_ms: Math.round(remaining), acknowledged: this.timer.acknowledged, clock_screen: this.clockScreen };
  }

  timerMessage(show) {
    return { type: "timer_state", show, ...this.timerPublic() };
  }

  scheduleTimer() {
    clearTimeout(this.timerHandle);
    if (this.timer.state !== "running") return;
    const id = this.timer.id;
    this.timerHandle = setTimeout(() => {
      if (this.timer.id !== id || this.timer.state !== "running") return;
      this.timer.state = "ringing";
      this.youtube.playing && this.send({ type: "youtube_pause" });
      this.send(this.timerMessage(true));
    }, Math.max(0, this.timer.ends_at - Date.now()));
  }

  // ---------- Quiz mit Mitspieler-Bots ----------

  quizState() {
    const q = this.quiz;
    if (!q) return { phase: "none" };
    const ranking = [...q.players].sort((a, b) => b.score - a.score).map((p) => ({ name: p.name, score: p.score, gained: p.gained || 0 }));
    let question = null;
    if (q.phase === "question" || q.phase === "reveal") {
      const item = q.questions[q.index];
      question = { text: item.q, cat: "Allgemeinwissen", answers: item.answers, number: q.index + 1, total: q.questions.length };
      if (q.phase === "reveal") {
        question.correct = item.correct;
        question.counts = item.answers.map((_, i) => q.players.filter((p) => p.answer === i).length);
      }
    }
    return {
      code: q.code, phase: q.phase, remaining: q.phase === "question" ? Math.max(0, (q.ends_at - Date.now()) / 1000) : 0, seconds: 15,
      answered: q.players.filter((p) => p.answer !== null).length, players: q.players.map((p) => p.name), ranking,
      join_url: "https://github.com/t0n3y/tv-jarvis", question,
    };
  }

  async quizRun() {
    const q = this.quiz;
    for (q.index = 0; q.index < q.questions.length; q.index += 1) {
      if (this.quiz !== q) return;
      q.phase = "question";
      q.started = Date.now();
      q.ends_at = Date.now() + 15000;
      q.skip = false;
      q.players.forEach((p) => {
        p.answer = null;
        p.gained = 0;
        // Bots antworten nach 2-11 s, meistens richtig
        const correct = q.questions[q.index].correct;
        const choice = Math.random() < 0.65 ? correct : (correct + 1 + Math.floor(Math.random() * 3)) % 4;
        p.timer = setTimeout(() => {
          if (q.phase === "question") {
            p.answer = choice;
            p.at = Date.now();
          }
        }, 2000 + Math.random() * 9000);
      });
      while (Date.now() < q.ends_at && !q.skip && !q.players.every((p) => p.answer !== null)) await new Promise((r) => setTimeout(r, 250));
      q.players.forEach((p) => {
        clearTimeout(p.timer);
        if (p.answer === q.questions[q.index].correct) {
          p.gained = 500 + Math.round(500 * Math.max(0, 1 - (p.at - q.started) / 15000));
          p.score += p.gained;
        }
      });
      q.phase = "reveal";
      q.skip = false;
      const end = Date.now() + 6000;
      while (Date.now() < end && !q.skip) await new Promise((r) => setTimeout(r, 250));
    }
    q.phase = "final";
  }

  // ---------- Anfragen ----------

  async handle(method, path, query, body = {}) {
    try {
      return await this.route(method, path, query, body || {});
    } catch (err) {
      console.error(err);
      return fail(500, "Fehler in der Vorschau");
    }
  }

  publicApp(app) {
    return app;
  }

  async route(method, path, query, body) {
    const is = (m, p) => method === m && path === p;
    let m;

    // --- Kiosk ---
    if (is("GET", "/api/state")) return ok(this.state());
    if (is("GET", "/api/apps-dashboard")) return ok({ panels: this.panels() });
    if (is("GET", "/api/setup/status")) return ok({ name: this.profile.name, setup_done: true, password_set: true });

    // --- Fernbedienung: Grundlagen ---
    if (is("GET", "/api/remote/now-playing")) {
      return ok({
        tv_on: this.tvOn, youtube: this.youtube, twitch: { login: null, display_name: null, title: null, avatar: null, thumbnail: null, playing: false },
        twitch_error: { id: 0, message: null }, jellyfin: this.jellyfin, jellyfin_error: { id: 0, message: null },
        vinyl: { token: 0, position: 0, context: null, record: null, song_index: 0, title: null, artist: null, current_time: 0, duration: 0, playing: false, queue_length: 0, active: false },
        timer: this.timerPublic(), vinyl_error: { id: 0, message: null },
        radio: { playing: this.radio.playing, station: this.radio.stations.find((s) => s.id === this.radio.current_id) }, light: this.light,
      });
    }
    if (is("GET", "/api/remote/info")) return ok({ name: this.profile.user_name, jellyfin: true, system_name: this.profile.name, apps: this.state().apps });
    if (is("POST", "/api/remote/power")) {
      await this.power(body.state === "on");
      return ok();
    }
    if (is("POST", "/api/remote/volume")) {
      if (body.delta > 0) this.volume.percent = Math.min(100, this.volume.percent + 5);
      else if (body.delta < 0) this.volume.percent = Math.max(0, this.volume.percent - 5);
      else this.volume.muted = !this.volume.muted;
      if (body.delta) this.volume.muted = false;
      return ok({ ok: true, volume: this.volume });
    }

    // --- YouTube ---
    if (is("POST", "/api/remote/youtube")) {
      const a = body.action;
      if (a === "play") {
        const id = (String(body.url || "").match(/(?:v=|youtu\.be\/|shorts\/|embed\/|^)([\w-]{11})(?:[?&#]|$)/) || [])[1];
        if (!id) return fail(400, "Das ist kein YouTube-Link");
        await this.ensureOn();
        this.radio.playing = false;
        this.resetJellyfin();
        Object.assign(this.youtube, { video_id: id, title: "YouTube", thumbnail_url: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`, current_time: 0, duration: 0, playing: true });
        this.send({ type: "youtube_play", video_id: id });
        return ok({ ok: true, video_id: id });
      }
      if (a === "stop") this.resetYoutube();
      if (a === "pause") this.youtube.playing = false;
      if (a === "resume") this.youtube.playing = true;
      this.send({ type: `youtube_${a}`, seconds: body.seconds });
      return ok();
    }
    if (method === "GET" && path === "/api/remote/youtube/subscriptions") return ok({ videos: [], error: "In der Vorschau gibt es keine Abos – auf dem Pi meldest du dich einmal im TV-Browser bei YouTube an." });

    // --- Jellyfin (freie Blender-Filme) ---
    const film = (f, full) => {
      const item = { id: f.id, name: f.name, type: "Movie", is_folder: false, year: f.year, runtime_seconds: f.runtime, position_seconds: this.positions[f.id] || 0, played: false, series_name: null, season_number: null, episode_number: null, child_count: null, wide: false, poster: null, backdrop: null, subtitle: `${f.year} · ${Math.round(f.runtime / 60)} Min.` };
      return full ? { ...item, overview: f.overview, genres: ["Animation", "Kurzfilm"], official_rating: "FSK 6", community_rating: 7.5, playback_issue: null } : item;
    };
    if (is("GET", "/api/remote/jellyfin/home")) {
      const resume = FILMS.filter((f) => this.positions[f.id] > 30).map((f) => film(f));
      return ok({ libraries: [{ id: "lib-filme", name: "Freie Filme", type: "CollectionFolder", is_folder: true, child_count: FILMS.length, poster: null, backdrop: null, subtitle: "" }], resume });
    }
    if (method === "GET" && path === "/api/remote/jellyfin/items") {
      const search = (query.get("search") || "").toLowerCase();
      return ok({ items: FILMS.filter((f) => !search || f.name.toLowerCase().includes(search)).map((f) => film(f)) });
    }
    if ((m = path.match(/^\/api\/remote\/jellyfin\/item\/([\w-]+)$/))) {
      const f = FILMS.find((x) => x.id === m[1]);
      return f ? ok(film(f, true)) : fail(404, "Nicht gefunden");
    }
    if (is("POST", "/api/remote/jellyfin")) {
      if (body.action === "play") {
        const f = FILMS.find((x) => x.id === body.item_id);
        if (!f) return fail(404, "Nicht gefunden");
        await this.ensureOn();
        this.radio.playing = false;
        this.resetYoutube();
        const start = body.from_start ? 0 : this.positions[f.id] || 0;
        Object.assign(this.jellyfin, { item_id: f.id, title: f.name, subtitle: `${f.year}`, current_time: start, duration: f.runtime, playing: true });
        this.send({ type: "jellyfin_play", item_id: f.id, title: f.name, subtitle: `${f.year}`, poster_url: null, backdrop_url: null, duration: f.runtime, start_seconds: start, stream_url: `api/kiosk/jellyfin/stream/${f.id}` });
        return ok();
      }
      if (body.action === "stop") this.resetJellyfin();
      if (body.action === "pause") this.jellyfin.playing = false;
      if (body.action === "resume") this.jellyfin.playing = true;
      this.send({ type: `jellyfin_${body.action}`, seconds: body.seconds });
      return ok();
    }
    if (path.startsWith("/api/remote/jellyfin/upload")) return fail(400, NOT_IN_DEMO);

    // --- Twitch ---
    if (method === "GET" && path === "/api/remote/twitch") return ok({ channels: this.twitchChannels, error: null, now_playing: { login: null, playing: false } });
    if (is("POST", "/api/remote/twitch/channels")) {
      const login = String(body.login || "").toLowerCase().replace(/^.*twitch\.tv\//, "").replace(/[^\w]/g, "");
      if (!login) return fail(400, "Bitte einen Namen eingeben");
      if (!this.twitchChannels.some((c) => c.login === login)) this.twitchChannels.push({ login, display_name: login, live: false });
      return ok({ channels: this.twitchChannels });
    }
    if ((m = path.match(/^\/api\/remote\/twitch\/channels\/(.+)$/)) && method === "DELETE") {
      this.twitchChannels = this.twitchChannels.filter((c) => c.login !== decodeURIComponent(m[1]));
      return ok({ channels: this.twitchChannels });
    }
    if (is("POST", "/api/remote/twitch")) return body.action === "stop" ? ok() : fail(409, "In der Vorschau ist niemand live.");

    // --- Radio (ohne Ton in der Vorschau) ---
    if (is("GET", "/api/remote/radio/stations")) return ok({ stations: this.radio.stations, current_id: this.radio.current_id });
    if (is("POST", "/api/remote/radio/stations")) {
      const id = String(body.name || "sender").toLowerCase().replace(/[^\w]+/g, "-");
      this.radio.stations.push({ id, name: body.name, url: body.url });
      return ok({ stations: this.radio.stations, current_id: this.radio.current_id });
    }
    if ((m = path.match(/^\/api\/remote\/radio\/stations\/(.+)$/)) && method === "DELETE") {
      this.radio.stations = this.radio.stations.filter((s) => s.id !== decodeURIComponent(m[1]));
      return ok({ stations: this.radio.stations, current_id: this.radio.current_id });
    }
    if (is("POST", "/api/remote/radio")) {
      if (body.action === "play") {
        await this.ensureOn();
        this.radio.current_id = body.station_id || this.radio.current_id;
        this.radio.playing = true;
        if (this.youtube.video_id) this.send({ type: "youtube_stop" });
        if (this.jellyfin.item_id) this.send({ type: "jellyfin_stop" });
        this.resetYoutube();
        this.resetJellyfin();
      } else {
        this.radio.playing = false;
      }
      this.send({ type: "state_updated" });
      return ok({ ok: true, radio: { playing: this.radio.playing, station: this.radio.stations.find((s) => s.id === this.radio.current_id) } });
    }

    // --- Uhr & Timer ---
    if (is("POST", "/api/remote/timer")) {
      const a = body.action;
      const t = this.timer;
      if (a === "start" || a === "restart") {
        const seconds = a === "start" ? Math.round(Number(body.seconds)) : t.duration;
        if (!seconds) return fail(400, "Es gibt keinen Timer zum Neustarten");
        Object.assign(t, { id: t.id + 1, state: "running", duration: seconds, ends_at: Date.now() + seconds * 1000, remaining: seconds * 1000, acknowledged: false });
        await this.ensureOn();
      } else if (a === "pause" && t.state === "running") Object.assign(t, { state: "paused", remaining: t.ends_at - Date.now() });
      else if (a === "resume" && t.state === "paused") Object.assign(t, { state: "running", ends_at: Date.now() + t.remaining });
      else if (a === "add") {
        t.duration += Number(body.seconds) || 0;
        if (t.state === "running") t.ends_at += (Number(body.seconds) || 0) * 1000;
        else t.remaining += (Number(body.seconds) || 0) * 1000;
      } else if (a === "ack") t.acknowledged = true;
      else if (a === "cancel" || a === "dismiss") Object.assign(t, { state: "idle", remaining: 0, acknowledged: false });
      this.scheduleTimer();
      this.send(this.timerMessage(false));
      return ok({ ok: true, timer: this.timerPublic() });
    }
    if (is("POST", "/api/remote/clock")) {
      this.clockScreen = !!body.show;
      if (this.clockScreen) await this.ensureOn();
      this.send({ type: this.clockScreen ? "clock_show" : "clock_hide" });
      return ok({ ok: true, timer: this.timerPublic() });
    }

    // --- Licht (DMX) ---
    if (is("GET", "/api/remote/light")) return ok({ ...this.light, effects: this.effects });
    if (is("POST", "/api/remote/light")) {
      for (const key of ["on", "brightness", "color", "effect", "bpm", "fixtures"]) if (key in body) this.light[key] = body[key];
      this.light.addresses = Array.from({ length: this.light.fixtures }, (_, i) => `d${pad(i * 8 + 1).padStart(3, "0")}`);
      return ok(this.light);
    }

    // --- Einstellungen ---
    if (is("GET", "/api/remote/schedule")) return ok(this.schedule);
    if (is("POST", "/api/remote/schedule")) {
      Object.assign(this.schedule, body);
      return ok(this.schedule);
    }
    if (is("POST", "/api/remote/schedule/test")) {
      (async () => {
        await this.ensureOn();
        await new Promise((r) => setTimeout(r, 4500));
        await this.speak(this.briefingText());
        this.radio.playing = true;
        this.send({ type: "state_updated" });
      })();
      return ok();
    }
    if (is("GET", "/api/remote/school")) return ok(this.school);
    if (is("POST", "/api/remote/school")) {
      this.school.kurse = body.kurse || this.school.kurse;
      this.school.faecher = body.faecher || this.school.faecher;
      return ok(this.school);
    }
    if (is("GET", "/api/remote/system")) {
      return ok({ ...this.profile, setup_done: true, password_set: true, hardware: { connected: true, port: 1, cec_adapter: "/dev/cec0", alsa_device: "plughw:CARD=vc4hdmi0,DEV=0" }, cec_adapter: "/dev/cec0", alsa_device: "plughw:CARD=vc4hdmi0,DEV=0", password_suggestion: "demo-vors-chau-2026" });
    }
    if (is("POST", "/api/remote/system")) {
      if ("name" in body) this.profile.name = String(body.name || "").trim() || "RPi TV";
      if ("user_name" in body) this.profile.user_name = String(body.user_name || "").trim();
      if (body.city) this.profile.city = String(body.city).trim();
      this.send({ type: "state_updated" });
      this.hooks.rename(this.profile.name);
      return ok({ ...this.profile, setup_done: true, password_set: true });
    }
    if (is("POST", "/api/remote/system/test-tv")) {
      await this.ensureOn();
      this.speak(`Hallo! Hier ist ${this.profile.name}. Wenn du mich hörst, ist der Ton richtig eingestellt.`);
      return ok();
    }
    if (is("GET", "/api/remote/system/update")) return ok({ available: false, possible: true, count: 0, changes: [], version: "Vorschau", reason: "", state: { running: false } });
    if (is("POST", "/api/remote/system/restart")) return ok();
    if (path.startsWith("/api/remote/system/")) return fail(400, NOT_IN_DEMO);

    // --- App Store ---
    if (is("GET", "/api/remote/apps")) return ok({ apps: this.apps });
    if (is("POST", "/api/remote/apps/install")) return fail(400, NOT_IN_DEMO);
    if ((m = path.match(/^\/api\/remote\/apps\/(\w+)\/test$/))) return ok({ ok: true, message: "Vorschau: Verbindung simuliert – alles gut" });
    if ((m = path.match(/^\/api\/remote\/apps\/(\w+)\/tv$/))) {
      if (body.action === "close") this.closePage();
      else await this.openPage(m[1], body.page);
      return ok();
    }
    if ((m = path.match(/^\/api\/remote\/apps\/(\w+)$/)) && method === "POST") {
      const app = this.apps.find((a) => a.id === m[1]);
      if (!app) return fail(404, "Unbekannte App");
      if (body.enabled !== undefined && body.enabled !== null) app.enabled = !!body.enabled;
      for (const field of app.fields) {
        if (!(field.key in (body.values || {}))) continue;
        const value = body.values[field.key];
        if (field.key.startsWith("secret:")) field.is_set = field.is_set || !!value;
        else field.value = value;
      }
      this.send({ type: "state_updated" });
      return ok(app);
    }

    // --- Eigene Apps (apps/<id>/server.py im echten Projekt) ---
    if ((m = path.match(/^\/api\/apps\/(\w+)\/(.*)$/))) return this.appRoute(m[1], method, m[2], query, body);

    if (path.startsWith("/api/remote/vinyl") || path.startsWith("/api/remote/browser") || path.startsWith("/api/comics")) return method === "GET" ? ok({ genres: [], records: [], open: false, url: "", title: "", books: [] }) : fail(400, NOT_IN_DEMO);
    return fail(404, NOT_IN_DEMO);
  }

  async appRoute(id, method, sub, query, body) {
    const is = (m, p) => method === m && sub === p;
    let m;
    if (id === "pinnwand") {
      if (is("GET", "message")) return ok({ text: this.pinnwand.text, signature: "" });
      if (is("POST", "message")) {
        if (!String(body.text || "").trim()) return fail(400, "Bitte eine Nachricht eintippen");
        this.pinnwand.text = String(body.text).slice(0, 200);
        return ok();
      }
    }
    if (id === "durchsage") {
      const presets = ["Essen ist fertig!", "Kommst du bitte mal?", "Wir fahren in fünf Minuten los.", "Gute Nacht!"];
      if (is("GET", "info")) return ok({ presets, history: this.durchsage.history, tv_on: this.tvOn });
      if (is("POST", "say")) {
        const text = String(body.text || "").trim();
        if (!text) return fail(400, "Bitte etwas eintippen");
        if (!this.tvOn && !body.power_on) return fail(409, "Der Fernseher ist aus – Schalter „Fernseher dafür einschalten“ antippen");
        await this.ensureOn();
        await this.speak(text);
        this.durchsage.history = [{ text, at: hhmm(new Date()) }, ...this.durchsage.history.filter((h) => h.text !== text)].slice(0, 6);
        return ok();
      }
    }
    if (id === "einkaufsliste") {
      const items = () => ok({ items: this.shopping });
      if (is("GET", "items")) return items();
      if (is("POST", "items")) {
        for (const name of String(body.text || "").split(",").map((s) => s.trim()).filter(Boolean)) {
          const found = this.shopping.find((i) => i.text.toLowerCase() === name.toLowerCase());
          if (found) found.done = false;
          else this.shopping.push({ id: `i${Date.now()}${Math.random().toString(16).slice(2, 6)}`, text: name, done: false });
        }
        this.send({ type: "state_updated" });
        return items();
      }
      if ((m = sub.match(/^items\/(\w+)\/toggle$/))) {
        const item = this.shopping.find((i) => i.id === m[1]);
        if (item) item.done = !item.done;
        return items();
      }
      if ((m = sub.match(/^items\/(\w+)$/)) && method === "DELETE") {
        this.shopping = this.shopping.filter((i) => i.id !== m[1]);
        return items();
      }
      if (is("POST", "clear-done")) {
        this.shopping = this.shopping.filter((i) => !i.done);
        return items();
      }
    }
    if (id === "schlaf_timer") {
      const pub = () => ok({ active: !!this.sleep.ends_at, remaining: Math.round(Math.max(0, this.sleep.ends_at - Date.now()) / 1000), minutes: this.sleep.minutes });
      if (is("GET", "state")) return pub();
      if (is("POST", "start")) {
        clearTimeout(this.sleep.timer);
        this.sleep.minutes = Number(body.minutes);
        this.sleep.ends_at = Date.now() + this.sleep.minutes * 60000;
        this.sleep.timer = setTimeout(() => {
          this.sleep.ends_at = 0;
          this.power(false);
        }, this.sleep.minutes * 60000);
        return pub();
      }
      if (is("POST", "cancel")) {
        clearTimeout(this.sleep.timer);
        this.sleep.ends_at = 0;
        return pub();
      }
    }
    if (id === "abfahrten") {
      if (is("GET", "departures")) return ok({ stop: this.stop, departures: this.departures() });
      if (is("GET", "search")) {
        const q = (query.get("q") || "").trim();
        return ok({ stops: q.length < 2 ? [] : [`${q} Bahnhof`, `${q} Mitte`, `${q}, Rathaus`].map((name, i) => ({ id: `s${i}`, name, area: "Beispieldaten" })) });
      }
      if (is("POST", "stop")) {
        this.stop = { id: body.id, name: body.name };
        return ok();
      }
    }
    if (id === "bilderrahmen") {
      if (is("GET", "info")) return ok({ folder: "", folder_ok: false, count: 0, seconds: 12, showing: false });
      return fail(400, "In der Vorschau gibt es keine Fotos – auf dem Pi zeigt die App deinen Foto-Ordner.");
    }
    if (id === "wlan_lampen") {
      const pub = (l) => ({ id: l.id, name: l.name, ip: l.ip, found: l.found });
      if (is("GET", "devices")) return ok({ devices: this.lamps.map(pub), scenes: ["hell", "gemuetlich", "kino", "konzentration", "aus"] });
      if (is("GET", "status")) return ok({ status: this.lamps.map((l) => ({ id: l.id, on: l.on, online: true })) });
      if (is("POST", "discover")) {
        await new Promise((r) => setTimeout(r, 1500));
        return ok({ devices: this.lamps.map(pub) });
      }
      if (is("POST", "set")) {
        const targets = this.lamps.filter((l) => !body.ids || body.ids.includes(l.id));
        const on = body.scene ? body.scene !== "aus" : body.on !== false;
        targets.forEach((l) => (l.on = on));
        return ok({ results: targets.map((l) => ({ id: l.id, ok: true })) });
      }
    }
    if (id === "quiz") {
      if (is("POST", "new")) {
        clearTimeout(this.quizJoin);
        const questions = [...QUESTIONS].sort(() => Math.random() - 0.5).slice(0, Math.min(Number(body.rounds) || 5, QUESTIONS.length)).map(([q, ...answers]) => {
          const correct = answers[0];
          const shuffled = [...answers].sort(() => Math.random() - 0.5);
          return { q, answers: shuffled, correct: shuffled.indexOf(correct) };
        });
        this.quiz = { code: String(1000 + Math.floor(Math.random() * 9000)), phase: "lobby", players: [], questions, index: 0 };
        // Mitspieler-Bots treten nacheinander bei
        BOTS.forEach((name, i) => setTimeout(() => this.quiz && this.quiz.phase === "lobby" && this.quiz.players.push({ name, score: 0, answer: null }), 1500 + i * 1800));
        await this.openPage("quiz", "tv.html");
        return ok(this.quizState());
      }
      if (is("GET", "state") || is("GET", "tv")) return ok(this.quizState());
      if (is("POST", "start")) {
        if (!this.quiz || this.quiz.phase !== "lobby") return fail(409, "Kein Spiel in der Warteschlange");
        if (!this.quiz.players.length) return fail(400, "Noch niemand ist beigetreten");
        this.quizRun();
        return ok();
      }
      if (is("POST", "skip")) {
        if (this.quiz) this.quiz.skip = true;
        return ok();
      }
      if (is("POST", "end")) {
        this.quiz = null;
        this.closePage();
        return ok();
      }
    }
    return fail(404, NOT_IN_DEMO);
  }
}

window.DemoServer = DemoServer;
