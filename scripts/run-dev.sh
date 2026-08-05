#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

check_only=false
style_options=()
while (($# > 0)); do
    case $1 in
        --check)
            check_only=true
            shift
            ;;
        --style)
            if (($# < 2)); then
                printf 'Missing value after --style; expected modern or nerd.\n' >&2
                exit 2
            fi
            style_options=(--style "$2")
            shift 2
            ;;
        *)
            printf 'Usage: %s [--check] [--style modern|nerd]\n' "$0" >&2
            exit 2
            ;;
    esac
done

missing=()
for command_name in conky python3; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        missing+=("$command_name")
    fi
done

if ((${#missing[@]} > 0)); then
    printf 'Missing required commands: %s\n' "${missing[*]}" >&2
    printf 'No packages were installed. Provide a Conky build with Lua/Cairo support and retry.\n' >&2
    exit 1
fi

dashboard_style=$(python3 -m src.bhola_style "${style_options[@]}")
printf 'Python: %s\n' "$(python3 --version 2>&1)"
printf 'Conky build summary:\n'
conky --version
python3 -m src.bhola_provider --check
python3 -m src.bhola_clickthrough --check
python3 -m src.bhola_monitors --check
python3 -m src.bhola_runtime --check
printf 'Dashboard style: %s\n' "$dashboard_style"

if $check_only; then
    exit 0
fi

state_file=${BHOLA_STATE_FILE:-state/dashboard.json}
mkdir -p -- "$(dirname -- "$state_file")"

provider_pid=
runtime_pid=

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    for process_id in "$runtime_pid" "$provider_pid"; do
        if [[ -n $process_id ]] && kill -0 "$process_id" 2>/dev/null; then
            kill -TERM "$process_id" 2>/dev/null || true
        fi
    done
    for process_id in "$runtime_pid" "$provider_pid"; do
        if [[ -n $process_id ]]; then
            wait "$process_id" 2>/dev/null || true
        fi
    done
    exit "$exit_code"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

python3 -m src.bhola_provider --output "$state_file" &
provider_pid=$!

for _attempt in {1..50}; do
    if ! kill -0 "$provider_pid" 2>/dev/null; then
        wait "$provider_pid"
        printf 'Unified provider stopped before the dashboard started.\n' >&2
        exit 1
    fi
    if [[ -s $state_file ]]; then
        break
    fi
    sleep 0.1
done

if [[ ! -s $state_file ]]; then
    printf 'Unified provider did not create %s in time.\n' "$state_file" >&2
    exit 1
fi

python3 -m src.bhola_runtime --state-file "$state_file" --style "$dashboard_style" &
runtime_pid=$!

set +e
wait -n "$provider_pid" "$runtime_pid"
wait_status=$?
set -e
exit "$wait_status"
