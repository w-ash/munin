---
description: "Python tooling defaults: uv for package management, Python 3.14 preferred"
paths:
  - "**/*.py"
  - "**/pyproject.toml"
  - "**/requirements*.txt"
  - "**/uv.lock"
---

# Python tooling

Use `uv` exclusively for package management. Prefer Python 3.14 when the project allows.

Don't paper over failures; fix the root cause. Replace a strippable `assert` with a real guard that raises or narrows the type (asserts vanish under `python -O`). A lint, type, or security finding gets a targeted one-line ignore with a reason only when the tool is provably wrong, never a blanket ignore. A failing check or measurement is evidence, not noise: investigate before dismissing it as an artifact.

For the vault's own Python package at `scripts/vault_scripts/`, see `.claude/rules/scripts.md` for stricter conventions (basedpyright, type discipline, dispatcher, etc.).
