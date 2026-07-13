"""Unit tests for the ``fm`` bulk frontmatter editor. The core promise is that
setting one field leaves every other line byte-for-byte intact (unlike
``obsidian property:set``, which re-serializes the whole block and strips the
vault's convention quotes). Assignment parsing and the all-or-nothing write
guard are covered too. Filesystem tests use ``tmp_path``; the rest are strings
in, strings out."""

from __future__ import annotations

import re

import frontmatter
import pytest

from vault_scripts.fm import (
    FmError,
    apply_assignments,
    parse_assignment,
    run_set,
)

# A note that carries every quoting case the tool must preserve: a quoted date,
# quoted coordinates, and a bare enum.
_NOTE = (
    "---\n"
    'created: "2026-07-02"\n'
    "tags:\n"
    "  - provider\n"
    'name: "Albany Physical Therapy"\n'
    "specialty: pt\n"
    'coordinates: "37.8885, -122.2992"\n'
    "rating:\n"
    "last_visited:\n"
    "---\n"
    "\n"
    "# Albany Physical Therapy\n"
    "body line with a stray key: value that must be ignored\n"
)


# --- assignment parsing ---


def test_parse_assignment_string_is_quoted_value():
    field, value = parse_assignment("status=candidate")
    assert field == "status"
    assert value == "candidate"  # str; yaml_scalar will quote it


def test_parse_assignment_empty_value():
    field, value = parse_assignment("rank=")
    assert field == "rank"
    assert value == ""


def test_parse_assignment_typed_values():
    assert parse_assignment("score:int=44") == ("score", 44)
    assert parse_assignment("weight:float=1.5") == ("weight", 1.5)
    assert parse_assignment("done:bool=true") == ("done", True)
    assert parse_assignment("done:bool=false") == ("done", False)


def test_parse_assignment_hyphenated_field():
    assert parse_assignment("rec-for-friends:bool=true") == ("rec-for-friends", True)


def test_parse_assignment_rejects_non_assignment():
    with pytest.raises(FmError):
        parse_assignment("Health/Providers/entries/Foo.md")


def test_parse_assignment_rejects_bad_type():
    with pytest.raises(FmError):
        parse_assignment("score:int=not-a-number")
    with pytest.raises(FmError):
        parse_assignment("flag:bogus=x")


# --- apply_assignments preserves the rest of the block ---


def test_apply_preserves_other_lines_quoting():
    out, changes = apply_assignments(
        _NOTE, [("status", "candidate"), ("score", 44)], after=None
    )
    # Untouched lines keep their exact quoting.
    assert 'created: "2026-07-02"' in out
    assert 'coordinates: "37.8885, -122.2992"' in out
    assert "specialty: pt" in out  # bare enum untouched
    # New string field is quoted (yaml_scalar); the int value serializes bare.
    assert 'status: "candidate"' in out
    assert "score: 44\n" in out
    # A body line that looks like a field is never touched.
    assert "body line with a stray key: value that must be ignored" in out
    assert [c["action"] for c in changes] == ["added", "added"]


def test_apply_int_type_is_bare():
    out, _ = apply_assignments(_NOTE, [("score", 44)], after=None)
    # value 44 (an int) formats bare; assignment parsing does the int cast.
    assert "score: 44\n" in out
    assert frontmatter.loads(out)["score"] == 44


def test_apply_round_trips_string_value():
    out, _ = apply_assignments(_NOTE, [("status", "candidate")], after=None)
    assert frontmatter.loads(out)["status"] == "candidate"


def test_apply_after_positions_new_field():
    note = "---\nstatus: candidate\nformat: in-person\n---\nbody\n"
    out, _ = apply_assignments(note, [("rank", "strong")], after="status")
    assert re.search(r'status: candidate\nrank: "strong"\nformat: in-person', out)


def test_apply_reports_update_for_existing_field():
    note = "---\nstatus: candidate\n---\nbody\n"
    _out, changes = apply_assignments(note, [("status", "shortlist")], after=None)
    assert changes[0]["action"] == "updated"
    assert changes[0]["from"] == "candidate"
    assert changes[0]["to"] == "shortlist"


# --- run_set: resolution, dry-run, and the all-or-nothing write guard ---


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_run_set_dry_run_does_not_write(tmp_path):
    p = tmp_path / "note.md"
    arg = _write(p, '---\ncreated: "2026-07-02"\nname: "X"\n---\nbody\n')
    res = run_set([arg, "status=candidate"], after=None, write=False)
    assert res["dryRun"] is True
    assert res["written"] is False
    assert res["summary"]["changed"] == 1
    assert "status" not in p.read_text()  # untouched on disk


def test_run_set_write_persists_and_preserves_quotes(tmp_path):
    p = tmp_path / "note.md"
    arg = _write(
        p,
        '---\ncreated: "2026-07-02"\ncoordinates: "1.0, 2.0"\nspecialty: pt\n---\nbody\n',
    )
    res = run_set([arg, "status=candidate", "score:int=44"], after=None, write=True)
    assert res["written"] is True
    out = p.read_text()
    assert 'created: "2026-07-02"' in out
    assert 'coordinates: "1.0, 2.0"' in out
    assert "specialty: pt" in out
    assert 'status: "candidate"' in out
    assert "score: 44" in out


def test_run_set_missing_file_raises(tmp_path):
    with pytest.raises(FmError):
        run_set([str(tmp_path / "nope.md"), "x=1"], after=None, write=True)


def test_run_set_requires_paths_and_assignments(tmp_path):
    p = tmp_path / "note.md"
    arg = _write(p, "---\nname: X\n---\nbody\n")
    with pytest.raises(FmError):
        run_set(["status=candidate"], after=None, write=False)  # no path
    with pytest.raises(FmError):
        run_set([arg], after=None, write=False)  # no assignment


def test_run_set_no_frontmatter_aborts_whole_batch(tmp_path):
    good = tmp_path / "good.md"
    bad = tmp_path / "bad.md"
    good_arg = _write(good, '---\nname: "A"\n---\nb\n')
    bad_arg = _write(bad, "no frontmatter here\n")
    res = run_set([good_arg, bad_arg, "status=candidate"], after=None, write=True)
    assert res["ok"] is False
    assert res["written"] is False  # all-or-nothing: nothing written
    assert "aborted" in res
    assert (
        "status" not in good.read_text()
    )  # the good file was spared, not half-applied
