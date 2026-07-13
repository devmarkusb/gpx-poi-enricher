#!/usr/bin/env python3
"""Build a macOS .app bundle for the PyQt GUI (Finder icon, Dock, double-click launch).

Requires macOS (sips, iconutil). Output defaults to dist/GPX POI Enricher.app (gitignored).
"""

from __future__ import annotations

import argparse
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ICON_PNG = _REPO / "src/gpx_poi_enricher/data/app_icon.png"
_DEFAULT_OUT = _REPO / "dist/GPX POI Enricher.app"
_BUNDLE_ID = "com.gpxpoienricher.gui"
_APP_NAME = "GPX POI Enricher"
_EXECUTABLE = "gpx-poi-enricher-gui"

_ICONSET_SIZES: list[tuple[int, str]] = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

_LAUNCHER = """\
#!/bin/bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$APP_ROOT/Contents/Resources/gpx-poi-enricher.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

if [[ -n "${GPX_POI_ENRICHER_VENV:-}" ]]; then
  GUI_BIN="${GPX_POI_ENRICHER_VENV}/bin/gpx-poi-enricher-gui"
  if [[ -x "$GUI_BIN" ]]; then
    exec "$GUI_BIN" "$@"
  fi
fi

if command -v gpx-poi-enricher-gui >/dev/null 2>&1; then
  exec gpx-poi-enricher-gui "$@"
fi

osascript -e 'display dialog "Could not find gpx-poi-enricher-gui.\\n\\nFrom a dev clone: uv sync --extra gui, then rebuild with scripts/build_macos_app.py.\\n\\nOr install: pip install \\"gpx-poi-enricher[gui]\\"" buttons {"OK"} default button 1 with icon stop with title "GPX POI Enricher"'
exit 1
"""


def _read_version() -> str:
    text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not read project version from pyproject.toml")
    return match.group(1)


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, check=True, cwd=cwd)


def _build_icns(icon_png: Path, dest_icns: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="gpx-poi-icon-") as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size, name in _ICONSET_SIZES:
            out = iconset / name
            _run(["sips", "-z", str(size), str(size), str(icon_png), "--out", str(out)])
        _run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest_icns)])


def _venv_env_line() -> str:
    venv = _REPO / ".venv"
    gui_bin = venv / "bin" / _EXECUTABLE
    if gui_bin.is_file():
        return f'GPX_POI_ENRICHER_VENV="{venv.resolve()}"\n'
    return ""


def build_app(*, output: Path, venv_hint: bool) -> Path:
    if sys.platform != "darwin":
        raise SystemExit("This script only runs on macOS (needs sips and iconutil).")
    if not _ICON_PNG.is_file():
        raise SystemExit(
            f"Missing {_ICON_PNG}. Run: uv run --with pillow python scripts/generate_brand_assets.py"
        )

    if output.exists():
        shutil.rmtree(output)

    contents = output / "Contents"
    macos_dir = contents / "MacOS"
    resources = contents / "Resources"
    macos_dir.mkdir(parents=True)
    resources.mkdir(parents=True)

    icns_path = resources / "AppIcon.icns"
    _build_icns(_ICON_PNG, icns_path)

    launcher = macos_dir / _EXECUTABLE
    launcher.write_text(_LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)

    if venv_hint:
        env_line = _venv_env_line()
        if env_line:
            (resources / "gpx-poi-enricher.env").write_text(env_line, encoding="utf-8")
        else:
            print(
                "Warning: .venv/bin/gpx-poi-enricher-gui not found; "
                "the .app will look for gpx-poi-enricher-gui on PATH.",
                file=sys.stderr,
            )

    version = _read_version()
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": _EXECUTABLE,
        "CFBundleIconFile": "AppIcon",
        "CFBundleIdentifier": _BUNDLE_ID,
        "CFBundleName": _APP_NAME,
        "CFBundleDisplayName": _APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh)

    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GPX POI Enricher.app for macOS.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output .app path (default: {_DEFAULT_OUT})",
    )
    parser.add_argument(
        "--no-venv-hint",
        action="store_true",
        help="Do not embed a path to this repo's .venv (use PATH / pipx install only).",
    )
    args = parser.parse_args()
    out = args.output
    if out.suffix != ".app":
        raise SystemExit("--output must end with .app")

    app_path = build_app(output=out.resolve(), venv_hint=not args.no_venv_hint)
    print(f"Wrote {app_path}")
    print(f'Open from Finder or: open "{app_path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
