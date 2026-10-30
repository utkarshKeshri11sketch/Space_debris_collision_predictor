"""Background warm-up: a first screening run over the real catalog takes minutes, so the server
computes it at startup and again before the 15-minute run cache expires, instead of making the
first user request wait. Requests that arrive during a run wait on Screening's lock.
"""
from __future__ import annotations

import logging
import os
import threading
import time

LOG = logging.getLogger(__name__)
INTERVAL_S = 600  # below Screening's 900 s run-cache lifetime


def _loop(stop: threading.Event) -> None:
    from .data.catalog import load_catalog
    from .physics import screening
    while not stop.is_set():
        started = time.monotonic()
        try:
            load_catalog()
            events = screening.screen(None, 7, 0)
            LOG.info("Screening warm-up: %d events in %.0f s", len(events), time.monotonic() - started)
        except Exception:  # noqa: BLE001 - keep serving; requests will retry the run themselves
            LOG.exception("Screening warm-up failed")
        stop.wait(INTERVAL_S)


def start() -> threading.Event | None:
    """SCREENING_WARMUP=0 disables it (tests, Lambda, where EventBridge should pre-compute)."""
    if os.getenv("SCREENING_WARMUP", "1") == "0":
        return None
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="screening-warmup", daemon=True).start()
    return stop
