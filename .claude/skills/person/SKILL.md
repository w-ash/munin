---
name: person
description: Create or enrich a person note in People/. Pulls details from Apple Contacts and asks the user for anything missing.
user_invocable: true
---

# Person

Create a new person note or enrich an existing one. Combines Apple Contacts lookup with user input.

## Steps

1. **Parse the name** from `$ARGUMENTS` or the user's message. If unclear, ask.

2. **Check if a note exists** — `obsidian search query="$NAME" format=json` and check `People/`.

3. **Look up Apple Contacts** for enrichment (birthday, location, org, job title, `ZUNIQUEID`). See `.claude/rules/apple-contacts.md` for the DB path + query schema. If multiple matches, disambiguate using emails/phones (Ash will help — don't paste them into notes); if no match, note it and move on.

4. **If creating:**
   - Pre-fill frontmatter with Contacts data, including `apple_contact_id` (full `ZUNIQUEID` string with `:ABPerson` suffix). This anchors future lookups when names change or duplicate.
   - Birthdays with year 1604 mean year unknown — use `0000-MM-DD`.
   - Create at `People/entries/$NAME.md` per `.claude/rules/people.md` schema.
   - **Ask the user** for fields Contacts can't provide: pronouns (required — never assume), relationship to Ash, nickname if different from first name.
   - If a name change is involved (marriage, transition), capture both: current `full_name` and `birth_name`.
   - Body: `# Name` heading, bold full name + pronouns, key details as bullets.
   - Link to related people with `[[wikilinks]]`.

5. **If enriching:** read current note. If `apple_contact_id` is set, look up that record directly (stable across renames). Otherwise match by name. Compare against Contacts, show what can be filled, confirm before changing. Ask for anything still missing.

6. **Propagate relationships** when the user establishes one — treat it as a graph operation:

   - Set `parent` / `children` / `siblings` / `partner` (link-type lists) on the new/updated note. Omit empty.
   - **Propagate the inverse** to the other person's note:

     | If you set...     | Add to the other note...         |
     |-------------------|----------------------------------|
     | `parent: [[X]]`   | `children: [[this person]]` on X |
     | `children: [[X]]` | `parent: [[this person]]` on X   |
     | `siblings: [[X]]` | `siblings: [[this person]]` on X |
     | `partner: [[X]]`  | `partner: [[this person]]` on X  |

   - **Infer transitive:** A and B sharing a `parent` → add each to the other's `siblings`. A's `parent` X with other children → those are A's siblings.
   - Show the user all cross-links before making changes.
   - Offer to create People/ notes for related people who don't have one yet.

## Privacy

Don't put email/phone in vault notes unless the user asks. Contact data is enrichment context only.

## File operations

Use the `obsidian` CLI where possible; fall back to direct file ops when it doesn't cover the operation.
