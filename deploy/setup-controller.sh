#!/bin/sh
# Cursus setup revision 2026-11-20-r3
set -eu
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/setup.py" controller "$@"
