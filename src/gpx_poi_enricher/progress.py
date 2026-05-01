"""Thread-based progress heartbeat for long-running API operations."""

from __future__ import annotations

import sys
import threading
import time
from typing import TextIO


def _short_host(url: str) -> str:
    """Return just the hostname from a URL string."""
    if not url:
        return "—"
    s = url
    for prefix in ("https://", "http://"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return s.split("/")[0] or url


class ProgressHeartbeat:
    """Periodically print a status line to *stream* while long operations run.

    Usage::

        state = {"phase": "nominatim", "pois_found": 0, ...}
        with ProgressHeartbeat(state, interval=5.0):
            do_long_work(progress=state)

    The caller mutates *state* and the heartbeat thread reads it. All fields are
    optional; missing ones render as ``"?"`` or ``0``.
    """

    def __init__(
        self,
        state: dict,
        interval: float = 5.0,
        stream: TextIO | None = None,
    ) -> None:
        self.state = state
        self.interval = interval
        self.stream = stream if stream is not None else sys.stderr
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_identity: object | None = None
        self._step_started_at: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _state_identity(self) -> object:
        """Value that changes when the user-visible “step” changes (timer resets)."""
        s = self.state
        phase = s.get("phase", "?")
        pois = s.get("pois_found", 0)
        if phase == "nominatim":
            return (
                phase,
                s.get("nominatim_sample_idx", 0),
                s.get("nominatim_samples_total"),
                s.get("nominatim_rev_calls", 0),
                pois,
            )
        if phase == "overpass":
            bcur, btot = s.get("batch", (0, 0))
            return (
                phase,
                bcur,
                btot,
                s.get("country", "?"),
                _short_host(s.get("endpoint", "")),
                s.get("attempt"),
                s.get("max_retries"),
                pois,
            )
        return (phase, pois)

    def _format_line(self, elapsed_s: float) -> str:
        s = self.state
        phase = s.get("phase", "?")
        pois = s.get("pois_found", 0)
        wait = f" · {int(elapsed_s)}s on this step" if elapsed_s >= 1.0 else ""

        if phase == "nominatim":
            si = s.get("nominatim_sample_idx", 0)
            st = s.get("nominatim_samples_total", "?")
            rv = s.get("nominatim_rev_calls", 0)
            return (
                f"[progress] nominatim: sample {si + 1}/{st}, "
                f"reverse-geocode calls completed: {rv} | pois so far: {pois}{wait}"
            )

        if phase == "overpass":
            bcur, btot = s.get("batch", (0, 0))
            cc = s.get("country", "?")
            host = _short_host(s.get("endpoint", ""))
            att = s.get("attempt")
            mx = s.get("max_retries")
            att_s = f"{att}/{mx}" if att is not None and mx else "—"
            return (
                f"[progress] overpass: batch {bcur}/{btot} ({cc}) | "
                f"{host} attempt {att_s} | pois so far: {pois}{wait}"
            )

        return f"[progress] {phase} | pois so far: {pois}{wait}"

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            ident = self._state_identity()
            if ident != self._last_identity:
                self._last_identity = ident
                self._step_started_at = time.monotonic()
            elapsed = time.monotonic() - self._step_started_at
            print(self._format_line(elapsed), file=self.stream, flush=True)

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> ProgressHeartbeat:
        self._stop.clear()
        self._last_identity = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 2.0)
        return False
