#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

python3 scripts/privacy-check.py
python3 -m compileall -q src tests
python3 -m unittest discover -s tests -v
if command -v lua5.3 >/dev/null 2>&1; then
    lua5.3 tests/test_surface_compat.lua
elif [[ ${CI:-false} == true ]]; then
    printf 'Lua 5.3 is mandatory for Cairo compatibility tests in CI.\n' >&2
    exit 1
else
    printf 'SKIP: Lua surface tests (install lua5.3 to run them).\n' >&2
fi
python3 -m src.bhola_provider --check
bash -n \
    scripts/run-dev.sh \
    scripts/check.sh \
    scripts/build-deb.sh \
    packaging/bhola-pulse \
    debian/build-ppa-source \
    debian/build-pr-source

printf 'All environment-independent checks passed.\n'
