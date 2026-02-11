"""Position counter deep-dive analysis.

Extracts the raw microsecond LOW gap timings for Type B position fields
across door travel captures and attempts multiple decoding strategies.
"""

import os
import sys
import io
from analyze import (
    parse_capture, find_bursts, classify_burst, burst_pulses,
    decode_pwm, TYPE_B_HEADER, TYPE_B_HEADER_LEN, PWM_UNIT_US,
    DOOR_STATE_MAP, DIRECTION_MAP
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def extract_type_b_raw(filepath):
    """Extract all Type B messages with both quantized symbols AND raw microsecond timings.
    
    Returns list of dicts with keys:
        time, symbols, raw_us, header_syms, payload_syms,
        header_raw, payload_raw, door_state, direction
    """
    channels, _ = parse_capture(filepath)
    results = []
    
    if not channels[1]:
        return results
    
    bursts = find_bursts(channels[1])
    for burst in bursts:
        if classify_burst(burst) != "data":
            continue
        
        symbols, raw_us = decode_pwm(burst)
        
        # Check if it's a Type B message
        if len(symbols) < TYPE_B_HEADER_LEN + 2:
            continue
        if tuple(symbols[:TYPE_B_HEADER_LEN]) != TYPE_B_HEADER:
            continue
        
        payload_syms = symbols[TYPE_B_HEADER_LEN:]
        payload_raw = raw_us[TYPE_B_HEADER_LEN:]
        
        # Decode door state
        door_state = None
        direction = None
        if len(payload_syms) >= 2:
            door_state = DOOR_STATE_MAP.get(tuple(payload_syms[0:2]), f"?({payload_syms[0]},{payload_syms[1]})")
        if len(payload_syms) >= 7:
            direction = DIRECTION_MAP.get(tuple(payload_syms[5:7]))
        
        results.append({
            "time": burst[0][0],
            "symbols": symbols,
            "raw_us": raw_us,
            "header_syms": symbols[:TYPE_B_HEADER_LEN],
            "payload_syms": payload_syms,
            "header_raw": raw_us[:TYPE_B_HEADER_LEN],
            "payload_raw": payload_raw,
            "door_state": door_state,
            "direction": direction,
        })
    
    return results


def try_decode_strategies(messages):
    """Try multiple decoding strategies on position field and print results."""
    
    print("=" * 100)
    print("  POSITION COUNTER ANALYSIS - MULTI-STRATEGY DECODING")
    print("=" * 100)
    
    # Filter to only moving states
    moving = [m for m in messages if m["door_state"] in ("OPENING", "CLOSING")]
    if not moving:
        print("  No moving-state messages found.")
        return
    
    print(f"\n  Found {len(moving)} messages during door travel.\n")
    
    # ---- Strategy 0: Raw dump ----
    print("-" * 100)
    print("  STRATEGY 0: RAW DATA DUMP")
    print("-" * 100)
    print(f"  {'Time':>8s}  {'State':>10s}  {'Full payload symbols':<50s}  {'Full payload raw_us'}")
    for m in moving:
        ps = m["payload_syms"]
        pr = [f"{v:.0f}" for v in m["payload_raw"]]
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {str(ps):<50s}  [{', '.join(pr)}]")
    
    # ---- Strategy 1: Position = sum of all position symbols (pos 7+) ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 1: Sum of position symbols (pos 7+)")
    print("-" * 100)
    print(f"  {'Time':>8s}  {'State':>10s}  {'Pos syms':<40s}  {'Sum':>5s}  {'Delta':>6s}")
    prev_sum = None
    for m in moving:
        ps = m["payload_syms"]
        pos = ps[7:] if len(ps) > 7 else []
        s = sum(pos)
        delta = (s - prev_sum) if prev_sum is not None else 0
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {str(pos):<40s}  {s:5d}  {delta:+6d}")
        prev_sum = s
    
    # ---- Strategy 2: Position = total raw microseconds of position field ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 2: Total raw microseconds of position field (pos 7+)")
    print("-" * 100)
    print(f"  {'Time':>8s}  {'State':>10s}  {'Total_us':>10s}  {'Delta_us':>10s}")
    prev_us = None
    for m in moving:
        pr = m["payload_raw"]
        pos_raw = pr[7:] if len(pr) > 7 else []
        total = sum(pos_raw)
        delta = (total - prev_us) if prev_us is not None else 0
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {total:10.1f}  {delta:+10.1f}")
        prev_us = total
    
    # ---- Strategy 3: Treat 9 as delimiter, decode fields before/after as base-9 ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 3: Split on 9,9 delimiter -> base-9 fields")
    print("-" * 100)
    
    def split_on_99(syms):
        """Split symbol list on [9,9] delimiter. Returns list of fields."""
        fields = []
        current = []
        i = 0
        while i < len(syms):
            if i < len(syms) - 1 and syms[i] == 9 and syms[i+1] == 9:
                fields.append(current)
                current = []
                i += 2
            else:
                current.append(syms[i])
                i += 1
        if current:
            fields.append(current)
        return fields
    
    def base9_decode(digits):
        """Decode list of base-9 digits (wire value - 1) to integer."""
        val = 0
        for d in digits:
            val = val * 9 + (d - 1)  # wire symbol 1-9 -> digit 0-8
        return val
    
    def base8_decode(digits):
        """Decode list of base-8 digits (wire value 1-8 -> 0-7) to integer, treating 9 as impossible."""
        val = 0
        for d in digits:
            if d >= 9:
                return None  # invalid
            val = val * 8 + (d - 1)
        return val
    
    print(f"  {'Time':>8s}  {'State':>10s}  {'Before 9,9':>20s}  {'After 9,9':>20s}  {'B9_pre':>8s}  {'B9_post':>8s}  {'B8_pre':>8s}  {'B8_post':>8s}")
    for m in moving:
        pos = m["payload_syms"][7:] if len(m["payload_syms"]) > 7 else []
        fields = split_on_99(pos)
        pre = fields[0] if len(fields) > 0 else []
        post = fields[1] if len(fields) > 1 else []
        b9_pre = base9_decode(pre) if pre else None
        b9_post = base9_decode(post) if post else None
        b8_pre = base8_decode(pre) if pre else None
        b8_post = base8_decode(post) if post else None
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {str(pre):>20s}  {str(post):>20s}  "
              f"{str(b9_pre):>8s}  {str(b9_post):>8s}  {str(b8_pre):>8s}  {str(b8_post):>8s}")
    
    # ---- Strategy 4: Entire position as one base-N number (ignoring 9,9) ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 4: Entire position as one number (remove 9,9 delimiter)")
    print("-" * 100)
    
    def remove_99(syms):
        """Remove all adjacent 9,9 pairs from symbol list."""
        result = []
        i = 0
        while i < len(syms):
            if i < len(syms) - 1 and syms[i] == 9 and syms[i+1] == 9:
                i += 2
            else:
                result.append(syms[i])
                i += 1
        return result
    
    print(f"  {'Time':>8s}  {'State':>10s}  {'Digits':>30s}  {'Base9':>10s}  {'Base8':>10s}  {'d(B9)':>8s}  {'d(B8)':>8s}")
    prev_b9 = None
    prev_b8 = None
    for m in moving:
        pos = m["payload_syms"][7:] if len(m["payload_syms"]) > 7 else []
        digits = remove_99(pos)
        b9 = base9_decode(digits) if digits else None
        b8 = base8_decode(digits) if digits else None
        d9 = (b9 - prev_b9) if (b9 is not None and prev_b9 is not None) else None
        d8 = (b8 - prev_b8) if (b8 is not None and prev_b8 is not None) else None
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {str(digits):>30s}  "
              f"{str(b9):>10s}  {str(b8):>10s}  "
              f"{str(d9):>8s}  {str(d8):>8s}")
        if b9 is not None:
            prev_b9 = b9
        if b8 is not None:
            prev_b8 = b8
    
    # ---- Strategy 5: Binary expansion (each symbol = N bits of 1) ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 5: Alternating run-length encoding")
    print("    Treat symbols as run lengths of alternating 1s and 0s")
    print("-" * 100)
    
    def to_runlength_bits(syms, start_bit=1):
        """Convert symbol list to bits via run-length encoding.
        First symbol = N bits of start_bit, second = N bits of (1-start_bit), etc."""
        bits = []
        bit = start_bit
        for s in syms:
            bits.extend([bit] * s)
            bit = 1 - bit
        return bits
    
    print(f"  {'Time':>8s}  {'State':>10s}  {'Bits (start=1)':>50s}  {'Len':>4s}  {'As int':>12s}")
    prev_int = None
    for m in moving:
        pos = m["payload_syms"][7:] if len(m["payload_syms"]) > 7 else []
        bits = to_runlength_bits(pos, start_bit=1)
        bit_str = ''.join(str(b) for b in bits)
        val = int(bit_str, 2) if bits else 0
        d = (val - prev_int) if prev_int is not None else None
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {bit_str:>50s}  {len(bits):4d}  {val:12d}  d={str(d)}")
        prev_int = val
    
    # ---- Strategy 6: Each symbol IS a 4-bit nibble ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 6: Each symbol as 4-bit nibble (1=0001 ... 9=1001)")
    print("    Concatenate nibbles, remove 9,9 (=0xFF) delimiter")
    print("-" * 100)
    
    print(f"  {'Time':>8s}  {'State':>10s}  {'Hex':>30s}  {'Decimal':>12s}  {'Delta':>10s}")
    prev_val = None
    for m in moving:
        pos = m["payload_syms"][7:] if len(m["payload_syms"]) > 7 else []
        digits = remove_99(pos)
        # Each symbol 1-9 as a 4-bit nibble
        nibbles = ''.join(f'{s:04b}' for s in digits)
        val = int(nibbles, 2) if nibbles else 0
        hex_str = hex(val) if nibbles else "0x0"
        delta = (val - prev_val) if prev_val is not None else None
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {hex_str:>30s}  {val:12d}  {str(delta):>10s}")
        prev_val = val
    
    # ---- Strategy 7: Trinary/ternary - symbol mod 3 gives 2 trits ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 7: Symbol mapped to trinary (1-9 -> 0-8, base-3 pairs)")
    print("-" * 100)
    
    def sym_to_trits(s):
        """Map symbol 1-9 to two base-3 trits: (s-1)//3, (s-1)%3"""
        v = s - 1  # 0-8
        return (v // 3, v % 3)
    
    print(f"  {'Time':>8s}  {'State':>10s}  {'Trits':>40s}  {'Base3 val':>12s}  {'Delta':>10s}")
    prev_val = None
    for m in moving:
        pos = m["payload_syms"][7:] if len(m["payload_syms"]) > 7 else []
        digits_no99 = remove_99(pos)
        trits = []
        for s in digits_no99:
            t = sym_to_trits(s)
            trits.extend(t)
        trit_str = ''.join(str(t) for t in trits)
        val = int(trit_str, 3) if trit_str else 0
        delta = (val - prev_val) if prev_val is not None else None
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {trit_str:>40s}  {val:12d}  {str(delta):>10s}")
        prev_val = val

    # ---- Strategy 8: Look at the FULL message raw timing more carefully ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 8: Raw timing analysis - look for consistent sub-26us patterns")
    print("-" * 100)
    print(f"  {'Time':>8s}  {'Pos raw_us values (each LOW gap in position field)'}")
    for m in moving:
        pr = m["payload_raw"]
        pos_raw = pr[7:] if len(pr) > 7 else []
        # Show both raw and the ratio to 26us
        ratios = [f"{v:.1f}({v/PWM_UNIT_US:.2f})" for v in pos_raw]
        print(f"  {m['time']:8.3f}s  [{', '.join(ratios)}]")
    
    # ---- Strategy 9: What if position is encoded across the WHOLE payload? ----
    print(f"\n{'-'*100}")
    print("  STRATEGY 9: Full payload (pos 0-end) as single value")
    print("    Remove known state fields (pos 0-6), but also check pos 0-6 for changes")
    print("-" * 100)
    
    print(f"  {'Time':>8s}  {'State':>10s}  {'Pos0-6':>24s}  {'Pos7+':>40s}")
    for m in moving:
        ps = m["payload_syms"]
        state_part = ps[:7] if len(ps) >= 7 else ps
        pos_part = ps[7:] if len(ps) > 7 else []
        print(f"  {m['time']:8.3f}s  {m['door_state']:>10s}  {str(state_part):>24s}  {str(pos_part)}")
    
    # Check if pos 0-6 ever changes during travel
    state_parts = set()
    for m in moving:
        ps = m["payload_syms"]
        if len(ps) >= 7:
            state_parts.add(tuple(ps[:7]))
    print(f"\n  Distinct pos 0-6 values during travel: {len(state_parts)}")
    for sp in sorted(state_parts):
        print(f"    {list(sp)}")


def main():
    """Run position analysis on door travel captures."""
    travel_files = [
        ("test04_open_full.txt", "Full open (closed -> open)"),
        ("test05_close_full.txt", "Full close (open -> closed)"),
    ]
    
    for fname, desc in travel_files:
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            print(f"  File not found: {fname}")
            continue
        
        print(f"\n\n{'#'*100}")
        print(f"  FILE: {fname} - {desc}")
        print(f"{'#'*100}")
        
        messages = extract_type_b_raw(path)
        if not messages:
            print("  No Type B messages found.")
            continue
        
        print(f"  Total Type B messages: {len(messages)}")
        try_decode_strategies(messages)
    
    # Also do stop/resume files to see if position freezes
    stop_files = [
        ("test06_open_stop_mid.txt", "Open then stop mid-travel"),
        ("test07_resume_open.txt", "Resume from mid-travel"),
    ]
    
    for fname, desc in stop_files:
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            continue
        
        print(f"\n\n{'#'*100}")
        print(f"  FILE: {fname} - {desc}")
        print(f"{'#'*100}")
        
        messages = extract_type_b_raw(path)
        if not messages:
            continue
        
        print(f"  Total Type B messages: {len(messages)}")
        
        # Just show Strategy 0 for stop files to see freeze behavior
        print(f"\n  {'Time':>8s}  {'State':>20s}  {'Payload symbols'}")
        for m in messages:
            ps = m["payload_syms"]
            print(f"  {m['time']:8.3f}s  {m['door_state']:>20s}  {ps}")


if __name__ == "__main__":
    main()