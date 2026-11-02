#!/usr/bin/env bash
set -euo pipefail

SOLUTION_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SOLUTION_DIR/reference.py" --witness "${COLOR_WITNESS:-green_to_target}"
