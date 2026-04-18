"""Safe deletion utilities for bloatr."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from bloatr.models import Item


class UnsafePathError(Exception):
    """Raised when a path fails the safety check and must not be deleted."""


MIN_DEPTH: int = 1  # Minimum number of path components below home directory.

# Top-level home subdirectories that must never be deleted outright.
_BLOCKLIST: frozenset[str] = frozenset({
    "Library", "Documents", "Desktop", "Downloads",
    "Pictures", "Music", "Movies", "Applications",
    "Public", "Sites",
})

# Subset of _BLOCKLIST whose *contents* are also protected — these hold personal
# files (documents, photos, music, etc.).  ~/Library is intentionally excluded
# here because its subdirectories contain legitimate developer caches that bloatr
# is designed to clean.
_PERSONAL_DIRS: frozenset[str] = frozenset({
    "Documents", "Desktop", "Downloads",
    "Pictures", "Music", "Movies",
    "Public", "Sites",
})


ProgressCallback = Callable[[int, str], None]
"""A callback that receives (bytes_delta, current_path) as deletion progresses."""


def is_safe_path(path: Path) -> bool:
    """Return True only if *path* is safe to delete.

    Safety criteria (all must hold):

    1. The resolved path must be located inside the user's home directory.
    2. The resolved path must be at least :data:`MIN_DEPTH` components below
       the home directory.
    3. The path must not be a bare top-level directory listed in ``_BLOCKLIST``
       (``~/Library``, ``~/Documents``, etc.).

    Symlinks are resolved before the check so that a symlink pointing outside
    the home directory is correctly rejected.

    Args:
        path: The path to check.  Need not exist on disk.

    Returns:
        ``True`` if the path passes the safety checks, ``False`` otherwise.
    """
    home = Path.home().resolve()
    resolved = path.resolve()

    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return False

    if len(relative.parts) < MIN_DEPTH:
        return False

    # Block the top-level directory itself (e.g. ~/Library, ~/Documents).
    if len(relative.parts) == 1 and relative.parts[0] in _BLOCKLIST:
        return False

    # Block anything inside personal directories (e.g. ~/Documents/file.pdf,
    # ~/Desktop/project/).  ~/Library is excluded from this check — its
    # subdirectories (Caches, Developer, …) are legitimate deletion targets.
    if len(relative.parts) > 1 and relative.parts[0] in _PERSONAL_DIRS:
        return False

    return True


def delete(item: "Item", dry_run: bool = False) -> None:
    """Delete the filesystem entry represented by *item* (no progress).

    Simpler wrapper around :func:`delete_with_progress` used by the CLI's
    non-interactive paths and tests.

    Raises:
        UnsafePathError: If ``item.path`` is not safe to delete.
        OSError: If the underlying filesystem operation fails.
    """
    if not is_safe_path(item.path):
        raise UnsafePathError(f"Refusing to delete unsafe path: {item.path!r}")

    if dry_run:
        return

    if item.is_dir:
        shutil.rmtree(item.path)
    else:
        item.path.unlink()


def delete_with_progress(
    item: "Item",
    on_progress: ProgressCallback | None = None,
    dry_run: bool = False,
) -> tuple[int, str | None]:
    """Delete *item* file-by-file so progress can be streamed to a callback.

    Walks the directory bottom-up using :func:`os.walk`, deleting individual
    files and empty subdirectories.  After each file is removed, the caller's
    ``on_progress`` callback is invoked with ``(bytes_freed_delta, path)`` so
    the UI can update a progress bar in real time.

    Args:
        item: The :class:`~bloatr.models.Item` to delete.
        on_progress: Optional callback invoked with ``(bytes_delta, current_path)``
            for every file removed (or once, with the total, in dry-run mode).
        dry_run: When True, report progress but make no filesystem changes.

    Returns:
        A tuple ``(bytes_freed, first_error_or_None)``.  Errors on individual
        files are recorded and processing continues; only the first error
        message is returned.

    Raises:
        UnsafePathError: If ``item.path`` fails the safety check.
    """
    if not is_safe_path(item.path):
        raise UnsafePathError(f"Refusing to delete unsafe path: {item.path!r}")

    if not item.path.exists() and not item.path.is_symlink():
        return 0, "not found"

    # Dry-run: just report the pre-computed size and bail.
    if dry_run:
        if on_progress:
            on_progress(item.size, str(item.path))
        return item.size, None

    # Non-directory path (file or symlink).
    if not item.path.is_dir() or item.path.is_symlink():
        try:
            size = item.path.lstat().st_size
            item.path.unlink()
            if on_progress:
                on_progress(size, str(item.path))
            return size, None
        except OSError as exc:
            return 0, str(exc)

    # Directory: walk bottom-up, delete per-file.
    freed = 0
    first_error: str | None = None
    walk_errors: list[str] = []

    def on_walk_error(exc: OSError) -> None:
        walk_errors.append(str(exc))

    for root, dirs, files in os.walk(
        item.path,
        topdown=False,
        followlinks=False,
        onerror=on_walk_error,
    ):
        for name in files:
            fpath = os.path.join(root, name)
            try:
                st = os.lstat(fpath)
                os.unlink(fpath)
                freed += st.st_size
                if on_progress:
                    on_progress(st.st_size, fpath)
            except OSError as exc:
                if first_error is None:
                    first_error = str(exc)

        for name in dirs:
            dpath = os.path.join(root, name)
            try:
                # rmdir only succeeds on empty dirs; that's the invariant after
                # the files loop above.
                os.rmdir(dpath)
            except OSError as exc:
                if first_error is None:
                    first_error = str(exc)

    try:
        os.rmdir(item.path)
    except OSError as exc:
        if first_error is None:
            first_error = str(exc)

    if first_error is None and walk_errors:
        first_error = walk_errors[0]

    return freed, first_error


def delete_many(
    items: list["Item"],
    dry_run: bool = False,
) -> list[tuple["Item", Exception | None]]:
    """Delete multiple items, capturing any per-item errors.

    Each item is deleted independently via :func:`delete`.  If an exception
    is raised for a particular item it is caught and recorded; processing
    continues with the remaining items.

    Args:
        items: List of :class:`~bloatr.models.Item` objects to delete.
        dry_run: Passed through to :func:`delete` for every item.

    Returns:
        A list of ``(item, error)`` tuples in the same order as *items*.
        ``error`` is ``None`` when deletion succeeded, or the exception
        instance when it failed.
    """
    results: list[tuple[Item, Exception | None]] = []

    for item in items:
        try:
            delete(item, dry_run=dry_run)
            results.append((item, None))
        except Exception as exc:
            results.append((item, exc))

    return results
