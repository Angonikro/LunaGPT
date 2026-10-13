#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$ROOT/dist"
STAGE="$ROOT/build/deb-root"
VERSION="1.10.1"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/share/lunagpt/lunagpt" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/256x256/apps" "$OUT"
cp "$ROOT/debian/control" "$STAGE/DEBIAN/control"
chmod g-s "$STAGE/DEBIAN" || true
chmod 755 "$STAGE/DEBIAN"
cp "$ROOT/bin/lunagpt" "$STAGE/usr/bin/lunagpt"
chmod 755 "$STAGE/usr/bin/lunagpt"
cp "$ROOT/lunagpt/"*.py "$STAGE/usr/share/lunagpt/lunagpt/"
cp "$ROOT/requirements.txt" "$STAGE/usr/share/lunagpt/requirements.txt"
cp "$ROOT/share/applications/lunagpt.desktop" "$STAGE/usr/share/applications/"
cp "$ROOT/share/icons/hicolor/256x256/apps/lunagpt.svg" "$STAGE/usr/share/icons/hicolor/256x256/apps/"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT/lunagpt_${VERSION}_all.deb"
echo "Built: $OUT/lunagpt_${VERSION}_all.deb"
