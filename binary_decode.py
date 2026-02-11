"""Binary position decoder: position field encodes binary via active-low waveform.

Theory: Each (L,H) pair defines a waveform segment.
  - L time units at LOW level → bit value 1 (active-low: LOW=1)
  - H time units at HIGH level → bit value 0
  - Read LSB-first (first time unit = bit 0)

Both data_A and data_B independently encode binary counters.
Counter increases during OPENING, decreases during CLOSING.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from analyze import parse_capture, find_bursts, BURST_GAP_S

PWM_UNIT_US = 26.0
HDR_L = [1, 7, 2, 1, 4, 6, 2, 9]
CROSSTALK_THRESH = 10


def burst_to_pairs(burst):
    """Convert burst transitions to (L, H) pairs."""
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


def pairs_to_binary(pairs):
    """Convert (L,H) pairs to inverted-LSB binary value.
    
    LOW time units → bit 1 (active-low inversion)
    HIGH time units → bit 0
    LSB-first: first time unit = bit 0
    
    Returns (value, num_bits, bit_string)
    """
    bits = []
    for l, h in pairs:
        # Skip crosstalk-corrupted pairs
        if h > CROSSTALK_THRESH:
            continue
        bits.extend([1] * l)  # LOW = 1 (active-low)
        if h > 0:
            bits.extend([0] * h)  # HIGH = 0
    
    value = 0
    for i, bit in enumerate(bits):
        value += bit * (1 << i)
    
    bit_str = ''.join(str(b) for b in bits)
    return value, len(bits), bit_str


def extract_messages(filepath):
    """Extract Type B messages with full (L,H) pairs."""
    channels, _ = parse_capture(filepath)
    ch1 = channels.get(1, [])
    if not ch1:
        return []
    msgs = []
    for burst in find_bursts(ch1):
        pairs = burst_to_pairs(burst)
        if len(pairs) < 8:
            continue
        if [l for l, h in pairs[:8]] != HDR_L:
            continue
        msgs.append({"time": burst[0][0], "pairs": pairs[8:]})  # payload only
    return msgs


def find_delim(l_syms, start=0):
    """Find first 7,9 or 9,9 delimiter in L-only symbols."""
    for i in range(start, len(l_syms) - 1):
        if (l_syms[i] == 7 and l_syms[i+1] == 9) or \
           (l_syms[i] == 9 and l_syms[i+1] == 9):
            return i, f"{l_syms[i]},{l_syms[i+1]}"
    return None, None


def decode_position_field(payload_pairs):
    """Decode the position field from payload (L,H) pairs.
    
    Returns dict with: state, prefix, delimiter, A_value, B_value, 
    A_bits, B_bits, full_value, full_bits
    """
    l_syms = [l for l, h in payload_pairs]
    
    state = l_syms[:2]
    
    # Position field starts at payload index 5
    pos_pairs = payload_pairs[5:]
    pos_l = [l for l, h in pos_pairs]
    
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
    
    # Find delimiter
    delim_idx, delim_type = find_delim(pos_l, data_start)
    
    if delim_idx is None:
        # No delimiter - can't split A/B
        a_pairs = pos_pairs[data_start:]
        b_pairs = []
        delim_type = "none"
    else:
        a_pairs = pos_pairs[data_start:delim_idx]
        b_pairs = pos_pairs[delim_idx + 2:]  # skip 2 delimiter pairs
    
    # Decode each region as binary
    a_val, a_bits, a_str = pairs_to_binary(a_pairs) if a_pairs else (0, 0, "")
    b_val, b_bits, b_str = pairs_to_binary(b_pairs) if b_pairs else (0, 0, "")
    
    # Full position field as one bitstream
    full_val, full_bits, full_str = pairs_to_binary(pos_pairs) if pos_pairs else (0, 0, "")
    
    return {
        "state": state,
        "prefix": prefix,
        "delim": delim_type if delim_type else "none",
        "A_val": a_val,
        "A_bits": a_bits,
        "A_str": a_str,
        "B_val": b_val,
        "B_bits": b_bits,
        "B_str": b_str,
        "full_val": full_val,
        "full_bits": full_bits,
    }


def analyze_file(filepath, label, expected_dir):
    """Analyze one capture file and report binary-decoded positions."""
    msgs = extract_messages(filepath)
    if not msgs:
        print(f"  No messages in {filepath}")
        return
    
    print(f"\n{'=' * 120}")
    print(f"  {label}: {os.path.basename(filepath)} ({len(msgs)} msgs, expected: {expected_dir})")
    print(f"{'=' * 120}")
    print(f"  {'Time':>8s}  {'St':>5s} {'Pfx':>4s} {'Dlm':>4s}  "
          f"{'A_val':>6s}({'Ab':>2s})  {'B_val':>6s}({'Bb':>2s})  "
          f"{'Full':>16s}({'Fb':>2s})  {'A-B':>6s}")
    
    a_vals = []
    b_vals = []
    full_vals = []
    
    for msg in msgs:
        d = decode_position_field(msg["pairs"])
        t = msg["time"]
        
        a_vals.append(d["A_val"])
        b_vals.append(d["B_val"])
        full_vals.append(d["full_val"])
        
        diff = d["A_val"] - d["B_val"] if d["B_val"] > 0 else "n/a"
        
        print(f"  {t:8.3f}s  {str(d['state']):>5s} {d['prefix']:>4s} {d['delim']:>4s}  "
              f"{d['A_val']:>6d}({d['A_bits']:>2d})  {d['B_val']:>6d}({d['B_bits']:>2d})  "
              f"{d['full_val']:>16d}({d['full_bits']:>2d})  {str(diff):>6s}")
    
    # Summary and monotonicity analysis
    print(f"\n  --- A binary values ---")
    print(f"  Values: {a_vals}")
    check_monotonicity("A", a_vals)
    
    print(f"\n  --- B binary values ---")
    print(f"  Values: {b_vals}")
    check_monotonicity("B", b_vals)
    
    print(f"\n  --- Full field binary values ---")
    print(f"  Values: {full_vals}")
    check_monotonicity("Full", full_vals)
    
    # Check A-B relationship
    if any(b > 0 for b in b_vals):
        diffs = [a - b for a, b in zip(a_vals, b_vals) if b > 0]
        if diffs:
            print(f"\n  --- A-B differences ---")
            print(f"  Diffs: {diffs}")
            if len(set(diffs)) == 1:
                print(f"  A - B = CONSTANT {diffs[0]} (redundant encoding!)")
            else:
                print(f"  A - B varies: {min(diffs)} to {max(diffs)}")


def check_monotonicity(name, vals):
    """Check and report monotonicity of a value sequence."""
    if len(vals) < 2:
        return
    
    inc = sum(1 for i in range(1, len(vals)) if vals[i] > vals[i-1])
    dec = sum(1 for i in range(1, len(vals)) if vals[i] < vals[i-1])
    eq = sum(1 for i in range(1, len(vals)) if vals[i] == vals[i-1])
    total = len(vals) - 1
    
    if inc > 0 and dec == 0:
        direction = "STRICTLY INCREASING"
    elif dec > 0 and inc == 0:
        direction = "STRICTLY DECREASING"
    elif inc > dec:
        direction = f"MOSTLY INCREASING (inc={inc} dec={dec} eq={eq})"
    elif dec > inc:
        direction = f"MOSTLY DECREASING (inc={inc} dec={dec} eq={eq})"
    else:
        direction = f"MIXED (inc={inc} dec={dec} eq={eq})"
    
    pct = max(inc, dec) / total * 100 if total > 0 else 0
    
    print(f"  {name}: {direction}")
    print(f"  Range: {min(vals)} to {max(vals)}")
    print(f"  Monotonicity: {pct:.1f}% ({max(inc,dec)}/{total} transitions)")
    
    # Show any reversals
    reversals = []
    for i in range(1, len(vals)):
        if inc >= dec and vals[i] < vals[i-1]:
            reversals.append((i, vals[i-1], vals[i]))
        elif dec > inc and vals[i] > vals[i-1]:
            reversals.append((i, vals[i-1], vals[i]))
    if reversals:
        print(f"  Reversals: {reversals}")


def unwrap_positions(b_vals, direction="auto"):
    """Unwrap B values that wrap mod 512 (9-bit counter).
    
    Direction: 'inc' = opening, 'dec' = closing, 'auto' = detect from data.
    Returns list of unwrapped position values.
    """
    if not b_vals:
        return []
    
    # Filter out 0 values (no B data, e.g. transitional messages)
    result = []
    wrap_offset = 0
    prev = None
    
    for b in b_vals:
        if b == 0:
            result.append(None)  # No position data
            continue
        
        if prev is not None:
            delta = b - prev
            # Detect wrap: large positive jump = wrapping down (closing)
            # Large negative jump = wrapping up (opening)
            if delta < -256:  # Wrapped up: 511 -> small (opening)  
                wrap_offset += 512
            elif delta > 256:  # Wrapped down: small -> 511 (closing)
                wrap_offset -= 512
        
        result.append(b + wrap_offset)
        prev = b
    
    return result


def analyze_file_unwrapped(filepath, label):
    """Analyze file with unwrapped position output."""
    msgs = extract_messages(filepath)
    if not msgs:
        print(f"  No messages in {filepath}")
        return
    
    print(f"\n{'=' * 100}")
    print(f"  {label}: {os.path.basename(filepath)} ({len(msgs)} msgs)")
    print(f"{'=' * 100}")
    print(f"  {'#':>3s} {'Time':>8s}  {'St':>5s} {'Pfx':>4s} {'Dlm':>4s}  "
          f"{'A':>6s}({'Ab':>2s})  {'B':>5s}({'Bb':>2s})  "
          f"{'Pos':>5s}  {'Step':>5s}  {'A-B':>6s}")
    
    b_vals = []
    a_vals = []
    
    for msg in msgs:
        d = decode_position_field(msg["pairs"])
        b_vals.append(d["B_val"])
        a_vals.append(d["A_val"])
    
    # Unwrap B values
    positions = unwrap_positions(b_vals)
    
    for i, msg in enumerate(msgs):
        d = decode_position_field(msg["pairs"])
        t = msg["time"]
        
        pos = positions[i]
        pos_str = f"{pos:>5d}" if pos is not None else "  n/a"
        
        step = ""
        if i > 0 and positions[i] is not None and positions[i-1] is not None:
            s = positions[i] - positions[i-1]
            step = f"{s:>+5d}"
        
        diff = d["A_val"] - d["B_val"] if d["B_val"] > 0 else "n/a"
        
        print(f"  {i:>3d} {t:8.3f}s  {str(d['state']):>5s} {d['prefix']:>4s} {d['delim']:>4s}  "
              f"{d['A_val']:>6d}({d['A_bits']:>2d})  {d['B_val']:>5d}({d['B_bits']:>2d})  "
              f"{pos_str}  {step:>5s}  {str(diff):>6s}")
    
    # Monotonicity of unwrapped positions  
    valid_pos = [p for p in positions if p is not None]
    if len(valid_pos) > 1:
        print(f"\n  --- Unwrapped Position ---")
        print(f"  Range: {min(valid_pos)} to {max(valid_pos)}")
        inc = sum(1 for i in range(1, len(valid_pos)) if valid_pos[i] > valid_pos[i-1])
        dec = sum(1 for i in range(1, len(valid_pos)) if valid_pos[i] < valid_pos[i-1])
        eq = sum(1 for i in range(1, len(valid_pos)) if valid_pos[i] == valid_pos[i-1])
        total = len(valid_pos) - 1
        mono = max(inc, dec) + eq
        print(f"  Monotonic transitions: {mono}/{total} = {mono/total*100:.1f}%")
        if inc > dec:
            print(f"  Direction: INCREASING (opening) — inc={inc} dec={dec} eq={eq}")
        else:
            print(f"  Direction: DECREASING (closing) — inc={inc} dec={dec} eq={eq}")
        
        # Show any reversals
        for i in range(1, len(valid_pos)):
            if inc >= dec and valid_pos[i] < valid_pos[i-1]:
                print(f"  !! Reversal at index {i}: {valid_pos[i-1]} -> {valid_pos[i]}")
            elif dec > inc and valid_pos[i] > valid_pos[i-1]:
                print(f"  !! Reversal at index {i}: {valid_pos[i-1]} -> {valid_pos[i]}")


def main():
    base = os.path.dirname(__file__)
    
    test_files = [
        ('test04_open_full.txt', 'OPENING full'),
        ('test05_close_full.txt', 'CLOSING full'),
        ('test06_open_stop_mid.txt', 'OPEN stop mid'),
        ('test07_resume_open.txt', 'RESUME (closing)'),
    ]
    
    for fname, label in test_files:
        path = os.path.join(base, fname)
        if os.path.exists(path):
            analyze_file_unwrapped(path, label)


if __name__ == "__main__":
    main()
