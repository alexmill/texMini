#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ] && [ -d /work ]; then
  work_uid="$(stat -c %u /work)"
  work_gid="$(stat -c %g /work)"

  if [ "$work_uid" -ne 0 ] || [ "$work_gid" -ne 0 ]; then
    exec setpriv --reuid "$work_uid" --regid "$work_gid" --clear-groups texmini "$@"
  fi
fi

exec texmini "$@"
