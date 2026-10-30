"""Text formatting that mirrors frontend/src/lib/format.ts so AI prose matches what the UI shows."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

_SUPERSCRIPT = {"-": "⁻", **{str(d): "⁰¹²³⁴⁵⁶⁷⁸⁹"[d] for d in range(10)}}


def distance(metres: float) -> str:
    if not math.isfinite(metres):
        return "unknown"
    return f"{metres / 1000:.2f} km" if abs(metres) >= 1000 else f"{round(metres)} m"


def probability(pc: float) -> str:
    if not math.isfinite(pc) or pc < 0 or pc > 1:
        return "unknown"
    if pc == 0:
        return "0"
    coefficient, exponent = f"{pc:.1e}".split("e")
    return f"{coefficient} × 10{''.join(_SUPERSCRIPT.get(c, c) for c in str(int(exponent)))}"


def kg(value: float) -> str:
    return f"{value:.2f} kg" if value >= 0.01 or value == 0 else f"{value:.3f} kg"


def dv(value: float) -> str:
    return f"{value:.2f} m/s"


def short_name(name: str) -> str:
    """'STARLINK-31502' -> 'STARLINK'; 'ISS (ZARYA)' -> 'ISS'; used in 'signed by' lines."""
    return re.split(r"[-\s(]", name.strip(), maxsplit=1)[0] or name


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def hours_between(later: str | None, earlier: str | None) -> float | None:
    a, b = parse_time(later), parse_time(earlier)
    return None if a is None or b is None else (a - b).total_seconds() / 3600


def hours(value: float) -> str:
    """'18 hours' / '1.5 hours' / '45 minutes' — avoids clock times, which cannot be grounding-checked."""
    if value < 1:
        return f"{round(value * 60)} minutes"
    return f"{value:.1f} hours".replace(".0 hours", " hours")
