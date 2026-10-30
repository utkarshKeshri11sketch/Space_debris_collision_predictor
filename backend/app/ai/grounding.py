"""Guard against LLM-invented numbers.

The AI may phrase things, but every number in its text must already exist in the FACTS it was given
(computed by screening/maneuver code). Anything else is rejected and the caller uses its template.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_SUP = str.maketrans("⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "-0123456789")
# 3.1 × 10⁻⁴, 3.1 x 10^-4, 3.1e-4
_SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[×x*]\s*10\s*\^?\s*([⁻\-]?[⁰¹²³⁴⁵⁶⁷⁸⁹\d]+)|[eE]([+\-]?\d+))")
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?)?")


_UNIT_AFTER = re.compile(r"\s*(?:km|kg|m/s|m|hours?|minutes?|days?)\b|\s*%", re.IGNORECASE)


def scan(text: str, known_names: Iterable[str] = ()) -> list[tuple[float, bool]]:
    """(value, has_unit) for each number in prose. Object names/IDs (e.g. STARLINK-31502) are stripped first."""
    for name in sorted(known_names, key=len, reverse=True):
        if name:
            text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    text = _ISO.sub(" ", text)
    text = re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", text)  # "4 200 m" -> "4200 m"
    found: list[tuple[float, bool]] = []

    def sci(match: re.Match[str]) -> str:
        exp = match.group(2) or match.group(3)
        found.append((float(match.group(1)) * 10 ** int(exp.translate(_SUP)), True))
        return " "

    text = _SCI.sub(sci, text)
    for m in _NUM.finditer(text):
        found.append((float(m.group().replace(",", "")), bool(_UNIT_AFTER.match(text, m.end()))))
    return found


def numbers_in(text: str, known_names: Iterable[str] = ()) -> list[float]:
    return [value for value, _ in scan(text, known_names)]


def collect_numbers(value: Any) -> list[float]:
    """Every numeric value in a nested facts structure (bools excluded)."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):  # numbers quoted inside notes (e.g. "imaging pass in 3 hours") are also facts
        return numbers_in(value)
    if isinstance(value, dict):
        return [n for v in value.values() for n in collect_numbers(v)]
    if isinstance(value, (list, tuple)):
        return [n for v in value for n in collect_numbers(v)]
    return []


def _decimals(text_value: float) -> int:
    s = f"{text_value:.10g}"
    return len(s.split(".")[1]) if "." in s else 0


def _matches(x: float, allowed: float) -> bool:
    # Allow the only unit conversion our formatters apply (m<->km) and rounding to displayed precision.
    for candidate in (allowed, allowed / 1000, allowed * 1000):
        if candidate == x:
            return True
        if abs(candidate - x) <= 0.015 * max(abs(candidate), abs(x)):
            return True
        if round(candidate, _decimals(x)) == x:
            return True
    return False


def ungrounded_numbers(text: str, facts: Any, known_names: Iterable[str] = (), free_up_to: float = 10.0) -> list[float]:
    """Numbers in `text` not traceable to `facts`.

    Small bare whole numbers ("round 2") are free; with a unit ("5 m") they must be grounded.
    """
    allowed = collect_numbers(facts)
    bad = []
    for x, has_unit in scan(text, known_names):
        if not has_unit and float(x).is_integer() and 0 <= x <= free_up_to:
            continue
        if not any(_matches(x, a) for a in allowed):
            bad.append(x)
    return bad


def is_grounded(text: str, facts: Any, known_names: Iterable[str] = ()) -> bool:
    return not ungrounded_numbers(text, facts, known_names)
