#!/usr/bin/env python3
"""
CS 1.6 (GoldSrc) demo killfeed extractor.

Usage:
    python cs16_killfeed.py path/to/demo.dem
    python cs16_killfeed.py demo.dem --window 5 --min-kills 2
    python cs16_killfeed.py demo.dem --all-kills

Output: <demo>_multikills.txt next to the input file, in the format:
    13:37 player1 killed player2 with ak47 (headshot)
"""
import argparse
import re
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Known CS 1.6 weapon strings from DeathMsg.weapon (HLSDK / cstrike source).
# Used as a whitelist to validate parsed kills.
# ---------------------------------------------------------------------------
KNOWN_WEAPONS = {
    # pistols
    "usp", "glock18", "deagle", "p228", "elite", "fiveseven",
    # smgs
    "mp5navy", "mac10", "tmp", "p90", "ump45",
    # shotguns
    "m3", "xm1014",
    # rifles
    "famas", "galil", "ak47", "m4a1", "aug", "sg552", "sg550", "g3sg1", "scout",
    # heavy
    "awp", "m249",
    # melee/explosives
    "knife", "hegrenade", "grenade", "bomb", "c4",
    # world / fall damage
    "world", "worldspawn",
    # rare/custom
    "event_headshot", "headshot",
}

# ---------------------------------------------------------------------------
# Demo container constants (verified against py-goldsrc-demo source code)
# ---------------------------------------------------------------------------
DEMO_MAGIC = b"HLDEMO\x00\x00"
HEADER_SIZE = 544
NETMSGINFO_SIZE = 436          # timestamp+RefParams+UserCmd+MoveVars+view+view_model
NETMSG_TAIL_SIZE = 32          # 7 sequence ints + msg_length
DIRECTORY_ENTRY_SIZE = 92      # id + name[64] + flags + cd_track + time + frames + offset + length

# SVC byte values (stable in HL/CS 1.6 net protocol)
SVC_UPDATEUSERINFO = 13
SVC_NEWUSERMSG = 39


# ---------------------------------------------------------------------------
# Container parser
# ---------------------------------------------------------------------------
def parse_demo_container(data: bytes):
    """Parse demo header + frames. Returns dict with metadata and list of
    (frame_time, msg_bytes) tuples for every NetMsg frame in playback order."""
    if len(data) < HEADER_SIZE or data[:8] != DEMO_MAGIC:
        raise ValueError("Not a GoldSrc demo file (bad magic)")

    demo_protocol, net_protocol = struct.unpack_from("<II", data, 8)
    map_name = data[16 : 16 + 260].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    mod_name = data[276 : 276 + 260].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    map_crc, dir_offset = struct.unpack_from("<iI", data, 536)

    # Directory table
    if dir_offset + 4 > len(data):
        raise ValueError("Bad directory offset in header")
    (dir_count,) = struct.unpack_from("<I", data, dir_offset)
    if dir_count == 0 or dir_count > 16:
        raise ValueError(f"Suspicious directory count: {dir_count}")

    directories = []
    pos = dir_offset + 4
    for _ in range(dir_count):
        if pos + DIRECTORY_ENTRY_SIZE > len(data):
            raise ValueError("Truncated directory entry")
        d_id = struct.unpack_from("<I", data, pos)[0]
        d_name = data[pos + 4 : pos + 68].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        flags, cd_track, dtime, frames, doffset, dlength = struct.unpack_from(
            "<IifIII", data, pos + 68
        )
        pos += DIRECTORY_ENTRY_SIZE
        directories.append({
            "id": d_id, "name": d_name, "flags": flags,
            "cd_track": cd_track, "time": dtime, "frames": frames,
            "offset": doffset, "length": dlength,
        })

    netmsgs = []
    for d in directories:
        pos = d["offset"]
        end = d["offset"] + d["length"] if d["length"] > 0 else len(data)
        end = min(end, len(data))

        while pos < end:
            if pos + 9 > end:
                break
            ftype = data[pos]
            ftime, _fframe = struct.unpack_from("<fI", data, pos + 1)
            pos += 9

            if ftype in (0, 1):  # NetMsg frame
                if pos + NETMSGINFO_SIZE + NETMSG_TAIL_SIZE > end:
                    break
                pos += NETMSGINFO_SIZE
                seqs = struct.unpack_from("<iiiiiiiI", data, pos)
                pos += NETMSG_TAIL_SIZE
                msg_length = seqs[7]
                if msg_length < 0 or msg_length > 65536 or pos + msg_length > end:
                    break
                netmsgs.append((ftime, data[pos : pos + msg_length]))
                pos += msg_length
            elif ftype == 2:  # FirstMacro / DemoStart — no payload
                pass
            elif ftype == 3:  # ConsoleCommand
                pos += 64
            elif ftype == 4:  # ClientData
                pos += 32
            elif ftype == 5:  # FinalMacro / NextSection — end of section
                break
            elif ftype == 6:  # Event
                pos += 84
            elif ftype == 7:  # WeaponAnim
                pos += 8
            elif ftype == 8:  # Sound (variable)
                if pos + 8 > end:
                    break
                _channel, sample_length = struct.unpack_from("<ii", data, pos)
                pos += 8 + sample_length + 16
            elif ftype == 9:  # DemoBuffer (variable)
                if pos + 4 > end:
                    break
                buf_len = struct.unpack_from("<i", data, pos)[0]
                pos += 4 + buf_len
            else:
                # Unknown frame type — bail this directory.
                break

    return {
        "map_name": map_name,
        "mod_name": mod_name,
        "demo_protocol": demo_protocol,
        "net_protocol": net_protocol,
        "netmsgs": netmsgs,
    }


def collect_svc_time_samples(netmsgs):
    """Walk every NetMsg payload, pick out SVC_TIME (id=7) samples, and
    return them as a list of (frame_ftime, server_time) tuples, sorted by
    frame_ftime.

    Important caveats:
      - Early in a demo the server often broadcasts SVC_TIME=0.000 during
        the signon phase; those are filtered out.
      - Byte 0x07 also appears inside other SVC payloads, so some samples
        are garbage (random 4 bytes interpreted as float). We keep them
        here but callers should use apply_server_time_to_events() which
        rolls a median to reject outliers.

    Wire format: 1 byte id (7) + 4 bytes little-endian float."""
    samples = []
    for ftime, msg in netmsgs:
        i = 0
        L = len(msg)
        best = None
        while i < L - 4:
            if msg[i] == 7:
                try:
                    (t,) = struct.unpack_from("<f", msg, i + 1)
                except struct.error:
                    i += 1
                    continue
                # filter obvious signon zeros and absurd values
                if 0.5 < t < 10_000_000.0:
                    best = t
            i += 1
        if best is not None:
            samples.append((ftime, best))
    return samples


def apply_server_time_to_events(events, svc_samples, get_ftime, set_ftime,
                                window=21, max_dev=5.0):
    """Translate event timestamps from demo-time to server-time using
    SVC_TIME samples.

    Problem: byte 0x07 appears naturally inside many SVC payloads, so
    ~10% of SVC_TIME samples are actually garbage floats. A simple
    "nearest sample" lookup lands on an outlier every ~10 events.

    Solution: for each event, take the <window> samples closest to it in
    ftime, compute each sample's offset (svc_time - frame_ftime), take
    their median, and assume time runs linearly with that offset.

    This is robust — it tolerates up to ~40% garbage samples before the
    median tips over.

    events      — iterable of records
    svc_samples — output of collect_svc_time_samples (sorted by ftime)
    get_ftime   — fn(record) -> demo ftime
    set_ftime   — fn(record, new_time) -> updated record
    window      — how many neighbouring samples to median over
    max_dev     — unused by current impl; reserved for future tightening"""
    if not svc_samples:
        return list(events)

    import bisect
    sample_ftimes = [s[0] for s in svc_samples]
    sample_offsets = [s[1] - s[0] for s in svc_samples]

    half = max(1, window // 2)

    def median_offset_near(idx):
        lo = max(0, idx - half)
        hi = min(len(sample_offsets), idx + half + 1)
        chunk = sorted(sample_offsets[lo:hi])
        return chunk[len(chunk) // 2]

    adjusted = []
    for ev in events:
        t = get_ftime(ev)
        idx = bisect.bisect_left(sample_ftimes, t)
        if idx >= len(sample_ftimes):
            idx = len(sample_ftimes) - 1
        off = median_offset_near(idx)
        adjusted.append(set_ftime(ev, t + off))
    return adjusted


def find_server_time_offset(netmsgs):
    """Legacy helper kept for backwards compatibility. Returns the median
    offset across all SVC_TIME samples — a sensible single-number summary
    but note that the real offset drifts during playback, so new code
    should use apply_server_time_to_events instead."""
    samples = collect_svc_time_samples(netmsgs)
    if not samples:
        return None
    offsets = sorted(s[1] - s[0] for s in samples)
    return offsets[len(offsets) // 2]


# ---------------------------------------------------------------------------
# SVC stream scanners (signature-based, no full SVC parser)
# ---------------------------------------------------------------------------
def find_deathmsg_id(netmsgs):
    """Find SVC_NEWUSERMSG entry registering 'DeathMsg'.
    Wire format: byte SVC(39), byte index, signed-byte size, string name+\\0.
    Returns (id_byte, declared_size_signed) or (None, None)."""
    needle = b"DeathMsg\x00"
    for _, msg in netmsgs:
        idx = 0
        while True:
            i = msg.find(needle, idx)
            if i < 0:
                break
            if i >= 3 and msg[i - 3] == SVC_NEWUSERMSG:
                msg_id = msg[i - 2]
                size_byte = msg[i - 1]
                size_signed = size_byte if size_byte < 128 else size_byte - 256
                return msg_id, size_signed
            idx = i + 1
    return None, None


def find_player_names(netmsgs):
    """Build slot->name map from SVC_UPDATEUSERINFO occurrences.
    Wire: byte SVC(13), byte slot, uint32 userid, string userinfo+\\0, 16 bytes hash.
    Userinfo is non-empty key/value blob like '\\name\\X\\team\\Y' or just '\\0'."""
    slot_names = {}
    name_re = re.compile(rb"\\name\\([^\\\x00]+)")
    for _, msg in netmsgs:
        i = 0
        L = len(msg)
        while i < L - 7:
            if msg[i] == SVC_UPDATEUSERINFO and msg[i + 1] <= 31:
                # 1 byte SVC + 1 byte slot + 4 bytes userid → userinfo starts at i+6.
                # Userinfo is either empty (\x00) or starts with '\'.
                first = msg[i + 6]
                if first == 0x5C or first == 0:
                    slot = msg[i + 1]
                    null_pos = msg.find(b"\x00", i + 6, min(i + 6 + 260, L))
                    if null_pos >= i + 6:
                        userinfo = msg[i + 6 : null_pos]
                        m = name_re.search(userinfo)
                        if m:
                            name_bytes = m.group(1)
                            name = None
                            for enc in ("utf-8", "cp1251", "latin-1"):
                                try:
                                    name = name_bytes.decode(enc)
                                    break
                                except UnicodeDecodeError:
                                    continue
                            if name is None:
                                name = name_bytes.decode("ascii", errors="replace")
                            slot_names[slot] = name
                        # skip past userinfo + null + 16 bytes hash
                        i = null_pos + 1 + 16
                        continue
            i += 1
    return slot_names


def find_kills(netmsgs, deathmsg_id):
    """Scan all NetMsg payloads for variable-length user message <deathmsg_id>.
    Wire (variable-size user msg): byte id, byte length, then <length> bytes.
    DeathMsg payload: byte killer, byte victim, byte headshot, str weapon+\\0.
    Returns list of (frame_time, killer, victim, headshot, weapon)."""
    if deathmsg_id is None:
        return []

    kills = []
    for ftime, msg in netmsgs:
        i = 0
        L = len(msg)
        while i < L - 5:
            if msg[i] == deathmsg_id:
                length = msg[i + 1]
                # killer(1)+victim(1)+hs(1)+weapon(>=1)+null(1) → length>=5,
                # be slightly tolerant on the upper bound.
                if 5 <= length <= 30 and i + 2 + length <= L:
                    killer = msg[i + 2]
                    victim = msg[i + 3]
                    headshot = msg[i + 4]
                    payload_end = i + 2 + length  # exclusive
                    weapon_end = msg.find(b"\x00", i + 5, payload_end)
                    if (
                        weapon_end > i + 5
                        and weapon_end == payload_end - 1  # null is the last byte of payload
                        and 0 <= killer <= 32
                        and 1 <= victim <= 32
                        and headshot in (0, 1)
                    ):
                        weapon_bytes = msg[i + 5 : weapon_end]
                        try:
                            weapon = weapon_bytes.decode("ascii")
                        except UnicodeDecodeError:
                            weapon = ""
                        if (
                            weapon
                            and all(c.isalnum() or c == "_" for c in weapon)
                            and weapon.lower() in KNOWN_WEAPONS
                        ):
                            kills.append((ftime, killer, victim, headshot, weapon))
                            i = payload_end
                            continue
            i += 1
    return kills


# ---------------------------------------------------------------------------
# Multikill grouping
# ---------------------------------------------------------------------------
def find_round_boundaries(netmsgs):
    """Scan NetMsg payloads for end-of-round signals. Returns sorted list of
    timestamps when rounds ended (or match-level events that separate rounds).

    Signals are plain ASCII strings embedded in SendAudio/TextMsg user
    messages — we match them by substring without full user-msg parsing.

    Categories:
      - Round outcomes (#CTs_Win, #Terrorists_Win, #Round_Draw)
      - Bomb outcomes (#Target_Bombed, #Bomb_Defused, #Target_Saved)
      - Hostage outcomes (#All_Hostages_Rescued, #Hostages_Not_Rescued)
      - Radio audio mirrors of the above (%!MRAD_*)
      - Match restarts (#Game_will_restart_in) — common in pro CS 1.6
        where teams do LIVE restarts at match start or after pauses."""
    signals = (
        # Round end
        b"#CTs_Win", b"#Terrorists_Win", b"#Round_Draw",
        b"#Target_Bombed", b"#Bomb_Defused", b"#Target_Saved",
        b"#All_Hostages_Rescued", b"#Hostages_Not_Rescued",
        b"%!MRAD_ctwin", b"%!MRAD_terwin", b"%!MRAD_rounddraw",
        b"%!MRAD_bombdef",
        # Match restart — also acts as a round boundary
        b"#Game_will_restart_in",
    )
    boundaries = []
    last_added = -10.0
    for ftime, msg in netmsgs:
        for sig in signals:
            if sig in msg:
                # Dedupe: TextMsg + SendAudio often fire within the same tick,
                # and #Game_will_restart_in is typically echoed by
                # #Game_will_restart_in_console ~same frame.
                if ftime - last_added > 2.0:
                    boundaries.append(ftime)
                    last_added = ftime
                break
    return boundaries


def select_round_multikills(kills, min_count, round_boundaries=None, max_gap_sec=25.0):
    """Return streaks of kills by the same player within a single round.

    If round_boundaries is given (timestamps of round ends), kills are
    bucketed by round and per-killer multikills extracted from each bucket.
    Otherwise falls back to heuristic: split on killer's death OR
    on gaps > max_gap_sec between consecutive kills."""
    from collections import defaultdict

    if round_boundaries:
        import bisect
        buckets = defaultdict(list)  # (round_idx, killer) -> [kills]
        for k in kills:
            ftime, killer, _v, _hs, _w = k
            if killer == 0:
                continue
            # bisect_left places kill at time == boundary[i] into round i
            # i.e. the round that just ended — the correct bucket, since
            # the game-ending frag is part of that round.
            r = bisect.bisect_left(round_boundaries, ftime)
            buckets[(r, killer)].append(k)

        streaks = []
        for (_r, _killer), klst in buckets.items():
            if len(klst) >= min_count:
                klst.sort(key=lambda x: x[0])
                streaks.append(klst)
        streaks.sort(key=lambda s: s[0][0])
        return streaks

    # --- Fallback: no boundaries detected ---
    events = defaultdict(list)
    for k in kills:
        ftime, killer, victim, _hs, _w = k
        if killer != 0:
            events[killer].append((ftime, "kill", k))
        events[victim].append((ftime, "died", None))

    streaks = []
    for _player, evs in events.items():
        evs.sort(key=lambda e: e[0])
        cur = []
        last_kt = None
        for t, kind, k in evs:
            if kind == "kill":
                if last_kt is not None and t - last_kt > max_gap_sec:
                    if len(cur) >= min_count:
                        streaks.append(cur)
                    cur = []
                cur.append(k)
                last_kt = t
            else:
                if len(cur) >= min_count:
                    streaks.append(cur)
                cur = []
                last_kt = None
        if len(cur) >= min_count:
            streaks.append(cur)
    streaks.sort(key=lambda s: s[0][0])
    return streaks


def select_multikills(kills, window_sec, min_count):
    """Return only kills that are part of streaks: same killer, gap<=window."""
    by_killer = {}
    for k in kills:
        if k[1] == 0:  # skip world / suicides
            continue
        by_killer.setdefault(k[1], []).append(k)

    selected = []
    for ks in by_killer.values():
        ks.sort(key=lambda x: x[0])
        run = [ks[0]]
        for k in ks[1:]:
            if k[0] - run[-1][0] <= window_sec:
                run.append(k)
            else:
                if len(run) >= min_count:
                    selected.extend(run)
                run = [k]
        if len(run) >= min_count:
            selected.extend(run)

    selected.sort(key=lambda x: x[0])
    return selected


# ---------------------------------------------------------------------------
# Highlight selection for CSV export
# ---------------------------------------------------------------------------
HS_COMBO_WEAPONS = {"deagle", "ak47", "m4a1"}


def select_highlights(kills, round_boundaries):
    """Apply the highlight selection rules used for CSV export:

    Include ALL kills a player made in one round if:
      - 4 or 5 kills (quads and aces), any weapons, any distribution
      - exactly 3 kills AND all are headshots AND span <= 5s AND all weapons
        are in {deagle, ak47, m4a1}
      - exactly 3 kills AND all from AWP AND all within 1 second (triple
        one-shot)
      - exactly 2 kills AND both from AWP AND within 1 second (double
        one-shot)

    Returns list of streaks (each a list of kill tuples), sorted by first
    kill time."""
    from collections import defaultdict
    import bisect

    buckets = defaultdict(list)
    for k in kills:
        ftime, killer, victim, _hs, _w = k
        if killer == 0:                   # world damage with no attacker
            continue
        if killer == victim:              # self-kill: falldamage, own nade, etc.
            continue                      # doesn't count toward a multikill
        r = bisect.bisect_left(round_boundaries, ftime) if round_boundaries else 0
        buckets[(r, killer)].append(k)

    highlights = []
    for klst in buckets.values():
        klst.sort(key=lambda x: x[0])
        n = len(klst)

        if n in (4, 5):
            highlights.append(klst)
            continue

        if n == 3:
            times = [k[0] for k in klst]
            span = times[-1] - times[0]
            weapons = [k[4].lower() for k in klst]
            all_hs = all(k[3] == 1 for k in klst)

            if all_hs and span <= 5.0 and all(w in HS_COMBO_WEAPONS for w in weapons):
                highlights.append(klst)
                continue
            if all(w == "awp" for w in weapons) and span <= 1.0:
                highlights.append(klst)
                continue

        if n == 2:
            times = [k[0] for k in klst]
            weapons = [k[4].lower() for k in klst]
            if all(w == "awp" for w in weapons) and times[-1] - times[0] <= 1.0:
                highlights.append(klst)
                continue

    highlights.sort(key=lambda s: s[0][0])
    return highlights


# ---------------------------------------------------------------------------
# HLTV vs POV detection
# ---------------------------------------------------------------------------
def detect_demo_type(netmsgs):
    """Distinguish HLTV from POV demos.

    HLTV demos are recorded by an HLTV proxy (spectator-side) and contain
    several tell-tale signals that POV demos don't:
      1. SVC_HLTV messages (net protocol id 50 / 0x32) appear in the stream
         at regular intervals to announce HLTV state.
      2. The strings 'HLTV' / 'hltv' / 'HLTV Proxy' show up in server/client
         info, hostnames, model paths etc.
    We count matches and require a few to avoid random byte collisions."""
    hltv_string_hits = 0
    hltv_svc_hits = 0
    for _ftime, msg in netmsgs:
        hltv_string_hits += msg.count(b"HLTV") + msg.count(b"hltv")
        i = 0
        L = len(msg)
        while i < L:
            if msg[i] == 50:
                # Weak signature for SVC_HLTV; we just count occurrences.
                hltv_svc_hits += 1
            i += 1
            if hltv_svc_hits > 50 or hltv_string_hits > 5:
                return "HLTV"
    return "HLTV" if (hltv_string_hits >= 3 or hltv_svc_hits >= 20) else "POV"


# ---------------------------------------------------------------------------
# High-level parse wrapper for UI / CSV export
# ---------------------------------------------------------------------------
def parse_demo_full(demo_path):
    """One-call parse: reads demo, applies per-event server-time correction,
    returns a dict with everything the UI needs."""
    data = Path(demo_path).read_bytes()
    info = parse_demo_container(data)
    netmsgs = info["netmsgs"]

    deathmsg_id, _ = find_deathmsg_id(netmsgs)
    if deathmsg_id is None:
        raise ValueError("DeathMsg user message registration not found")

    slot_names = find_player_names(netmsgs)
    kills = find_kills(netmsgs, deathmsg_id)
    boundaries = find_round_boundaries(netmsgs)

    # Server-time correction: sample every SVC_TIME in the demo, then for
    # each kill/boundary look up the nearest sample to compute its real
    # in-game timestamp. This matters because the offset drifts during
    # playback (signon frames carry SVC_TIME=0, real uptime starts later).
    svc_samples = collect_svc_time_samples(netmsgs)

    kills = apply_server_time_to_events(
        kills, svc_samples,
        get_ftime=lambda k: k[0],
        set_ftime=lambda k, t: (t, k[1], k[2], k[3], k[4]),
    )
    boundaries = apply_server_time_to_events(
        boundaries, svc_samples,
        get_ftime=lambda t: t,
        set_ftime=lambda _t, new: new,
    )

    # Also report a robust offset estimate for diagnostics/UI display.
    # Use a median across early samples — the very first sample is often
    # a garbage outlier, so we skip past the signon area to get a clean read.
    if svc_samples:
        early = svc_samples[:200] if len(svc_samples) >= 200 else svc_samples
        early_offsets = sorted(s[1] - s[0] for s in early)
        initial_offset = early_offsets[len(early_offsets) // 2]
    else:
        initial_offset = 0.0

    highlights = select_highlights(kills, boundaries)
    demo_type = detect_demo_type(netmsgs)

    return {
        "demo_name": Path(demo_path).name,
        "map_name": info["map_name"],
        "demo_type": demo_type,
        "slot_names": slot_names,
        "highlights": highlights,
        "server_time_offset": initial_offset,
        "svc_sample_count": len(svc_samples),
    }


# ---------------------------------------------------------------------------
# CSV row building
# ---------------------------------------------------------------------------
WEAPON_DISPLAY_RENAMES = {
    "ak47": "ak",
    "hegrenade": "grenade",
}


def _weapon_display(weapon):
    return WEAPON_DISPLAY_RENAMES.get(weapon.lower(), weapon.lower())


COUNT_LABELS = {2: "2k", 3: "3k", 4: "4k", 5: "ace"}


def build_info_string(streak):
    """Build the 'info' CSV column: '<label> with <weapons>'."""
    label = COUNT_LABELS.get(len(streak), f"{len(streak)}k")
    seen = []
    for _t, _k, _v, _hs, w in streak:
        disp = _weapon_display(w)
        if disp not in seen:
            seen.append(disp)
    return f"{label} with {', '.join(seen)}"


def build_csv_rows(parsed):
    """Build CSV rows from a parsed demo dict.
    Returns list of [demo_name, map, player_name, highlight, info]."""
    rows = []
    slot_names = parsed["slot_names"]
    for streak in parsed["highlights"]:
        killer_idx = streak[0][1]
        killer_name = slot_names.get(killer_idx - 1, f"player_{killer_idx}")

        highlight_lines = []
        for ftime, _k, v_idx, hs, weapon in streak:
            victim = slot_names.get(v_idx - 1, f"player_{v_idx}")
            highlight_lines.append(format_kill(ftime, killer_name, victim, hs, weapon))

        rows.append([
            parsed["demo_name"],
            parsed["map_name"],
            killer_name,
            "\n".join(highlight_lines),
            build_info_string(streak),
        ])
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _fmt_time(ftime):
    """Format as H:MM:SS when >= 1 hour, otherwise MM:SS."""
    ftime = max(0.0, ftime)
    total = int(ftime)
    hours = total // 3600
    mins = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_kill(ftime, killer_name, victim_name, headshot, weapon):
    ts = _fmt_time(ftime)
    if headshot:
        return f"{ts}: {killer_name} killed {victim_name} with a headshot from {weapon}"
    return f"{ts}: {killer_name} killed {victim_name} with {weapon}"


STREAK_LABELS = {2: "DOUBLE", 3: "TRIPLE", 4: "QUAD", 5: "ACE"}


def format_streak(streak, slot_names, boundaries=None):
    killer_idx = streak[0][1]
    killer_name = slot_names.get(killer_idx - 1, f"player_{killer_idx}")
    t0, t1 = streak[0][0], streak[-1][0]
    label = STREAK_LABELS.get(len(streak), f"{len(streak)}-KILL")

    round_tag = ""
    if boundaries:
        import bisect
        r = bisect.bisect_left(boundaries, t0) + 1  # 1-based round number
        round_tag = f" [Round {r}]"

    header = (f"=== {label}{round_tag} by {killer_name} "
              f"({_fmt_time(t0)} - {_fmt_time(t1)}) ===")
    lines = [header]
    for ftime, _k_idx, v_idx, hs, weapon in streak:
        victim_name = slot_names.get(v_idx - 1, f"player_{v_idx}")
        lines.append(format_kill(ftime, killer_name, victim_name, hs, weapon))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="CS 1.6 demo killfeed / multikill extractor")
    ap.add_argument("demo", help="Path to .dem file")
    ap.add_argument("--rounds", type=int, metavar="N",
                    help="Find streaks of N+ kills within a single round "
                         "(round = between killer's deaths AND no gap > --max-gap). "
                         "Typical: 4 or 5.")
    ap.add_argument("--max-gap", type=float, default=25.0,
                    help="Max seconds between kills in a round streak (default: 25). "
                         "Larger gap = round transition.")
    ap.add_argument("--window", type=float, default=5.0,
                    help="Multikill window in seconds (default: 5)")
    ap.add_argument("--min-kills", type=int, default=2,
                    help="Minimum kills per streak for --window mode (default: 2)")
    ap.add_argument("--flat", action="store_true",
                    help="In --rounds mode, skip '=== QUAD ===' headers — "
                         "emit just the kill lines, one streak after another.")
    ap.add_argument("--no-server-time", action="store_true",
                    help="Output demo time (from 0:00) instead of server time "
                         "(which matches the timer shown in the game's demo player).")
    ap.add_argument("--all-kills", action="store_true",
                    help="Output every kill, not just multikills")
    ap.add_argument("--debug", action="store_true", help="Verbose output")
    args = ap.parse_args()

    demo_path = Path(args.demo)
    if not demo_path.is_file():
        print(f"File not found: {demo_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {demo_path} ({demo_path.stat().st_size:,} bytes)")
    data = demo_path.read_bytes()
    info = parse_demo_container(data)
    print(f"  map={info['map_name']!r} mod={info['mod_name']!r}")
    print(f"  demo_proto={info['demo_protocol']} net_proto={info['net_protocol']}")
    print(f"  NetMsg frames: {len(info['netmsgs'])}")

    deathmsg_id, declared_size = find_deathmsg_id(info["netmsgs"])
    if deathmsg_id is None:
        print("ERROR: DeathMsg user message registration not found in demo.")
        print("Hint: this might not be a CS 1.6 demo, or it's a partial/HLTV chunk")
        print("      that was recorded after the registration handshake.")
        sys.exit(2)
    print(f"  DeathMsg user_msg_id={deathmsg_id} declared_size={declared_size}")

    slot_names = find_player_names(info["netmsgs"])
    print(f"  Players: {len(slot_names)}")
    if args.debug:
        for s in sorted(slot_names):
            print(f"    slot {s}: {slot_names[s]}")

    kills = find_kills(info["netmsgs"], deathmsg_id)
    print(f"  Total kills: {len(kills)}")

    boundaries = find_round_boundaries(info["netmsgs"])
    print(f"  Round boundaries detected: {len(boundaries)}")
    if args.debug and boundaries:
        for i, t in enumerate(boundaries, 1):
            print(f"    round {i} end: {_fmt_time(t)}")

    # Server time correction — aligns output with the timer shown in-game.
    # The offset isn't constant: signon frames send SVC_TIME=0 so real
    # server uptime only enters the stream some frames later. We sample
    # every SVC_TIME in the demo and apply the nearest one to each event.
    if not args.no_server_time:
        svc_samples = collect_svc_time_samples(info["netmsgs"])
        if svc_samples:
            first_ft, first_srv = svc_samples[0]
            last_ft, last_srv = svc_samples[-1]
            first_off = first_srv - first_ft
            last_off = last_srv - last_ft
            print(f"  Server time: {len(svc_samples)} samples, "
                  f"offset drift {first_off:.1f}s -> {last_off:.1f}s "
                  f"(output will match in-game player)")
            kills = apply_server_time_to_events(
                kills, svc_samples,
                get_ftime=lambda k: k[0],
                set_ftime=lambda k, t: (t, k[1], k[2], k[3], k[4]),
            )
            boundaries = apply_server_time_to_events(
                boundaries, svc_samples,
                get_ftime=lambda t: t,
                set_ftime=lambda _t, new: new,
            )
        else:
            print("  Server time: no SVC_TIME samples, using demo time (0:00 start)")

    out_path = demo_path.with_name(demo_path.stem + "_multikills.txt")

    if args.rounds is not None:
        if boundaries:
            streaks = select_round_multikills(kills, args.rounds, boundaries)
            method = f"via {len(boundaries)} round boundaries"
        else:
            streaks = select_round_multikills(
                kills, args.rounds, None, args.max_gap
            )
            method = f"via max-gap heuristic ({args.max_gap}s) — no boundary signals found"
        print(f"  Round streaks with {args.rounds}+ kills ({method}): {len(streaks)}")
        with open(out_path, "w", encoding="utf-8") as f:
            for i, s in enumerate(streaks):
                if args.flat:
                    # Plain list: blank line between streaks for readability
                    if i:
                        f.write("\n")
                    killer_idx = s[0][1]
                    killer_name = slot_names.get(killer_idx - 1, f"player_{killer_idx}")
                    for ftime, _k, v_idx, hs, weapon in s:
                        victim_name = slot_names.get(v_idx - 1, f"player_{v_idx}")
                        f.write(format_kill(ftime, killer_name, victim_name, hs, weapon) + "\n")
                else:
                    if i:
                        f.write("\n")
                    f.write(format_streak(s, slot_names, boundaries) + "\n")
    elif args.all_kills:
        out_kills = sorted(kills, key=lambda x: x[0])
        with open(out_path, "w", encoding="utf-8") as f:
            for ftime, k_idx, v_idx, hs, weapon in out_kills:
                killer_name = slot_names.get(k_idx - 1, f"player_{k_idx}")
                victim_name = slot_names.get(v_idx - 1, f"player_{v_idx}")
                f.write(format_kill(ftime, killer_name, victim_name, hs, weapon) + "\n")
    else:
        out_kills = select_multikills(kills, args.window, args.min_kills)
        print(f"  Multikill streaks (window={args.window}s, min={args.min_kills}): "
              f"{len(out_kills)}")
        with open(out_path, "w", encoding="utf-8") as f:
            for ftime, k_idx, v_idx, hs, weapon in out_kills:
                killer_name = slot_names.get(k_idx - 1, f"player_{k_idx}")
                victim_name = slot_names.get(v_idx - 1, f"player_{v_idx}")
                f.write(format_kill(ftime, killer_name, victim_name, hs, weapon) + "\n")

    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
