"""CLI wrapper around add-split-waypoints functionality."""

from __future__ import annotations

import sys


def main() -> None:
    # Delegate to the standalone script which uses gpxpy
    import importlib.util
    import pathlib

    script = pathlib.Path(__file__).parent.parent.parent / "add-split-waypoints.py"
    if not script.exists():
        print(f"Error: {script} not found", file=sys.stderr)
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("add_split_waypoints", script)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.main()


if __name__ == "__main__":
    main()
