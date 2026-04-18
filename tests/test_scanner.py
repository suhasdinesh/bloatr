"""Tests for bloatr.scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from bloatr.scanner import compute_size, list_children, scan_locations
from bloatr.models import Item


def make_tree(root: Path, spec: dict) -> None:
    """Recursively create files/dirs from a nested dict.

    String values are file contents; dict values are subdirectories.
    """
    for name, content in spec.items():
        path = root / name
        if isinstance(content, dict):
            path.mkdir(parents=True, exist_ok=True)
            make_tree(path, content)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)


# ------------------------------------------------------------------ #
# compute_size
# ------------------------------------------------------------------ #


def test_compute_size_empty_dir(tmp_path: Path) -> None:
    size, error = compute_size(tmp_path)
    assert size == 0
    assert error is None


def test_compute_size_with_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"x" * 100)
    (tmp_path / "b.txt").write_bytes(b"x" * 200)
    (tmp_path / "c.txt").write_bytes(b"x" * 300)
    size, error = compute_size(tmp_path)
    assert size == 600
    assert error is None


def test_compute_size_nested(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "sub": {
            "file1.txt": "hello",   # 5 bytes
            "file2.txt": "world!",  # 6 bytes
        },
        "root.txt": "abc",          # 3 bytes
    })
    size, error = compute_size(tmp_path)
    assert size == 14
    assert error is None


def test_compute_size_skips_symlinks(tmp_path: Path) -> None:
    big_file = tmp_path / "big.bin"
    big_file.write_bytes(b"x" * 10_000)

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    link = subdir / "link_to_big"
    link.symlink_to(big_file)

    # Only the real big.bin should be counted (it's in tmp_path root, not subdir).
    # The symlink inside subdir must be skipped.
    size, error = compute_size(subdir)
    assert size == 0  # subdir contains only a symlink — skipped
    assert error is None


def test_compute_size_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    size, error = compute_size(missing)
    assert size == 0
    assert error is not None


def test_compute_size_file(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_bytes(b"hello world")
    size, error = compute_size(f)
    assert size == 11
    assert error is None


# ------------------------------------------------------------------ #
# scan_locations
# ------------------------------------------------------------------ #


def test_scan_locations_sorts_by_size(tmp_path: Path) -> None:
    small = tmp_path / "small"
    small.mkdir()
    (small / "f.txt").write_bytes(b"x" * 50)

    large = tmp_path / "large"
    large.mkdir()
    (large / "f.txt").write_bytes(b"x" * 500)

    results = scan_locations([small, large])
    assert results[0].path == large
    assert results[1].path == small


def test_scan_locations_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "ghost"
    results = scan_locations([missing])
    assert len(results) == 1
    assert results[0].size == 0
    assert results[0].error is not None


def test_scan_locations_mixed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "f.txt").write_bytes(b"data")

    missing = tmp_path / "ghost"

    results = scan_locations([real, missing])
    assert len(results) == 2
    paths = {r.path for r in results}
    assert real in paths
    assert missing in paths


def test_scan_locations_empty_input() -> None:
    results = scan_locations([])
    assert results == []


# ------------------------------------------------------------------ #
# list_children
# ------------------------------------------------------------------ #


def test_list_children_returns_children(tmp_path: Path) -> None:
    for name in ["alpha", "beta", "gamma"]:
        d = tmp_path / name
        d.mkdir()
        (d / "f.txt").write_bytes(b"x" * 100)

    parent_item = Item(
        path=tmp_path,
        display=f"~/{tmp_path.name}",
        size=300,
        is_dir=True,
    )
    children = list_children(parent_item)
    assert len(children) == 3


def test_list_children_sorted(tmp_path: Path) -> None:
    small = tmp_path / "small"
    small.mkdir()
    (small / "f.txt").write_bytes(b"x" * 10)

    large = tmp_path / "large"
    large.mkdir()
    (large / "f.txt").write_bytes(b"x" * 1000)

    parent_item = Item(path=tmp_path, display="~/tmp", size=1010, is_dir=True)
    children = list_children(parent_item)
    assert children[0].path == large


def test_list_children_not_dir(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("hello")
    item = Item(path=f, display="~/file.txt", size=5, is_dir=False)
    assert list_children(item) == []


def test_list_children_nonexistent(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    item = Item(path=missing, display="~/nope", size=0, is_dir=True)
    assert list_children(item) == []
