# bloatr v2 Roadmap — On-Device AI Summaries

**Theme:** Bring on-device intelligence to disk cleanup decisions using Apple's FoundationModels framework (macOS 26+, Apple Silicon). Every AI feature is strictly opt-in and degrades gracefully to v1 behaviour when unavailable.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Feature Specs](#2-feature-specs)
3. [Graceful Degradation](#3-graceful-degradation)
4. [Python↔Swift Bridge Protocol](#4-pythonswift-bridge-protocol)
5. [Build & Packaging](#5-build--packaging)
6. [Timeline Estimate](#6-timeline-estimate)

---

## 1. Architecture Overview

### Why a Swift companion binary?

Python has no direct binding to `FoundationModels`. The framework is a native Swift/ObjC API that ships with macOS 26 and runs exclusively on Apple Silicon. The cleanest integration path for a Python CLI is a thin Swift binary (`bloatr-helper`) that:

- receives a JSON request on `stdin`
- runs the model session synchronously (blocking until done)
- writes a JSON response to `stdout`
- exits with code `0` on success, non-zero on error

Python calls it via `subprocess.run`, parses the response, and renders results in the Textual TUI. No XPC, no sockets, no long-lived daemon — keep it simple.

```
bloatr (Python/Textual)
    │
    │  stdin: JSON request
    ▼
bloatr-helper (Swift binary)
    │  FoundationModels.LanguageModelSession
    │
    │  stdout: JSON response
    ▼
bloatr (Python/Textual)  →  render in TUI
```

### Swift skeleton — `bloatr-helper`

```swift
// Sources/bloatr-helper/main.swift
import Foundation
import FoundationModels

// 1. Check model availability before doing anything else
let model = SystemLanguageModel.default
guard case .available = model.availability else {
    let err = ["error": "model_unavailable", "detail": "\(model.availability)"]
    print(String(data: try! JSONEncoder().encode(err), encoding: .utf8)!)
    exit(1)
}

// 2. Read JSON request from stdin
let inputData = FileHandle.standardInput.readDataToEndOfFile()
guard let request = try? JSONDecoder().decode(BloatrRequest.self, from: inputData) else {
    fputs("bloatr-helper: invalid JSON request\n", stderr)
    exit(2)
}

// 3. Dispatch to the right handler
let response: BloatrResponse
do {
    response = try await dispatch(request: request)
} catch {
    response = BloatrResponse(action: request.action, error: error.localizedDescription)
}

// 4. Write JSON response to stdout
let outputData = try! JSONEncoder().encode(response)
FileHandle.standardOutput.write(outputData)
```

```swift
// Sources/bloatr-helper/Models.swift
import Foundation
import FoundationModels

struct BloatrRequest: Codable {
    let action: String          // "summarize" | "risk" | "ask" | "group" | "explain"
    let payload: [String: String]
}

struct BloatrResponse: Codable {
    let action: String
    var summary: String?
    var riskLevel: String?      // "low" | "caution" | "verify"
    var riskReason: String?
    var matches: [String]?
    var groups: [String: [String]]?
    var explanation: String?
    var error: String?
}
```

```swift
// Sources/bloatr-helper/Dispatch.swift
import FoundationModels

func dispatch(request: BloatrRequest) async throws -> BloatrResponse {
    switch request.action {
    case "summarize": return try await handleSummarize(request)
    case "risk":      return try await handleRisk(request)
    case "ask":       return try await handleAsk(request)
    case "group":     return try await handleGroup(request)
    case "explain":   return try await handleExplain(request)
    default:
        return BloatrResponse(action: request.action, error: "unknown_action")
    }
}
```

### Python availability detection

```python
# bloatr/ai_bridge.py
import shutil
import subprocess
import platform
import json
from pathlib import Path

HELPER_NAME = "bloatr-helper"

def _macos_version() -> tuple[int, int]:
    ver = platform.mac_ver()[0]          # e.g. "26.0.0"
    parts = ver.split(".")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0

def ai_available() -> bool:
    """True only on macOS 26+, Apple Silicon, with the helper binary present."""
    major, _ = _macos_version()
    if major < 26:
        return False
    helper = _find_helper()
    return helper is not None

def _find_helper() -> Path | None:
    # 1. Prefer binary sitting next to the installed wheel's scripts
    candidate = Path(__file__).parent / "bin" / HELPER_NAME
    if candidate.exists():
        return candidate
    # 2. Fall back to PATH (useful for dev installs)
    found = shutil.which(HELPER_NAME)
    return Path(found) if found else None

def call_helper(action: str, payload: dict) -> dict:
    """
    Call bloatr-helper with a JSON request and return the parsed response.
    Raises RuntimeError if the helper is unavailable or returns a non-zero exit code.
    """
    helper = _find_helper()
    if helper is None:
        raise RuntimeError("bloatr-helper not found")

    request = json.dumps({"action": action, "payload": payload})
    result = subprocess.run(
        [str(helper)],
        input=request,
        capture_output=True,
        text=True,
        timeout=30,          # on-device inference is fast; 30s is generous
    )

    if result.returncode != 0:
        raise RuntimeError(f"bloatr-helper exited {result.returncode}: {result.stderr.strip()}")

    return json.loads(result.stdout)
```

---

## 2. Feature Specs

Features are listed in ship priority order (highest value, lowest risk first).

---

### 2.1 "What is this folder?" pre-delete summary

**Goal:** Before a user confirms deletion, show a 1–2 sentence plain-English explanation of what the folder is, so they can make an informed decision.

**Trigger:** User selects a folder in the TUI and presses `Enter` (confirm) or `i` (inspect).

**Python side — data collection:**

```python
# bloatr/inspector.py
import json
from pathlib import Path
from datetime import datetime

MAX_README_CHARS = 1500   # stay well under the 4096-token context budget

def collect_folder_hints(path: Path) -> dict:
    hints = {
        "path": str(path),
        "size_mb": round(_dir_size(path) / 1_048_576, 1),
        "last_modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
    }
    for candidate in ["README.md", "README.txt", "readme.md"]:
        readme = path / candidate
        if readme.exists():
            hints["readme_excerpt"] = readme.read_text(errors="replace")[:MAX_README_CHARS]
            break
    for manifest in ["package.json", "Cargo.toml", "pyproject.toml", "go.mod"]:
        mf = path / manifest
        if mf.exists():
            hints["manifest"] = mf.read_text(errors="replace")[:800]
            hints["manifest_name"] = manifest
            break
    return hints
```

**Swift handler:**

```swift
// Sources/bloatr-helper/Handlers/Summarize.swift
import FoundationModels

@Generable(description: "A short summary of a developer folder")
struct FolderSummary {
    @Guide(description: "One to two sentence plain-English explanation of what this folder is and what it was used for.")
    var summary: String

    @Guide(description: "Whether the folder appears to be actively used or abandoned. One word: active, idle, or abandoned.")
    var status: String
}

func handleSummarize(_ request: BloatrRequest) async throws -> BloatrResponse {
    let session = LanguageModelSession(instructions: """
        You are a macOS disk-cleanup assistant. Given metadata about a developer \
        project folder, explain in 1–2 plain sentences what it is and whether it \
        looks actively used. Be factual; do not speculate beyond the evidence. \
        Never output more than two sentences.
        """)

    let prompt = buildSummarizePrompt(request.payload)
    let response = try await session.respond(to: prompt, generating: FolderSummary.self)

    var result = BloatrResponse(action: "summarize")
    result.summary = "\(response.content.summary) (status: \(response.content.status))"
    return result
}

private func buildSummarizePrompt(_ p: [String: String]) -> String {
    var parts = ["Folder: \(p["path"] ?? "unknown")"]
    if let size  = p["size_mb"]       { parts.append("Size: \(size) MB") }
    if let mtime = p["last_modified"] { parts.append("Last modified: \(mtime)") }
    if let mf    = p["manifest_name"] { parts.append("Contains \(mf):") }
    if let mfc   = p["manifest"]      { parts.append(mfc) }
    if let readme = p["readme_excerpt"]{ parts.append("README excerpt:\n\(readme)") }
    return parts.joined(separator: "\n")
}
```

**TUI integration:** Display the summary in a modal overlay before the delete confirmation dialog. Cache results in a `dict[str, str]` keyed by `str(path)` for the session lifetime — never re-call for the same path twice.

---

### 2.2 Smart risk flagging

**Goal:** Tag each listed item with a risk badge (`low` / `caution` / `verify`) shown inline in the file list widget.

**Risk semantics:**

| Tag | Meaning |
|-----|---------|
| `low` | Safe to delete — clear build artifact, cache, or temp file |
| `caution` | Probably fine but worth a glance (e.g. node_modules in a repo with recent commits) |
| `verify` | Do not delete without checking — could be source, config, or a symlink target |

**Python side:** Call `call_helper("risk", hints)` in a background `asyncio.Task` when the list is first populated. Update each row's tag as responses arrive. Rows without a response yet show no badge (v1 default appearance).

**Swift handler:**

```swift
// Sources/bloatr-helper/Handlers/Risk.swift
import FoundationModels

@Generable(description: "Risk assessment for deleting a developer folder")
struct RiskAssessment {
    @Guide(description: "Risk level: exactly one of: low, caution, verify")
    var level: String

    @Guide(description: "One short sentence explaining the risk rating.")
    var reason: String
}

func handleRisk(_ request: BloatrRequest) async throws -> BloatrResponse {
    let session = LanguageModelSession(instructions: """
        You are a macOS disk-cleanup safety checker. Rate the risk of permanently \
        deleting the described folder. Use exactly one of: low, caution, verify. \
        Base your rating only on the metadata provided.
        """)

    let prompt = buildSummarizePrompt(request.payload)  // reuse same builder
    let response = try await session.respond(to: prompt, generating: RiskAssessment.self)

    var result = BloatrResponse(action: "risk")
    result.riskLevel  = response.content.level
    result.riskReason = response.content.reason
    return result
}
```

**TUI rendering:** Add a `RichText` badge column to the existing `DataTable`. Colors: green (`low`), yellow (`caution`), red (`verify`).

---

### 2.3 Natural language query — `bloatr ask "..."`

**Goal:** Let users filter/query the candidate list using plain English instead of flags.

```
$ bloatr ask "stale node_modules older than 6 months"
$ bloatr ask "Xcode DerivedData for projects I haven't touched in a year"
$ bloatr ask "anything in ~/.gradle larger than 500 MB"
```

**Architecture:** This feature translates a natural language query into a structured filter spec, which Python then evaluates against the pre-scanned candidate list.

```swift
// Sources/bloatr-helper/Handlers/Ask.swift
import FoundationModels

@Generable(description: "A structured filter derived from a natural language cleanup query")
struct QueryFilter {
    @Guide(description: "Folder name patterns to include, e.g. ['node_modules', '.gradle']")
    var namePatterns: [String]

    @Guide(description: "Maximum last-modified age in days. 0 means no constraint.")
    var maxAgeDays: Int

    @Guide(description: "Minimum size in MB. 0 means no constraint.")
    var minSizeMB: Int

    @Guide(description: "Optional base directory prefix to restrict search, e.g. ~/Library/Developer")
    var pathPrefix: String
}

func handleAsk(_ request: BloatrRequest) async throws -> BloatrResponse {
    let session = LanguageModelSession(instructions: """
        You translate macOS disk-cleanup queries into structured JSON filters. \
        Extract folder name patterns, age constraints, size constraints, and \
        optional path prefixes. Use 0 for unconstrained numeric fields.
        """)

    let query = request.payload["query"] ?? ""
    let response = try await session.respond(
        to: "Query: \(query)",
        generating: QueryFilter.self
    )

    let f = response.content
    var result = BloatrResponse(action: "ask")
    // Encode the filter back as a flat payload Python can parse
    result.matches = f.namePatterns
    result.explanation = "age<=\(f.maxAgeDays)d size>=\(f.minSizeMB)MB prefix=\(f.pathPrefix)"
    return result
}
```

**Python side:**

```python
# bloatr/query.py
def apply_query_filter(candidates: list[Path], filter_response: dict) -> list[Path]:
    name_patterns = filter_response.get("matches", [])
    explanation   = filter_response.get("explanation", "")
    max_age_days, min_size_mb, path_prefix = _parse_explanation(explanation)

    now = time.time()
    results = []
    for p in candidates:
        if name_patterns and not any(pat in p.name for pat in name_patterns):
            continue
        if path_prefix and not str(p).startswith(path_prefix):
            continue
        stat = p.stat()
        age_days = (now - stat.st_mtime) / 86400
        size_mb  = _dir_size(p) / 1_048_576
        if max_age_days and age_days < max_age_days:
            continue
        if min_size_mb and size_mb < min_size_mb:
            continue
        results.append(p)
    return results
```

---

### 2.4 DerivedData project grouping

**Goal:** Instead of listing 40 opaque UUID-named DerivedData folders, group them by inferred project name and show one collapsible row per project.

**Input:** The path `~/Library/Developer/Xcode/DerivedData/<Name>-<UUID>/` — the `<Name>` segment is usually the Xcode project/workspace name, but sometimes it's mangled. The model normalises edge cases.

**Swift handler:**

```swift
// Sources/bloatr-helper/Handlers/Group.swift
import FoundationModels

@Generable(description: "Inferred project name for a DerivedData folder")
struct ProjectName {
    @Guide(description: "Clean project name inferred from the folder name, e.g. 'MyApp' not 'MyApp-abcdef123456'")
    var name: String
}

func handleGroup(_ request: BloatrRequest) async throws -> BloatrResponse {
    // batch: payload["folders"] is a newline-separated list
    let folders = (request.payload["folders"] ?? "").split(separator: "\n").map(String.init)

    var groups: [String: [String]] = [:]
    for folder in folders {
        let session = LanguageModelSession(instructions:
            "Extract the clean Xcode project name from a DerivedData folder name. " +
            "Remove UUID suffixes. Return only the project name.")
        let resp = try await session.respond(to: folder, generating: ProjectName.self)
        let key  = resp.content.name
        groups[key, default: []].append(folder)
    }

    var result = BloatrResponse(action: "group")
    result.groups = groups
    return result
}
```

**Note:** Create a new `LanguageModelSession` per folder (single-turn). Do not reuse sessions across unrelated inputs — each inference is independent and the context window is small.

**TUI integration:** Replace the flat DerivedData list with a `Tree` widget. Each project node shows the sum of child sizes. Expanding reveals individual build folders with their own risk badges.

---

### 2.5 On-demand "explain this cache" — `?` key

**Goal:** User presses `?` on any selected row to get a full explanation of what the cache is and why it exists, streamed into a sidebar panel.

**This feature uses streaming** so text appears progressively rather than after a multi-second wait.

```swift
// Sources/bloatr-helper/Handlers/Explain.swift
import FoundationModels

// Non-streaming path (helper uses stdout; streaming happens inside Swift,
// Python sees the final result after the process exits)
func handleExplain(_ request: BloatrRequest) async throws -> BloatrResponse {
    let session = LanguageModelSession(instructions: """
        You are a macOS developer tools expert. Explain what the described cache \
        or build artifact directory is, why it exists, what creates it, and \
        whether it is safe to delete. Be concise — 3 to 5 sentences maximum.
        """)

    let path    = request.payload["path"] ?? "unknown"
    let name    = request.payload["name"] ?? Path(path).lastComponent
    let sizeMB  = request.payload["size_mb"] ?? "unknown"

    let prompt  = "Path: \(path)\nFolder name: \(name)\nSize: \(sizeMB) MB"
    let response = try await session.respond(to: prompt)

    var result = BloatrResponse(action: "explain")
    result.explanation = response.content
    return result
}
```

**Python TUI:** Open a `RichLog` widget in a right-side panel. Since the helper process is synchronous (stdout written on exit), display a spinner while waiting, then render the explanation with Markdown formatting once received. For a streaming feel in a future v2.1, `bloatr-helper` could flush newline-delimited partial responses — but for v2.0, single-shot is sufficient.

---

## 3. Graceful Degradation

All AI features are hidden behind a single gate. If the gate is `False`, the tool behaves exactly as v1 with zero visible difference.

```python
# bloatr/ai_bridge.py  (continued)

_AI_ENABLED: bool | None = None   # cached after first check

def ai_enabled() -> bool:
    global _AI_ENABLED
    if _AI_ENABLED is None:
        _AI_ENABLED = ai_available()
    return _AI_ENABLED
```

**Usage pattern throughout the codebase:**

```python
from bloatr.ai_bridge import ai_enabled, call_helper

# In any feature module:
if ai_enabled():
    try:
        resp = call_helper("summarize", hints)
        summary = resp.get("summary")
    except Exception:
        summary = None    # silently degrade; never crash
else:
    summary = None
```

**Degradation matrix:**

| Condition | Result |
|-----------|--------|
| macOS < 26 | `ai_enabled()` returns `False`; no binary call attempted |
| macOS 26+, Intel Mac | `ai_enabled()` returns `False` (FoundationModels requires Apple Silicon) |
| macOS 26+, Apple Silicon, helper missing | `ai_enabled()` returns `False` |
| macOS 26+, Apple Silicon, Apple Intelligence disabled in Settings | helper exits non-zero; exception caught; summary is `None` |
| Helper times out (>30 s) | `subprocess.TimeoutExpired` caught; feature skipped |
| Model returns unexpected JSON | `KeyError`/`json.JSONDecodeError` caught; feature skipped |

The TUI must never show an error panel or stack trace due to AI unavailability. Missing AI data simply means "no badge", "no summary panel", "no grouping".

---

## 4. Python↔Swift Bridge Protocol

All communication uses newline-terminated JSON over stdin/stdout. One request per process invocation.

### Request schema

```json
{
  "action": "<string>",
  "payload": {
    "<key>": "<string>"
  }
}
```

`payload` values are always strings (numbers serialised as strings). This keeps the Swift `Codable` struct trivial and avoids type-mismatch edge cases.

### Response schema

```json
{
  "action": "<string>",
  "summary":     "<string | null>",
  "riskLevel":   "low | caution | verify | null",
  "riskReason":  "<string | null>",
  "matches":     ["<string>", ...],
  "groups":      { "<project>": ["<folder>", ...] },
  "explanation": "<string | null>",
  "error":       "<string | null>"
}
```

Fields not relevant to the action are omitted (not `null`) to keep payloads small.

### Per-action payload reference

| Action | Required payload keys | Optional payload keys |
|--------|-----------------------|-----------------------|
| `summarize` | `path` | `size_mb`, `last_modified`, `manifest_name`, `manifest`, `readme_excerpt` |
| `risk` | `path` | `size_mb`, `last_modified`, `manifest_name`, `manifest` |
| `ask` | `query` | — |
| `group` | `folders` (newline-separated list) | — |
| `explain` | `path`, `name` | `size_mb` |

### Error response

On any failure the helper returns:

```json
{
  "action": "<requested action>",
  "error": "human-readable description"
}
```

Exit code is non-zero when the model is unavailable at the OS level; exit code `0` with `"error"` set for application-level errors (e.g. bad prompt, inference failure).

### Size limits

Keep total prompt data under **3,000 characters** per call to leave headroom within the 4,096-token context window (instructions + prompt + response). Truncate README excerpts and manifest content accordingly (see `MAX_README_CHARS = 1500` in §2.1).

---

## 5. Build & Packaging

### Swift package structure

```
bloatr-helper/
├── Package.swift
└── Sources/
    └── bloatr-helper/
        ├── main.swift
        ├── Models.swift
        ├── Dispatch.swift
        └── Handlers/
            ├── Summarize.swift
            ├── Risk.swift
            ├── Ask.swift
            ├── Group.swift
            └── Explain.swift
```

```swift
// bloatr-helper/Package.swift
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "bloatr-helper",
    platforms: [.macOS(.v26)],
    targets: [
        .executableTarget(
            name: "bloatr-helper",
            path: "Sources/bloatr-helper",
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency")
            ]
        )
    ]
)
```

Build the release binary:

```bash
swift build -c release --arch arm64
# output: .build/arm64-apple-macosx/release/bloatr-helper
```

### Bundling with the Python wheel

The binary lives at `src/bloatr/bin/bloatr-helper`. Python's `_find_helper()` checks this path first (see §1).

```toml
# pyproject.toml  (excerpt)
[tool.hatch.build.targets.wheel]
packages = ["src/bloatr"]

[tool.hatch.build.targets.wheel.shared-data]
# bloatr/bin/ is a Python package sub-directory, not shared-data —
# include it via the packages glob above.
```

Because `pyproject.toml` wheels include everything under `src/bloatr/`, the binary at `src/bloatr/bin/bloatr-helper` is automatically included as long as it is committed to the repo (or copied there during the build step).

**Post-build hook** — add to `Makefile` or CI:

```makefile
.PHONY: build-helper
build-helper:
	cd bloatr-helper && swift build -c release --arch arm64
	cp bloatr-helper/.build/arm64-apple-macosx/release/bloatr-helper \
	   src/bloatr/bin/bloatr-helper
	chmod +x src/bloatr/bin/bloatr-helper

.PHONY: build
build: build-helper
	python -m build
```

**Executable bit preservation:** `hatch` and `pip` honour the executable bit in wheels (stored in the zip metadata). Verify with `python -m zipfile -l dist/*.whl | grep bloatr-helper` — the mode should show `0755`.

### Non-Apple-Silicon installs

On Intel Macs or Linux, `ai_enabled()` returns `False` before any binary call is made, so the missing/non-runnable binary is a non-issue. The wheel is still installable everywhere — the binary just sits unused.

If you later want universal binaries:

```bash
swift build -c release --arch arm64
swift build -c release --arch x86_64
lipo -create \
  .build/arm64-apple-macosx/release/bloatr-helper \
  .build/x86_64-apple-macosx/release/bloatr-helper \
  -output src/bloatr/bin/bloatr-helper
```

### Gitignore note

Add `.build/` to `.gitignore`. Commit only `src/bloatr/bin/bloatr-helper` (the compiled output). CI rebuilds it from source on every release tag.

---

## 6. Timeline Estimate

Assumes a solo developer with familiarity with both Python/Textual and basic Swift, spending roughly 15–20 hrs/week.

| Week | Deliverable |
|------|-------------|
| **1** | Swift package scaffold, JSON bridge plumbing, `ai_available()` detection, `call_helper()` wrapper with timeout and error handling. Manual end-to-end test with a hardcoded prompt. |
| **2** | Feature 2.1 — folder summary. Swift `Summarize.swift`, Python `inspector.py` hint collector, TUI modal overlay. Ship behind `--ai` flag for dogfooding. |
| **3** | Feature 2.2 — risk flagging. `Risk.swift`, badge column in `DataTable`, background asyncio task, session-level result cache. |
| **4** | Feature 2.5 — `?` explain panel. `Explain.swift`, `RichLog` sidebar widget, spinner while waiting. Good UX payoff for low Swift complexity. |
| **5** | Feature 2.3 — `bloatr ask`. `Ask.swift`, `QueryFilter` generable, Python `apply_query_filter()`. CLI entry point (`bloatr ask "<query>"`). |
| **6** | Feature 2.4 — DerivedData grouping. `Group.swift`, `Tree` widget in TUI, aggregate size display. Most complex TUI work. |
| **7** | Hardening: edge-case prompts, token-budget guard (truncation), timeout tuning, full degradation test matrix (Intel, macOS 25, AI disabled). |
| **8** | Build automation (`make build-helper`), wheel packaging verification, `CHANGELOG`, v2.0.0 release tag. |

**Total: ~8 weeks to a shippable v2.0.**

Buffer advice: weeks 5–6 tend to slip if the Textual widget work is underestimated. If pressed for time, ship features 2.1–2.2 and 2.5 as v2.0, and defer 2.3–2.4 to v2.1.

---

## Appendix — File Layout After v2

```
bloatr/
├── bloatr-helper/          # Swift package (source)
│   ├── Package.swift
│   └── Sources/bloatr-helper/
│       ├── main.swift
│       ├── Models.swift
│       ├── Dispatch.swift
│       └── Handlers/
├── src/bloatr/
│   ├── bin/
│   │   └── bloatr-helper   # compiled ARM64 binary (committed)
│   ├── ai_bridge.py        # availability check + subprocess wrapper
│   ├── inspector.py        # hint collection (README, manifests, mtimes)
│   ├── query.py            # NL query filter application
│   └── ...                 # existing v1 modules unchanged
├── docs/
│   └── v2-roadmap.md       # this document
├── Makefile
└── pyproject.toml
```
