"""Narrow hand-written stub for duckdb under strict basedpyright.

duckdb's own type surface is Any-heavy, which trips reportAny/reportUnknown*;
this stub covers only the surface vault_scripts.db uses. Expand as call sites
appear (same policy as typings/frontmatter/).
"""

from collections.abc import Sequence
from typing import Self

class Error(Exception): ...

class DuckDBPyConnection:
    description: list[tuple[str, str, None, None, None, None, None]] | None
    def execute(
        self, query: str, parameters: Sequence[object] | None = None
    ) -> Self: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def fetchmany(self, size: int = 1) -> list[tuple[object, ...]]: ...
    def close(self) -> None: ...

def connect(
    database: str = ":memory:", read_only: bool = False
) -> DuckDBPyConnection: ...
