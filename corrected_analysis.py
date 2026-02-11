"""Test L+H-1 corrected symbol theory.

Theory: The protocol encodes data in the falling-edge-to-falling-edge period.
Each pair (L, H) encodes symbol = L + H - 1.
Standard: H=1, symbol = L. Non-standard: H>1 redistributes time.
Example: (1,9) -> symbol 9, (9,1) -> symbol 9, (3,3) -> symbol 5.

This would mean our original L-only decode was missing data stored
in the HIGH durations.
"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from analyze import parse_capture, find_bursts, BURST_GAP_S

PWM_UNIT_US = 26.0
CROSSTALK_THRESHOLD = 10  # H values above this are CH0 carrier interference

TYPE_B_HEADER_LOW = [1, 7, 2, 1, 4, 6, 2, 9]


def burst_to_lh_pairs(burst):
    """Convert burst to (L, H) unit pairs."""
    segments = []
    for i in range(1, len(burst)):
        state = burst[i-1][1]
        dur_us = (burst[i][0] - burst[i-1][0]) * 1e6
        segments.append((state, round(dur_us / PWM_UNIT_US)))
    
    pairs = []
    i = 0
    while i < len(segments):
        if segments[i][0] == 0:  # LOW
            l = segments[i][1]
            h = 0
            if i + 1 < len(segments) and segments[i+1][0] == 1:
                h = segments[i+1][1]
                i += 2
            else:
                i += 1
            pairs.append((l, h))
        else:
            i += 1
    return pairs


def is_type_b(pairs):
    if len(pairs) < len(TYPE_B_HEADER_LOW):
        return False
    return all(pairs[i][0] == TYPE_B_HEADER_LOW[i] for i in range(len(TYPE_B_HEADER_LOW)))


def corrected_symbols(pairs, start=0):
    """Compute corrected symbols: L + H - 1 for each pair.
    For last pair (H=0), use just L.
    Filter out crosstalk (H > threshold -> use L only)."""
    result = []
    for l, h in pairs[start:]:
        if h == 0:
            result.append(l)
        elif h > CROSSTALK_THRESHOLD:
            result.append(l)  # crosstalk: ignore H
        else:
            result.append(l + h - 1)
    return result


def raw_l_symbols(pairs, start=0):
    """Original L-only symbols."""
    return [l for l, h in pairs[start:]]


def extract_messages(filepath):
    channels, ncols = parse_capture(filepath)
    ch1 = channels.get(1, [])
    if not ch1:
        return []
    msgs = []
    for burst in find_bursts(ch1):
        pairs = burst_to_lh_pairs(burst)
        if not is_type_b(pairs):
            continue
        msgs.append({"time": burst[0][0], "pairs": pairs})
    return msgs


def find_delimiter(syms, start=5):
    """Find the 7,9 or 9,9 delimiter in corrected symbols."""
    for i in range(start, len(syms) - 1):
        if syms[i] == 7 and syms[i+1] == 9:
            return i, "7,9"
        if syms[i] == 9 and syms[i+1] == 9:
            return i, "9,9"
    return None, None


SYM_TO_OCT = {1:0, 2:1, 3:2, 4:3, 5:4, 6:5, 7:6, 9:7}

def syms_to_int(syms, big_endian=True):
    """Convert symbol list to integer using octal mapping."""
    octals = []
    for s in syms:
        if s in SYM_TO_OCT:
            octals.append(SYM_TO_OCT[s])
        else:
            return None  # invalid symbol
    if not octals:
        return None
    if big_endian:
        val = 0
        for o in octals:
            val = val * 8 + o
        return val
    else:
        val = 0
        for i, o in enumerate(octals):
            val += o * (8 ** i)
        return val


def check_monotonicity(values):
    """Return (score%, direction)."""
    if len(values) < 2:
        return 0, "N/A"
    inc = sum(1 for i in range(1, len(values)) if values[i] > values[i-1])
    dec = sum(1 for i in range(1, len(values)) if values[i] < values[i-1])
    total = len(values) - 1
    if inc >= dec:
        return inc / total * 100, "INC"
    else:
        return dec / total * 100, "DEC"


def analyze_file(filepath, label, expected_dir):
    msgs = extract_messages(filepath)
    if not msgs:
        print(f"  No Type B messages in {filepath}")
        return
    
    print(f"\n{'#'*100}")
    print(f"  {label}: {os.path.basename(filepath)} ({len(msgs)} msgs)")
    print(f"{'#'*100}")
    
    # Show corrected vs original side-by-side
    print(f"\n  {'Time':>8s}  {'L-only payload':>60s} | {'Corrected payload (L+H-1)':>60s}")
    print(f"  {'-'*140}")
    
    interpretations = {}
    
    for msg in msgs:
        pairs = msg["pairs"]
        payload_pairs = pairs[8:]  # skip header
        
        l_syms = raw_l_symbols(pairs, 8)
        c_syms = corrected_symbols(pairs, 8)
        
        t = msg["time"]
        
        # Show both
        l_str = ",".join(str(s) for s in l_syms)
        c_str = ",".join(str(s) for s in c_syms)
        
        # Mark differences
        diffs = []
        for i, (l, c) in enumerate(zip(l_syms, c_syms)):
            if l != c:
                diffs.append(f"p{i}:{l}→{c}")
        diff_str = " ".join(diffs) if diffs else "(same)"
        
        print(f"  {t:8.3f}s  {l_str:>60s} | {c_str:>60s}  {diff_str}")
        
        # Position field analysis on CORRECTED symbols
        # Try various starts for position field
        for pos_start in [5, 6, 7]:
            if pos_start >= len(c_syms):
                continue
            pos_syms = c_syms[pos_start:]
            
            # Full field as octal (various endianness)
            for be_label, be in [("BE", True), ("LE", False)]:
                val = syms_to_int(pos_syms, be)
                if val is not None:
                    key = f"corr_p{pos_start}_full_{be_label}"
                    interpretations.setdefault(key, []).append(val)
            
            # Find delimiter, split into A and B
            delim_idx, delim_type = find_delimiter(c_syms, pos_start)
            if delim_idx is not None:
                data_a = c_syms[pos_start:delim_idx]
                data_b = c_syms[delim_idx+2:]  # skip 2-symbol delimiter
                
                for be_label, be in [("BE", True), ("LE", False)]:
                    va = syms_to_int(data_a, be)
                    vb = syms_to_int(data_b, be)
                    if va is not None:
                        key = f"corr_A_{be_label}"
                        interpretations.setdefault(key, []).append(va)
                    if vb is not None:
                        key = f"corr_B_{be_label}"
                        interpretations.setdefault(key, []).append(vb)
                    if va is not None and vb is not None:
                        key = f"corr_A*512+B_{be_label}"
                        interpretations.setdefault(key, []).append(va * 512 + vb)
            
            # Fixed-width windows
            for w in [2, 3, 4]:
                for be_label, be in [("BE", True), ("LE", False)]:
                    if pos_start + w <= len(c_syms):
                        val = syms_to_int(c_syms[pos_start:pos_start+w], be)
                        if val is not None:
                            key = f"corr_p{pos_start}_w{w}_{be_label}"
                            interpretations.setdefault(key, []).append(val)
        
        # Total units & counts on corrected
        pos5 = c_syms[5:] if len(c_syms) > 5 else []
        interpretations.setdefault("corr_sum_syms", []).append(sum(pos5))
        interpretations.setdefault("corr_nsyms", []).append(len(pos5))
        
        # Also do L-only for comparison
        l_pos5 = l_syms[5:] if len(l_syms) > 5 else []
        interpretations.setdefault("lonly_sum_syms", []).append(sum(l_pos5))
        
        # NEW: sum of L+H for position field pairs (total duration)
        pos_pairs = payload_pairs[5:] if len(payload_pairs) > 5 else []
        total_dur = sum(l + h for l, h in pos_pairs if h <= CROSSTALK_THRESHOLD)
        interpretations.setdefault("total_duration", []).append(total_dur)
        
        # NEW: H-only values in position field
        h_vals = [h for _, h in pos_pairs if 0 < h <= CROSSTALK_THRESHOLD]
        interpretations.setdefault("sum_H_pos", []).append(sum(h_vals))
        interpretations.setdefault("sum_extraH_pos", []).append(sum(h - 1 for h in h_vals if h > 1))
    
    # Score all interpretations
    print(f"\n  {'Score':>6s} {'Match':>5s} {'Key':>35s} {'Dir':>5s} {'Min':>8s} {'Max':>8s} {'Rng':>8s}  Values (first 10)")
    print(f"  {'-'*120}")
    
    scored = []
    for key, vals in interpretations.items():
        if len(vals) < 3:
            continue
        score, direction = check_monotonicity(vals)
        match = "YES" if (direction == "INC" and expected_dir == "increasing") or \
                        (direction == "DEC" and expected_dir == "decreasing") else "no"
        scored.append((score, match, key, direction, vals))
    
    scored.sort(key=lambda x: (-x[0], x[2]))
    
    for score, match, key, direction, vals in scored[:30]:
        vmin, vmax = min(vals), max(vals)
        rng = vmax - vmin
        v_str = str(vals[:10]) + ("..." if len(vals) > 10 else "")
        print(f"  {score:5.1f}% {match:>5s} {key:>35s} {direction:>5s} {vmin:>8} {vmax:>8} {rng:>8}  {v_str}")


def main():
    base = os.path.dirname(__file__)
    
    analyze_file(os.path.join(base, "test04_open_full.txt"), "OPENING full travel", "increasing")
    analyze_file(os.path.join(base, "test05_close_full.txt"), "CLOSING full travel", "decreasing")
    
    # Also look at test06 (open, stop mid) and test08 (close, stop mid)
    analyze_file(os.path.join(base, "test06_open_stop_mid.txt"), "OPENING stop mid", "increasing")


if __name__ == "__main__":
    main()
