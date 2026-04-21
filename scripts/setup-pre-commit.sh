#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_python="$repo_root/.venv/bin/python"
venv_precommit="$repo_root/.venv/bin/pre-commit"

if [[ ! -x "$venv_python" ]]; then
  python3 -m venv "$repo_root/.venv"
fi

if ! "$venv_python" -m pip --version >/dev/null 2>&1; then
  "$venv_python" -m ensurepip --upgrade
fi

"$venv_python" -m pip install --upgrade pip pre-commit
exec "$venv_precommit" install --install-hooks
