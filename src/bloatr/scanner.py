"""Concurrent directory scanner for bloatr."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bloatr.models import Item


def compute_size(path: Path) -> tuple[int, str | None]:
    """Compute the total size of a directory tree iteratively.

    Uses an explicit stack to avoid hitting Python's recursion limit on deep
    directory trees.  Symlinks are skipped entirely.  Per-entry permission
    errors are swallowed; the first error message is returned alongside the
    partial size.

    Args:
        path: Root directory to measure.

    Returns:
        A ``(total_bytes, first_error_or_None)`` tuple.
    """
    if not path.exists():
        return 0, "not found"

    if path.is_file():
        try:
            return path.stat().st_size, None
        except OSError as exc:
            return 0, str(exc)

    total = 0
    first_error: str | None = None
    stack: list[str] = [str(path)]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except (PermissionError, OSError) as exc:
                        if first_error is None:
                            first_error = str(exc)
        except (PermissionError, OSError) as exc:
            if first_error is None:
                first_error = str(exc)

    return total, first_error


def _size_one(path: Path) -> Item:
    """Size a single location and return a complete Item."""
    base = Item.from_path(path)

    if not path.exists():
        return Item(
            path=path,
            display=base.display,
            size=0,
            is_dir=False,
            error="not found",
        )

    size, error = compute_size(path)
    return Item(
        path=path,
        display=base.display,
        size=size,
        is_dir=path.is_dir(),
        error=error,
    )


def scan_locations(paths: list[Path], max_workers: int = 8) -> list[Item]:
    """Scan a list of locations concurrently and return Items sorted by size.

    Each path is measured in a separate thread.  Missing paths produce an Item
    with ``error="not found"`` and ``size=0``.

    Args:
        paths: Absolute paths to scan.
        max_workers: Thread pool size (default 8).

    Returns:
        List of :class:`~bloatr.models.Item` objects sorted descending by size.
    """
    results: list[Item] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_path = {pool.submit(_size_one, p): p for p in paths}
        for future in as_completed(future_to_path):
            try:
                results.append(future.result())
            except Exception as exc:
                p = future_to_path[future]
                base = Item.from_path(p)
                results.append(
                    Item(
                        path=p,
                        display=base.display,
                        size=0,
                        is_dir=False,
                        error=str(exc),
                    )
                )

    results.sort(key=lambda i: i.size, reverse=True)
    return results


def list_children(item: Item) -> list[Item]:
    """Return immediate children of a directory item, sorted by size desc.

    Each child is sized individually.  Non-directory items and missing paths
    return an empty list.

    Args:
        item: The parent directory item to drill into.

    Returns:
        Sorted list of child :class:`~bloatr.models.Item` objects.
    """
    if not item.is_dir or not item.path.exists():
        return []

    children: list[Path] = []
    try:
        with os.scandir(item.path) as it:
            for entry in it:
                if not entry.name.startswith(".") or True:  # show hidden too
                    children.append(Path(entry.path))
    except (PermissionError, OSError):
        return []

    return scan_locations(children)
