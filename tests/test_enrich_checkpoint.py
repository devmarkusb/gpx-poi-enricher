"""Tests for enrich_checkpoint sidecar files."""

from __future__ import annotations

import json

import pytest

from gpx_poi_enricher.enrich_checkpoint import (
    CHECKPOINT_EXT,
    checkpoint_path,
    clear_checkpoint,
    has_checkpoint,
    read_checkpoint,
    write_checkpoint,
)


def test_checkpoint_path_suffix(tmp_path):
    out = tmp_path / "route-zoo.gpx"
    assert checkpoint_path(out).name == f"route-zoo{CHECKPOINT_EXT}"


def test_write_read_and_clear_checkpoint(tmp_path):
    out = tmp_path / "out.gpx"
    write_checkpoint(out, last_completed_batch=3, total_batches=10)
    assert has_checkpoint(out)
    last, total = read_checkpoint(out)
    assert last == 3
    assert total == 10
    data = json.loads(checkpoint_path(out).read_text(encoding="utf-8"))
    assert data["version"] == 1
    clear_checkpoint(out)
    assert not has_checkpoint(out)


def test_read_checkpoint_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_checkpoint(tmp_path / "missing.gpx")
