# Print one-pager reference

Symptom to cause to fix for every print/PDF failure mode, plus how to measure page count and fit
with a headless browser. These are the failures that look fine on screen and even in a headless
print test, but break in a real export.

## Contents
- The PDF (or print) comes out all black
- Content spills onto a second page
- Two columns render as one column in print
- Content is clipped at the bottom or edges
- Looks right on screen but breaks when exported (screen vs print media)
- Headless measure technique (page count and fit headroom)
- macOS image-embedding recipe
- Copy-as-PNG export and perfect fonts

## The PDF (or print) comes out all black
Two independent causes, both common:

1. **Gradient `transparent` stops.** `transparent` is `rgba(0,0,0,0)` (transparent BLACK). Many
   PDF/export engines ignore the alpha and fill it as solid opaque black. A single
   `radial-gradient(white, transparent)` covering the sheet blacks out the whole page.
   - Fix: remove every `transparent` keyword from gradients. Replace each with a zero-alpha version
     of the ADJACENT color, e.g. `rgba(224,169,46,0)`, or drop the gradient for a solid fill.
     Grep the file for `transparent` and make sure none remain in any `background`.
2. **`mix-blend-mode`.** `multiply` and friends render as a solid black fill in macOS Quartz,
   Safari Save as PDF, and some Chrome print previews.
   - Fix: remove `mix-blend-mode` from the base CSS. Recreate texture/halftone with plain low-alpha
     overlays instead. Add `* { mix-blend-mode: normal !important; background-blend-mode: normal !important }` in `@media print` as a guard.

Note: headless Chromium (`--print-to-pdf`, Skia) renders both of these correctly, so a headless
test will NOT reproduce the black. Trust the rule, not the headless render, for these two.

## Content spills onto a second page
Three distinct causes:
- **Sheet sized to the full page.** A sheet at `8.5in` x `11in` (or `min-height: 11in`) is as large
  as the paper, so it is taller and wider than the printable area (paper minus margins) and spills.
  This bites hardest when a tool exports the SCREEN view, where the full-height sheet is laid out as
  is. The print-media page count can still read 1 while the screen export is 2 pages.
  - Fix: size the sheet to the printable area in EVERY media, and never switch geometry between
    screen and print: `@page { margin: 0.4in }` plus
    `.sheet { width: 7.6in; min-height: 10.0in; margin: 0 auto }` (no padding; `@page` gives the
    printed border, a screen-only box-shadow stands in). 7.6in < 7.7in printable width and
    10.0in < 10.2in printable height, so the sheet cannot exceed the page in either media.
- **Sheet hardcoded to full paper width with zero page margin.** `width: 8.5in` + `@page { margin: 0 }`
  sits flush to the paper edge; any printer margin or sub-pixel rounding makes it "too wide" and
  pushes a second page. Same fix: sheet narrower than the paper, real `@page` margins.
- **Content genuinely taller than the printable area.** No scale-to-fit exists in print CSS.
  - Fix: trim vertical space (line-height, inter-section margins by 1-2px, smaller display type, a
    quote or paragraph shorter by a line) until the content measures under ~9.8in. Re-check.

## Two columns render as one column in print
- **Cause: CSS `column-count` / `column-gap`.** In paged media the default `column-fill` packs
  everything into the first column up to the page height before using the second, so short content
  becomes one column. Screen (and sometimes headless print) balances it, hiding the bug.
  - Fix: use explicit flex columns instead of multi-column:
    ```css
    .body { display: flex; }
    .body .col { flex: 1 1 0; min-width: 0; }
    .body .col:first-child { padding-right: 0.17in; }
    .body .col:last-child  { padding-left: 0.17in; border-left: 1px solid rgba(0,0,0,0.35); }
    ```
    Split the prose into two `.col` divs at a sentence boundary so the gutter falls cleanly. Scope a
    drop cap to the first column only: `.body .col:first-child p:first-of-type::first-letter`.
    For a true drop cap use `initial-letter: 3` (with `-webkit-initial-letter: 3`); it aligns the
    cap top to line one and its baseline to line three automatically.

## Content is clipped at the bottom or edges
- **Cause: a fixed-height sheet with `overflow: hidden` while content exceeds the box.** The page
  count reads 1 (because overflow is clipped) but the footer is cut off.
  - Fix: measure the natural content height (below) and trim until it fits with headroom; do not
    rely on `overflow: hidden` to hide a real overflow. Keep ~0.4in+ of headroom because a user's
    engine often renders a bit taller than a headless test.

## Looks right on screen but breaks when exported (screen vs print media)
- **Tell:** the exported PDF shows the screen-only chrome (box-shadow around the sheet, the page
  backdrop color, an on-page Print button). That means the export used SCREEN styles and ignored
  `@media print` entirely.
- **Implication:** fixes placed only in `@media print` will not help that user.
  - Fix: put robustness in the BASE CSS (solid backgrounds, no blend modes, flex columns, sheet
    sized to the printable area) so the document is correct in both media. Keep the geometry
    identical across media; reserve `@media print` for the color-adjust and blend-mode guards.

## Headless measure technique (three signals, not just page count)
Page count from print-media `--print-to-pdf` is necessary but NOT sufficient: a doc can read one
page in print media while the screen-view export spills to two. Measure all three of: true content
height (with headroom), screen document height, and print page count.

**Use `scripts/check_print.sh "<file.html>"`** - it does all three (reading the `@page` margin from
the file), prints PASS/FAIL per signal with the headroom figure, and emits a print PNG and a screen
PNG to inspect. That is the canonical tool; prefer it.

Fallback, only if the script cannot run (no Chromium browser, or you are reproducing one signal by
hand). Brave is at `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` (Chrome is not
installed; Chromium/Edge also work). `--virtual-time-budget=5000` lets `@import` fonts load first.
- Page count: `--print-to-pdf=/tmp/out.pdf`, then count `/Type /Page` objects in the bytes (fall
  back to the last `/Count` if those are compressed).
- Visual: `sips -s format png /tmp/out.pdf --out /tmp/print.png`, and a screen screenshot with
  `--force-device-scale-factor=1.5 --window-size=900,1180 --screenshot=/tmp/screen.png`.
- Fit headroom: inject a `load` script into a temp copy that sets the sheet `min-height:0; height:auto`
  and reports `scrollHeight` via `--dump-dom`; compare to the printable height (paper height minus
  2x the `@page` margin, x96 for px). Aim for 0.4in+ of headroom.

## macOS image-embedding recipe
Keep the file self-contained so it prints offline with no broken images.
```bash
curl -sSL -A "Mozilla/5.0" "<image-url>" -o /tmp/src.jpg
sips -Z 620 -s format jpeg -s formatOptions 86 /tmp/src.jpg --out /tmp/small.jpg   # ~620px long edge
base64 -i /tmp/small.jpg                                                            # paste into src="data:image/jpeg;base64,..."
```
Size the source ~2.5x the display box so it stays crisp at print resolution. ~600px is plenty for a
portrait shown at ~1.3in. Prefer official or public-domain images; note when a likeness is used in
satire/parody.

## Copy-as-PNG export and perfect fonts
The template's "Copy PNG" button is dependency-free: it clones `.sheet` into an SVG `<foreignObject>`,
draws it to a 2x canvas, and copies the PNG to the clipboard (falling back to a download). This is
the same technique the modern libraries (snapDOM, html-to-image) use under the hood; building it in
keeps the file self-contained and avoids running external code.

Two things make or break fidelity:
- **Embedded resources only.** Images must be `data:` URIs or the canvas taints and the clipboard
  write fails. (Ours already are.)
- **Fonts must be present as data, not fetched.** A web font pulled via `@import` is NOT available
  to the SVG-as-image rasterizer, so it falls back to the serif/sans stack in the PNG. Embed the
  fonts as base64 `@font-face` (run `scripts/embed_fonts.sh "<google-fonts-url>"` and paste the
  block in place of the `@import`) and they render exactly. The built-in renderer then needs no
  library and no network.

Gotcha: the inlined CSS goes inside the SVG `<style>` wrapped in `<![CDATA[ ... ]]>`. Without CDATA,
a bare `&` in a CSS value (e.g. a Google Fonts `@import` URL's `&family=`) is illegal XML and the
SVG image silently fails to load (the PNG comes out empty). The template already does this.
