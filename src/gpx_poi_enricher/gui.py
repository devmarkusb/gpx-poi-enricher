"""Qt GUI for the GPX POI Enricher toolkit.

Launch with:
    gpx-poi-enricher-gui

or:
    python -m gpx_poi_enricher.gui
"""

from __future__ import annotations

import pathlib
import re
import sys
import threading
from typing import Any

import requests
from PyQt6.QtCore import QObject, QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .enricher import enrich_gpx_file
from .maps_to_gpx_cli import (
    _expand_url,
    _resolve_waypoints,
    _route_osrm,
    _write_gpx,
    _write_gpx_segments,
    parse_waypoints_from_url,
)
from .profiles import load_all_profiles
from .route_detours import (
    alternate_is_reverse_itinerary,
    alternate_redundant_with_prior,
    extract_detour_segments,
)
from .split_cli import add_split_waypoints

# ── Stderr capture ─────────────────────────────────────────────────────────────


class _LogEmitter(QObject):
    """Emit log strings as a Qt signal (safe to call from any thread)."""

    message = pyqtSignal(str)


class _CapturedStderr:
    """Drop-in replacement for sys.stderr that routes lines to a Qt signal.

    Thread-safe: a lock serialises concurrent writes from the worker thread and
    the ProgressHeartbeat daemon thread.
    """

    def __init__(self, emitter: _LogEmitter) -> None:
        self._emitter = emitter
        self._buf = ""
        self._lock = threading.Lock()

    # Make it look like a proper text stream so that print() and gpxpy are happy
    encoding = "utf-8"
    errors = "replace"

    def write(self, text: str) -> int:
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                stripped = line.strip()
                if stripped:
                    self._emitter.message.emit(stripped)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._buf.strip():
                self._emitter.message.emit(self._buf.strip())
                self._buf = ""

    def fileno(self) -> int:  # some libraries call this; raise to signal "not a real file"
        import io

        raise io.UnsupportedOperation("fileno")

    def isatty(self) -> bool:
        return False


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _file_row(
    dialog_title: str,
    placeholder: str = "",
    save: bool = False,
    filter_str: str = "GPX files (*.gpx);;All files (*)",
) -> tuple[QWidget, QLineEdit]:
    """Return a (container widget, QLineEdit) pair with a Browse button."""
    container = QWidget()
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    btn = QPushButton("Browse…")
    btn.setFixedWidth(80)
    h.addWidget(edit)
    h.addWidget(btn)

    def _browse() -> None:
        if save:
            path, _ = QFileDialog.getSaveFileName(container, dialog_title, "", filter_str)
        else:
            path, _ = QFileDialog.getOpenFileName(container, dialog_title, "", filter_str)
        if path:
            edit.setText(path)

    btn.clicked.connect(_browse)
    return container, edit


def _dir_row(dialog_title: str, default_dir: str = "") -> tuple[QWidget, QLineEdit]:
    """Return a (container widget, QLineEdit) pair with a Browse button for directories."""
    container = QWidget()
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit()
    if default_dir:
        edit.setText(default_dir)
    else:
        edit.setPlaceholderText("Select output folder…")
    btn = QPushButton("Browse…")
    btn.setFixedWidth(80)
    h.addWidget(edit)
    h.addWidget(btn)

    def _browse() -> None:
        start = edit.text() or default_dir
        path = QFileDialog.getExistingDirectory(container, dialog_title, start)
        if path:
            edit.setText(path)

    btn.clicked.connect(_browse)
    return container, edit


def _shorten_label(label: str) -> str:
    """Return a short city-level name from a potentially verbose address string.

    Iterates comma-separated parts, strips leading postal codes, and returns
    the first part that contains no remaining digits (i.e. looks like a place name).
    Falls back to the postal-code-stripped first part if nothing cleaner is found.
    """
    parts = [p.strip() for p in label.split(",")]
    for part in parts:
        clean = re.sub(r"^\d[\d\s]*\s+", "", part).strip()
        if clean and not any(c.isdigit() for c in clean):
            return clean
    clean = re.sub(r"^\d[\d\s]*\s+", "", parts[0]).strip()
    return clean or parts[0]


def _safe_filename(label: str) -> str:
    """Sanitize a string for use as a filename component."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", label).strip(". ")


def _log_widget() -> QPlainTextEdit:
    w = QPlainTextEdit()
    w.setReadOnly(True)
    w.setFont(QFont("Monospace", 9))
    w.setMaximumBlockCount(5000)
    return w


def _append_log(log: QPlainTextEdit, text: str) -> None:
    log.appendPlainText(text)
    sb = log.verticalScrollBar()
    sb.setValue(sb.maximum())


def _gui_settings() -> QSettings:
    """Per-user persistent GUI state (desktop: plist / registry / ini)."""
    return QSettings("gpx-poi-enricher", "gui")


def _set_combo_profile_id(combo: QComboBox, profile_id: str) -> None:
    if not profile_id:
        return
    for i in range(combo.count()):
        if combo.itemData(i) == profile_id:
            combo.setCurrentIndex(i)
            return


# ── Worker threads ─────────────────────────────────────────────────────────────


class _EnricherWorker(QThread):
    log_message = pyqtSignal(str)
    finished = pyqtSignal(list)  # list of POI dicts
    error = pyqtSignal(str)

    def __init__(
        self,
        input_path: str,
        output_path: str,
        profile_id: str,
        cancel_event: threading.Event,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._input = input_path
        self._output = output_path
        self._profile_id = profile_id
        self._cancel_event = cancel_event
        self._kwargs = kwargs

    def run(self) -> None:
        emitter = _LogEmitter()
        emitter.message.connect(self.log_message)
        capture = _CapturedStderr(emitter)
        old_stderr = sys.stderr
        sys.stderr = capture  # type: ignore[assignment]
        try:
            items = enrich_gpx_file(
                self._input,
                self._output,
                self._profile_id,
                cancel_event=self._cancel_event,
                **self._kwargs,
            )
            capture.flush()
            self.finished.emit(items)
        except Exception as exc:
            capture.flush()
            self.error.emit(str(exc))
        finally:
            sys.stderr = old_stderr


class _SplitWorker(QThread):
    log_message = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, input_path: str, output_path: str, segments: int) -> None:
        super().__init__()
        self._input = input_path
        self._output = output_path
        self._segments = segments

    def run(self) -> None:
        try:
            add_split_waypoints(self._input, self._output, self._segments)
            self.log_message.emit(f"Done. Wrote: {self._output}")
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class _MapsWorker(QThread):
    log_message = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, urls: list[str], output_path: str, mode: str, track_name: str) -> None:
        super().__init__()
        self._urls = urls
        self._output = output_path
        self._mode = mode
        self._track_name = track_name

    def run(self) -> None:
        # Redirect stderr so that _resolve_waypoints geocoding messages are captured
        emitter = _LogEmitter()
        emitter.message.connect(self.log_message)
        capture = _CapturedStderr(emitter)
        old_stderr = sys.stderr
        sys.stderr = capture  # type: ignore[assignment]
        session = requests.Session()
        try:
            routes: list[tuple[list[tuple[float, float, str]], list[tuple[float, float]]]] = []
            for idx, raw_url in enumerate(self._urls):
                url = raw_url.strip()
                self.log_message.emit(f"Route {idx + 1}/{len(self._urls)}: parsing…")
                if "goo.gl" in url or "maps.app" in url:
                    self.log_message.emit("Expanding short URL…")
                    url = _expand_url(url, session)
                    self.log_message.emit(f"  → {url}")

                raw = parse_waypoints_from_url(url)
                if len(raw) < 2:
                    self.error.emit("Each URL needs at least 2 waypoints (origin + destination).")
                    return
                self.log_message.emit(f"Found {len(raw)} waypoint(s) in URL.")

                self.log_message.emit("Resolving waypoints via Nominatim…")
                waypoints = _resolve_waypoints(raw, session)
                for lat, lon, label in waypoints:
                    self.log_message.emit(f"  {label} → {lat:.5f}, {lon:.5f}")

                self.log_message.emit(f"Routing via OSRM ({self._mode})…")
                track_points = _route_osrm(waypoints, self._mode, session)
                self.log_message.emit(f"  {len(track_points)} track point(s) returned.")
                routes.append((waypoints, track_points))

            primary_wp, primary_pts = routes[0]
            out_path = pathlib.Path(self._output)
            out_dir = out_path.parent
            stem = out_path.stem

            _write_gpx(primary_pts, primary_wp, str(out_path), self._track_name)
            self.log_message.emit(f"Saved primary: {out_path}")

            if len(routes) > 1:
                for j, (wpts, pts) in enumerate(routes[1:], start=2):
                    alt_path = out_dir / f"{stem}-full-{j:02d}.gpx"
                    alt_track = f"{_shorten_label(wpts[0][2])} – {_shorten_label(wpts[-1][2])}"
                    if alt_path.exists():
                        self.log_message.emit(
                            f"Alternate route GPX already exists, reusing: {alt_path}"
                        )
                    else:
                        _write_gpx(pts, wpts, str(alt_path), alt_track)
                        self.log_message.emit(f"Saved alternate GPX: {alt_path}")

                prior_alt_pts: list[list[tuple[float, float]]] = []
                wrote_detour = False
                for j, (_wpts, alt_pts) in enumerate(routes[1:], start=2):
                    if alternate_redundant_with_prior(alt_pts, primary_pts, prior_alt_pts):
                        self.log_message.emit(
                            f"Alternate {j}: skipping detour GPX (same geometry as primary "
                            "or an earlier alternate, including reverse)."
                        )
                        prior_alt_pts.append(alt_pts)
                        continue
                    if alternate_is_reverse_itinerary(primary_pts, alt_pts):
                        self.log_message.emit(
                            f"Alternate {j}: skipping detour GPX (reverse itinerary B→A vs "
                            "primary A→B — no separate detour; see full-route GPX)."
                        )
                        prior_alt_pts.append(alt_pts)
                        continue
                    prior_alt_pts.append(alt_pts)
                    detour_segs = extract_detour_segments(alt_pts, primary_pts)
                    if not detour_segs:
                        self.log_message.emit(
                            f"Alternate {j}: no detour GPX (stays on primary within threshold)."
                        )
                        continue
                    det_path = out_dir / f"{stem}-detour-{j:02d}.gpx"
                    if det_path.exists():
                        self.log_message.emit(f"Detour GPX already exists, reusing: {det_path}")
                    else:
                        _write_gpx_segments(
                            detour_segs, [], str(det_path), f"Detour (alternate {j})"
                        )
                        n_pts = sum(len(s) for s in detour_segs)
                        self.log_message.emit(
                            f"Saved detour: {det_path} ({len(detour_segs)} segments, {n_pts} pts)"
                        )
                    wrote_detour = True
                if len(routes) > 1 and not wrote_detour:
                    self.log_message.emit(
                        "No detour GPX files (alternates coincide with primary or each other)."
                    )

            self.finished.emit()
        except Exception as exc:
            capture.flush()
            self.error.emit(str(exc))
        finally:
            capture.flush()
            sys.stderr = old_stderr


class _EasyWorker(QThread):
    """Combined Maps→GPX + POI enrichment pipeline for Easy mode."""

    log_message = pyqtSignal(str)
    tracks_ready = pyqtSignal(object)  # list[str] — GPX paths passed to enrichment
    pois_done = pyqtSignal(object)  # list[tuple[str, int]] — output GPX path + POI count each
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        urls: list[str],
        profile_id: str,
        output_dir: str,
        cancel_event: threading.Event,
        quick: bool = False,
    ) -> None:
        super().__init__()
        self._urls = urls
        self._profile_id = profile_id
        self._output_dir = output_dir
        self._cancel_event = cancel_event
        self._quick = quick

    def run(self) -> None:
        emitter = _LogEmitter()
        emitter.message.connect(self.log_message)
        capture = _CapturedStderr(emitter)
        old_stderr = sys.stderr
        sys.stderr = capture  # type: ignore[assignment]
        session = requests.Session()
        try:
            routes: list[tuple[list[tuple[float, float, str]], list[tuple[float, float]]]] = []
            for idx, raw_url in enumerate(self._urls):
                if self._cancel_event.is_set():
                    self.log_message.emit("Cancelled.")
                    return
                url = raw_url.strip()
                self.log_message.emit(f"Route {idx + 1}/{len(self._urls)}: parsing…")
                if "goo.gl" in url or "maps.app" in url:
                    self.log_message.emit("Expanding short URL…")
                    url = _expand_url(url, session)
                    self.log_message.emit(f"  → {url}")

                raw = parse_waypoints_from_url(url)
                if len(raw) < 2:
                    self.error.emit("Each URL needs at least 2 waypoints (origin + destination).")
                    return
                self.log_message.emit(f"Found {len(raw)} waypoint(s) in URL.")

                self.log_message.emit("Resolving waypoints via Nominatim…")
                waypoints = _resolve_waypoints(raw, session)
                for lat, lon, label in waypoints:
                    self.log_message.emit(f"  {label} → {lat:.5f}, {lon:.5f}")

                self.log_message.emit("Routing via OSRM (driving)…")
                track_points = _route_osrm(waypoints, "driving", session)
                self.log_message.emit(f"  {len(track_points)} track point(s) returned.")
                routes.append((waypoints, track_points))

            primary_wp, primary_pts = routes[0]
            start_label = _shorten_label(primary_wp[0][2])
            finish_label = _shorten_label(primary_wp[-1][2])
            base_name = f"{_safe_filename(start_label)}-{_safe_filename(finish_label)}"
            out_dir = pathlib.Path(self._output_dir)
            track_path = out_dir / f"{base_name}.gpx"
            track_name = f"{start_label} – {finish_label}"

            if track_path.exists():
                self.log_message.emit(f"Primary track already exists, reusing: {track_path}")
            else:
                _write_gpx(primary_pts, primary_wp, str(track_path), track_name)
                self.log_message.emit(f"Primary track saved: {track_path}")

            tracks_to_enrich: list[str] = [str(track_path)]

            if len(routes) > 1:
                for j, (wpts, pts) in enumerate(routes[1:], start=2):
                    alt_path = out_dir / f"{base_name}-full-{j:02d}.gpx"
                    alt_track = f"{_shorten_label(wpts[0][2])} – {_shorten_label(wpts[-1][2])}"
                    if alt_path.exists():
                        self.log_message.emit(
                            f"Alternate route GPX already exists, reusing: {alt_path}"
                        )
                    else:
                        _write_gpx(pts, wpts, str(alt_path), alt_track)
                        self.log_message.emit(f"Alternate route GPX: {alt_path}")

                prior_alt_pts: list[list[tuple[float, float]]] = []
                for j, (wpts, alt_pts) in enumerate(routes[1:], start=2):
                    if alternate_redundant_with_prior(alt_pts, primary_pts, prior_alt_pts):
                        self.log_message.emit(
                            f"Alternate {j}: skipping detour enrichment (same as primary "
                            "or earlier alternate, including reverse)."
                        )
                        prior_alt_pts.append(alt_pts)
                        continue
                    if alternate_is_reverse_itinerary(primary_pts, alt_pts):
                        self.log_message.emit(
                            f"Alternate {j}: skipping detour enrichment (reverse itinerary "
                            "B→A vs primary A→B)."
                        )
                        prior_alt_pts.append(alt_pts)
                        continue
                    prior_alt_pts.append(alt_pts)
                    detour_segs = extract_detour_segments(alt_pts, primary_pts)
                    if not detour_segs:
                        self.log_message.emit(
                            f"Alternate {j}: no detour track (on primary within threshold)."
                        )
                        continue
                    det_path = out_dir / f"{base_name}-detour-{j:02d}.gpx"
                    if det_path.exists():
                        self.log_message.emit(f"Detour GPX already exists, reusing: {det_path}")
                    else:
                        _write_gpx_segments(
                            detour_segs, [], str(det_path), f"Detour (alternate {j})"
                        )
                        n_pts = sum(len(s) for s in detour_segs)
                        self.log_message.emit(
                            f"Detour GPX: {det_path} ({len(detour_segs)} segments, {n_pts} pts)"
                        )
                    tracks_to_enrich.append(str(det_path))

            self.tracks_ready.emit(tracks_to_enrich)

            if self._cancel_event.is_set():
                self.log_message.emit("Cancelled.")
                return

            enrich_kwargs: dict[str, Any] = {"progress_interval": 5.0}
            if self._quick:
                enrich_kwargs.update(
                    {"sample_km": 500.0, "max_km": 1.0, "country_sample_km": 500.0}
                )

            primary_stem = track_path.stem
            poi_results: list[tuple[str, int]] = []
            for tpath in tracks_to_enrich:
                if self._cancel_event.is_set():
                    self.log_message.emit("Cancelled.")
                    return
                stem = pathlib.Path(tpath).stem
                poi_path = str(out_dir / f"{stem}-{self._profile_id}.gpx")
                self.log_message.emit(f"Enriching: {tpath} → {poi_path}")
                # Early cancel only for the primary route GPX, not detour fragments (often empty).
                early_cancel = stem == primary_stem
                items = enrich_gpx_file(
                    tpath,
                    poi_path,
                    self._profile_id,
                    early_cancel_if_no_pois=early_cancel,
                    cancel_event=self._cancel_event,
                    **enrich_kwargs,
                )
                poi_results.append((poi_path, len(items)))
                self.log_message.emit(f"POIs saved: {poi_path} ({len(items)} POI(s))")

            capture.flush()
            self.pois_done.emit(poi_results)
            self.finished.emit()

        except Exception as exc:
            capture.flush()
            self.error.emit(str(exc))
        finally:
            sys.stderr = old_stderr


# ── Tab: Easy mode ────────────────────────────────────────────────────────────


class _EasyTab(QWidget):
    """Easy mode: paste a Maps URL, pick a profile, generate GPX files."""

    def __init__(self, parent: QWidget | None = None, quick: bool = False) -> None:
        super().__init__(parent)
        self._quick = quick
        self._worker: _EasyWorker | None = None
        self._cancel_event = threading.Event()
        self._profiles: dict = {}
        self._track_paths: list[str] = []
        self._poi_results: list[tuple[str, int]] = []
        self._setup_ui()
        self._load_profiles()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        # URLs: primary + optional additional (detour) routes
        url_box = QGroupBox("Google Maps directions URLs")
        url_l = QVBoxLayout(url_box)
        url_l.addWidget(QLabel("Primary route (required):"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://www.google.com/maps/dir/…  or  maps.app.goo.gl/…"
        )
        url_l.addWidget(self._url_edit)
        url_l.addWidget(
            QLabel(
                "Additional routes (optional, one URL per line) — alternate paths used "
                "to find detours vs the primary. A reverse trip (B→A vs your A→B) gets no "
                "detour GPX (geometry differs too much from OSRM); use the full-route file."
            )
        )
        self._extra_urls_edit = QPlainTextEdit()
        self._extra_urls_edit.setPlaceholderText(
            "Optional:\n"
            "https://www.google.com/maps/dir/…/variant/\n"
            "https://maps.app.goo.gl/…  (return trip or different itinerary)\n"
        )
        self._extra_urls_edit.setMaximumBlockCount(50)
        self._extra_urls_edit.setFixedHeight(88)
        url_l.addWidget(self._extra_urls_edit)
        root.addWidget(url_box)

        # Profile + output folder
        cfg_box = QGroupBox("Options")
        cfg_l = QFormLayout(cfg_box)
        self._profile_combo = QComboBox()
        cfg_l.addRow("Profile:", self._profile_combo)
        dir_w, self._output_dir_edit = _dir_row("Select Output Folder", str(pathlib.Path.home()))
        cfg_l.addRow("Output folder:", dir_w)
        root.addWidget(cfg_box)

        # Buttons
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Generate GPX")
        self._run_btn.setFixedHeight(40)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(40)
        self._cancel_btn.setEnabled(False)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

        self._run_btn.clicked.connect(self._run)
        self._cancel_btn.clicked.connect(self._cancel)

        # Progress + status
        self._progress = QProgressBar()
        self._status_lbl = QLabel("Ready.")
        root.addWidget(self._progress)
        root.addWidget(self._status_lbl)

        # Splitter: log (top) + results (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        log_w = QWidget()
        log_l = QVBoxLayout(log_w)
        log_l.setContentsMargins(0, 0, 0, 0)
        log_l.addWidget(QLabel("Log:"))
        self._log = _log_widget()
        log_l.addWidget(self._log)
        splitter.addWidget(log_w)

        results_w = QWidget()
        res_l = QVBoxLayout(results_w)
        res_l.setContentsMargins(0, 0, 0, 0)
        res_l.addWidget(QLabel("Generated files:"))
        self._results_edit = QPlainTextEdit()
        self._results_edit.setReadOnly(True)
        self._results_edit.setPlainText("—")
        self._results_edit.setFont(QFont("Monospace", 9))
        self._results_edit.setMaximumHeight(140)
        self._results_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._results_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        res_l.addWidget(self._results_edit)
        splitter.addWidget(results_w)

        splitter.setSizes([360, 140])
        root.addWidget(splitter, 1)

    def _load_profiles(self) -> None:
        try:
            self._profiles = load_all_profiles()
            for p in self._profiles.values():
                self._profile_combo.addItem(f"{p.id}  —  {p.description}", p.id)
        except Exception as exc:
            _append_log(self._log, f"Warning: could not load profiles: {exc}")

    def _run(self) -> None:
        primary = self._url_edit.text().strip()
        extra_lines = [
            ln.strip() for ln in self._extra_urls_edit.toPlainText().splitlines() if ln.strip()
        ]
        urls = [primary, *extra_lines]
        pid = self._profile_combo.currentData()
        out_dir = self._output_dir_edit.text().strip()

        if not primary:
            QMessageBox.warning(
                self, "URL required", "Please enter a primary Google Maps directions URL."
            )
            return
        if not pid:
            QMessageBox.warning(self, "Profile required", "Please select a profile.")
            return
        if not out_dir:
            QMessageBox.warning(self, "Folder required", "Please select an output folder.")
            return
        if not pathlib.Path(out_dir).is_dir():
            QMessageBox.warning(self, "Invalid folder", f"Output folder does not exist:\n{out_dir}")
            return

        self._log.clear()
        self._results_edit.setPlainText("—")
        self._track_paths = []
        self._poi_results = []
        self._progress.setRange(0, 0)
        self._status_lbl.setText("Running…")
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._cancel_event = threading.Event()
        self._worker = _EasyWorker(urls, pid, out_dir, self._cancel_event, self._quick)
        self._worker.log_message.connect(lambda t: _append_log(self._log, t))
        self._worker.tracks_ready.connect(self._on_tracks_ready)
        self._worker.pois_done.connect(self._on_pois_done)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel(self) -> None:
        _append_log(self._log, "Cancellation requested — waiting for current batch…")
        self._cancel_event.set()
        self._cancel_btn.setEnabled(False)

    def _on_tracks_ready(self, paths: object) -> None:
        self._track_paths = list(paths)  # type: ignore[arg-type]
        self._update_results()

    def _on_pois_done(self, results: object) -> None:
        self._poi_results = list(results)  # type: ignore[arg-type]
        self._update_results()

    def _update_results(self) -> None:
        lines: list[str] = []
        if self._track_paths:
            lines.append("Tracks to enrich:")
            for p in self._track_paths:
                lines.append(f"  {p}")
        if self._poi_results:
            lines.append("POI outputs:")
            total = 0
            for path, n in self._poi_results:
                lines.append(f"  {path}  ({n} POI(s))")
                total += n
            if len(self._poi_results) > 1:
                lines.append(f"  (sum of counts: {total})")
        self._results_edit.setPlainText("\n".join(lines) if lines else "—")

    def _on_done(self) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        n_files = len(self._poi_results)
        total_pois = sum(n for _, n in self._poi_results)
        self._status_lbl.setText(
            f"Done — {total_pois} POI(s) in {n_files} file(s)." if n_files else "Done."
        )
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    def _on_error(self, msg: str) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._status_lbl.setText("Error — see log.")
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        _append_log(self._log, f"\nERROR: {msg}")
        QMessageBox.critical(self, "Failed", msg)

    def read_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("easy")
        try:
            self._url_edit.setText(s.value("primary_url", "", type=str))
            self._extra_urls_edit.setPlainText(s.value("extra_urls", "", type=str))
            _set_combo_profile_id(self._profile_combo, s.value("profile_id", "", type=str))
            od = s.value("output_dir", "", type=str)
            if od:
                self._output_dir_edit.setText(od)
        finally:
            s.endGroup()

    def write_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("easy")
        try:
            s.setValue("primary_url", self._url_edit.text())
            s.setValue("extra_urls", self._extra_urls_edit.toPlainText())
            pid = self._profile_combo.currentData()
            s.setValue("profile_id", pid if pid else "")
            s.setValue("output_dir", self._output_dir_edit.text())
        finally:
            s.endGroup()


# ── Tab: POI Enricher ─────────────────────────────────────────────────────────


class _EnricherTab(QWidget):
    """Main workflow tab: enrich a GPX track with nearby OSM POIs."""

    def __init__(self, parent: QWidget | None = None, quick: bool = False) -> None:
        super().__init__(parent)
        self._quick = quick
        self._worker: _EnricherWorker | None = None
        self._cancel_event = threading.Event()
        self._profiles: dict = {}
        self._setup_ui()
        self._load_profiles()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # Files
        files_box = QGroupBox("Files")
        fl = QFormLayout(files_box)
        input_w, self._input_edit = _file_row("Open Input GPX", "route.gpx")
        output_w, self._output_edit = _file_row("Save Output GPX", "pois.gpx", save=True)
        fl.addRow("Input GPX:", input_w)
        fl.addRow("Output GPX:", output_w)
        root.addWidget(files_box)

        # Profile
        profile_box = QGroupBox("Profile")
        pl = QFormLayout(profile_box)
        self._profile_combo = QComboBox()
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self._profile_info = QLabel("—")
        self._profile_info.setWordWrap(True)
        _pi_fm = QFontMetrics(self._profile_info.font())
        self._profile_info.setMinimumHeight(_pi_fm.lineSpacing() * 3)
        pl.addRow("Profile:", self._profile_combo)
        pl.addRow("Defaults:", self._profile_info)
        root.addWidget(profile_box)

        # Parameters
        params_box = QGroupBox("Parameters  (0 = use profile default)")
        param_l = QFormLayout(params_box)

        self._max_km = QDoubleSpinBox()
        self._max_km.setRange(0, 999)
        self._max_km.setDecimals(1)
        self._max_km.setSuffix(" km")
        self._max_km.setSpecialValueText("profile default")
        self._max_km.setToolTip("Maximum distance from track to include a POI")

        self._sample_km = QDoubleSpinBox()
        self._sample_km.setRange(0, 999)
        self._sample_km.setDecimals(1)
        self._sample_km.setSuffix(" km")
        self._sample_km.setSpecialValueText("profile default")
        self._sample_km.setToolTip("Track-sampling interval for Overpass queries")

        self._batch_size = QSpinBox()
        self._batch_size.setRange(0, 200)
        self._batch_size.setSpecialValueText("profile default")
        self._batch_size.setToolTip("Track points per Overpass query batch")

        self._country_km = QDoubleSpinBox()
        self._country_km.setRange(1, 999)
        self._country_km.setDecimals(1)
        self._country_km.setValue(40.0)
        self._country_km.setSuffix(" km")
        self._country_km.setToolTip("Minimum spacing between Nominatim reverse-geocode calls")

        self._verbose_cb = QCheckBox("Show verbose Overpass error bodies")

        # Wide enough for special-value text ("profile default") without clipping
        _fm = QFontMetrics(self._max_km.font())
        _spin_pad = 56
        _dbl_w = (
            max(
                _fm.horizontalAdvance("999.9 km"),
                _fm.horizontalAdvance("profile default"),
            )
            + _spin_pad
        )
        self._max_km.setMinimumWidth(_dbl_w)
        self._sample_km.setMinimumWidth(_dbl_w)
        _int_w = (
            max(_fm.horizontalAdvance("200"), _fm.horizontalAdvance("profile default")) + _spin_pad
        )
        self._batch_size.setMinimumWidth(_int_w)

        param_l.addRow("Max distance:", self._max_km)
        param_l.addRow("Sample interval:", self._sample_km)
        param_l.addRow("Batch size:", self._batch_size)
        param_l.addRow("Country sample interval:", self._country_km)
        param_l.addRow("", self._verbose_cb)
        root.addWidget(params_box)

        # Run / Cancel
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run Enrichment")
        self._run_btn.setFixedHeight(34)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(34)
        self._cancel_btn.setEnabled(False)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

        self._run_btn.clicked.connect(self._run)
        self._cancel_btn.clicked.connect(self._cancel)

        # Progress
        self._progress = QProgressBar()
        self._status_lbl = QLabel("Ready.")
        root.addWidget(self._progress)
        root.addWidget(self._status_lbl)

        # Splitter: log (top) + results table (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        log_w = QWidget()
        log_l = QVBoxLayout(log_w)
        log_l.setContentsMargins(0, 0, 0, 0)
        log_l.addWidget(QLabel("Log output:"))
        self._log = _log_widget()
        log_l.addWidget(self._log)
        splitter.addWidget(log_w)

        results_w = QWidget()
        res_l = QVBoxLayout(results_w)
        res_l.setContentsMargins(0, 0, 0, 0)
        res_l.addWidget(QLabel("Results:"))
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Name", "Kind", "Dist (km)", "Lat", "Lon"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        res_l.addWidget(self._table)
        splitter.addWidget(results_w)

        splitter.setSizes([260, 160])
        root.addWidget(splitter, 1)

    # ── Profile loading ────────────────────────────────────────────────────────

    def _load_profiles(self) -> None:
        try:
            self._profiles = load_all_profiles()
            for p in self._profiles.values():
                self._profile_combo.addItem(f"{p.id}  —  {p.description}", p.id)
        except Exception as exc:
            _append_log(self._log, f"Warning: could not load profiles: {exc}")

    def _on_profile_changed(self) -> None:
        pid = self._profile_combo.currentData()
        if pid and pid in self._profiles:
            p = self._profiles[pid]
            self._profile_info.setText(
                f"max_km={p.max_km}  sample_km={p.sample_km}  "
                f"batch_size={p.batch_size}  retries={p.retries}"
            )

    # ── Run / Cancel ───────────────────────────────────────────────────────────

    def _run(self) -> None:
        inp = self._input_edit.text().strip()
        out = self._output_edit.text().strip()
        pid = self._profile_combo.currentData()

        if not inp:
            QMessageBox.warning(self, "Input required", "Please select an input GPX file.")
            return
        if not out:
            QMessageBox.warning(self, "Output required", "Please specify an output GPX file.")
            return
        if not pid:
            QMessageBox.warning(self, "Profile required", "Please select a profile.")
            return

        self._log.clear()
        self._table.setRowCount(0)
        self._progress.setRange(0, 0)  # pulsing / indeterminate
        self._status_lbl.setText("Running…")
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._cancel_event = threading.Event()

        kwargs: dict[str, Any] = {
            "max_km": self._max_km.value() or (1.0 if self._quick else None),
            "sample_km": self._sample_km.value() or (500.0 if self._quick else None),
            "batch_size": self._batch_size.value() or None,
            "country_sample_km": self._country_km.value() if not self._quick else 500.0,
            "progress_interval": 5.0,
            "verbose": self._verbose_cb.isChecked(),
        }

        self._worker = _EnricherWorker(inp, out, pid, self._cancel_event, **kwargs)
        self._worker.log_message.connect(lambda t: _append_log(self._log, t))
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel(self) -> None:
        _append_log(self._log, "Cancellation requested — waiting for current batch to finish…")
        self._cancel_event.set()
        self._cancel_btn.setEnabled(False)

    # ── Completion callbacks ───────────────────────────────────────────────────

    def _on_done(self, items: list) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._status_lbl.setText(f"Done — {len(items)} POI(s) written.")
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        _append_log(self._log, f"\nFinished: {len(items)} POI(s) added to output file.")
        self._populate_table(items)

    def _on_error(self, msg: str) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._status_lbl.setText("Error — see log.")
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        _append_log(self._log, f"\nERROR: {msg}")
        QMessageBox.critical(self, "Enrichment failed", msg)

    def _populate_table(self, items: list) -> None:
        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._table.setItem(row, 0, QTableWidgetItem(item.get("name", "")))
            self._table.setItem(row, 1, QTableWidgetItem(item.get("kind", "")))
            dist = item.get("distance_km", 0.0)
            self._table.setItem(row, 2, QTableWidgetItem(f"{dist:.2f}"))
            self._table.setItem(row, 3, QTableWidgetItem(f"{item.get('lat', 0):.5f}"))
            self._table.setItem(row, 4, QTableWidgetItem(f"{item.get('lon', 0):.5f}"))

    def read_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("enricher")
        try:
            self._input_edit.setText(s.value("input_path", "", type=str))
            self._output_edit.setText(s.value("output_path", "", type=str))
            _set_combo_profile_id(self._profile_combo, s.value("profile_id", "", type=str))
            self._max_km.setValue(float(s.value("max_km", 0.0, type=float)))
            self._sample_km.setValue(float(s.value("sample_km", 0.0, type=float)))
            self._batch_size.setValue(int(s.value("batch_size", 0, type=int)))
            self._country_km.setValue(float(s.value("country_km", 40.0, type=float)))
            self._verbose_cb.setChecked(s.value("verbose", False, type=bool))
        finally:
            s.endGroup()
        self._on_profile_changed()

    def write_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("enricher")
        try:
            s.setValue("input_path", self._input_edit.text())
            s.setValue("output_path", self._output_edit.text())
            pid = self._profile_combo.currentData()
            s.setValue("profile_id", pid if pid else "")
            s.setValue("max_km", self._max_km.value())
            s.setValue("sample_km", self._sample_km.value())
            s.setValue("batch_size", self._batch_size.value())
            s.setValue("country_km", self._country_km.value())
            s.setValue("verbose", self._verbose_cb.isChecked())
        finally:
            s.endGroup()


# ── Tab: Split Waypoints ──────────────────────────────────────────────────────


class _SplitTab(QWidget):
    """Helper tab: add evenly-spaced split waypoints along a GPX track."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _SplitWorker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        files_box = QGroupBox("Files")
        fl = QFormLayout(files_box)
        input_w, self._input_edit = _file_row("Open Input GPX", "route.gpx")
        output_w, self._output_edit = _file_row("Save Output GPX", "split.gpx", save=True)
        fl.addRow("Input GPX:", input_w)
        fl.addRow("Output GPX:", output_w)
        root.addWidget(files_box)

        params_box = QGroupBox("Parameters")
        pl = QFormLayout(params_box)
        self._segments = QSpinBox()
        self._segments.setRange(2, 9999)
        self._segments.setValue(10)
        self._segments.setToolTip(
            "Number of equal-length segments — (N-1) waypoints will be inserted"
        )
        pl.addRow("Segments:", self._segments)
        root.addWidget(params_box)

        self._run_btn = QPushButton("Add Split Waypoints")
        self._run_btn.setFixedHeight(34)
        root.addWidget(self._run_btn)
        self._run_btn.clicked.connect(self._run)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        root.addWidget(self._progress)

        root.addWidget(QLabel("Log output:"))
        self._log = _log_widget()
        root.addWidget(self._log, 1)

    def _run(self) -> None:
        inp = self._input_edit.text().strip()
        out = self._output_edit.text().strip()
        segs = self._segments.value()

        if not inp:
            QMessageBox.warning(self, "Input required", "Please select an input GPX file.")
            return
        if not out:
            QMessageBox.warning(self, "Output required", "Please specify an output GPX file.")
            return

        self._log.clear()
        self._progress.setRange(0, 0)
        self._run_btn.setEnabled(False)

        self._worker = _SplitWorker(inp, out, segs)
        self._worker.log_message.connect(lambda t: _append_log(self._log, t))
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._run_btn.setEnabled(True)

    def _on_error(self, msg: str) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._run_btn.setEnabled(True)
        _append_log(self._log, f"\nERROR: {msg}")
        QMessageBox.critical(self, "Split failed", msg)

    def read_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("split")
        try:
            self._input_edit.setText(s.value("input_path", "", type=str))
            self._output_edit.setText(s.value("output_path", "", type=str))
            segs = int(s.value("segments", 10, type=int))
            segs = max(self._segments.minimum(), min(segs, self._segments.maximum()))
            self._segments.setValue(segs)
        finally:
            s.endGroup()

    def write_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("split")
        try:
            s.setValue("input_path", self._input_edit.text())
            s.setValue("output_path", self._output_edit.text())
            s.setValue("segments", self._segments.value())
        finally:
            s.endGroup()


# ── Tab: Maps → GPX ──────────────────────────────────────────────────────────


class _MapsTab(QWidget):
    """Convert Google Maps directions URL(s) to routed GPX file(s), including detour splits."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _MapsWorker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        url_box = QGroupBox("Google Maps directions URLs")
        url_outer = QVBoxLayout(url_box)
        url_outer.addWidget(QLabel("Primary route (required) — written to the output path below:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://www.google.com/maps/dir/Paris/Lyon/Marseille/  or  maps.app.goo.gl/…"
        )
        url_outer.addWidget(self._url_edit)
        url_outer.addWidget(
            QLabel(
                "Additional routes (optional, one URL per line). Full routes and detours are "
                "named next to the primary basename; reverse B→A trips get no detour GPX."
            )
        )
        self._extra_urls_edit = QPlainTextEdit()
        self._extra_urls_edit.setPlaceholderText(
            "Optional detour / alternate directions:\nhttps://www.google.com/maps/dir/…\n"
        )
        self._extra_urls_edit.setMaximumBlockCount(50)
        self._extra_urls_edit.setFixedHeight(80)
        url_outer.addWidget(self._extra_urls_edit)
        root.addWidget(url_box)

        out_box = QGroupBox("Output")
        ol = QFormLayout(out_box)
        output_w, self._output_edit = _file_row("Save Output GPX", "route.gpx", save=True)
        self._mode_combo = QComboBox()
        for mode in ("driving", "cycling", "walking"):
            self._mode_combo.addItem(mode, mode)
        self._name_edit = QLineEdit("Route")
        ol.addRow("Output GPX:", output_w)
        ol.addRow("Transport mode:", self._mode_combo)
        ol.addRow("Primary track name:", self._name_edit)
        root.addWidget(out_box)

        self._run_btn = QPushButton("Convert to GPX")
        self._run_btn.setFixedHeight(34)
        root.addWidget(self._run_btn)
        self._run_btn.clicked.connect(self._run)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        root.addWidget(self._progress)

        root.addWidget(QLabel("Log output:"))
        self._log = _log_widget()
        root.addWidget(self._log, 1)

    def _run(self) -> None:
        primary = self._url_edit.text().strip()
        extra_lines = [
            ln.strip() for ln in self._extra_urls_edit.toPlainText().splitlines() if ln.strip()
        ]
        urls = [primary, *extra_lines]
        out = self._output_edit.text().strip()
        mode = self._mode_combo.currentData()
        name = self._name_edit.text().strip() or "Route"

        if not primary:
            QMessageBox.warning(self, "URL required", "Please enter a primary Google Maps URL.")
            return
        if not out:
            QMessageBox.warning(self, "Output required", "Please specify an output GPX file.")
            return

        self._log.clear()
        self._progress.setRange(0, 0)
        self._run_btn.setEnabled(False)

        self._worker = _MapsWorker(urls, out, mode, name)
        self._worker.log_message.connect(lambda t: _append_log(self._log, t))
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._run_btn.setEnabled(True)

    def _on_error(self, msg: str) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._run_btn.setEnabled(True)
        _append_log(self._log, f"\nERROR: {msg}")
        QMessageBox.critical(self, "Conversion failed", msg)

    def read_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("maps")
        try:
            self._url_edit.setText(s.value("primary_url", "", type=str))
            self._extra_urls_edit.setPlainText(s.value("extra_urls", "", type=str))
            self._output_edit.setText(s.value("output_path", "", type=str))
            mode = s.value("transport_mode", "driving", type=str)
            for i in range(self._mode_combo.count()):
                if self._mode_combo.itemData(i) == mode:
                    self._mode_combo.setCurrentIndex(i)
                    break
            self._name_edit.setText(s.value("track_name", "Route", type=str))
        finally:
            s.endGroup()

    def write_gui_settings(self, s: QSettings) -> None:
        s.beginGroup("maps")
        try:
            s.setValue("primary_url", self._url_edit.text())
            s.setValue("extra_urls", self._extra_urls_edit.toPlainText())
            s.setValue("output_path", self._output_edit.text())
            m = self._mode_combo.currentData()
            s.setValue("transport_mode", m if m else "driving")
            s.setValue("track_name", self._name_edit.text())
        finally:
            s.endGroup()


# ── Main window ────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self, quick: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("GPX POI Enricher" + (" [quick]" if quick else ""))
        self.resize(760, 820)

        central = QWidget()
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Mode switcher bar
        mode_bar = QWidget()
        mode_h = QHBoxLayout(mode_bar)
        mode_h.setContentsMargins(8, 6, 8, 4)

        self._easy_btn = QPushButton("Easy")
        self._easy_btn.setCheckable(True)
        self._easy_btn.setChecked(True)
        self._easy_btn.setFixedWidth(90)

        self._expert_btn = QPushButton("Expert")
        self._expert_btn.setCheckable(True)
        self._expert_btn.setFixedWidth(90)

        btn_group = QButtonGroup(self)
        btn_group.setExclusive(True)
        btn_group.addButton(self._easy_btn)
        btn_group.addButton(self._expert_btn)

        mode_h.addWidget(self._easy_btn)
        mode_h.addWidget(self._expert_btn)
        mode_h.addStretch()
        vbox.addWidget(mode_bar)

        # Stacked content
        self._stack = QStackedWidget()

        self._easy_widget = _EasyTab(quick=quick)
        self._stack.addWidget(self._easy_widget)  # index 0

        self._expert_tabs = QTabWidget()
        self._enricher_tab = _EnricherTab(quick=quick)
        self._split_tab = _SplitTab()
        self._maps_tab = _MapsTab()
        self._expert_tabs.addTab(self._enricher_tab, "POI Enricher")
        self._expert_tabs.addTab(self._split_tab, "Split Waypoints")
        self._expert_tabs.addTab(self._maps_tab, "Maps → GPX")
        self._stack.addWidget(self._expert_tabs)  # index 1

        vbox.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._easy_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._expert_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))

        sb = QStatusBar()
        sb.showMessage("Ready.")
        self.setStatusBar(sb)

        self._restore_gui_settings()

    def _restore_gui_settings(self) -> None:
        s = _gui_settings()
        geo = s.value("main/geometry")
        if geo is not None:
            self.restoreGeometry(geo)  # type: ignore[arg-type]
        mode_idx = int(s.value("main/mode_stack_index", 0, type=int))
        mode_idx = 0 if mode_idx not in (0, 1) else mode_idx
        if mode_idx == 1:
            self._expert_btn.setChecked(True)
            self._easy_btn.setChecked(False)
            self._stack.setCurrentIndex(1)
        else:
            self._easy_btn.setChecked(True)
            self._expert_btn.setChecked(False)
            self._stack.setCurrentIndex(0)
        et = int(s.value("main/expert_tab_index", 0, type=int))
        et = max(0, min(et, self._expert_tabs.count() - 1))
        self._expert_tabs.setCurrentIndex(et)
        self._easy_widget.read_gui_settings(s)
        self._enricher_tab.read_gui_settings(s)
        self._split_tab.read_gui_settings(s)
        self._maps_tab.read_gui_settings(s)

    def _save_gui_settings(self) -> None:
        s = _gui_settings()
        s.setValue("main/geometry", self.saveGeometry())
        s.setValue("main/mode_stack_index", self._stack.currentIndex())
        s.setValue("main/expert_tab_index", self._expert_tabs.currentIndex())
        self._easy_widget.write_gui_settings(s)
        self._enricher_tab.write_gui_settings(s)
        self._split_tab.write_gui_settings(s)
        self._maps_tab.write_gui_settings(s)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_gui_settings()
        super().closeEvent(event)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    quick = "--quick" in sys.argv
    qt_argv = [a for a in sys.argv if a != "--quick"]
    app = QApplication.instance() or QApplication(qt_argv)
    win = MainWindow(quick=quick)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
