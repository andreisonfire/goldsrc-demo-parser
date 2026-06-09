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
def _walk_frames(data, start, end, stop_on_finalmacro=True):
    """Walk frames in [start, end). Returns (netmsgs, frame_type_counts,
    final_position, exit_reason).

    netmsgs is a list of (frame_time, msg_bytes) tuples for every NetMsg
    frame encountered. frame_type_counts is a dict {0..9: count} that
    tells us how many of each frame type were seen — this is the basis
    for POV/HLTV detection (see detect_demo_type).

    If stop_on_finalmacro is True, returns when hitting a frame type 5
    (FinalMacro) — used for normal directory-driven parsing.
    If False, keeps going past FinalMacro until end-of-data — used for
    fallback when the directory table is broken/missing."""
    netmsgs = []
    counts = {i: 0 for i in range(10)}
    pos = start
    while pos < end:
        if pos + 9 > end:
            return netmsgs, counts, pos, "out of bytes for frame header"
        ftype = data[pos]
        ftime, _fframe = struct.unpack_from("<fI", data, pos + 1)
        pos += 9

        if 0 <= ftype <= 9:
            counts[ftype] += 1

        if ftype in (0, 1):  # NetMsg frame
            if pos + NETMSGINFO_SIZE + NETMSG_TAIL_SIZE > end:
                return netmsgs, counts, pos, "truncated NetMsg info"
            pos += NETMSGINFO_SIZE
            seqs = struct.unpack_from("<iiiiiiiI", data, pos)
            pos += NETMSG_TAIL_SIZE
            msg_length = seqs[7]
            if msg_length < 0 or msg_length > 65536 or pos + msg_length > end:
                return netmsgs, counts, pos, f"bad NetMsg length {msg_length}"
            netmsgs.append((ftime, data[pos : pos + msg_length]))
            pos += msg_length
        elif ftype == 2:  # FirstMacro / DemoStart — no payload
            pass
        elif ftype == 3:  # ConsoleCommand
            pos += 64
        elif ftype == 4:  # ClientData
            pos += 32
        elif ftype == 5:  # FinalMacro / NextSection
            if stop_on_finalmacro:
                return netmsgs, counts, pos, "FinalMacro"
            # In fallback mode, keep going — the next section starts here.
        elif ftype == 6:  # Event
            pos += 84
        elif ftype == 7:  # WeaponAnim
            pos += 8
        elif ftype == 8:  # Sound (variable)
            if pos + 8 > end:
                return netmsgs, counts, pos, "truncated Sound frame"
            _channel, sample_length = struct.unpack_from("<ii", data, pos)
            pos += 8 + sample_length + 16
        elif ftype == 9:  # DemoBuffer (variable)
            if pos + 4 > end:
                return netmsgs, counts, pos, "truncated DemoBuffer frame"
            buf_len = struct.unpack_from("<i", data, pos)[0]
            pos += 4 + buf_len
        else:
            return netmsgs, counts, pos, f"unknown frame type {ftype}"

    return netmsgs, counts, pos, "end of data"


def parse_demo_container(data: bytes):
    """Parse demo header + frames. Returns dict with metadata and list of
    (frame_time, msg_bytes) tuples for every NetMsg frame in playback order.

    Robust against broken/missing directory tables: if the directory is
    unparseable (zero offset, absurd count, truncated entries), falls back
    to streaming all frames sequentially from the end of the header.

    This recovery is what lets us parse demos from crashed HLTV proxies
    where the directory wasn't written before the recording stopped."""
    if len(data) < HEADER_SIZE or data[:8] != DEMO_MAGIC:
        raise ValueError("Not a GoldSrc demo file (bad magic)")

    demo_protocol, net_protocol = struct.unpack_from("<II", data, 8)
    map_name = data[16 : 16 + 260].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    mod_name = data[276 : 276 + 260].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    map_crc, dir_offset = struct.unpack_from("<iI", data, 536)

    # --- Try directory-driven parsing first (the normal path) ---
    directory_ok = False
    directories = []
    if 0 < dir_offset and dir_offset + 4 <= len(data):
        try:
            (dir_count,) = struct.unpack_from("<I", data, dir_offset)
            if 0 < dir_count <= 16:
                pos = dir_offset + 4
                tmp_dirs = []
                for _ in range(dir_count):
                    if pos + DIRECTORY_ENTRY_SIZE > len(data):
                        raise ValueError("truncated entry")
                    d_id = struct.unpack_from("<I", data, pos)[0]
                    d_name = data[pos + 4 : pos + 68].split(b"\x00", 1)[0].decode("ascii", errors="replace")
                    flags, cd_track, dtime, frames, doffset, dlength = struct.unpack_from(
                        "<IifIII", data, pos + 68
                    )
                    pos += DIRECTORY_ENTRY_SIZE
                    tmp_dirs.append({
                        "id": d_id, "name": d_name, "flags": flags,
                        "cd_track": cd_track, "time": dtime, "frames": frames,
                        "offset": doffset, "length": dlength,
                    })
                # Sanity-check: all offsets must point inside the file.
                if all(HEADER_SIZE <= d["offset"] < len(data) for d in tmp_dirs):
                    directories = tmp_dirs
                    directory_ok = True
        except (struct.error, ValueError):
            pass

    netmsgs = []
    frame_type_counts = {i: 0 for i in range(10)}
    fallback_used = False

    if directory_ok:
        # Normal path: walk each section using directory offsets
        for d in directories:
            section_end = d["offset"] + d["length"] if d["length"] > 0 else len(data)
            section_end = min(section_end, len(data))
            chunk, chunk_counts, _, _ = _walk_frames(
                data, d["offset"], section_end, stop_on_finalmacro=True
            )
            netmsgs.extend(chunk)
            for k, v in chunk_counts.items():
                frame_type_counts[k] = frame_type_counts.get(k, 0) + v
    else:
        # Fallback: directory is broken. Stream from end of header to EOF,
        # ignoring FinalMacro section boundaries (otherwise we'd stop after
        # the short LOADING section and miss the entire Playback section).
        netmsgs, frame_type_counts, _final_pos, _reason = _walk_frames(
            data, HEADER_SIZE, len(data), stop_on_finalmacro=False
        )
        fallback_used = True

    return {
        "map_name": map_name,
        "mod_name": mod_name,
        "demo_protocol": demo_protocol,
        "net_protocol": net_protocol,
        "netmsgs": netmsgs,
        "fallback_used": fallback_used,
        "frame_type_counts": frame_type_counts,
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


def find_name_history(netmsgs):
    """Build slot -> list of (ftime, name) tuples — full name history per slot.

    Returns timestamps in DEMO time (raw netmsg ftime), not server time. The
    caller maps to server time as needed.

    Why this exists: a player can change nick mid-game or after the match
    ends. The simple `slot_names` dict only stores the LAST name seen, which
    means kills made earlier in the match get attributed to the player's
    post-match name. Common example: an esports player finishes their game
    and renames to 'gg' / 'kk' / 'bb'. Without the history, all their kills
    show up as 'gg' in the CSV.

    Use `name_at_time(history, slot, demo_time)` to look up the right name.
    """
    return _scan_userinfo_field(netmsgs, b"name")


def find_model_history(netmsgs):
    """Build slot -> list of (ftime, model_name) tuples — model per slot over time.

    The 'model' field in CS 1.6 userinfo carries the player's character model,
    which directly maps to the team they're playing for:
      CT models: urban, sas, gign, gsg9, spetsnaz
      T models:  terror, leet, guerilla, arctic, militia

    The model updates at side switches (typically after 15 rounds), so
    tracking it over time lets us answer "what side was this player on at
    the moment of this kill?" — needed to identify team-kills and exclude
    them from highlight counts.

    Why model and not the \\team\\ field: many CS 1.6 demos don't include
    the team key in their userinfo blob, but the model is reliably set on
    every spawn. The model:side mapping is fixed by the game.
    """
    return _scan_userinfo_field(netmsgs, b"model")


def _scan_userinfo_field(netmsgs, field_name):
    """Generic scanner: extract a specific \\fieldname\\value\\ from every
    SVC_UPDATEUSERINFO seen in the demo, deduplicating consecutive equal
    values per slot. Returns slot -> [(ftime, value), ...]."""
    pattern = re.compile(rb"\\" + re.escape(field_name) + rb"\\([^\\\x00]+)")
    history = {}
    for ftime, msg in netmsgs:
        i = 0
        L = len(msg)
        while i < L - 7:
            if msg[i] == SVC_UPDATEUSERINFO and msg[i + 1] <= 31:
                first = msg[i + 6]
                if first == 0x5C or first == 0:
                    slot = msg[i + 1]
                    null_pos = msg.find(b"\x00", i + 6, min(i + 6 + 260, L))
                    if null_pos >= i + 6:
                        userinfo = msg[i + 6 : null_pos]
                        m = pattern.search(userinfo)
                        if m:
                            value_bytes = m.group(1)
                            value = None
                            for enc in ("utf-8", "cp1251", "latin-1"):
                                try:
                                    value = value_bytes.decode(enc)
                                    break
                                except UnicodeDecodeError:
                                    continue
                            if value is None:
                                value = value_bytes.decode("ascii", errors="replace")
                            lst = history.setdefault(slot, [])
                            # Dedupe consecutive identical values
                            if not lst or lst[-1][1] != value:
                                lst.append((ftime, value))
                        i = null_pos + 1 + 16
                        continue
            i += 1
    return history


# CS 1.6 model -> side mapping (fixed by the game)
CT_MODELS = {"urban", "sas", "gign", "gsg9", "spetsnaz"}
T_MODELS  = {"terror", "leet", "guerilla", "arctic", "militia"}


def model_to_side(model_name):
    """Return 'CT', 'T', or None for a CS 1.6 character model name.

    None means "unknown" — could be a spectator-only entity, a custom server
    model, or a partial parse. Callers should treat None as "don't assume
    same team" so we don't accidentally drop legitimate kills.
    """
    if not model_name:
        return None
    m = model_name.lower()
    if m in CT_MODELS:
        return "CT"
    if m in T_MODELS:
        return "T"
    return None


def side_at_time(model_history, slot, query_time):
    """Return CT/T for a slot at a specific moment, or None if unknown.

    Looks up the most recent model update for this slot at or before
    query_time, then maps to side. Same time-base contract as
    name_at_time — caller must use either demo time or server time
    consistently for both arguments and the history.
    """
    entries = model_history.get(slot)
    if not entries:
        return None
    last_model = entries[0][1]
    for t, model in entries:
        if t > query_time:
            break
        last_model = model
    return model_to_side(last_model)


def is_teammate_kill(kill, model_history):
    """True iff this kill is a team-kill (killer and victim on the same side
    at the moment of the kill).

    Conservative: only returns True when BOTH sides are known and equal.
    If either is unknown, returns False so we don't drop legitimate kills
    when team info is missing (some demos may have partial userinfo data).
    """
    ftime, killer_ent, victim_ent, _hs, _w = kill
    if killer_ent == 0 or killer_ent == victim_ent:
        return False
    # Entity index in kill tuples is 1-based; userinfo slot is 0-based
    k_side = side_at_time(model_history, killer_ent - 1, ftime)
    v_side = side_at_time(model_history, victim_ent - 1, ftime)
    if k_side is None or v_side is None:
        return False
    return k_side == v_side


def name_at_time(history, slot, query_time, fallback=None):
    """Look up the player's name at a specific moment in time.

    Returns the most recent name set BEFORE or AT query_time. If the slot
    has no history entries before this time (e.g. query is from before any
    userinfo packet for this slot), returns the FIRST known name as a
    fallback — better than returning None which would corrupt downstream
    formatting.

    history: dict from find_name_history()
    slot: 0-based slot index
    query_time: float — same time-base as history entries (demo or server time,
                pick one consistently in the caller)
    fallback: returned if slot has no history at all
    """
    entries = history.get(slot)
    if not entries:
        return fallback
    last = entries[0][1]    # first known name as default
    for t, name in entries:
        if t > query_time:
            break
        last = name
    return last


def most_common_name(history, slot, fallback=None):
    """Return the name this slot held the LONGEST during the demo.

    Used for the recorder identification: a player who renames mid-game or
    after the match still has a 'canonical' name (the one they used for most
    of the demo). Picking that instead of the last name avoids
    'recorder=gg' artifacts in the UI for esports demos.
    """
    entries = history.get(slot)
    if not entries:
        return fallback
    if len(entries) == 1:
        return entries[0][1]
    # Compute duration each name was held. The last entry runs until the end
    # of the demo, which we estimate as max(all_times) + small epsilon.
    all_times = []
    for h in history.values():
        for t, _n in h:
            all_times.append(t)
    end_time = max(all_times) if all_times else entries[-1][0] + 1
    durations = {}
    for i, (t, name) in enumerate(entries):
        next_t = entries[i + 1][0] if i + 1 < len(entries) else end_time
        durations[name] = durations.get(name, 0) + (next_t - t)
    # Return the name with the largest total duration
    return max(durations.items(), key=lambda x: x[1])[0]


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
def find_round_events(netmsgs):
    """Scan NetMsg payloads for round-related signals. Returns a sorted list
    of (ftime, kind) tuples where kind is either 'round_end' or 'restart'.

    Signals are plain ASCII strings embedded in SendAudio/TextMsg user
    messages — we match them by substring without full user-msg parsing.

    Categories:
      - 'round_end' — a real round was won/lost/drawn:
            #CTs_Win, #Terrorists_Win, #Round_Draw,
            #Target_Bombed, #Bomb_Defused, #Target_Saved,
            #All_Hostages_Rescued, #Hostages_Not_Rescued,
            and their %!MRAD_* radio mirrors
      - 'restart' — the match was reset (warm-up end, false start,
        live restart, etc.):
            #Game_will_restart_in"""
    round_end_signals = (
        b"#CTs_Win", b"#Terrorists_Win", b"#Round_Draw",
        b"#Target_Bombed", b"#Bomb_Defused", b"#Target_Saved",
        b"#All_Hostages_Rescued", b"#Hostages_Not_Rescued",
        b"%!MRAD_ctwin", b"%!MRAD_terwin", b"%!MRAD_rounddraw",
        b"%!MRAD_bombdef",
    )
    restart_signals = (
        b"#Game_will_restart_in",
    )

    events = []
    last_added = {"round_end": -10.0, "restart": -10.0}
    for ftime, msg in netmsgs:
        for sig in round_end_signals:
            if sig in msg:
                if ftime - last_added["round_end"] > 2.0:
                    events.append((ftime, "round_end"))
                    last_added["round_end"] = ftime
                break
        for sig in restart_signals:
            if sig in msg:
                if ftime - last_added["restart"] > 2.0:
                    events.append((ftime, "restart"))
                    last_added["restart"] = ftime
                break

    events.sort(key=lambda e: e[0])
    return events


def find_round_boundaries(netmsgs):
    """Backward-compatible: returns just timestamps of all round-related
    events (both round-end and restart) as a flat sorted list.

    New code should prefer find_round_events() which preserves event types."""
    return [t for t, _kind in find_round_events(netmsgs)]


def find_match_start(round_events, min_rounds_in_half=15):
    """Find the timestamp of the first match restart that is followed by
    at least `min_rounds_in_half` round-ends without another restart.

    Why this matters: pro CS 1.6 demos often start with a long warm-up,
    then teams do an `mp_restartround` ("LIVE restart") to begin the match.
    But sometimes a player drops out in the first few rounds, the team
    requests a redo, another LIVE restart happens — and so on. We don't
    want to count any of the false-start kills as highlights.

    Logic: a CS 1.6 match half is exactly 15 rounds. The first restart
    that is followed by 15 clean round-ends (no more restarts) is the
    real match start. Everything before it is warm-up or false starts.

    On overtime support: this function returns the *single* match-start
    timestamp. We do NOT need to track side-switch restarts or OT
    restarts separately because they always happen AFTER the first 15
    rounds completed — so they sit safely after match_start in time.
    Anything past match_start is real gameplay, including OT halves
    that have only 3 round-ends per restart.

    Returns the ftime of that restart, or None if no qualifying start
    was found (e.g. casual demos with no restart at all)."""
    for i, (ftime, kind) in enumerate(round_events):
        if kind != "restart":
            continue
        # Count round_end events after this restart, stopping if another
        # restart is encountered before we hit min_rounds_in_half.
        round_ends_after = 0
        for ftime2, kind2 in round_events[i + 1:]:
            if kind2 == "restart":
                break  # false start — try next restart
            if kind2 == "round_end":
                round_ends_after += 1
                if round_ends_after >= min_rounds_in_half:
                    return ftime
    return None


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
ONE_SHOT_WEAPONS = {"awp", "scout"}
ONE_SHOT_WINDOW = 1.0   # seconds: kills closer than this count as a single one-shot multikill
HS_COMBO_WEAPONS = {"deagle", "ak47", "m4a1"}
HS_COMBO_WINDOW = 5.0   # seconds: 3 HS within this window with combo weapons is "fast 3hs"


def _find_one_shot_subset(klst, weapon_name, k, window):
    """Find a subset of `k` kills with `weapon_name`, within `window` seconds
    of each other. Returns the matching sublist (sorted) or None."""
    candidates = [x for x in klst if x[4].lower() == weapon_name]
    if len(candidates) < k:
        return None
    candidates.sort(key=lambda x: x[0])
    # Sliding window of size k
    for i in range(len(candidates) - k + 1):
        window_kills = candidates[i:i + k]
        if window_kills[-1][0] - window_kills[0][0] <= window:
            return window_kills
    return None


def _find_fast_3hs_subset(klst):
    """Find 3 HS kills with HS-combo weapons (deagle/ak47/m4a1) within 5s."""
    hs_combo = [x for x in klst if x[3] == 1 and x[4].lower() in HS_COMBO_WEAPONS]
    if len(hs_combo) < 3:
        return None
    hs_combo.sort(key=lambda x: x[0])
    for i in range(len(hs_combo) - 2):
        window_kills = hs_combo[i:i + 3]
        if window_kills[-1][0] - window_kills[0][0] <= HS_COMBO_WINDOW:
            return window_kills
    return None


def _find_all_one_shot_doubles(klst, used_ids):
    """Find ALL non-overlapping 2-kill subsets of awp/scout within 1s.

    `used_ids` is the set of id()s of kills already consumed by other subsets
    (e.g. by a triple). Those kills are excluded from this search so we don't
    double-count.

    Greedy algorithm: walk through kills in time order, pair up the first
    two that are within 1s, mark them used, continue. This finds the maximum
    number of non-overlapping doubles when there are no overlapping pairs.

    Returns list of (subset, weapon_name) tuples, one per double found.
    """
    doubles = []
    for w in ONE_SHOT_WEAPONS:
        weapon_kills = [k for k in klst
                        if k[4].lower() == w and id(k) not in used_ids]
        weapon_kills.sort(key=lambda k: k[0])
        i = 0
        while i < len(weapon_kills) - 1:
            if weapon_kills[i + 1][0] - weapon_kills[i][0] <= ONE_SHOT_WINDOW:
                pair = weapon_kills[i:i + 2]
                doubles.append((pair, w))
                used_ids.add(id(pair[0]))
                used_ids.add(id(pair[1]))
                i += 2
            else:
                i += 1
    return doubles


def _scan_subsets(klst):
    """Inside a bucket of kills (one player, one round), find notable subsets.

    Returns a dict with possible keys:
      'triple_one_shot': (subset, weapon)       — 3 awp/scout in 1s (at most 1)
      'doubles_one_shot': list of (subset, weapon) — ALL non-overlapping 2 awp/scout in 1s,
                                                     after subtracting any triple kills
      'fast_3hs': subset                         — 3 HS combo-weapon kills in 5s (at most 1)

    Math note: a triple uses 3 kills, so in n=4 quad you can't have a triple AND
    any double (only 1 kill remains). In n=5 ace you CAN have triple + 1 double
    (2 kills remaining). And double+double is possible in n=4 (4 awp in two pairs)
    or n=5 (4 awp in two pairs + 1 other).

    Two fast_3hs subsets are mathematically impossible in n<=5 (would need 6 HS kills),
    so we only track count=1 for that category.
    """
    found = {}
    used_ids = set()

    # Find triple_one_shot first (at most 1 per bucket — math)
    for w in ONE_SHOT_WEAPONS:
        subset = _find_one_shot_subset(klst, w, 3, ONE_SHOT_WINDOW)
        if subset is not None:
            found['triple_one_shot'] = (subset, w)
            used_ids.update(id(k) for k in subset)
            break

    # Find ALL non-overlapping doubles in the remaining kills (could be 0, 1, or 2+)
    doubles = _find_all_one_shot_doubles(klst, used_ids)
    if doubles:
        found['doubles_one_shot'] = doubles

    # Find fast 3hs (at most 1 — needs 3 HS combo weapons, math limits it)
    fast_3hs = _find_fast_3hs_subset(klst)
    if fast_3hs is not None:
        found['fast_3hs'] = fast_3hs

    return found


def _format_annotations(subsets):
    """Convert detected subsets into annotation labels for the info string.

    Each annotation specifies its weapon explicitly, since double/triple are
    exclusively snipers (awp or scout) and that needs to be unambiguous when
    the bucket also contains other weapons.

    Multiple doubles in the same bucket are grouped by weapon:
      - same weapon, count >= 2: 'Nx double with awp'
      - different weapons: listed separately ('double with awp, double with scout')

    Annotations are emitted in priority order: triple > double > fast 3hs.
    """
    annotations = []
    if 'triple_one_shot' in subsets:
        _subset, w = subsets['triple_one_shot']
        annotations.append(f'triple with {_weapon_display(w)}')
    if 'doubles_one_shot' in subsets:
        from collections import Counter
        # Preserve weapon order (first occurrence) so output is deterministic.
        weapons_seen = []
        for _subset, w in subsets['doubles_one_shot']:
            if w not in weapons_seen:
                weapons_seen.append(w)
        weapon_counts = Counter(w for _subset, w in subsets['doubles_one_shot'])
        for weapon in weapons_seen:
            count = weapon_counts[weapon]
            disp = _weapon_display(weapon)
            if count == 1:
                annotations.append(f'double with {disp}')
            else:
                annotations.append(f'{count}x double with {disp}')
    if 'fast_3hs' in subsets:
        annotations.append('fast 3hs')
    return annotations


def select_highlights(kills, round_boundaries):
    """Apply the highlight selection rules used for CSV/TXT export.

    Each (round, killer) bucket gets classified into one of:

      n=5:  'ace with weapons' (+ annotations if subsets exist)
      n=4:  '4k with weapons'  (+ annotations if subsets exist)
      n=3:
        - all awp/scout within 1s → 'triple with awp/scout'
        - all HS + HS-combo weapons + 5s span → 'fast 3hs with weapons'
        - has a subset of 2 awp/scout within 1s → 'double with awp/scout'
          (the third kill is treated as extra and not shown in CSV — only
           the 2 kills that form the double are kept)
        - else → skipped
      n=2:
        - both awp/scout within 1s → 'double with awp/scout'
        - else → skipped

    Annotations for quad/ace, multiple allowed, in priority order:
      '(incl. triple)' if 3 awp/scout within 1s exists as a subset
      '(incl. double)' if 2 awp/scout within 1s exists (when no triple)
      '(incl. fast 3hs)' if 3 HS combo within 5s exists

    For ace specifically, both triple AND double can coexist (rare: 3-kill
    one-shot + 2-kill one-shot in different moments of the round). In that
    case the annotation reads '(incl. triple, double)'.

    Returns a list of dicts:
      {'kills': [k1, k2, ...], 'category': 'double', 'weapon': 'awp', 'annotations': [...]}
    """
    from collections import defaultdict
    import bisect

    buckets = defaultdict(list)
    for k in kills:
        ftime, killer, victim, _hs, _w = k
        if killer == 0:                   # world damage with no attacker
            continue
        if killer == victim:              # self-kill (falldamage, own nade, etc)
            continue
        r = bisect.bisect_left(round_boundaries, ftime) if round_boundaries else 0
        buckets[(r, killer)].append(k)

    highlights = []
    for klst in buckets.values():
        klst.sort(key=lambda x: x[0])
        n = len(klst)
        h = _classify_bucket(klst, n)
        if h is not None:
            highlights.append(h)

    highlights.sort(key=lambda s: s['kills'][0][0])
    return highlights


def _classify_bucket(klst, n):
    """Apply the rules to a bucket of one player's kills in one round.
    Returns a highlight dict or None if the bucket isn't a highlight."""
    if n >= 4:
        # quad/ace: always a highlight, annotate with notable subsets
        category = 'ace' if n >= 5 else '4k'
        subsets = _scan_subsets(klst)
        annotations = _format_annotations(subsets)
        return {
            'kills': klst,
            'category': category,
            'weapon': None,             # multiple weapons possible
            'annotations': annotations,
        }

    if n == 3:
        # Try the 3-kill base categories first (full bucket matches one rule)
        times = [k[0] for k in klst]
        span = times[-1] - times[0]
        weapons = [k[4].lower() for k in klst]
        all_hs = all(k[3] == 1 for k in klst)

        # triple awp/scout: all three same weapon and within 1s
        for w in ONE_SHOT_WEAPONS:
            if all(wp == w for wp in weapons) and span <= ONE_SHOT_WINDOW:
                return {
                    'kills': klst,
                    'category': 'triple',
                    'weapon': w,
                    'annotations': [],
                }

        # fast 3hs: all HS, all HS-combo weapons, within 5s
        if all_hs and all(w in HS_COMBO_WEAPONS for w in weapons) and span <= HS_COMBO_WINDOW:
            return {
                'kills': klst,
                'category': 'fast_3hs',
                'weapon': None,
                'annotations': [],
            }

        # Fall back: maybe there's a 2-kill subset that IS a one-shot double
        # (the third kill happened later in the round and the bucket-level
        # rules don't fit, but the double itself is a real wow-moment).
        for w in ONE_SHOT_WEAPONS:
            subset = _find_one_shot_subset(klst, w, 2, ONE_SHOT_WINDOW)
            if subset is not None:
                return {
                    'kills': subset,            # only the 2 kills of the double
                    'category': 'double',
                    'weapon': w,
                    'annotations': [],
                }
        return None

    if n == 2:
        times = [k[0] for k in klst]
        weapons = [k[4].lower() for k in klst]
        span = times[-1] - times[0]
        for w in ONE_SHOT_WEAPONS:
            if all(wp == w for wp in weapons) and span <= ONE_SHOT_WINDOW:
                return {
                    'kills': klst,
                    'category': 'double',
                    'weapon': w,
                    'annotations': [],
                }
        return None

    return None


# ---------------------------------------------------------------------------
# HLTV vs POV detection
# ---------------------------------------------------------------------------
def detect_demo_type(frame_type_counts):
    """Distinguish HLTV from POV demos using a single, reliable signal:
    the count of frame type 3 (ConsoleCommand).

    Why this works: ConsoleCommand frames record the recording client's
    own input — keypresses like '+attack', 'slot2', '+forward'. Only a
    real player has these; an HLTV proxy is a server-side spectator
    that has nothing to type. So the presence of even a few ConsoleCommand
    frames is a hard "this is a POV recording" signal.

    Tested on 9 real demos (4 POV, 5 HLTV) — 100% accuracy. The gap
    between POV (thousands of ConsoleCommand frames) and HLTV (zero) is
    not "small but measurable", it's an absolute presence/absence."""
    return "POV" if frame_type_counts.get(3, 0) > 0 else "HLTV"


def find_recorder_slot(netmsgs, scan_first_n=10):
    """For a POV demo, identify which player slot recorded it by parsing
    SVC_SETVIEW (id=5) messages in the very first NetMsg frames.

    How CS engine works on POV connect: the server sends SVC_SETVIEW=32
    (entity 32 = the world placeholder, "no view yet"), then immediately
    SVC_SETVIEW=<recorder_entity> to lock the camera onto the recording
    player. Spectator-mode switches (when the player dies) happen later.
    So the first SETVIEW with a real player entity index is our answer.

    SVC_SETVIEW wire format: 1 byte id (5) + 2 bytes signed entity index
    (little-endian). Entity indices are 1-based; player slots are 0-based,
    so slot = entity - 1.

    Returns the player slot (0-31) or None if not found. None typically
    means this isn't a POV demo, or the demo header is unusually short.

    Tested on 4 POV demos — 4/4 correctly identify the recording player."""
    for _ftime, msg in netmsgs[:scan_first_n]:
        i = 0
        L = len(msg)
        while i < L - 2:
            if msg[i] == 5:
                try:
                    (entity,) = struct.unpack_from("<h", msg, i + 1)
                except struct.error:
                    i += 1
                    continue
                # Real player slots are 1..31. Skip 32 (world) and 0.
                if 1 <= entity <= 31:
                    return entity - 1
            i += 1
    return None


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
    name_history = find_name_history(netmsgs)
    model_history = find_model_history(netmsgs)
    kills = find_kills(netmsgs, deathmsg_id)
    round_events = find_round_events(netmsgs)
    boundaries = [t for t, _ in round_events]

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
    # Apply server-time to round_events too, preserving kind tags
    round_events_st = apply_server_time_to_events(
        round_events, svc_samples,
        get_ftime=lambda e: e[0],
        set_ftime=lambda e, t: (t, e[1]),
    )
    # Apply server-time to the name history entries too — so a lookup with
    # a kill's server time will hit the right name change.
    name_history_st = {}
    for slot, entries in name_history.items():
        if not entries:
            continue
        translated = apply_server_time_to_events(
            entries, svc_samples,
            get_ftime=lambda e: e[0],
            set_ftime=lambda e, t: (t, e[1]),
        )
        name_history_st[slot] = translated

    # Same for model history — used to identify team-kills (same side at the
    # moment of the kill) and exclude them from highlight counting.
    model_history_st = {}
    for slot, entries in model_history.items():
        if not entries:
            continue
        translated = apply_server_time_to_events(
            entries, svc_samples,
            get_ftime=lambda e: e[0],
            set_ftime=lambda e, t: (t, e[1]),
        )
        model_history_st[slot] = translated

    # Filter out team-kills from the kill list before highlight selection.
    # A team-kill is a real DeathMsg event but it shouldn't bump n in a
    # bucket — 4 enemies + 1 teammate killed should read as a quad, not an
    # ace. Conservative: if either side is unknown for a kill, we keep it
    # (don't drop legitimate highlights when model data is partial).
    kills = [k for k in kills if not is_teammate_kill(k, model_history_st)]

    # Also report a robust offset estimate for diagnostics/UI display.
    # Use a median across early samples — the very first sample is often
    # a garbage outlier, so we skip past the signon area to get a clean read.
    if svc_samples:
        early = svc_samples[:200] if len(svc_samples) >= 200 else svc_samples
        early_offsets = sorted(s[1] - s[0] for s in early)
        initial_offset = early_offsets[len(early_offsets) // 2]
    else:
        initial_offset = 0.0

    # POV/HLTV detection. POV demos contain ConsoleCommand frames (the
    # recording client's keypresses); HLTV demos don't, since HLTV is a
    # server-side spectator. See detect_demo_type for details.
    demo_type = detect_demo_type(info["frame_type_counts"])

    # Detect the real match start: the first restart followed by ≥15 clean
    # rounds. Anything before that is warm-up or false starts.
    #
    # Apply this filter ONLY for HLTV demos. Two reasons:
    #
    # 1. HLTV recordings always start before the match begins (proxy is set
    #    up to capture warm-up, sides, OT). The first-restart-with-15-rounds
    #    heuristic is rock-solid here.
    #
    # 2. POV recordings are made by the player intentionally — typically
    #    starting at round 1 of the first half because they want to capture
    #    real match action. Warm-up multikills in POV are extremely rare
    #    (you don't usually record yourself farming AFK teammates). And the
    #    cost of misfiring is high: if a player started recording mid-first-
    #    half and got an ace before the side switch, the warm-up filter
    #    would mistake the side-switch restart for the match start and drop
    #    the ace. Skipping the filter for POV avoids that loss.
    match_start = find_match_start(round_events_st, min_rounds_in_half=15)
    if demo_type == "HLTV" and match_start is not None:
        kills_for_highlights = [k for k in kills if k[0] >= match_start]
        boundaries_for_highlights = [b for b in boundaries if b >= match_start]
    else:
        kills_for_highlights = kills
        boundaries_for_highlights = boundaries

    # For POV demos, identify the recording player and filter highlights
    # to keep only their own multikills. Other players' kills are still
    # captured by the network stream, but they're not interesting in a
    # POV recording — the user is browsing this demo for their own plays.
    recorder_slot = None
    recorder_name = None
    if demo_type == "POV":
        recorder_slot = find_recorder_slot(netmsgs)
        if recorder_slot is not None:
            # Show the name they used MOST of the demo, not the last name.
            # Esports players often rename to 'gg'/'kk'/'bb' after the match.
            recorder_name = most_common_name(
                name_history_st, recorder_slot,
                fallback=slot_names.get(recorder_slot),
            )
            recorder_entity = recorder_slot + 1
            kills_for_highlights = [
                k for k in kills_for_highlights if k[1] == recorder_entity
            ]

    highlights = select_highlights(kills_for_highlights, boundaries_for_highlights)

    return {
        "demo_name": Path(demo_path).name,
        "map_name": info["map_name"],
        "demo_type": demo_type,
        "slot_names": slot_names,
        "name_history": name_history_st,    # for name-at-time-of-kill lookup
        "model_history": model_history_st,  # for team/side lookup per kill
        "highlights": highlights,
        "server_time_offset": initial_offset,
        "svc_sample_count": len(svc_samples),
        "match_start": match_start,
        "round_events_count": len(round_events_st),
        "recorder_slot": recorder_slot,
        "recorder_name": recorder_name,
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


CATEGORY_LABELS = {
    'ace': 'ace',
    '4k': '4k',
    'triple': 'triple',
    'double': 'double',
    'fast_3hs': 'fast 3hs',
}


def build_info_string(highlight):
    """Build the 'info' CSV column.

    For category-with-known-weapon highlights (double/triple, fast_3hs):
      'double with awp'
      'triple with scout'
      'fast 3hs with deagle, ak47'

    For quad/ace (multiple weapons possible) with optional annotations:
      '4k with m4a1, awp'
      'ace with m4a1, awp (incl. triple)'
      'ace with m4a1, awp (incl. triple, double)'
    """
    cat = highlight['category']
    label = CATEGORY_LABELS.get(cat, cat)
    kills = highlight['kills']

    if cat in ('double', 'triple'):
        # Specific one-shot category — weapon is known and fixed
        weapon_disp = _weapon_display(highlight['weapon'])
        return f"{label} with {weapon_disp}"

    if cat == 'fast_3hs':
        # 3 HS combo — list the weapons used in this combo
        seen = []
        for _t, _k, _v, _hs, w in kills:
            disp = _weapon_display(w)
            if disp not in seen:
                seen.append(disp)
        return f"{label} with {', '.join(seen)}"

    # Quad / ace: list all weapons, then any annotations in parens
    seen = []
    for _t, _k, _v, _hs, w in kills:
        disp = _weapon_display(w)
        if disp not in seen:
            seen.append(disp)
    info = f"{label} with {', '.join(seen)}"
    if highlight.get('annotations'):
        info += f" (incl. {', '.join(highlight['annotations'])})"
    return info


def build_csv_rows(parsed):
    """Build CSV rows from a parsed demo dict.
    Returns list of [demo_name, map, player_name, highlight, info].

    Names are looked up AT THE TIME OF EACH KILL using name_history. This
    handles the common esports case where a player renames after the match
    (often to 'gg' / 'kk' / 'bb' as a sign-off) — earlier kills should still
    be attributed to their match name, not the post-match alias.

    Killer name uses the time of the FIRST kill in the streak (stable for
    the whole streak so the output reads naturally). Victim names use the
    time of EACH kill individually.
    """
    rows = []
    slot_names = parsed["slot_names"]
    name_history = parsed.get("name_history", {})

    for streak in parsed["highlights"]:
        kills = streak['kills']
        killer_idx = kills[0][1]
        # Killer name: use time of FIRST kill in streak for consistency
        killer_name = name_at_time(
            name_history, killer_idx - 1, kills[0][0],
            fallback=slot_names.get(killer_idx - 1, f"player_{killer_idx}"),
        )

        highlight_lines = []
        for ftime, _k, v_idx, hs, weapon in kills:
            # Victim name: at the time of THIS kill specifically
            victim = name_at_time(
                name_history, v_idx - 1, ftime,
                fallback=slot_names.get(v_idx - 1, f"player_{v_idx}"),
            )
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
    """Format time as MM:SS, expanding to MMM:SS for long matches.

    We deliberately avoid switching to H:MM:SS at the 60-minute mark — the
    in-game CS 1.6 demo player shows time as plain minutes:seconds even for
    very long sessions (e.g. '1003:36' for a 16+ hour server uptime), so
    matching that format makes it easy to scrub directly to a highlight."""
    ftime = max(0.0, ftime)
    total = int(ftime)
    mins = total // 60
    secs = total % 60
    return f"{mins:02d}:{secs:02d}"


def format_kill(ftime, killer_name, victim_name, headshot, weapon):
    """Format a single kill line.

    Headshot kills are wrapped in '*** ***' so that mouse-eye scanning the
    CSV/TXT output picks them out quickly — feedback from movie-makers
    confirmed this is genuinely useful even though it adds visual noise."""
    ts = _fmt_time(ftime)
    if headshot:
        return f"*** {ts}: {killer_name} killed {victim_name} with a headshot from {weapon} ***"
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
    ap.add_argument("--highlights", action="store_true",
                    help="Use the exact same highlight selection logic as the "
                         "web UI: aces, quads, fast 3hs, triple/double awp/scout, "
                         "with subset annotations '(incl. triple/double)'. "
                         "POV-aware (filters to recorder's own kills) and "
                         "applies the HLTV warm-up filter. This is the "
                         "recommended drag-and-drop mode.")
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

    # --highlights mode: short-circuit and use the same code path as the UI.
    # This guarantees CLI output stays in sync with the web UI even as new
    # highlight categories or filters are added.
    if args.highlights:
        try:
            parsed = parse_demo_full(str(demo_path))
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(2)

        out_path = demo_path.with_name(demo_path.stem + "_highlights.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            rows = build_csv_rows(parsed)
            f.write(f"# {parsed['demo_name']}  map={parsed['map_name']}  "
                    f"type={parsed['demo_type']}")
            if parsed.get('recorder_name'):
                f.write(f"  recorder={parsed['recorder_name']}")
            f.write(f"\n# highlights: {len(rows)}\n\n")
            for row in rows:
                _demo, _map, player, lines, info = row
                f.write(f"{info}  ({player})\n")
                for line in lines.split('\n'):
                    f.write(f"  {line}\n")
                f.write('\n')
        print(f"  type={parsed['demo_type']}  map={parsed['map_name']}  "
              f"highlights={len(rows)}")
        if parsed.get('recorder_name'):
            print(f"  recorder={parsed['recorder_name']}")
        print(f"  -> {out_path.name}")
        return

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
