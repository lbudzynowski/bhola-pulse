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
                printf 'Missing value after --style; expected modern, nerd, or cinematic.\n' >&2
                exit 2
            fi
            style_options=(--style "$2")
            shift 2
            ;;
        *)
            printf 'Usage: %s [--check] [--style modern|nerd|cinematic]\n' "$0" >&2
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
printf 'Dashboard style: %s\n' "$dashboard_style"

if $check_only; then
    exit 0
fi

state_file=${BHOLA_STATE_FILE:-state/dashboard.json}
mkdir -p -- "$(dirname -- "$state_file")"

provider_pid=
conky_pids=()

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    for process_id in "${conky_pids[@]}" "$provider_pid"; do
        if [[ -n $process_id ]] && kill -0 "$process_id" 2>/dev/null; then
            kill -TERM "$process_id" 2>/dev/null || true
        fi
    done
    for process_id in "${conky_pids[@]}" "$provider_pid"; do
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

read -r -a monitor_indices <<<"$(python3 -m src.bhola_monitors --indices)"
render_interval=$(python3 -m src.bhola_monitors --render-interval "${#monitor_indices[@]}")
if [[ $dashboard_style == cinematic ]]; then
    render_interval=0.05
fi
default_scale=${BHOLA_SCALE:-1.25}
if [[ ! $default_scale =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]]; then
    printf 'Invalid BHOLA_SCALE=%q; using 1.25.\n' "$default_scale" >&2
    default_scale=1.25
fi

printf 'Starting Bhola Pulse V2 %s on %d active monitor(s) at %s s; use Ctrl+C to stop all processes.\n' "$dashboard_style" "${#monitor_indices[@]}" "$render_interval"
for monitor_index in "${monitor_indices[@]}"; do
    window_title="conky (Bhola ${monitor_index})"
    scale_variable="BHOLA_SCALE_HEAD_${monitor_index}"
    monitor_scale=$default_scale
    if [[ -v $scale_variable ]]; then
        monitor_scale=${!scale_variable}
    fi
    if [[ ! $monitor_scale =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]]; then
        printf 'Invalid %s=%q; using %s.\n' "$scale_variable" "$monitor_scale" "$default_scale" >&2
        monitor_scale=$default_scale
    fi
    printf 'Starting monitor head %s at scale %s.\n' "$monitor_index" "$monitor_scale"
    BHOLA_WINDOW_TITLE="$window_title" BHOLA_UPDATE_INTERVAL="$render_interval" BHOLA_SCALE="$monitor_scale" BHOLA_STYLE="$dashboard_style" BHOLA_STATE_FILE="$state_file" conky --config=conky/bhola-pulse.conf --xinerama-head="$monitor_index" &
    conky_pid=$!
    conky_pids+=("$conky_pid")
    if ! python3 -m src.bhola_clickthrough --pid "$conky_pid" --name "$window_title"; then
        printf 'Could not make dashboard instance %s click-through.\n' "$monitor_index" >&2
        exit 1
    fi
done

set +e
wait -n "$provider_pid" "${conky_pids[@]}"
wait_status=$?
set -e
exit "$wait_status"
