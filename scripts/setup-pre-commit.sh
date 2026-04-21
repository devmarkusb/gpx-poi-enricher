#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tool_repo_url="https://github.com/devmarkusb/pre-commit.git"
tool_ref="${MB_PRE_COMMIT_REF:-v1.9.0}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
hooks_dir="$(git -C "$repo_root" rev-parse --git-path hooks)"
venv_python="$repo_root/.venv/bin/python"
venv_precommit="$repo_root/.venv/bin/pre-commit"

git clone --depth 1 --branch "$tool_ref" "$tool_repo_url" "$tmp_dir/mb-pre-commit"

python3 "$tmp_dir/mb-pre-commit/python/mb-pre-commit-setup.py" \
  --project-source-dir "$repo_root" \
  --project-binary-dir "$repo_root/.mb-pre-commit-gen" \
  --venv-dir "$repo_root/.venv" \
  --no-install-example-config

# Worktrees expose .git as a file; mb-pre-commit currently skips those trees.
if [[ ! -f "$hooks_dir/pre-commit" ]]; then
  if [[ ! -x "$venv_python" ]]; then
    python3 -m venv "$repo_root/.venv"
  fi
  if ! "$venv_python" -m pip --version >/dev/null 2>&1; then
    "$venv_python" -m ensurepip --upgrade
  fi
  "$venv_python" -m pip install --upgrade pip pre-commit
  exec "$venv_precommit" install --install-hooks
fi
