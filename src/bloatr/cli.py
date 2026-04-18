"""CLI entry point for bloatr."""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from bloatr import __version__
from bloatr.app import run_tui
from bloatr.locations import get_locations
from bloatr.models import Item
from bloatr.scanner import list_children, scan_locations
from bloatr.sizes import format_size, parse_size


def main() -> None:
    """Parse CLI flags, run the scanner, then launch TUI or JSON output."""
    parser = argparse.ArgumentParser(
        prog="bloatr",
        description="Kill your Mac's bloat. Select. Delete. Done.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  bloatr                      # launch interactive TUI (built-in locations)
  bloatr ~/                   # scan home directory children
  bloatr ~/Documents          # scan a specific folder's children
  bloatr --dry-run            # TUI, but don't actually delete anything
  bloatr --min-size 1G        # only show items larger than 1 GB
  bloatr --json               # print JSON to stdout (no TUI)
  bloatr --json | jq '.[].size_human'
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--min-size",
        default=None,
        metavar="SIZE",
        help="Only show items larger than SIZE (e.g. 500M, 1G, 2T)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output scan results as JSON and exit (non-interactive)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"bloatr {__version__}",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        metavar="PATH",
        help="Scan this directory's children instead of the built-in developer locations (e.g. ~/ or ~/Documents)",
    )
    args = parser.parse_args()

    # Validate --min-size
    min_size = 0
    if args.min_size:
        try:
            min_size = parse_size(args.min_size)
        except ValueError as exc:
            print(f"bloatr: invalid --min-size value: {exc}", file=sys.stderr)
            sys.exit(1)

    # Scan — either a user-supplied path or the built-in developer locations.
    scan_root: Path | None = None

    if args.path:
        scan_root = Path(args.path).expanduser().resolve()
        if not scan_root.exists():
            print(f"bloatr: path does not exist: {scan_root}", file=sys.stderr)
            sys.exit(1)
        if not scan_root.is_dir():
            print(f"bloatr: not a directory: {scan_root}", file=sys.stderr)
            sys.exit(1)
        if not args.json_output:
            print(f"bloatr: scanning {scan_root}…", file=sys.stderr)
        root_item = Item.from_path(scan_root)
        items = list_children(root_item)
    else:
        locations = get_locations()
        if not args.json_output:
            print("bloatr: scanning…", file=sys.stderr)
        items = scan_locations(locations)

    # Filter by min-size
    if min_size > 0:
        items = [i for i in items if i.size >= min_size]

    # JSON mode — print and exit
    if args.json_output:
        data = [
            {
                "path": str(item.path),
                "display": item.display,
                "size": item.size,
                "size_human": format_size(item.size),
                "is_dir": item.is_dir,
                "error": item.error,
            }
            for item in items
        ]
        print(json.dumps(data, indent=2))
        return

    # Interactive TUI
    run_tui(items, dry_run=args.dry_run, scan_root=scan_root)


if __name__ == "__main__":
    main()
