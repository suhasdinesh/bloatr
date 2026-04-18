"""Tests for bloatr.sizes — parse_size and format_size."""

import pytest

from bloatr.sizes import format_size, parse_size


class TestParseSize:
    def test_megabytes(self) -> None:
        assert parse_size("500M") == 500 * 1024**2

    def test_gigabytes_fractional(self) -> None:
        assert parse_size("1.5G") == int(1.5 * 1024**3)

    def test_bare_bytes(self) -> None:
        assert parse_size("100") == 100

    def test_terabytes(self) -> None:
        assert parse_size("2T") == 2 * 1024**4

    def test_kilobytes(self) -> None:
        assert parse_size("10K") == 10 * 1024

    def test_lowercase_suffix(self) -> None:
        assert parse_size("5m") == 5 * 1024**2

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_size("")

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_size("abc")

    def test_suffix_only_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_size("G")

    def test_unknown_suffix_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_size("10X")


class TestFormatSize:
    def test_zero(self) -> None:
        assert format_size(0) == "0 B"

    def test_exactly_one_kb(self) -> None:
        assert format_size(1024) == "1.0 KB"

    def test_one_and_half_kb(self) -> None:
        assert format_size(1536) == "1.5 KB"

    def test_exactly_one_gb(self) -> None:
        assert format_size(1024**3) == "1.0 GB"

    def test_large_value(self) -> None:
        # 2.5 TB
        result = format_size(int(2.5 * 1024**4))
        assert result == "2.5 TB"

    def test_megabytes(self) -> None:
        result = format_size(10 * 1024**2)
        assert result == "10.0 MB"

    def test_small_bytes(self) -> None:
        assert format_size(512) == "512 B"

    def test_one_byte(self) -> None:
        assert format_size(1) == "1 B"
