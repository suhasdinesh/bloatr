"""Known macOS developer bloat locations for bloatr."""

from __future__ import annotations

import subprocess
from pathlib import Path

KNOWN_PATHS: tuple[str, ...] = (
    "~/Library/Developer/Xcode/DerivedData",
    "~/Library/Developer/Xcode/Archives",
    "~/Library/Developer/CoreSimulator/Runtimes",
    "~/Library/Caches",
    "~/Library/Developer/Xcode/iOS DeviceSupport",
    "~/.gradle/caches",
    "~/.npm",
    "~/.yarn/cache",
    "~/.pnpm-store",
    "~/.cocoapods/repos",
    "~/.cargo/registry",
    "~/.cargo/git",
    "~/.pub-cache",
    "~/go/pkg/mod",
    "~/.expo",
    "~/Library/Android/sdk",
    "~/Library/Application Support/JetBrains",
)


def _brew_cache() -> Path | None:
    """Return the Homebrew cache directory, or None if brew is unavailable.

    Runs ``brew --cache`` with a 5-second timeout.  Any exception (including
    FileNotFoundError when brew is not installed, TimeoutExpired, or a
    non-zero exit code) results in None being returned.

    Returns:
        Path to the brew cache directory, or None.
    """
    try:
        result = subprocess.run(
            ["brew", "--cache"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            cache_path = result.stdout.strip()
            if cache_path:
                return Path(cache_path)
        return None
    except Exception:
        return None


def get_locations() -> list[Path]:
    """Return the full list of developer bloat paths to scan.

    Expands all entries in ``KNOWN_PATHS`` and appends the Homebrew cache
    directory if ``brew`` is available.

    Returns:
        List of absolute ``Path`` objects (paths may or may not exist on disk).
    """
    locations: list[Path] = [Path(p).expanduser() for p in KNOWN_PATHS]

    brew = _brew_cache()
    if brew is not None:
        locations.append(brew)

    return locations
