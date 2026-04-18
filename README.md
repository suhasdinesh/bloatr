# bloatr

> Kill your Mac's bloat. Select. Delete. Done.

A dead-simple macOS CLI that finds your biggest developer cache directories, lets you browse them, and deletes what you don't need — with a clean terminal UI.

```
  SIZE        LOCATION
  24.3 GB ▶   ~/Library/Developer/Xcode/DerivedData
  11.2 GB     ~/Library/Caches
   4.1 GB     ~/Library/Android/sdk
   3.1 GB     ~/.expo
   1.9 GB     ~/.gradle/caches
   515 MB      ~/.npm

  space:select  enter:explore  esc:back  d:delete  q:quit
```

---

## Install

```bash
pipx install bloatr
```

Or with pip:

```bash
pip install bloatr
```

---

## Usage

```bash
# Launch interactive TUI (scans known developer bloat locations)
bloatr

# Scan any directory — like `du` but interactive
bloatr ~/
bloatr ~/Documents
bloatr ~/Library/Caches

# Preview what would be deleted (safe mode)
bloatr --dry-run

# Only show items > 1 GB
bloatr --min-size 1G

# JSON output (pipe-friendly)
bloatr --json
bloatr --json ~/Library | jq '.[].size_human'
```

---

## What it scans

| Location | What it is |
|---|---|
| `~/Library/Developer/Xcode/DerivedData` | Xcode build artifacts |
| `~/Library/Developer/Xcode/Archives` | Xcode app archives |
| `~/Library/Developer/CoreSimulator/Runtimes` | iOS/watchOS simulator runtimes |
| `~/Library/Developer/Xcode/iOS DeviceSupport` | Per-device debug symbols |
| `~/Library/Caches` | App caches |
| `~/.gradle/caches` | Gradle build cache |
| `~/.npm` | npm package cache |
| `~/.yarn/cache` | Yarn package cache |
| `~/.pnpm-store` | pnpm content-addressable store |
| `~/.cocoapods/repos` | CocoaPods spec repos |
| `~/.cargo/registry` | Rust crate registry |
| `~/.cargo/git` | Rust git dependencies |
| `~/.pub-cache` | Flutter/Dart package cache |
| `~/go/pkg/mod` | Go module cache |
| `~/.expo` | Expo/React Native cache |
| `~/Library/Android/sdk` | Android SDK |
| `~/Library/Application Support/JetBrains` | JetBrains IDE caches |
| Homebrew cache | `brew --cache` output |

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `space` | Toggle select |
| `enter` | Drill into folder |
| `esc` / `backspace` | Go back |
| `d` | Delete selected items |
| `r` | Rescan from scratch |
| `q` | Quit |

---

## Safety

bloatr will **never** delete:
- Anything outside your home directory (`~`)
- Top-level protected directories (`~/Library`, `~/Documents`, `~/Desktop`, etc.)
- The home directory itself

Every deletion requires an explicit confirmation prompt. Use `--dry-run` to preview without touching anything.

---

## Credits

Idea and direction by a human who lost 100 GB to Mac bloat one too many times. Code written entirely by [Claude Code](https://claude.ai/code).

---

## License

MIT
