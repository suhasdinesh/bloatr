"""Size parsing and formatting utilities for bloatr."""

_SUFFIXES: dict[str, int] = {
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
}

_FORMAT_UNITS: list[tuple[str, float]] = [
    ("TB", 1024.0**4),
    ("GB", 1024.0**3),
    ("MB", 1024.0**2),
    ("KB", 1024.0),
    ("B", 1.0),
]


def parse_size(s: str) -> int:
    """Parse a human-readable size string into bytes.

    Supports suffixes K, M, G, T (case-insensitive) and bare integers.
    Examples: "500M", "1.5G", "100", "2T", "10K".

    Args:
        s: Size string to parse.

    Returns:
        Size in bytes as an integer.

    Raises:
        ValueError: If the string is empty, has an unknown suffix, or is
            otherwise malformed.
    """
    if not s:
        raise ValueError("Empty size string")

    upper = s.strip().upper()

    if upper[-1] in _SUFFIXES:
        multiplier = _SUFFIXES[upper[-1]]
        numeric_part = upper[:-1]
    else:
        multiplier = 1
        numeric_part = upper

    if not numeric_part:
        raise ValueError(f"No numeric component in size string: {s!r}")

    try:
        value = float(numeric_part)
    except ValueError:
        raise ValueError(f"Invalid size string: {s!r}")

    return int(value * multiplier)


def format_size(n: int) -> str:
    """Format a byte count as a human-readable string.

    Returns values like "0 B", "1.5 KB", "24.3 GB".  Values below 1 KB are
    shown without a decimal place; everything else uses one decimal place.

    Args:
        n: Number of bytes (non-negative integer).

    Returns:
        Human-readable size string.
    """
    if n == 0:
        return "0 B"

    for unit, threshold in _FORMAT_UNITS:
        if n >= threshold:
            value = n / threshold
            if unit == "B":
                return f"{n} B"
            return f"{value:.1f} {unit}"

    return f"{n} B"
