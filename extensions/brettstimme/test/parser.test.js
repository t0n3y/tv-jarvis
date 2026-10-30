// Ausführen mit:  node erweiterung/test/parser.test.js
const assert = require('assert');
const P = require('../src/parser.js');

// Legale Züge im Format, das chess.com liefert (Ausschnitt)
const z = (from, to, piece, san, extra = {}) => ({ from, to, piece, san, color: 1, ...extra });
const legal = [
  z('e2', 'e4', 'p', 'e4'), z('e2', 'e3', 'p', 'e3'), z('d2', 'd4', 'p', 'd4'),
  z('b1', 'd2', 'n', 'Nbd2'), z('f3', 'd2', 'n', 'Nfd2'), z('f3', 'e5', 'n', 'Nxe5', { captured: 'p' }),
  z('f1', 'c4', 'b', 'Bc4'), z('e1', 'g1', 'k', 'O-O'), z('e1', 'c1', 'k', 'O-O-O'),
  z('a1', 'd1', 'r', 'Rad1'), z('h1', 'd1', 'r', 'Rhd1'),
  z('g7', 'g8', 'p', 'g8=Q+'), z('g7', 'g8', 'p', 'g8=N'), z('g7', 'g8', 'p', 'g8=R'), z('g7', 'g8', 'p', 'g8=B'),
  z('d1', 'h5', 'q', 'Qh5'),
];

let n = 0;
function ok(text, from, to, promo) {
  const r = P.findeZug(text, legal);
  assert.strictEqual(r.status, 'ok', `"${text}" -> ${r.status} ${JSON.stringify(r.zuege.map((x) => x.san))}`);
  assert.strictEqual(r.zuege[0].from + r.zuege[0].to, from + to, `"${text}" -> ${r.zuege[0].san}`);
  if (promo) assert.ok(r.zuege[0].san.includes('=' + promo), `"${text}" promo ${r.zuege[0].san}`);
  n++;
}
function mehrdeutig(text, anzahl) {
  const r = P.findeZug(text, legal);
  assert.strictEqual(r.status, 'mehrdeutig', `"${text}" -> ${r.status}`);
  assert.strictEqual(r.zuege.length, anzahl, `"${text}" Anzahl`);
  n++;
  return r.zuege;
}

ok('e4', 'e2', 'e4');
ok('E4', 'e2', 'e4');
ok('Bauer auf E4', 'e2', 'e4');
ok('eh vier', 'e2', 'e4');
ok('E-4', 'e2', 'e4');
ok('Läufer c4', 'f1', 'c4');
ok('Läufer auf Zeh vier', 'f1', 'c4');
ok('Laeufer C 4', 'f1', 'c4');
ok('Springer schlägt E5', 'f3', 'e5');
ok('Pferd auf e5', 'f3', 'e5');
ok('Sf3xe5', 'f3', 'e5');
ok('Nxe5', 'f3', 'e5');
ok('Sxe5', 'f3', 'e5');
ok('Dame H5', 'd1', 'h5');
ok('Dame auf ha fünf', 'd1', 'h5');
ok('Qh5', 'd1', 'h5');
ok('Dh5', 'd1', 'h5');
ok('kurze Rochade', 'e1', 'g1');
ok('Rochade kurz', 'e1', 'g1');
ok('kleine Rochade', 'e1', 'g1');
ok('lange Rochade', 'e1', 'c1');
ok('große Rochade', 'e1', 'c1');
ok('O-O', 'e1', 'g1');
ok('O-O-O', 'e1', 'c1');
ok('Springer B D2', 'b1', 'd2');
ok('Springer von b1 nach d2', 'b1', 'd2');
ok('Springer f3 d2', 'f3', 'd2');
ok('e2 e4', 'e2', 'e4');
ok('e2e4', 'e2', 'e4');
ok('Turm a d1', 'a1', 'd1');
ok('g8', 'g7', 'g8', 'Q');
ok('Bauer g8 Springer', 'g7', 'g8', 'N');
ok('g8 Umwandlung in Turm', 'g7', 'g8', 'R');
ok('g8=N', 'g7', 'g8', 'N');
assert.ok(P.findeZug('g8', legal).dameAngenommen);

const sp = mehrdeutig('Springer d2', 2);
mehrdeutig('Springer auf D zwei', 2);
mehrdeutig('Turm d1', 2);
mehrdeutig('Rochade', 2);
assert.strictEqual(P.findeZug('Hallo wie geht es', legal).status, 'unbekannt');
assert.strictEqual(P.findeZug('Springer h8', legal).status, 'unbekannt');

// Rückfrage + Auswahl
assert.strictEqual(P.rueckfrage(sp).sprache, 'Welcher Springer? Der von B 1 oder der von F 3?');
assert.strictEqual(P.waehleOption('der von B1', sp, 'w').from, 'b1');
assert.strictEqual(P.waehleOption('F3', sp, 'w').from, 'f3');
assert.strictEqual(P.waehleOption('B', sp, 'w').from, 'b1');
assert.strictEqual(P.waehleOption('der linke', sp, 'w').from, 'b1');
assert.strictEqual(P.waehleOption('der linke', sp, 'b').from, 'f3');
assert.strictEqual(P.waehleOption('der zweite', sp, 'w').from, 'f3');
assert.strictEqual(P.waehleOption('keine Ahnung', sp, 'w'), null);

// Ja / Nein / Wiederholen
assert.ok(P.istJa('Ja'));
assert.ok(P.istJa('genau richtig'));
assert.ok(!P.istJa('nicht richtig'));
assert.ok(P.istNein('Nein'));
assert.ok(P.istNein('nee falsch'));
assert.ok(P.istWiederholen('Wiederholen bitte'));
assert.ok(P.istWiederholen('noch mal'));
assert.ok(!P.istWiederholen('Springer f3'));

// Beschreibungen
const fenStart = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
let d = P.beschreibeZug({ from: 'g8', to: 'f6', piece: 'n', san: 'Nf6', color: 2 }, fenStart);
assert.strictEqual(d.titel, 'Springer auf F6');
assert.strictEqual(d.sprache, 'Springer auf F 6.');
d = P.beschreibeZug({ from: 'b8', to: 'd7', piece: 'n', san: 'Nbd7+', color: 2 });
assert.strictEqual(d.titel, 'Springer von B8 auf D7');
assert.ok(d.hinweise.includes('Schach!'));
d = P.beschreibeZug({ from: 'e5', to: 'd4', piece: 'p', san: 'exd4', color: 2 }, '8/8/8/4p3/3P4/8/8/8 b - - 0 1');
assert.strictEqual(d.titel, 'Bauer von E5 schlägt auf D4');
assert.ok(!d.enPassant);
d = P.beschreibeZug({ from: 'e4', to: 'd3', piece: 'p', san: 'exd3', color: 2 }, '8/8/8/8/3Pp3/8/8/8 b - d3 0 1');
assert.ok(d.enPassant);
assert.ok(d.hinweise[0].includes('D4'));
d = P.beschreibeZug({ from: 'e8', to: 'g8', piece: 'k', san: 'O-O', color: 2 });
assert.strictEqual(d.titel, 'Kurze Rochade');
assert.deepStrictEqual(d.hinweise, ['König E8 → G8', 'Turm H8 → F8']);
d = P.beschreibeZug({ from: 'b2', to: 'b1', piece: 'p', san: 'b1=Q#', color: 2 });
assert.ok(d.hinweise.includes('Umwandlung in Dame') && d.hinweise.includes('Schachmatt!'));

console.log(`Alle Tests bestanden (${n} Zug-Erkennungen + Beschreibungen).`);
