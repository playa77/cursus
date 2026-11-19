"""Disposable workspaces; later packages add external boundary fixtures here."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Iterator


@dataclass(frozen=True)
class Workspace:
    root: Path
    state: Path
    artifacts: Path
    worktrees: Path


@contextmanager
def workspace() -> Iterator[Workspace]:
    """Create only empty isolated directories, never synthetic Cursus state."""
    with TemporaryDirectory(prefix="cursus test — ") as directory:
        root = Path(directory)
        paths = [root / name for name in ("state", "artifacts", "worktrees")]
        for path in paths:
            path.mkdir(mode=0o700)
        yield Workspace(root, *paths)
