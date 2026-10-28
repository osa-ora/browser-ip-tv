#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
action="${1:-start}"

if [[ "$action" == "start" || "$action" == "run" ]]; then
  if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
  .venv/bin/python -m pip install -r requirements.txt
  LOCAL_IPTV_PYTHON="$PWD/.venv/bin/python" exec python3 launcher.py "$action"
fi

if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python launcher.py "$action"
fi
exec python3 launcher.py "$action"
