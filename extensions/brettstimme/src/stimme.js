/*
 * Brettstimme – Sprachausgabe (Text-to-Speech) und Spracherkennung (Mikrofon)
 * Nutzt die eingebauten Browser-APIs (Chrome / Edge).
 *
 * Laeuft die Seite auf dem Fernseher von TV-Jarvis, stellt Jarvis vorher
 * window.__jarvisChess bereit: dann spricht Jarvis die Ansagen (eigene
 * Stimme ueber den Fernseher) und das Gesprochene kommt vom Handy.
 */
(function (root) {
  'use strict';

  const synth = root.speechSynthesis;
  const Erkennung = root.SpeechRecognition || root.webkitSpeechRecognition;
  const jarvis = () => root.__jarvisChess || null;

  // ---------- Sprachausgabe ----------
  let stimmen = [];
  function ladeStimmen() {
    stimmen = synth ? synth.getVoices().filter((v) => /^de(-|_|$)/i.test(v.lang)) : [];
    return stimmen;
  }
  if (synth) {
    ladeStimmen();
    synth.addEventListener && synth.addEventListener('voiceschanged', ladeStimmen);
  }

  function besteStimme(name) {
    ladeStimmen();
    if (name) {
      const v = stimmen.find((s) => s.name === name);
      if (v) return v;
    }
    const vorlieben = [/natural/i, /online/i, /google/i, /katja|conrad|amala|seraphina|florian/i, /de-DE/i];
    for (const re of vorlieben) {
      const v = stimmen.find((s) => re.test(s.name) || re.test(s.lang));
      if (v) return v;
    }
    return stimmen[0] || null;
  }

  const pause = (ms) => new Promise((r) => setTimeout(r, ms));

  function sprichEinmal(text, opt) {
    return new Promise((resolve) => {
      if (!synth) return resolve();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'de-DE';
      const v = besteStimme(opt.stimme);
      if (v) u.voice = v;
      u.rate = opt.tempo || 1;
      u.volume = opt.lautstaerke == null ? 1 : opt.lautstaerke;
      let fertig = false;
      const ende = () => { if (!fertig) { fertig = true; clearTimeout(notbremse); resolve(); } };
      // Chrome feuert "end" manchmal nicht – Notbremse nach geschätzter Dauer
      const notbremse = setTimeout(ende, 2500 + text.length * 120 / (u.rate || 1));
      u.onend = ende;
      u.onerror = ende;
      synth.speak(u);
    });
  }

  let sprichtGerade = false;
  let sprechAuftrag = 0;
  /** Spricht text `mal`-mal (mit Pause dazwischen). Neuere Aufträge brechen ältere ab. */
  async function sprich(text, opt = {}) {
    const meinAuftrag = ++sprechAuftrag;
    if (synth) synth.cancel();
    sprichtGerade = true;
    try {
      const mal = opt.mal || 1;
      if (jarvis()) {
        await jarvis().sprich(text, mal);
        return;
      }
      for (let i = 0; i < mal; i++) {
        if (meinAuftrag !== sprechAuftrag) return;
        await sprichEinmal(text, opt);
        if (i < mal - 1) await pause(opt.pauseMs || 900);
      }
    } finally {
      if (meinAuftrag === sprechAuftrag) sprichtGerade = false;
    }
  }

  function verstummen() {
    sprechAuftrag++;
    sprichtGerade = false;
    if (synth) synth.cancel();
    if (jarvis()) jarvis().verstummen();
  }

  // ---------- Spracherkennung ----------
  /**
   * Hört dauerhaft zu (startet sich nach Pausen selbst neu), solange `aktiv` ist.
   * onErgebnis(alternativen: string[]) bekommt die erkannten Varianten, beste zuerst.
   */
  function erstelleZuhoerer({ onErgebnis, onZustand, onFehler }) {
    if (jarvis()) {
      // Das Mikrofon ist das Handy: Jarvis liefert fertige Texte ueber
      // Brettstimme.hoere(). Hier nur merken, ob gerade zugehoert wird.
      let soll = false;
      return {
        verfuegbar: true,
        starte() { soll = true; onZustand && onZustand('hoert'); },
        stoppe() { soll = false; onZustand && onZustand('aus'); },
        get aktiv() { return soll; },
      };
    }
    if (!Erkennung) {
      return { verfuegbar: false, starte() { onFehler && onFehler('nicht-unterstuetzt'); }, stoppe() {}, get aktiv() { return false; } };
    }
    let rec = null;
    let soll = false;
    let laeuft = false;
    let neustartTimer = null;
    let fehlerInFolge = 0;

    function neu() {
      const r = new Erkennung();
      r.lang = 'de-DE';
      r.continuous = false;
      r.interimResults = true;
      r.maxAlternatives = 5;
      r.onstart = () => { laeuft = true; onZustand && onZustand('hoert'); };
      r.onresult = (e) => {
        const res = e.results[e.results.length - 1];
        if (!res) return;
        const alts = [];
        for (let i = 0; i < res.length; i++) alts.push(res[i].transcript.trim());
        if (res.isFinal) {
          fehlerInFolge = 0;
          onErgebnis && onErgebnis(alts.filter(Boolean));
        } else {
          onZustand && onZustand('zwischen', alts[0]);
        }
      };
      r.onerror = (e) => {
        if (e.error === 'no-speech' || e.error === 'aborted') return;
        fehlerInFolge++;
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') soll = false;
        onFehler && onFehler(e.error);
      };
      r.onend = () => {
        laeuft = false;
        if (soll) {
          clearTimeout(neustartTimer);
          neustartTimer = setTimeout(starteIntern, fehlerInFolge > 2 ? 2000 : 150);
        } else {
          onZustand && onZustand('aus');
        }
      };
      return r;
    }

    function starteIntern() {
      if (!soll || laeuft) return;
      try {
        rec = neu();
        rec.start();
      } catch (e) {
        neustartTimer = setTimeout(starteIntern, 500);
      }
    }

    return {
      verfuegbar: true,
      starte() {
        soll = true;
        starteIntern();
      },
      stoppe() {
        soll = false;
        clearTimeout(neustartTimer);
        if (rec) { try { rec.abort(); } catch (e) { /* egal */ } }
        laeuft = false;
        onZustand && onZustand('aus');
      },
      get aktiv() { return soll; },
    };
  }

  root.Brettstimme = root.Brettstimme || {};
  root.Brettstimme.stimme = {
    sprich, verstummen, erstelleZuhoerer, ladeStimmen, besteStimme,
    get sprichtGerade() { return sprichtGerade; },
    get kannSprechen() { return !!synth; },
    get kannHoeren() { return !!Erkennung || !!jarvis(); },
  };
})(window);
