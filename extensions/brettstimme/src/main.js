/*
 * Brettstimme – Ablaufsteuerung
 *   Gegner zieht  -> groß anzeigen + 2× ansagen -> zuhören
 *   Du sagst Zug  -> nachfragen ("Meinst du …?") -> Ja -> Zug auf chess.com ausführen
 */
(function (root) {
  'use strict';
  if (root.__brettstimmeGeladen) return;
  root.__brettstimmeGeladen = true;

  const P = root.Brettstimme.parser;
  const S = root.Brettstimme.stimme;
  const A = root.Brettstimme.anzeige;
  const E = () => A.einstellungen;
  const gross = (f) => String(f).toUpperCase();

  let aktiviert = false;
  let mikroPausiert = false;
  let phase = 'warten'; // warten | zug | bestaetigen | auswahl | ende
  let offenerZug = null;
  let offeneOptionen = null;
  let letzteAnsage = null;
  let kette = Promise.resolve();
  const zustand = { game: null, anzahl: -1, spieltAls: undefined, vorbei: false };

  // ---------- chess.com-Schnittstelle ----------

  function finde() {
    let bestes = null;
    let flaeche = 0;
    document.querySelectorAll('wc-chess-board, chess-board').forEach((b) => {
      if (!b.game) return;
      const r = b.getBoundingClientRect();
      if (r.width * r.height > flaeche) { flaeche = r.width * r.height; bestes = b; }
    });
    return bestes ? { brett: bestes, g: bestes.game } : null;
  }
  const farbeVon = (n) => (n === 1 ? 'w' : n === 2 ? 'b' : null);
  const spieltAls = (g) => { try { return farbeVon(g.getPlayingAs()); } catch (e) { return null; } };
  const amZug = (g) => { try { return farbeVon(g.getTurn()); } catch (e) { return null; } };
  const binDran = (g) => !!zustand.spieltAls && amZug(g) === zustand.spieltAls && !zustand.vorbei;

  function legaleZuege(g) {
    try { return g.getLegalMoves() || []; } catch (e) { return []; }
  }

  function leseZeit(container) {
    if (!container) return null;
    for (const e of container.querySelectorAll('[class*="clock"], [class*="time"]')) {
      if (e.children.length) continue;
      const t = e.textContent.trim();
      if (/^(\d{1,2}:)?\d{1,2}:\d{2}(\.\d)?$|^\d{1,2}\.\d$/.test(t)) return t;
    }
    return null;
  }

  function aktualisiereUhren(s) {
    if (!s) return A.setUhren(null);
    const oben = leseZeit(document.querySelector('.board-layout-top, #board-layout-player-top'));
    const unten = leseZeit(document.querySelector('.board-layout-bottom, #board-layout-player-bottom'));
    const untenFarbe = zustand.spieltAls || (s.brett.classList.contains('flipped') ? 'b' : 'w');
    const dran = zustand.vorbei ? null : amZug(s.g);
    A.setUhren({ oben, unten, amZug: dran ? (dran === untenFarbe ? 'unten' : 'oben') : null });
  }

  // ---------- Sprache ----------

  const sprechOptionen = (mal) => ({ mal: mal || 1, stimme: E().stimme, tempo: E().tempo });

  async function sage(text, mal) {
    zuhoerer.stoppe();
    A.setMikro('aus', 'Ansage läuft …', '');
    await S.sprich(text, sprechOptionen(mal));
  }

  function mikroText() {
    if (phase === 'bestaetigen') return 'Sag „Ja“ oder „Nein“';
    if (phase === 'auswahl') return 'Sag z.B. „der von B1“';
    if (phase === 'zug') return 'Ich höre zu – sag deinen Zug';
    return 'Mikrofon aus';
  }

  // Fuer TV-Jarvis: Zustand an die Fernbedienung melden
  function meldeStatus() {
    const J = root.__jarvisChess;
    if (!J) return;
    let offen = null;
    try {
      const s = finde();
      if (offenerZug && s) offen = P.beschreibeZug(offenerZug, s.g.getFEN()).titel;
    } catch (e) { /* egal */ }
    J.status({
      aktiv: aktiviert,
      phase,
      hinweis: mikroText(),
      partie: !!zustand.game,
      spieltAls: zustand.spieltAls || null,
      vorbei: zustand.vorbei,
      gegnerzug: letzteAnsage ? letzteAnsage.titel : null,
      offenerZug: offen,
      optionen: offeneOptionen ? offeneOptionen.map((z) => P.beschreibeZug(z).titel) : null,
    });
  }

  function hoeren() {
    meldeStatus();
    const darf = aktiviert && E().sprachEingabe && !mikroPausiert && S.kannHoeren &&
      ['zug', 'bestaetigen', 'auswahl'].includes(phase);
    if (darf) {
      zuhoerer.starte();
    } else {
      zuhoerer.stoppe();
      let text = 'Mikrofon aus';
      if (!S.kannHoeren) text = 'Spracheingabe wird von diesem Browser nicht unterstützt (Chrome oder Edge nutzen)';
      else if (phase === 'warten') text = 'Warte auf den Gegner …';
      else if (phase === 'ende') text = 'Partie beendet';
      else if (mikroPausiert || !E().sprachEingabe) text = 'Mikrofon aus – Zug tippen oder M drücken';
      A.setMikro('aus', text, '');
    }
  }

  const zuhoerer = S.erstelleZuhoerer({
    onErgebnis: (alts) => verarbeiteGehoertes(alts),
    onZustand: (z, zwischen) => {
      if (z === 'hoert') A.setMikro('hoert', mikroText());
      else if (z === 'zwischen') A.setMikro('hoert', null, zwischen);
      else if (z === 'aus') A.setMikro('aus', null);
    },
    onFehler: (f) => {
      const texte = {
        'not-allowed': 'Mikrofon blockiert – im Schloss-Symbol der Adresszeile erlauben',
        'service-not-allowed': 'Spracherkennung blockiert',
        network: 'Spracherkennung braucht Internet – versuche es erneut',
        'audio-capture': 'Kein Mikrofon gefunden',
        'nicht-unterstuetzt': 'Spracheingabe nicht unterstützt (Chrome oder Edge nutzen)',
      };
      A.setMikro('fehler', texte[f] || 'Mikrofon-Fehler: ' + f);
    },
  });

  // ---------- Ablauf ----------

  function folge(fn) {
    kette = kette.then(fn).catch((e) => console.error('[Brettstimme]', e));
    return kette;
  }

  function naechsterSchritt() {
    const s = finde();
    if (!s || zustand.vorbei) {
      phase = zustand.vorbei ? 'ende' : 'warten';
    } else if (binDran(s.g)) {
      if (!['bestaetigen', 'auswahl'].includes(phase)) phase = 'zug';
    } else {
      phase = 'warten';
    }
    hoeren();
  }

  function partieText(farbe) {
    if (farbe === 'w') return 'Du spielst Weiß';
    if (farbe === 'b') return 'Du spielst Schwarz';
    return 'Zuschauen';
  }

  function neuePartie(s, anzahl) {
    zustand.game = s.g;
    zustand.anzahl = anzahl;
    zustand.spieltAls = spieltAls(s.g);
    zustand.vorbei = false;
    offenerZug = null;
    offeneOptionen = null;
    letzteAnsage = null;
    phase = 'warten';
    A.setPartie(partieText(zustand.spieltAls));
    let fen = null;
    try { fen = s.g.getFEN(); } catch (e) { /* egal */ }
    const lz = letzterZug(s.g);
    A.zeigeBrett(fen, lz && lz.from, lz && lz.to, zustand.spieltAls || 'w');
    if (aktiviert) folge(() => begruessung(s, anzahl === 0));
  }

  function letzterZug(g) {
    try { return g.getLastMove() || null; } catch (e) { return null; }
  }

  async function begruessung(s, ganzNeu) {
    const ich = zustand.spieltAls;
    const lz = letzterZug(s.g);
    if (!ich) {
      A.zeigeInfo('Zuschauen', 'Züge werden angesagt', 'Du spielst in dieser Partie nicht mit – Spracheingabe ist aus.');
      if (lz) await sageGegnerzug(lz);
      return naechsterSchritt();
    }
    const farbe = ich === 'w' ? 'Weiß' : 'Schwarz';
    if (binDran(s.g)) {
      if (lz && !ganzNeu) {
        await sageGegnerzug(lz);
      } else {
        A.zeigeInfo(ganzNeu ? 'Neue Partie' : partieText(ich), `Du spielst ${farbe}. Dein Zug!`, 'Sag deinen Zug, z.B. „E4“ oder „Springer auf F3“.', true);
        await sage(`${ganzNeu ? 'Neue Partie. ' : ''}Du spielst ${farbe}. Dein Zug.`);
      }
    } else {
      A.zeigeInfo(ganzNeu ? 'Neue Partie' : partieText(ich), `Du spielst ${farbe}.`, 'Warte auf den Zug des Gegners …');
      await sage(`${ganzNeu ? 'Neue Partie. ' : ''}Du spielst ${farbe}. Warte auf den Gegner.`);
    }
    naechsterSchritt();
  }

  async function sageGegnerzug(zug) {
    const d = P.beschreibeZug(zug, zug.beforeFen);
    letzteAnsage = d;
    A.zeigeGegnerzug(d);
    await sage(d.sprache, E().ansageMal);
  }

  function neuerZug(s) {
    const lz = letzterZug(s.g);
    if (!lz) return;
    const von = farbeVon(lz.color);
    A.zeigeBrett(lz.fen || s.g.getFEN(), lz.from, lz.to, zustand.spieltAls || 'w');
    offenerZug = null;
    offeneOptionen = null;
    if (!aktiviert) {
      const d = P.beschreibeZug(lz, lz.beforeFen);
      if (von !== zustand.spieltAls) { letzteAnsage = d; A.zeigeGegnerzug(d); } else A.zeigeEigenenZug(d);
      return;
    }
    if (von !== zustand.spieltAls) {
      phase = 'warten';
      zuhoerer.stoppe();
      folge(async () => {
        await sageGegnerzug(lz);
        naechsterSchritt();
      });
    } else {
      const d = P.beschreibeZug(lz, lz.beforeFen);
      phase = 'warten';
      A.zeigeEigenenZug(d, 'Gespielt – warte auf den Gegner');
      hoeren();
      if (E().eigenenZugAnsagen) folge(() => sage('Gespielt: ' + d.sprache));
    }
  }

  function partieEnde(s) {
    zustand.vorbei = true;
    phase = 'ende';
    hoeren();
    let ergebnis = '*';
    try { ergebnis = s.g.getResult(); } catch (e) { /* egal */ }
    const ich = zustand.spieltAls;
    let text = 'Die Partie ist beendet.';
    if (ergebnis === '1/2-1/2') text = 'Remis.';
    else if (ergebnis === '1-0' || ergebnis === '0-1') {
      const sieger = ergebnis === '1-0' ? 'w' : 'b';
      text = !ich ? (sieger === 'w' ? 'Weiß gewinnt.' : 'Schwarz gewinnt.') : sieger === ich ? 'Du hast gewonnen!' : 'Du hast verloren.';
    }
    folge(async () => {
      A.zeigeInfo('Partie beendet', text, 'Starte auf chess.com eine neue Partie – Alt+B wechselt zwischen Anzeige und Webseite.');
      if (aktiviert) await sage('Partie beendet. ' + text);
    });
  }

  // ---------- Eingabe verarbeiten ----------

  function verarbeiteGehoertes(alts) {
    if (!alts.length || S.sprichtGerade) return;
    A.setMikro('hoert', mikroText(), alts[0]);
    if (alts.some((t) => P.istWiederholen(t))) return wiederholen();

    if (phase === 'bestaetigen') {
      const erst = alts[0];
      if (P.istJa(erst)) return ausfuehren();
      if (P.istNein(erst)) return abgelehnt();
      if (alts.some((t) => P.istJa(t))) return ausfuehren();
      if (alts.some((t) => P.istNein(t))) return abgelehnt();
      if (versucheZug(alts, true)) return;
      return folge(async () => { await sage('Bitte sag Ja oder Nein.'); hoeren(); });
    }
    if (phase === 'auswahl') {
      for (const t of alts) {
        const m = P.waehleOption(t, offeneOptionen, zustand.spieltAls);
        if (m) return kandidat(m);
      }
      if (alts.some((t) => P.istNein(t))) return abgelehnt();
      if (versucheZug(alts, true)) return;
      const frage = P.rueckfrage(offeneOptionen);
      return folge(async () => { await sage(frage.sprache); hoeren(); });
    }
    if (phase === 'zug') versucheZug(alts, false);
  }

  /** Sucht in den erkannten Varianten einen legalen Zug. */
  function versucheZug(alts, still) {
    const s = finde();
    if (!s || !binDran(s.g)) return false;
    const legal = legaleZuege(s.g);
    let mehrdeutig = null;
    for (const t of alts) {
      const r = P.findeZug(t, legal);
      if (r.status === 'ok') { kandidat(r.zuege[0], r.dameAngenommen); return true; }
      if (r.status === 'mehrdeutig' && !mehrdeutig) mehrdeutig = r;
    }
    if (mehrdeutig) { auswahl(mehrdeutig.zuege); return true; }
    if (!still) {
      const a = P.analysiere(alts[0]);
      const klingtNachZug = a.felder.length || a.figuren.length || a.rochade;
      A.setMikro('hoert', klingtNachZug ? 'Dieser Zug ist nicht möglich – nochmal?' : 'Nicht verstanden – nochmal?', alts[0]);
      if (klingtNachZug) folge(async () => { await sage('Dieser Zug geht nicht. Bitte nochmal.'); hoeren(); });
    }
    return false;
  }

  function kandidat(zug, dameAngenommen) {
    const s = finde();
    if (!s) return;
    const d = P.beschreibeZug(zug, s.g.getFEN());
    offeneOptionen = null;
    if (!E().nachfragen) {
      offenerZug = zug;
      return ausfuehren();
    }
    phase = 'bestaetigen';
    offenerZug = zug;
    meldeStatus();
    A.zeigeBestaetigung(d, dameAngenommen ? 'Umwandlung in Dame angenommen – für eine andere Figur z.B. „G8 Springer“ sagen.' : '');
    folge(async () => {
      await sage(d.sprache + ' Richtig?');
      hoeren();
    });
  }

  function auswahl(optionen) {
    phase = 'auswahl';
    offenerZug = null;
    offeneOptionen = optionen;
    meldeStatus();
    const frage = P.rueckfrage(optionen);
    const gleich = new Set(optionen.map((z) => z.piece + z.to)).size === 1;
    const farbe = zustand.spieltAls || 'w';
    A.zeigeAuswahl(frage.titel, optionen.map((z) => ({
      symbol: P.SYMBOL[farbe][z.piece],
      text: gleich ? `von ${gross(z.from)}` : P.beschreibeZug(z).titel,
    })));
    folge(async () => {
      await sage(frage.sprache);
      hoeren();
    });
  }

  function abgelehnt() {
    phase = 'zug';
    offenerZug = null;
    offeneOptionen = null;
    A.zeigeInfo('Dein Zug', 'Okay – sag deinen Zug nochmal.', letzteAnsage ? `Letzter Zug des Gegners: ${letzteAnsage.titel}` : '', true);
    folge(async () => {
      await sage('Okay, sag deinen Zug nochmal.');
      naechsterSchritt();
    });
  }

  function wiederholen() {
    if (!letzteAnsage) return;
    if (phase === 'bestaetigen' || phase === 'auswahl') phase = 'zug';
    offenerZug = null;
    offeneOptionen = null;
    const d = letzteAnsage;
    folge(async () => {
      A.zeigeGegnerzug(d);
      await sage(d.sprache, 1);
      naechsterSchritt();
    });
  }

  function gleicherZug(a, b) {
    const pa = (a.promotion || (/=([QRBN])/.exec(a.san || '') || [])[1] || '').toLowerCase();
    const pb = (b.promotion || (/=([QRBN])/.exec(b.san || '') || [])[1] || '').toLowerCase();
    return a.from === b.from && a.to === b.to && pa === pb;
  }

  function ausfuehren() {
    const s = finde();
    const zug = offenerZug;
    if (!s || !zug) return;
    const legal = legaleZuege(s.g);
    const echt = legal.find((z) => gleicherZug(z, zug));
    if (!echt || !binDran(s.g)) {
      phase = binDran(s.g) ? 'zug' : 'warten';
      offenerZug = null;
      folge(async () => { await sage('Dieser Zug ist gerade nicht möglich.'); naechsterSchritt(); });
      return;
    }
    offenerZug = null;
    phase = 'warten';
    zuhoerer.stoppe();
    const promo = (/=([QRBN])/.exec(echt.san || '') || [])[1];
    const vorher = zustand.anzahl;
    try {
      s.g.move({ from: echt.from, to: echt.to, promotion: promo ? promo.toLowerCase() : undefined, animate: true, userGenerated: true });
    } catch (e) {
      console.warn('[Brettstimme] game.move fehlgeschlagen, versuche Klicks', e);
    }
    setTimeout(() => {
      if (zustand.anzahl !== vorher || historienLaenge(s.g) !== vorher) return;
      klickeZug(s.brett, echt.from, echt.to);
      setTimeout(() => {
        if (historienLaenge(s.g) !== vorher) return;
        phase = 'zug';
        A.zeigeInfo('Hoppla', 'Der Zug konnte nicht ausgeführt werden.', 'Bitte ziehe direkt auf chess.com (Alt+B) oder versuche es nochmal.', true);
        folge(async () => { await sage('Der Zug konnte nicht ausgeführt werden.'); naechsterSchritt(); });
      }, 900);
    }, 900);
  }

  function historienLaenge(g) {
    try { return g.getHistorySANs().length; } catch (e) { return -1; }
  }

  /** Notlösung: Züge per simulierten Mausklicks auf das Brett. */
  function klickeZug(brett, von, nach) {
    const r = brett.getBoundingClientRect();
    const gedreht = brett.classList.contains('flipped');
    const punkt = (feld) => {
      const f = feld.charCodeAt(0) - 97;
      const z = +feld[1] - 1;
      const x = gedreht ? 7 - f : f;
      const y = gedreht ? z : 7 - z;
      return { clientX: r.left + (x + 0.5) * r.width / 8, clientY: r.top + (y + 0.5) * r.height / 8 };
    };
    const klick = (p) => {
      const opt = Object.assign({ bubbles: true, cancelable: true, composed: true, pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1 }, p);
      brett.dispatchEvent(new PointerEvent('pointerdown', opt));
      brett.dispatchEvent(new MouseEvent('mousedown', opt));
      brett.dispatchEvent(new PointerEvent('pointerup', Object.assign({}, opt, { buttons: 0 })));
      brett.dispatchEvent(new MouseEvent('mouseup', Object.assign({}, opt, { buttons: 0 })));
    };
    klick(punkt(von));
    setTimeout(() => klick(punkt(nach)), 120);
  }

  // ---------- Hauptschleife ----------

  function takt() {
    const s = finde();
    if (!s) {
      if (zustand.game) {
        zustand.game = null;
        zustand.anzahl = -1;
        phase = 'warten';
        A.setPartie('Keine Partie offen');
        hoeren();
      }
      aktualisiereUhren(null);
      return;
    }
    const anzahl = historienLaenge(s.g);
    if (anzahl < 0) return;
    if (s.g !== zustand.game || anzahl < zustand.anzahl || spieltAls(s.g) !== zustand.spieltAls) {
      neuePartie(s, anzahl);
    } else if (anzahl > zustand.anzahl) {
      zustand.anzahl = anzahl;
      neuerZug(s);
    }
    let vorbei = false;
    try { vorbei = s.g.isGameOver(); } catch (e) { /* egal */ }
    if (vorbei && !zustand.vorbei) partieEnde(s);
    if (!vorbei && zustand.vorbei) { zustand.vorbei = false; naechsterSchritt(); }
    aktualisiereUhren(s);
  }

  function aktivieren() {
    if (aktiviert) return;
    aktiviert = true;
    A.zeigeInfo('Bereit', 'Los geht\'s!', 'Starte auf chess.com eine Partie gegen einen Bot, online oder gegen Freunde.');
    folge(async () => {
      await sage('Brettstimme ist bereit.');
      const s = finde();
      if (s) await begruessung(s, historienLaenge(s.g) === 0);
      else naechsterSchritt();
    });
  }

  A.baue({
    onStart: aktivieren,
    onOeffnen: () => { if (!aktiviert) A.zeigeStart(); },
    onJa: () => {
      if (!aktiviert) return aktivieren();
      if (phase === 'bestaetigen') ausfuehren();
    },
    onNein: () => { if (phase === 'bestaetigen' || phase === 'auswahl') abgelehnt(); },
    onOption: (i) => { if (phase === 'auswahl' && offeneOptionen && offeneOptionen[i]) kandidat(offeneOptionen[i]); },
    onWiederholen: wiederholen,
    onMikro: () => { mikroPausiert = !mikroPausiert; hoeren(); },
    onProbe: () => S.sprich('Springer von B 1 auf D 2. Schach!', sprechOptionen(1)),
    onTipp: (text) => {
      if (phase === 'bestaetigen' && (P.istJa(text) || P.istNein(text))) return P.istJa(text) ? ausfuehren() : abgelehnt();
      const s = finde();
      if (!s || !binDran(s.g)) return A.setMikro('fehler', 'Du bist gerade nicht am Zug', text);
      if (!versucheZug([text], true)) A.setMikro('fehler', 'Zug nicht erkannt oder nicht erlaubt', text);
    },
    onEinstellung: (k) => {
      if (k === 'sprachEingabe') hoeren();
      if (k === 'uhr') aktualisiereUhren(finde());
    },
  });
  // Zum Testen ohne Mikrofon:  Brettstimme.hoere('Springer auf f3')
  // (TV-Jarvis schickt hier die Erkennung vom Handy, auch mehrere Varianten)
  root.Brettstimme.hoere = (text) => verarbeiteGehoertes((Array.isArray(text) ? text : [text]).filter(Boolean));
  // Fernsteuerung durch TV-Jarvis (Knoepfe auf dem Handy)
  root.Brettstimme.steuer = {
    aktivieren,
    tippe: (text) => {
      if (phase === 'bestaetigen' && (P.istJa(text) || P.istNein(text))) return P.istJa(text) ? ausfuehren() : abgelehnt();
      versucheZug([text], false);
    },
    ja: () => { if (phase === 'bestaetigen') ausfuehren(); },
    nein: () => { if (phase === 'bestaetigen' || phase === 'auswahl') abgelehnt(); },
    option: (i) => { if (phase === 'auswahl' && offeneOptionen && offeneOptionen[i]) kandidat(offeneOptionen[i]); },
    wiederholen,
    status: meldeStatus,
  };
  A.zeigeStart();
  A.setMikro('aus', 'Mikrofon aus');
  setInterval(takt, 250);
  takt();
})(window);
