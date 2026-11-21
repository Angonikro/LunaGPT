#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$ROOT/dist"
STAGE="$ROOT/build/deb-root"
VERSION=$(grep '^APP_VERSION = ' "$ROOT/lunagpt/version.py" | cut -d '"' -f 2)
if [ -z "$VERSION" ]; then
  echo "Fehler: APP_VERSION konnte aus lunagpt/version.py nicht gelesen werden." >&2
  exit 1
fi
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/share/lunagpt/lunagpt" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/256x256/apps" "$OUT"
sed "s/^Version: .*/Version: $VERSION/" "$ROOT/debian/control" > "$STAGE/DEBIAN/control"
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
