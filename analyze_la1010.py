#!/usr/bin/env python3
"""Analyze LA1010 dry-run capture of the CC1110 debug firmware.

Reads the CSV export and verifies:
  - Phase 0a: RESET_N (CH2) blinks 3x alone
  - Phase 0b: DC (CH0) blinks 3x alone
  - Phase 0c: DD (CH1) blinks 3x alone
  - Phase 0d: All three blink 3x together
  - Phase 0e: Debug entry sequence (RST low → 2 DC edges → RST high)
  - Phase 0f: GET_CHIP_ID command (0x68) bit pattern on DD clocked by DC
  - Phase 1: Connectivity test (similar to Phase 0)
"""

import csv
import sys


def load_capture(path):
    """Load CSV: returns list of (time, ch0, ch1, ch2) tuples."""
    samples = []
    with open(path, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if len(row) < 4:
                continue
            t = float(row[0].strip())
            ch0 = int(row[1].strip())
            ch1 = int(row[2].strip())
            ch2 = int(row[3].strip())
            samples.append((t, ch0, ch1, ch2))
    return samples


def find_edges(samples, ch_idx):
    """Find all edges on a given channel. Returns list of (time, direction, ch0, ch1, ch2)."""
    edges = []
    for i in range(1, len(samples)):
        prev_val = samples[i-1][ch_idx]
        curr_val = samples[i][ch_idx]
        if curr_val != prev_val:
            direction = "RISE" if curr_val == 1 else "FALL"
            edges.append((samples[i][0], direction, samples[i][1], samples[i][2], samples[i][3]))
    return edges


def find_pulses(samples, ch_idx):
    """Find high pulses on a channel. Returns list of (start_time, end_time, duration)."""
    edges = find_edges(samples, ch_idx)
    pulses = []
    rise_time = None
    for t, direction, *_ in edges:
        if direction == "RISE":
            rise_time = t
        elif direction == "FALL" and rise_time is not None:
            pulses.append((rise_time, t, t - rise_time))
            rise_time = None
    return pulses


def find_low_pulses(samples, ch_idx):
    """Find low pulses (active-low signals like RESET_N)."""
    edges = find_edges(samples, ch_idx)
    pulses = []
    fall_time = None
    for t, direction, *_ in edges:
        if direction == "FALL":
            fall_time = t
        elif direction == "RISE" and fall_time is not None:
            pulses.append((fall_time, t, t - fall_time))
            fall_time = None
    return pulses


def decode_debug_entry(samples, start_t, end_t):
    """Check debug entry sequence: RST low → 2 DC rising edges → RST high."""
    # Filter samples in time window
    window = [(t, ch0, ch1, ch2) for t, ch0, ch1, ch2 in samples
              if start_t <= t <= end_t]

    if not window:
        return "No samples in window"

    # Find RST (CH2) edges
    rst_edges = []
    for i in range(1, len(window)):
        if window[i][3] != window[i-1][3]:
            rst_edges.append((window[i][0], "RISE" if window[i][3] == 1 else "FALL"))

    # Find DC (CH0) rising edges
    dc_rises = []
    for i in range(1, len(window)):
        if window[i][1] == 1 and window[i-1][1] == 0:
            dc_rises.append(window[i][0])

    return rst_edges, dc_rises


def decode_spi_command(samples, start_t, end_t):
    """Decode bits clocked on DD (CH1) by DC (CH0) rising edges."""
    window = [(t, ch0, ch1, ch2) for t, ch0, ch1, ch2 in samples
              if start_t <= t <= end_t]

    bits = []
    for i in range(1, len(window)):
        # DC rising edge
        if window[i][1] == 1 and window[i-1][1] == 0:
            # DD value at this moment
            dd_val = window[i][2]
            bits.append(dd_val)

    return bits


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "dry_run.txt"
    print(f"Loading capture: {path}")
    samples = load_capture(path)
    print(f"Loaded {len(samples)} transition records")
    print(f"Time range: {samples[0][0]:.4f}s to {samples[-1][0]:.4f}s")
    print(f"Initial state: CH0(DC)={samples[0][1]} CH1(DD)={samples[0][2]} CH2(RST)={samples[0][3]}")
    print()

    # Channel mapping
    CH_DC = 1   # index into tuple (0-based after time)
    CH_DD = 2
    CH_RST = 3

    # ── Overview: find all edges per channel ──
    dc_edges = find_edges(samples, CH_DC)
    dd_edges = find_edges(samples, CH_DD)
    rst_edges = find_edges(samples, CH_RST)

    print(f"Total edges — DC(CH0): {len(dc_edges)}, DD(CH1): {len(dd_edges)}, RST(CH2): {len(rst_edges)}")
    print()

    # ── Print all transitions with timestamps ──
    print("=" * 70)
    print("FULL TRANSITION LOG")
    print("=" * 70)
    for i in range(len(samples)):
        t, ch0, ch1, ch2 = samples[i]
        if i == 0:
            print(f"  {t:12.7f}s  DC={ch0} DD={ch1} RST={ch2}  (initial)")
            continue
        prev = samples[i-1]
        changes = []
        if ch0 != prev[1]:
            changes.append(f"DC {'↑' if ch0 else '↓'}")
        if ch1 != prev[2]:
            changes.append(f"DD {'↑' if ch1 else '↓'}")
        if ch2 != prev[3]:
            changes.append(f"RST {'↑' if ch2 else '↓'}")
        dt = t - prev[0]
        gap_str = ""
        if dt > 0.01:
            gap_str = f"  (gap {dt*1000:.1f}ms)"
        elif dt > 0.0001:
            gap_str = f"  (gap {dt*1000000:.0f}µs)"
        print(f"  {t:12.7f}s  DC={ch0} DD={ch1} RST={ch2}  {' '.join(changes)}{gap_str}")
    print()

    # ── Identify phases by timing gaps ──
    print("=" * 70)
    print("PHASE IDENTIFICATION")
    print("=" * 70)

    # Find large gaps (>0.5s) to separate phases
    phases = []
    phase_start = 0
    for i in range(1, len(samples)):
        dt = samples[i][0] - samples[i-1][0]
        if dt > 0.3:  # gap > 300ms = phase boundary
            phases.append((samples[phase_start][0], samples[i-1][0],
                          phase_start, i-1))
            phase_start = i
    phases.append((samples[phase_start][0], samples[-1][0],
                  phase_start, len(samples)-1))

    for pi, (ps, pe, si, ei) in enumerate(phases):
        n_samples = ei - si + 1
        dur = pe - ps
        print(f"  Phase block {pi}: {ps:.4f}s - {pe:.4f}s  ({dur*1000:.0f}ms, {n_samples} transitions)")

        # Count edges per channel in this phase
        dc_e = dd_e = rst_e = 0
        for j in range(si+1, ei+1):
            if samples[j][1] != samples[j-1][1]: dc_e += 1
            if samples[j][2] != samples[j-1][2]: dd_e += 1
            if samples[j][3] != samples[j-1][3]: rst_e += 1
        print(f"           Edges: DC={dc_e} DD={dd_e} RST={rst_e}")

    print()

    # ── Decode the fast burst near the end (Phase 0e + 0f) ──
    print("=" * 70)
    print("DEBUG ENTRY SEQUENCE ANALYSIS (Phase 0e)")
    print("=" * 70)

    # Find the fast burst: look for samples with small gaps (<1ms)
    fast_regions = []
    in_fast = False
    fast_start = 0
    for i in range(1, len(samples)):
        dt = samples[i][0] - samples[i-1][0]
        if dt < 0.001:  # < 1ms gap
            if not in_fast:
                fast_start = i - 1
                in_fast = True
        else:
            if in_fast:
                fast_regions.append((fast_start, i-1))
                in_fast = False
    if in_fast:
        fast_regions.append((fast_start, len(samples)-1))

    for ri, (fs, fe) in enumerate(fast_regions):
        t_start = samples[fs][0]
        t_end = samples[fe][0]
        print(f"\n  Fast region {ri}: {t_start:.7f}s - {t_end:.7f}s "
              f"({(t_end-t_start)*1000000:.0f}µs, {fe-fs+1} transitions)")

        # Check for debug entry pattern: RST fall, DC rises, RST rise
        rst_falls = []
        rst_rises = []
        dc_rises = []
        for j in range(fs+1, fe+1):
            if samples[j][3] == 0 and samples[j-1][3] == 1:
                rst_falls.append(samples[j][0])
            if samples[j][3] == 1 and samples[j-1][3] == 0:
                rst_rises.append(samples[j][0])
            if samples[j][1] == 1 and samples[j-1][1] == 0:
                dc_rises.append(samples[j][0])

        if rst_falls and dc_rises and rst_rises:
            print(f"    RST falls at: {[f'{t:.7f}' for t in rst_falls]}")
            print(f"    DC rises at:  {[f'{t:.7f}' for t in dc_rises]}")
            print(f"    RST rises at: {[f'{t:.7f}' for t in rst_rises]}")

            # Verify sequence: RST fall → DC rises → RST rise
            if rst_falls[0] < dc_rises[0] and dc_rises[-1] < rst_rises[-1]:
                print(f"    ✓ CORRECT: RST went LOW before DC pulses, HIGH after")
                dc_during_rst = [t for t in dc_rises
                                 if any(rf < t for rf in rst_falls) and
                                 any(t < rr for rr in rst_rises)]
                print(f"    DC rising edges while RST LOW: {len(dc_during_rst)} (need exactly 2)")
                if len(dc_during_rst) == 2:
                    print(f"    ✓ CORRECT: Exactly 2 DC rising edges during reset — debug entry is valid!")
                else:
                    print(f"    ✗ WRONG: Expected 2, got {len(dc_during_rst)}")
            else:
                print(f"    ✗ WRONG ORDER: RST/DC timing is incorrect")

        # Decode SPI-like command bits
        bits = []
        for j in range(fs+1, fe+1):
            # DC rising edge → sample DD
            if samples[j][1] == 1 and samples[j-1][1] == 0:
                bits.append(samples[j][2])  # DD value

        if len(bits) > 2:
            print(f"    All bits clocked on DC rising edges: {bits}")
            if len(bits) >= 8:
                # Try to decode as bytes
                for byte_start in range(0, len(bits) - 7, 8):
                    byte_bits = bits[byte_start:byte_start+8]
                    val = 0
                    for b in byte_bits:
                        val = (val << 1) | b
                    print(f"    Byte at bit[{byte_start}]: "
                          f"{''.join(str(b) for b in byte_bits)} = 0x{val:02X}")
                    if val == 0x68:
                        print(f"    ✓ This is GET_CHIP_ID (0x68)!")
                    elif val == 0x34:
                        print(f"    This is READ_STATUS (0x34)")
                    elif val == 0x44:
                        print(f"    This is HALT (0x44)")

    # ── Safety Assessment ──
    print()
    print("=" * 70)
    print("SAFETY ASSESSMENT")
    print("=" * 70)

    # Check that CHIP_ERASE (0x14) is never sent
    all_dc_rises = []
    all_dd_at_rise = []
    for i in range(1, len(samples)):
        if samples[i][1] == 1 and samples[i-1][1] == 0:
            all_dc_rises.append(samples[i][0])
            all_dd_at_rise.append(samples[i][2])

    bytes_sent = []
    for i in range(0, len(all_dd_at_rise) - 7, 8):
        val = 0
        for b in all_dd_at_rise[i:i+8]:
            val = (val << 1) | b
        bytes_sent.append(val)

    print(f"  Total DC rising edges: {len(all_dc_rises)}")
    print(f"  Decoded bytes (from all DC-clocked bits): {['0x%02X' % b for b in bytes_sent]}")

    if 0x14 in bytes_sent:
        print(f"  ✗✗✗ DANGER: CHIP_ERASE (0x14) detected in byte stream! ✗✗✗")
    else:
        print(f"  ✓ SAFE: No CHIP_ERASE (0x14) command detected")

    # Check the debug entry is correct
    print()
    print(f"  Initial state: DC={samples[0][1]} DD={samples[0][2]} RST={samples[0][3]}")
    expected_idle = (0, 1, 1)  # DC=0, DD=1 (pull-up), RST=1 (inactive)
    actual_idle = (samples[0][1], samples[0][2], samples[0][3])
    if actual_idle == expected_idle:
        print(f"  ✓ Idle state correct: DC=LOW, DD=HIGH(pull-up), RST=HIGH(inactive)")
    else:
        print(f"  ✗ Idle state unexpected: got DC={actual_idle[0]} DD={actual_idle[1]} RST={actual_idle[2]}")
        print(f"    Expected DC=0 DD=1 RST=1")

    # Final state
    final = samples[-1]
    print(f"  Final state: DC={final[1]} DD={final[2]} RST={final[3]}")


if __name__ == "__main__":
    main()
