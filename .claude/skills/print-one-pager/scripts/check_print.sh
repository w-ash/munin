#!/usr/bin/env bash
# check_print.sh <file.html> [out_dir]
#
# Verifies a one-pager actually fits ONE printable page, in BOTH print and screen media.
# Page count alone is not enough: a doc can be one page in print media yet spill to two when
# a tool exports the SCREEN view. So this checks three signals:
#
#   1. true content height  (sheet measured with min-height removed)  -> headroom vs printable area
#   2. screen document height (body as the browser lays it out)       -> catches a too-tall sheet
#   3. print-media page count (Chromium --print-to-pdf)               -> the print path
#
# PASS requires all three. Also emits a print PNG and a screen PNG to inspect by eye.
#
# Note on enforcement: the single-page guarantee lives in THIS check, not in document clipping.
# The sheet is allowed to grow (no overflow:hidden), so overrun surfaces as a height/page FAIL
# instead of being silently cut off. Because template content lives inside .sheet with no body
# margins, the screen-document height only exceeds the page when true content already does.
#
# macOS. Uses any Chromium browser (Brave / Chrome / Chromium / Edge), `sips`, and python3.

set -euo pipefail

# Fail with a clear message rather than a bare `set -e` crash mid-run: python3 is
# used throughout (geometry parsing, probe injection, PDF page count, verdict math)
# and stock macOS doesn't guarantee it.
command -v python3 >/dev/null || { echo "check_print.sh needs python3 on PATH" >&2; exit 3; }

# Virtual-time budget for the headless render: long enough for @import web fonts
# to download and apply before heights are measured (see reference.md on fonts).
FONT_LOAD_MS=5000
# Screen-screenshot geometry: 900x1180 CSS px approximates the sheet's on-screen
# aspect at 96dpi, and 1.5x device scale keeps the PNG legible for eyeballing.
# These only affect the inspection PNG, never the PASS/FAIL math.
SCREEN_W=900; SCREEN_H=1180; SCALE=1.5

HTML="${1:-}"
if [ -z "$HTML" ] || [ ! -f "$HTML" ]; then
  echo "usage: check_print.sh <file.html> [out_dir]" >&2; exit 2
fi
ABS="$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")"
URL="file://$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$ABS")"
OUT="${2:-/tmp/print-check}"; mkdir -p "$OUT"
PDF="$OUT/print.pdf"; PRINT_PNG="$OUT/print.png"; SCREEN_PNG="$OUT/screen.png"; PROBE="$OUT/probe.html"

# --- read the page geometry from the file itself (don't assume one fixed layout) ---
# Parses the @page block for `margin: <N>in` and `size:` (letter vs a4); falls back to
# Letter / 0.4in margins when absent.
PAGE_INFO="$(python3 - "$ABS" <<'PY'
import re, sys
h = open(sys.argv[1], encoding='utf-8', errors='replace').read()
m = re.search(r'@page\s*\{([^}]*)\}', h, re.S)
block = m.group(1) if m else ''
mar = re.search(r'margin:\s*([0-9.]+)\s*in', block)
margin = float(mar.group(1)) if mar else 0.4
size = re.search(r'size:\s*([a-zA-Z0-9]+)', block)
paper = size.group(1).lower() if size else 'letter'
# Only page HEIGHT is gated here; width overrun surfaces via the print page count.
H = 11.69 if paper == 'a4' else 11.0
print(f"{margin} {H} {paper} {1 if m else 0}")
PY
)"
read -r MARGIN PH PAPER HAS_PAGE <<<"$PAGE_INFO"
PRINTABLE_IN="$(python3 -c "print(round($PH - 2*$MARGIN, 2))")"          # usable height
SAFE_CONTENT_IN="$(python3 -c "print(round($PRINTABLE_IN - 0.4, 2))")"   # 0.4in headroom buffer

BROWSER=""
for cand in \
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
  [ -x "$cand" ] && { BROWSER="$cand"; break; }
done
if [ -z "$BROWSER" ]; then
  echo "No Chromium browser found. Open the file and use Cmd+P -> Save as PDF to check by eye:" >&2
  echo "  $ABS" >&2; exit 3
fi
COMMON=(--headless=new --disable-gpu --virtual-time-budget="$FONT_LOAD_MS")

# 1+2) Measure heights in screen media. Neutralize min-height for TRUE content height; read
#      body.scrollHeight for the as-laid-out screen-document height. Probe is injected before
#      </body> (case-insensitive), else </html>, else appended (a trailing script still runs).
python3 - "$ABS" "$PROBE" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
h = open(src, encoding='utf-8', errors='replace').read()
probe = ("<script>window.addEventListener('load',function(){"
         "var s=document.querySelector('.sheet'),w=0;"
         "if(!s){s=document.body;w=1;}"
         "var screenDoc=document.body.scrollHeight;"
         "s.style.minHeight='0';s.style.height='auto';"
         "var natural=s.scrollHeight;"
         "document.title='PROBE natural='+natural+' screenDoc='+screenDoc+' wrap='+w;});</script>")
low = h.lower()
for tag in ('</body>', '</html>'):
    i = low.rfind(tag)
    if i != -1:
        h = h[:i] + probe + h[i:]; break
else:
    h = h + probe
open(dst, 'w', encoding='utf-8').write(h)
PY
PURL="file://$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$PROBE")"
DUMP="$("$BROWSER" "${COMMON[@]}" --dump-dom "$PURL" 2>/dev/null || true)"
LINE="$(printf '%s' "$DUMP" | grep -oE 'PROBE natural=[0-9]+ screenDoc=[0-9]+ wrap=[01]' | head -1 || true)"
NAT_PX="$(printf '%s' "$LINE" | grep -oE 'natural=[0-9]+' | grep -oE '[0-9]+' || echo 0)"
SCR_PX="$(printf '%s' "$LINE" | grep -oE 'screenDoc=[0-9]+' | grep -oE '[0-9]+' || echo 0)"
WRAP="$(printf '%s' "$LINE" | grep -oE 'wrap=[01]' | grep -oE '[01]' || echo 0)"

# 3) Print media -> PDF page count + PNG. Count actual /Type /Page objects; fall back to the
#    last /Count only if those are inside compressed object streams.
rm -f "$PDF"
"$BROWSER" "${COMMON[@]}" --no-pdf-header-footer --print-to-pdf="$PDF" "$URL" >/dev/null 2>&1 || true
PAGES="?"
if [ -f "$PDF" ]; then
  PAGES="$(python3 -c "
import re,sys
d=open(sys.argv[1],'rb').read()
n=len(re.findall(rb'/Type\s*/Page(?![s])',d))
if n==0:
    m=re.findall(rb'/Count\s+(\d+)',d); n=int(m[-1]) if m else 0
print(n or '?')" "$PDF")"
  sips -s format png "$PDF" --out "$PRINT_PNG" >/dev/null 2>&1 || true
fi

# Screen screenshot
"$BROWSER" "${COMMON[@]}" --hide-scrollbars --force-device-scale-factor="$SCALE" \
  --window-size="$SCREEN_W,$SCREEN_H" --screenshot="$SCREEN_PNG" "$URL" >/dev/null 2>&1 || true

# Distinguish "measurement failed" from "content too small"
if [ "$NAT_PX" = "0" ] || [ "$SCR_PX" = "0" ]; then
  echo "WARNING: probe returned 0 height - the measurement may not have run (font/network hang, or" >&2
  echo "         an unusual document). Heights below are unreliable; inspect the PNGs by eye." >&2
fi
[ "$WRAP" = "1" ] && echo "WARNING: no .sheet element found; measured <body> instead. Wrap content in .sheet for an accurate reading." >&2
[ "$HAS_PAGE" = "0" ] && echo "NOTE: no @page rule found; assuming $PAPER paper with ${MARGIN}in margins." >&2

# Verdict (guarded: if the math python errors, surface it instead of a blank report)
VERDICT_OUT="$(python3 -c "
nat=$NAT_PX/96.0; scr=$SCR_PX/96.0; printable=$PRINTABLE_IN; safe=$SAFE_CONTENT_IN
print(f'{nat:.2f} {scr:.2f} {safe-nat:.2f} {int(nat<=safe and nat>0)} {int(scr<=printable and scr>0)}')
" 2>/dev/null || true)"
if ! printf '%s' "$VERDICT_OUT" | grep -qE '^[0-9.]+ -?[0-9.]+ -?[0-9.]+ [01] [01]$'; then
  echo "ERROR: could not compute verdict (nat=${NAT_PX}px scr=${SCR_PX}px). Inspect the file by eye." >&2
  exit 4
fi
read -r NAT SCR HEAD C_OK S_OK <<<"$VERDICT_OUT"
P_OK=0; [ "$PAGES" = "1" ] && P_OK=1

echo "file:            $ABS"
echo "paper/margins:   $PAPER, ${MARGIN}in  (printable height ${PRINTABLE_IN}in)"
echo "true content:    ${NAT}in   (must be <= ${SAFE_CONTENT_IN}in; headroom ${HEAD}in)  $([ "$C_OK" = 1 ] && echo PASS || echo FAIL)"
echo "screen document: ${SCR}in   (must be <= ${PRINTABLE_IN}in)                       $([ "$S_OK" = 1 ] && echo PASS || echo FAIL)"
echo "print pages:     ${PAGES}      (must be 1)                                  $([ "$P_OK" = 1 ] && echo PASS || echo FAIL)"
echo "print render:    $PRINT_PNG"
echo "screen render:   $SCREEN_PNG"
[ "$P_OK" = 0 ] && echo "(print.png shows only page 1 of a multi-page PDF; use screen.png or the PDF to see the overflow.)"
if [ "$C_OK" = 1 ] && [ "$S_OK" = 1 ] && [ "$P_OK" = 1 ]; then
  echo "VERDICT: PASS - fits one page in both media. Still Read both PNGs (color, columns, clipping)."
  exit 0
else
  echo "VERDICT: FAIL - trim until 'true content' is <= ${SAFE_CONTENT_IN}in and keep the sheet sized to the printable area (see reference.md)."
  exit 1
fi
