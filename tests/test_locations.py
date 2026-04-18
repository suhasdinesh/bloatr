"""Tests for bloatr.locations — get_locations and KNOWN_PATHS."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bloatr.locations import KNOWN_PATHS, _brew_cache, get_locations


class TestGetLocations:
    def test_returns_non_empty_list(self) -> None:
        locations = get_locations()
        assert len(locations) > 0

    def test_all_paths_are_path_objects(self) -> None:
        for loc in get_locations():
            assert isinstance(loc, Path), f"Expected Path, got {type(loc)}: {loc}"

    def test_all_paths_are_absolute(self) -> None:
        for loc in get_locations():
            assert loc.is_absolute(), f"Path is not absolute: {loc}"

    def test_no_tilde_in_paths(self) -> None:
        for loc in get_locations():
            assert "~" not in str(loc), f"Tilde not expanded in: {loc}"

    def test_all_paths_under_home(self) -> None:
        home = Path.home()
        for loc in get_locations():
            try:
                loc.relative_to(home)
            except ValueError:
                pytest.fail(f"Path is not under home directory: {loc}")

    def test_includes_brew_cache_when_available(self) -> None:
        fake_brew_path = Path.home() / "Library" / "Caches" / "Homebrew"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = str(fake_brew_path) + "\n"

        with patch("bloatr.locations.subprocess.run", return_value=mock_result):
            locations = get_locations()

        assert fake_brew_path in locations, (
            f"Brew cache {fake_brew_path} not found in locations: {locations}"
        )

    def test_brew_file_not_found_does_not_crash(self) -> None:
        with patch(
            "bloatr.locations.subprocess.run",
            side_effect=FileNotFoundError("brew not found"),
        ):
            locations = get_locations()

        # Should still return all hardcoded paths
        assert len(locations) == len(KNOWN_PATHS)

    def test_brew_timeout_does_not_crash(self) -> None:
        import subprocess

        with patch(
            "bloatr.locations.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="brew", timeout=5),
        ):
            locations = get_locations()

        assert len(locations) == len(KNOWN_PATHS)

    def test_known_paths_count(self) -> None:
        # Ensure no accidental deletions from KNOWN_PATHS
        assert len(KNOWN_PATHS) == 17


class TestKnownPaths:
    def test_all_start_with_tilde(self) -> None:
        for p in KNOWN_PATHS:
            assert p.startswith("~"), f"Path does not start with ~: {p}"

    def test_contains_xcode_derived_data(self) -> None:
        assert "~/Library/Developer/Xcode/DerivedData" in KNOWN_PATHS

    def test_contains_npm(self) -> None:
        assert "~/.npm" in KNOWN_PATHS

    def test_contains_cargo_registry(self) -> None:
        assert "~/.cargo/registry" in KNOWN_PATHS


class TestBrewCache:
    def test_returns_none_on_exception(self) -> None:
        with patch(
            "bloatr.locations.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _brew_cache()
        assert result is None

    def test_returns_path_on_success(self) -> None:
        fake_path = "/Users/test/Library/Caches/Homebrew"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_path + "\n"

        with patch("bloatr.locations.subprocess.run", return_value=mock_result):
            result = _brew_cache()

        assert result == Path(fake_path)

    def test_returns_none_on_nonzero_exit(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("bloatr.locations.subprocess.run", return_value=mock_result):
            result = _brew_cache()

        assert result is None
