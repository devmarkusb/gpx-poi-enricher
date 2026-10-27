"""The launcher environment must preserve paths as literal shell strings."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest


def test_venv_hint_preserves_shell_characters(monkeypatch, tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to check the launcher")
    script = Path(__file__).parents[1] / "scripts/build_macos_app.py"
    spec = importlib.util.spec_from_file_location("build_macos_app", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = tmp_path / "route $UNSET_AUDIT_VALUE $(false) directory"
    binary = repo / ".venv/bin/gpx-poi-enricher-gui"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(module, "_REPO", repo)
    env_file = tmp_path / "launcher.env"
    env_file.write_text(module._venv_env_line())
    result = subprocess.run(
        [bash, "-c", 'source "$1"; printf "%s" "$GPX_POI_ENRICHER_VENV"', "test", str(env_file)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == str(repo / ".venv")
