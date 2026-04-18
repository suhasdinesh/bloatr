"""Data models for bloatr."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bloatr.sizes import format_size


@dataclass(frozen=True)
class Item:
    """Represents a single filesystem entry that bloatr can inspect or delete.

    Attributes:
        path: Absolute path to the entry.
        display: Path in ``~/...`` form relative to the user's home directory.
        size: Size in bytes; 0 when the entry is missing or the size could not
            be determined.
        is_dir: True when the entry is a directory.
        error: Human-readable error message if something went wrong during
            scanning; None otherwise.
    """

    path: Path
    display: str
    size: int
    is_dir: bool
    error: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> "Item":
        """Construct an Item from an absolute path.

        The ``display`` field is computed by replacing the user's home
        directory prefix with ``~``.  ``size`` is initialised to 0; callers
        are responsible for populating real size data via a scanner.
        ``is_dir`` reflects whether *path* is a directory at construction
        time.

        Args:
            path: Absolute path to the filesystem entry.

        Returns:
            A new :class:`Item` with ``size=0`` and ``error=None``.
        """
        home = Path.home()
        try:
            relative = path.relative_to(home)
            display = f"~/{relative}"
        except ValueError:
            display = str(path)

        is_dir = path.is_dir()

        return cls(
            path=path,
            display=display,
            size=0,
            is_dir=is_dir,
            error=None,
        )

    def size_display(self) -> str:
        """Return the size formatted as a human-readable string.

        Delegates to :func:`bloatr.sizes.format_size`.

        Returns:
            Human-readable size string, e.g. ``"1.5 GB"``.
        """
        return format_size(self.size)
