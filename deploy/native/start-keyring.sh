#!/bin/sh
# Private in-container Secret Service; never connects to a host session bus.
set -eu
mkdir -p /tmp/cursus-runtime
chmod 700 /tmp/cursus-runtime
export XDG_RUNTIME_DIR=/tmp/cursus-runtime
export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/cursus-session-bus
if [ ! -S /tmp/cursus-session-bus ]; then
  dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork --nopidfile
fi
# The dedicated keyring belongs to this credential domain only. Its host
# directory is private; an empty unlock password permits unattended native use.
printf '\n' | gnome-keyring-daemon --unlock --components=secrets >/dev/null
