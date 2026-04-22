# GoldSrc Demo Parser

Extract multikill highlights from Counter-Strike 1.6 demo files (`.dem`).  
Works offline, no Python required, no data leaves your machine.

**Made by THUNDERGOD** · v1.0

---

## Features

- Parses both POV and HLTV demos of CS 1.6 (GoldSrc engine)
- Automatic HLTV/POV detection
- Server-time correction — timestamps match the in-game demo player
- Smart highlight selection rules:
  - All **4+ and 5-kill streaks** per round (quads and aces)
  - 3 headshots within 5 seconds using Deagle, AK-47, or M4A1
  - Triple kill from AWP in a single second (one-shot triple)
  - Double kill from AWP in a single second (one-shot double)
- CSV export with columns: `demo_name`, `map`, `player_name`, `highlight`, `info`
- Two modes: a local web UI, and drag-and-drop batch files for power users

## Installation

Download the latest release, unzip, double-click `cs16_ui.exe`.  
A browser tab opens at `http://localhost:8765` — drop your demos there.

No Python installation needed.

## Build from source

Requires Python 3.10+ installed with "Add Python to PATH" checked.

```bat
build_exe.bat
```

This creates a `release/` folder with standalone `.exe` files you can share.

## How it works

Under the hood this is a pure-Python parser for the GoldSrc `.dem` container
format. No external libraries — just `struct.unpack` on binary bytes.

Key pieces:
- Container walker — reads the demo header, directory table, and frame stream
- User message extractor — finds `DeathMsg` registrations and decodes kills
- Round boundary detector — scans for `#CTs_Win`, `#Terrorists_Win`,
  `#Target_Bombed`, `#Game_will_restart_in` and other match signals
- Server-time correction — samples `SVC_TIME` packets across the demo and
  uses a rolling median to reject outliers (0x07 bytes appear naturally
  in packet payloads, not just as SVC_TIME)

## Known limitations

- Only GoldSrc engine demos (CS 1.6, not CSGO/CS2)
- Highlight selection rules are hard-coded; if you want different rules,
  edit `select_highlights()` in `cs16_killfeed.py`
- Antivirus software sometimes flags PyInstaller `.exe` files as suspicious
  (false positive, standard issue)

## License

MIT License — see [LICENSE](LICENSE)
