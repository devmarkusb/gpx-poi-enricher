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

    def enrich(location, output, profile, profiles_dir, **kwargs):
        calls.append((location, output, profile, profiles_dir, kwargs))
        return [object(), object()]

    monkeypatch.setattr(bridge, "enrich_point_file", enrich)
    result = json.loads(bridge.easy_generate_point("1,2", "aquarium", "profiles", tmp_path, None))
    assert result["track_path"] == ""
    assert result["poi_count"] == 2
    assert pathlib.Path(result["poi_path"]).parent == tmp_path
    assert calls[0][:1] == ("1,2",)
    assert calls[0][2:4] == ("aquarium", pathlib.Path("profiles"))
    assert "max_km" not in calls[0][4]  # Profile radius remains in effect.


def test_android_easy_point_cancelled(bridge, monkeypatch, tmp_path):
    def enrich(*args, **kwargs):
        bridge._cancel_event.set()
        return []

    monkeypatch.setattr(bridge, "enrich_point_file", enrich)
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


def test_desktop_easy_point_worker(gui, monkeypatch, tmp_path):
    calls = []

    def enrich(*args, **kwargs):
        calls.append((args, kwargs))
        return [object()]

    monkeypatch.setattr(gui, "enrich_point_file", enrich)
    worker = gui._EasyWorker([], "aquarium", str(tmp_path), threading.Event(), point_location="1,2")
    results = []
    worker.pois_done.connect(results.append)
    worker.run()
    assert results[0][0][1] == 1
    assert calls[0][0][0] == "1,2"
    assert "sample_km" not in calls[0][1]
    assert "max_km" not in calls[0][1]


def test_desktop_easy_point_controls_and_preferences(gui, tmp_path):
    tab = gui._EasyTab()
    tab._source_combo.setCurrentIndex(1)
    tab._point_edit.setText("1,2")
    assert tab._url_box.isHidden()
    assert not tab._point_edit.isHidden()
    assert tab._milestone_parts.isHidden()
    settings = gui.QSettings(str(tmp_path / "gui.ini"), gui.QSettings.Format.IniFormat)
    tab.write_gui_settings(settings)
    restored = gui._EasyTab()
    restored.read_gui_settings(settings)
    assert restored._source_combo.currentData() == "point"
    assert restored._point_edit.text() == "1,2"
    restored._source_combo.setCurrentIndex(0)
    assert restored._point_edit.isHidden()
    assert not restored._url_box.isHidden()
