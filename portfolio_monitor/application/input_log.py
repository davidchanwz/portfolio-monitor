"""Input log: append-only, arrival-ordered record of every command.

This is the source of truth and the unit of replication: any replica that applies the
same entries in the same order reaches the same state.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_monitor.application.commands import BATCH_COMMANDS, Command


@dataclass(frozen=True)
class LogEntry:
    seq: int
    command: Command


class InputLog:
    def __init__(self) -> None:
        self._entries: list[LogEntry] = []

    def append(self, command: Command) -> LogEntry:
        entry = LogEntry(seq=len(self._entries) + 1, command=command)
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[LogEntry, ...]:
        return tuple(self._entries)

    def next_upload_no(self) -> int:
        """Upload numbers are user-facing (1, 2, 3 ...) and derived from the log, so replicas agree."""
        return 1 + sum(isinstance(e.command, BATCH_COMMANDS) for e in self._entries)
