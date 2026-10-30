/*
 * Brettstimme – Zug-Logik (ohne DOM, auch mit Node testbar)
 *  - beschreibt Züge auf Deutsch ("Springer von B1 auf D2")
 *  - versteht gesprochene/getippte Züge ("Springer auf f3", "e4", "kurze Rochade", "Sf3")
 */
(function (root) {
  'use strict';

  const FIGUR = { k: 'König', q: 'Dame', r: 'Turm', b: 'Läufer', n: 'Springer', p: 'Bauer' };
  const FIGUR_ART = { k: 'r', q: '', r: 'r', b: 'r', n: 'r', p: 'r' }; // welche-r / welche
  const SYMBOL = {
    w: { k: '♔', q: '♕', r: '♖', b: '♗', n: '♘', p: '♙' },
    b: { k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' },
  };
  const SAN_DEUTSCH = { N: 'S', B: 'L', R: 'T', Q: 'D', K: 'K' };

  // ---------- Wörter, die die Spracherkennung liefern kann ----------
  const FIGUR_WORTE = {
    koenig: 'k', konig: 'k', king: 'k',
    dame: 'q', damen: 'q', koenigin: 'q', queen: 'q',
    turm: 'r', tuerme: 'r', turn: 'r', rook: 'r',
    laeufer: 'b', laufer: 'b', leufer: 'b', bishop: 'b',
    springer: 'n', pferd: 'n', pferdchen: 'n', roessel: 'n', roessl: 'n', roesslein: 'n', knight: 'n',
    bauer: 'p', bauern: 'p', pawn: 'p',
  };
  const LINIE_WORTE = {
    a: 'a', ah: 'a',
    b: 'b', be: 'b', bee: 'b', beh: 'b',
    c: 'c', ce: 'c', ze: 'c', zeh: 'c', cee: 'c', tse: 'c', see: 'c',
    d: 'd', de: 'd', dee: 'd', deh: 'd',
    e: 'e', eh: 'e', ee: 'e',
    f: 'f', ef: 'f', eff: 'f',
    g: 'g', ge: 'g', geh: 'g', gee: 'g',
    h: 'h', ha: 'h', hah: 'h',
  };
  const REIHE_WORTE = {
    1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8',
    eins: '1', ein: '1', eine: '1', zwei: '2', zwo: '2', drei: '3', vier: '4',
    fuenf: '5', funf: '5', sechs: '6', sieben: '7', acht: '8',
  };
  const NUR_NACH_LINIE = new Set(['ein', 'eine']); // als Artikel zu häufig
  const JA = new Set(['ja', 'jawohl', 'jap', 'jep', 'jo', 'joa', 'genau', 'richtig', 'korrekt', 'ok', 'okay', 'passt',
    'stimmt', 'yes', 'yeah', 'bestaetigt', 'bestaetigen', 'klar', 'sicher', 'gerne', 'mach', 'spielen', 'spiel', 'jawoll']);
  const NEIN = new Set(['nein', 'nee', 'ne', 'noe', 'nicht', 'falsch', 'abbrechen', 'zurueck', 'stopp', 'stop', 'no', 'nope', 'anders']);
  const KURZ = new Set(['kurz', 'kurze', 'kurzen', 'kurzer', 'kleine', 'kleinen', 'kleiner', 'koenigsseite', 'short', 'kingside']);
  const LANG = new Set(['lang', 'lange', 'langen', 'langer', 'grosse', 'grossen', 'grosser', 'damenseite', 'long', 'queenside']);
  const ORDINAL = { erste: 0, ersten: 0, erster: 0, erstes: 0, zweite: 1, zweiten: 1, zweiter: 1, zweites: 1, dritte: 2, dritten: 2, dritter: 2 };

  function normalisiere(text) {
    return String(text || '').toLowerCase()
      .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');
  }

  function woerter(text) {
    return normalisiere(text).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean);
  }

  /** Zerlegt einen Satz in Figuren, Felder, einzelne Linien/Reihen und Rochade-Wünsche. */
  function analysiere(text) {
    const roh = normalisiere(text);
    const w = woerter(text);
    const a = { figuren: [], felder: [], linien: [], reihen: [], rochade: null, promo: null, woerter: w };

    if (/\b[o0]-[o0]-[o0]\b/.test(roh)) a.rochade = 'lang';
    else if (/\b[o0]-[o0]\b/.test(roh)) a.rochade = 'kurz';

    for (let i = 0; i < w.length; i++) {
      const t = w[i];
      let m;
      if (FIGUR_WORTE[t]) {
        a.figuren.push({ p: FIGUR_WORTE[t], i });
      } else if ((m = /^([a-h][1-8])([a-h][1-8])([qrbn])?$/.exec(t))) {
        a.felder.push({ feld: m[1], i }, { feld: m[2], i });
        if (m[3]) a.promo = m[3];
      } else if (/^[a-h][1-8]$/.test(t)) {
        a.felder.push({ feld: t, i });
      } else if (LINIE_WORTE[t] !== undefined) {
        const naechstes = w[i + 1];
        if (naechstes !== undefined && REIHE_WORTE[naechstes] !== undefined) {
          a.felder.push({ feld: LINIE_WORTE[t] + REIHE_WORTE[naechstes], i });
          i++;
        } else {
          a.linien.push({ linie: LINIE_WORTE[t], i });
        }
      } else if (REIHE_WORTE[t] !== undefined && !NUR_NACH_LINIE.has(t)) {
        a.reihen.push({ reihe: REIHE_WORTE[t], i });
      } else if (t === 'rochade' || t === 'rochiert' || t === 'rochieren' || t === 'castle' || t === 'castles') {
        a.rochade = a.rochade || 'egal';
      }
      if (KURZ.has(t) && a.rochade) a.rochade = 'kurz';
      if (LANG.has(t) && a.rochade) a.rochade = 'lang';
    }
    // "kurze Rochade": Adjektiv kommt vor dem Wort Rochade
    if (a.rochade === 'egal') {
      if (w.some((t) => KURZ.has(t))) a.rochade = 'kurz';
      else if (w.some((t) => LANG.has(t))) a.rochade = 'lang';
    }
    return a;
  }

  function sanOhneZeichen(san) {
    return String(san).replace(/[+#!?]/g, '');
  }

  function umwandlung(zug) {
    if (zug.promotion) return String(zug.promotion).toLowerCase();
    const m = /=([QRBN])/i.exec(zug.san || '');
    return m ? m[1].toLowerCase() : null;
  }

  function sanDeutsch(san) {
    return sanOhneZeichen(san).replace(/^[NBRQK]/, (c) => SAN_DEUTSCH[c]).replace(/=([NBRQ])/, (_, c) => '=' + SAN_DEUTSCH[c]);
  }

  /** Probiert, ob der Text direkt Schachnotation ist (Sf3, Nf3, exd5, O-O, e8=D). */
  function alsNotation(text, legal) {
    const t = String(text || '').trim().replace(/\s+/g, '').replace(/[+#!?.]/g, '');
    if (!t || t.length > 9) return [];
    // lange Notation: Sf3xe5, Ng1-f3, e7e8=D
    const lang = /^[KQRBNSLTD]?([a-h][1-8])[-x:]?([a-h][1-8])=?([QRBNDTLS])?$/i.exec(t);
    if (lang) {
      const promo = lang[3] ? { D: 'q', T: 'r', L: 'b', S: 'n' }[lang[3].toUpperCase()] || lang[3].toLowerCase() : null;
      return legal.filter((z) => z.from === lang[1].toLowerCase() && z.to === lang[2].toLowerCase() &&
        (!umwandlung(z) || umwandlung(z) === (promo || 'q')));
    }
    const ohneX = (s) => s.replace(/x/g, '').replace(/:/g, '');
    const genau = legal.filter((z) => {
      const en = sanOhneZeichen(z.san);
      const de = sanDeutsch(z.san);
      return [en, de, ohneX(en), ohneX(de)].includes(t) || [en, de].map(ohneX).includes(ohneX(t));
    });
    if (genau.length) return genau;
    const klein = ohneX(t.toLowerCase());
    return legal.filter((z) => ohneX(sanOhneZeichen(z.san).toLowerCase()) === klein || ohneX(sanDeutsch(z.san).toLowerCase()) === klein);
  }

  function weicherFilter(liste, pred) {
    const r = liste.filter(pred);
    return r.length ? r : liste;
  }

  function eindeutig(liste) {
    const gesehen = new Set();
    return liste.filter((z) => {
      const k = z.from + z.to + (umwandlung(z) || '');
      if (gesehen.has(k)) return false;
      gesehen.add(k);
      return true;
    });
  }

  /**
   * Findet zu einem gesprochenen/getippten Text die passenden legalen Züge.
   * @returns {{status:'ok'|'mehrdeutig'|'unbekannt', zuege:Array, dameAngenommen?:boolean}}
   */
  function findeZug(text, legal) {
    legal = legal || [];
    const notation = eindeutig(alsNotation(text, legal));
    if (notation.length === 1) return { status: 'ok', zuege: notation };
    if (notation.length > 1) return { status: 'mehrdeutig', zuege: notation };

    const a = analysiere(text);
    let kandidaten = [];
    let dameAngenommen = false;

    if (a.rochade && a.felder.length === 0) {
      kandidaten = legal.filter((z) => /^O-O/.test(z.san));
      if (a.rochade === 'kurz') kandidaten = kandidaten.filter((z) => sanOhneZeichen(z.san) === 'O-O');
      if (a.rochade === 'lang') kandidaten = kandidaten.filter((z) => sanOhneZeichen(z.san) === 'O-O-O');
    } else if (a.felder.length) {
      const ziel = a.felder[a.felder.length - 1];
      const start = a.felder.length >= 2 ? a.felder[a.felder.length - 2] : null;
      const figurVorher = a.figuren.find((f) => f.i < (start ? start.i : ziel.i));
      const figurNachher = a.figuren.filter((f) => f.i > ziel.i).pop();
      const figur = figurVorher ? figurVorher.p : null;

      kandidaten = legal.filter((z) => z.to === ziel.feld);
      if (start) kandidaten = kandidaten.filter((z) => z.from === start.feld);

      if (figur) {
        kandidaten = kandidaten.filter((z) => z.piece === figur);
      } else if (!start) {
        // "e4" ohne Figur heißt wie in der Notation: Bauernzug
        kandidaten = weicherFilter(kandidaten, (z) => z.piece === 'p');
      }

      // Hinweise zur Herkunft ("Springer b d2", "Turm 1 d1")
      if (!start) {
        a.linien.filter((l) => l.i < ziel.i).forEach((l) => {
          kandidaten = weicherFilter(kandidaten, (z) => z.from[0] === l.linie);
        });
        a.reihen.filter((r) => r.i < ziel.i).forEach((r) => {
          kandidaten = weicherFilter(kandidaten, (z) => z.from[1] === r.reihe);
        });
      }

      if (kandidaten.some((z) => umwandlung(z))) {
        let wunsch = a.promo || (figurNachher ? figurNachher.p : null);
        if (!wunsch || !'qrbn'.includes(wunsch)) {
          wunsch = 'q';
          dameAngenommen = true;
        }
        kandidaten = kandidaten.filter((z) => umwandlung(z) === wunsch);
      }
    }

    kandidaten = eindeutig(kandidaten);
    if (kandidaten.length === 1) return { status: 'ok', zuege: kandidaten, dameAngenommen };
    if (kandidaten.length > 1) return { status: 'mehrdeutig', zuege: kandidaten, dameAngenommen };
    return { status: 'unbekannt', zuege: [] };
  }

  /** Bei Nachfrage ("Welcher Springer?"): wählt aus den Optionen. */
  function waehleOption(text, optionen, spieltAls) {
    const a = analysiere(text);
    let r = optionen.slice();
    const anwenden = (pred) => {
      const neu = r.filter(pred);
      if (neu.length) r = neu;
    };
    a.felder.forEach((f) => anwenden((z) => z.from === f.feld || z.to === f.feld));
    a.linien.forEach((l) => anwenden((z) => z.from[0] === l.linie));
    a.reihen.forEach((x) => anwenden((z) => z.from[1] === x.reihe));
    a.figuren.forEach((f) => anwenden((z) => z.piece === f.p));
    if (r.length === 1 && r.length < optionen.length) return r[0];

    const ord = a.woerter.map((t) => ORDINAL[t]).find((x) => x !== undefined);
    if (ord !== undefined && optionen[ord]) return optionen[ord];

    const links = a.woerter.includes('links') || a.woerter.includes('linke') || a.woerter.includes('linken');
    const rechts = a.woerter.includes('rechts') || a.woerter.includes('rechte') || a.woerter.includes('rechten');
    if ((links || rechts) && optionen.length === 2) {
      const sortiert = optionen.slice().sort((x, y) => x.from.charCodeAt(0) - y.from.charCodeAt(0));
      if (spieltAls === 'b') sortiert.reverse();
      if (sortiert[0].from[0] !== sortiert[1].from[0]) return links ? sortiert[0] : sortiert[1];
    }
    return null;
  }

  function istJa(text) {
    const w = woerter(text);
    if (w.some((t) => NEIN.has(t))) return false;
    return w.some((t) => JA.has(t));
  }

  function istNein(text) {
    return woerter(text).some((t) => NEIN.has(t));
  }

  function istWiederholen(text) {
    const n = normalisiere(text);
    return /wiederhol|repeat|noch ?mal|was hat (er|sie|es)|letzte[nr]? zug/.test(n);
  }

  // ---------- Stellung ----------

  /** FEN -> 8x8 Array, [0] = Reihe 8, Spalte 0 = Linie a. Werte: 'P','n',... oder null */
  function brettAusFen(fen) {
    const reihen = String(fen || '').split(' ')[0].split('/');
    return reihen.map((r) => {
      const zeile = [];
      for (const c of r) {
        if (/\d/.test(c)) for (let k = 0; k < +c; k++) zeile.push(null);
        else zeile.push(c);
      }
      return zeile;
    });
  }

  function figurAuf(fen, feld) {
    const brett = brettAusFen(fen);
    const spalte = feld.charCodeAt(0) - 97;
    const zeile = 8 - +feld[1];
    return (brett[zeile] || [])[spalte] || null;
  }

  // ---------- Beschreibung eines Zuges ----------

  const F = (feld) => String(feld).toUpperCase();
  const sprichFeld = (feld) => F(feld)[0] + ' ' + feld[1];

  /**
   * @param zug   {from,to,piece,san,color}  (color 1 = Weiß, 2 = Schwarz oder 'w'/'b')
   * @param fenVorher Stellung vor dem Zug (für en passant)
   */
  function beschreibeZug(zug, fenVorher) {
    const farbe = zug.color === 2 || zug.color === 'b' ? 'b' : 'w';
    const fig = String(zug.piece || 'p').toLowerCase();
    const san = String(zug.san || '');
    const schlag = san.includes('x') || !!zug.captured;
    const schach = /\+$/.test(san);
    const matt = /#$/.test(san);
    const promo = umwandlung(zug);
    const hinweise = [];
    const d = {
      farbe, figur: fig, figurName: FIGUR[fig], symbol: SYMBOL[farbe][fig],
      von: F(zug.from), nach: F(zug.to), schlag, schach, matt, promo,
      rochade: null, enPassant: false, zeigeVon: false,
      zeile1: '', zeile2: '', hinweise, sprache: '', kurz: '',
    };

    if (/^O-O-O/.test(san) || /^O-O/.test(san)) {
      const lang = /^O-O-O/.test(san);
      const r = farbe === 'w' ? '1' : '8';
      d.rochade = lang ? 'lang' : 'kurz';
      d.figur = 'k';
      d.symbol = SYMBOL[farbe].k;
      d.zeile1 = lang ? 'Lange Rochade' : 'Kurze Rochade';
      d.zeile2 = '';
      hinweise.push(lang ? `König E${r} → C${r}` : `König E${r} → G${r}`);
      hinweise.push(lang ? `Turm A${r} → D${r}` : `Turm H${r} → F${r}`);
      d.titel = d.zeile1;
      d.sprache = d.zeile1 + '.';
    } else {
      const disamb = /^[KQRBN]([a-h]?[1-8]?)x?[a-h][1-8]/.exec(san);
      d.zeigeVon = !!(disamb && disamb[1]) || (fig === 'p' && schlag);
      d.enPassant = fig === 'p' && schlag && !!fenVorher && !figurAuf(fenVorher, zug.to);
      const verb = schlag ? 'schlägt auf' : 'auf';
      d.zeile1 = FIGUR[fig];
      d.zeile2 = F(zug.to);
      d.titel = `${FIGUR[fig]}${d.zeigeVon ? ' von ' + F(zug.from) : ''} ${verb} ${F(zug.to)}`;
      d.sprache = `${FIGUR[fig]}${d.zeigeVon ? ' von ' + sprichFeld(zug.from) : ''} ${verb} ${sprichFeld(zug.to)}.`;
      if (d.enPassant) {
        const geschlagen = zug.to[0] + zug.from[1];
        hinweise.push(`En passant – Bauer auf ${F(geschlagen)} vom Brett nehmen`);
        d.sprache += ` En passant. Bauer auf ${sprichFeld(geschlagen)} entfernen.`;
      }
      if (promo) {
        hinweise.push(`Umwandlung in ${FIGUR[promo]}`);
        d.sprache += ` Umwandlung in ${FIGUR[promo]}.`;
      }
    }
    if (matt) {
      hinweise.push('Schachmatt!');
      d.sprache += ' Schachmatt!';
    } else if (schach) {
      hinweise.push('Schach!');
      d.sprache += ' Schach!';
    }
    d.kurz = d.titel + (promo && !d.rochade ? `, Umwandlung in ${FIGUR[promo]}` : '');
    return d;
  }

  /** Frage bei mehrdeutiger Eingabe, z.B. "Welcher Springer? Der von B 1 oder der von D 2?" */
  function rueckfrage(optionen) {
    const figuren = new Set(optionen.map((z) => z.piece));
    const ziele = new Set(optionen.map((z) => z.to));
    if (figuren.size === 1 && ziele.size === 1) {
      const p = optionen[0].piece;
      const artikel = p === 'q' ? 'Die' : 'Der';
      const teile = optionen.map((z) => `${artikel.toLowerCase()} von ${sprichFeld(z.from)}`);
      const text = `Welche${FIGUR_ART[p]} ${FIGUR[p]}? ${teile.slice(0, -1).join(', ')} oder ${teile[teile.length - 1]}?`;
      return { sprache: text.charAt(0).toUpperCase() + text.slice(1).replace(/\? der/, '? Der').replace(/\? die/, '? Die'), titel: `Welche${FIGUR_ART[p]} ${FIGUR[p]}?` };
    }
    const teile = optionen.map((z) => beschreibeZug(z).sprache.replace(/\.$/, ''));
    return { sprache: `Meinst du ${teile.slice(0, -1).join(', ')} oder ${teile[teile.length - 1]}?`, titel: 'Welcher Zug?' };
  }

  const api = {
    FIGUR, SYMBOL, analysiere, findeZug, waehleOption, istJa, istNein, istWiederholen,
    brettAusFen, figurAuf, beschreibeZug, rueckfrage, sprichFeld, woerter,
  };
  root.Brettstimme = root.Brettstimme || {};
  root.Brettstimme.parser = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
