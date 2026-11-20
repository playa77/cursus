#!/bin/sh
# 2026-11-20-r1
set -eu
exec python3 "$(dirname "$(readlink -f "$0")")/setup.py" control "$@"
