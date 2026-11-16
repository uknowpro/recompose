#!/bin/sh
# Maintainer build: Docker is needed here, never on the end user's machine.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT=${1:-"$ROOT/dist/native"}
if [ -e "$OUTPUT" ]; then
    echo 'Output exists; choose a new directory.' >&2
    exit 1
fi
docker buildx build --platform linux/amd64 --file "$ROOT/tools/Dockerfile.native" \
    --output "type=local,dest=$OUTPUT" "$ROOT"
