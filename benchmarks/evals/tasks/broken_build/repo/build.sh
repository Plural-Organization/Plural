#!/bin/sh
set -e
. ./env.sh
mkdir -p "$OUT"
python3 tools/render.py "$TEMPLATE" > "$OUT/index.html"
