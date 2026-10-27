"""Offline regressions for interrupted enrichment and output publication."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from gpx_poi_enricher import enricher
from gpx_poi_enricher.enrich_checkpoint import has_checkpoint
from gpx_poi_enricher.gpx_utils import GPX_NS


@pytest.fixture
def offline_enrichment(monkeypatch, sample_gpx_path, profiles_dir, tmp_path):
    monkeypatch.setattr(enricher.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        enricher, "detect_country_segments", lambda pts, *_args, **_kwargs: {"EN": pts}
    )
    response = {
        "elements": [
            {"type": "node", "id": 7, "lat": 48.1351, "lon": 11.582, "tags": {"name": "Test POI"}}
        ]
    }
    monkeypatch.setattr(enricher, "query_overpass", lambda *_args, **_kwargs: response)
    output = tmp_path / "pois.gpx"
    kwargs = dict(
        profile_id="camping",
        profiles_dir=profiles_dir,
        progress_interval=0,
        checkpoint_each_batch=True,
        early_cancel_if_no_pois=False,
        batch_size=1,
        sample_km=0.001,
    )
    return sample_gpx_path, output, kwargs, response


def _interrupt(monkeypatch, setup):
    source, output, kwargs, response = setup
    calls = 0

    def query(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Simulated network failure")
        return response

    monkeypatch.setattr(enricher, "query_overpass", query)
    with pytest.raises(enricher.EnrichInterrupted):
        enricher.enrich_gpx_file(source, output, **kwargs)
    assert has_checkpoint(output)
    monkeypatch.setattr(enricher, "query_overpass", lambda *_args, **_kwargs: response)


@pytest.mark.parametrize("changed", [{"max_km": 20}, {"batch_size": 2}])
def test_resume_rejects_different_search(monkeypatch, offline_enrichment, changed):
    _interrupt(monkeypatch, offline_enrichment)
    source, output, kwargs, _ = offline_enrichment
    with pytest.raises((ValueError, enricher.EnrichInterrupted), match="changed|match"):
        enricher.enrich_gpx_file(source, output, resume=True, **{**kwargs, **changed})
    assert has_checkpoint(output)


def test_resume_requires_its_poi_snapshot(monkeypatch, offline_enrichment):
    _interrupt(monkeypatch, offline_enrichment)
    source, output, kwargs, _ = offline_enrichment
    output.unlink()
    with pytest.raises(FileNotFoundError, match="snapshot|GPX"):
        enricher.enrich_gpx_file(source, output, resume=True, **kwargs)


def test_failed_final_write_preserves_snapshot_and_resume(monkeypatch, offline_enrichment):
    source, output, kwargs, _ = offline_enrichment
    write = ET.ElementTree.write
    calls = 0

    def failing_write(tree, path, *args, **kw):
        nonlocal calls
        calls += 1
        if calls == 6:
            Path(path).write_text("interrupted write")
            raise OSError("Simulated full disk")
        return write(tree, path, *args, **kw)

    monkeypatch.setattr(ET.ElementTree, "write", failing_write)
    with pytest.raises((OSError, enricher.EnrichInterrupted), match="full disk"):
        enricher.enrich_gpx_file(source, output, **kwargs)
    assert has_checkpoint(output)
    assert ET.parse(output).getroot().findall(f"{{{GPX_NS}}}wpt")


def test_resume_does_not_reclassify_original_stops_as_pois(
    monkeypatch, offline_enrichment, tmp_path
):
    source, output, kwargs, response = offline_enrichment
    root = ET.parse(source).getroot()
    stop = ET.Element(f"{{{GPX_NS}}}wpt", lat="48.1351", lon="11.5820")
    ET.SubElement(stop, f"{{{GPX_NS}}}name").text = "Original stop"
    root.insert(0, stop)
    copied = tmp_path / "with-stop.gpx"
    ET.ElementTree(root).write(copied)
    setup = str(copied), output, kwargs, response
    _interrupt(monkeypatch, setup)
    items = enricher.enrich_gpx_file(copied, output, resume=True, **kwargs)
    assert [item["name"] for item in items] == ["Test POI"]
    names = [
        el.text for el in ET.parse(output).getroot().findall(f"{{{GPX_NS}}}wpt/{{{GPX_NS}}}name")
    ]
    assert names.count("Original stop") == 1


def test_resume_rejects_changed_original_waypoints(monkeypatch, offline_enrichment, tmp_path):
    source, output, kwargs, response = offline_enrichment
    copied = tmp_path / "source.gpx"
    copied.write_bytes(Path(source).read_bytes())
    setup = str(copied), output, kwargs, response
    _interrupt(monkeypatch, setup)
    root = ET.parse(copied).getroot()
    root.insert(0, ET.Element(f"{{{GPX_NS}}}wpt", lat="48", lon="11"))
    ET.ElementTree(root).write(copied)
    with pytest.raises((ValueError, enricher.EnrichInterrupted), match="changed|match"):
        enricher.enrich_gpx_file(copied, output, resume=True, **kwargs)
