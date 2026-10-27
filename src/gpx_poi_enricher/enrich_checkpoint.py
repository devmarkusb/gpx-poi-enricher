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
    run_fingerprint: str | None = None,
) -> None:
    path = checkpoint_path(output_gpx)
    payload = {
        "version": _VERSION,
        "last_completed_batch": last_completed_batch,
        "total_batches": total_batches,
        "run_fingerprint": run_fingerprint,
    }
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_checkpoint_data(output_gpx: str | pathlib.Path) -> dict:
    path = checkpoint_path(output_gpx)
    if not path.is_file():
        raise FileNotFoundError(f"No enrichment checkpoint at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid enrichment checkpoint: expected an object")
    if data.get("version") != _VERSION:
        raise ValueError(f"Unsupported checkpoint version: {data.get('version')!r}")
    last, total = data["last_completed_batch"], data["total_batches"]
    if type(last) is not int or type(total) is not int or not 0 <= last <= total or total < 1:
        raise ValueError("Invalid enrichment checkpoint batch counters")
    return data


def read_checkpoint(output_gpx: str | pathlib.Path) -> tuple[int, int]:
    data = _read_checkpoint_data(output_gpx)
    return data["last_completed_batch"], data["total_batches"]


def read_checkpoint_fingerprint(output_gpx: str | pathlib.Path) -> str | None:
    return _read_checkpoint_data(output_gpx).get("run_fingerprint")


def clear_checkpoint(output_gpx: str | pathlib.Path) -> None:
    checkpoint_path(output_gpx).unlink(missing_ok=True)
