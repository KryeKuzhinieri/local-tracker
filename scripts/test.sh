#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run black --check .
uv run mypy
uv run pytest
./scripts/check-no-personal-data.sh
