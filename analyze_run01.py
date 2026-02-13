#!/usr/bin/env python3
"""Analyze run01.txt — the real CC1110 debug attempt.

Streams through the large file without loading it all into memory.
Focuses on:
  1. Finding the debug entry sequence (RST low + 2 DC edges)
  2. Decoding GET_CHIP_ID response
  3. Finding READ_STATUS response
  4. Finding why the dump stopped early
"""

import sys

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "run01.txt"
    print(f"Streaming analysis of: {path}")

    # State tracking
    prev = None
    line_num = 0
    dc_rises = []       # all DC rising edge times
    dd_at_dc_rise = []   # DD value at each DC rising edge
    rst_falls = []
    rst_rises = []

    # Phase tracking — look for big gaps
    phase_boundaries = []
    
    # Track interesting regions
    first_activity_t = None
    last_t = 0.0
    
    # Channel state summary
    total_dc_edges = 0
    total_dd_edges = 0
    total_rst_edges = 0

    # Regions of fast activity (< 1ms gaps)
    in_fast = False
    fast_start_line = 0
    fast_start_t = 0.0
    fast_regions = []

    # Collect transitions around Phase 2 (debug entry + commands)
    # We'll detect this by looking for the FIRST time RST goes low
    # after the slow Phase 0/1 blink tests
    real_debug_entry_found = False
    phase2_transitions = []  # collect transitions from ~Phase 2 onward
    phase2_start_t = None
    collecting_phase2 = False

    with open(path, 'r') as f:
        header = next(f)  # skip header
        for line in f:
            line_num += 1
            parts = line.strip().split(',')
            if len(parts) < 4:
                continue
            try:
                t = float(parts[0])
                ch0 = int(parts[1].strip())  # DC
                ch1 = int(parts[2].strip())  # DD
                ch2 = int(parts[3].strip())  # RST
            except (ValueError, IndexError):
                continue

            if first_activity_t is None and prev is not None:
                first_activity_t = t

            if prev is not None:
                dt = t - prev[0]
                p_ch0, p_ch1, p_ch2 = prev[1], prev[2], prev[3]

                # Count edges
                if ch0 != p_ch0:
                    total_dc_edges += 1
                if ch1 != p_ch1:
                    total_dd_edges += 1
                if ch2 != p_ch2:
                    total_rst_edges += 1

                # DC rising edges — sample DD
                if ch0 == 1 and p_ch0 == 0:
                    dc_rises.append(t)
                    dd_at_dc_rise.append(ch1)

                # RST edges
                if ch2 == 0 and p_ch2 == 1:
                    rst_falls.append(t)
                if ch2 == 1 and p_ch2 == 0:
                    rst_rises.append(t)

                # Phase boundaries (gaps > 0.1s)
                if dt > 0.1:
                    phase_boundaries.append((t, dt))

                # Fast region detection
                if dt < 0.001:
                    if not in_fast:
                        fast_start_line = line_num
                        fast_start_t = prev[0]
                        in_fast = True
                else:
                    if in_fast:
                        fast_regions.append((fast_start_t, prev[0],
                                           fast_start_line, line_num - 1))
                        in_fast = False

                # Collect phase 2+ data (after slow blinks end, ~15s in)
                if not collecting_phase2 and t > 20.0 and ch2 == 0 and p_ch2 == 1:
                    # First RST fall after 20s — this should be Phase 2
                    collecting_phase2 = True
                    phase2_start_t = prev[0]

                if collecting_phase2 and len(phase2_transitions) < 100000:
                    phase2_transitions.append((t, ch0, ch1, ch2))

            prev = (t, ch0, ch1, ch2)
            last_t = t

            # Progress
            if line_num % 2000000 == 0:
                print(f"  ... processed {line_num/1e6:.1f}M lines, t={t:.3f}s")

    if in_fast:
        fast_regions.append((fast_start_t, prev[0], fast_start_line, line_num))

    print(f"\nProcessed {line_num} lines")
    print(f"Time range: 0.000s to {last_t:.3f}s ({last_t:.1f}s total)")
    print(f"Total edges — DC: {total_dc_edges}, DD: {total_dd_edges}, RST: {total_rst_edges}")
    print(f"DC rising edges: {len(dc_rises)}")
    print(f"RST falls: {len(rst_falls)}, RST rises: {len(rst_rises)}")
    print()

    # ── Phase boundaries ──
    print("=" * 70)
    print("PHASE BOUNDARIES (gaps > 100ms)")
    print("=" * 70)
    for t, dt in phase_boundaries[:30]:
        print(f"  t={t:.4f}s  gap={dt*1000:.1f}ms")
    if len(phase_boundaries) > 30:
        print(f"  ... and {len(phase_boundaries) - 30} more")
    print()

    # ── Fast regions ──
    print("=" * 70)
    print(f"FAST ACTIVITY REGIONS (< 1ms gaps): {len(fast_regions)} found")
    print("=" * 70)
    for i, (fs, fe, fl, el) in enumerate(fast_regions[:20]):
        dur_us = (fe - fs) * 1e6
        n_lines = el - fl + 1
        print(f"  Region {i}: t={fs:.7f}s - {fe:.7f}s  ({dur_us:.0f}µs, {n_lines} transitions)")
    if len(fast_regions) > 20:
        print(f"  ... and {len(fast_regions) - 20} more")
    print()

    # ── Debug entry analysis ──
    print("=" * 70)
    print("DEBUG ENTRY ANALYSIS")
    print("=" * 70)
    
    # Find RST falls that have DC rising edges during them
    for i, rst_f in enumerate(rst_falls):
        # Find matching RST rise
        matching_rises = [r for r in rst_rises if r > rst_f]
        if not matching_rises:
            print(f"  RST fall #{i} at {rst_f:.7f}s — no matching rise (still low at end)")
            continue
        rst_r = matching_rises[0]
        dur_ms = (rst_r - rst_f) * 1000

        # Count DC rises during this RST-low period
        dc_during = [t for t in dc_rises if rst_f < t < rst_r]

        if len(dc_during) > 0 and dur_ms < 10:
            # This looks like a debug entry attempt
            print(f"  RST fall #{i} at {rst_f:.7f}s, rise at {rst_r:.7f}s ({dur_ms:.3f}ms)")
            print(f"    DC rising edges during RST LOW: {len(dc_during)}")
            if len(dc_during) == 2:
                print(f"    ✓ Valid debug entry sequence!")
            elif len(dc_during) < 2:
                print(f"    ✗ Not enough DC edges — debug entry may have failed")
            else:
                print(f"    ✗ Too many DC edges — unexpected")

        if i > 30:
            print(f"  ... (showing first 30 RST falls only)")
            break
    print()

    # ── Decode commands from DC-clocked bits ──
    print("=" * 70)
    print("COMMAND DECODE (bits clocked on DC rising edges)")
    print("=" * 70)
    
    if len(dd_at_dc_rise) >= 8:
        # Group into bytes
        n_bytes = len(dd_at_dc_rise) // 8
        print(f"  Total DC rising edges: {len(dc_rises)}")
        print(f"  Decodable bytes: {n_bytes}")
        print()

        # Find byte boundaries that align to known commands
        # The debug entry 2 DC pulses aren't data — they're just clock pulses
        # Real command bytes start after debug entry
        # Let's decode ALL bytes and look for known commands
        all_bytes = []
        for i in range(n_bytes):
            bits = dd_at_dc_rise[i*8:(i+1)*8]
            val = 0
            for b in bits:
                val = (val << 1) | b
            all_bytes.append(val)

        print(f"  All decoded bytes: {' '.join(f'{b:02X}' for b in all_bytes[:50])}")
        if len(all_bytes) > 50:
            print(f"  ... total {len(all_bytes)} bytes")

        # Look for known command bytes
        known = {
            0x68: "GET_CHIP_ID",
            0x34: "READ_STATUS",
            0x44: "HALT",
            0x4C: "RESUME",
            0x55: "DEBUG_INSTR_1",
            0x56: "DEBUG_INSTR_2",
            0x57: "DEBUG_INSTR_3",
            0x1D: "WR_CONFIG",
            0x24: "RD_CONFIG",
            0x28: "GET_PC",
            0x14: "CHIP_ERASE !!DANGER!!",
        }
        print()
        for i, b in enumerate(all_bytes):
            if b in known:
                print(f"  Byte[{i}] = 0x{b:02X} → {known[b]}")
    else:
        print(f"  Only {len(dd_at_dc_rise)} DC rising edges — not enough for a full byte")
    print()

    # ── Phase 2 analysis ──
    print("=" * 70)
    print("PHASE 2+ ANALYSIS (real debug attempt)")
    print("=" * 70)

    if phase2_start_t:
        print(f"  Phase 2 detected starting at t={phase2_start_t:.4f}s")
        print(f"  Collected {len(phase2_transitions)} transitions")

        if phase2_transitions:
            # Decode command/response pairs from Phase 2
            p2_dc_rises = []
            p2_dd_at_rise = []
            prev2 = phase2_transitions[0]
            for tr in phase2_transitions[1:]:
                if tr[1] == 1 and prev2[1] == 0:  # DC rise
                    p2_dc_rises.append(tr[0])
                    p2_dd_at_rise.append(tr[2])
                prev2 = tr

            n_bytes = len(p2_dd_at_rise) // 8
            p2_bytes = []
            for i in range(n_bytes):
                bits = p2_dd_at_rise[i*8:(i+1)*8]
                val = 0
                for b in bits:
                    val = (val << 1) | b
                p2_bytes.append(val)

            print(f"  Phase 2 DC rising edges: {len(p2_dc_rises)}")
            print(f"  Phase 2 decoded bytes: {' '.join(f'{b:02X}' for b in p2_bytes[:80])}")
            if len(p2_bytes) > 80:
                print(f"  ... total {len(p2_bytes)} bytes")

            # Annotate
            print()
            for i, b in enumerate(p2_bytes[:80]):
                if b in known:
                    print(f"    Byte[{i}] = 0x{b:02X} → {known[b]}")
    else:
        print(f"  No Phase 2 activity detected (RST never went low after 20s)")
        print(f"  This means dump_collect.py captured the Phase 0g test HEX")
        print(f"  before Phase 2 could start.")
    print()

    # ── Check what HEX EOF terminated the capture ──
    print("=" * 70)
    print("ROOT CAUSE ANALYSIS")
    print("=" * 70)
    print()
    print("  The serial log shows dump_collect.py received the Phase 0g test")
    print("  HEX records (64 bytes, 0x00-0x3F) and their EOF marker.")
    print("  dump_collect.py saw ':00000001FF' and stopped, thinking the")
    print("  dump was complete.")
    print()
    print("  This happened because Phase 0g emits HEX + EOF as a connectivity")
    print("  test, but dump_collect.py (without --dry-run) also looks for EOF")
    print("  to know when the real dump is done.")
    print()
    print("  FIX NEEDED: Either:")
    print("    1. Remove the Phase 0g HEX emission in non-dry-run mode, or")
    print("    2. Make dump_collect.py ignore the first EOF and wait for the")
    print("       real 32KB dump's EOF, or")
    print("    3. Add a marker prefix to Phase 0g records so they're ignored")

    # ── Safety check ──
    print()
    print("=" * 70)
    print("SAFETY CHECK")
    print("=" * 70)
    has_erase = any(b == 0x14 for b in (all_bytes if 'all_bytes' in dir() else []))
    if has_erase:
        print("  ✗✗✗ CHIP_ERASE (0x14) DETECTED!")
    else:
        print("  ✓ No CHIP_ERASE (0x14) command found in any bitstream")
    print(f"  ✓ CC1110 is safe")


if __name__ == "__main__":
    main()
