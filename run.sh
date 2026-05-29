#!/usr/bin/env bash
# Back-compat alias — use start.sh
exec "$(dirname "$0")/start.sh" "$@"
