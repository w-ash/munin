"""Unit tests for the shared frontmatter helpers in ``_utils``: YAML scalar
escaping and field upsert/insert scoped to the frontmatter block (a ``key:`` line
in the note body must never be treated as a field). No filesystem — strings in,
strings out, with ``frontmatter.loads`` used to assert round-trip values."""

from __future__ import annotations

import frontmatter

from vault_scripts._utils import (
    has_field,
    insert_field_after,
    patch_field,
    yaml_scalar,
)

_NOTE = "---\nname: Cafe\naddress: 1-2-3\n---\nNotes about the place.\n"


# --- yaml_scalar escaping (round-trips through YAML) ---


def test_yaml_scalar_escapes_backslash():
    # A value with a backslash must survive the double-quoted YAML round-trip;
    # unescaped, "C:\temp" reads back as "C:<TAB>emp".
    out = patch_field(_NOTE, "path", "C:\\temp")
    assert frontmatter.loads(out)["path"] == "C:\\temp"


def test_yaml_scalar_escapes_trailing_backslash_and_quote():
    value = 'a"b\\'  # embedded double-quote and a trailing backslash
    out = patch_field(_NOTE, "path", value)
    assert frontmatter.loads(out)["path"] == value


def test_yaml_scalar_bare_for_bool_and_int():
    assert yaml_scalar(True) == "true"
    assert yaml_scalar(0) == "0"
    assert yaml_scalar("") == '""'


# --- field scans/edits ignore the note body ---


def test_has_field_ignores_body_line():
    note = _NOTE + "website: this is body prose, not frontmatter\n"
    assert has_field(note, "website") is False
    assert has_field(note, "name") is True


def test_patch_field_inserts_into_frontmatter_not_body():
    note = _NOTE + "website: body prose, not a field\n"
    out = patch_field(note, "website", "https://cafe.example")
    # The real field lands in the frontmatter...
    assert frontmatter.loads(out)["website"] == "https://cafe.example"
    # ...and the colliding body line is left untouched.
    assert "website: body prose, not a field\n" in out


def test_patch_field_replaces_existing_frontmatter_value():
    out = patch_field("---\nname: Old\n---\nbody\n", "name", "New")
    assert frontmatter.loads(out)["name"] == "New"
    assert out.endswith("body\n")


def test_insert_field_after_targets_frontmatter_anchor():
    note = "---\naddress: A\n---\naddress: a body line\n"
    out = insert_field_after(note, "address", "address_local", "B")
    assert frontmatter.loads(out)["address_local"] == "B"
    # body line preserved
    assert "address: a body line\n" in out
