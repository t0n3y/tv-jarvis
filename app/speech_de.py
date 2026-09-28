"""Hilfen, damit die Piper-Stimme Zahlen, Uhrzeiten und Stunden natuerlich
ausspricht ("in der fuenften Stunde", "um 8 Uhr 30") statt Ziffern und
Doppelpunkte herunterzurattern."""

from __future__ import annotations

import re

_ONES = ["", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun"]
_TEENS = {
    10: "zehn", 11: "elf", 12: "zwölf", 13: "dreizehn", 14: "vierzehn", 15: "fünfzehn",
    16: "sechzehn", 17: "siebzehn", 18: "achtzehn", 19: "neunzehn",
}
_TENS = {2: "zwanzig", 3: "dreißig"}
_ORDINAL_SPECIAL = {1: "ers", 3: "drit", 7: "sieb", 8: "ach"}

MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def cardinal(n: int) -> str:
    """0-39 als Wort (fuer Tage im Monat und Anzahlen), sonst Ziffern."""
    if n == 0:
        return "null"
    if n == 1:
        return "eins"
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n]
    if n < 40:
        tens, ones = divmod(n, 10)
        return (_ONES[ones] + "und" if ones else "") + _TENS[tens]
    return str(n)


def ordinal_stem(n: int) -> str:
    """Stamm der Ordnungszahl: 1 -> "ers", 5 -> "fünf", 29 -> "neunundzwanzigs"."""
    if n in _ORDINAL_SPECIAL:
        return _ORDINAL_SPECIAL[n]
    if n < 20:
        return cardinal(n)
    return cardinal(n) + "s"


def ordinal(n: int, ending: str = "te") -> str:
    """ordinal(5) -> "fünfte", ordinal(5, "ten") -> "fünften"."""
    stem = ordinal_stem(n)
    # "ers"+"te", "fünf"+"te", "zwanzigs"+"te"
    return stem + ending


def count_word(n: int) -> str:
    """Anzahl vor einem Nomen: 1 -> "eine", 2 -> "zwei"."""
    return "eine" if n == 1 else cardinal(n)


def spoken_date(day: int, month: int) -> str:
    """29, 9 -> "neunundzwanzigste September"."""
    return f"{ordinal(day)} {MONTHS[month - 1]}"


def spoken_time(hhmm: str) -> str:
    """"08:00" -> "8 Uhr", "09:30" -> "9 Uhr 30"."""
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", hhmm.strip())
    if not match:
        return hhmm
    hours, minutes = int(match.group(1)), int(match.group(2))
    return f"{hours} Uhr" if minutes == 0 else f"{hours} Uhr {minutes}"


_TIME_IN_TEXT = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b(\s*Uhr)?")


def times_in_text(text: str) -> str:
    """Uhrzeiten in freiem Text ("Frühstück 9.30") sprechbar machen."""
    return _TIME_IN_TEXT.sub(lambda m: spoken_time(f"{m.group(1)}:{m.group(2)}"), text)


def lesson_phrase(lesson: str) -> str | None:
    """"5" -> "in der fünften Stunde", "3-4" -> "in der dritten und vierten
    Stunde", "1-4" -> "von der ersten bis zur vierten Stunde"."""
    numbers = [int(n) for n in re.findall(r"\d+", lesson or "")]
    if not numbers or any(n < 1 or n > 19 for n in numbers):
        return None
    if len(numbers) == 1 or numbers[0] == numbers[-1]:
        return f"in der {ordinal(numbers[0], 'ten')} Stunde"
    first, last = numbers[0], numbers[-1]
    if last == first + 1:
        return f"in der {ordinal(first, 'ten')} und {ordinal(last, 'ten')} Stunde"
    return f"von der {ordinal(first, 'ten')} bis zur {ordinal(last, 'ten')} Stunde"


def sentence(text: str) -> str:
    """Satzzeichen am Ende sicherstellen - Piper macht nach Saetzen eine Pause."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."
