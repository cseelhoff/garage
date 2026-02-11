"""
Position decoder — base-8 / 3-bit hypothesis.

Key discovery: symbol 8 NEVER appears (only 2 occurrences across all files,
both quantization errors). The true alphabet is {1,2,3,4,5,6,7,9} = 8 symbols.

This means each symbol encodes exactly 3 bits:
  1→000  2→001  3→010  4→011  5→100  6→101  7→110  9→111

Or equivalently, each symbol maps to an octal digit 0-7:
  1→0  2→1  3→2  4→3  5→4  6→5  7→6  9→7

This script tries every reasonable combination:
  - Which symbols are position data vs structure
  - Big-endian vs little-endian
  - Data_A and data_B as independent numbers or concatenated
  - Different split points in the payload
"""

import sys
import os
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import (parse_capture, find_bursts, classify_burst, decode_pwm,
                     TYPE_B_HEADER, TYPE_B_HEADER_LEN, DOOR_STATE_MAP)


# The mapping: symbol → octal digit (0-7)
SYM_TO_OCT = {1:0, 2:1, 3:2, 4:3, 5:4, 6:5, 7:6, 9:7}


def sym_to_bits(sym):
    """Convert symbol to 3-bit string."""
    return f"{SYM_TO_OCT[sym]:03b}"


def syms_to_int_be(syms):
    """Symbols → integer, big-endian (first symbol = most significant)."""
    val = 0
    for s in syms:
        val = val * 8 + SYM_TO_OCT[s]
    return val


def syms_to_int_le(syms):
    """Symbols → integer, little-endian (first symbol = least significant)."""
    val = 0
    for i, s in enumerate(syms):
        val += SYM_TO_OCT[s] * (8 ** i)
    return val


def syms_to_bits_be(syms):
    """Symbols → bit string, big-endian."""
    return "".join(sym_to_bits(s) for s in syms)


def extract_messages(filepath):
    """Extract Type B messages with full payload."""
    channels, _ = parse_capture(filepath)
    if not channels or not channels.get(1):
        return []
    messages = []
    for burst in find_bursts(channels[1]):
        if classify_burst(burst) != "data":
            continue
        symbols, raw_us = decode_pwm(burst)
        if len(symbols) < TYPE_B_HEADER_LEN + 7:
            continue
        if tuple(symbols[:TYPE_B_HEADER_LEN]) != TYPE_B_HEADER:
            continue
        payload = symbols[TYPE_B_HEADER_LEN:]
        payload_us = raw_us[TYPE_B_HEADER_LEN:]
        state_key = tuple(payload[0:2])
        state_name = DOOR_STATE_MAP.get(state_key, f"UNK{state_key}")
        messages.append({
            "time": burst[0][0],
            "payload": payload,
            "payload_us": payload_us,
            "state": state_name,
        })
    return messages


def check_monotonicity(values):
    """Return (score%, direction, violations)."""
    if len(values) < 2:
        return 100.0, "flat", 0
    n = len(values) - 1
    inc_v = sum(1 for i in range(1, len(values)) if values[i] < values[i-1])
    dec_v = sum(1 for i in range(1, len(values)) if values[i] > values[i-1])
    if inc_v <= dec_v:
        return (n - inc_v) / n * 100, "increasing", inc_v
    else:
        return (n - dec_v) / n * 100, "decreasing", dec_v


def analyze_file(filepath, label, direction_expected):
    """Analyze one file with every base-8 interpretation."""
    print(f"\n{'#'*120}")
    print(f"  {label}: {os.path.basename(filepath)}")
    print(f"{'#'*120}")

    messages = extract_messages(filepath)
    moving = [m for m in messages if m["state"] in ("OPENING", "CLOSING")]
    print(f"  Total: {len(messages)}, Moving: {len(moving)}")
    if len(moving) < 3:
        return

    # Show raw payloads with 3-bit annotation
    print(f"\n  RAW PAYLOADS (octal mapping: 1→0 2→1 3→2 4→3 5→4 6→5 7→6 9→7)")
    print(f"  {'Time':>8s}  {'Payload symbols':>55s}  {'Octal digits':>55s}  {'3-bit binary':>72s}")
    print(f"  {'-'*120}")
    for m in moving[:5]:
        p = m["payload"]
        oct_digits = [SYM_TO_OCT.get(s, '?') for s in p]
        bits = "".join(sym_to_bits(s) for s in p if s in SYM_TO_OCT)
        print(f"  {m['time']:8.3f}s  {str(p):>55s}  {str(oct_digits):>55s}  {bits:>72s}")
    if len(moving) > 5:
        print(f"  ... ({len(moving) - 5} more)")

    # ---- Generate all interpretations ----
    results = {}

    for m in moving:
        p = m["payload"]

        # Try many different start positions for the position field
        for start in range(5, min(8, len(p))):
            pos_field = p[start:]

            # Full field as big-endian octal
            key = f"pos{start}+_BE_full"
            results.setdefault(key, []).append(syms_to_int_be(pos_field))

            # Full field as little-endian octal
            key = f"pos{start}+_LE_full"
            results.setdefault(key, []).append(syms_to_int_le(pos_field))

            # Full field as bit string → int
            key = f"pos{start}+_bits_BE"
            bits = syms_to_bits_be(pos_field)
            results.setdefault(key, []).append(int(bits, 2))

            # Just the DATA symbols (1-6 only, skip 7 and 9) as base-6 BE
            data_only = [s for s in pos_field if s <= 6]
            if data_only:
                key = f"pos{start}+_data16_b6BE"
                val = 0
                for s in data_only:
                    val = val * 6 + (s - 1)
                results.setdefault(key, []).append(val)

                key = f"pos{start}+_data16_b6LE"
                val = 0
                for i, s in enumerate(data_only):
                    val += (s - 1) * (6 ** i)
                results.setdefault(key, []).append(val)

                # Sum of data symbols
                key = f"pos{start}+_data_sum"
                results.setdefault(key, []).append(sum(s - 1 for s in data_only))

                # Count of data symbols
                key = f"pos{start}+_data_count"
                results.setdefault(key, []).append(len(data_only))

            # Total µs from start pos
            us_field = m["payload_us"][start:]
            key = f"pos{start}+_total_us"
            results.setdefault(key, []).append(sum(us_field))

            # Total µs / 26
            key = f"pos{start}+_total_units"
            results.setdefault(key, []).append(round(sum(us_field) / 26))

            # Number of symbols in position field
            key = f"pos{start}+_nsyms"
            results.setdefault(key, []).append(len(pos_field))

        # --- Try splitting on EVERY occurrence of 7,9 and 9,9 ---
        for split_start in range(5, min(8, len(p))):
            pos_field = p[split_start:]
            for i in range(len(pos_field) - 1):
                pair = (pos_field[i], pos_field[i+1])
                if pair in ((7, 9), (9, 9)):
                    before = pos_field[:i]
                    after = pos_field[i+2:]
                    if not before or not after:
                        continue
                    pair_name = f"{pair[0]}{pair[1]}"

                    # data-only (1-6) before and after delimiter
                    db = [s for s in before if s <= 6]
                    da = [s for s in after if s <= 6]

                    if db:
                        # Before-delimiter as base-6 BE
                        key = f"p{split_start}_pre{pair_name}_b6be"
                        val = 0
                        for s in db:
                            val = val * 6 + (s - 1)
                        results.setdefault(key, []).append(val)

                    if da:
                        key = f"p{split_start}_post{pair_name}_b6be"
                        val = 0
                        for s in da:
                            val = val * 6 + (s - 1)
                        results.setdefault(key, []).append(val)

                    if db and da:
                        # Combined: before * 216 + after (base6, max 3 digits = 216)
                        vb = sum((s-1) * (6**j) for j, s in enumerate(reversed(db)))
                        va = sum((s-1) * (6**j) for j, s in enumerate(reversed(da)))
                        key = f"p{split_start}_combo{pair_name}_b6"
                        results.setdefault(key, []).append(vb * 216 + va)

                    break  # only first delimiter

        # --- Fixed-width octal: try reading exactly N symbols from various positions ---
        for start in range(5, min(10, len(p))):
            for width in range(2, min(6, len(p) - start + 1)):
                chunk = p[start:start + width]
                if all(s in SYM_TO_OCT for s in chunk):
                    key = f"oct_p{start}_w{width}_BE"
                    results.setdefault(key, []).append(syms_to_int_be(chunk))
                    key = f"oct_p{start}_w{width}_LE"
                    results.setdefault(key, []).append(syms_to_int_le(chunk))

    # ---- Score all interpretations ----
    # Only keep interpretations with the right number of values
    n_expected = len(moving)
    scored = []
    for key, values in results.items():
        if len(values) != n_expected:
            continue
        score, direction, violations = check_monotonicity(values)
        # Correct direction?
        dir_match = (direction_expected == "increasing" and direction == "increasing") or \
                    (direction_expected == "decreasing" and direction == "decreasing")
        # Value range
        vmin, vmax = min(values), max(values)
        vrange = vmax - vmin
        scored.append((score, dir_match, key, direction, violations, vmin, vmax, vrange, values))

    # Sort: best score first, prefer matching direction, prefer larger range
    scored.sort(key=lambda x: (-x[0], -x[1], -x[7]))

    # Show top 30
    print(f"\n  {'='*120}")
    print(f"  TOP INTERPRETATIONS (expected: {direction_expected})")
    print(f"  {'='*120}")
    print(f"  {'Score':>6s} {'Match':>5s}  {'Key':>35s}  {'Dir':>11s}  {'Viol':>5s}  {'Min':>10s}  {'Max':>10s}  {'Range':>10s}  First 10 values")
    print(f"  {'-'*120}")

    shown = 0
    for score, dir_match, key, direction, violations, vmin, vmax, vrange, values in scored:
        if shown >= 40:
            break
        dm = "YES" if dir_match else "no"
        val_str = str(values[:10])
        if len(values) > 10:
            val_str = val_str[:-1] + ", ...]"
        print(f"  {score:5.1f}% {dm:>5s}  {key:>35s}  {direction:>11s}  {violations:>5d}  {vmin:>10}  {vmax:>10}  {vrange:>10}  {val_str}")
        shown += 1

    # If there's a high scorer (>=85%), show full values
    if scored and scored[0][0] >= 85:
        best = scored[0]
        print(f"\n  *** BEST: {best[2]} — {best[0]:.1f}% {best[3]} ***")
        print(f"  Full values: {best[8]}")
        # Show deltas
        deltas = [best[8][i] - best[8][i-1] for i in range(1, len(best[8]))]
        print(f"  Deltas: {deltas}")

    # ---- Also show the 3-bit representation side by side for visual pattern matching ----
    print(f"\n  {'='*120}")
    print(f"  BINARY REPRESENTATION (pos 5+ as 3-bit per symbol)")
    print(f"  {'='*120}")
    for m in moving:
        p = m["payload"][5:]
        bits = "".join(sym_to_bits(s) for s in p if s in SYM_TO_OCT)
        # Add spaces every 3 bits for readability
        spaced = " ".join(sym_to_bits(s) for s in p if s in SYM_TO_OCT)
        # Mark 7s and 9s
        annotated = []
        for s in p:
            if s == 7:
                annotated.append("[7]")
            elif s == 9:
                annotated.append("[9]")
            else:
                annotated.append(f" {s} ")
        ann_str = "".join(annotated)
        print(f"  {m['time']:8.3f}s  {ann_str:>50s}  {spaced}")

    return moving


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    files = [
        ("test04_open_full.txt", "OPENING full travel", "increasing"),
        ("test05_close_full.txt", "CLOSING full travel", "decreasing"),
    ]

    for fname, label, expected_dir in files:
        fpath = os.path.join(base, fname)
        if os.path.exists(fpath):
            analyze_file(fpath, label, expected_dir)


if __name__ == "__main__":
    main()
