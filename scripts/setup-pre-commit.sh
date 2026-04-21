#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ensure the tooling submodule is available at the pinned revision.
git -C "$repo_root" submodule update --init --recursive tools/mb-pre-commit

exec python3 "$repo_root/tools/mb-pre-commit/python/mb-pre-commit-setup.py" \
  --project-source-dir "$repo_root" \
  --project-binary-dir "$repo_root/.mb-pre-commit-gen" \
  --venv-dir "$repo_root/.venv" \
  --no-install-example-config
