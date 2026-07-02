#!/usr/bin/env bash
# embed_fonts.sh "<google-fonts-css2-url>" [subset]
#
# Turns a Google Fonts @import URL into a self-contained @font-face block with the font files
# inlined as base64, so the fonts render exactly on screen, in print, AND in the Copy-PNG export,
# even offline. Prints the <style>-ready CSS to stdout; paste it in place of the @import.
#
#   subset (optional): "latin" (default) or "all". Latin covers English text plus curly quotes and
#   en/em dashes; use "all" only if the document needs accented/Cyrillic/Vietnamese glyphs.
#
# Example:
#   ./embed_fonts.sh "https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&display=swap" > fonts.css
#
# Requires network (downloads the font files once). macOS/Linux, python3.

set -euo pipefail
URL="${1:-}"
SUBSET="${2:-latin}"
if [ -z "$URL" ]; then
  echo "usage: embed_fonts.sh \"<google-fonts-css2-url>\" [latin|all]" >&2
  exit 2
fi

python3 - "$URL" "$SUBSET" <<'PY'
import re, sys, base64, urllib.request
url, subset = sys.argv[1], sys.argv[2]
# Any modern-Chrome UA works; Google Fonts only needs it to serve woff2 (the
# exact version number is arbitrary and doesn't need updating).
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def fetch(u, binary=False):
    req = urllib.request.Request(u, headers={'User-Agent': UA})
    # 30s per request: font files are ~15-50 KB each, so this only trips on a
    # genuinely stuck connection, not a slow one.
    data = urllib.request.urlopen(req, timeout=30).read()
    return data if binary else data.decode('utf-8')

try:
    css = fetch(url)
except Exception as e:
    sys.stderr.write("ERROR: could not fetch the font CSS (%s). Check the URL and your network.\n" % e)
    sys.exit(3)

parts = re.findall(r'/\*\s*([a-z-]+)\s*\*/\s*@font-face\s*\{([^}]*)\}', css)
if not parts:
    sys.stderr.write("ERROR: no @font-face blocks found. Pass the css2 '?family=...' URL (woff2 UA needed).\n")
    sys.exit(4)

out, total, kept = [], 0, 0
for sub, body in parts:
    if subset != 'all' and sub != subset:
        continue
    fam = re.search(r"font-family:\s*'([^']+)'", body)
    wt  = re.search(r'font-weight:\s*(\d+)', body)
    st  = re.search(r'font-style:\s*(\w+)', body)
    src = re.search(r'url\(([^)]+\.woff2)\)', body)
    if not (fam and src):
        continue
    rng = re.search(r'unicode-range:\s*([^;]+);', body)
    try:
        data = fetch(src.group(1), binary=True)
    except Exception as e:
        sys.stderr.write("WARNING: skipped %s (%s)\n" % (src.group(1), e))
        continue
    total += len(data); kept += 1
    b64 = base64.b64encode(data).decode()
    out.append(
        "@font-face{font-family:'%s';font-style:%s;font-weight:%s;font-display:swap;"
        "src:url(data:font/woff2;base64,%s) format('woff2');%s}"
        % (fam.group(1), st.group(1) if st else 'normal', wt.group(1) if wt else '400',
           b64, ("unicode-range:%s;" % rng.group(1).strip()) if rng else ''))

# Never emit an empty-but-successful result: a caller doing `> fonts.css` would
# get a blank stylesheet and only notice when the fonts silently don't render.
if kept == 0:
    sys.stderr.write(
        "ERROR: no font faces embedded (subset %r matched nothing, or every "
        "download failed). Try subset 'all', and check the warnings above.\n" % subset
    )
    sys.exit(5)
sys.stdout.write('\n'.join(out) + '\n')
sys.stderr.write("embedded %d face(s) [%s], %d KB of fonts, %d KB of CSS.\n"
                 % (kept, subset, total // 1024, len('\n'.join(out)) // 1024))
PY
