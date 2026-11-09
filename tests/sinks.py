"""A hook sink that keeps what it is told, for the tests that drive the dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Recorder:
    """A sink that keeps its records and markers in memory."""

    records: list[dict[str, object]] = field(default_factory=list)
    marks: set[str] = field(default_factory=set)

    def diagnostic(self, record: dict[str, object]) -> None:
        self.records.append(record)

    def seen(self, key: str) -> bool:
        return key in self.marks

    def mark(self, key: str) -> None:
        self.marks.add(key)
