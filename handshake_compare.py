#!/usr/bin/env python3
"""handshake_compare.py — Compare variable boot handshake (L,H) durations across all captures."""

import analyze as A
from collections import defaultdict


def extract_handshake_messages():
    """Extract all variable handshake messages from all boot-containing files."""
    boot_sequences = []

    for path, info in A.TEST_FILES.items():
        try:
            channels, _ = A.parse_capture(path)
        except:
            continue

        all_msgs = []
        for ch_idx in range(len(channels)):
            ch = channels[ch_idx]
            if ch is None or not isinstance(ch, list) or len(ch) == 0:
                continue
            if not isinstance(ch[0], (tuple, list)):
                continue
            bursts = A.find_bursts(ch)
            for burst in bursts:
                if A.classify_burst(burst) != 'data':
                    continue
                syms, _ = A.decode_pwm(burst)
                if ch_idx == 0:
                    name, _, _, _ = A.classify_ch0(syms)
                else:
                    name, _, _, _ = A.classify_ch1(syms)
                t = burst[0][0]
                all_msgs.append((t, ch_idx, name, syms, burst, path))

        if not all_msgs:
            continue
        all_msgs.sort(key=lambda x: x[0])

        cycle = None
        last_handshake_t = -999

        for t, ch_idx, name, syms, burst, p in all_msgs:
            if name in ('CMD-B-INIT', 'HANDSHAKE-D', 'HANDSHAKE-E'):
                if cycle is None or (t - last_handshake_t) > 10:
                    cycle = {'file': path, 'msgs': []}
                    boot_sequences.append(cycle)
                cycle['msgs'].append({
                    'time': t,
                    'channel': ch_idx,
                    'name': name,
                    'syms': syms,
                    'burst': burst,
                })
                last_handshake_t = t

    return boot_sequences


def pairs_str(pairs):
    return "  ".join(f"({l},{h})" for l, h in pairs)


def main():
    boot_sequences = extract_handshake_messages()

    print(f"Found {len(boot_sequences)} boot cycle(s) across all files\n")
    print("=" * 120)

    variable_exchanges = []

    for i, cycle in enumerate(boot_sequences):
        cmd_b_short = []
        cmd_b_long = []
        handshake_d = []
        handshake_e = []

        for msg in cycle['msgs']:
            if msg['name'] == 'CMD-B-INIT':
                if len(msg['syms']) <= 22:
                    cmd_b_short.append(msg)
                else:
                    cmd_b_long.append(msg)
            elif msg['name'] == 'HANDSHAKE-D':
                handshake_d.append(msg)
            elif msg['name'] == 'HANDSHAKE-E':
                handshake_e.append(msg)

        if cmd_b_long or handshake_e:
            variable_exchanges.append({
                'cycle': i + 1,
                'file': cycle['file'],
                'cmd_b_short': cmd_b_short,
                'cmd_b_long': cmd_b_long,
                'handshake_d': handshake_d,
                'handshake_e': handshake_e,
            })

    print(f"\n{len(variable_exchanges)} boot cycle(s) with variable handshake data\n")

    # === Part 1: Show each cycle's full handshake in order ===
    for ex in variable_exchanges:
        print(f"\n{'=' * 120}")
        print(f"Boot Cycle {ex['cycle']}  —  {ex['file']}")
        print(f"{'=' * 120}")

        all_in_cycle = []
        for msg in ex['cmd_b_short']:
            all_in_cycle.append(msg)
        for msg in ex['cmd_b_long']:
            all_in_cycle.append(msg)
        for msg in ex['handshake_d']:
            all_in_cycle.append(msg)
        for msg in ex['handshake_e']:
            all_in_cycle.append(msg)
        all_in_cycle.sort(key=lambda m: m['time'])

        for msg in all_in_cycle:
            ch_label = "CH0→" if msg['channel'] == 0 else "←CH1"
            pairs = A.burst_to_lh_pairs(msg['burst'])
            is_variable = (msg['name'] == 'CMD-B-INIT' and len(msg['syms']) > 22) or msg['name'] == 'HANDSHAKE-E'
            marker = " *** VARIABLE ***" if is_variable else " (constant)"

            print(f"\n  {ch_label} {msg['name']:15s} t={msg['time']:.3f}s  syms={len(msg['syms'])}  pairs={len(pairs)}{marker}")
            print(f"       Symbols: {msg['syms']}")
            print(f"       (L,H):  {pairs_str(pairs)}")

    # === Part 2: Side-by-side comparison of VARIABLE messages only ===
    CMD_B_INIT_HDR = 8
    HANDSHAKE_E_HDR = 8

    print(f"\n\n{'#' * 120}")
    print(f"#  VARIABLE MESSAGE COMPARISON — CMD-B-INIT long form (CH0 challenge)")
    print(f"{'#' * 120}\n")

    for ex in variable_exchanges:
        for msg in ex['cmd_b_long']:
            pairs = A.burst_to_lh_pairs(msg['burst'])
            syms = msg['syms']
            var_syms = syms[CMD_B_INIT_HDR:]

            print(f"  Cycle {ex['cycle']:2d} [{ex['file']:40s}]  len={len(syms):2d}  "
                  f"hdr={syms[:CMD_B_INIT_HDR]}  var_payload={var_syms}")
            print(f"           (L,H) pairs ({len(pairs):2d}): {pairs_str(pairs)}")
            print()

    print(f"\n{'#' * 120}")
    print(f"#  VARIABLE MESSAGE COMPARISON — HANDSHAKE-E (CH1 response)")
    print(f"{'#' * 120}\n")

    for ex in variable_exchanges:
        for msg in ex['handshake_e']:
            pairs = A.burst_to_lh_pairs(msg['burst'])
            syms = msg['syms']
            var_syms = syms[HANDSHAKE_E_HDR:]

            print(f"  Cycle {ex['cycle']:2d} [{ex['file']:40s}]  len={len(syms):2d}  "
                  f"hdr={syms[:HANDSHAKE_E_HDR]}  var_payload={var_syms}")
            print(f"           (L,H) pairs ({len(pairs):2d}): {pairs_str(pairs)}")
            print()

    # === Part 3: Paired challenge-response table ===
    print(f"\n{'#' * 120}")
    print(f"#  PAIRED CHALLENGE → RESPONSE (variable portions only)")
    print(f"{'#' * 120}\n")

    for ex in variable_exchanges:
        if not ex['cmd_b_long'] or not ex['handshake_e']:
            continue

        challenge = ex['cmd_b_long'][0]
        response = ex['handshake_e'][0]

        c_pairs = A.burst_to_lh_pairs(challenge['burst'])
        r_pairs = A.burst_to_lh_pairs(response['burst'])

        c_syms = challenge['syms'][CMD_B_INIT_HDR:]
        r_syms = response['syms'][HANDSHAKE_E_HDR:]

        print(f"  Cycle {ex['cycle']:2d}  ({ex['file']})")
        print(f"    Challenge L-syms ({len(c_syms):2d}): {c_syms}")
        print(f"    Response  L-syms ({len(r_syms):2d}): {r_syms}")
        print(f"    Challenge (L,H)  ({len(c_pairs):2d}): {pairs_str(c_pairs)}")
        print(f"    Response  (L,H)  ({len(r_pairs):2d}): {pairs_str(r_pairs)}")
        print()


if __name__ == "__main__":
    main()
