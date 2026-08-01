#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

python3 scripts/privacy-check.py
python3 -m compileall -q src tests
python3 -m unittest discover -s tests -v
python3 -m src.bhola_provider --check
bash -n scripts/run-dev.sh scripts/check.sh scripts/build-deb.sh packaging/bhola-pulse

printf 'All environment-independent checks passed.\n'
