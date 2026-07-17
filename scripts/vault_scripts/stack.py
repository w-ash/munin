"""Compute canonical nutrient intake across the supplement stack.

Supplements are a notes-as-record domain (one product note per SKU in
``Health/Supplements/entries/``). Each note's ``ingredients`` carry a canonical
substance ``key`` mapping the label name to a row in the reference registry
``Health/data/reference/substances.jsonl`` (canonical unit + NIH ODS upper
intake level). This module turns those into cross-product totals:

- ``ingredients`` regenerates ``Health/data/derived/product-ingredients.jsonl``,
  one row per product x substance with the per-pill amount. A layer-2
  projection (trackers framework): regenerable, rewritten wholesale, never the
  record.
- ``totals`` sums the current active daily stack per substance (per-pill model:
  ``per_serving / pills_per_serving x pills_per_day``), reporting each substance
  against its UL where one exists.
- ``uls`` shows only the UL-bearing substances with headroom, so an over-UL
  total is visible at a glance. Findings are neutral totals, never advice.

Slice 1 reads the regimen from each note's current mirror fields (``status``,
``frequency``, ``pills_per_day``). The effective-dated regimen log (slice 2)
supersedes that snapshot without changing this arithmetic.

Examples:

    scripts/vault-tool stack ingredients            # dry-run: counts + sample
    scripts/vault-tool stack ingredients --write     # write the derived JSONL
    scripts/vault-tool stack totals                  # all substances, vs UL
    scripts/vault-tool stack uls                      # UL-bearing only
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import sys

import frontmatter
from pydantic import ValidationError
import yaml

from vault_scripts._cli import (
    CliError,
    emit_write,
    envelope,
    error_envelope,
    print_json,
)
from vault_scripts._types import (
    DailyIntakeRow,
    ProductIngredientRow,
    RegimenEvent,
    StackException,
    SubstanceRow,
    SupplementNote,
)
from vault_scripts._utils import VAULT, parse_typed_args, patch_field, rel_path

_ID_KEY = "stack"
_ID_VALUE = "supplements"

_ENTRIES_PARTS = ("Health", "Supplements", "entries")
_SUBSTANCES_PARTS = ("Health", "data", "reference", "substances.jsonl")
_DERIVED_PARTS = ("Health", "data", "derived")
_CANONICAL_PARTS = ("Health", "data", "canonical")
_PRODUCT_INGREDIENTS = "product-ingredients.jsonl"
_REGIMEN_FILE = "stack-regimen.jsonl"
_EXCEPTIONS_FILE = "stack-exceptions.jsonl"

_MISS = "miss"
_TAKEN = "taken"
_EXTRA = "extra"
_SUBSTITUTE = "substitute"
_DOSE_CHANGE = "dose_change"
_KINDS = (_MISS, _TAKEN, _EXTRA, _SUBSTITUTE, _DOSE_CHANGE)

_ACTIVE = "active"
_STOPPED = "stopped"
_DAILY = "daily"

STACK_START = "<!-- stack:start -->"
STACK_END = "<!-- stack:end -->"
_STACK_BLOCK_RE = re.compile(r"<!-- stack:start -->.*?<!-- stack:end -->", re.DOTALL)

# The initial regimen date recorded in Stack.md ("Set 2026-07-12 from the
# Timing Study"). Migration stamps every seed event with this effective date.
_SEED_EFFECTIVE = "2026-07-12"

# Slot -> display heading for the generated regimen block. As-needed items
# (empty slot) render under _ASNEEDED_HEADING, always last.
_SLOT_HEADINGS = {
    "1-wake": "Wake, fasted (with Adderall)",
    "2-breakfast": "Breakfast (with a fatty meal)",
    "3-dinner": "Dinner",
    "4-bedtime": "Bedtime",
}
_ASNEEDED_HEADING = "As-needed"

# One-time migration seed: (role, source_id, display label, timing note). Order
# is the current Stack.md order, so the generated block reproduces it. Product,
# pills, slot, and frequency are read from each note; taurine (considering) gets
# no role until it is bought and set.
_SEED: tuple[tuple[str, str, str, str], ...] = (
    ("ala", "nutricost-alpha-lipoic-acid-600", "Alpha Lipoic Acid",
     "empty stomach, 30-60 min before breakfast"),
    ("b_complex", "garden-of-life-raw-b-complex", "B-Complex", ""),
    ("cdp_choline", "nutricost-cdp-choline-300", "CDP Choline", ""),
    ("methylfolate", "nutricost-l-methylfolate-1000", "L-Methylfolate", ""),
    ("vitamin_c", "thorne-vitamin-c-500", "Vitamin C", "at least 1 hour after Adderall"),
    ("zinc", "igennus-zinc-complex-25", "Zinc", ""),
    ("coq10", "nutricost-coq10-100", "CoQ10", "needs fat"),
    ("d3_k2", "sports-research-d3-k2", "D3 + K2", "needs fat"),
    ("astaxanthin", "nutricost-astaxanthin-12", "Astaxanthin", "needs fat"),
    ("egcg", "now-egcg-green-tea-400", "EGCg", "with food, never empty stomach"),
    ("probiotic", "nutricost-probiotic-complex", "Probiotic", ""),
    ("magnesium_daytime", "now-magtein-magnesium-l-threonate", "Magtein",
     "magnesium L-threonate"),
    ("creatine", "naked-nutrition-creatine-monohydrate", "Creatine",
     "mix into a carb drink"),
    ("quercetin", "thorne-quercetin-phytosome", "Quercetin", ""),
    ("spm", "zdoroviye-spm-complex", "SPM / omega-3", "needs fat"),
    ("magnesium_bedtime", "nutricost-magnesium-glycinate", "Magnesium Glycinate", ""),
    ("ashwagandha", "nutricost-ksm66-ashwagandha-600", "Ashwagandha", ""),
    ("iron", "naturelo-iron-vitamin-c", "Iron + Vitamin C",
     "mid-morning, away from coffee and tea; 2h from zinc and the magnesiums; "
     "1h+ from Adderall; alternate days"),
)
# Round the per-pill amount finely (small doses like 4 mg caffeine) and the
# summed daily total a touch coarser; both avoid binary-float display noise.
_PER_PILL_DP = 4
_TOTAL_DP = 3


def _entries_dir() -> Path:
    return VAULT.joinpath(*_ENTRIES_PARTS)


def _substances_path() -> Path:
    return VAULT.joinpath(*_SUBSTANCES_PARTS)


def _derived_dir() -> Path:
    return VAULT.joinpath(*_DERIVED_PARTS)


# --- Load ---


def _read_substances() -> dict[str, SubstanceRow]:
    path = _substances_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CliError(f"cannot read substances registry {path}: {e}") from e
    out: dict[str, SubstanceRow] = {}
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = SubstanceRow.model_validate_json(line)
        except ValidationError as e:
            raise CliError(f"malformed substances.jsonl line {i}: {e}") from e
        out[row.key] = row
    return out


def _read_notes() -> list[SupplementNote]:
    directory = _entries_dir()
    if not directory.exists():
        raise CliError(f"no supplement entries dir at {directory}")
    notes: list[SupplementNote] = []
    for path in sorted(directory.glob("*.md")):
        try:
            post = frontmatter.load(str(path))
        except (OSError, yaml.YAMLError) as e:
            raise CliError(f"cannot parse {path.name}: {e}") from e
        try:
            note = SupplementNote.model_validate(post.metadata)
        except ValidationError as e:
            raise CliError(f"invalid frontmatter in {path.name}: {e}") from e
        notes.append(note)
    return notes


# --- Derive product x substance rows ---


def _product_rows(
    notes: list[SupplementNote], substances: dict[str, SubstanceRow]
) -> tuple[list[ProductIngredientRow], list[str]]:
    """One row per product x ingredient, plus warnings for any ingredient whose
    ``key`` is missing from the registry or whose label unit disagrees with the
    registry's canonical unit (a silent unit mismatch would corrupt a sum)."""
    rows: list[ProductIngredientRow] = []
    warnings: list[str] = []
    for note in notes:
        pps = note.pills_per_serving if note.pills_per_serving > 0 else 1
        for ing in note.ingredients:
            sub = substances.get(ing.key)
            if sub is None:
                warnings.append(
                    f"{note.source_id}: unknown substance key {ing.key!r} "
                    f"for {ing.name!r}"
                )
            elif ing.unit != sub.unit:
                warnings.append(
                    f"{note.source_id}: {ing.key} unit {ing.unit!r} != "
                    f"registry {sub.unit!r}"
                )
            rows.append(
                ProductIngredientRow(
                    product=note.source_id,
                    product_name=note.name,
                    brand=note.brand,
                    status=note.status,
                    frequency=note.frequency,
                    time_slot=note.time_slot,
                    pills_per_serving=pps,
                    pills_per_day=note.pills_per_day,
                    key=ing.key,
                    ingredient_name=ing.name,
                    per_serving=ing.per_serving,
                    unit=ing.unit,
                    per_pill=round(ing.per_serving / pps, _PER_PILL_DP),
                    dv_percent=ing.dv_percent,
                )
            )
    return rows, warnings


@dataclass
class _Agg:
    amount: float = 0.0
    products: list[str] = field(default_factory=list)
    units: set[str] = field(default_factory=set)


def _totals(
    rows: list[ProductIngredientRow], substances: dict[str, SubstanceRow]
) -> list[dict[str, object]]:
    """Sum the current active daily stack per substance. Daily contribution of a
    product to a substance is ``per_pill x pills_per_day``; as-needed and
    non-active products are excluded (they contribute only via logged intake in
    a later slice)."""
    daily = [r for r in rows if r.status == _ACTIVE and r.frequency == _DAILY]
    agg: dict[str, _Agg] = {}
    for r in daily:
        a = agg.setdefault(r.key, _Agg())
        a.amount += r.per_pill * r.pills_per_day
        a.products.append(r.product)
        a.units.add(r.unit)
    out: list[dict[str, object]] = []
    for key, a in agg.items():
        sub = substances.get(key)
        name = sub.name if sub else key
        unit = sub.unit if sub else (min(a.units) if a.units else "")
        amount = round(a.amount, _TOTAL_DP)
        ul = sub.ul if sub else None
        out.append({
            "key": key,
            "name": name,
            "unit": unit,
            "daily_amount": amount,
            "ul": ul,
            "pct_of_ul": round(amount / ul * 100, 1) if ul else None,
            "headroom": round(ul - amount, _TOTAL_DP) if ul else None,
            "over_ul": (amount > ul) if ul else None,
            "ul_basis": sub.ul_basis if sub else None,
            "mixed_units": sorted(a.units) if len(a.units) > 1 else None,
            "products": sorted(set(a.products)),
        })
    out.sort(key=lambda r: str(r["name"]).lower())
    return out


# --- Commands ---


def _write_product_ingredients(rows: list[ProductIngredientRow]) -> dict[str, object]:
    path = _derived_dir() / _PRODUCT_INGREDIENTS
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r.product, r.key, r.ingredient_name))
    path.write_text(
        "".join(r.model_dump_json() + "\n" for r in ordered), encoding="utf-8"
    )
    return {"path": str(rel_path(path)), "rows": len(ordered)}


def cmd_ingredients(*, write: bool) -> None:
    substances = _read_substances()
    rows, warnings = _product_rows(_read_notes(), substances)
    sample = [r.model_dump() for r in rows[:3]]
    dry: dict[str, object] = {
        "path": str(rel_path(_derived_dir() / _PRODUCT_INGREDIENTS)),
        "rows": len(rows),
        "warnings": warnings,
        "sample": sample,
    }
    emit_write(
        "ingredients",
        _ID_KEY,
        _ID_VALUE,
        write=write,
        dry=dry,
        apply=lambda: {**_write_product_ingredients(rows), "warnings": warnings},
    )


def cmd_totals() -> None:
    substances = _read_substances()
    rows, warnings = _product_rows(_read_notes(), substances)
    totals = _totals(rows, substances)
    result: dict[str, object] = {
        "asOf": "current-mirrors",
        "substances": totals,
        "productsCounted": len({
            r.product for r in rows if r.status == _ACTIVE and r.frequency == _DAILY
        }),
        "warnings": warnings,
    }
    print_json(envelope("totals", _ID_KEY, _ID_VALUE, result))


def cmd_uls() -> None:
    substances = _read_substances()
    rows, warnings = _product_rows(_read_notes(), substances)
    with_ul = [t for t in _totals(rows, substances) if t["ul"] is not None]
    over = [t for t in with_ul if t["over_ul"]]
    result: dict[str, object] = {
        "asOf": "current-mirrors",
        "substances": with_ul,
        "overUl": [t["key"] for t in over],
        "warnings": warnings,
    }
    print_json(envelope("uls", _ID_KEY, _ID_VALUE, result))


# --- Regimen event log + effective dating ---


def _regimen_path() -> Path:
    return VAULT.joinpath(*_CANONICAL_PARTS) / _REGIMEN_FILE


def _read_events() -> list[RegimenEvent]:
    path = _regimen_path()
    if not path.exists():
        return []
    out: list[RegimenEvent] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(RegimenEvent.model_validate_json(line))
        except ValidationError as e:
            raise CliError(f"malformed {_REGIMEN_FILE} line {i}: {e}") from e
    return out


def _append_events(events: list[RegimenEvent]) -> None:
    if not events:
        return
    path = _regimen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        _ = fh.write("".join(e.model_dump_json() + "\n" for e in events))


def _next_seq(events: list[RegimenEvent]) -> int:
    mx = 0
    for e in events:
        m = re.match(r"reg-(\d+)$", e.id)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def _note_index() -> dict[str, tuple[Path, SupplementNote]]:
    """source_id -> (path, note), for wikilink stems and mirror writes."""
    idx: dict[str, tuple[Path, SupplementNote]] = {}
    for path in sorted(_entries_dir().glob("*.md")):
        try:
            post = frontmatter.load(str(path))
            note = SupplementNote.model_validate(post.metadata)
        except (OSError, yaml.YAMLError, ValidationError) as e:
            raise CliError(f"cannot parse {path.name}: {e}") from e
        if note.source_id:
            idx[note.source_id] = (path, note)
    return idx


def regimen_as_of(events: list[RegimenEvent], on_date: str) -> dict[str, RegimenEvent]:
    """Fold the log to the active fill per role as of ``on_date``: events with
    ``effective <= on_date`` ordered by ``(effective, ts)``; the last ``set``
    wins, a later ``stop`` clears the role."""
    state: dict[str, RegimenEvent] = {}
    for e in sorted(
        (e for e in events if e.effective <= on_date),
        key=lambda e: (e.effective, e.ts),
    ):
        if e.event == "set":
            state[e.role] = e
        elif e.event == "stop":
            state.pop(e.role, None)
    return state


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


# --- Stack.md generated regimen block ---


def render_regimen_block(
    fills: dict[str, RegimenEvent], stems: dict[str, str]
) -> str:
    """The sentinel-wrapped regimen block: fills grouped by slot (known slots by
    display heading, as-needed last), each a wikilink to its product note with
    the stored label and timing note. Within a slot, ordered by first-set ts, so
    the migration seed reproduces the current Stack.md order."""
    lines = [STACK_START]

    def emit(heading: str, items: list[RegimenEvent]) -> None:
        lines.append(f"### {heading}")
        for f in sorted(items, key=lambda f: f.ts):
            stem = stems.get(f.product, f.product)
            label = f.label or f.product
            tail = f" ({f.timing_note})" if f.timing_note else ""
            lines.append(f"- [[{stem}|{label}]]{tail}")

    for slot in sorted({f.slot for f in fills.values() if f.slot}):
        emit(
            _SLOT_HEADINGS.get(slot, slot),
            [f for f in fills.values() if f.slot == slot],
        )
    asneeded = [f for f in fills.values() if not f.slot]
    if asneeded:
        emit(_ASNEEDED_HEADING, asneeded)
    lines.append(STACK_END)
    return "\n".join(lines)


def upsert_stack_block(text: str, block: str, anchor: str = "## Exception log") -> str:
    """Replace the sentinel block in place, or (first run, no sentinels) insert
    it before ``anchor``. The one-time removal of the old hand-written regimen
    subsections is done by a reviewed edit, not here."""
    if _STACK_BLOCK_RE.search(text):
        return _STACK_BLOCK_RE.sub(lambda _: block, text, count=1)
    idx = text.find(anchor)
    if idx == -1:
        return text.rstrip("\n") + "\n\n" + block + "\n"
    return text[:idx] + block + "\n\n" + text[idx:]


def _stack_hub_path() -> Path:
    return VAULT / "Health" / "Supplements" / "Stack.md"


def _render_current_block(on_date: str | None = None) -> str:
    events = _read_events()
    fills = regimen_as_of(events, on_date or _today())
    stems = {sid: p.stem for sid, (p, _n) in _note_index().items()}
    return render_regimen_block(fills, stems)


def _project_stack(*, write: bool) -> dict[str, object]:
    path = _stack_hub_path()
    if not path.exists():
        return {"stackBlock": "skipped: no Stack.md"}
    block = _render_current_block()
    text = path.read_text(encoding="utf-8")
    new = upsert_stack_block(text, block)
    changed = new != text
    if write and changed:
        path.write_text(new, encoding="utf-8")
    return {"stackBlock": "updated" if changed else "unchanged"}


# --- Product-note mirror writes ---


def _append_log_line(text: str, line: str) -> str:
    """Append a dated bullet under the note's final ``## Log`` section."""
    if "## Log" not in text:
        return text
    return text.rstrip("\n") + f"\n{line}\n"


def _apply_mirror(
    text: str, *, status: str, pills: int, slot: str, frequency: str
) -> str:
    out = patch_field(text, "status", status)
    out = patch_field(out, "pills_per_day", pills)
    out = patch_field(out, "time_slot", slot)
    return patch_field(out, "frequency", frequency)


# --- Regimen commands ---


def cmd_migrate(*, write: bool) -> None:
    index = _note_index()
    existing = _read_events()
    have_roles = {e.role for e in existing}
    base = datetime.now().astimezone()
    seq = _next_seq(existing)
    new: list[RegimenEvent] = []
    missing: list[str] = []
    for i, (role, sid, label, timing) in enumerate(_SEED):
        if role in have_roles:
            continue
        entry = index.get(sid)
        if entry is None:
            missing.append(sid)
            continue
        _p, note = entry
        seq += 1
        new.append(RegimenEvent(
            id=f"reg-{seq:06d}",
            ts=(base + timedelta(microseconds=i)).isoformat(),
            event="set",
            role=role,
            effective=_SEED_EFFECTIVE,
            product=sid,
            pills_per_day=note.pills_per_day,
            slot=note.time_slot,
            frequency=note.frequency,
            label=label,
            timing_note=timing,
            note="seeded from Timing Study regimen",
        ))
    dry: dict[str, object] = {
        "seedEvents": len(new),
        "skippedExisting": len(have_roles),
        "missingProducts": missing,
        "regimenFile": str(rel_path(_regimen_path())),
        "block": render_regimen_block(
            regimen_as_of(existing + new, _today()),
            {sid: p.stem for sid, (p, _n) in index.items()},
        ),
    }

    def apply() -> dict[str, object]:
        _append_events(new)
        return {**dry, "written": len(new)}

    emit_write("migrate", _ID_KEY, _ID_VALUE, write=write, dry=dry, apply=apply)


def cmd_show(as_of: str | None) -> None:
    day = as_of or _today()
    events = _read_events()
    fills = regimen_as_of(events, day)
    stems = {sid: p.stem for sid, (p, _n) in _note_index().items()}
    rows = sorted(
        (
            {
                "role": f.role,
                "product": f.product,
                "label": f.label,
                "pills_per_day": f.pills_per_day,
                "slot": f.slot,
                "frequency": f.frequency,
                "effective": f.effective,
            }
            for f in fills.values()
        ),
        key=lambda r: (str(r["slot"]), str(r["role"])),
    )
    result: dict[str, object] = {
        "asOf": day,
        "roles": rows,
        "block": render_regimen_block(fills, stems),
    }
    print_json(envelope("show", _ID_KEY, _ID_VALUE, result))


def cmd_history(role: str) -> None:
    events = [e for e in _read_events() if e.role == role]
    events.sort(key=lambda e: (e.effective, e.ts))
    result: dict[str, object] = {
        "role": role,
        "events": [e.model_dump() for e in events],
    }
    print_json(envelope("history", _ID_KEY, _ID_VALUE, result))


def _write_mirror(
    path: Path, *, status: str, pills: int, slot: str, frequency: str, log: str
) -> None:
    text = path.read_text(encoding="utf-8")
    text = _apply_mirror(text, status=status, pills=pills, slot=slot, frequency=frequency)
    text = _append_log_line(text, log)
    path.write_text(text, encoding="utf-8")


def _reconcile_mirrors(events: list[RegimenEvent]) -> list[str]:
    """Sync every product-note mirror to regimen-as-of-today, appending a Log
    line only where a note actually changes. Because the target is today's fold,
    a future-dated event changes no mirror until its date arrives, and a product
    superseded out of the regimen is marked stopped only once the swap is in
    effect. This is the write side of what ``check`` reads."""
    today = _today()
    desired = {f.product: f for f in regimen_as_of(events, today).values()}
    # Only products the log has managed (ever named in a set event) are subject
    # to being stopped here; a note the log never touched is left alone.
    managed = {e.product for e in events if e.event == "set"}
    changed: list[str] = []
    for sid, (path, note) in _note_index().items():
        want = desired.get(sid)
        if want is not None:
            current = (note.status, note.pills_per_day, note.time_slot, note.frequency)
            target = (_ACTIVE, want.pills_per_day, want.slot, want.frequency)
            if current != target:
                slot_txt = f", {want.slot}" if want.slot else ""
                _write_mirror(
                    path, status=_ACTIVE, pills=want.pills_per_day,
                    slot=want.slot, frequency=want.frequency,
                    log=f"- **[[{today}]]** — regimen: {want.role} "
                        f"({want.pills_per_day}/day{slot_txt}).",
                )
                changed.append(sid)
        elif sid in managed and note.status == _ACTIVE:
            text = patch_field(path.read_text(encoding="utf-8"), "status", _STOPPED)
            text = _append_log_line(
                text, f"- **[[{today}]]** — stopped (no longer in the regimen)."
            )
            path.write_text(text, encoding="utf-8")
            changed.append(sid)
    return changed


def cmd_set(args: _Args, *, write: bool) -> None:
    index = _note_index()
    if args.product not in index:
        raise CliError(f"unknown product source_id: {args.product}")
    events = _read_events()
    _p, note = index[args.product]
    prior = regimen_as_of(events, args.effective).get(args.role)
    ev = RegimenEvent(
        id=f"reg-{_next_seq(events) + 1:06d}",
        ts=datetime.now().astimezone().isoformat(),
        event="set",
        role=args.role,
        effective=args.effective,
        product=args.product,
        pills_per_day=args.pills,
        slot=args.slot,
        frequency=args.frequency,
        label=args.label or note.name,
        timing_note=args.timing_note,
        note=args.note,
    )
    dry: dict[str, object] = {
        "event": ev.model_dump(),
        "supersedes": prior.product if prior and prior.product != args.product else None,
    }

    def apply() -> dict[str, object]:
        _append_events([ev])
        changed = _reconcile_mirrors([*events, ev])
        return {**dry, "mirrorsChanged": changed, **_project_stack(write=True)}

    emit_write("set", _ID_KEY, _ID_VALUE, write=write, dry=dry, apply=apply)


def cmd_stop(role: str, effective: str, note_text: str, *, write: bool) -> None:
    events = _read_events()
    prior = regimen_as_of(events, effective).get(role)
    if prior is None:
        raise CliError(f"role {role!r} has no active fill as of {effective}")
    ev = RegimenEvent(
        id=f"reg-{_next_seq(events) + 1:06d}",
        ts=datetime.now().astimezone().isoformat(),
        event="stop",
        role=role,
        effective=effective,
        note=note_text,
    )
    dry: dict[str, object] = {"event": ev.model_dump(), "product": prior.product}

    def apply() -> dict[str, object]:
        _append_events([ev])
        changed = _reconcile_mirrors([*events, ev])
        return {**dry, "mirrorsChanged": changed, **_project_stack(write=True)}

    emit_write("stop", _ID_KEY, _ID_VALUE, write=write, dry=dry, apply=apply)


def cmd_check() -> None:
    """Report mirror drift: product-note regimen fields vs regimen-as-of-today."""
    index = _note_index()
    fills = regimen_as_of(_read_events(), _today())
    drift: list[dict[str, object]] = []
    role_products = {f.product for f in fills.values()}
    for role, f in fills.items():
        entry = index.get(f.product)
        if entry is None:
            drift.append({"role": role, "issue": f"no note for {f.product}"})
            continue
        _p, note = entry
        mism: list[str] = []
        if note.status != _ACTIVE:
            mism.append(f"status={note.status!r} (expected active)")
        if note.pills_per_day != f.pills_per_day:
            mism.append(f"pills_per_day={note.pills_per_day} (expected {f.pills_per_day})")
        if note.time_slot != f.slot:
            mism.append(f"time_slot={note.time_slot!r} (expected {f.slot!r})")
        if note.frequency != f.frequency:
            mism.append(f"frequency={note.frequency!r} (expected {f.frequency!r})")
        if mism:
            drift.append({"role": role, "product": f.product, "mismatches": mism})
    # Active daily notes that no role fills (mirror says in-stack, log disagrees).
    for sid, (_p, note) in index.items():
        if note.status == _ACTIVE and note.frequency == _DAILY and sid not in role_products:
            drift.append({"product": sid, "issue": "active daily note fills no role"})
    result: dict[str, object] = {"asOf": _today(), "drift": drift, "ok": not drift}
    print_json(envelope("check", _ID_KEY, _ID_VALUE, result))


# --- Exceptions + derived daily intake ---


def _exceptions_path() -> Path:
    return VAULT.joinpath(*_CANONICAL_PARTS) / _EXCEPTIONS_FILE


def _read_exceptions() -> list[StackException]:
    path = _exceptions_path()
    if not path.exists():
        return []
    out: list[StackException] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(StackException.model_validate_json(line))
        except ValidationError as e:
            raise CliError(f"malformed {_EXCEPTIONS_FILE} line {i}: {e}") from e
    return out


def _append_exception(ev: StackException) -> None:
    path = _exceptions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        _ = fh.write(ev.model_dump_json() + "\n")


def _next_exc_seq(events: list[StackException]) -> int:
    mx = 0
    for e in events:
        m = re.match(r"exc-(\d+)$", e.id)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def _date_range(start: str, end: str) -> list[str]:
    cur, last = date.fromisoformat(start), date.fromisoformat(end)
    days: list[str] = []
    while cur <= last:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _ingredient_rows(
    note: SupplementNote, day: str, role: str, slot: str, pills: int,
    basis: str, event_id: str,
) -> list[DailyIntakeRow]:
    pps = note.pills_per_serving if note.pills_per_serving > 0 else 1
    return [
        DailyIntakeRow(
            date=day, role=role, product=note.source_id, slot=slot, pills=pills,
            key=ing.key, amount=round(ing.per_serving / pps * pills, _TOTAL_DP),
            unit=ing.unit, basis=basis, event_id=event_id,
        )
        for ing in note.ingredients
    ]


def _intake_for_day(
    day: str,
    events: list[RegimenEvent],
    notes: dict[str, SupplementNote],
    excs: list[StackException],
) -> list[DailyIntakeRow]:
    """The resolved intake for one day: the regimen fold that day, minus misses,
    with dose overrides and substitutions applied, plus affirmative taken/extra
    rows. PRN (as-needed) roles contribute nothing from the plan; only a logged
    ``taken`` produces their rows."""
    fills = regimen_as_of(events, day)
    day_missed = any(e.kind == _MISS and e.scope == "day" for e in excs)
    missed_slots = {e.slot for e in excs if e.kind == _MISS and e.scope == "slot"}
    missed_roles = {e.role for e in excs if e.kind == _MISS and e.scope == "role"}
    dose_over = {e.role: e.pills for e in excs if e.kind == _DOSE_CHANGE}
    subs = {e.role: e.product for e in excs if e.kind == _SUBSTITUTE}
    rows: list[DailyIntakeRow] = []
    if not day_missed:
        for role, f in fills.items():
            if f.frequency != _DAILY:
                continue
            if role in missed_roles or (f.slot and f.slot in missed_slots):
                continue
            note = notes.get(subs.get(role, f.product))
            if note is None:
                continue
            rows += _ingredient_rows(
                note, day, role, f.slot, dose_over.get(role, f.pills_per_day),
                "plan", "",
            )
    for e in excs:
        if e.kind not in {_TAKEN, _EXTRA}:
            continue
        fill = fills.get(e.role)
        note = notes.get(e.product or (fill.product if fill else ""))
        if note is None:
            continue
        slot = fill.slot if fill else e.slot
        pills = e.pills or (fill.pills_per_day if fill else 1)
        rows += _ingredient_rows(note, day, e.role, slot, pills, "exception", e.id)
    return rows


def _write_intake(rows: list[DailyIntakeRow]) -> dict[str, object]:
    by_year: dict[str, list[DailyIntakeRow]] = {}
    for r in rows:
        by_year.setdefault(r.date[:4], []).append(r)
    directory = _derived_dir()
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for year, yr in sorted(by_year.items()):
        path = directory / f"intake-{year}.jsonl"
        path.write_text(
            "".join(x.model_dump_json() + "\n" for x in yr), encoding="utf-8"
        )
        written[year] = len(yr)
    return {"years": written}


def cmd_derive(*, write: bool) -> None:
    events = _read_events()
    if not events:
        raise CliError("no regimen events; run `stack migrate` first")
    start, end = min(e.effective for e in events), _today()
    notes = {sid: n for sid, (_p, n) in _note_index().items()}
    by_date: dict[str, list[StackException]] = {}
    for e in _read_exceptions():
        by_date.setdefault(e.date, []).append(e)
    rows: list[DailyIntakeRow] = []
    for day in _date_range(start, end):
        rows += _intake_for_day(day, events, notes, by_date.get(day, []))
    dry: dict[str, object] = {
        "range": {"from": start, "to": end},
        "rows": len(rows),
    }
    emit_write(
        "derive", _ID_KEY, _ID_VALUE, write=write, dry=dry,
        apply=lambda: {**dry, **_write_intake(rows)},
    )


def cmd_day(day: str) -> None:
    events = _read_events()
    notes = {sid: n for sid, (_p, n) in _note_index().items()}
    excs = [e for e in _read_exceptions() if e.date == day]
    rows = _intake_for_day(day, events, notes, excs)
    subs = _read_substances()
    agg: dict[str, float] = {}
    for r in rows:
        agg[r.key] = agg.get(r.key, 0.0) + r.amount
    totals = sorted(
        (
            {
                "key": k,
                "name": subs[k].name if k in subs else k,
                "amount": round(v, _TOTAL_DP),
                "unit": subs[k].unit if k in subs else "",
            }
            for k, v in agg.items()
        ),
        key=lambda t: str(t["name"]).lower(),
    )
    result: dict[str, object] = {
        "date": day,
        "rows": [r.model_dump() for r in rows],
        "totals": totals,
        "exceptions": [e.model_dump() for e in excs],
    }
    print_json(envelope("day", _ID_KEY, _ID_VALUE, result))


def _miss_detail(ev: StackException) -> str:
    if ev.scope == "day":
        return "missed the whole day"
    if ev.scope == "slot":
        return f"missed the {ev.slot} slot"
    if ev.scope == "role":
        return f"missed {ev.role}"
    return "miss"


def _exception_log_line(ev: StackException) -> str:
    pill_txt = f" ({ev.pills} pill{'s' if ev.pills != 1 else ''})" if ev.pills else ""
    detail = {
        _MISS: _miss_detail(ev),
        _TAKEN: f"took {ev.role or ev.product}{pill_txt}",
        _EXTRA: f"extra {ev.role}{pill_txt}",
        _SUBSTITUTE: f"substituted {ev.role} with {ev.product}",
        _DOSE_CHANGE: f"dose change {ev.role} to {ev.pills}/day",
    }.get(ev.kind, ev.kind)
    tail = f" ({ev.note})" if ev.note else ""
    return f"- **[[{ev.date}]]** — {detail}{tail}."


def _append_stack_exception_line(line: str) -> str:
    path = _stack_hub_path()
    if not path.exists():
        return "skipped: no Stack.md"
    text = path.read_text(encoding="utf-8")
    heading = "## Exception log" if "## Exception log" in text else "## Miss log"
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.strip() == heading]
    if not starts:
        return "skipped: no exception log section"
    start = starts[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    insert_at = end
    while insert_at - 1 > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, line)
    path.write_text("\n".join(lines), encoding="utf-8")
    return "appended"


def _validate_log(
    args: _Args,
    on_date: str,
    index: dict[str, tuple[Path, SupplementNote]],
    fills: dict[str, RegimenEvent],
) -> None:
    """Reject an exception that references something that does not resolve, so a
    typo fails loudly instead of silently deriving nothing (or, for a bad
    substitute product, silently dropping the role's planned intake that day).
    A product must exist as a source_id; a role must have a regimen fill on the
    exception's date."""
    if args.kind == _MISS:
        if args.scope not in {"day", "slot", "role"}:
            raise CliError("miss requires --scope day|slot|role")
        if args.scope == "slot" and not args.slot:
            raise CliError("miss --scope slot requires --slot")
        if args.scope == "role" and not args.role:
            raise CliError("miss --scope role requires --role")
        return
    if args.product and args.product not in index:
        raise CliError(f"unknown product source_id: {args.product}")
    if args.kind == _TAKEN:
        if not args.product and args.role not in fills:
            raise CliError(
                f"taken needs --product, or a --role with a regimen fill on {on_date}"
            )
    elif args.kind == _EXTRA:
        if args.role not in fills:
            raise CliError(f"extra requires a --role with a regimen fill on {on_date}")
    elif args.kind == _SUBSTITUTE:
        if args.role not in fills:
            raise CliError(
                f"substitute requires a --role with a regimen fill on {on_date}"
            )
        if not args.product:
            raise CliError("substitute requires --product")
    elif args.kind == _DOSE_CHANGE:
        if args.role not in fills:
            raise CliError(
                f"dose_change requires a --role with a regimen fill on {on_date}"
            )
        if args.pills <= 0:
            raise CliError("dose_change requires --pills > 0")


def cmd_log(args: _Args, *, write: bool) -> None:
    if args.kind not in _KINDS:
        raise CliError(f"unknown kind {args.kind!r}; one of {', '.join(_KINDS)}")
    on_date = args.date or _today()
    _validate_log(args, on_date, _note_index(), regimen_as_of(_read_events(), on_date))
    events = _read_exceptions()
    ev = StackException(
        id=f"exc-{_next_exc_seq(events) + 1:06d}",
        ts=datetime.now().astimezone().isoformat(),
        date=on_date,
        kind=args.kind,
        scope=args.scope,
        slot=args.slot,
        role=args.role,
        product=args.product,
        pills=args.pills,
        note=args.note,
    )
    line = _exception_log_line(ev)
    dry: dict[str, object] = {"event": ev.model_dump(), "stackLine": line}

    def apply() -> dict[str, object]:
        _append_exception(ev)
        return {**dry, "stackLog": _append_stack_exception_line(line)}

    emit_write("log", _ID_KEY, _ID_VALUE, write=write, dry=dry, apply=apply)


class _Args(argparse.Namespace):
    command: str
    write: bool
    as_of: str | None
    role: str
    product: str
    pills: int
    effective: str
    slot: str
    frequency: str
    label: str
    timing_note: str
    note: str
    kind: str
    scope: str
    date: str


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Canonical nutrient intake across the supplement stack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ing_p = sub.add_parser(
        "ingredients", help="regenerate product-ingredients.jsonl (per-pill amounts)"
    )
    _ = ing_p.add_argument(
        "--write", action="store_true", help="apply (default: dry-run plan)"
    )
    _ = sub.add_parser("totals", help="current daily intake per substance, vs UL")
    _ = sub.add_parser("uls", help="UL-bearing substances only, with headroom")

    mig_p = sub.add_parser("migrate", help="seed the regimen log from current notes")
    _ = mig_p.add_argument("--write", action="store_true", help="apply (default: dry-run)")

    show_p = sub.add_parser("show", help="the regimen as of a date (default today)")
    _ = show_p.add_argument("--as-of", dest="as_of", default=None, help="YYYY-MM-DD")

    hist_p = sub.add_parser("history", help="all regimen events for a role")
    _ = hist_p.add_argument("role", help="role slug (e.g. magnesium_bedtime)")

    proj_p = sub.add_parser("project", help="regenerate the Stack.md regimen block")
    _ = proj_p.add_argument("--write", action="store_true", help="apply (default: dry-run)")

    _ = sub.add_parser("check", help="report product-note mirror drift vs the log")

    set_p = sub.add_parser("set", help="set or supersede a role's product fill")
    _ = set_p.add_argument("role", help="role slug")
    _ = set_p.add_argument("--product", required=True, help="product source_id")
    _ = set_p.add_argument("--pills", type=int, default=1, help="pills per day")
    _ = set_p.add_argument("--effective", required=True, help="YYYY-MM-DD")
    _ = set_p.add_argument("--slot", default="", help="slot (empty for as-needed)")
    _ = set_p.add_argument("--frequency", default=_DAILY, help="daily | as-needed")
    _ = set_p.add_argument("--label", default="", help="display label")
    _ = set_p.add_argument("--timing-note", dest="timing_note", default="", help="parenthetical")
    _ = set_p.add_argument("--note", default="", help="change rationale")
    _ = set_p.add_argument("--write", action="store_true", help="apply (default: dry-run)")

    stop_p = sub.add_parser("stop", help="end a role")
    _ = stop_p.add_argument("role", help="role slug")
    _ = stop_p.add_argument("--effective", required=True, help="YYYY-MM-DD")
    _ = stop_p.add_argument("--note", default="", help="change rationale")
    _ = stop_p.add_argument("--write", action="store_true", help="apply (default: dry-run)")

    log_p = sub.add_parser("log", help="log an exception (miss/taken/extra/...)")
    _ = log_p.add_argument("kind", help="miss | taken | extra | substitute | dose_change")
    _ = log_p.add_argument("--date", default="", help="YYYY-MM-DD (default today)")
    _ = log_p.add_argument("--scope", default="", help="miss scope: day | slot | role")
    _ = log_p.add_argument("--slot", default="", help="slot for a slot-scope miss")
    _ = log_p.add_argument("--role", default="", help="role slug")
    _ = log_p.add_argument("--product", default="", help="product source_id (taken/substitute)")
    _ = log_p.add_argument("--pills", type=int, default=0, help="pills (taken/extra/dose_change)")
    _ = log_p.add_argument("--note", default="", help="free-text note")
    _ = log_p.add_argument("--write", action="store_true", help="apply (default: dry-run)")

    der_p = sub.add_parser("derive", help="regenerate the derived daily intake record")
    _ = der_p.add_argument("--write", action="store_true", help="apply (default: dry-run)")

    day_p = sub.add_parser("day", help="resolved intake for one day (plan +/- exceptions)")
    _ = day_p.add_argument("date", help="YYYY-MM-DD")

    args = parse_typed_args(parser, _Args)
    try:
        if args.command == "ingredients":
            cmd_ingredients(write=args.write)
        elif args.command == "totals":
            cmd_totals()
        elif args.command == "uls":
            cmd_uls()
        elif args.command == "migrate":
            cmd_migrate(write=args.write)
        elif args.command == "show":
            cmd_show(args.as_of)
        elif args.command == "history":
            cmd_history(args.role)
        elif args.command == "project":
            emit_write(
                "project", _ID_KEY, _ID_VALUE, write=args.write,
                dry={"stackBlock": "dry-run"}, apply=lambda: _project_stack(write=True),
            )
        elif args.command == "check":
            cmd_check()
        elif args.command == "set":
            cmd_set(args, write=args.write)
        elif args.command == "stop":
            cmd_stop(args.role, args.effective, args.note, write=args.write)
        elif args.command == "log":
            cmd_log(args, write=args.write)
        elif args.command == "derive":
            cmd_derive(write=args.write)
        else:
            cmd_day(args.date)
    except CliError as e:
        print_json(error_envelope(args.command, _ID_KEY, _ID_VALUE, str(e)))
        sys.exit(e.code)


if __name__ == "__main__":
    main()
