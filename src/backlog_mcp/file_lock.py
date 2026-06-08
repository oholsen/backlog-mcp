"""Cross-process fcntl advisory lock for backlog write+commit pipelines.

The HTTP server's asyncio lock only serializes within its own process; a
concurrent stdio MCP, editor save, or second backlog-agent can still race
on the same Backlog.md. This lock — held on a sibling `.lock` file via
`fcntl.flock(LOCK_EX)` — gives mutual exclusion across all processes that
honour it.

Advisory only: a process that doesn't take the lock can still clobber the
file. All backlog write paths must wrap their read-modify-write-commit
pipeline in `backlog_lock(BACKLOG_PATH)` for this to be effective.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


@contextmanager
def backlog_lock(backlog_path: Path) -> Iterator[None]:
    lock_path = backlog_path.with_suffix(backlog_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
