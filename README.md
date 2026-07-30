# GoldSrc Demo Parser (GSDP)

Extract multikill highlights from Counter-Strike 1.6 demo files (`.dem`).
Runs entirely on your computer — no Python installation, no internet required,
no data ever leaves your machine.

**Made by THUNDERGOD** · [v2.0](#version-history)

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
3. Double-click `gsdp.exe` (or `run_ui.bat`).
4. A native app window opens — drop your `.dem` files onto the drop zone.
5. Hit **Export** and pick CSV or TXT.

No Python, no dependencies, no setup. Works on Windows 10 / 11 out of the
box — the app uses the system's built-in WebView2 runtime.

## How to use

### Desktop app (recommended)

Double-click `gsdp.exe`. A native app window opens with a drag-and-drop zone.

- **Drop one or more `.dem` files** onto the area (or click to pick them).
- Each demo is processed locally (may take 2–10 seconds for a 20 MB file).
- Results show up in a table grouped by highlight.
- Star the rows you want to keep, then hit **Export** and pick CSV or TXT.
  Tick **favourites only** to export just the starred rows.
- After saving, your file manager opens with the exported file selected.
- Click **Clear** to reset and start over.

> `run_ui.bat` is a wrapper around `gsdp.exe`. Either works.

> Everything runs locally on your machine. No internet connection, no
> firewall prompts, no data leaves the app.

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
2. Builds `cs16_killfeed.exe` (CLI) and `gsdp.exe` (desktop app)
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
- **Non-competitive stretches inside a live demo are not detected.** Technical
  pauses, or one team standing at spawn while the other shoots them, look
  structurally identical to real gameplay: rounds start and end normally,
  victims are unique, teams and models are consistent. On
  `mtw-vs-no-dsrack3-playoffs` this produces about four highlights nobody wants.
  Warm-up *before* the match is filtered, but a pause can begin at any point.
- **Team detection can misplace a barely-active player in a very short demo.**
  Teams come from the kill graph, which anchors each player through both the
  kills they made and the deaths they took. A player who frags almost never
  during the match but team-kills repeatedly in a warm-up can be pulled to the
  wrong side, because the flip only costs less than his few real kills and
  deaths. Measured threshold: this needs team-kills to outnumber his deaths
  plus kills, which cannot happen across a full match (a player dies ~25 times
  in 30 rounds) but is reachable in a 3-5 round fragment. Across the 68-demo
  test corpus no player was actually misplaced. Fix planned: score each
  player's placement confidence and fall back to the model field for the
  weakly-anchored ones.

## Troubleshooting

**"DeathMsg user message registration not found"**
The demo is probably a partial HLTV chunk recorded after the initial server
handshake. This happens with HLTV archive clips that don't include the full
session. Full-match demos should always parse fine.

**"Not a GoldSrc demo file (bad magic)"**
The file isn't a valid `.dem`, or it's from a different engine (e.g., CS:GO).

**Timestamps don't match the in-game player**
If they're off by more than a second, please open an issue with the demo
file attached (if sharing is OK) or at least the first 10 MB of it.

## Version history

### v2.0

**Round-bucketing fixes**

Three separate defects made kills land in the wrong round. Each was found by
running the parser against a 68-demo corpus and comparing against ColDemoPlayer.

- **Boundaries are now sorted before `bisect`.** `bisect` silently returns
  nonsense indices on an unsorted list, which collapsed kills from several
  rounds into one bucket. On `375_166_602952` a single round-end that had been
  handed a corrupt timestamp broke the ordering and produced buckets of 11, 9
  and 6 kills — all three were then swallowed by the `>5` safety net, so the
  demo reported 2 highlights instead of 5. The 3 lost ones included a genuine
  6.9-second m4a1 ace.
- **A frag landing just after the round-end message stays in its own round**
  (`ROUND_EDGE_EPS`, 6 seconds). The round-winning DeathMsg and the
  `#CTs_Win` / `#Bomb_Defused` message race each other in the stream, and when
  the kill lost it was bucketed into the next round. This also covers frags
  that are legitimately post-round: defusing and then killing the last
  terrorist, or the clock expiring and the T killing the last CT.
- **Round-event debounce no longer depends on arrival order.** Hits are
  collected, sorted, then collapsed. A demo can open with a signon preamble
  whose frames carry the server's uptime instead of a recording offset; a
  round-end inside that preamble used to poison the debounce state and reject
  every later event. On `basi3.dem` that discarded 26 of 28 round ends, left 4
  boundaries for a 34-minute match, and lost a real m4a1 ace.

`collect_svc_time_samples()` now sorts its output by frame time, which
`apply_server_time_to_events()` bisects on. The rolling-median window for
server-time correction widened from 21 to 101 samples so that a contiguous run
of garbage samples can no longer outvote its neighbours.

Net effect across 68 demos: 6 changed, 62 byte-for-byte identical. Of the 6,
three recovered real highlights, one removed a false 4k that was two rounds
glued together, one corrected a false ace down to the 4k it actually was, and
one shifted a single timestamp by a second.

**Team detection from the kill graph**

Team-kills have to be excluded before highlights are counted — 4 enemies plus
a teammate is a quad, not an ace. The only team signal CS 1.6 userinfo offers
is the `model` field, and it goes stale: some servers never resend a player's
model after a side switch, and a single stale player breaks the filter in both
directions at once.

On `mtw-vs-no-dsrack3-playoffs` slot 9 kept the model it was assigned at 01:30
until 63:39, so for the entire second half the filter read him as CT while his
team played T. That deleted 44 of his legitimate kills as "team-kills", costing
five real highlights including three aces, while simultaneously passing three
actual team-kills through as a "fast 3hs with ak" highlight.

Teams are now inferred from who killed whom. In a real match essentially every
kill crosses team lines, so the correct split is the one leaving the fewest
kills inside a team. With ten players that's 512 possible splits, so an exact
brute force is cheaper than any heuristic. Teams also stay fixed for the whole
demo while sides swap at half time, so this needs no time tracking — removing
the entire class of stale-userinfo bugs.

Measured over a 68-demo corpus: the best split leaves a median of 1.8% of kills
inside teams and never more than 18.9%, and it matched clan-tag groupings on all
16 demos where tags were legible, with no contradictions. Six recovered
highlights were confirmed by hand against the game. The model field is still
used as a fallback whenever the graph can't produce a confident split — too
many players to brute force, too few kills to constrain the answer, or no split
clean enough.

**Non-gameplay stretches inside a live demo**

Warm-up before the match was already filtered, but a demo also contains
non-gameplay stretches in the MIDDLE and at the END, and those look
structurally identical to real rounds — rounds start and end normally, victims
are unique, teams and models stay consistent. The usual shape is one team
standing at spawn while the other farms frags, which reads as a run of aces.
On H2k_vs_Lions_DHW09 that was 14 of 22 highlights; on
mtw-vs-no-dsrack3-playoffs, 5 of 8.

They can't be told apart from the frags themselves, but CS 1.6 match rules pin
down where real play sits, so `find_live_intervals()` reconstructs the match
structure instead:

- Each half opens with a pistol round, since $800 only buys pistols. Halves are
  located by those pistol rounds rather than by `mp_restartround` bursts —
  restart detection isn't dependable, and on mtw-vs-no the half-time restart
  never reaches the stream at all, which merged both halves into one 22-round
  period and lost four live overtime highlights. The pistol rounds are plainly
  visible there (rounds 1 and 16).
- The first half is always exactly 15 rounds. A pistol round that has another
  one within 15 rounds is a false start that got replayed.
- Regulation ends when a team reaches 16, so the second half runs 1 to 15
  rounds; its length comes from the score, which is why `find_round_events()`
  now reports the winning side of every round.
- At 15:15 it goes to overtime — up to 3 rounds per half, opening on $10000, so
  overtime halves have no pistol round and are found via restart bursts.

When the structure isn't a standard match the function returns None and nothing
is filtered: fewer than two pistol rounds (one side wasn't recorded), too few
rounds, or no locatable second half. Demos cut mid-half are rare and losing a
real highlight is worse than letting some junk through.

A round's pistol share is measured between the previous boundary of ANY kind,
restarts included, and the round's own end. Rounds cut short by a restart burst
never produce a win message, so keying only on wins stretches the window across
them and their kills dilute the share — that hid the second-half pistol round on
2433409_2433410, where a "LIVE, LIVE, LIVE" burst sits right before it.

Note that round numbering here counts only WON rounds, so it won't line up with
a demo viewer's. ColDemoPlayer numbers every round that started: on
H2k_vs_Lions_DHW09 it lists 64 rounds against 41 wins, the other 23 having been
cut short by restarts and replayed. Since a replayed round doesn't score, a half
is always exactly 15 won rounds either way, which is what the 15-round rule
relies on.

Verified against the game by hand, demo by demo: of the highlights this removes
across the corpus, 23 were confirmed junk and 7 were live — all 7 traced to bugs
in the rules above, which were then fixed. Scores reconstructed from the win
messages match the viewer exactly (H2k_vs_Lions 12:3 at half time then 15:15;
zenn 11:4 then 16:7; 2433409 9:6 then 16:14).

One known gap remains: a tournament that plays out all 30 rounds instead of
stopping at 16 loses the highlights after the 16th round — seen once, on
47_52_1100865.

Pairing the two halves is safe because a demo only ever holds one map — a map
change stops the recording, so a file can't contain two matches whose pistol
rounds might be mismatched. Within one match the second half's pistol round is
always at least 15 won rounds after the first's, so a closer pair is a false
start and nothing else.

**Warm-up filtering on short demos**

`find_match_start()` looked for the first restart followed by 15 clean rounds,
since a CS 1.6 half is exactly 15 rounds. Plenty of demos are a single map or a
cut-down fragment and never contain 15 rounds after any restart — all 15
protocol-47 demos in the test corpus fell short, most with under 6 rounds. The
strict rule returned None for every one of them, which silently disabled warm-up
filtering and let warm-up frags through as highlights.

When nothing reaches a full half, it now falls back to the restart with the
longest clean run of rounds after it — naturally the last of a "LIVE, LIVE,
LIVE" burst. At least two clean rounds are required so stray noise can't
qualify.

**Native desktop app**
- The tool no longer opens a browser tab. Instead, `gsdp.exe` launches
  a native app window powered by [pywebview](https://pywebview.flowrl.com/)
  and the system's WebView2 runtime (present on all Windows 10 / 11
  machines by default). No more `http://localhost:8765`, no more console
  window in the background, no more Firewall prompt on first run.
- File picking and export go through native OS dialogs. Demos are read from
  disk by path rather than shipped through the UI as base64, which keeps
  memory flat on large batches.
- After an export is saved, the file manager opens with the file selected.
- The executable is now named `gsdp.exe` (was `cs16_ui.exe`). `run_ui.bat`
  accepts either name, so existing release folders keep working.
- Every highlight-selection rule is unchanged from v1.3 apart from the
  round-bucketing fixes above.
- `.exe` grew from ~9 MB to ~15–20 MB due to bundled pywebview components.

**Icon**
- Custom app icon replaces the default PyInstaller feather. White tactical
  operator silhouette on black — shows up in Windows Explorer, on the
  taskbar, in Alt+Tab, and in the app window's title bar.

### v1.3

**Formatting**
- Headshot markers `***` moved from BEFORE the timestamp to AFTER, so
  timestamps align vertically across all lines regardless of HS status.
  Matches the ColDemoPlayer output style.
  - Before: `*** 48:23: X killed Y with a headshot from usp ***`
  - After:  `48:23: *** X killed Y with a headshot from usp ***`

**UI/UX**
- Modded-server demos are now flagged with a yellow warning in the log
  instead of silently returning zero highlights. Message: "kill events
  not supported (modded server — ReHLDS/AMX plugins)". Detection works
  by looking for DeathMsg payloads that pass basic sanity checks but
  have extra bytes after the weapon name — the signature of servers
  running ReHLDS / ReGameDLL with kill-tracking AMX plugins.

**Launchers**
- `run_ui.bat`, `run_round_multikills.bat`, and `run_all_kills.bat` now
  try the compiled `.exe` first and fall back to running the `.py`
  through Python if the `.exe` isn't next to them. Same batch file works
  for both release and dev layouts.

**Not changed**
- The parser core is unchanged from v1.2. Modded-server demos are still
  not fully parsed — only detected and warned about. Vanilla server
  demos (all pro CS 1.6 matches and standard PUGs) work as before.

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
