/*
 * Brettstimme – große Vollbild-Anzeige über chess.com
 */
(function (root) {
  'use strict';

  const P = root.Brettstimme.parser;
  const SPEICHER = 'brettstimme-einstellungen';
  const STANDARD = {
    uhr: true, minibrett: true, ansageMal: 2, sprachEingabe: true, nachfragen: true,
    stimme: '', tempo: 1, eigenenZugAnsagen: false,
  };

  function ladeEinstellungen() {
    try {
      return Object.assign({}, STANDARD, JSON.parse(localStorage.getItem(SPEICHER) || '{}'));
    } catch (e) {
      return Object.assign({}, STANDARD);
    }
  }
  function speichereEinstellungen(e) {
    try { localStorage.setItem(SPEICHER, JSON.stringify(e)); } catch (x) { /* privat-Modus */ }
  }

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const glyph = (s) => s + '︎'; // Schachfigur als Schrift, nicht als Emoji

  const CSS = `
#bs-root{position:fixed;inset:0;z-index:2147483000;display:none;font-family:"Segoe UI Variable Display","Segoe UI",system-ui,-apple-system,"Inter",sans-serif;color:#12141c;-webkit-font-smoothing:antialiased;overflow:hidden;
  --tinte:#12141c;--grau:#6b7184;--linie:rgba(18,20,28,.08);--karte:rgba(255,255,255,.62);--akzent:#3a6df0;--akzent2:#f0a23a;--gut:#1f9d6b;--schlecht:#e5484d}
#bs-root.offen{display:block}
:where(#bs-root) *{box-sizing:border-box}
:where(#bs-root) button{font:inherit;color:inherit;cursor:pointer}
.bs-bg{position:absolute;inset:0;background:#f6f7fb;overflow:hidden}
.bs-bg::before{content:"";position:absolute;inset:-50%;background:conic-gradient(from 0deg at 50% 50%,#ffffff 0deg,#eef2fb 90deg,#ffffff 180deg,#f5f0fa 270deg,#ffffff 360deg);animation:bs-dreh 60s linear infinite;opacity:.9}
.bs-bg::after{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(18,20,28,.07) 1px,transparent 1.4px);background-size:26px 26px;-webkit-mask-image:radial-gradient(ellipse at 50% 45%,#000 0%,transparent 75%);mask-image:radial-gradient(ellipse at 50% 45%,#000 0%,transparent 75%)}
.bs-blob{position:absolute;border-radius:50%;filter:blur(70px);opacity:.75;will-change:transform}
.bs-blob.b1{width:52vmax;height:52vmax;left:-12vmax;top:-18vmax;background:radial-gradient(circle,#dfe6ff 0%,transparent 70%);animation:bs-schweb1 26s ease-in-out infinite alternate}
.bs-blob.b2{width:46vmax;height:46vmax;right:-14vmax;top:8vmax;background:radial-gradient(circle,#ffe3ee 0%,transparent 70%);animation:bs-schweb2 31s ease-in-out infinite alternate}
.bs-blob.b3{width:50vmax;height:50vmax;left:18vmax;bottom:-26vmax;background:radial-gradient(circle,#dcf7ec 0%,transparent 70%);animation:bs-schweb3 23s ease-in-out infinite alternate}
.bs-blob.b4{width:30vmax;height:30vmax;right:20vmax;bottom:-6vmax;background:radial-gradient(circle,#fff1d6 0%,transparent 70%);animation:bs-schweb1 37s ease-in-out infinite alternate-reverse}
.bs-welle{position:absolute;left:50%;top:46%;width:20vmin;height:20vmin;margin:-10vmin 0 0 -10vmin;border-radius:50%;border:2px solid rgba(58,109,240,.35);opacity:0;pointer-events:none}
.bs-welle.los{animation:bs-welle 1.6s cubic-bezier(.2,.7,.2,1) forwards}
@keyframes bs-dreh{to{transform:rotate(360deg)}}
@keyframes bs-schweb1{to{transform:translate(14vmax,10vmax) scale(1.15)}}
@keyframes bs-schweb2{to{transform:translate(-12vmax,8vmax) scale(.9)}}
@keyframes bs-schweb3{to{transform:translate(-10vmax,-12vmax) scale(1.1)}}
@keyframes bs-welle{0%{opacity:.9;transform:scale(.4)}100%{opacity:0;transform:scale(6)}}
@keyframes bs-rein{0%{opacity:0;transform:translateY(18px) scale(.97)}100%{opacity:1;transform:none}}
@keyframes bs-puls{0%,100%{box-shadow:0 0 0 0 rgba(229,72,77,.45)}50%{box-shadow:0 0 0 14px rgba(229,72,77,0)}}
@keyframes bs-atmen{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.35);opacity:.55}}
.bs-app{position:relative;height:100%;display:grid;grid-template-rows:auto 1fr auto;padding:clamp(14px,2.4vh,28px) clamp(16px,3vw,40px);gap:clamp(10px,2vh,24px)}
.bs-kopf{display:flex;align-items:center;gap:14px}
.bs-logo{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:-.01em;font-size:18px}
.bs-logo i{font-style:normal;font-size:26px;line-height:1;font-family:"Segoe UI Symbol","Noto Sans Symbols 2",serif}
.bs-partie{color:var(--grau);font-size:15px;padding:6px 12px;border-radius:999px;background:var(--karte);border:1px solid var(--linie);backdrop-filter:blur(8px)}
.bs-kopf .bs-luft{flex:1}
.bs-knopf-rund{width:42px;height:42px;border-radius:50%;border:1px solid var(--linie);background:var(--karte);backdrop-filter:blur(8px);display:grid;place-items:center;font-size:18px;transition:transform .15s,background .15s}
.bs-knopf-rund:hover{background:#fff;transform:translateY(-1px)}
.bs-mitte{display:grid;grid-template-columns:1fr auto;gap:clamp(16px,3vw,48px);min-height:0;align-items:center}
.bs-mitte.ohne-seite{grid-template-columns:1fr}
.bs-buehne{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;min-width:0;min-height:0}
.bs-buehne>.bs-inhalt{animation:bs-rein .45s cubic-bezier(.2,.7,.2,1)}
.bs-etikett{font-size:clamp(13px,1.6vh,17px);font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:var(--grau);margin-bottom:clamp(6px,1.4vh,16px)}
.bs-etikett.dein{color:var(--akzent)}
.bs-figurzeile{display:flex;align-items:center;justify-content:center;gap:.3em;font-size:clamp(34px,7vh,84px);font-weight:650;letter-spacing:-.02em;line-height:1}
.bs-symbol{font-family:"Segoe UI Symbol","Noto Sans Symbols 2","DejaVu Sans",serif;font-weight:400;font-size:1.25em}
.bs-feld{font-size:clamp(110px,30vh,380px);font-weight:800;letter-spacing:-.05em;line-height:.92;font-variant-numeric:tabular-nums;background:linear-gradient(180deg,#12141c 0%,#3a3f55 100%);-webkit-background-clip:text;background-clip:text;color:transparent;padding:0 .04em}
.bs-feld.mittel{font-size:clamp(64px,15vh,190px)}
.bs-von{font-size:clamp(26px,5vh,58px);color:var(--grau);font-weight:600;margin-top:clamp(4px,1vh,12px)}
.bs-von b{color:var(--tinte)}
.bs-chips{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-top:clamp(10px,2.4vh,28px)}
.bs-chip{font-size:clamp(16px,2.4vh,26px);font-weight:650;padding:.35em .9em;border-radius:999px;background:#fff;border:1px solid var(--linie);box-shadow:0 6px 20px rgba(18,20,28,.06)}
.bs-chip.warn{background:var(--schlecht);color:#fff;border-color:transparent}
.bs-chip.info{background:var(--tinte);color:#fff;border-color:transparent}
.bs-text{font-size:clamp(22px,4vh,46px);font-weight:650;letter-spacing:-.01em;max-width:22ch}
.bs-klein{font-size:clamp(15px,2vh,20px);color:var(--grau);margin-top:12px;max-width:52ch;line-height:1.45}
.bs-knoepfe{display:flex;flex-wrap:wrap;gap:16px;justify-content:center;margin-top:clamp(16px,3.4vh,40px)}
.bs-gross{font-size:clamp(20px,3vh,32px);font-weight:700;padding:.6em 1.4em;border-radius:20px;border:1px solid var(--linie);background:#fff;box-shadow:0 10px 30px rgba(18,20,28,.08);transition:transform .15s,box-shadow .15s;display:inline-flex;gap:.5em;align-items:center}
.bs-gross:hover{transform:translateY(-2px);box-shadow:0 14px 34px rgba(18,20,28,.12)}
.bs-gross.ja{background:var(--gut);color:#fff;border-color:transparent}
.bs-gross.haupt{background:var(--tinte);color:#fff;border-color:transparent}
.bs-gross kbd{font:inherit;font-size:.55em;opacity:.7;border:1px solid currentColor;border-radius:6px;padding:.05em .4em}
.bs-seite{display:flex;flex-direction:column;gap:clamp(10px,2vh,22px);align-items:stretch;width:clamp(220px,26vw,360px)}
.bs-uhr{border-radius:22px;padding:clamp(10px,1.6vh,18px) 20px;background:var(--karte);border:1px solid var(--linie);backdrop-filter:blur(10px);transition:background .3s,color .3s,transform .3s}
.bs-uhr .wer{font-size:13px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;opacity:.65}
.bs-uhr .zeit{font-size:clamp(36px,7vh,72px);font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.03em;line-height:1.05}
.bs-uhr.amzug{background:var(--tinte);color:#fff;transform:scale(1.02)}
.bs-uhr.knapp{color:#fff;background:var(--schlecht);animation:bs-puls 1s infinite}
.bs-uhr[hidden],.bs-brett[hidden]{display:none}
.bs-brett{display:grid;grid-template-columns:repeat(8,1fr);aspect-ratio:1;border-radius:16px;overflow:hidden;border:1px solid var(--linie);box-shadow:0 12px 36px rgba(18,20,28,.08);background:#fff}
.bs-brett div{display:grid;place-items:center;font-family:"Segoe UI Symbol","Noto Sans Symbols 2","DejaVu Sans",serif;font-size:clamp(16px,2.6vw,34px);line-height:1;position:relative}
.bs-brett .h{background:#f1f3f8}.bs-brett .d{background:#d9dfeb}
.bs-brett .von{background:#c7d6ff}.bs-brett .nach{background:#ffd89a}
.bs-brett .w{color:#fff;-webkit-text-stroke:1.2px #12141c;paint-order:stroke fill;text-shadow:0 1px 2px rgba(0,0,0,.25)}
.bs-brett .s{color:#12141c}
.bs-fuss{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.bs-mikro{display:flex;align-items:center;gap:12px;flex:1;min-width:240px;padding:12px 18px;border-radius:18px;background:var(--karte);border:1px solid var(--linie);backdrop-filter:blur(10px);font-size:17px}
.bs-punkt{width:12px;height:12px;border-radius:50%;background:#b8bdcc;flex:none}
.bs-mikro.hoert .bs-punkt{background:var(--schlecht);animation:bs-atmen 1.4s infinite}
.bs-mikro.fehler .bs-punkt{background:var(--akzent2)}
.bs-mikro .gehoert{color:var(--grau);font-style:italic;margin-left:auto;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:45%}
.bs-eingabe{display:flex;gap:8px}
.bs-eingabe input{font:inherit;font-size:17px;padding:12px 16px;border-radius:14px;border:1px solid var(--linie);background:rgba(255,255,255,.85);width:min(220px,40vw);outline:none}
.bs-eingabe input:focus{border-color:var(--akzent);box-shadow:0 0 0 3px rgba(58,109,240,.15)}
.bs-eingabe button{padding:0 16px;border-radius:14px;border:1px solid var(--linie);background:#fff;font-weight:650}
.bs-tasten{font-size:13px;color:var(--grau)}
.bs-dialog{position:absolute;inset:0;display:none;place-items:center;background:rgba(246,247,251,.55);backdrop-filter:blur(6px);z-index:5}
.bs-dialog.offen{display:grid}
.bs-karte{width:min(520px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;background:#fff;border-radius:24px;padding:24px;box-shadow:0 30px 80px rgba(18,20,28,.18);border:1px solid var(--linie)}
.bs-karte h2{margin:0 0 14px;font-size:22px}
.bs-zeile{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 0;border-top:1px solid var(--linie);font-size:16px}
.bs-zeile small{display:block;color:var(--grau);font-size:13px}
.bs-zeile select,.bs-zeile input[type=range]{font:inherit;max-width:220px}
.bs-schalter{appearance:none;-webkit-appearance:none;width:46px;height:28px;border-radius:999px;background:#d5d9e4;position:relative;cursor:pointer;flex:none;transition:background .2s}
.bs-schalter::after{content:"";position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.25);transition:transform .2s}
.bs-schalter:checked{background:var(--akzent)}.bs-schalter:checked::after{transform:translateX(18px)}
#bs-starter{position:fixed;left:16px;bottom:16px;z-index:2147482999;display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:999px;border:1px solid rgba(0,0,0,.1);background:#fff;color:#12141c;font:600 15px "Segoe UI",system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.25);cursor:pointer}
#bs-starter .bs-punkt{width:10px;height:10px}
#bs-starter.hoert .bs-punkt{background:#e5484d;animation:bs-atmen 1.4s infinite}
@media (max-width:820px){.bs-mitte{grid-template-columns:1fr;align-content:center}.bs-seite{width:100%;flex-direction:row;flex-wrap:wrap}.bs-seite .bs-uhr{flex:1}.bs-brett{display:none}.bs-tasten{display:none}}
`;

  let el = {};
  let cb = {};
  let einstellungen = ladeEinstellungen();
  let letzteBrettDaten = null;

  function baue(callbacks) {
    cb = callbacks || {};
    const stil = document.createElement('style');
    stil.id = 'bs-stil';
    stil.textContent = CSS;
    document.head.appendChild(stil);

    const starter = document.createElement('button');
    starter.id = 'bs-starter';
    starter.title = 'Brettstimme öffnen (Alt+B)';
    starter.innerHTML = '<span class="bs-punkt"></span><span>♞︎ Brettmodus</span>';
    starter.addEventListener('click', () => oeffnen());
    document.body.appendChild(starter);

    const r = document.createElement('div');
    r.id = 'bs-root';
    r.innerHTML = `
      <div class="bs-bg"><div class="bs-blob b1"></div><div class="bs-blob b2"></div><div class="bs-blob b3"></div><div class="bs-blob b4"></div><div class="bs-welle"></div></div>
      <div class="bs-app">
        <div class="bs-kopf">
          <div class="bs-logo"><i>${glyph('♞')}</i>Brettstimme</div>
          <div class="bs-partie">Warte auf eine Partie …</div>
          <div class="bs-luft"></div>
          <button class="bs-knopf-rund" data-a="wiederholen" title="Letzten Zug wiederholen (R)">↻</button>
          <button class="bs-knopf-rund" data-a="mikro" title="Mikrofon an/aus (M)">🎙︎</button>
          <button class="bs-knopf-rund" data-a="einstellungen" title="Einstellungen">⚙︎</button>
          <button class="bs-knopf-rund" data-a="schliessen" title="Zu chess.com wechseln (Alt+B)">✕</button>
        </div>
        <div class="bs-mitte">
          <div class="bs-buehne"></div>
          <div class="bs-seite">
            <div class="bs-uhr oben"><div class="wer">Gegner</div><div class="zeit">–:––</div></div>
            <div class="bs-brett"></div>
            <div class="bs-uhr unten"><div class="wer">Du</div><div class="zeit">–:––</div></div>
          </div>
        </div>
        <div class="bs-fuss">
          <div class="bs-mikro"><span class="bs-punkt"></span><span class="status">Mikrofon aus</span><span class="gehoert"></span></div>
          <form class="bs-eingabe" autocomplete="off"><input placeholder="Zug tippen, z.B. Sf3" aria-label="Zug tippen"><button type="submit">Ziehen</button></form>
          <div class="bs-tasten">Enter = Ja · Esc = Nein · R = wiederholen · Alt+B = umschalten</div>
        </div>
      </div>
      <div class="bs-dialog"><div class="bs-karte"></div></div>`;
    document.body.appendChild(r);

    el = {
      root: r, starter,
      buehne: r.querySelector('.bs-buehne'),
      partie: r.querySelector('.bs-partie'),
      mitte: r.querySelector('.bs-mitte'),
      seite: r.querySelector('.bs-seite'),
      uhrOben: r.querySelector('.bs-uhr.oben'),
      uhrUnten: r.querySelector('.bs-uhr.unten'),
      brett: r.querySelector('.bs-brett'),
      welle: r.querySelector('.bs-welle'),
      mikro: r.querySelector('.bs-mikro'),
      mikroText: r.querySelector('.bs-mikro .status'),
      gehoert: r.querySelector('.bs-mikro .gehoert'),
      form: r.querySelector('.bs-eingabe'),
      input: r.querySelector('.bs-eingabe input'),
      dialog: r.querySelector('.bs-dialog'),
      karte: r.querySelector('.bs-karte'),
    };

    r.addEventListener('click', (e) => {
      const b = e.target.closest('[data-a]');
      if (!b) return;
      const a = b.getAttribute('data-a');
      if (a === 'schliessen') schliessen();
      else if (a === 'einstellungen') zeigeEinstellungen();
      else if (a === 'dialog-zu') el.dialog.classList.remove('offen');
      else if (a === 'option') cb.onOption && cb.onOption(+b.getAttribute('data-i'));
      else if (cb['on' + a[0].toUpperCase() + a.slice(1)]) cb['on' + a[0].toUpperCase() + a.slice(1)]();
    });
    el.form.addEventListener('submit', (e) => {
      e.preventDefault();
      const t = el.input.value.trim();
      if (t && cb.onTipp) cb.onTipp(t);
      el.input.value = '';
    });

    document.addEventListener('keydown', (e) => {
      if (e.altKey && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault();
        istOffen() ? schliessen() : oeffnen();
        return;
      }
      if (!istOffen()) return;
      const imFeld = e.target === el.input || (e.target.closest && e.target.closest('.bs-karte'));
      if (e.key === 'Escape' && el.dialog.classList.contains('offen')) { el.dialog.classList.remove('offen'); return; }
      if (imFeld) return;
      if (e.key === 'Enter') { e.preventDefault(); cb.onJa && cb.onJa(); }
      else if (e.key === 'Escape') { e.preventDefault(); cb.onNein && cb.onNein(); }
      else if (e.key === 'r' || e.key === 'R') cb.onWiederholen && cb.onWiederholen();
      else if (e.key === 'm' || e.key === 'M') cb.onMikro && cb.onMikro();
      else if (/^[1-9]$/.test(e.key)) cb.onOption && cb.onOption(+e.key - 1);
    }, true);

    wendeEinstellungenAn();
  }

  function istOffen() { return el.root && el.root.classList.contains('offen'); }
  function oeffnen() {
    el.root.classList.add('offen');
    document.documentElement.style.overflow = 'hidden';
    el.starter.style.display = 'none';
    cb.onOeffnen && cb.onOeffnen();
  }
  function schliessen() {
    el.root.classList.remove('offen');
    document.documentElement.style.overflow = '';
    el.starter.style.display = '';
  }

  function welle() {
    el.welle.classList.remove('los');
    void el.welle.offsetWidth;
    el.welle.classList.add('los');
  }

  function buehne(html) {
    el.buehne.innerHTML = `<div class="bs-inhalt">${html}</div>`;
  }

  // ---------- Inhalte der Bühne ----------

  function zeigeStart(text) {
    buehne(`
      <div class="bs-etikett">Physisches Brett · chess.com</div>
      <div class="bs-figurzeile"><span class="bs-symbol">${glyph('♘')}</span></div>
      <div class="bs-text" style="margin-top:14px">Bereit zum Spielen?</div>
      <div class="bs-klein">${esc(text || 'Ein Klick gibt Ton und Mikrofon frei. Danach werden die Züge des Gegners angesagt und du sagst einfach deinen Zug – z.B. „Springer auf F3“.')}</div>
      <div class="bs-knoepfe"><button class="bs-gross haupt" data-a="start">Los geht's</button></div>`);
  }

  function zugHtml(d, etikett, etikettKlasse) {
    let haupt;
    if (d.rochade) {
      haupt = `<div class="bs-figurzeile"><span class="bs-symbol">${glyph(d.symbol)}</span></div>
               <div class="bs-feld mittel">${esc(d.titel)}</div>`;
    } else {
      haupt = `<div class="bs-figurzeile"><span class="bs-symbol">${glyph(d.symbol)}</span><span>${esc(d.figurName)}${d.schlag ? ' schlägt' : ''}</span></div>
               <div class="bs-feld">${esc(d.nach)}</div>
               ${d.zeigeVon ? `<div class="bs-von">von <b>${esc(d.von)}</b></div>` : ''}`;
    }
    const chips = d.hinweise.map((h) => {
      const art = /Schach/.test(h) ? 'warn' : /Umwandlung|En passant|Turm|König/.test(h) ? 'info' : '';
      return `<span class="bs-chip ${art}">${esc(h)}</span>`;
    }).join('');
    return `<div class="bs-etikett ${etikettKlasse || ''}">${esc(etikett)}</div>${haupt}${chips ? `<div class="bs-chips">${chips}</div>` : ''}`;
  }

  function zeigeGegnerzug(d) {
    buehne(zugHtml(d, 'Gegner zieht'));
    welle();
  }

  function zeigeEigenenZug(d, etikett) {
    buehne(zugHtml(d, etikett || 'Gespielt', 'dein'));
  }

  function zeigeBestaetigung(d, zusatz) {
    buehne(`${zugHtml(d, 'Meinst du …', 'dein')}
      ${zusatz ? `<div class="bs-klein">${esc(zusatz)}</div>` : ''}
      <div class="bs-knoepfe">
        <button class="bs-gross ja" data-a="ja">✓ Ja <kbd>Enter</kbd></button>
        <button class="bs-gross" data-a="nein">✕ Nein <kbd>Esc</kbd></button>
      </div>`);
  }

  function zeigeAuswahl(titel, optionen) {
    buehne(`<div class="bs-etikett dein">Rückfrage</div>
      <div class="bs-text">${esc(titel)}</div>
      <div class="bs-knoepfe">${optionen.map((o, i) =>
        `<button class="bs-gross" data-a="option" data-i="${i}"><span class="bs-symbol">${glyph(o.symbol)}</span>${esc(o.text)} <kbd>${i + 1}</kbd></button>`).join('')}
        <button class="bs-gross" data-a="nein">Abbrechen <kbd>Esc</kbd></button>
      </div>`);
  }

  function zeigeInfo(etikett, text, klein, mitDeinKlasse) {
    buehne(`<div class="bs-etikett ${mitDeinKlasse ? 'dein' : ''}">${esc(etikett)}</div>
      <div class="bs-text">${esc(text)}</div>
      ${klein ? `<div class="bs-klein">${esc(klein)}</div>` : ''}`);
  }

  // ---------- Seitenleiste ----------

  function setPartie(text) {
    el.partie.textContent = text;
  }

  function setUhren(u) {
    const zeigen = einstellungen.uhr && u && (u.oben || u.unten);
    el.uhrOben.hidden = !zeigen;
    el.uhrUnten.hidden = !zeigen;
    if (zeigen) {
      el.uhrOben.querySelector('.zeit').textContent = u.oben || '–:––';
      el.uhrUnten.querySelector('.zeit').textContent = u.unten || '–:––';
      el.uhrOben.classList.toggle('amzug', u.amZug === 'oben');
      el.uhrUnten.classList.toggle('amzug', u.amZug === 'unten');
      el.uhrOben.classList.toggle('knapp', u.amZug === 'oben' && istKnapp(u.oben));
      el.uhrUnten.classList.toggle('knapp', u.amZug === 'unten' && istKnapp(u.unten));
    }
    seitenleisteSichtbar();
  }

  function istKnapp(zeit) {
    if (!zeit) return false;
    const teile = zeit.split(':').map(parseFloat);
    const sek = teile.length === 1 ? teile[0] : teile.length === 2 ? teile[0] * 60 + teile[1] : teile[0] * 3600 + teile[1] * 60 + teile[2];
    return sek < 20;
  }

  function zeigeBrett(fen, von, nach, spieltAls) {
    letzteBrettDaten = [fen, von, nach, spieltAls];
    el.brett.hidden = !einstellungen.minibrett || !fen;
    if (el.brett.hidden) return seitenleisteSichtbar();
    const brett = P.brettAusFen(fen);
    const schwarz = spieltAls === 'b';
    let html = '';
    for (let z = 0; z < 8; z++) {
      for (let s = 0; s < 8; s++) {
        const zeile = schwarz ? 7 - z : z;
        const spalte = schwarz ? 7 - s : s;
        const feld = String.fromCharCode(97 + spalte) + (8 - zeile);
        const f = brett[zeile] && brett[zeile][spalte];
        const klasse = [(zeile + spalte) % 2 ? 'd' : 'h', feld === von ? 'von' : '', feld === nach ? 'nach' : ''].join(' ');
        let fig = '';
        if (f) {
          const farbe = f === f.toUpperCase() ? 'w' : 'b';
          fig = `<span class="${farbe === 'w' ? 'w' : 's'}">${glyph(P.SYMBOL.b[f.toLowerCase()])}</span>`;
        }
        html += `<div class="${klasse}">${fig}</div>`;
      }
    }
    el.brett.innerHTML = html;
    seitenleisteSichtbar();
  }

  function seitenleisteSichtbar() {
    const leer = el.uhrOben.hidden && el.brett.hidden;
    el.seite.style.display = leer ? 'none' : '';
    el.mitte.classList.toggle('ohne-seite', leer);
  }

  function setMikro(zustand, text, gehoert) {
    el.mikro.classList.toggle('hoert', zustand === 'hoert');
    el.mikro.classList.toggle('fehler', zustand === 'fehler');
    el.starter.classList.toggle('hoert', zustand === 'hoert');
    if (text != null) el.mikroText.textContent = text;
    if (gehoert != null) el.gehoert.textContent = gehoert ? `„${gehoert}“` : '';
  }

  // ---------- Einstellungen ----------

  function zeigeEinstellungen() {
    const st = root.Brettstimme.stimme;
    const stimmen = st.ladeStimmen();
    const e = einstellungen;
    const schalter = (k, titel, info) => `<label class="bs-zeile"><span>${titel}${info ? `<small>${info}</small>` : ''}</span><input type="checkbox" class="bs-schalter" data-k="${k}" ${e[k] ? 'checked' : ''}></label>`;
    el.karte.innerHTML = `
      <h2>Einstellungen</h2>
      ${schalter('uhr', 'Zeit anzeigen', 'Uhren aus der chess.com-Partie')}
      ${schalter('minibrett', 'Mini-Brett anzeigen', 'Zeigt den letzten Zug als Markierung')}
      ${schalter('sprachEingabe', 'Spracheingabe', 'Deinen Zug per Mikrofon sagen')}
      ${schalter('nachfragen', 'Vor dem Ziehen nachfragen', '„Meinst du Springer auf F3?“')}
      ${schalter('eigenenZugAnsagen', 'Eigenen Zug nochmal ansagen', 'Nach dem Ziehen kurze Bestätigung')}
      <label class="bs-zeile"><span>Ansage wie oft</span>
        <select data-k="ansageMal">${[1, 2, 3].map((n) => `<option value="${n}" ${+e.ansageMal === n ? 'selected' : ''}>${n}×</option>`).join('')}</select></label>
      <label class="bs-zeile"><span>Stimme<small>${stimmen.length ? stimmen.length + ' deutsche Stimmen gefunden' : 'Keine deutsche Stimme gefunden'}</small></span>
        <select data-k="stimme"><option value="">Automatisch</option>${stimmen.map((v) => `<option ${v.name === e.stimme ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></label>
      <label class="bs-zeile"><span>Sprechtempo</span><input type="range" min="0.6" max="1.4" step="0.05" value="${e.tempo}" data-k="tempo"></label>
      <div class="bs-knoepfe" style="margin-top:16px">
        <button class="bs-gross" data-a="probe">Stimme testen</button>
        <button class="bs-gross haupt" data-a="dialog-zu">Fertig</button>
      </div>`;
    el.karte.querySelectorAll('[data-k]').forEach((inp) => {
      inp.addEventListener('change', () => {
        const k = inp.getAttribute('data-k');
        let v = inp.type === 'checkbox' ? inp.checked : inp.value;
        if (k === 'ansageMal' || k === 'tempo') v = +v;
        einstellungen[k] = v;
        speichereEinstellungen(einstellungen);
        wendeEinstellungenAn();
        cb.onEinstellung && cb.onEinstellung(k, v);
      });
    });
    el.dialog.classList.add('offen');
  }

  function wendeEinstellungenAn() {
    if (!einstellungen.uhr) { el.uhrOben.hidden = true; el.uhrUnten.hidden = true; }
    if (letzteBrettDaten) zeigeBrett.apply(null, letzteBrettDaten);
    else { el.brett.hidden = true; seitenleisteSichtbar(); }
  }

  root.Brettstimme.anzeige = {
    baue, oeffnen, schliessen, istOffen,
    zeigeStart, zeigeGegnerzug, zeigeEigenenZug, zeigeBestaetigung, zeigeAuswahl, zeigeInfo,
    setPartie, setUhren, zeigeBrett, setMikro,
    get einstellungen() { return einstellungen; },
  };
})(window);
