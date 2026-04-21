"""Qt GUI for the GPX POI Enricher toolkit.

Launch with:
    gpx-poi-enricher-gui

or:
    python -m gpx_poi_enricher.gui
"""

from __future__ import annotations

import sys
import threading
from typing import Any

import requests
from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
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
    parse_waypoints_from_url,
)
from .profiles import load_all_profiles
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

    def __init__(self, url: str, output_path: str, mode: str, track_name: str) -> None:
        super().__init__()
        self._url = url
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
            url = self._url
            if "goo.gl" in url or "maps.app" in url:
                self.log_message.emit("Expanding short URL…")
                url = _expand_url(url, session)
                self.log_message.emit(f"  → {url}")

            raw = parse_waypoints_from_url(url)
            if len(raw) < 2:
                self.error.emit("Need at least 2 waypoints (origin + destination).")
                return
            self.log_message.emit(f"Found {len(raw)} waypoint(s) in URL.")

            self.log_message.emit("Resolving waypoints via Nominatim…")
            waypoints = _resolve_waypoints(raw, session)
            for lat, lon, label in waypoints:
                self.log_message.emit(f"  {label} → {lat:.5f}, {lon:.5f}")

            self.log_message.emit(f"Routing via OSRM ({self._mode})…")
            track_points = _route_osrm(waypoints, self._mode, session)
            self.log_message.emit(f"  {len(track_points)} track point(s) returned.")

            _write_gpx(track_points, waypoints, self._output, self._track_name)
            self.log_message.emit(f"Saved: {self._output}")
            self.finished.emit()
        except Exception as exc:
            capture.flush()
            self.error.emit(str(exc))
        finally:
            capture.flush()
            sys.stderr = old_stderr


# ── Tab: POI Enricher ─────────────────────────────────────────────────────────


class _EnricherTab(QWidget):
    """Main workflow tab: enrich a GPX track with nearby OSM POIs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
            "max_km": self._max_km.value() or None,
            "sample_km": self._sample_km.value() or None,
            "batch_size": self._batch_size.value() or None,
            "country_sample_km": self._country_km.value(),
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


# ── Tab: Maps → GPX ──────────────────────────────────────────────────────────


class _MapsTab(QWidget):
    """Convert a Google Maps directions URL to a routed GPX file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _MapsWorker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        url_box = QGroupBox("Google Maps directions URL")
        ul = QFormLayout(url_box)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://www.google.com/maps/dir/Paris/Lyon/Marseille/  or  maps.app.goo.gl/…"
        )
        ul.addRow("URL:", self._url_edit)
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
        ol.addRow("Track name:", self._name_edit)
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
        url = self._url_edit.text().strip()
        out = self._output_edit.text().strip()
        mode = self._mode_combo.currentData()
        name = self._name_edit.text().strip() or "Route"

        if not url:
            QMessageBox.warning(self, "URL required", "Please enter a Google Maps URL.")
            return
        if not out:
            QMessageBox.warning(self, "Output required", "Please specify an output GPX file.")
            return

        self._log.clear()
        self._progress.setRange(0, 0)
        self._run_btn.setEnabled(False)

        self._worker = _MapsWorker(url, out, mode, name)
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


# ── Main window ────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GPX POI Enricher")
        self.resize(760, 820)

        tabs = QTabWidget()
        tabs.addTab(_EnricherTab(), "POI Enricher")
        tabs.addTab(_SplitTab(), "Split Waypoints")
        tabs.addTab(_MapsTab(), "Maps → GPX")
        self.setCentralWidget(tabs)

        sb = QStatusBar()
        sb.showMessage("Ready.")
        self.setStatusBar(sb)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
