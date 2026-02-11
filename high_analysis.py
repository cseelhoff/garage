"""Analyze HIGH duration patterns in Type B position field.

Fresh approach: look at BOTH low and high durations as (L,H) pairs,
since HIGH durations are NOT always 1 unit in the position field.
"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from analyze import parse_capture, find_bursts, BURST_GAP_S

PWM_UNIT_US = 26.0

# Type B header as (L,H) pairs - we expect all H=1
TYPE_B_HEADER_LOW = [1, 7, 2, 1, 4, 6, 2, 9]


def burst_to_lh_pairs(burst):
    """Convert burst transitions to list of (L_units, H_units) pairs.
    
    Each symbol transmission is a LOW period followed by a HIGH period.
    Returns: list of (low_units, high_units) tuples, plus raw microseconds.
    """
    pairs_units = []
    pairs_us = []
    
    # Build state/duration sequence
    segments = []
    for i in range(1, len(burst)):
        state = burst[i-1][1]
        dur_us = (burst[i][0] - burst[i-1][0]) * 1e6
        segments.append((state, dur_us))
    
    # Group into (LOW, HIGH) pairs
    i = 0
    while i < len(segments):
        if segments[i][0] == 0:  # LOW
            low_us = segments[i][1]
            high_us = 0
            if i + 1 < len(segments) and segments[i+1][0] == 1:
                high_us = segments[i+1][1]
                i += 2
            else:
                i += 1
            low_units = round(low_us / PWM_UNIT_US)
            high_units = round(high_us / PWM_UNIT_US)
            pairs_units.append((low_units, high_units))
            pairs_us.append((low_us, high_us))
        else:
            # Starts with HIGH - skip initial high
            i += 1
    
    return pairs_units, pairs_us


def is_type_b(pairs):
    """Check if (L,H) pairs match Type B header."""
    if len(pairs) < len(TYPE_B_HEADER_LOW):
        return False
    for i, expected_low in enumerate(TYPE_B_HEADER_LOW):
        if pairs[i][0] != expected_low:
            return False
    return True


def extract_type_b_messages(filepath):
    """Extract Type B messages as (L,H) pair sequences."""
    channels, ncols = parse_capture(filepath)
    ch1 = channels.get(1, [])
    if not ch1:
        return []
    
    messages = []
    for burst in find_bursts(ch1):
        pairs, pairs_us = burst_to_lh_pairs(burst)
        if not is_type_b(pairs):
            continue
        
        t_start = burst[0][0]
        messages.append({
            "time": t_start,
            "pairs": pairs,       # (L_units, H_units) tuples
            "pairs_us": pairs_us, # raw microseconds
        })
    return messages


def main():
    base = os.path.dirname(__file__)
    
    # ============================================================
    # PART 1: HIGH duration histogram across all Type B messages
    # ============================================================
    print("=" * 80)
    print("  PART 1: HIGH duration distribution in Type B messages")
    print("=" * 80)
    
    all_h_header = Counter()  # H values in header positions
    all_h_payload = Counter()  # H values in payload positions
    all_h_by_pos = {}  # position -> Counter of H values
    
    test_files = ['test04_open_full.txt', 'test05_close_full.txt',
                  'test06_open_stop_mid.txt', 'test07_resume_open.txt',
                  'test08_close_stop_mid.txt']
    
    for fname in test_files:
        fpath = os.path.join(base, fname)
        if not os.path.exists(fpath):
            continue
        msgs = extract_type_b_messages(fpath)
        for msg in msgs:
            pairs = msg["pairs"]
            for idx, (l, h) in enumerate(pairs):
                if idx < 8:
                    all_h_header[h] += 1
                else:
                    all_h_payload[h] += 1
                if idx not in all_h_by_pos:
                    all_h_by_pos[idx] = Counter()
                all_h_by_pos[idx][h] += 1
    
    print(f"\n  Header H values:  {dict(sorted(all_h_header.items()))}")
    print(f"  Payload H values: {dict(sorted(all_h_payload.items()))}")
    
    print(f"\n  H values by position (showing positions with any H != 1):")
    for pos in sorted(all_h_by_pos.keys()):
        c = all_h_by_pos[pos]
        if any(k != 1 and k != 0 for k in c.keys()):
            print(f"    pos {pos:2d}: {dict(sorted(c.items()))}")
    
    # ============================================================
    # PART 2: Show (L,H) pairs for each Type B in test04, test05
    # ============================================================
    print("\n" + "=" * 80)
    print("  PART 2: Full (L,H) pair sequences for OPENING / CLOSING")
    print("=" * 80)
    
    for fname, label in [('test04_open_full.txt', 'OPENING'),
                         ('test05_close_full.txt', 'CLOSING')]:
        fpath = os.path.join(base, fname)
        msgs = extract_type_b_messages(fpath)
        
        print(f"\n  --- {label}: {fname} ({len(msgs)} Type B messages) ---")
        
        for msg in msgs:
            pairs = msg["pairs"]
            t = msg["time"]
            payload = pairs[8:]  # skip header
            
            # Format: show L values, with H annotated when != 1
            parts = []
            for l, h in payload:
                if h == 0:
                    parts.append(f"{l}.")  # trailing (no HIGH after)
                elif h == 1:
                    parts.append(f"{l}")
                else:
                    parts.append(f"{l}({h}H)")
            
            # Also show just the H values for the whole payload
            h_vals = [h for _, h in payload]
            non_one_h = [(i, l, h) for i, (l, h) in enumerate(payload) if h != 1]
            
            print(f"\n    {t:8.3f}s  L: {' '.join(parts)}")
            if non_one_h:
                annot = ", ".join(f"p{i}:L={l},H={h}" for i, l, h in non_one_h)
                print(f"             Non-1H: {annot}")
    
    # ============================================================
    # PART 3: Focus on position field - extract H values only
    # ============================================================
    print("\n" + "=" * 80)
    print("  PART 3: Track non-1H values through door travel")
    print("=" * 80)
    
    for fname, label, expected_dir in [('test04_open_full.txt', 'OPENING', 'increasing'),
                                        ('test05_close_full.txt', 'CLOSING', 'decreasing')]:
        fpath = os.path.join(base, fname)
        msgs = extract_type_b_messages(fpath)
        
        print(f"\n  --- {label} ({expected_dir}) ---")
        print(f"  {'Time':>8s}  {'State':>10s}  {'#pairs':>6s}  {'sum(H)':>6s}  {'sum(H-1)':>8s}  {'max(H)':>6s}  Non-1H positions and values")
        
        for msg in msgs:
            pairs = msg["pairs"]
            t = msg["time"]
            payload = pairs[8:]
            
            state_l = [l for l, h in payload[:2]]
            
            h_vals = [h for _, h in payload]
            sum_h = sum(h_vals)
            sum_h_extra = sum(max(0, h - 1) for _, h in payload)
            max_h = max(h_vals) if h_vals else 0
            
            non1 = [(i, l, h) for i, (l, h) in enumerate(payload) if h != 1 and h != 0]
            non1_str = " ".join(f"[{i}]={h}" for i, l, h in non1)
            
            print(f"  {t:8.3f}s  {str(state_l):>10s}  {len(payload):6d}  {sum_h:6d}  {sum_h_extra:8d}  {max_h:6d}  {non1_str}")
    
    # ============================================================
    # PART 4: What if HIGH encodes a separate value per symbol pair?
    # Try interpreting each (L, H) as a combined value
    # ============================================================
    print("\n" + "=" * 80)
    print("  PART 4: Combined (L,H) interpretations for position field")
    print("=" * 80)
    
    for fname, label in [('test04_open_full.txt', 'OPENING'),
                         ('test05_close_full.txt', 'CLOSING')]:
        fpath = os.path.join(base, fname)
        msgs = extract_type_b_messages(fpath)
        
        print(f"\n  --- {label} ---")
        
        values_by_interp = {
            'sum_all_H': [],
            'sum_extra_H': [],       # sum(H-1) for H>1
            'total_units': [],       # sum of all L+H
            'pos_field_LH': [],      # concat of L*10+H for pos 5+
            'H_as_binary': [],       # treat extra H as binary number
            'L_plus_H': [],          # sum(L+H) per pair, total
        }
        times = []
        
        for msg in msgs:
            pairs = msg["pairs"]
            payload = pairs[8:]
            
            # Skip non-moving states (check sub-state)
            state = tuple(p[0] for p in payload[:2])
            
            pos_pairs = payload[5:]  # position field starts ~pos 5
            
            h_vals = [h for _, h in pos_pairs]
            l_vals = [l for l, _ in pos_pairs]
            
            times.append(msg["time"])
            values_by_interp['sum_all_H'].append(sum(h_vals))
            values_by_interp['sum_extra_H'].append(sum(max(0, h-1) for h in h_vals))
            values_by_interp['total_units'].append(sum(l + h for l, h in pos_pairs))
            
            # H values > 1 as a binary-ish number
            non1_h = [h - 1 for _, h in pos_pairs if h > 1]
            if non1_h:
                values_by_interp['H_as_binary'].append(sum(non1_h))
            else:
                values_by_interp['H_as_binary'].append(0)
            
            values_by_interp['L_plus_H'].append(
                sum(l + h for l, h in pos_pairs))
        
        for key, vals in values_by_interp.items():
            if len(vals) < 3:
                continue
            # Check monotonicity
            inc = sum(1 for i in range(1, len(vals)) if vals[i] > vals[i-1])
            dec = sum(1 for i in range(1, len(vals)) if vals[i] < vals[i-1])
            eq = sum(1 for i in range(1, len(vals)) if vals[i] == vals[i-1])
            total = len(vals) - 1
            
            inc_pct = inc / total * 100
            dec_pct = dec / total * 100
            
            dir_str = "INC" if inc > dec else "DEC"
            score = max(inc, dec) / total * 100
            
            print(f"  {key:>20s}: {dir_str} {score:5.1f}%  range=[{min(vals)}, {max(vals)}]  vals={vals[:15]}...")


if __name__ == "__main__":
    main()
