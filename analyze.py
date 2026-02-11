"""Overhead Door Odyssey 1000 (Model 7030) - Protocol Analyzer
=============================================================
Decodes the 3.3V PWM serial protocol on the 4-pin wireless receiver
interface (GND, Z3, Z4, 3.3V). All protocol knowledge is embedded as
structured data so running this script against the captures reconstructs
the complete protocol specification.

Usage:
    python analyze.py              # Analyze all capture files (default)
    python analyze.py --spec       # Generate protocol reference document
    python analyze.py --file X.txt # Analyze a single capture file
    python analyze.py --raw X.txt  # Raw symbols without interpretation

Physical interface:
    Pin 1: GND
    Pin 2: Z3 (CH0) - Receiver -> Opener: commands, keepalives
    Pin 3: Z4 (CH1) - Opener -> Receiver: ACKs, status, beacons
    Pin 4: 3.3V power

PWM encoding:
    Each symbol period consists of a LOW gap followed by a HIGH separator.
    BOTH durations carry data, quantized to ~26us base units.
    The LOW duration encodes the primary symbol value (1-9).
    The HIGH duration encodes secondary data using the same alphabet
    {1,2,3,4,5,6,7,9} — notably, symbol 8 never appears in either.
    In header and status fields, HIGH is always 1 unit (separator only).
    In position fields, HIGH varies and encodes binary position data.
    Messages are bursts of symbols separated by >10ms idle-HIGH gaps.
    Carrier blocks (3838 Hz, 16 pulses) accompany some CH0 transmissions.

    Position encoding (Type B payload pos 5+):
    The position field uses active-low, LSB-first binary waveform encoding.
    Each (L,H) pair contributes L one-bits then H zero-bits to a bitstream.
    The field is split by a delimiter (7,9 or 9,9) into data_A and data_B
    regions that independently encode binary counters. data_B is the
    position counter (9-bit, wraps mod 512). data_A is a redundant check
    (A = B + constant within each delimiter phase).
"""

import os
import sys
import io
import argparse
from dataclasses import dataclass, field
from collections import Counter
from typing import List, Dict, Tuple, Optional

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ====================================================================
#  PROTOCOL KNOWLEDGE DATABASE
# ====================================================================

# -- Physical layer constants --
PWM_UNIT_US = 26.0          # Base time unit for symbol encoding (microseconds)
BURST_GAP_S = 0.010         # Minimum idle gap between bursts (seconds)
CARRIER_FREQ_HZ = 3838      # Carrier tone frequency
CARRIER_PULSES = 16         # Pulses per carrier block
CARRIER_DUTY = 0.10         # ~10% duty cycle
CROSSTALK_THRESH = 10       # H durations above this are CH0 carrier crosstalk artifacts

# -- Wire roles --
WIRE_ROLES = {
    "Z3": "Pin 2, CH0: Receiver -> Opener (commands, keepalives)",
    "Z4": "Pin 3, CH1: Opener -> Receiver (ACKs, status, beacons)",
}

# -- CH0 (Z3) Known Commands: exact-match patterns --
# Maps tuple(symbols) -> (name, description)
CH0_COMMANDS = {
    (0,0,0,0,0,3):
        ("CMD-INIT",  "Boot hello/reset - first message from receiver after power-on"),
    (1,7,1,1,5,1,4,2,9,2,3,2,4,2,1):
        ("CMD-A",     "Keepalive - sent every ~5s during normal operation"),
    (1,7,1,1,5,1,4,2,9,1,3,2,1,2,2,1):
        ("CMD-A1",    "First keepalive - transitional variant sent once after handshake"),
    (1,7,1,1,5,5,2,9,1,6,4,2):
        ("CMD-R",     "Door toggle - sent by receiver when remote button pressed"),
    (1,7,1,1,5,1,3,2,2,6,1,6,1,1,2):
        ("CMD-L",     "Light toggle - sent by receiver when remote light button pressed"),
    (1,7,1,1,5,5,1,9,1,7,2,1,1):
        ("CMD-ECHO",  "Post-command echo - sent after CMD-R or CMD-L"),
}

# CH0 prefix-match patterns (tried after exact match fails)
# List of (prefix_tuple, name, description)
CH0_PREFIXES = [
    ((1,7,3,4,1,4,1,9), "CMD-B-INIT", "Boot handshake config message"),
    ((1,7,3,4),          "CMD-B",      "Extended command (config/query)"),
    ((1,7,1,1,5),        "CMD-?",      "Unrecognized command (has command prefix)"),
]

# -- CH1 (Z4) Known Responses: exact-match patterns --
CH1_RESPONSES = {
    (1,7,3,5,1,4,1,9,1,1,2,1):
        ("ACK-A",   "ACK for CMD-A keepalive"),
    (1,7,3,5,1,4,9,1,1,2):
        ("ACK-A2",  "ACK for CMD-A (boot/transitional variant)"),
    (1,7,3,5,5,1,9,3,1,1):
        ("ACK-R",   "ACK for CMD-R door toggle"),
    (1,7,3,5,1,3,1,9,1,1,1,1):
        ("ACK-L",   "ACK for CMD-L light toggle"),
    (1,7,3,5,4,9,3):
        ("ACK-B",   "ACK for CMD-B extended command"),
    (1,7,3,5,5,9,3,1):
        ("ACK-B2",  "ACK for CMD-B (boot variant)"),
}

# CH1 prefix-match patterns
CH1_PREFIXES = [
    ((1,7,2,1,4,6,2,9), "TYPE-B",       "Status message (door/light/position state)"),
    ((1,7,3,1,3,2,3,2,9), "TYPE-C",     "Full status message (extended state)"),
    ((1,7,4,4,6,1,9),   "HANDSHAKE-D",  "Boot handshake response (type D)"),
    ((1,7,4,4,2,3,1,9), "HANDSHAKE-E",  "Boot handshake response (type E)"),
    ((1,7,5,3),          "BOOT-F",       "Boot-only message (seen once after handshake)"),
    ((1,7,1,1,5,5,1,9), "ECHO",         "Command echo (relayed back by opener)"),
    ((1,7,3,5),          "ACK-?",        "Unrecognized ACK variant"),
    ((8,5,5),            "BEACON",       "Opener beacon (polling, no receiver connected)"),
]

# -- Type B Status Message Decoding --
TYPE_B_HEADER = (1,7,2,1,4,6,2,9)
TYPE_B_HEADER_LEN = 8

# Type C header (constant portion)
TYPE_C_HEADER = (1,7,3,1,3,2,3,2,9)
TYPE_C_HEADER_LEN = 9  # for classification; full constant header is 23 symbols
TYPE_C_FULL_HEADER_LEN = 23

# Door state from Type B payload positions 0-1
DOOR_STATE_MAP = {
    (2, 6): "IDLE_CLOSED",
    (9, 4): "IDLE_OPEN",
    (1, 6): "STARTING",               # brief transitional state at motor activation
    (1, 2): "OPENING",
    (1, 3): "CLOSING",
    (3, 1): "STOPPED_MID_OPEN",
    (2, 1): "STOPPED_MID_CLOSE",
    (5, 3): "ARRIVED_OPEN",
    (2, 2): "ARRIVED_CLOSED",       # or IDLE_CLOSED_LIGHT_ON (see sub-state)
    (1, 1): "OBSTRUCTION_REVERSAL",
}

# Sub-state from Type B payload positions 2-4
SUB_STATE_MAP = {
    (3, 4, 4): "ACTIVE",         # in motion, stopped, or transitional
    (3, 4, 2): "SETTLED",        # stable idle state (light on, door closed)
    (3, 3, 3): "OBSTRUCTION",    # obstruction detected, holding position
    (3, 3, 4): "REVERSING",      # obstruction reversal in progress
    (4, 2, 1): "IDLE_OFF",       # stable idle (light off, door closed)
    (4, 3, 1): "AT_ENDPOINT",    # just arrived at travel endpoint (variant 1)
    (4, 3, 2): "AT_ENDPOINT_2",  # just arrived at travel endpoint (variant 2)
    (4, 4, 1): "ACTIVATING",     # motor activating (variant 1)
    (4, 4, 9): "ACTIVATING_2",   # motor activating (variant 2)
    (3, 9, 1): "IDLE_OPEN",      # stable idle (door open)
    (1, 3, 3): "REVERSAL_INIT",  # first frame of obstruction reversal
    (1, 3, 4): "REVERSAL_INIT_2",# first frame variant
}

# Light state from Type B payload positions 1-4 (only valid when door closed)
LIGHT_PATTERNS = {
    (6, 4, 2, 1): "OFF",
    (2, 3, 4, 2): "ON",
}

# Position field prefix at Type B payload positions 5-6
# Previously thought to be direction, but (1,7) appears in BOTH opening and
# closing. It's actually the start of the position encoding field.
# True direction is determined by the door state at positions 0-1.
POSITION_PREFIX_MAP = {
    (1, 7): "1,7",   # Standard position prefix (both directions)
    (9,):   "9",     # Short prefix variant (early in travel)
}

# Human-readable door state descriptions
DOOR_STATE_DESC = {
    "IDLE_CLOSED":          "Door closed (idle)",
    "IDLE_OPEN":            "Door open (idle)",
    "OPENING":              "Door opening",
    "CLOSING":              "Door closing",
    "STOPPED_MID_OPEN":     "Door stopped mid-travel (was opening)",
    "STOPPED_MID_CLOSE":    "Door stopped mid-travel (was closing)",
    "ARRIVED_OPEN":         "Door just arrived at fully open",
    "ARRIVED_CLOSED":       "Door just arrived at fully closed",
    "OBSTRUCTION_REVERSAL": "Obstruction detected, reversing",
    "STARTING":              "Motor starting (brief transitional)",
}

# -- Test File Manifest --
TEST_FILES = {
    "test01_idle_closed.txt":
        {"group": "baseline", "desc": "Idle, door closed, light off"},
    "test02_idle_open.txt":
        {"group": "baseline", "desc": "Idle, door open, light off"},
    "test03_idle_light_on.txt":
        {"group": "baseline", "desc": "Idle, door closed, light on"},
    "test04_open_full.txt":
        {"group": "travel", "desc": "Full open travel (closed -> open)"},
    "test05_close_full.txt":
        {"group": "travel", "desc": "Full close travel (open -> closed)"},
    "test06_open_stop_mid.txt":
        {"group": "stop_reverse", "desc": "Open then stop mid-travel"},
    "test07_resume_open.txt":
        {"group": "stop_reverse", "desc": "Resume/reverse from mid-travel"},
    "test08_close_stop_mid.txt":
        {"group": "stop_reverse", "desc": "Close then stop mid-travel"},
    "test09_reverse_while_closing.txt":
        {"group": "stop_reverse", "desc": "Reverse direction while closing"},
    "test10_light_on.txt":
        {"group": "light", "desc": "Light OFF -> ON via wall button"},
    "test11_light_off.txt":
        {"group": "light", "desc": "Light ON -> OFF via wall button"},
    "test17_obstruct_while_closing.txt":
        {"group": "obstruction", "desc": "Beam obstruction during close"},
    "test18_close_beam_blocked.txt":
        {"group": "obstruction", "desc": "Close attempt with beam already blocked"},
    "test_A1_A2.txt":
        {"group": "remote", "desc": "Remote: open from closed + stop mid-travel"},
    "test_A3.txt":
        {"group": "remote", "desc": "Remote: close from mid to fully closed"},
    "test_A4.txt":
        {"group": "remote", "desc": "Remote: light toggle on then off"},
    "B1_Boot sequence.txt":
        {"group": "boot", "desc": "Power-on boot sequence (cold start)"},
    "c1_c2_wall_button.txt":
        {"group": "no_receiver", "desc": "Receiver disconnected, wall button + idle"},
    "2026-02-10_20-52-43-chan0.txt":
        {"group": "single_ch", "desc": "Early single-channel CH0 capture"},
    "2026-02-10_20-59-53chan1.txt":
        {"group": "single_ch", "desc": "Early single-channel CH1 capture"},
}

GROUP_ORDER = [
    "baseline", "travel", "stop_reverse", "light",
    "obstruction", "remote", "boot", "no_receiver", "single_ch",
]

GROUP_NAMES = {
    "baseline":     "Baseline Idle States",
    "travel":       "Door Travel (Full Open/Close)",
    "stop_reverse": "Stop & Reverse Mid-Travel",
    "light":        "Light Control (Wall Button)",
    "obstruction":  "Obstruction Detection",
    "remote":       "Remote (Wireless Receiver) Commands",
    "boot":         "Boot / Power-On Sequence",
    "no_receiver":  "Receiver Disconnected Tests",
    "single_ch":    "Early Single-Channel Captures",
}


# ====================================================================
#  DATA STRUCTURES
# ====================================================================

@dataclass
class Message:
    """A single decoded protocol message."""
    time: float
    channel: int              # 0=CH0/Z3, 1=CH1/Z4
    symbols: list             # full quantized symbol array
    name: str                 # e.g. "CMD-A", "TYPE-B", "BEACON"
    description: str          # human-readable explanation
    category: str             # COMMAND, ACK, STATUS, FULL_STATUS, BEACON, HANDSHAKE, UNKNOWN
    header: list = field(default_factory=list)
    payload: list = field(default_factory=list)
    state: Optional[dict] = None   # decoded state dict (TYPE-B only)


@dataclass
class CaptureAnalysis:
    """Complete analysis of one capture file."""
    filepath: str
    filename: str
    description: str
    group: str
    duration: float
    columns: int              # 2 or 3
    messages: List[Message]   # all messages, chronological
    ch0_count: int
    ch1_count: int
    carrier_blocks: int
    pwm_unit_stats: Optional[dict] = None


# ====================================================================
#  CORE PARSING & DECODING
# ====================================================================

def parse_capture(filepath):
    """Parse a logic analyzer CSV into per-channel transition lists.

    Auto-detects 2-column (single channel) vs 3-column (dual channel) format.
    Returns: (channels_dict, column_count)
        channels_dict: {0: [(t, val), ...], 1: [(t, val), ...]}
        column_count: 2 or 3
    """
    channels = {0: [], 1: []}
    prev = {0: None, 1: None}
    col_count = 3
    ch_map = {0: 0, 1: 1}  # column index -> channel number

    with open(filepath) as f:
        header = f.readline().strip()
        # Detect format from header
        if "Channel 0" in header and "Channel 1" in header:
            col_count = 3
        elif "Channel 0" in header:
            col_count = 2
            ch_map = {0: 0}
        elif "Channel 1" in header:
            col_count = 2
            ch_map = {0: 1}  # single column maps to channel 1
        else:
            col_count = 3  # fallback

        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            t = float(parts[0].strip())
            if col_count == 3 and len(parts) >= 3:
                vals = {0: int(parts[1].strip()), 1: int(parts[2].strip())}
                for ch in [0, 1]:
                    if prev[ch] is None or vals[ch] != prev[ch]:
                        channels[ch].append((t, vals[ch]))
                        prev[ch] = vals[ch]
            elif col_count == 2 and len(parts) >= 2:
                val = int(parts[1].strip())
                ch = ch_map[0]
                if prev[ch] is None or val != prev[ch]:
                    channels[ch].append((t, val))
                    prev[ch] = val

    return channels, col_count


def find_bursts(transitions, gap_threshold=BURST_GAP_S):
    """Split transitions into bursts separated by idle gaps > threshold."""
    if len(transitions) < 2:
        return []
    bursts = []
    current = [transitions[0]]
    for i in range(1, len(transitions)):
        gap = transitions[i][0] - transitions[i-1][0]
        if gap > gap_threshold:
            bursts.append(current)
            current = []
        current.append(transitions[i])
    if current:
        bursts.append(current)
    return bursts


def burst_pulses(burst):
    """Extract (state, duration_us) pairs from a burst's transitions."""
    pulses = []
    for i in range(1, len(burst)):
        state = burst[i-1][1]
        dur_us = (burst[i][0] - burst[i-1][0]) * 1e6
        pulses.append((state, round(dur_us, 1)))
    return pulses


def classify_burst(burst):
    """Classify a burst as 'data', 'carrier', or 'short'."""
    if len(burst) < 5:
        return "short"
    pulses = burst_pulses(burst)
    low_durations = [d for s, d in pulses if s == 0]
    if not low_durations:
        return "short"
    spread = max(low_durations) - min(low_durations)
    if spread > 50:
        return "data"
    if len(burst) > 20:
        return "carrier"
    return "data"


def decode_pwm(burst, unit=PWM_UNIT_US):
    """Decode a PWM data burst into quantized integer symbols.

    Returns: (symbols_list, raw_low_durations_us)
    """
    pulses = burst_pulses(burst)
    low_us = [d for s, d in pulses if s == 0]
    symbols = [round(d / unit) for d in low_us]
    return symbols, low_us


def measure_pwm_unit(burst):
    """Measure the actual HIGH pulse widths in a data burst to verify PWM unit."""
    pulses = burst_pulses(burst)
    high_us = [d for s, d in pulses if s == 1]
    if not high_us:
        return None
    return {
        "mean": sum(high_us) / len(high_us),
        "min": min(high_us),
        "max": max(high_us),
        "count": len(high_us),
    }


def burst_to_lh_pairs(burst):
    """Convert burst transitions to (L_units, H_units) duration pairs.

    Both LOW and HIGH durations carry data in the Type B position field.
    Each pair represents one symbol period:
      L = LOW duration in 26us units (the traditional "symbol value")
      H = HIGH duration in 26us units (also encodes data)

    Returns list of (L, H) tuples.
    """
    segs = []
    for i in range(1, len(burst)):
        state = burst[i-1][1]
        dur_us = (burst[i][0] - burst[i-1][0]) * 1e6
        segs.append((state, round(dur_us / PWM_UNIT_US)))
    pairs = []
    j = 0
    while j < len(segs):
        if segs[j][0] == 0:  # LOW segment
            l = segs[j][1]
            h = segs[j+1][1] if j+1 < len(segs) and segs[j+1][0] == 1 else 0
            pairs.append((l, h))
            j += 2 if h > 0 else 1
        else:
            j += 1
    return pairs


def decode_position_binary(data_pairs):
    """Decode binary position from (L,H) pairs using active-low LSB-first encoding.

    Encoding method:
      - Each (L,H) pair contributes to a bitstream.
      - L time units at LOW level -> binary 1 (active-low: LOW = asserted)
      - H time units at HIGH level -> binary 0
      - Read LSB-first: first time unit = bit 0

    Returns: (value, num_bits) or (None, 0) if no valid data.
    """
    bits = []
    for l, h in data_pairs:
        if h > CROSSTALK_THRESH:
            continue  # Skip crosstalk-corrupted pairs
        bits.extend([1] * l)   # LOW = 1 (active-low)
        if h > 0:
            bits.extend([0] * h)  # HIGH = 0

    if not bits:
        return None, 0

    value = sum(bit << i for i, bit in enumerate(bits))
    return value, len(bits)


def decode_type_b_position(payload_pairs):
    """Decode position from Type B payload (L,H) pairs.

    Position field structure (from payload index 5 onward):
      prefix:    position encoding prefix in L values (1,7 or 9)
      data_A:    first binary region (redundant verification counter)
      delimiter: structural marker (L-only: 7,9 or 9,9)
      data_B:    second binary region (position counter, 9-bit mod 512)

    data_B is the primary position counter. data_A = data_B + constant
    within each delimiter phase (provides redundancy/error checking).

    Returns dict with position fields.
    """
    result = {
        "position": None,
        "position_a": None,
        "position_bits": 0,
        "position_prefix": None,
        "position_delimiter": None,
    }

    if len(payload_pairs) <= 5:
        return result

    pos_pairs = payload_pairs[5:]
    pos_l = [l for l, h in pos_pairs]

    # Detect prefix (position encoding prefix in L values)
    if len(pos_l) >= 2 and pos_l[0] == 1 and pos_l[1] == 7:
        prefix = "1,7"
        data_start = 2
    elif len(pos_l) >= 1 and pos_l[0] == 9:
        prefix = "9"
        data_start = 1
    else:
        prefix = None
        data_start = 0

    result["position_prefix"] = prefix

    # Find delimiter (7,9 or 9,9) in L-only values
    delim_idx = None
    delim_type = None
    for i in range(data_start, len(pos_l) - 1):
        if (pos_l[i] == 7 and pos_l[i+1] == 9) or \
           (pos_l[i] == 9 and pos_l[i+1] == 9):
            delim_idx = i
            delim_type = f"{pos_l[i]},{pos_l[i+1]}"
            break

    result["position_delimiter"] = delim_type

    if delim_idx is None:
        # No delimiter — transitional/endpoint message, can't decode position
        return result

    # Split into data_A (before delimiter) and data_B (after delimiter)
    a_pairs = pos_pairs[data_start:delim_idx]
    b_pairs = pos_pairs[delim_idx + 2:]  # skip 2 delimiter pairs

    # Decode each region as binary (active-low, LSB-first)
    if a_pairs:
        a_val, _ = decode_position_binary(a_pairs)
        result["position_a"] = a_val

    if b_pairs:
        b_val, b_bits = decode_position_binary(b_pairs)
        result["position"] = b_val
        result["position_bits"] = b_bits

    return result


# ====================================================================
#  MESSAGE CLASSIFICATION
# ====================================================================

def classify_ch0(symbols):
    """Classify a CH0 (Z3, receiver->opener) message.

    Returns: (name, description, category, header_len)
    """
    key = tuple(symbols)

    # Exact match first
    if key in CH0_COMMANDS:
        name, desc = CH0_COMMANDS[key]
        cat = "COMMAND"
        return name, desc, cat, len(symbols)

    # Prefix match
    for prefix, name, desc in CH0_PREFIXES:
        if len(key) >= len(prefix) and key[:len(prefix)] == prefix:
            return name, desc, "COMMAND", len(prefix)

    return "CH0-UNKNOWN", f"Unrecognized CH0 message ({len(symbols)} symbols)", "UNKNOWN", 0


def classify_ch1(symbols):
    """Classify a CH1 (Z4, opener->receiver) message.

    Returns: (name, description, category, header_len)
    """
    key = tuple(symbols)

    # Exact match first
    if key in CH1_RESPONSES:
        name, desc = CH1_RESPONSES[key]
        cat = "ACK"
        return name, desc, cat, len(symbols)

    # Prefix match
    for prefix, name, desc in CH1_PREFIXES:
        if len(key) >= len(prefix) and key[:len(prefix)] == prefix:
            cat = {
                "TYPE-B": "STATUS",
                "TYPE-C": "FULL_STATUS",
                "BEACON": "BEACON",
                "ECHO": "ECHO",
            }.get(name, "HANDSHAKE" if "HANDSHAKE" in name or "BOOT" in name else "UNKNOWN")
            return name, desc, cat, len(prefix)

    return "CH1-UNKNOWN", f"Unrecognized CH1 message ({len(symbols)} symbols)", "UNKNOWN", 0


def decode_type_b_state(payload):
    """Decode a Type B payload (after the 8-symbol header) into state fields.

    Returns dict with keys: door, door_desc, sub_state, light,
                            position, position_raw, raw_payload
    """
    result = {
        "raw_payload": list(payload),
        "door": None,
        "door_desc": None,
        "sub_state": None,
        "light": None,
        "position_raw": None,
        "position": None,
        "position_a": None,
        "position_bits": 0,
        "position_prefix": None,
        "position_delimiter": None,
    }

    if len(payload) < 2:
        return result

    # Door state from positions 0-1
    door_key = tuple(payload[0:2])
    door_state = DOOR_STATE_MAP.get(door_key)
    if door_state:
        result["door"] = door_state
        result["door_desc"] = DOOR_STATE_DESC.get(door_state, door_state)
    else:
        result["door"] = f"UNKNOWN({payload[0]},{payload[1]})"

    # Sub-state from positions 2-4
    if len(payload) >= 5:
        sub_key = tuple(payload[2:5])
        result["sub_state"] = SUB_STATE_MAP.get(sub_key, f"({payload[2]},{payload[3]},{payload[4]})")

    # Light state: check positions 1-4 (only meaningful when door closed)
    if len(payload) >= 5 and door_state in ("IDLE_CLOSED", "ARRIVED_CLOSED", None):
        light_key = tuple(payload[1:5])
        light = LIGHT_PATTERNS.get(light_key)
        if light:
            result["light"] = light
            # Refine door state for light-on case
            if light == "ON" and door_state == "ARRIVED_CLOSED":
                sub = result.get("sub_state")
                if sub == "SETTLED":
                    result["door"] = "IDLE_CLOSED"
                    result["door_desc"] = "Door closed (idle), light on"

    # Positions 5+ are the position encoding field (decoded separately
    # by decode_type_b_position using full L,H pairs from the waveform).
    # Store raw L-only symbols for reference.
    if len(payload) >= 8:
        result["position_raw"] = list(payload[5:])

    return result


def make_message(time, channel, burst):
    """Create a fully classified Message from a burst on the given channel."""
    symbols, _ = decode_pwm(burst)

    if channel == 0:
        name, desc, cat, hdr_len = classify_ch0(symbols)
    else:
        name, desc, cat, hdr_len = classify_ch1(symbols)

    header = symbols[:hdr_len]
    payload = symbols[hdr_len:]

    state = None
    if name == "TYPE-B" and len(symbols) > TYPE_B_HEADER_LEN:
        state = decode_type_b_state(symbols[TYPE_B_HEADER_LEN:])
        # Decode position using full (L,H) pair encoding
        pairs = burst_to_lh_pairs(burst)
        if len(pairs) > TYPE_B_HEADER_LEN:
            pos_info = decode_type_b_position(pairs[TYPE_B_HEADER_LEN:])
            state.update(pos_info)

    return Message(
        time=time,
        channel=channel,
        symbols=symbols,
        name=name,
        description=desc,
        category=cat,
        header=header,
        payload=payload,
        state=state,
    )


# ====================================================================
#  CAPTURE ANALYSIS
# ====================================================================

def analyze_capture(filepath):
    """Perform complete analysis of a capture file.

    Returns a CaptureAnalysis with all messages classified and decoded.
    """
    filename = os.path.basename(filepath)
    meta = TEST_FILES.get(filename, {"group": "unknown", "desc": filename})

    channels, col_count = parse_capture(filepath)

    # Compute duration
    duration = 0.0
    for ch in channels.values():
        if ch:
            duration = max(duration, ch[-1][0])

    messages = []
    carrier_count = 0
    pwm_stats = {"high_us": [], "low_us_per_symbol": {}}

    for ch_num in [0, 1]:
        if not channels[ch_num]:
            continue
        bursts = find_bursts(channels[ch_num])
        for burst in bursts:
            btype = classify_burst(burst)
            if btype == "data":
                msg = make_message(burst[0][0], ch_num, burst)
                messages.append(msg)
                # Collect PWM statistics
                stats = measure_pwm_unit(burst)
                if stats:
                    pwm_stats["high_us"].extend([stats["mean"]])
                syms, raw = decode_pwm(burst)
                for s, r in zip(syms, raw):
                    if s not in pwm_stats["low_us_per_symbol"]:
                        pwm_stats["low_us_per_symbol"][s] = []
                    pwm_stats["low_us_per_symbol"][s].append(r)
            elif btype == "carrier":
                carrier_count += 1

    messages.sort(key=lambda m: m.time)

    ch0_msgs = [m for m in messages if m.channel == 0]
    ch1_msgs = [m for m in messages if m.channel == 1]

    return CaptureAnalysis(
        filepath=filepath,
        filename=filename,
        description=meta["desc"],
        group=meta["group"],
        duration=duration,
        columns=col_count,
        messages=messages,
        ch0_count=len(ch0_msgs),
        ch1_count=len(ch1_msgs),
        carrier_blocks=carrier_count,
        pwm_unit_stats=pwm_stats,
    )


# ====================================================================
#  OUTPUT FORMATTING
# ====================================================================

def format_state(state):
    """Format a Type B decoded state dict as a concise string."""
    if not state:
        return ""
    parts = []
    if state.get("door"):
        parts.append(state["door"])
    if state.get("sub_state") and state["sub_state"] not in ("ACTIVE", "SETTLED"):
        parts.append(state["sub_state"])
    if state.get("light"):
        parts.append(f"light={state['light']}")
    if state.get("position") is not None:
        parts.append(f"pos={state['position']}")
    elif state.get("position_raw"):
        parts.append(f"pos_raw={state['position_raw']}")
    return " | ".join(parts)


def format_symbols(symbols, max_len=60):
    """Format a symbol list, truncating if very long."""
    s = str(symbols)
    if len(s) > max_len:
        return s[:max_len-3] + "..."
    return s


def ch_label(ch):
    """Return channel label string."""
    return "Z3/CH0" if ch == 0 else "Z4/CH1"


def print_file_analysis(analysis, raw=False):
    """Print detailed analysis of a single capture file."""
    a = analysis
    print(f"\n{'='*78}")
    print(f"  {a.filename}")
    print(f"  {a.description}")
    print(f"{'='*78}")
    print(f"  Duration: {a.duration:.3f}s | Format: {a.columns}-column | "
          f"Messages: {len(a.messages)} (CH0={a.ch0_count}, CH1={a.ch1_count}) | "
          f"Carrier blocks: {a.carrier_blocks}")

    if not a.messages:
        print("  (no decoded messages)")
        return

    # -- Message type summary --
    print(f"\n  --- Message Summary ---")
    ch0_types = Counter(m.name for m in a.messages if m.channel == 0)
    ch1_types = Counter(m.name for m in a.messages if m.channel == 1)

    if ch0_types:
        print(f"  CH0 (Z3, receiver->opener):")
        for name, count in ch0_types.most_common():
            desc = next((m.description for m in a.messages if m.name == name and m.channel == 0), "")
            print(f"    {count:3d}x {name:14s}  {desc}")
    else:
        print(f"  CH0 (Z3): no messages")

    if ch1_types:
        print(f"  CH1 (Z4, opener->receiver):")
        for name, count in ch1_types.most_common():
            desc = next((m.description for m in a.messages if m.name == name and m.channel == 1), "")
            print(f"    {count:3d}x {name:14s}  {desc}")
    else:
        print(f"  CH1 (Z4): no messages")

    # -- Timeline --
    print(f"\n  --- Timeline ({len(a.messages)} messages) ---")
    print(f"  {'Time':>8s}  {'Ch':6s}  {'Name':14s}  {'Detail'}")
    print(f"  {'----':>8s}  {'--':6s}  {'----':14s}  {'------'}")

    prev_type_b_state = None
    for msg in a.messages:
        ch = ch_label(msg.channel)
        if raw:
            detail = format_symbols(msg.symbols, 80)
        elif msg.state:
            state_str = format_state(msg.state)
            # Mark state changes
            marker = ""
            if prev_type_b_state is not None:
                if msg.state.get("door") != prev_type_b_state.get("door"):
                    marker = " ** STATE CHANGE **"
                elif msg.state.get("light") != prev_type_b_state.get("light"):
                    marker = " ** LIGHT CHANGE **"
            detail = f"{state_str}{marker}"
            prev_type_b_state = msg.state
        elif msg.payload:
            detail = format_symbols(msg.payload, 70)
        else:
            detail = ""
        print(f"  {msg.time:8.3f}s  {ch:6s}  {msg.name:14s}  {detail}")

    # -- Type B State Evolution --
    type_b_msgs = [m for m in a.messages if m.name == "TYPE-B" and m.state]
    if type_b_msgs and not raw:
        print(f"\n  --- Type B State Evolution ({len(type_b_msgs)} snapshots) ---")
        prev = None
        for msg in type_b_msgs:
            s = msg.state
            changed = []
            if prev:
                for k in ["door", "sub_state", "light"]:
                    if s.get(k) != prev.get(k) and (s.get(k) is not None or prev.get(k) is not None):
                        changed.append(f"{k}: {prev.get(k)} -> {s.get(k)}")
            change_str = f"  CHANGED: {', '.join(changed)}" if changed else ""
            print(f"  {msg.time:8.3f}s  {format_state(s)}{change_str}")
            prev = s

        # Position analysis: which payload positions vary?
        payloads = [m.state["raw_payload"] for m in type_b_msgs if m.state.get("raw_payload")]
        if payloads:
            max_len = max(len(p) for p in payloads)
            varying = []
            for pos in range(max_len):
                vals = set(p[pos] for p in payloads if pos < len(p))
                if len(vals) > 1:
                    varying.append((pos, sorted(vals)))
            if varying:
                print(f"\n  Payload positions that vary (0-indexed from after header):")
                for pos, vals in varying:
                    print(f"    pos {pos:2d}: {len(vals)} values: {vals}")

        # Position counter summary (decoded binary positions)
        pos_msgs = [(m.time, m.state.get("position"), m.state.get("door"))
                    for m in type_b_msgs if m.state.get("position") is not None]
        if pos_msgs:
            pos_values = [p for _, p, _ in pos_msgs]
            print(f"\n  Position counter (binary-decoded from active-low LSB-first waveform):")
            print(f"    Decoded values: {len(pos_values)} readings, range {min(pos_values)}-{max(pos_values)}")
            # Show first/last few
            if len(pos_values) > 6:
                print(f"    First 3: {pos_values[:3]}")
                print(f"    Last  3: {pos_values[-3:]}")
            else:
                print(f"    Values: {pos_values}")


# ====================================================================
#  SPEC GENERATOR
# ====================================================================

def print_spec(analyses):
    """Generate a complete protocol reference from all analyzed captures.

    Args:
        analyses: dict mapping filename -> CaptureAnalysis
    """
    print("=" * 78)
    print("  OVERHEAD DOOR ODYSSEY 1000 (MODEL 7030) - PROTOCOL SPECIFICATION")
    print("  Auto-generated from logic analyzer captures")
    print("=" * 78)

    # ---- Section 1: Physical Layer ----
    print(f"\n{'='*78}")
    print("  SECTION 1: PHYSICAL LAYER")
    print(f"{'='*78}")
    print(f"""
  Interface: 4-pin header for wireless receiver module
    Pin 1: GND
    Pin 2: Z3 - {WIRE_ROLES['Z3']}
    Pin 3: Z4 - {WIRE_ROLES['Z4']}
    Pin 4: 3.3V power supply

  Voltage: 3.3V logic (confirmed by multimeter)
  Idle state: both lines HIGH (1)
  Unpowered: both lines LOW (0)

  PWM Encoding:
    Each symbol period: LOW gap + HIGH separator, both quantized to ~{PWM_UNIT_US} us.
    LOW duration encodes primary symbol value (1-9).
    HIGH duration encodes secondary data using same alphabet {{1-7,9}} (no 8).
    In header/status fields, HIGH is always 1 unit (separator only).
    In position fields, HIGH varies and carries binary position data.
    Nominal base unit: {PWM_UNIT_US} us""")

    # Compute actual PWM stats across all captures
    all_high = []
    all_low_by_sym = {}
    for a in analyses.values():
        if a.pwm_unit_stats:
            all_high.extend(a.pwm_unit_stats.get("high_us", []))
            for sym, vals in a.pwm_unit_stats.get("low_us_per_symbol", {}).items():
                if sym not in all_low_by_sym:
                    all_low_by_sym[sym] = []
                all_low_by_sym[sym].extend(vals)

    if all_high:
        print(f"\n  Measured HIGH pulse width (separator):")
        print(f"    Mean: {sum(all_high)/len(all_high):.1f} us  "
              f"Range: [{min(all_high):.1f}, {max(all_high):.1f}] us  "
              f"(N={len(all_high)} bursts)")

    if all_low_by_sym:
        print(f"\n  Measured LOW gap width by symbol value:")
        print(f"    {'Sym':>4s}  {'Expected':>10s}  {'Mean':>8s}  {'Min':>8s}  {'Max':>8s}  {'N':>6s}")
        for sym in sorted(all_low_by_sym.keys()):
            vals = all_low_by_sym[sym]
            if len(vals) > 0:
                expected = sym * PWM_UNIT_US
                mean = sum(vals) / len(vals)
                print(f"    {sym:4d}  {expected:10.1f}  {mean:8.1f}  {min(vals):8.1f}  {max(vals):8.1f}  {len(vals):6d}")

    print(f"""
  Carrier Tone:
    Frequency: ~{CARRIER_FREQ_HZ} Hz
    Pulses per block: {CARRIER_PULSES}
    Duty cycle: ~{CARRIER_DUTY*100:.0f}%
    Purpose: Accompanies some CH0 command transmissions

  Burst Separation:
    Messages are separated by >{BURST_GAP_S*1000:.0f}ms idle-HIGH gaps.
    Bursts with <5 transitions are noise/glitches (ignored).""")

    # ---- Section 2: Message Catalog ----
    print(f"\n{'='*78}")
    print("  SECTION 2: MESSAGE CATALOG")
    print(f"{'='*78}")

    # Collect all messages from all files
    all_msgs = []
    for fname, a in analyses.items():
        for m in a.messages:
            all_msgs.append((fname, m))

    # CH0 commands
    print(f"\n  --- CH0 (Z3): Receiver -> Opener Commands ---")
    ch0_by_name = {}
    for fname, m in all_msgs:
        if m.channel == 0:
            if m.name not in ch0_by_name:
                ch0_by_name[m.name] = {"count": 0, "files": set(), "example": m, "variants": set()}
            ch0_by_name[m.name]["count"] += 1
            ch0_by_name[m.name]["files"].add(fname)
            ch0_by_name[m.name]["variants"].add(tuple(m.symbols))

    for name in sorted(ch0_by_name.keys()):
        info = ch0_by_name[name]
        ex = info["example"]
        print(f"\n  {name}: {ex.description}")
        print(f"    Occurrences: {info['count']} across {len(info['files'])} file(s)")
        print(f"    Files: {', '.join(sorted(info['files']))}")
        if len(info["variants"]) <= 3:
            for v in sorted(info["variants"], key=len):
                print(f"    Pattern: {list(v)} ({len(v)} symbols)")
        else:
            print(f"    {len(info['variants'])} distinct patterns (prefix match)")
            for v in sorted(info["variants"], key=len)[:3]:
                print(f"    Example: {list(v)} ({len(v)} symbols)")

    # CH1 responses
    print(f"\n  --- CH1 (Z4): Opener -> Receiver Responses ---")
    ch1_by_name = {}
    for fname, m in all_msgs:
        if m.channel == 1:
            if m.name not in ch1_by_name:
                ch1_by_name[m.name] = {"count": 0, "files": set(), "example": m, "variants": set()}
            ch1_by_name[m.name]["count"] += 1
            ch1_by_name[m.name]["files"].add(fname)
            if m.name not in ("TYPE-B", "TYPE-C"):  # too many variants for these
                ch1_by_name[m.name]["variants"].add(tuple(m.symbols))

    for name in sorted(ch1_by_name.keys()):
        info = ch1_by_name[name]
        ex = info["example"]
        print(f"\n  {name}: {ex.description}")
        print(f"    Occurrences: {info['count']} across {len(info['files'])} file(s)")
        print(f"    Files: {', '.join(sorted(info['files']))}")
        if info["variants"]:
            if len(info["variants"]) <= 5:
                for v in sorted(info["variants"], key=len):
                    print(f"    Pattern: {list(v)} ({len(v)} symbols)")
            else:
                print(f"    {len(info['variants'])} distinct patterns")
                for v in sorted(info["variants"], key=len)[:3]:
                    print(f"    Example: {list(v)} ({len(v)} symbols)")

    # ---- Section 3: State Encoding ----
    print(f"\n{'='*78}")
    print("  SECTION 3: TYPE B STATUS MESSAGE - STATE ENCODING")
    print(f"{'='*78}")

    print(f"""
  Type B messages carry real-time door/light/position state.
  Header: {list(TYPE_B_HEADER)} (constant, 8 symbols)
  Payload follows immediately after header.

  Payload Position Map (0-indexed from after header):
    Pos 0-1:  Door/motor state
    Pos 2-4:  Sub-state (motion/obstruction)
    Pos 1-4:  Light state (when door closed, overlaps with pos 0-1)
    Pos 5-6:  Position field prefix (1,7 = standard, 9 = variant)
    Pos 7+:   Position counter (binary encoded via active-low waveform)
""")

    # Collect all Type B payloads
    all_type_b = []
    for fname, m in all_msgs:
        if m.name == "TYPE-B" and m.state:
            all_type_b.append((fname, m))

    print(f"  Door State Values (pos 0-1):")
    print(f"    {'Values':12s}  {'State':26s}  {'Seen in'}")
    print(f"    {'------':12s}  {'-----':26s}  {'-------'}")
    door_files = {}
    for fname, m in all_type_b:
        p = m.state["raw_payload"]
        if len(p) >= 2:
            key = (p[0], p[1])
            if key not in door_files:
                door_files[key] = set()
            door_files[key].add(fname)
    for key in sorted(door_files.keys()):
        state = DOOR_STATE_MAP.get(key, "UNKNOWN")
        files = door_files[key]
        file_list = ", ".join(sorted(f.replace(".txt", "") for f in files))
        print(f"    [{key[0]},{key[1]}]       {state:26s}  {file_list}")

    print(f"\n  Sub-State Values (pos 2-4):")
    sub_files = {}
    for fname, m in all_type_b:
        p = m.state["raw_payload"]
        if len(p) >= 5:
            key = (p[2], p[3], p[4])
            if key not in sub_files:
                sub_files[key] = set()
            sub_files[key].add(fname)
    for key in sorted(sub_files.keys()):
        state = SUB_STATE_MAP.get(key, "UNKNOWN")
        files = sub_files[key]
        file_list = ", ".join(sorted(f.replace(".txt", "") for f in files))
        print(f"    [{key[0]},{key[1]},{key[2]}]     {state:16s}  {file_list}")

    print(f"\n  Light State (pos 1-4, when door closed):")
    for pattern, state in LIGHT_PATTERNS.items():
        print(f"    {list(pattern)} = {state}")

    print(f"\n  Position Field Prefix (pos 5-6):")
    print(f"    [1, 7] = standard prefix (both opening and closing)")
    print(f"    [9, X] = short prefix variant (early/late in travel)")
    print(f"    Direction is determined by door state (pos 0-1), not this prefix.")

    # Position counter analysis
    print(f"\n  Position Counter (binary-decoded):")
    print(f"    Encoding: active-low, LSB-first binary waveform.")
    print(f"    Each (L,H) pair contributes L one-bits then H zero-bits to a bitstream.")
    print(f"    Both L and H use alphabet {{1,2,3,4,5,6,7,9}} — no symbol 8 in either.")
    print(f"    H values >10 are CH0 carrier crosstalk artifacts (filtered out).")
    print(f"")
    print(f"    Structure (from payload pos 5 onward):")
    print(f"      prefix:    position encoding prefix in L values (1,7 or 9)")
    print(f"      data_A:    redundant verification counter (binary encoded)")
    print(f"      delimiter: structural marker in L values (7,9 or 9,9)")
    print(f"      data_B:    position counter (binary encoded, 9-bit, wraps mod 512)")
    print(f"")
    print(f"    data_B is the primary position counter.")
    print(f"    data_A = data_B + constant within each delimiter phase (redundancy).")
    print(f"    Counter increases during OPENING, decreases during CLOSING.")
    print(f"    Full travel range: ~890 counts (~30 counts per 0.5s update).")
    print(f"    Freezes when door stops. Resumes from same value on restart.")

    # Collect position ranges per file
    pos_by_file = {}
    for fname, m in all_type_b:
        p = m.state.get("position")
        if p is not None:
            if fname not in pos_by_file:
                pos_by_file[fname] = []
            pos_by_file[fname].append(p)
    if pos_by_file:
        print(f"\n    Position counter values by file:")
        print(f"      {'File':<42s} {'Count':>5s}  {'Min':>5s}  {'Max':>5s}  {'Range':>5s}")
        for fname in sorted(pos_by_file.keys()):
            vals = pos_by_file[fname]
            rng = max(vals) - min(vals)
            print(f"      {fname:<42s} {len(vals):>5d}  {min(vals):>5d}  {max(vals):>5d}  {rng:>5d}")

    # ---- Section 4: Boot Sequence ----
    print(f"\n{'='*78}")
    print("  SECTION 4: BOOT / POWER-ON SEQUENCE")
    print(f"{'='*78}")

    boot_analysis = analyses.get("B1_Boot sequence.txt")
    if boot_analysis:
        print(f"""
  Captured from cold power-on. Both lines start LOW (0).
  Duration: {boot_analysis.duration:.1f}s

  Phase 1 - Beacon (0.4s - 6.5s):
    Opener polls Z4 with BEACON every ~2.0s, waiting for receiver.
    Z3 is silent. Beacon stops once receiver responds.

  Phase 2 - Init (~6.8s):
    Receiver sends CMD-INIT [0,0,0,0,0,3] on Z3.

  Phase 3 - Handshake (~7.8s - 8.1s):
    Receiver sends two CMD-B-INIT config messages on Z3.
    Opener responds with ACKs + HANDSHAKE-D + HANDSHAKE-E on Z4.
    Receiver sends CMD-ECHO.

  Phase 4 - First Keepalive (~12.9s):
    Receiver sends CMD-A1 (transitional keepalive variant) on Z3.
    Opener responds with ACK + TYPE-B status + BOOT-F on Z4.

  Phase 5 - Steady State (~17.9s+):
    Normal operation: CMD-A every ~5s on Z3.
    Opener responds with ACK + TYPE-B + TYPE-C triplet on Z4.

  Boot messages in order:""")
        for msg in boot_analysis.messages:
            ch = ch_label(msg.channel)
            syms = format_symbols(msg.symbols, 60)
            print(f"    {msg.time:8.3f}s  {ch:6s}  {msg.name:14s}  {syms}")
    else:
        print("\n  (B1_Boot sequence.txt not found)")

    # ---- Section 5: Communication Patterns ----
    print(f"\n{'='*78}")
    print("  SECTION 5: COMMUNICATION PATTERNS")
    print(f"{'='*78}")

    # Keepalive timing
    all_cmd_a_intervals = []
    for a in analyses.values():
        cmd_a_times = [m.time for m in a.messages if m.name == "CMD-A"]
        for i in range(1, len(cmd_a_times)):
            all_cmd_a_intervals.append(cmd_a_times[i] - cmd_a_times[i-1])

    if all_cmd_a_intervals:
        avg = sum(all_cmd_a_intervals) / len(all_cmd_a_intervals)
        print(f"\n  Keepalive (CMD-A) Interval:")
        print(f"    Mean: {avg:.3f}s  Range: [{min(all_cmd_a_intervals):.3f}s, "
              f"{max(all_cmd_a_intervals):.3f}s]  (N={len(all_cmd_a_intervals)})")

    # Beacon timing
    all_beacon_intervals = []
    for a in analyses.values():
        beacon_times = [m.time for m in a.messages if m.name == "BEACON"]
        for i in range(1, len(beacon_times)):
            all_beacon_intervals.append(beacon_times[i] - beacon_times[i-1])
    if all_beacon_intervals:
        avg = sum(all_beacon_intervals) / len(all_beacon_intervals)
        print(f"\n  Beacon Interval (no receiver):")
        print(f"    Mean: {avg:.3f}s  Range: [{min(all_beacon_intervals):.3f}s, "
              f"{max(all_beacon_intervals):.3f}s]  (N={len(all_beacon_intervals)})")

    # ACK response timing
    print(f"\n  Request-Response Pattern:")
    print(f"    After each CH0 command, opener responds on CH1 within ~50ms.")
    print(f"    Normal cycle: CMD-A -> ACK-A -> TYPE-B -> TYPE-C (~100ms total)")
    print(f"    During motion: TYPE-B updates every ~100ms with changing position counter.")

    # Who sends what
    print(f"""
  Communication Roles:
    - Receiver (Z3) is the MASTER: initiates boot, sends keepalives.
    - Opener (Z4) is the RESPONDER: sends ACKs and status only when polled.
    - Without a receiver: opener sends BEACON on Z4 every ~2s indefinitely.
      No CMD-A, no TYPE-B, no TYPE-C. Z3 is completely silent.""")

    # ---- Section 6: Test Matrix ----
    print(f"\n{'='*78}")
    print("  SECTION 6: TEST CAPTURE MATRIX")
    print(f"{'='*78}")

    # Collect all message type names
    all_names = set()
    for a in analyses.values():
        for m in a.messages:
            all_names.add(m.name)
    all_names = sorted(all_names)

    # Short names for column headers
    print(f"\n  {'File':<40s}", end="")
    for nm in all_names:
        print(f" {nm[:7]:>7s}", end="")
    print()
    print(f"  {'-'*40}", end="")
    for _ in all_names:
        print(f" {'---':>7s}", end="")
    print()

    for group in GROUP_ORDER:
        group_files = [(f, a) for f, a in analyses.items()
                       if a.group == group]
        if not group_files:
            continue
        for fname, a in sorted(group_files):
            short = fname.replace(".txt", "")[:38]
            print(f"  {short:<40s}", end="")
            name_counts = Counter(m.name for m in a.messages)
            for nm in all_names:
                c = name_counts.get(nm, 0)
                if c > 0:
                    print(f" {c:>7d}", end="")
                else:
                    print(f" {'':>7s}", end="")
            print()

    # ---- Section 7: Unknowns ----
    print(f"\n{'='*78}")
    print("  SECTION 7: UNRECOGNIZED / UNKNOWN MESSAGES")
    print(f"{'='*78}")

    unknowns = [(fname, m) for fname, m in all_msgs
                if "UNKNOWN" in m.name or "?" in m.name]
    if unknowns:
        print(f"\n  {len(unknowns)} unrecognized message(s):")
        for fname, m in unknowns:
            ch = ch_label(m.channel)
            print(f"    {fname}  {m.time:.3f}s  {ch}  {m.name}  {m.symbols}")
    else:
        print(f"\n  All messages successfully classified!")

    # Note undecoded fields
    print(f"\n  Known undecoded fields:")
    print(f"    - Type C payload: structure beyond the 23-symbol header not analyzed.")
    print(f"    - CMD-B extended payloads: variable-length config data, purpose unclear.")


# ====================================================================
#  ALL-FILE RUNNER
# ====================================================================

def run_all(base_dir):
    """Analyze all capture files, grouped by test scenario."""
    analyses = {}

    # Discover and analyze all files
    for fname, meta in TEST_FILES.items():
        path = os.path.join(base_dir, fname)
        if os.path.exists(path):
            analyses[fname] = analyze_capture(path)

    # Also discover any files not in manifest
    for f in os.listdir(base_dir):
        if f.endswith(".txt") and f not in analyses and f not in TEST_FILES:
            path = os.path.join(base_dir, f)
            analyses[f] = analyze_capture(path)

    print("=" * 78)
    print(f"  OVERHEAD DOOR PROTOCOL ANALYSIS - {len(analyses)} capture files")
    print("=" * 78)

    for group in GROUP_ORDER:
        group_files = {f: a for f, a in analyses.items() if a.group == group}
        if not group_files:
            continue

        print(f"\n\n{'#'*78}")
        print(f"  GROUP: {GROUP_NAMES.get(group, group).upper()}")
        print(f"{'#'*78}")

        for fname in sorted(group_files.keys()):
            print_file_analysis(group_files[fname])

        # Group summary
        if len(group_files) > 1:
            print(f"\n  --- Group Summary: {GROUP_NAMES.get(group, group)} ---")
            for fname in sorted(group_files.keys()):
                a = group_files[fname]
                type_b = [m for m in a.messages if m.name == "TYPE-B" and m.state]
                states = set(m.state.get("door", "?") for m in type_b)
                lights = set(m.state.get("light") for m in type_b if m.state.get("light"))
                print(f"  {fname:<42s} states={sorted(states)}  lights={sorted(lights) if lights else 'n/a'}")

    # Handle unknown-group files
    unknown_files = {f: a for f, a in analyses.items() if a.group == "unknown"}
    if unknown_files:
        print(f"\n\n{'#'*78}")
        print(f"  GROUP: UNLISTED FILES")
        print(f"{'#'*78}")
        for fname in sorted(unknown_files.keys()):
            print_file_analysis(unknown_files[fname])

    return analyses


# ====================================================================
#  MAIN
# ====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Overhead Door Odyssey 1000 - Protocol Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze.py              Analyze all captures (default)
  python analyze.py --spec       Generate protocol specification
  python analyze.py --file test01_idle_closed.txt
  python analyze.py --raw test01_idle_closed.txt
        """,
    )
    parser.add_argument("--spec", action="store_true",
                        help="Generate protocol reference document")
    parser.add_argument("--file", type=str,
                        help="Analyze a single capture file")
    parser.add_argument("--raw", type=str,
                        help="Show raw symbols for a single file (no interpretation)")
    parser.add_argument("--dir", type=str, default=None,
                        help="Base directory for capture files (default: script directory)")
    args = parser.parse_args()

    base_dir = args.dir or os.path.dirname(os.path.abspath(__file__))

    if args.raw:
        path = args.raw if os.path.isabs(args.raw) else os.path.join(base_dir, args.raw)
        if not os.path.exists(path):
            print(f"ERROR: File not found: {path}")
            sys.exit(1)
        a = analyze_capture(path)
        print_file_analysis(a, raw=True)

    elif args.file:
        path = args.file if os.path.isabs(args.file) else os.path.join(base_dir, args.file)
        if not os.path.exists(path):
            print(f"ERROR: File not found: {path}")
            sys.exit(1)
        a = analyze_capture(path)
        print_file_analysis(a)

    elif args.spec:
        # Load all files first, then generate spec
        analyses = {}
        for fname in TEST_FILES:
            path = os.path.join(base_dir, fname)
            if os.path.exists(path):
                analyses[fname] = analyze_capture(path)
        for f in os.listdir(base_dir):
            if f.endswith(".txt") and f not in analyses:
                analyses[f] = analyze_capture(os.path.join(base_dir, f))
        print_spec(analyses)

    else:
        run_all(base_dir)


if __name__ == "__main__":
    main()
