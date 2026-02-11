"""Raw signal duration viewer.

Outputs alternating HIGH/LOW durations for each channel, divided by 26µs.
Shows the actual signal structure without any PWM decoding assumptions.
"""
import sys
import os

PWM_UNIT_US = 26.0

sys.path.insert(0, os.path.dirname(__file__))
from analyze import parse_capture, find_bursts, BURST_GAP_S


def burst_to_units(burst):
    """Convert a burst to a list of durations in 26µs units.
    
    Returns list of (state, units) pairs and a flat list of rounded units
    alternating starting with the first transition's state.
    """
    pairs = []
    for i in range(1, len(burst)):
        state = burst[i-1][1]
        dur_us = (burst[i][0] - burst[i-1][0]) * 1e6
        units = dur_us / PWM_UNIT_US
        pairs.append((state, units))
    return pairs


def format_burst(burst):
    """Format a burst as alternating duration units, annotated with H/L."""
    pairs = burst_to_units(burst)
    parts = []
    for state, units in pairs:
        r = round(units)
        frac = abs(units - r)
        tag = "H" if state == 1 else "L"
        if frac > 0.15:
            parts.append(f"{units:.1f}{tag}")
        else:
            parts.append(f"{r}{tag}")
    return parts


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <capture_file> [--ch 0|1|both] [--burst N]")
        print(f"  Outputs alternating H/L durations in 26µs units per burst.")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isabs(filepath):
        filepath = os.path.join(os.path.dirname(__file__), filepath)

    # Parse optional args
    show_ch = "both"
    show_burst = None
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--ch" and i + 1 < len(sys.argv):
            show_ch = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--burst" and i + 1 < len(sys.argv):
            show_burst = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    channels, ncols = parse_capture(filepath)
    print(f"File: {os.path.basename(filepath)}  (ncols={ncols})")

    for ch_id in sorted(channels.keys()):
        if show_ch != "both" and str(ch_id) != show_ch:
            continue
        transitions = channels[ch_id]
        if not transitions:
            continue

        bursts = find_bursts(transitions)
        print(f"\n{'='*80}")
        print(f"  CH{ch_id}  ({len(transitions)} transitions, {len(bursts)} bursts)")
        print(f"{'='*80}")

        for bi, burst in enumerate(bursts):
            if show_burst is not None and bi != show_burst:
                continue
            t_start = burst[0][0]
            parts = format_burst(burst)
            n_transitions = len(burst)

            # Also show just the rounded integer sequence
            pairs = burst_to_units(burst)
            int_seq = []
            for state, units in pairs:
                int_seq.append(round(units))

            print(f"\n  Burst {bi:2d} @ {t_start:.4f}s  ({n_transitions} transitions)")
            # Show annotated version
            print(f"    {', '.join(parts)}")
            # Show plain integer sequence
            print(f"    [{', '.join(str(x) for x in int_seq)}]")


if __name__ == "__main__":
    main()
