from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def commit_and_push(repo_root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_root, check=True, capture_output=True)
    try:
        subprocess.run(["git", "push"], cwd=repo_root, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.warning("git push failed (changes committed locally): %s", e.stderr.decode())
