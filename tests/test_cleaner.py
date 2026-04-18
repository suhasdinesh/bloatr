"""Tests for bloatr.cleaner — is_safe_path and delete/delete_many."""

from pathlib import Path

import pytest

from bloatr.cleaner import (
    MIN_DEPTH,
    UnsafePathError,
    delete,
    delete_many,
    delete_with_progress,
    is_safe_path,
)
from bloatr.models import Item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(path: Path, *, is_dir: bool | None = None) -> Item:
    """Build an Item for *path*, optionally overriding is_dir detection."""
    item = Item.from_path(path)
    if is_dir is not None and item.is_dir != is_dir:
        # Use object.__setattr__ to mutate the frozen dataclass in tests only.
        object.__setattr__(item, "is_dir", is_dir)
    return item


# ---------------------------------------------------------------------------
# is_safe_path
# ---------------------------------------------------------------------------

class TestIsSafePath:
    def test_deep_home_path_is_safe(self) -> None:
        home = Path.home()
        assert is_safe_path(home / "a" / "b" / "c") is True

    def test_two_levels_deep_is_safe(self) -> None:
        home = Path.home()
        # depth 2 is fine (MIN_DEPTH is 1)
        assert is_safe_path(home / "a" / "b") is True

    def test_outside_home_is_not_safe(self) -> None:
        assert is_safe_path(Path("/tmp/x")) is False

    def test_home_itself_is_not_safe(self) -> None:
        assert is_safe_path(Path.home()) is False

    def test_blocklisted_top_level_dir_is_not_safe(self) -> None:
        home = Path.home()
        # ~/Library itself is blocklisted — too dangerous to delete outright
        assert is_safe_path(home / "Library") is False

    def test_non_blocklisted_one_level_deep_is_safe(self) -> None:
        home = Path.home()
        # ~/.npm is 1 level deep and not blocklisted — should be safe
        assert is_safe_path(home / ".npm") is True

    def test_symlink_outside_home_is_not_safe(self, tmp_path: Path) -> None:
        """A symlink that resolves outside home must be rejected."""
        link = tmp_path / "evil_link"
        try:
            link.symlink_to("/tmp")
            # /tmp is outside the home directory — should be rejected.
            assert is_safe_path(link) is False
        except (OSError, NotImplementedError):
            pytest.skip("Cannot create symlink in this environment")

    def test_min_depth_constant(self) -> None:
        assert MIN_DEPTH == 1


# ---------------------------------------------------------------------------
# delete — dry_run
# ---------------------------------------------------------------------------

class TestDeleteDryRun:
    def test_dry_run_does_not_remove_directory(self, tmp_path: Path) -> None:
        # Build a safe path: home / a / b / target
        home = Path.home()
        safe_dir = home / ".bloatr_test_tmp" / "a" / "b"
        safe_dir.mkdir(parents=True, exist_ok=True)
        try:
            item = Item.from_path(safe_dir)
            delete(item, dry_run=True)
            assert safe_dir.exists(), "dry_run must not remove the directory"
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)

    def test_dry_run_does_not_remove_file(self, tmp_path: Path) -> None:
        home = Path.home()
        safe_parent = home / ".bloatr_test_tmp" / "a" / "b"
        safe_parent.mkdir(parents=True, exist_ok=True)
        safe_file = safe_parent / "test_file.txt"
        safe_file.write_text("hello")
        try:
            item = Item.from_path(safe_file)
            delete(item, dry_run=True)
            assert safe_file.exists(), "dry_run must not remove the file"
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)


# ---------------------------------------------------------------------------
# delete — actual removal
# ---------------------------------------------------------------------------

class TestDeleteActual:
    def test_delete_removes_directory(self) -> None:
        home = Path.home()
        safe_dir = home / ".bloatr_test_tmp" / "a" / "b"
        safe_dir.mkdir(parents=True, exist_ok=True)
        try:
            item = Item.from_path(safe_dir)
            delete(item, dry_run=False)
            assert not safe_dir.exists(), "delete must remove the directory"
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)

    def test_delete_removes_file(self) -> None:
        home = Path.home()
        safe_parent = home / ".bloatr_test_tmp" / "a" / "b"
        safe_parent.mkdir(parents=True, exist_ok=True)
        safe_file = safe_parent / "test_file.txt"
        safe_file.write_text("hello")
        try:
            item = Item.from_path(safe_file)
            delete(item, dry_run=False)
            assert not safe_file.exists(), "delete must remove the file"
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)

    def test_delete_raises_for_unsafe_path(self) -> None:
        unsafe_path = Path("/tmp/unsafe_bloatr_test")
        item = Item(
            path=unsafe_path,
            display="/tmp/unsafe_bloatr_test",
            size=0,
            is_dir=False,
        )
        with pytest.raises(UnsafePathError):
            delete(item)


# ---------------------------------------------------------------------------
# delete_many
# ---------------------------------------------------------------------------

class TestDeleteMany:
    def test_delete_many_returns_results_for_each_item(self) -> None:
        home = Path.home()
        base = home / ".bloatr_test_tmp"

        dir_a = base / "a" / "b" / "c"
        dir_b = base / "a" / "b" / "d"
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)

        try:
            items = [Item.from_path(dir_a), Item.from_path(dir_b)]
            results = delete_many(items, dry_run=False)

            assert len(results) == 2
            assert results[0][0] is items[0]
            assert results[1][0] is items[1]
            assert results[0][1] is None
            assert results[1][1] is None
            assert not dir_a.exists()
            assert not dir_b.exists()
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def test_delete_many_captures_errors(self) -> None:
        """An unsafe path should yield an UnsafePathError in results."""
        unsafe_item = Item(
            path=Path("/tmp/bloatr_no_such"),
            display="/tmp/bloatr_no_such",
            size=0,
            is_dir=False,
        )
        results = delete_many([unsafe_item], dry_run=False)
        assert len(results) == 1
        item, error = results[0]
        assert item is unsafe_item
        assert isinstance(error, UnsafePathError)

    def test_delete_many_dry_run_captures_no_errors(self) -> None:
        home = Path.home()
        safe_dir = home / ".bloatr_test_tmp" / "a" / "b"
        safe_dir.mkdir(parents=True, exist_ok=True)
        try:
            items = [Item.from_path(safe_dir)]
            results = delete_many(items, dry_run=True)
            assert results[0][1] is None
            assert safe_dir.exists()
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)


# ---------------------------------------------------------------------------
# delete_with_progress
# ---------------------------------------------------------------------------


class TestDeleteWithProgress:
    def test_progress_callback_fires_per_file(self) -> None:
        home = Path.home()
        base = home / ".bloatr_test_tmp" / "a" / "b"
        base.mkdir(parents=True, exist_ok=True)

        (base / "f1.txt").write_bytes(b"x" * 100)
        (base / "f2.txt").write_bytes(b"x" * 200)
        (base / "f3.txt").write_bytes(b"x" * 50)

        calls: list[tuple[int, str]] = []

        def cb(delta: int, path: str) -> None:
            calls.append((delta, path))

        try:
            item = Item.from_path(base)
            freed, error = delete_with_progress(item, on_progress=cb)
            assert error is None
            assert freed == 350
            assert len(calls) == 3
            assert sum(delta for delta, _ in calls) == 350
            assert not base.exists()
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)

    def test_progress_dry_run_reports_total_once(self) -> None:
        home = Path.home()
        base = home / ".bloatr_test_tmp" / "a" / "b"
        base.mkdir(parents=True, exist_ok=True)
        (base / "f.txt").write_bytes(b"x" * 500)

        calls: list[tuple[int, str]] = []

        def cb(delta: int, path: str) -> None:
            calls.append((delta, path))

        try:
            # Size is passed via Item.size, not computed — simulate by building one.
            item = Item(
                path=base,
                display="~/.bloatr_test_tmp/a/b",
                size=500,
                is_dir=True,
            )
            freed, error = delete_with_progress(item, on_progress=cb, dry_run=True)
            assert error is None
            assert freed == 500
            assert len(calls) == 1
            assert calls[0][0] == 500
            assert base.exists()  # dry-run must not delete
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)

    def test_progress_unsafe_path_raises(self) -> None:
        unsafe = Item(
            path=Path("/tmp/bloatr_unsafe_xyz"),
            display="/tmp/bloatr_unsafe_xyz",
            size=0,
            is_dir=False,
        )
        with pytest.raises(UnsafePathError):
            delete_with_progress(unsafe)

    def test_progress_nested_tree(self) -> None:
        home = Path.home()
        base = home / ".bloatr_test_tmp" / "nest" / "deep"
        (base / "level1" / "level2").mkdir(parents=True, exist_ok=True)
        (base / "level1" / "level2" / "deep.txt").write_bytes(b"x" * 1000)
        (base / "level1" / "top.txt").write_bytes(b"x" * 500)
        (base / "root.txt").write_bytes(b"x" * 250)

        try:
            item = Item.from_path(base)
            freed, error = delete_with_progress(item)
            assert error is None
            assert freed == 1750
            assert not base.exists()
        finally:
            import shutil
            shutil.rmtree(home / ".bloatr_test_tmp", ignore_errors=True)
