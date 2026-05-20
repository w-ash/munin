---
description: Rules for person notes in the People/ folder
paths:
  - "People/**"
---

# People Conventions

## Required frontmatter

```yaml
created: YYYY-MM-DD
tags:
  - person
full_name: ""
nickname: ""
pronouns: ""
relationship: ""    # e.g. partner, brother, friend, coworker — describes relationship to Ash
location: ""        # e.g. Oakland, CA
birthday:           # YYYY-MM-DD (use 0000 for year if unknown)
apple_contact_id: "" # ZUNIQUEID from Apple Contacts, full string incl. ":ABPerson" suffix
```

Optional properties as needed:
- `birth_name` — prior legal name (use this, not "maiden name")
- `birth_year` — for age formulas in Bases
- `deceased: true` — set when the person has passed away

## Relationship properties (optional, link-type lists)

These describe relationships **to other people in the vault**, not to Ash (that's what `relationship` is for). Use wikilinks so Obsidian renders them as clickable links and Bases can query them.

```yaml
parent:             # e.g. ["[[Jamie]]"]
children:           # e.g. ["[[Ash]]", "[[Tristan]]", "[[Alex]]"]
siblings:           # e.g. ["[[Tristan]]", "[[Alex]]"]
partner:            # e.g. ["[[Kew]]"] — covers spouse, partner, girlfriend, boyfriend
```

Only include properties that apply — don't add empty lists. These properties are **bidirectional**: when you set `parent: [[Jamie]]` on Ash, Jamie's note should have `children: [[Ash]]`. The `/person` skill handles propagation automatically.

## Body structure

```markdown
# [Nickname or Name]

**Full Name** (pronouns). Brief description of who they are.

- Key details (what they do, where they live, relationship to Ash)
- Notable facts, shared history
```

## Rules

- Don't duplicate Ash's info — link to `[[Ash]]` rather than restating.
- Ask before assuming relationship details, pronouns, or other personal info.
