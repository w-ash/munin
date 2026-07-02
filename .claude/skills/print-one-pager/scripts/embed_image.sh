#!/usr/bin/env bash
# embed_image.sh <image-url-or-path> [max_px] [--css]
#
# Turns an image into a paste-ready data: URI so the one-pager stays self-contained.
# Downloads (or reads a local file), resizes so the longest side is max_px, converts
# to JPEG, and prints the data URI to stdout:
#
#   default:  a full <img> tag      <img src="data:image/jpeg;base64,..." alt="">
#   --css:    a bare url() value    url(data:image/jpeg;base64,...)
#
#   max_px (optional, default 1200): longest-side pixel cap. 1200px covers the
#   full 7.6in sheet width at ~158dpi, sharp enough for print while keeping the
#   base64 payload reasonable; use ~600 for half-column images.
#
# Examples:
#   ./embed_image.sh "https://example.com/photo.jpg" 800
#   ./embed_image.sh scan.png 600 --css
#
# macOS (uses `sips`), plus `curl` for URLs. Prefer official/public-domain sources.

set -euo pipefail

SRC="${1:-}"
MAX_PX="${2:-1200}"
MODE="${3:-img}"
if [ -z "$SRC" ]; then
  echo "usage: embed_image.sh <image-url-or-path> [max_px] [--css]" >&2
  exit 2
fi
case "$MAX_PX" in
  ''|*[!0-9]*) echo "ERROR: max_px must be a positive integer, got '$MAX_PX'" >&2; exit 2 ;;
esac

command -v sips >/dev/null || { echo "embed_image.sh needs sips (macOS)" >&2; exit 3; }

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
RAW="$TMP_DIR/raw"
JPG="$TMP_DIR/out.jpg"

case "$SRC" in
  http://*|https://*)
    # -f fails on HTTP errors so a 404 page never gets embedded as an "image".
    if ! curl -fsSL "$SRC" -o "$RAW"; then
      echo "ERROR: download failed: $SRC" >&2
      exit 4
    fi
    ;;
  *)
    [ -f "$SRC" ] || { echo "ERROR: no such file: $SRC" >&2; exit 4; }
    cp "$SRC" "$RAW"
    ;;
esac

# -Z caps the longest side (never upscales); JPEG keeps the base64 payload far
# smaller than PNG for photos, which is what one-pagers embed.
if ! sips -Z "$MAX_PX" -s format jpeg "$RAW" --out "$JPG" >/dev/null 2>&1; then
  echo "ERROR: sips could not convert $SRC (not an image, or unsupported format)" >&2
  exit 5
fi

B64="$(base64 -i "$JPG")"
if [ "$MODE" = "--css" ]; then
  printf 'url(data:image/jpeg;base64,%s)\n' "$B64"
else
  printf '<img src="data:image/jpeg;base64,%s" alt="">\n' "$B64"
fi