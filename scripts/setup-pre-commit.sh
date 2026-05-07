#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tool_repo_url="https://github.com/devmarkusb/pre-commit.git"
tool_ref="${MB_PRE_COMMIT_REF:-v2.0.0}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

git clone "$tool_repo_url" "$tmp_dir/mb-pre-commit"
git -C "$tmp_dir/mb-pre-commit" checkout --detach "$tool_ref"

python3 "$tmp_dir/mb-pre-commit/python/mb-pre-commit-setup.py" \
  --project-source-dir "$repo_root" \
  --project-binary-dir "$repo_root/.mb-pre-commit-gen" \
  --venv-dir "$repo_root/.venv" \
  --no-install-example-config

# Conventional commit checks (see .pre-commit-config.yaml); mb-pre-commit only installs pre-commit stage.
py="$repo_root/.venv/bin/python3"
if [ -x "$py" ] && "$py" -m pre_commit --version >/dev/null 2>&1; then
  (cd "$repo_root" && "$py" -m pre_commit install --hook-type commit-msg)
else
  echo "Note: install dev deps in .venv then run: pre-commit install --hook-type commit-msg" >&2
fi
