"""Verifies backlog_lock serialises concurrent writers across processes.

Uses subprocess.Popen directly (not multiprocessing) to avoid pytest's
fork/thread interaction issues — we just need a second OS process with a
fresh open() of the lock file.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

from backlog_mcp.file_lock import backlog_lock


HOLDER_SCRIPT = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    from backlog_mcp.file_lock import backlog_lock
    backlog = Path(sys.argv[1])
    hold = float(sys.argv[2])
    marker = sys.argv[3]
    with backlog_lock(backlog):
        text = backlog.read_text()
        time.sleep(hold)
        backlog.write_text(text + marker + "\\n")
""")


def _spawn_holder(backlog: Path, hold_s: float, marker: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", HOLDER_SCRIPT, str(backlog), str(hold_s), marker],
    )


def test_backlog_lock_serializes_processes(tmp_path):
    """A's critical section must complete before B's even though B is started
    while A is still mid-section. Both markers must end up in the file."""
    backlog = tmp_path / "Backlog.md"
    backlog.write_text("seed\n")

    a = _spawn_holder(backlog, 0.5, "A")
    time.sleep(0.1)  # ensure A grabbed the lock first
    b = _spawn_holder(backlog, 0.1, "B")

    assert a.wait(timeout=10) == 0
    assert b.wait(timeout=10) == 0

    text = backlog.read_text()
    assert "A\n" in text and "B\n" in text, text
    assert text.startswith("seed\n")
    # If the lock did NOT serialise, B (which read text before A finished writing)
    # would have written `seed\nB\n`, clobbering A. So `A\n` appearing AFTER
    # `seed\n` and before `B\n` confirms serialisation.
    assert text.index("A\n") < text.index("B\n"), text


def test_backlog_lock_releases_on_exit(tmp_path):
    """Sanity: after context exits, lock is releasable by a fresh acquire."""
    backlog = tmp_path / "Backlog.md"
    backlog.write_text("seed\n")
    with backlog_lock(backlog):
        pass
    # A second acquire should not block.
    t0 = time.monotonic()
    with backlog_lock(backlog):
        pass
    assert time.monotonic() - t0 < 1.0
