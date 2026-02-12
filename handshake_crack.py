#!/usr/bin/env python3
"""handshake_crack.py — Numeric analysis of challenge-response pairs to find the transform."""

import analyze as A
import itertools
import math
from collections import Counter

CMD_B_INIT_HDR = 8
HANDSHAKE_E_HDR = 8


def extract_pairs():
    """Return list of (challenge_lh_pairs, response_lh_pairs) for variable portion only."""
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
        last_t = -999
        for t, ch_idx, name, syms, burst, p in all_msgs:
            if name in ('CMD-B-INIT', 'HANDSHAKE-D', 'HANDSHAKE-E'):
                if cycle is None or (t - last_t) > 10:
                    cycle = {'file': path, 'msgs': []}
                    boot_sequences.append(cycle)
                cycle['msgs'].append({
                    'time': t, 'channel': ch_idx, 'name': name,
                    'syms': syms, 'burst': burst,
                })
                last_t = t

    pairs = []
    for cycle in boot_sequences:
        cmd_b_long = [m for m in cycle['msgs'] if m['name'] == 'CMD-B-INIT' and len(m['syms']) > 22]
        handshake_e = [m for m in cycle['msgs'] if m['name'] == 'HANDSHAKE-E']
        if cmd_b_long and handshake_e:
            c = cmd_b_long[0]
            r = handshake_e[0]
            c_lh = A.burst_to_lh_pairs(c['burst'])[CMD_B_INIT_HDR:]  # variable portion
            r_lh = A.burst_to_lh_pairs(r['burst'])[HANDSHAKE_E_HDR:]  # variable portion
            c_syms = c['syms'][CMD_B_INIT_HDR:]
            r_syms = r['syms'][HANDSHAKE_E_HDR:]
            pairs.append({
                'cycle': len(pairs) + 1,
                'file': cycle['file'],
                'c_lh': c_lh,
                'r_lh': r_lh,
                'c_syms': c_syms,
                'r_syms': r_syms,
            })
    return pairs


def lh_to_value(l, h, method):
    """Convert an (L,H) pair to a single numeric value using different encoding hypotheses."""
    if method == 'L_only':
        return l
    elif method == 'H_only':
        return h
    elif method == 'L+H':
        return l + h
    elif method == 'L*10+H':
        return l * 10 + h
    elif method == 'L*9+H':
        return l * 9 + h
    elif method == 'L-1_base9':
        return (l - 1) * 9 + (h - 1) if h >= 1 else (l - 1) * 9
    elif method == 'LH_concat_bin':
        # Treat L as high nibble, H as low nibble (4-bit each)
        return (l << 4) | h
    elif method == 'L*8+H':
        return l * 8 + h
    elif method == 'pack_3bit':
        # L in bits [5:3], H in bits [2:0]
        return ((l & 0x7) << 3) | (h & 0x7)
    elif method == 'H*9+L':
        return h * 9 + l
    else:
        return l


def pairs_to_values(lh_pairs, method):
    """Convert list of (L,H) tuples to list of numeric values."""
    return [lh_to_value(l, h, method) for l, h in lh_pairs]


def pairs_to_bitstream(lh_pairs, method, bits_per_val):
    """Convert to a flat bitstream."""
    vals = pairs_to_values(lh_pairs, method)
    bits = []
    for v in vals:
        for b in range(bits_per_val - 1, -1, -1):
            bits.append((v >> b) & 1)
    return bits


def pairs_to_bigint(lh_pairs, method):
    """Pack all values into a single big integer."""
    vals = pairs_to_values(lh_pairs, method)
    result = 0
    for v in vals:
        result = result * 100 + v  # Enough room for 2-digit values
    return result


def try_xor_relationship(pairs_data):
    """Try XOR between challenge and response packed as integers."""
    print("\n" + "=" * 100)
    print("TEST: XOR between challenge and response (various encodings)")
    print("=" * 100)

    methods = ['L_only', 'H_only', 'L+H', 'L*9+H', 'L*10+H', 'LH_concat_bin']

    for method in methods:
        print(f"\n--- Encoding: {method} ---")
        for p in pairs_data:
            c_vals = pairs_to_values(p['c_lh'], method)
            r_vals = pairs_to_values(p['r_lh'], method)
            print(f"  Cycle {p['cycle']}: C({len(c_vals)})={c_vals}")
            print(f"           R({len(r_vals)})={r_vals}")

            # Sum check
            c_sum = sum(c_vals)
            r_sum = sum(r_vals)
            print(f"           C_sum={c_sum}  R_sum={r_sum}  C_sum-R_sum={c_sum-r_sum}  "
                  f"C_sum%R_sum={'N/A' if r_sum == 0 else c_sum % r_sum}  "
                  f"ratio={c_sum/r_sum:.3f}" if r_sum else "")


def check_sum_invariants(pairs_data):
    """Check if sum(challenge) + sum(response) = constant, or other sum relationships."""
    print("\n" + "=" * 100)
    print("TEST: Sum-based invariants")
    print("=" * 100)

    methods = ['L_only', 'H_only', 'L+H', 'L*9+H', 'L*10+H']

    for method in methods:
        print(f"\n--- Encoding: {method} ---")
        c_sums = []
        r_sums = []
        totals = []
        products_mod = []
        for p in pairs_data:
            c_vals = pairs_to_values(p['c_lh'], method)
            r_vals = pairs_to_values(p['r_lh'], method)
            cs = sum(c_vals)
            rs = sum(r_vals)
            c_sums.append(cs)
            r_sums.append(rs)
            totals.append(cs + rs)

            # Product of all values mod various primes
            cp = 1
            for v in c_vals:
                if v != 0:
                    cp = (cp * v)
            rp = 1
            for v in r_vals:
                if v != 0:
                    rp = (rp * v)
            products_mod.append((cp, rp))

        print(f"  Challenge sums: {c_sums}")
        print(f"  Response  sums: {r_sums}")
        print(f"  C+R totals:     {totals}")
        print(f"  C-R diffs:      {[c - r for c, r in zip(c_sums, r_sums)]}")

        # Check if any modular operation gives a constant
        for mod in [7, 8, 9, 10, 13, 16, 17, 19, 23, 31, 32, 37, 41, 64, 127, 128, 255, 256]:
            c_mod = [s % mod for s in c_sums]
            r_mod = [s % mod for s in r_sums]
            t_mod = [s % mod for s in totals]
            if len(set(t_mod)) == 1:
                print(f"  *** CONSTANT (C+R) mod {mod} = {t_mod[0]} ***")
            if len(set(c_mod)) == 1:
                print(f"  *** CONSTANT C_sum mod {mod} = {c_mod[0]} ***")
            d_mod = [(c - r) % mod for c, r in zip(c_sums, r_sums)]
            if len(set(d_mod)) == 1:
                print(f"  *** CONSTANT (C-R) mod {mod} = {d_mod[0]} ***")
            xor_mod = [(c ^ r) % mod for c, r in zip(c_sums, r_sums)]
            if len(set(xor_mod)) == 1:
                print(f"  *** CONSTANT (C^R) mod {mod} = {xor_mod[0]} ***")


def check_symbol_sums(pairs_data):
    """Check sums of L-symbols and H-symbols separately."""
    print("\n" + "=" * 100)
    print("TEST: Raw L-symbol and H-symbol sum invariants")
    print("=" * 100)

    for p in pairs_data:
        cl = [l for l, h in p['c_lh']]
        ch = [h for l, h in p['c_lh']]
        rl = [l for l, h in p['r_lh']]
        rh = [h for l, h in p['r_lh']]
        print(f"  Cycle {p['cycle']}: "
              f"C_Lsum={sum(cl):3d}  C_Hsum={sum(ch):3d}  C_L+H={sum(cl)+sum(ch):3d}  "
              f"R_Lsum={sum(rl):3d}  R_Hsum={sum(rh):3d}  R_L+H={sum(rl)+sum(rh):3d}  "
              f"ALL={sum(cl)+sum(ch)+sum(rl)+sum(rh):3d}")


def check_value_distribution(pairs_data):
    """Look at value frequency distributions."""
    print("\n" + "=" * 100)
    print("TEST: Symbol value distributions")
    print("=" * 100)

    all_c_l = Counter()
    all_c_h = Counter()
    all_r_l = Counter()
    all_r_h = Counter()

    for p in pairs_data:
        for l, h in p['c_lh']:
            all_c_l[l] += 1
            all_c_h[h] += 1
        for l, h in p['r_lh']:
            all_r_l[l] += 1
            all_r_h[h] += 1

    print(f"  Challenge L values: {dict(sorted(all_c_l.items()))}")
    print(f"  Challenge H values: {dict(sorted(all_c_h.items()))}")
    print(f"  Response  L values: {dict(sorted(all_r_l.items()))}")
    print(f"  Response  H values: {dict(sorted(all_r_h.items()))}")

    # Max values observed
    print(f"\n  Challenge L range: {min(all_c_l.keys())}-{max(all_c_l.keys())}")
    print(f"  Challenge H range: {min(all_c_h.keys())}-{max(all_c_h.keys())}")
    print(f"  Response  L range: {min(all_r_l.keys())}-{max(all_r_l.keys())}")
    print(f"  Response  H range: {min(all_r_h.keys())}-{max(all_r_h.keys())}")


def pack_as_bytes(pairs_data):
    """Try packing (L,H) pairs into byte streams and look for patterns."""
    print("\n" + "=" * 100)
    print("TEST: Byte-level packing hypotheses")
    print("=" * 100)

    for p in pairs_data:
        print(f"\n  Cycle {p['cycle']}:")

        # Hypothesis 1: Each (L,H) pair is one byte: L*9+H (base-9 with offset)
        # L range 1-9 → 0-8, H range 0-9 → 0-9 ... try (L-1)*10 + H
        c_bytes_10 = [(l - 1) * 10 + h for l, h in p['c_lh']]
        r_bytes_10 = [(l - 1) * 10 + h for l, h in p['r_lh']]
        print(f"    (L-1)*10+H  C: {c_bytes_10}")
        print(f"    (L-1)*10+H  R: {r_bytes_10}")

        # Hypothesis 2: Just concatenate L and H as hex nibble pairs
        c_hex = ''.join(f'{l:x}{h:x}' for l, h in p['c_lh'])
        r_hex = ''.join(f'{l:x}{h:x}' for l, h in p['r_lh'])
        print(f"    Hex(L,H)    C: {c_hex}")
        print(f"    Hex(L,H)    R: {r_hex}")

        # Hypothesis 3: L values are the data, H values encode framing/length
        # (H = gap to next = number of "ticks" of high before next low)
        print(f"    L-only    C: {[l for l, h in p['c_lh']]}")
        print(f"    L-only    R: {[l for l, h in p['r_lh']]}")
        print(f"    H-only    C: {[h for l, h in p['c_lh']]}")
        print(f"    H-only    R: {[h for l, h in p['r_lh']]}")


def check_total_duration_invariant(pairs_data):
    """Check if total duration (sum of all L+H in both challenge+response) is constant."""
    print("\n" + "=" * 100)
    print("TEST: Total duration invariants (L+H summed across all pairs)")
    print("=" * 100)

    for p in pairs_data:
        c_total = sum(l + h for l, h in p['c_lh'])
        r_total = sum(l + h for l, h in p['r_lh'])
        c_l = sum(l for l, h in p['c_lh'])
        c_h = sum(h for l, h in p['c_lh'])
        r_l = sum(l for l, h in p['r_lh'])
        r_h = sum(h for l, h in p['r_lh'])
        print(f"  Cycle {p['cycle']}: C_dur={c_total:3d} ({c_l}L+{c_h}H)  "
              f"R_dur={r_total:3d} ({r_l}L+{r_h}H)  "
              f"C+R={c_total + r_total:3d}  "
              f"C_Lprod mod256={math.prod(l for l,h in p['c_lh']) % 256}  "
              f"R_Lprod mod256={math.prod(l for l,h in p['r_lh']) % 256}")


def estimate_entropy(pairs_data):
    """Estimate the effective bit-strength of the challenge-response space."""
    print("\n" + "=" * 100)
    print("ENTROPY ESTIMATION")
    print("=" * 100)

    # Challenge: variable payload length 22-30 symbols
    # Each L-symbol: values 1-6 observed (6 values = ~2.58 bits)
    # Each H-symbol: values 0-8 observed (9 values = ~3.17 bits)
    # Per (L,H) pair: up to 6*9 = 54 combinations = ~5.75 bits

    c_lens = [len(p['c_lh']) for p in pairs_data]
    r_lens = [len(p['r_lh']) for p in pairs_data]

    all_c_l_vals = set()
    all_c_h_vals = set()
    all_r_l_vals = set()
    all_r_h_vals = set()
    for p in pairs_data:
        for l, h in p['c_lh']:
            all_c_l_vals.add(l)
            all_c_h_vals.add(h)
        for l, h in p['r_lh']:
            all_r_l_vals.add(l)
            all_r_h_vals.add(h)

    print(f"\n  Challenge payload lengths: {c_lens} (range {min(c_lens)}-{max(c_lens)})")
    print(f"  Response  payload lengths: {r_lens} (range {min(r_lens)}-{max(r_lens)})")

    print(f"\n  Challenge L distinct values: {sorted(all_c_l_vals)} ({len(all_c_l_vals)} values = {math.log2(len(all_c_l_vals)):.2f} bits)")
    print(f"  Challenge H distinct values: {sorted(all_c_h_vals)} ({len(all_c_h_vals)} values = {math.log2(len(all_c_h_vals)):.2f} bits)")
    print(f"  Response  L distinct values: {sorted(all_r_l_vals)} ({len(all_r_l_vals)} values = {math.log2(len(all_r_l_vals)):.2f} bits)")
    print(f"  Response  H distinct values: {sorted(all_r_h_vals)} ({len(all_r_h_vals)} values = {math.log2(len(all_r_h_vals)):.2f} bits)")

    # Upper bound: each (L,H) pair carries at most log2(L_range * H_range) bits
    c_pair_bits = math.log2(len(all_c_l_vals) * len(all_c_h_vals))
    r_pair_bits = math.log2(len(all_r_l_vals) * len(all_r_h_vals))

    avg_c_len = sum(c_lens) / len(c_lens)
    avg_r_len = sum(r_lens) / len(r_lens)

    print(f"\n  Bits per challenge (L,H) pair: {c_pair_bits:.2f}")
    print(f"  Bits per response  (L,H) pair: {r_pair_bits:.2f}")

    print(f"\n  Challenge entropy upper bound: {avg_c_len:.0f} pairs × {c_pair_bits:.2f} bits = {avg_c_len * c_pair_bits:.0f} bits")
    print(f"  Response  entropy upper bound: {avg_r_len:.0f} pairs × {r_pair_bits:.2f} bits = {avg_r_len * r_pair_bits:.0f} bits")

    # If L is the primary data and H encodes structure
    print(f"\n  --- If only L-symbols carry data ---")
    c_l_bits = math.log2(len(all_c_l_vals))
    r_l_bits = math.log2(len(all_r_l_vals))
    print(f"  Challenge: {avg_c_len:.0f} × {c_l_bits:.2f} bits = {avg_c_len * c_l_bits:.0f} bits ({2**(avg_c_len * c_l_bits):.2e} keyspace)")
    print(f"  Response:  {avg_r_len:.0f} × {r_l_bits:.2f} bits = {avg_r_len * r_l_bits:.0f} bits ({2**(avg_r_len * r_l_bits):.2e} keyspace)")

    # If we treat each symbol as base-9 digit (values 1-9)
    print(f"\n  --- If L-symbols are base-9 digits (1-9) ---")
    print(f"  Challenge: 9^{avg_c_len:.0f} = {9**int(avg_c_len):.2e} ≈ {math.log2(9) * avg_c_len:.0f} bits")
    print(f"  Response:  9^{avg_r_len:.0f} = {9**int(avg_r_len):.2e} ≈ {math.log2(9) * avg_r_len:.0f} bits")

    print(f"\n  VERDICT:")
    print(f"  The RESPONSE is the weak link — only {avg_r_len:.0f} symbols, ~{avg_r_len * r_pair_bits:.0f} bits max.")
    print(f"  If we could collect enough challenge-response pairs per session,")
    print(f"  a lookup table of ~{2**(avg_r_len * r_l_bits):.0e} entries (L-only) or")
    print(f"  ~{2**(avg_r_len * r_pair_bits):.0e} entries (L+H) would cover the space.")
    print(f"  BUT: the shared secret (pairing key) matters — we need to understand")
    print(f"  whether the same (opener, receiver) always uses the same key.")


def check_lh_as_nibble_bytes(pairs_data):
    """Treat consecutive (L,H) pairs as encoding bytes — L=high nibble, H=low nibble."""
    print("\n" + "=" * 100)
    print("TEST: Treat each (L,H) as a byte (L<<4|H), look for CRC/checksum patterns")
    print("=" * 100)

    for p in pairs_data:
        c_bytes = bytes((l << 4) | (h & 0xF) for l, h in p['c_lh'])
        r_bytes = bytes((l << 4) | (h & 0xF) for l, h in p['r_lh'])
        print(f"\n  Cycle {p['cycle']}:")
        print(f"    C bytes: {c_bytes.hex(' ')}")
        print(f"    R bytes: {r_bytes.hex(' ')}")

        # XOR all bytes
        c_xor = 0
        for b in c_bytes:
            c_xor ^= b
        r_xor = 0
        for b in r_bytes:
            r_xor ^= b
        print(f"    C_XOR=0x{c_xor:02x}  R_XOR=0x{r_xor:02x}  C^R=0x{c_xor ^ r_xor:02x}")

        # Sum mod 256
        c_sum = sum(c_bytes) % 256
        r_sum = sum(r_bytes) % 256
        print(f"    C_sum%256=0x{c_sum:02x}  R_sum%256=0x{r_sum:02x}  (C+R)%256=0x{(c_sum+r_sum)%256:02x}")


def check_last_symbol_checksum(pairs_data):
    """Check if the last (L,H) pair is a checksum of the preceding ones."""
    print("\n" + "=" * 100)
    print("TEST: Last symbol as checksum of preceding payload?")
    print("=" * 100)

    for p in pairs_data:
        # Challenge
        c = p['c_lh']
        c_body = c[:-1]
        c_last = c[-1]
        c_l_sum = sum(l for l, h in c_body) % 10
        c_h_sum = sum(h for l, h in c_body) % 10
        c_l_xor = 0
        c_h_xor = 0
        for l, h in c_body:
            c_l_xor ^= l
            c_h_xor ^= h

        # Response
        r = p['r_lh']
        r_body = r[:-1]
        r_last = r[-1]
        r_l_sum = sum(l for l, h in r_body) % 10
        r_h_sum = sum(h for l, h in r_body) % 10
        r_l_xor = 0
        r_h_xor = 0
        for l, h in r_body:
            r_l_xor ^= l
            r_h_xor ^= h

        print(f"  Cycle {p['cycle']}:")
        print(f"    C last=({c_last[0]},{c_last[1]})  L_sum%10={c_l_sum}  H_sum%10={c_h_sum}  L_xor={c_l_xor}  H_xor={c_h_xor}")
        print(f"    R last=({r_last[0]},{r_last[1]})  L_sum%10={r_l_sum}  H_sum%10={r_h_sum}  L_xor={r_l_xor}  H_xor={r_h_xor}")


def check_bigint_modular(pairs_data):
    """Pack challenge/response as big integers, check modular relationships."""
    print("\n" + "=" * 100)
    print("TEST: Big-integer modular relationships")
    print("=" * 100)

    for method in ['L_only', 'L+H', 'L*9+H']:
        print(f"\n--- Encoding: {method} ---")
        c_ints = []
        r_ints = []
        for p in pairs_data:
            c_vals = pairs_to_values(p['c_lh'], method)
            r_vals = pairs_to_values(p['r_lh'], method)

            # Pack as base-N number
            base = max(max(c_vals), max(r_vals)) + 1
            c_num = 0
            for v in c_vals:
                c_num = c_num * base + v
            r_num = 0
            for v in r_vals:
                r_num = r_num * base + v

            c_ints.append(c_num)
            r_ints.append(r_num)

            print(f"  Cycle {p['cycle']}: base={base}")
            print(f"    C = {c_num}")
            print(f"    R = {r_num}")
            print(f"    C mod R = {c_num % r_num if r_num else 'N/A'}")
            print(f"    C XOR R = {c_num ^ r_num}")
            print(f"    C - R   = {c_num - r_num}")

        # Check if (C XOR R) is constant
        xors = [c ^ r for c, r in zip(c_ints, r_ints)]
        if len(set(xors)) == 1:
            print(f"\n  *** CONSTANT XOR FOUND: {xors[0]} ***")

        # Check if (C - R) mod N is constant for various N
        diffs = [c - r for c, r in zip(c_ints, r_ints)]
        for mod in [256, 65536, 2**32, 2**64]:
            d_mod = [(d % mod) for d in diffs]
            if len(set(d_mod)) == 1:
                print(f"  *** CONSTANT (C-R) mod {mod} = {d_mod[0]} ***")


def main():
    print("Extracting challenge-response pairs...")
    pairs_data = extract_pairs()
    print(f"Found {len(pairs_data)} paired challenge-response cycles\n")

    # Run all analyses
    estimate_entropy(pairs_data)
    check_symbol_sums(pairs_data)
    check_value_distribution(pairs_data)
    check_sum_invariants(pairs_data)
    check_total_duration_invariant(pairs_data)
    check_last_symbol_checksum(pairs_data)
    pack_as_bytes(pairs_data)
    check_lh_as_nibble_bytes(pairs_data)
    check_bigint_modular(pairs_data)
    try_xor_relationship(pairs_data)

    print("\n" + "=" * 100)
    print("FEASIBILITY ASSESSMENT: Breaking with ~100 captures")
    print("=" * 100)
    print("""
  KEY QUESTION: Is this a keyed function, or a fixed lookup?

  If FIXED LOOKUP (no shared secret, just obscurity):
    - The challenge space is ~9^23 ≈ 2^73 — WAY too large for brute force
    - BUT: if the opener just has a hardcoded table of N challenge-response pairs,
      then N is probably small (flash storage on cheap MCU = limited)
    - 100 captures might cover a significant fraction of a small table
    - Look for REPEATED challenges across boots → that would prove it's a fixed table

  If KEYED FUNCTION (HMAC, AES, shared secret from pairing):
    - Each (opener, receiver) pair shares a secret established during pairing
    - The challenge is a nonce, the response is f(secret, challenge)
    - 100 captures give 100 known plaintext-ciphertext pairs
    - With only ~40-80 bits of response, a weak function could be brute-forced
    - Common weak patterns: truncated CRC, simple XOR with key, LFSR-based PRNG

  BOTTOM LINE:
    - The response is SHORT (12-18 symbols ≈ 38-57 bits if L-only, 69-104 bits if L+H)
    - This is a CHEAP MCU protocol from early 2000s — unlikely to be AES/SHA
    - Most likely: LFSR-based or simple polynomial MAC
    - 100 captures is realistic for table exhaustion if it's a lookup
    - For a keyed function, 100 captures is enough for differential analysis
    - GATHERING MORE DATA IS THE RIGHT STRATEGY
""")


if __name__ == "__main__":
    main()
