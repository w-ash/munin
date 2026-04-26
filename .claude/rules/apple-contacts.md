---
description: How to enrich People notes using the local Apple Contacts database
globs: People/**
---

# Apple Contacts Enrichment

Ash's Apple Contacts are readable via SQLite. Use this for enrichment (birthday, location, organization) instead of asking Ash to type it all.

## When to use

- Creating new person notes — offer to look up the contact
- Filling in missing frontmatter (birthday, location, organization)
- Verifying spelling of names

## Database location

iCloud-synced (most contacts):
```
~/Library/Application Support/AddressBook/Sources/<UUID>/AddressBook-v22.abcddb
```

Discover the UUID: `ls ~/Library/Application\ Support/AddressBook/Sources/`

Local-only fallback: `~/Library/Application Support/AddressBook/AddressBook-v22.abcddb`

## Query

Join `ZABCDPOSTALADDRESS` on `ZOWNER = r.Z_PK` for city/state:

```sql
SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.ZORGANIZATION, r.ZJOBTITLE,
       DATE(r.ZBIRTHDAY + 978307200, 'unixepoch') AS birthday,
       a.ZCITY, a.ZSTATE
FROM ZABCDRECORD r
LEFT JOIN ZABCDPOSTALADDRESS a ON a.ZOWNER = r.Z_PK
WHERE r.ZFIRSTNAME = '$FIRST' AND r.ZLASTNAME = '$LAST';
```

`ZBIRTHDAY` is a Core Data timestamp (seconds since 2001-01-01). The `+ 978307200` converts to Unix epoch. Year 1604 means year unknown — use `0000-MM-DD` format in frontmatter.

## Privacy

- **Do not** paste raw email addresses or phone numbers into vault notes unless Ash explicitly asks. We intentionally ignore `ZABCDEMAILADDRESS`, `ZABCDPHONENUMBER`, `ZABCDSOCIALPROFILE`, `ZABCDURLADDRESS`.
- Contact data is for enrichment context (birthday, city, org) only.
- Always use `$HOME` expansion or quoted paths with sqlite3 — the source dir has spaces.
