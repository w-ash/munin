---
name: print-one-pager
user_invocable: true
description: Creates self-contained, print-ready HTML documents that reliably print or export to a single US Letter (8.5x11) page or a clean PDF. Use when the user wants a flyer, one-pager, handout, poster, menu, certificate, program, or any single-page printable document, or mentions printing to PDF or fitting content on one page. Encodes print-safe CSS and a headless render check that verifies the page count before finishing.
---

# Print one-pager

Produces one self-contained HTML file that prints or exports to a single US Letter page. Content
and styling vary per request; what stays constant is the print-safe scaffolding and a render check
that catches the failures which look fine on screen but break in print or PDF.

The output is one `.html` file with screen-only controls (a Print button and a Copy-as-PNG button)
that never appear in the printed/exported output. To make a PDF, the user opens it in a browser and
chooses Cmd+P then Save as PDF (or the Print button). No build step, no dependencies.

## Files in this skill
- `template.html` - minimal print-safe skeleton. Copy it, then fill in content. One level deep.
- `example-sofras.html` - a fully worked one-pager (a satirical newspaper flyer) to pattern-match
  against for masthead, two columns, drop cap, shaded panels, embedded photos. Reference only; it is
  a point-in-time snapshot, so treat it as an example of the patterns, not a live source of truth.
- `reference.md` - symptom to cause to fix catalog for every print failure mode, plus the
  headless measure technique. Read it when a check fails or before debugging anything print-related.
- `scripts/check_print.sh` - renders the file and reports the fit signals plus PNGs to inspect.
- `scripts/embed_fonts.sh` - turns a Google Fonts URL into a base64 `@font-face` block so web fonts
  render exactly (on screen, in print, and in the Copy-PNG export) and work offline.

## Workflow
1. Copy `template.html` to the destination (default: alongside the user's files, named like
   `<Topic> Flyer.html`) and work in the copy. Leave `template.html` and `example-sofras.html` as
   references.
2. Build the content into the copy. Restyle freely (fonts, colors, layout) for the request, but
   keep the print-safe rules below intact. Crib structure from `example-sofras.html` when useful.
3. Embed every image as a `data:` URI so the file is self-contained. On macOS:
   `curl` the image, `sips -Z <px> -s format jpeg` to resize, `base64 -i` to encode, then paste
   into `<img src="data:image/jpeg;base64,...">`. Prefer official/public-domain sources. If the
   design uses web fonts, embed them too: `scripts/embed_fonts.sh "<google-fonts-url>" > fonts.css`,
   then paste that block in place of the `@import` so the fonts are exact and offline-safe.
4. Run the check: `bash scripts/check_print.sh "<file.html>"`. All three signals must PASS: true
   content height (under ~9.8in, with headroom), screen document height, and print page count. Then
   Read the two PNGs and confirm colors are present (not black), columns intact, nothing clipped.
5. To win headroom, trim vertical space (line-height, section margins, slightly smaller display
   type). Print CSS has no scale-to-fit. Re-run the check until it reads VERDICT: PASS.
6. Open the finished file in the browser for the user and tell them to print with Cmd+P then Save
   as PDF, with Background graphics on and Margins on Default.

## Print-safe rules
Each rule is the affirmative form of a failure that looks fine on screen but breaks in print or PDF.

- **Page geometry.** Set `@page { size: letter portrait; margin: 0.4in }` and size the sheet to the
  printable area in EVERY media: `width: 7.6in; min-height: 10.0in; margin: 0 auto` (no padding, no
  `@media print` geometry switch; `@page` supplies the printed border, a screen-only box-shadow
  stands in). A sheet that equals the full `8.5in` x `11in` page is taller and wider than the
  printable area and spills to a second page, especially when a tool exports the screen view.
- **Solid color stops.** Fade to `rgba(r,g,b,0)` of the adjacent color, or use a solid fill. The
  bare `transparent` keyword is transparent black and prints as solid black in many PDF engines.
- **Blending off.** Build texture with plain low-alpha overlays and keep `mix-blend-mode: normal`.
  Blend modes print as a black fill in macOS Quartz, Safari, and some print previews.
- **Flex columns.** Lay columns out as explicit `.col` divs in a flex row, split prose at a sentence
  boundary, and scope any `::first-letter` drop cap to the first column. CSS `column-count` collapses
  to one column in print.
- **Self-contained file.** Embed images as `data:` URIs. For exact fonts everywhere (screen, print,
  and the Copy-PNG export, including offline), embed them as base64 `@font-face` via
  `scripts/embed_fonts.sh`; `@import` is lighter but its fonts fall back to the serif/sans stack in
  the PNG and offline, so always back the family with a real fallback stack.
- **Backgrounds in print.** Add `* { print-color-adjust: exact !important; -webkit-print-color-adjust: exact !important }` inside `@media print`.
- **Fit by design.** Keep the content under about 9.8in tall inside the 7.6in-wide sheet (that is
  the printable 10.2in minus a 0.4in headroom buffer, which is what `check_print.sh` gates on), and
  trim spacing to fit. Print CSS has no scale-to-fit.

## Verify across BOTH screen and print media
Page count alone is not enough: a doc can be one page in print media yet spill when a tool exports
the screen view (the box-shadow and backdrop give a screen export away). That is why the geometry
is the same in both media and why `check_print.sh` gates on true content height and screen document
height too, not just the print page count. Keep robustness in the base CSS; reserve `@media print`
for the color-adjust and blend-mode guards.

## When something looks wrong
Read `reference.md`. It maps each symptom (all-black PDF, two-page spill, single column in print,
clipped content, screen vs print mismatch) to its cause and fix, and documents how to measure page
count and fit headroom with a headless browser.
