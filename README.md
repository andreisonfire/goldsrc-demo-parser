# GoldSrc Demo Parser (GSDP)

Extract multikill highlights from Counter-Strike 1.6 demo files (`.dem`).
Runs entirely on your computer — no Python installation, no internet required,
no data ever leaves your machine.

**Made by THUNDERGOD** · [v1.3](#version-history)

---

## Table of Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [How to use](#how-to-use)
- [CSV output format](#csv-output-format)
- [Highlight selection rules](#highlight-selection-rules)
- [Server time vs demo time](#server-time-vs-demo-time)
- [HLTV vs POV detection](#hltv-vs-pov-detection)
- [Building from source](#building-from-source)
- [How it works (technical)](#how-it-works-technical)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Version history](#version-history)
- [License](#license)

---

## What it does

Give it a CS 1.6 `.dem` file — get back a list of the interesting moments
(multikills, aces, clutch AWP doubles) with timestamps that **match what
the in-game demo player shows**, so you can jump straight to them for
movie making, clip compilation, or just reviewing.

- Parses both **POV** (recorded by a player) and **HLTV** (spectator proxy) demos
- Detects round boundaries from in-game signals (`#CTs_Win`, bomb explosions,
  match restarts) — not just heuristics
- Extracts player names, weapons, headshot flags, and exact timestamps
- Filters out noise: self-kills, suicides, and world damage don't count
- Exports to CSV ready to open in Excel / Google Sheets

## Quick start

1. Download the latest release zip (see **Releases** tab).
2. Unzip anywhere.
3. Double-click `run_ui.bat`.
4. A browser tab opens at `http://localhost:8765` — drop your `.dem` files there.
5. Hit **Download CSV**.

No Python, no dependencies, no setup.

## How to use

### Web UI (recommended)

Double-click `run_ui.bat`. A browser opens with a drag-and-drop zone.

- **Drop one or more `.dem` files** onto the area (or click to pick them).
- Each demo is processed locally (may take 2–10 seconds for a 20 MB file).
- Results show up in a table grouped by highlight.
- Click **Download CSV** when done.
- Click **Clear** to reset and start over.

> `run_ui.bat` is just a convenience wrapper around `cs16_ui.exe` — you can
> launch the `.exe` directly if you prefer. The batch file opens a small
> console window alongside the browser; the `.exe` does the same.

> **Windows Firewall prompt** on first run is normal — the tool opens a local
> web server for the browser UI. No external connections are made. Choose
> "Allow access on private network" and you won't see it again.

### Drag-and-drop batch files (alternative)

For command-line users, two standalone `.bat` files do single-demo processing
with `.txt` output:

- **`run_round_multikills.bat`** — drag a `.dem` onto it. Outputs a `.txt`
  file next to the demo with all 4+ kill streaks found in single rounds.
- **`run_all_kills.bat`** — drag a `.dem` onto it. Outputs a `.txt` with
  every kill in the match in chronological order (entire killfeed).

## CSV output format

Five columns, one row per highlight:

| Column        | Example                                                          |
|---------------|------------------------------------------------------------------|
| `demo_name`   | `demo1.dem`                                                      |
| `map`         | `de_dust2`                                                       |
| `player_name` | `NBD\|sVIKEN- svalket savle navle`                               |
| `highlight`   | Multi-line killfeed for the streak                               |
| `info`        | `fast 3hs with ak47` · `ace with m4a1, usp` · `double with awp`  |

The `highlight` column contains all kills in the streak, one per line.
Headshot lines are wrapped in `*** ***` for easy scanning:

```
*** 19:54: NBD|sVIKEN killed DarkIT Azid with a headshot from ak47 ***
*** 19:56: NBD|sVIKEN killed DarkIT zRK with a headshot from ak47 ***
*** 19:59: NBD|sVIKEN killed DarkIT ENOkSEN with a headshot from ak47 ***
```

Timestamps are in **server time** — they match the counter shown by the
in-game demo player, so you can scrub straight to them.

## Highlight selection rules

The parser exports "meaningful" multikills with descriptive labels. Each
player's kills in a single round are grouped into a bucket, and the bucket
is classified by these rules (in priority order):

| Bucket | Condition | Label |
|--------|-----------|-------|
| 5 kills | Any weapons | `ace with <weapons>` |
| 4 kills | Any weapons | `4k with <weapons>` |
| 3 kills | All AWP **OR** all scout within 1s | `triple with awp` / `triple with scout` |
| 3 kills | All headshots, within 5s, all from {Deagle, AK, M4A1} | `fast 3hs with <weapons>` |
| 3 kills | 2 of them are AWP/scout one-shot (Δ ≤ 1s) + 1 outlier | `double with awp/scout` *(only the 2 close kills are shown)* |
| 2 kills | Both AWP **OR** both scout within 1s | `double with awp` / `double with scout` |

### Subset annotations (for 4k / ace)

When a quad or ace contains a notable sub-event, it's annotated with
`(incl. ...)`:

| Sub-event | Annotation |
|-----------|------------|
| 3 AWP/scout in ≤1s inside the bucket | `(incl. triple with awp)` |
| 2 AWP/scout in ≤1s inside the bucket | `(incl. double with awp)` |
| Two separate doubles in the bucket | `(incl. 2x double with awp)` |
| 3 HS combo (deagle/ak/m4a1 in 5s) inside | `(incl. fast 3hs)` |

Multiple annotations can co-exist (in an ace, you can have triple+double or
double+fast 3hs):

```
ace with awp (incl. triple with awp, double with awp)
ace with awp, deagle, ak, m4a1 (incl. double with awp, fast 3hs)
4k with awp (incl. 2x double with awp)
```

### Deliberately filtered out

- Self-kills (fall damage, own grenade, suicide) — `killer == victim`
- World damage with no attacker
- **Team-kills** — a kill where killer and victim are on the same side at
  that moment. Side is determined from each player's character model
  (which updates at side switches), so a quad + 1 TK reads correctly as
  `4k`, not `ace`. If model data is missing for either party, the kill is
  kept (conservative default — no false TK drops).
- "Slow 3K" with AWP (3 AWP across the round with no Δ ≤ 1s pair) — not
  interesting since AWP is slow and 3 kills over a long round isn't visually
  impressive
- Regular 2-kill clusters that aren't AWP/scout one-shot

If you want different rules, edit the `select_highlights()` and
`_classify_bucket()` functions in `cs16_killfeed.py` — rules are explicitly
declared and easy to change.

## Server time vs demo time

GoldSrc `.dem` files contain **two different clocks**:

- **Demo time** — starts at 0:00 when the recording began
- **Server time** — the server's uptime at the moment of each packet

The in-game demo player displays **server time** (e.g. `29:55.75`), not
demo time. This means a kill that happens at position `1739.6 seconds`
in the demo file is actually shown at `29:55.77` in the player.

This tool automatically corrects for the offset by sampling `SVC_TIME`
packets throughout the demo and applying a **rolling median** to reject
outliers (the byte `0x07` appears naturally in packet payloads, not just
as SVC_TIME markers, so a naive parser would pick up garbage).

The result: timestamps in CSV are accurate to **±0.05 seconds** vs. the
in-game player.

## HLTV vs POV detection

The tool automatically classifies demos as `POV` or `HLTV`:

- **HLTV demos** contain the string `HLTV` in the server info, plus
  recurring `SVC_HLTV` (id=50) messages from the relay proxy
- **POV demos** don't

Detection is heuristic with strict thresholds to avoid random byte collisions.
Accuracy should be near 100% on normal demos.

## Building from source

Requirements: Python 3.10 or newer on Windows, with **"Add Python to PATH"**
checked during install.

```bat
build_exe.bat
```

The script:
1. Installs PyInstaller via pip
2. Builds `cs16_killfeed.exe` (CLI) and `cs16_ui.exe` (web UI)
3. Collects everything into a `release/` folder ready to zip and distribute

No external Python dependencies — only the standard library is used.

## How it works (technical)

The parser is **pure Python with zero dependencies**, about 900 lines.

### Container format

GoldSrc `.dem` files are a custom binary format with:
- 544-byte header (magic `HLDEMO\0\0`, protocol version, map name, mod name)
- A directory table pointing to one or two sections (LOADING + Playback)
- Each section is a stream of frames, each with a 9-byte prefix (type + time + frame number)

Frame types include `NetMsg` (0 or 1), `ConsoleCommand` (3), `ClientData` (4),
`Event` (6), etc. We mostly care about `NetMsg` payloads, which contain the
actual gameplay network messages.

### Finding kills

Kill events come as `DeathMsg` user messages inside the NetMsg stream.
User messages have dynamic IDs assigned at runtime via `SVC_NEWUSERMSG`,
so we first scan for that registration to learn the numeric ID, then
scan all payloads for matching messages.

Each `DeathMsg` decodes to `(killer_slot, victim_slot, headshot_flag, weapon_string)`.

### Finding player names

`SVC_UPDATEUSERINFO` (id 13) messages carry the userinfo string for each
player slot, in the format `\name\Player1\team\CT\model\gign\...`. We
scan for `\name\` patterns inside these messages.

### Finding round boundaries

Round ends are announced via `TextMsg` and `SendAudio` user messages with
well-known localization keys: `#CTs_Win`, `#Terrorists_Win`, `#Round_Draw`,
`#Target_Bombed`, `#Bomb_Defused`, `#Target_Saved`, plus their `%!MRAD_*`
audio-file equivalents, and `#Game_will_restart_in` for pro-scene LIVE restarts.

### Server time correction

See [Server time vs demo time](#server-time-vs-demo-time) above.

### HLTV detection

See [HLTV vs POV detection](#hltv-vs-pov-detection) above.

## Known limitations

- **GoldSrc engine only** — CS 1.6, Counter-Strike: Condition Zero, Half-Life 1.
  Source engine demos (CS:S, CS:GO, CS2) use a completely different format.
- **No Mac/Linux builds** — Windows only for the `.exe`. The Python source
  runs fine on any OS; you'd just need to rebuild with PyInstaller on the
  target platform.
- **Antivirus false positives** — PyInstaller-packed `.exe` files are sometimes
  flagged by Windows Defender and others. No malware is actually present; this
  is a known issue with the packaging method used by many Python tools.
- **Hard-coded rules** — the highlight selection criteria are embedded in code.
  Future versions may expose them as UI options.
- **Single-threaded** — processes demos one at a time. A 5-minute matchday
  batch of 10 demos takes ~1 minute total.

## Troubleshooting

**"DeathMsg user message registration not found"**
The demo is probably a partial HLTV chunk recorded after the initial server
handshake. This happens with HLTV archive clips that don't include the full
session. Full-match demos should always parse fine.

**"Not a GoldSrc demo file (bad magic)"**
The file isn't a valid `.dem`, or it's from a different engine (e.g., CS:GO).

**Console window stays open after closing the browser**
Yes, known UX issue — the local web server keeps running. Close the console
window manually (the `X` in its corner) or press `Ctrl+C` inside it.

**Timestamps don't match the in-game player**
If they're off by more than a second, please open an issue with the demo
file attached (if sharing is OK) or at least the first 10 MB of it.

## Version history

### v1.3

**Bug fixes**
- **Modded server DeathMsg payload support** — servers running ReHLDS /
  ReGameDLL with certain AMX plugins append extra bytes (kill_id, flags,
  etc.) after the weapon name in the DeathMsg payload. The strict
  validation in v1.2 rejected these payloads entirely, causing zero
  highlights on affected demos. Now the trailing bytes are ignored —
  matching how ColDemoPlayer treats the same payloads. All modded-server
  demos should now parse correctly alongside vanilla demos.

**Formatting**
- Headshot markers `***` moved from BEFORE the timestamp to AFTER, so
  timestamps align vertically across all lines regardless of HS status.
  Matches the ColDemoPlayer output style.
  - Before: `*** 48:23: X killed Y with a headshot from usp ***`
  - After:  `48:23: *** X killed Y with a headshot from usp ***`

### v1.2

**New highlight categories and naming**
- Scout added to one-shot multikill rules — `double with scout` and
  `triple with scout` are now detected just like the AWP equivalents
- Renamed labels for clarity:
  - `double with awp` / `triple with awp` (was `2k with awp` / `3k with awp`)
  - `fast 3hs with deagle, ak47, m4a1` (was `3k with deagle, ak47, m4a1`)
- Subset annotations on quads and aces — when a 4k or ace contains a
  notable sub-event, it's tagged inline:
  - `4k with awp, deagle (incl. triple with awp)`
  - `ace with awp (incl. 2x double with awp)`
  - `ace with awp, deagle, ak, m4a1 (incl. double with awp, fast 3hs)`
- Slow 3K AWP removed as a separate category — 3 AWP across a round
  with no sub-1-second pair was rarely visually impressive

**Bug fixes**
- 2 AWP kills in the same millisecond + 1 extra AWP kill later in the same
  round is now correctly classified as `double with awp` (only the 2 close
  kills are shown). Previously it fell through every rule and the event was
  lost entirely.
- Player names are now resolved **at the time of each kill**, not from the
  last name seen in the demo. Esports players who rename to `gg` / `kk` /
  `bb` after the match no longer corrupt earlier kill attribution.
- Team-kills are now excluded from highlight counting. A player who killed
  4 enemies + 1 teammate in a single round is correctly reported as `4k`
  rather than `ace`. Side detection uses the player's character model from
  userinfo (CT models: urban, sas, gign, gsg9, spetsnaz; T models: terror,
  leet, guerilla, arctic, militia) — this updates reliably at half-time
  side switches, so kills are attributed to the right side throughout the
  demo. If model data is missing for either party, the kill is kept
  conservatively (no false TK drops).

**UI/UX**
- Headshot kill lines wrapped in `*** ***` again — restored after movie-maker
  feedback that the visual marker speeds up scanning the highlights output
- Per-demo progress is now visible while parsing a batch: each demo line
  starts as orange italic `… processing` while it's being parsed, then
  flips in-place to green `ok` (or red `ERROR`) when done. The top status
  shows `Processing 3/20: filename…` so you always know which demo is
  currently being worked on and how many remain. Final message reads
  `Done! 12 highlights from 20 demos.`

**CLI**
- New `--highlights` flag uses the exact same selection logic as the web UI.
  The `run_round_multikills.bat` drag-and-drop launcher now uses this flag,
  so its `.txt` output stays in sync with what the UI shows.

**HLTV vs POV**
- The warm-up filter now applies only to HLTV demos. POV recordings are
  always intentional (a player chose to record their game), and the cost of
  filtering them is high — if a player started recording mid-first-half
  and got an ace before the side switch, the warm-up filter could mistake
  the side-switch restart for the match start and drop the ace.

### v1.1

**POV mode**
- Auto-detect POV vs HLTV demos using ConsoleCommand frames (100% accurate
  on a test set of 9 demos — POV demos contain the recording client's
  keypresses, HLTV demos don't)
- For POV demos, identify the recording player and filter highlights to
  show only their own multikills
- Recovery for HLTV demos with corrupt directory tables (common artifact
  of crashed HLTV proxies — the demo data is intact, only the index is
  broken)

**Highlight quality**
- Filter out warm-up multikills: only count highlights after the first
  match restart followed by 15+ clean rounds (the standard CS 1.6 first
  half). Overtime rounds are still included.
- Skip self-kills (`killer == victim`) — falling damage and own-grenade
  kills no longer count toward streaks

**UI improvements**
- New Export dropdown with two formats:
  - **CSV** — same template as v1.0 minus `start_time` and `demo_type`
  - **TXT** — plain-text format with demo name above each streak
- Mark interesting highlights as favorites (⭐ click toggle), then export
  only the favorites with the "favorites only" checkbox
- Time always shown as `MM:SS` (or `MMM:SS` for very long matches),
  matching the in-game demo player exactly
- Headshots no longer wrapped in `***` for cleaner copy-paste
- Version visible in browser tab title and page header
- "Clear" button now also resets the status text

**Cleanup**
- Removed `start_time` and `demo_type` columns from CSV (info is in the
  page or implied by the data)
- Removed "X total kills" from per-demo log line — only highlight count
  is relevant

### v1.0 (first release)

- Full CS 1.6 / GoldSrc `.dem` parser in pure Python
- POV and HLTV demo support with auto-detection
- Round boundary detection via in-game win signals
- Server time correction with median-based outlier rejection
- Highlight selection rules: 4+/5 kills, 3-HS combos, AWP one-shot multi-kills
- Web UI with drag-and-drop and CSV export
- Standalone `.exe` distribution via PyInstaller

## License

MIT License — see [LICENSE](LICENSE).

Free to use, modify, redistribute. No warranty.
