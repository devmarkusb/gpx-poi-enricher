"""Easy mode must bypass routing for a point and return only POI files."""

import importlib.util
import json
import os
import pathlib
import threading

import pytest


@pytest.fixture
def bridge():
    path = pathlib.Path(__file__).parents[1] / "android/app/src/main/python/gpx_bridge.py"
    spec = importlib.util.spec_from_file_location("gpx_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_android_easy_point_result(bridge, monkeypatch, tmp_path):
    calls = []

    def named(location, output_dir, profile_id, profiles_dir=None, **kwargs):
        calls.append((location, output_dir, profile_id, profiles_dir, kwargs))
        path = pathlib.Path(output_dir) / f"{profile_id}-poi.gpx"
        return str(path), [object(), object()]

    monkeypatch.setattr(bridge, "enrich_point_file_named", named)
    result = json.loads(bridge.easy_generate_point("1,2", "aquarium", "profiles", tmp_path, None))
    assert result["track_path"] == ""
    assert result["poi_count"] == 2
    assert pathlib.Path(result["poi_path"]).parent == tmp_path
    assert calls[0][0] == "1,2"
    assert calls[0][2:4] == ("aquarium", pathlib.Path("profiles"))
    assert "max_km" not in calls[0][4]  # Profile radius remains in effect.


def test_android_easy_point_radius_override(bridge, monkeypatch, tmp_path):
    calls = []

    def named(location, output_dir, profile_id, profiles_dir=None, **kwargs):
        calls.append(kwargs)
        return str(pathlib.Path(output_dir) / "x.gpx"), []

    monkeypatch.setattr(bridge, "enrich_point_file_named", named)
    result = json.loads(
        bridge.easy_generate_point("1,2", "aquarium", "profiles", tmp_path, None, 5.0)
    )
    assert result["poi_count"] == 0
    assert calls[0]["max_km"] == 5.0


def test_android_easy_point_cancelled(bridge, monkeypatch, tmp_path):
    def named(*args, **kwargs):
        bridge._cancel_event.set()
        return str(tmp_path / "x.gpx"), []

    monkeypatch.setattr(bridge, "enrich_point_file_named", named)
    result = json.loads(bridge.easy_generate_point("1,2", "aquarium", "profiles", tmp_path, None))
    assert result == {"cancelled": True}


@pytest.fixture
def gui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    from gpx_poi_enricher import gui

    app = gui.QApplication.instance() or gui.QApplication([])
    yield gui
    _ = app  # Keep the application alive through the test.


def _fake_named(calls):
    def named(location, output_dir, profile_id, profiles_dir=None, **kwargs):
        calls.append((location, kwargs))
        return str(pathlib.Path(output_dir) / "x.gpx"), [object()]

    return named


def test_desktop_easy_point_worker(gui, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(gui, "enrich_point_file_named", _fake_named(calls))
    worker = gui._EasyWorker([], "aquarium", str(tmp_path), threading.Event(), point_location="1,2")
    results = []
    worker.pois_done.connect(results.append)
    worker.run()
    assert results[0][0][1] == 1
    assert calls[0][0] == "1,2"
    assert "sample_km" not in calls[0][1]
    assert "max_km" not in calls[0][1]


def test_desktop_easy_point_radius_override(gui, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(gui, "enrich_point_file_named", _fake_named(calls))
    worker = gui._EasyWorker(
        [],
        "aquarium",
        str(tmp_path),
        threading.Event(),
        point_location="1,2",
        point_radius=3.5,
    )
    worker.run()
    assert calls[0][1]["max_km"] == 3.5


def test_desktop_easy_point_controls_and_preferences(gui, tmp_path):
    tab = gui._EasyTab()
    tab._source_combo.setCurrentIndex(1)
    tab._point_edit.setText("1,2")
    tab._point_radius.setValue(4.5)
    assert tab._url_box.isHidden()
    assert not tab._point_edit.isHidden()
    assert not tab._point_radius.isHidden()
    assert tab._milestone_parts.isHidden()
    settings = gui.QSettings(str(tmp_path / "gui.ini"), gui.QSettings.Format.IniFormat)
    tab.write_gui_settings(settings)
    restored = gui._EasyTab()
    restored.read_gui_settings(settings)
    assert restored._source_combo.currentData() == "point"
    assert restored._point_edit.text() == "1,2"
    assert restored._point_radius.value() == 4.5
    restored._source_combo.setCurrentIndex(0)
    assert restored._point_edit.isHidden()
    assert restored._point_radius.isHidden()
    assert not restored._url_box.isHidden()


def _stub_routes(module, monkeypatch):
    monkeypatch.setattr(
        module, "_resolve_waypoints", lambda raw, _s: [(0, 0, "Start"), (0, 1, "Finish")]
    )
    monkeypatch.setattr(
        module, "parse_waypoints_from_url", lambda url: [{"name": url}, {"name": "Finish"}]
    )
    monkeypatch.setattr(module, "alternate_redundant_with_prior", lambda *_: True)


class _SilentLog:
    def onLog(self, _message):
        pass


def test_android_changed_route_replaces_stale_cached_track(bridge, monkeypatch, tmp_path):
    _stub_routes(bridge, monkeypatch)
    points = [(0, 0), (0.2, 0.5), (0, 1)]
    monkeypatch.setattr(bridge, "_route_osrm", lambda *_: points)
    monkeypatch.setattr(bridge, "enrich_tracks_to_poi_gpx", lambda *_a, **_k: [])
    first = json.loads(
        bridge.easy_generate("first", "", "camping", "profiles", str(tmp_path), _SilentLog())
    )
    points = [(0, 0), (0.8, 0.5), (0, 1)]
    second = json.loads(
        bridge.easy_generate("second", "", "camping", "profiles", str(tmp_path), _SilentLog())
    )
    import gpxpy

    track = gpxpy.parse(pathlib.Path(first["track_path"]).read_text())
    assert track.tracks[0].segments[0].points[1].latitude == 0.8
    assert second["track_reused"] is False
    third = json.loads(
        bridge.easy_generate("second", "", "camping", "profiles", str(tmp_path), _SilentLog())
    )
    assert third["track_reused"] is True


def test_android_alternates_get_milestone_companions(bridge, monkeypatch, tmp_path):
    _stub_routes(bridge, monkeypatch)
    monkeypatch.setattr(bridge, "_route_osrm", lambda *_: [(0, 0), (0, 1)])
    monkeypatch.setattr(bridge, "enrich_tracks_to_poi_gpx", lambda *_a, **_k: [])
    result = json.loads(
        bridge.easy_generate(
            "primary", "alternate", "camping", "profiles", str(tmp_path), _SilentLog(), 10
        )
    )
    assert len(result["milestone_paths"]) == 2
    assert all(pathlib.Path(path).is_file() for path in result["milestone_paths"])


def test_desktop_changed_route_and_alternate_milestones(gui, monkeypatch, tmp_path):
    _stub_routes(gui, monkeypatch)
    points = [(0, 0), (0.2, 0.5), (0, 1)]
    monkeypatch.setattr(gui, "_route_osrm", lambda *_: points)
    monkeypatch.setattr(gui, "enrich_tracks_to_poi_gpx", lambda *_a, **_k: [])
    worker = gui._EasyWorker(
        ["primary", "alternate"], "camping", str(tmp_path), threading.Event(), split_segments=10
    )
    milestones = []
    worker.milestone_paths_ready.connect(milestones.append)
    worker.run()
    points = [(0, 0), (0.8, 0.5), (0, 1)]
    worker.run()
    import gpxpy

    track = gpxpy.parse((tmp_path / "Start-Finish.gpx").read_text())
    assert track.tracks[0].segments[0].points[1].latitude == 0.8
    assert len(milestones[-1]) == 2


def test_queued_bridge_job_does_not_clear_active_cancellation(bridge, monkeypatch, tmp_path):
    attempting_lock = threading.Event()
    monkeypatch.setattr(
        bridge, "enrich_point_file_named", lambda *_a, **_k: (str(tmp_path / "x.gpx"), [])
    )
    lock = bridge._stderr_lock
    lock.acquire()

    class ObservedLock:
        def __enter__(self):
            attempting_lock.set()
            lock.acquire()

        def __exit__(self, *_):
            lock.release()

    monkeypatch.setattr(bridge, "_stderr_lock", ObservedLock())
    bridge._cancel_event.set()

    def queued():
        bridge.easy_generate_point("0,0", "camping", "profiles", tmp_path, None)

    thread = threading.Thread(target=queued)
    try:
        thread.start()
        assert attempting_lock.wait(1)
        assert bridge._cancel_event.is_set()
    finally:
        lock.release()
        thread.join(2)
    assert not thread.is_alive()


def test_cancelling_queued_job_does_not_cancel_active_job(bridge, monkeypatch, tmp_path):
    active_started = threading.Event()
    release_active = threading.Event()
    active_events = []
    errors = []

    def named(*_args, **kwargs):
        active_events.append(kwargs["cancel_event"])
        active_started.set()
        assert release_active.wait(2)
        return str(tmp_path / "x.gpx"), []

    monkeypatch.setattr(bridge, "enrich_point_file_named", named)

    def run(operation_id):
        try:
            bridge.easy_generate_point(
                "0,0", "camping", "profiles", tmp_path, None, operation_id=operation_id
            )
        except RuntimeError as exc:
            errors.append(str(exc))

    first = threading.Thread(target=run, args=("active",))
    queued = threading.Thread(target=run, args=("queued",))
    first.start()
    try:
        assert active_started.wait(1)
        queued.start()
        bridge.cancel("queued")
        assert not active_events[0].is_set()
    finally:
        release_active.set()
        first.join(2)
        queued.join(2)
    assert errors == ["Operation cancelled by user."]
    assert len(active_events) == 1


def test_profile_form_preserves_nested_filters_and_terms(gui, profiles_dir):
    import dataclasses

    from gpx_poi_enricher.gui_profiles import _ProfileEditorDialog
    from gpx_poi_enricher.profiles import load_profile

    original = dataclasses.replace(
        load_profile("outdoor_pool", profiles_dir), terms={"EN": ["Kids, fun"]}
    )
    dialog = _ProfileEditorDialog(None, profile=original, id_editable=False, title="test")
    dialog._max_km.setValue(7)
    changed = dialog._read_from_form()
    assert changed.max_km == 7
    assert changed.tags == original.tags
    assert changed.terms == original.terms


def test_profile_yaml_changes_survive_switch_to_form(gui, profiles_dir):
    from gpx_poi_enricher.gui_profiles import _ProfileEditorDialog
    from gpx_poi_enricher.profiles import dump_profile_yaml, load_profile

    original = load_profile("mcdonalds", profiles_dir)
    dialog = _ProfileEditorDialog(None, profile=original, id_editable=False, title="test")
    dialog._tabs.setCurrentIndex(1)
    import dataclasses

    edited = dataclasses.replace(original, description="Edited in YAML", max_km=7)
    dialog._yaml_edit.setPlainText(dump_profile_yaml(edited))
    dialog._tabs.setCurrentIndex(0)
    assert dialog._read_from_form() == edited


@pytest.fixture
def custom_profile_manager(gui, monkeypatch, tmp_path, profiles_dir):
    from gpx_poi_enricher import gui_profiles
    from gpx_poi_enricher.profiles import load_profile, save_profile

    custom = tmp_path / "custom"
    custom.mkdir()
    monkeypatch.setenv("GPX_POI_PROFILES_DIR", str(custom))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "normal-config"))
    save_profile(load_profile("camping", profiles_dir), custom)
    monkeypatch.setattr(
        gui_profiles.QMessageBox,
        "question",
        lambda *_a, **_k: gui_profiles.QMessageBox.StandardButton.Yes,
    )
    panel = gui_profiles.ProfilesManagerTab()
    yield gui_profiles, panel, custom
    panel.close()


def test_profile_manager_uses_and_deletes_from_configured_folder(
    custom_profile_manager, monkeypatch
):
    module, panel, custom = custom_profile_manager
    opened = []
    monkeypatch.setattr(
        module.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile())
    )
    panel._open_user_dir()
    assert opened == [str(custom)]
    panel._delete()
    assert not (custom / "camping.yaml").exists()
    assert panel._table.rowCount() == 0


def test_profile_manager_reports_delete_permission_errors(custom_profile_manager, monkeypatch):
    module, panel, custom = custom_profile_manager
    warnings = []

    def denied(*_a, **_k):
        raise PermissionError("Profile directory is read-only")

    monkeypatch.setattr(module, "delete_user_profile", denied)
    monkeypatch.setattr(
        module.QMessageBox, "warning", lambda _p, title, message: warnings.append((title, message))
    )
    panel._delete()
    assert warnings == [("Could not delete", "Profile directory is read-only")]
    assert (custom / "camping.yaml").is_file()


def test_closing_window_keeps_running_worker_alive(gui, monkeypatch, tmp_path):
    from types import SimpleNamespace

    settings = gui.QSettings(str(tmp_path / "state.ini"), gui.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, "_gui_settings", lambda: settings)
    window = gui.MainWindow()
    window._easy_widget._worker = SimpleNamespace(isRunning=lambda: True)
    event = gui.QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    window._easy_widget._worker = None


def test_easy_cancel_before_routing_finishes_worker(gui, tmp_path):
    cancelled = threading.Event()
    cancelled.set()
    worker = gui._EasyWorker(["unneeded"], "camping", str(tmp_path), cancelled)
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert finished == [True]


def test_android_resume_keeps_counts_from_completed_tracks(bridge, monkeypatch, tmp_path):
    primary = tmp_path / "Start-Finish.gpx"
    detour = tmp_path / "Start-Finish-detour-02.gpx"
    primary_pois = tmp_path / "Start-Finish-camping.gpx"
    bridge._write_gpx([], [(0, 0, "POI")] * 3, str(primary_pois), "POIs")
    detour_pois = str(tmp_path / "Start-Finish-detour-02-camping.gpx")
    monkeypatch.setattr(bridge, "enrich_tracks_to_poi_gpx", lambda *_a, **_k: [(detour_pois, 5)])
    result = json.loads(
        bridge.easy_resume_enrichment(
            "camping",
            "profiles",
            str(tmp_path),
            json.dumps([str(primary), str(detour)]),
            1,
            _SilentLog(),
        )
    )
    assert result["poi_count"] == 3
    assert result["detour_results"][0]["poi_count"] == 5


@pytest.mark.parametrize("operation", ["easy", "maps"])
def test_android_routing_closes_its_http_session(bridge, monkeypatch, tmp_path, operation):
    from unittest.mock import Mock

    _stub_routes(bridge, monkeypatch)
    monkeypatch.setattr(bridge, "_route_osrm", lambda *_: [(0, 0), (0, 1)])
    monkeypatch.setattr(bridge, "enrich_tracks_to_poi_gpx", lambda *_a, **_k: [])
    session = Mock()
    monkeypatch.setattr(bridge.requests, "Session", lambda: session)
    if operation == "easy":
        bridge.easy_generate("primary", "", "camping", "profiles", str(tmp_path), _SilentLog())
    else:
        bridge.maps_to_gpx("primary", str(tmp_path / "out.gpx"), "driving", "Track", _SilentLog())
    session.close.assert_called_once()
