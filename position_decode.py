"""
Position counter decoder — targeted analysis based on delimiter structure insight.

Key discovery: The position field (from payload pos 5 onward) has TWO formats:
  Format A: 9 [data_A] 7,9 [data_B]     — "near-closed" range
  Format B: 1,7 [data_A] 9,9 [data_B]   — "near-open" range

During OPENING:  Format A → Format B (transition ~1/3 from closed end)
During CLOSING:  Format B → Format A (transition ~2/3 into travel = same physical point)

This script extracts data_A and data_B from each format and tries every reasonable
interpretation to find a monotonically changing position counter.
"""

import sys
import os

# Fix encoding for Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import (parse_capture, find_bursts, classify_burst, burst_pulses,
                     decode_pwm, TYPE_B_HEADER, TYPE_B_HEADER_LEN, PWM_UNIT_US,
                     DOOR_STATE_MAP, DIRECTION_MAP)


def extract_messages(filepath):
    """Extract Type B messages with full payload and raw µs."""
    channels, col_count = parse_capture(filepath)
    if not channels or not channels.get(1):
        return []
    bursts = find_bursts(channels[1])
    messages = []
    for burst in bursts:
        if classify_burst(burst) != "data":
            continue
        symbols, raw_us = decode_pwm(burst)
        if len(symbols) < TYPE_B_HEADER_LEN + 2:
            continue
        if tuple(symbols[:TYPE_B_HEADER_LEN]) != TYPE_B_HEADER:
            continue
        payload = symbols[TYPE_B_HEADER_LEN:]
        payload_us = raw_us[TYPE_B_HEADER_LEN:]
        # Door state from pos 0-1
        state_key = tuple(payload[0:2]) if len(payload) >= 2 else None
        state_name = DOOR_STATE_MAP.get(state_key, f"UNK{state_key}")
        messages.append({
            "time": burst[0][0],  # seconds (already in seconds)
            "payload": payload,
            "payload_us": payload_us,
            "state": state_name,
        })
    return messages


def find_delimiter(symbols, start_idx=5):
    """
    Find the prefix and delimiter pair in payload starting from start_idx.
    
    Two prefix types:
      - '9': single symbol 9 at start_idx
      - '1,7': symbols [1,7] at start_idx
    
    Two delimiter types (searched for AFTER the prefix):
      - '7,9': first occurrence of [7,9] pair
      - '9,9': first occurrence of [9,9] pair
    
    Returns (prefix_type, delim_type, data_a_start, delim_start_idx) or None.
    """
    if len(symbols) <= start_idx:
        return None
    
    # Determine prefix
    if symbols[start_idx] == 9:
        prefix = "9"
        search_start = start_idx + 1
    elif (start_idx + 1 < len(symbols) and 
          symbols[start_idx] == 1 and symbols[start_idx + 1] == 7):
        prefix = "1,7"
        search_start = start_idx + 2
    else:
        return None
    
    # Search for the FIRST delimiter pair (either 7,9 or 9,9) after the prefix
    best_delim = None
    best_idx = len(symbols)  # larger than any valid index
    
    for i in range(search_start, len(symbols) - 1):
        if (symbols[i] == 7 and symbols[i+1] == 9):
            if i < best_idx:
                best_delim = "7,9"
                best_idx = i
            break  # take the first occurrence
        if (symbols[i] == 9 and symbols[i+1] == 9):
            if i < best_idx:
                best_delim = "9,9"
                best_idx = i
            break
    
    # If no pair found, look for earliest of either type
    if best_delim is None:
        idx_79 = None
        idx_99 = None
        for i in range(search_start, len(symbols) - 1):
            if symbols[i] == 7 and symbols[i+1] == 9 and idx_79 is None:
                idx_79 = i
            if symbols[i] == 9 and symbols[i+1] == 9 and idx_99 is None:
                idx_99 = i
        
        if idx_79 is not None and (idx_99 is None or idx_79 <= idx_99):
            best_delim, best_idx = "7,9", idx_79
        elif idx_99 is not None:
            best_delim, best_idx = "9,9", idx_99
        else:
            return None
    
    return (prefix, best_delim, search_start, best_idx)


def parse_position_field(payload, payload_us):
    """
    Parse the position field from payload pos 5+.
    Returns dict with format info, data_A, data_B, delimiter type, etc.
    """
    result = find_delimiter(payload)
    if result is None:
        return {"format": "UNKNOWN", "raw": payload[5:], "raw_us": payload_us[5:]}
    
    prefix, delim_type, data_a_start, delim_idx = result
    delim_len = 2
    fmt_label = f"{prefix}/{delim_type}"
    
    data_a = payload[data_a_start:delim_idx]
    data_a_us = payload_us[data_a_start:delim_idx]
    data_b = payload[delim_idx + delim_len:]
    data_b_us = payload_us[delim_idx + delim_len:]
    
    # Microsecond offsets
    us_before_delim = sum(payload_us[5:delim_idx])  # from pos 5 to delimiter
    us_data_a = sum(data_a_us) if data_a_us else 0
    us_data_b = sum(data_b_us) if data_b_us else 0
    
    return {
        "format": fmt_label,
        "prefix": prefix,
        "delim_type": delim_type,
        "data_a": data_a,
        "data_a_us": data_a_us,
        "data_b": data_b,
        "data_b_us": data_b_us,
        "delim_idx": delim_idx,
        "us_before_delim": us_before_delim,
        "us_data_a": us_data_a,
        "us_data_b": us_data_b,
        "sum_a": sum(data_a) if data_a else 0,
        "sum_b": sum(data_b) if data_b else 0,
        "sum_a_minus1": sum(s - 1 for s in data_a) if data_a else 0,
        "sum_b_minus1": sum(s - 1 for s in data_b) if data_b else 0,
        "len_a": len(data_a),
        "len_b": len(data_b),
    }


def try_interpretations(parsed_msgs):
    """
    Try many interpretations of the parsed position fields.
    Each interpretation should produce a single number per message.
    Check for monotonicity.
    """
    interpretations = {}
    
    for name, func in [
        # --- Simple sums ---
        ("sum_A", lambda p: p["sum_a"]),
        ("sum_B", lambda p: p["sum_b"]),
        ("sum_A+B", lambda p: p["sum_a"] + p["sum_b"]),
        ("sum_A-1", lambda p: p["sum_a_minus1"]),
        ("sum_B-1", lambda p: p["sum_b_minus1"]),
        ("sum(A-1)+(B-1)", lambda p: p["sum_a_minus1"] + p["sum_b_minus1"]),
        
        # --- Microsecond values ---
        ("us_A", lambda p: p["us_data_a"]),
        ("us_B", lambda p: p["us_data_b"]),
        ("us_A+B", lambda p: p["us_data_a"] + p["us_data_b"]),
        ("us_before_delim", lambda p: p["us_before_delim"]),
        
        # --- Lengths ---
        ("len_A", lambda p: p["len_a"]),
        ("len_B", lambda p: p["len_b"]),
        ("len_A+B", lambda p: p["len_a"] + p["len_b"]),
        
        # --- Combined: sum_A * N + sum_B ---
        ("A*8+B", lambda p: p["sum_a"] * 8 + p["sum_b"]),
        ("A*10+B", lambda p: p["sum_a"] * 10 + p["sum_b"]),
        ("A*16+B", lambda p: p["sum_a"] * 16 + p["sum_b"]),
        ("(A-1)*8+(B-1)", lambda p: p["sum_a_minus1"] * 8 + p["sum_b_minus1"]),
        ("(A-1)*10+(B-1)", lambda p: p["sum_a_minus1"] * 10 + p["sum_b_minus1"]),
        ("(A-1)*16+(B-1)", lambda p: p["sum_a_minus1"] * 16 + p["sum_b_minus1"]),
        
        # --- Base interpretations of data_A ---
        ("A_base6", lambda p: sum((s-1) * (6**i) for i, s in enumerate(reversed(p["data_a"]))) if p["data_a"] else 0),
        ("A_base8", lambda p: sum((s-1) * (8**i) for i, s in enumerate(reversed(p["data_a"]))) if p["data_a"] else 0),
        ("A_base9", lambda p: sum(s * (9**i) for i, s in enumerate(reversed(p["data_a"]))) if p["data_a"] else 0),
        
        # --- Base interpretations of data_B ---
        ("B_base6", lambda p: sum((s-1) * (6**i) for i, s in enumerate(reversed(p["data_b"]))) if p["data_b"] else 0),
        ("B_base8", lambda p: sum((s-1) * (8**i) for i, s in enumerate(reversed(p["data_b"]))) if p["data_b"] else 0),
        
        # --- Combined base ---
        ("A_b6*216+B_b6", lambda p: (sum((s-1)*(6**i) for i,s in enumerate(reversed(p["data_a"]))) if p["data_a"] else 0) * 216 + 
                                     (sum((s-1)*(6**i) for i,s in enumerate(reversed(p["data_b"]))) if p["data_b"] else 0)),
        
        # --- Product of symbols ---
        ("prod_A", lambda p: eval("*".join(str(s) for s in p["data_a"])) if p["data_a"] else 0),
        ("prod_B", lambda p: eval("*".join(str(s) for s in p["data_b"])) if p["data_b"] else 0),
        
        # --- XOR / alternating ---
        ("A_xor", lambda p: eval("^".join(str(s) for s in p["data_a"])) if p["data_a"] else 0),
        
        # --- us_A / 26 (quantized) ---
        ("us_A/26", lambda p: round(p["us_data_a"] / 26)),
        ("us_B/26", lambda p: round(p["us_data_b"] / 26)),
        ("us_A/26+us_B/26", lambda p: round(p["us_data_a"] / 26) + round(p["us_data_b"] / 26)),
        
        # --- Delimiter position in payload ---
        ("delim_idx", lambda p: p.get("delim_idx", 0)),
        
        # --- Weighted: delimiter position relative to message length ---
        ("delim_ratio*100", lambda p: round(p.get("delim_idx", 0) * 100 / max(1, p["len_a"] + p["len_b"] + 2))),
        
        # --- Maybe the symbols represent individual bits: 1=0, anything_else=1 ---
        ("A_bits_1is0", lambda p: int("".join("0" if s==1 else "1" for s in p["data_a"]), 2) if p["data_a"] else 0),
        ("B_bits_1is0", lambda p: int("".join("0" if s==1 else "1" for s in p["data_b"]), 2) if p["data_b"] else 0),
        
        # --- Maybe odd=1, even=0 ---
        ("A_oddeven", lambda p: int("".join("1" if s%2 else "0" for s in p["data_a"]), 2) if p["data_a"] else 0),
        ("B_oddeven", lambda p: int("".join("1" if s%2 else "0" for s in p["data_b"]), 2) if p["data_b"] else 0),
        
        # --- Treat each symbol-1 as a 3-bit value ---
        ("A_3bit", lambda p: int("".join(f"{s-1:03b}" for s in p["data_a"]), 2) if p["data_a"] else 0),
        ("B_3bit", lambda p: int("".join(f"{s-1:03b}" for s in p["data_b"]), 2) if p["data_b"] else 0),
        
        # --- Total µs divided by 26, offset by format type ---
        ("prefix_offset+us_A/26", lambda p: (0 if p.get("prefix") == "9" else 100) + round(p["us_data_a"] / 26)),
        ("prefix_offset+sum_A", lambda p: (0 if p.get("prefix") == "9" else 100) + p["sum_a"]),
        ("prefix_offset+sum_A-1", lambda p: (0 if p.get("prefix") == "9" else 100) + p["sum_a_minus1"]),
        ("delim_offset+us_A/26", lambda p: (0 if p.get("delim_type") == "7,9" else 100) + round(p["us_data_a"] / 26)),
        ("delim_offset+sum_A", lambda p: (0 if p.get("delim_type") == "7,9" else 100) + p["sum_a"]),
        ("delim_offset+sum_A-1", lambda p: (0 if p.get("delim_type") == "7,9" else 100) + p["sum_a_minus1"]),
    ]:
        values = []
        valid = True
        for msg in parsed_msgs:
            p = msg["parsed"]
            if p["format"] == "UNKNOWN":
                valid = False
                break
            try:
                v = func(p)
                values.append(v)
            except:
                valid = False
                break
        if valid and values:
            interpretations[name] = values
    
    return interpretations


def check_monotonicity(values):
    """
    Check how monotonic a sequence is.
    Returns (direction, violations, max_streak, score).
    direction: 'increasing', 'decreasing', or 'flat'
    violations: number of non-monotonic steps
    max_streak: longest monotonic run
    score: 0-100% monotonicity score
    """
    if len(values) < 2:
        return ("flat", 0, len(values), 100)
    
    inc_violations = 0
    dec_violations = 0
    inc_streak = 1
    dec_streak = 1
    max_inc_streak = 1
    max_dec_streak = 1
    
    for i in range(1, len(values)):
        if values[i] >= values[i-1]:
            inc_streak += 1
        else:
            inc_violations += 1
            max_inc_streak = max(max_inc_streak, inc_streak)
            inc_streak = 1
        
        if values[i] <= values[i-1]:
            dec_streak += 1
        else:
            dec_violations += 1
            max_dec_streak = max(max_dec_streak, dec_streak)
            dec_streak = 1
    
    max_inc_streak = max(max_inc_streak, inc_streak)
    max_dec_streak = max(max_dec_streak, dec_streak)
    
    n = len(values) - 1
    if inc_violations <= dec_violations:
        direction = "increasing"
        violations = inc_violations
        max_streak = max_inc_streak
    else:
        direction = "decreasing"
        violations = dec_violations
        max_streak = max_dec_streak
    
    score = (n - violations) / n * 100 if n > 0 else 100
    return (direction, violations, max_streak, score)


def analyze_file(filepath, label, show_detail=True):
    """Analyze one capture file for position encoding."""
    print(f"\n{'#'*100}")
    print(f"  {label}: {os.path.basename(filepath)}")
    print(f"{'#'*100}")
    
    messages = extract_messages(filepath)
    if not messages:
        print("  No messages found!")
        return
    
    # Filter to moving states
    moving = [m for m in messages if m["state"] in ("OPENING", "CLOSING")]
    print(f"  Total messages: {len(messages)}, Moving: {len(moving)}")
    
    if not moving:
        print("  No moving-state messages found.")
        return
    
    # Parse position fields
    for m in moving:
        m["parsed"] = parse_position_field(m["payload"], m["payload_us"])
    
    # Show raw parsed data
    print(f"\n  {'='*96}")
    print(f"  PARSED POSITION FIELDS (Format A: 9 [A] 7,9 [B] | Format B: 1,7 [A] 9,9 [B])")
    print(f"  {'='*96}")
    print(f"  {'Time':>8s}  {'State':>10s}  {'Fmt':>4s}  {'data_A':>25s}  {'data_B':>25s}  {'sA':>3s} {'sB':>3s}  {'usA':>5s} {'usB':>5s}")
    print(f"  {'-'*96}")
    
    for m in moving:
        p = m["parsed"]
        fmt = p.get("format", "?")
        da = str(p.get("data_a", p.get("raw", "?")))
        db = str(p.get("data_b", ""))
        sa = p.get("sum_a", "?")
        sb = p.get("sum_b", "?")
        ua = p.get("us_data_a", "?")
        ub = p.get("us_data_b", "?")
        print(f"  {m['time']:8.3f}s  {m['state']:>10s}  {fmt:>4s}  {da:>25s}  {db:>25s}  {sa:>3}  {sb:>3}  {ua:>5} {ub:>5}")
    
    # Count format types
    fmt_counts = {}
    for m in moving:
        fmt = m["parsed"].get("format", "UNKNOWN")
        fmt_counts[fmt] = fmt_counts.get(fmt, 0) + 1
    print(f"\n  Format distribution: {fmt_counts}")
    
    # Try all interpretations
    interps = try_interpretations(moving)
    
    # Score each interpretation
    scored = []
    for name, values in interps.items():
        direction, violations, max_streak, score = check_monotonicity(values)
        # Also check correlation with time
        if len(values) >= 3:
            first_third = values[:len(values)//3]
            last_third = values[2*len(values)//3:]
            avg_first = sum(first_third) / len(first_third)
            avg_last = sum(last_third) / len(last_third)
            trend = avg_last - avg_first
        else:
            trend = 0
        scored.append((score, name, direction, violations, max_streak, trend, values))
    
    scored.sort(key=lambda x: (-x[0], -abs(x[5])))
    
    # Show top 20 interpretations
    print(f"\n  {'='*96}")
    print(f"  TOP INTERPRETATIONS (ranked by monotonicity score)")
    print(f"  {'='*96}")
    print(f"  {'Score':>6s}  {'Name':>25s}  {'Dir':>11s}  {'Viol':>5s}  {'Streak':>6s}  {'Trend':>7s}  Values")
    print(f"  {'-'*96}")
    
    for score, name, direction, violations, max_streak, trend, values in scored[:25]:
        val_str = str(values[:15])
        if len(values) > 15:
            val_str = val_str[:-1] + ", ...]"
        print(f"  {score:5.1f}%  {name:>25s}  {direction:>11s}  {violations:>5d}  {max_streak:>6d}  {trend:>+7.1f}  {val_str}")
    
    # Show the best candidate in detail
    if scored:
        best_score, best_name, best_dir, best_viol, best_streak, best_trend, best_vals = scored[0]
        print(f"\n  BEST: {best_name} ({best_score:.1f}% {best_dir}, {best_viol} violations)")
        print(f"  Full values: {best_vals}")
        
        if best_score >= 80:
            print(f"\n  *** PROMISING! {best_name} shows {best_score:.1f}% monotonicity ***")
    
    # =====================================================
    # SPLIT ANALYSIS: analyze 7,9 and 9,9 phases separately
    # =====================================================
    print(f"\n  {'='*96}")
    print(f"  SPLIT ANALYSIS: Separate 7,9-phase and 9,9-phase")
    print(f"  {'='*96}")
    
    # Split by prefix type
    phase_pfx9 = [m for m in moving if m["parsed"].get("prefix") == "9"]
    phase_pfx17 = [m for m in moving if m["parsed"].get("prefix") == "1,7"]
    # Also split by delimiter type
    phase_d79 = [m for m in moving if m["parsed"].get("delim_type") == "7,9"]
    phase_d99 = [m for m in moving if m["parsed"].get("delim_type") == "9,9"]
    
    for phase_name, phase_msgs in [("prefix=9", phase_pfx9), ("prefix=1,7", phase_pfx17),
                                     ("delim=7,9", phase_d79), ("delim=9,9", phase_d99)]:
        if len(phase_msgs) < 3:
            print(f"\n  {phase_name}: only {len(phase_msgs)} messages, skipping")
            continue
        
        print(f"\n  --- {phase_name} ({len(phase_msgs)} messages) ---")
        
        phase_interps = try_interpretations(phase_msgs)
        phase_scored = []
        for name, values in phase_interps.items():
            direction, violations, max_streak, score = check_monotonicity(values)
            first_q = values[:max(1, len(values)//3)]
            last_q = values[max(1, 2*len(values)//3):]
            trend = sum(last_q)/len(last_q) - sum(first_q)/len(first_q)
            phase_scored.append((score, name, direction, violations, max_streak, trend, values))
        
        phase_scored.sort(key=lambda x: (-x[0], -abs(x[5])))
        
        print(f"  {'Score':>6s}  {'Name':>25s}  {'Dir':>11s}  {'Trend':>7s}  Values")
        for score, name, direction, violations, max_streak, trend, values in phase_scored[:10]:
            val_str = str(values[:12])
            if len(values) > 12:
                val_str = val_str[:-1] + ", ...]"
            print(f"  {score:5.1f}%  {name:>25s}  {direction:>11s}  {trend:>+7.1f}  {val_str}")
    
    return moving


def analyze_checksum_hypothesis(moving_msgs):
    """
    Test if data_B is a checksum/complement of data_A.
    If sum_A + sum_B ≈ constant, then B might be redundant.
    """
    print(f"\n  {'='*96}")
    print(f"  CHECKSUM HYPOTHESIS: Is sum_A + sum_B constant?")
    print(f"  {'='*96}")
    
    totals_79 = []
    totals_99 = []
    for m in moving_msgs:
        p = m["parsed"]
        if p["format"] == "UNKNOWN":
            continue
        total = p["sum_a"] + p["sum_b"]
        if p.get("delim_type") == "7,9":
            totals_79.append(total)
        else:
            totals_99.append(total)
    
    if totals_79:
        print(f"  7,9-phase sum(A+B): {totals_79}")
        print(f"    min={min(totals_79)}, max={max(totals_79)}, mode={max(set(totals_79), key=totals_79.count)}")
    if totals_99:
        print(f"  9,9-phase sum(A+B): {totals_99}")
        print(f"    min={min(totals_99)}, max={max(totals_99)}, mode={max(set(totals_99), key=totals_99.count)}")


def analyze_us_structure(moving_msgs):
    """
    Analyze the microsecond structure more carefully.
    Look at the total µs of data_A, data_B, and their ratio.
    """
    print(f"\n  {'='*96}")
    print(f"  MICROSECOND STRUCTURE ANALYSIS")
    print(f"  {'='*96}")
    
    print(f"  {'Time':>8s}  {'Fmt':>4s}  {'usA':>5s}  {'usB':>5s}  {'A+B':>5s}  {'A/(A+B)':>7s}  data_A → data_B")
    print(f"  {'-'*96}")
    
    for m in moving_msgs:
        p = m["parsed"]
        if p["format"] == "UNKNOWN":
            print(f"  {m['time']:8.3f}s  {'UNK':>4s}  {'-':>5s}  {'-':>5s}  {'-':>5s}  {'-':>7s}  {p.get('raw', '?')}")
            continue
        
        total_us = p["us_data_a"] + p["us_data_b"]
        ratio = p["us_data_a"] / total_us * 100 if total_us > 0 else 0
        da = p["data_a"]
        db = p["data_b"]
        print(f"  {m['time']:8.3f}s  {p['format']:>4s}  {p['us_data_a']:>5.0f}  {p['us_data_b']:>5.0f}  {total_us:>5.0f}  {ratio:>6.1f}%  {da} → {db}")


def analyze_cumulative_offset(moving_msgs):
    """
    Try computing position as cumulative µs offset from message start
    to the delimiter, including the format marker.
    """
    print(f"\n  {'='*96}")
    print(f"  DELIMITER OFFSET FROM MESSAGE START (µs and symbol count)")
    print(f"  {'='*96}")
    
    print(f"  {'Time':>8s}  {'Fmt':>4s}  {'DelIdx':>6s}  {'us_to_del':>9s}  {'sym_to_del':>10s}  {'us_after':>8s}")
    print(f"  {'-'*96}")
    
    us_to_del_list = []
    for m in moving_msgs:
        p = m["parsed"]
        if p["format"] == "UNKNOWN":
            continue
        delim_idx = p.get("delim_idx", 0)
        us_to_del = sum(m["payload_us"][:delim_idx])
        sym_to_del = sum(m["payload"][:delim_idx])
        us_after = sum(m["payload_us"][delim_idx+2:])
        us_to_del_list.append(us_to_del)
        print(f"  {m['time']:8.3f}s  {p['format']:>4s}  {delim_idx:>6d}  {us_to_del:>9.0f}  {sym_to_del:>10d}  {us_after:>8.0f}")
    
    if us_to_del_list:
        direction, violations, streak, score = check_monotonicity(us_to_del_list)
        print(f"\n  us_to_delimiter monotonicity: {score:.1f}% {direction}, {violations} violations")


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    
    test_files = [
        ("test04_open_full.txt", "OPENING - full travel (closed → open)"),
        ("test05_close_full.txt", "CLOSING - full travel (open → closed)"),
    ]
    
    for fname, label in test_files:
        fpath = os.path.join(base, fname)
        if not os.path.exists(fpath):
            # Try alternate names
            for f in os.listdir(base):
                if "test04" in f.lower() or "open_full" in f.lower():
                    if "test04" in fname.lower():
                        fpath = os.path.join(base, f)
                        break
                if "test05" in f.lower() or "close_full" in f.lower():
                    if "test05" in fname.lower():
                        fpath = os.path.join(base, f)
                        break
        
        if not os.path.exists(fpath):
            print(f"\n  WARNING: {fname} not found, skipping.")
            continue
        
        moving = analyze_file(fpath, label)
        if moving:
            analyze_checksum_hypothesis(moving)
            analyze_us_structure(moving)
            analyze_cumulative_offset(moving)
    
    # Also check stopped files for position freeze
    print(f"\n\n{'#'*100}")
    print(f"  STOPPED-STATE POSITION FREEZE CHECK")
    print(f"{'#'*100}")
    
    stop_files = [
        ("test06_open_stop_mid.txt", "Stop mid-open"),
        ("test07_resume_open.txt", "Resume from mid"),
    ]
    
    for fname, label in stop_files:
        fpath = os.path.join(base, fname)
        if not os.path.exists(fpath):
            for f in os.listdir(base):
                if "test06" in f.lower() and "test06" in fname.lower():
                    fpath = os.path.join(base, f)
                    break
                if "test07" in f.lower() and "test07" in fname.lower():
                    fpath = os.path.join(base, f)
                    break
        
        if not os.path.exists(fpath):
            continue
        
        messages = extract_messages(fpath)
        print(f"\n  --- {label} ({os.path.basename(fpath)}) ---")
        for m in messages:
            p = parse_position_field(m["payload"], m["payload_us"])
            fmt = p.get("format", "?")
            da = p.get("data_a", p.get("raw", "?"))
            db = p.get("data_b", "")
            print(f"  {m['time']:8.3f}s  {m['state']:>20s}  fmt={fmt}  A={da}  B={db}")


if __name__ == "__main__":
    main()
