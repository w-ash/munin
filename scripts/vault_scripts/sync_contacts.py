"""Sync Apple Contacts (with birthdays) → People/ notes in the Obsidian vault.

Usage:
    scripts/vault-tool sync_contacts            # dry-run
    scripts/vault-tool sync_contacts --write    # create notes
    scripts/vault-tool sync_contacts --enrich   # update existing notes
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import TypedDict, cast

from vault_scripts._utils import VAULT, has_field, parse_typed_args, patch_field

PEOPLE_DIR = VAULT / "People"
PEOPLE_ENTRIES = PEOPLE_DIR / "entries"
CORE_DATA_EPOCH = 978307200  # seconds between Unix epoch and 2001-01-01
YEAR_UNKNOWN_SENTINEL = 1604  # Contacts stores "year unknown" birthdays here
NAME_WITH_MIDDLE = 2  # len(["First", "Last"]) == 2; middle name lands at 3+


class Contact(TypedDict):
    first: str
    last: str
    nickname: str
    org: str
    job_title: str
    birthday: str | None
    city: str
    state: str


def find_contacts_db() -> Path:
    """Find the iCloud-synced AddressBook database."""
    base = Path.home() / "Library" / "Application Support" / "AddressBook"
    sources = base / "Sources"
    if sources.exists():
        uuids = [d for d in sources.iterdir() if d.is_dir()]
        if uuids:
            db = uuids[0] / "AddressBook-v22.abcddb"
            if db.exists():
                return db
    return base / "AddressBook-v22.abcddb"


def convert_birthday(ts: float | None) -> str | None:
    """Convert Core Data timestamp to YYYY-MM-DD, using 0000 for unknown year."""
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts + CORE_DATA_EPOCH, tz=UTC)
    if dt.year == YEAR_UNKNOWN_SENTINEL:
        return f"0000-{dt.month:02d}-{dt.day:02d}"
    return dt.strftime("%Y-%m-%d")


def _s(row: sqlite3.Row, key: str) -> str:
    """Coerce a possibly-None SQLite cell to string."""
    val = cast(object, row[key])
    return str(val) if val is not None else ""


def _f(row: sqlite3.Row, key: str) -> float | None:
    """Coerce a SQLite cell to float or None. ZBIRTHDAY is a REAL column."""
    val = cast(float | int | None, row[key])
    return float(val) if val is not None else None


def query_contacts(db_path: Path) -> list[Contact]:
    """Query all contacts that have birthdays."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = cast(
            list[sqlite3.Row],
            conn.execute("""
            SELECT r.ZFIRSTNAME AS first, r.ZLASTNAME AS last, r.ZNICKNAME AS nickname,
                   r.ZORGANIZATION AS org, r.ZJOBTITLE AS job_title,
                   r.ZBIRTHDAY AS birthday_ts,
                   a.ZCITY AS city, a.ZSTATE AS state
            FROM ZABCDRECORD r
            LEFT JOIN ZABCDPOSTALADDRESS a ON a.ZOWNER = r.Z_PK
            WHERE r.ZBIRTHDAY IS NOT NULL AND r.ZFIRSTNAME IS NOT NULL
            ORDER BY r.ZFIRSTNAME, r.ZLASTNAME
        """).fetchall(),
        )
    finally:
        conn.close()

    seen: set[tuple[str, str]] = set()
    contacts: list[Contact] = []
    for row in rows:
        first = _s(row, "first")
        last = _s(row, "last")
        key = (first, last)
        if key in seen:
            continue
        seen.add(key)
        contacts.append(
            Contact(
                first=first,
                last=last,
                nickname=_s(row, "nickname"),
                org=_s(row, "org"),
                job_title=_s(row, "job_title"),
                birthday=convert_birthday(_f(row, "birthday_ts")),
                city=_s(row, "city"),
                state=_s(row, "state"),
            )
        )
    return contacts


def existing_people(people_dir: Path) -> dict[str, Path]:
    """Map name variants → file path for existing People notes.

    Matches on full_name, first+last (ignoring middle), and filename.
    """
    people: dict[str, Path] = {}
    for f in people_dir.rglob("*.md"):
        people[f.stem.lower()] = f
        for line in f.read_text().splitlines():
            if line.startswith("full_name:"):
                name = line.split(":", 1)[1].strip().strip('"').strip("'")
                if name:
                    people[name.lower()] = f
                    parts = name.split()
                    if len(parts) > NAME_WITH_MIDDLE:
                        people[f"{parts[0]} {parts[-1]}".lower()] = f
                break
    return people


def make_location(city: str, state: str) -> str:
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


def generate_note(contact: Contact) -> str:
    """Generate a People/ note from contact data."""
    first = contact["first"]
    last = contact["last"]
    full_name = f"{first} {last}".strip()
    raw_nick = contact["nickname"]
    nickname = raw_nick if raw_nick and raw_nick != first else first
    location = make_location(contact["city"], contact["state"])
    birthday = contact["birthday"] or ""
    today = datetime.now(tz=UTC).date().isoformat()

    lines: list[str] = [
        "---",
        f'created: "{today}"',
        "tags:",
        "  - person",
        f'full_name: "{full_name}"',
        f'nickname: "{nickname}"',
        'pronouns: ""',
        'relationship: ""',
        f'location: "{location}"' if location else 'location: ""',
    ]
    if birthday:
        lines.append(f"birthday: {birthday}")
    lines.extend(["---", "", f"# {nickname}", "", f"**{full_name}**.", ""])

    if location:
        lines.append(f"- Lives in {location}")
    if contact["org"]:
        if contact["job_title"]:
            lines.append(f"- {contact['job_title']} at {contact['org']}")
        else:
            lines.append(f"- Works at {contact['org']}")

    return "\n".join(lines) + "\n"


class _Args(argparse.Namespace):
    write: bool
    enrich: bool


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Apple Contacts → People/ notes")
    _ = parser.add_argument(
        "--write", action="store_true", help="Actually write files (default is dry-run)"
    )
    _ = parser.add_argument(
        "--enrich",
        action="store_true",
        help="Update existing notes with missing birthdays",
    )
    args = parse_typed_args(parser, _Args)

    db_path = find_contacts_db()
    contacts = query_contacts(db_path)
    existing = existing_people(PEOPLE_DIR)

    new_contacts = [
        c
        for c in contacts
        if f"{c['first']} {c['last']}".strip().lower() not in existing
    ]
    first_name_counts: dict[str, int] = {}
    for c in new_contacts:
        first_name_counts[c["first"]] = first_name_counts.get(c["first"], 0) + 1

    to_create: list[tuple[Contact, str]] = []
    to_enrich: list[tuple[Contact, Path]] = []

    for contact in contacts:
        full_name = f"{contact['first']} {contact['last']}".strip()
        key = full_name.lower()
        if key in existing:
            if args.enrich and contact["birthday"]:
                to_enrich.append((contact, existing[key]))
            continue
        filename = (
            f"{contact['first']} {contact['last']}"
            if first_name_counts.get(contact["first"], 0) > 1
            else contact["first"]
        )
        to_create.append((contact, filename))

    print(f"\n📋 Apple Contacts with birthdays: {len(contacts)}")
    print(f"✅ Already in People/: {len(contacts) - len(to_create)}")
    print(f"🆕 To create: {len(to_create)}")
    if args.enrich:
        print(f"🔄 To enrich: {len(to_enrich)}")

    if to_create:
        print(f"\n{'Name':<30} {'Birthday':<12} {'Location':<25} {'Org':<30}")
        print("─" * 97)
        for contact, _filename in to_create:
            full_name = f"{contact['first']} {contact['last']}".strip()
            loc = make_location(contact["city"], contact["state"])
            bday = contact["birthday"] or ""
            print(f"{full_name:<30} {bday:<12} {loc:<25} {contact['org']:<30}")

    if args.write and to_create:
        print("\n✏️  Writing files...")
        for contact, filename in to_create:
            path = PEOPLE_ENTRIES / f"{filename}.md"
            if path.exists():
                print(f"  ⚠️  Skipping {path.name} (already exists)")
                continue
            path.write_text(generate_note(contact))
            print(f"  ✅ Created {path.name}")

    if args.enrich and to_enrich:
        print("\n🔄 Enriching existing notes with missing birthdays...")
        for contact, path in to_enrich:
            text = path.read_text()
            # Only fill a missing birthday — never overwrite a hand-entered one
            # (Contacts may hold a less precise year-unknown value).
            if has_field(text, "birthday"):
                continue
            new_text = patch_field(text, "birthday", contact["birthday"])
            if new_text != text:
                if args.write:
                    path.write_text(new_text)
                    print(f"  ✅ Added birthday to {path.name}: {contact['birthday']}")
                else:
                    print(f"  Would add birthday to {path.name}: {contact['birthday']}")

    if not args.write and to_create:
        print("\n💡 Run with --write to create these files.")


if __name__ == "__main__":
    main()
