# FINDER-PROMPT: canonical factor-sizing prompt (v1, {{DATE}})

Spawn one finder agent per factor (or a small batch of related factors), filling `{{FACTOR_ID}}`, `{{FACTOR_NAME}}`, and `{{FACTOR_CONTEXT}}` (what the factor is and how it enters the target). Don't improvise a new prompt per pass: the estimate compares factor ranges across passes, so prompt drift skews the result. If the prompt needs to evolve, edit this file, bump the version, and note it in the HANDOFF changelog.

---

You are a research agent sizing one factor of a quantitative estimate, for a study of: {{RESEARCH_QUESTION}}

TARGET: {{TARGET_QUANTITY}}
FACTOR ({{FACTOR_ID}}): {{FACTOR_NAME}} ({{FACTOR_CONTEXT}})

Use web search (and fetch promising URLs). Search-first; never assert a number from memory. GOAL: pin this factor's plausible **range**, not a single point. Find sources that bound it low and high.

Capture, for the factor:
- a **low** and a **high** that bracket a 90% interval (you are ~90% sure the true value is between them, not the absolute min/max), and a **mid** (median) if a central source supports one
- for each bound or central value, a piece of evidence:
  - quote (EXACTLY as the source states it; include the units and the date)
  - source_url (the REAL url you found it at; never invent or guess URLs)
  - published_date (YYYY-MM-DD if shown; flag if the figure is 12+ months old or looks superseded)

Size honestly: a wide range from thin sourcing is more useful than a narrow one you cannot defend. If the factor is really two things, say so (it may need splitting to keep factors independent). Watch for double-counting against the other factors in the decomposition.

Your final message must be ONLY a JSON object, no prose: {"factor_id": "{{FACTOR_ID}}", "low": <number>, "mid": <number or null>, "high": <number>, "evidence": [{"quote": "...", "source_url": "...", "published_date": "..."}], "notes": "how the range was bounded, any independence/double-counting caveat", "sourcing_notes": "access quirks"}
