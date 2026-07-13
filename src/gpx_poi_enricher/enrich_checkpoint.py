"""Minimal batch checkpoint for resuming interrupted POI enrichment."""

from __future__ import annotations

import json
import pathlib

CHECKPOINT_EXT = ".enrich-checkpoint.json"
_VERSION = 1


def checkpoint_path(output_gpx: str | pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(output_gpx)
    return p.with_name(f"{p.stem}{CHECKPOINT_EXT}")


def has_checkpoint(output_gpx: str | pathlib.Path) -> bool:
    return checkpoint_path(output_gpx).is_file()


def write_checkpoint(
    output_gpx: str | pathlib.Path,
    *,
    last_completed_batch: int,
    total_batches: int,
) -> None:
    path = checkpoint_path(output_gpx)
    payload = {
        "version": _VERSION,
        "last_completed_batch": last_completed_batch,
        "total_batches": total_batches,
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def read_checkpoint(output_gpx: str | pathlib.Path) -> tuple[int, int]:
    path = checkpoint_path(output_gpx)
    if not path.is_file():
        raise FileNotFoundError(f"No enrichment checkpoint at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != _VERSION:
        raise ValueError(f"Unsupported checkpoint version: {data.get('version')!r}")
    return int(data["last_completed_batch"]), int(data["total_batches"])


def clear_checkpoint(output_gpx: str | pathlib.Path) -> None:
    checkpoint_path(output_gpx).unlink(missing_ok=True)
