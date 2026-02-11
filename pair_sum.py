"""Pair-sum analysis: compute sum(L+H) for data_A and data_B regions.

Key insight: data_B sum appears CONSTANT while data_A sum changes with position.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from analyze import parse_capture, find_bursts, BURST_GAP_S

PWM_UNIT_US = 26.0
HDR_L = [1,7,2,1,4,6,2,9]

def burst_to_pairs(burst):
    segs = []
    for i in range(1, len(burst)):
        state = burst[i-1][1]
        dur_us = (burst[i][0] - burst[i-1][0]) * 1e6
        segs.append((state, round(dur_us / PWM_UNIT_US)))
    pairs = []
    j = 0
    while j < len(segs):
        if segs[j][0] == 0:
            l = segs[j][1]
            h = segs[j+1][1] if j+1 < len(segs) and segs[j+1][0] == 1 else 0
            pairs.append((l, h))
            j += 2 if h > 0 else 1
        else:
            j += 1
    return pairs

def extract(filepath):
    channels, _ = parse_capture(filepath)
    ch1 = channels.get(1, [])
    if not ch1: return []
    msgs = []
    for burst in find_bursts(ch1):
        pairs = burst_to_pairs(burst)
        if len(pairs) < 8: continue
        if [l for l,h in pairs[:8]] != HDR_L: continue
        msgs.append({"time": burst[0][0], "pairs": pairs[8:]})  # payload only
    return msgs

def find_delim(l_syms, start=0):
    """Find first 7,9 or 9,9 in L-only symbols starting from start."""
    for i in range(start, len(l_syms) - 1):
        if (l_syms[i] == 7 and l_syms[i+1] == 9) or (l_syms[i] == 9 and l_syms[i+1] == 9):
            return i, f"{l_syms[i]},{l_syms[i+1]}"
    return None, None

def analyze_file(filepath, label, expected):
    msgs = extract(filepath)
    if not msgs:
        print(f"  No messages in {filepath}")
        return

    print(f"\n{'='*120}")
    print(f"  {label}: {os.path.basename(filepath)} ({len(msgs)} msgs, expected: {expected})")
    print(f"{'='*120}")
    print(f"  {'Time':>8s} {'St':>5s} {'Pfx':>4s} {'Dlm':>4s} {'A_L':>20s} {'A_H':>20s} {'sumA':>5s} {'B_L':>20s} {'B_H':>20s} {'sumB':>5s} {'tot':>5s}")
    
    a_vals = []
    b_vals = []
    times = []
    
    for msg in msgs:
        payload = msg["pairs"]
        t = msg["time"]
        l_syms = [l for l,h in payload]
        h_syms = [h for l,h in payload]
        
        state = l_syms[:2]
        
        # Position field from pos 5
        pos_pairs = payload[5:]
        pos_l = [l for l,h in pos_pairs]
        pos_h = [h for l,h in pos_pairs]
        
        # Detect prefix
        if len(pos_l) >= 2 and pos_l[0] == 1 and pos_l[1] == 7:
            prefix = "1,7"
            data_start = 2
        elif len(pos_l) >= 1 and pos_l[0] == 9:
            prefix = "9"
            data_start = 1
        else:
            prefix = "?"
            data_start = 0
        
        # Find delimiter in L values after prefix
        delim_idx, delim_type = find_delim(pos_l, data_start)
        
        if delim_idx is None:
            # No delimiter found
            a_l = pos_l[data_start:]
            a_h = pos_h[data_start:]
            b_l = []
            b_h = []
            delim_type = "none"
        else:
            a_l = pos_l[data_start:delim_idx]
            a_h = pos_h[data_start:delim_idx]
            b_l = pos_l[delim_idx+2:]
            b_h = pos_h[delim_idx+2:]
        
        # Compute pair sums: sum of (L + H) for A and B data regions
        a_pairs_sum = sum(pos_pairs[data_start + i][0] + pos_pairs[data_start + i][1]
                         for i in range(len(a_l))
                         if pos_pairs[data_start + i][1] <= 10)  # exclude crosstalk
        
        b_start = delim_idx + 2 if delim_idx is not None else len(pos_pairs)
        b_pairs_sum = sum(pos_pairs[b_start + i][0] + pos_pairs[b_start + i][1]
                         for i in range(len(b_l))
                         if b_start + i < len(pos_pairs) and pos_pairs[b_start + i][1] <= 10)
        
        total = a_pairs_sum + b_pairs_sum
        
        a_vals.append(a_pairs_sum)
        b_vals.append(b_pairs_sum)
        times.append(t)
        
        # Filter crosstalk from display  
        a_h_clean = [h if h <= 10 else f"*{h}*" for h in a_h]
        b_h_clean = [h if h <= 10 else f"*{h}*" for h in b_h]
        
        print(f"  {t:8.3f}s {str(state):>5s} {prefix:>4s} {str(delim_type):>4s}"
              f" {str(a_l):>20s} {str(a_h_clean):>20s} {a_pairs_sum:>5d}"
              f" {str(b_l):>20s} {str(b_h_clean):>20s} {b_pairs_sum:>5d} {total:>5d}")
    
    # Summary
    print(f"\n  --- Summary ---")
    print(f"  A values: {a_vals}")
    print(f"  B values: {b_vals}")
    
    # Check A monotonicity
    if len(a_vals) > 2:
        inc = sum(1 for i in range(1, len(a_vals)) if a_vals[i] > a_vals[i-1])
        dec = sum(1 for i in range(1, len(a_vals)) if a_vals[i] < a_vals[i-1])
        eq = sum(1 for i in range(1, len(a_vals)) if a_vals[i] == a_vals[i-1])
        total = len(a_vals) - 1
        print(f"  A: inc={inc} dec={dec} eq={eq} total={total}")
        print(f"  A range: [{min(a_vals)}, {max(a_vals)}]")
        
    if len(b_vals) > 2:
        print(f"  B range: [{min(b_vals)}, {max(b_vals)}]")
        b_unique = set(b_vals)
        print(f"  B unique values: {sorted(b_unique)}")


def main():
    base = os.path.dirname(__file__)
    for fname, label, exp in [
        ('test04_open_full.txt', 'OPENING full', 'A increasing'),
        ('test05_close_full.txt', 'CLOSING full', 'A decreasing'),
        ('test06_open_stop_mid.txt', 'OPEN stop mid', 'A inc then freeze'),
        ('test07_resume_open.txt', 'RESUME open', 'A continues inc'),
    ]:
        path = os.path.join(base, fname)
        if os.path.exists(path):
            analyze_file(path, label, exp)

if __name__ == "__main__":
    main()
