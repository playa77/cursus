#!/usr/bin/env bash
# Cursus installer launcher (ADR 0017). Run from a checkout, as your own user (not root):
#   git clone https://github.com/playa77/cursus.git && cd cursus && ./install.sh --help
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
  echo "Cursus needs Python 3.12 or newer as python3 (found: $(python3 --version 2>&1 || echo none))." >&2
  exit 1
fi
exec python3 deploy/install.py "$@"
