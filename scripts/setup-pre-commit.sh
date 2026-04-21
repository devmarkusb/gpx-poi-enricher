#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tool_repo_url="https://github.com/devmarkusb/pre-commit.git"
tool_ref="${MB_PRE_COMMIT_REF:-v2.0.0}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

git clone "$tool_repo_url" "$tmp_dir/mb-pre-commit"
git -C "$tmp_dir/mb-pre-commit" checkout --detach "$tool_ref"

exec python3 "$tmp_dir/mb-pre-commit/python/mb-pre-commit-setup.py" \
  --project-source-dir "$repo_root" \
  --project-binary-dir "$repo_root/.mb-pre-commit-gen" \
  --venv-dir "$repo_root/.venv" \
  --no-install-example-config
