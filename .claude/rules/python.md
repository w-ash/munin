---
description: Python tooling defaults — uv for package management, Python 3.14 preferred
paths:
  - "**/*.py"
  - "**/pyproject.toml"
  - "**/requirements*.txt"
  - "**/uv.lock"
---

# Python tooling

Use `uv` exclusively for package management. Prefer Python 3.14 when the project allows.

For the vault's own Python package at `scripts/vault_scripts/`, see `.claude/rules/scripts.md` for stricter conventions (basedpyright, type discipline, dispatcher, etc.).
