#!/bin/sh
set -e

# If a Python Lambda handler is passed as the single command argument
if [ "$#" -eq 1 ] && echo "$1" | grep -qE '^[a-zA-Z0-9_.]+\.[a-zA-Z0-9_]+$'; then
    exec python -m awslambdaric "$1"
fi

exec "$@"
