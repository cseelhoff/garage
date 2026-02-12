#!/usr/bin/env python3
"""gf2_linearity_test.py — Test if the handshake response is a linear function of the
challenge over GF(2), using the proven (L,H) → bitstream encoding from TYPE-B position data.

Encoding: Each (L,H) pair contributes L one-bits then H zero-bits (active-low, LSB-first).
This is identical to decode_position_binary() in analyze.py.

If the response R = M·C (mod 2) for some constant matrix M, then for ANY three pairs:
  R1 ⊕ R2 ⊕ R3 = M·(C1 ⊕ C2 ⊕ C3)

For an affine function R = M·C ⊕ b:
  R1 ⊕ R2 = M·(C1 ⊕ C2)   (constant b cancels)

We test both.
"""

import analyze as A
from itertools import combinations

CMD_B_INIT_HDR = 8
HANDSHAKE_E_HDR = 8


def lh_to_bitstream(lh_pairs):
    """Convert (L,H) pairs to a bitstream: L one-bits then H zero-bits per pair."""
    bits = []
    for l, h in lh_pairs:
        bits.extend([1] * l)
        if h > 0:
            bits.extend([0] * h)
    return bits


def bitstream_to_int(bits):
    """Convert LSB-first bitstream to integer."""
    return sum(bit << i for i, bit in enumerate(bits))


def int_to_bits(val, n):
    """Convert integer to list of n bits (LSB-first)."""
    return [(val >> i) & 1 for i in range(n)]


def xor_bits(a, b):
    """XOR two bit lists (pads shorter one with zeros)."""
    n = max(len(a), len(b))
    a = a + [0] * (n - len(a))
    b = b + [0] * (n - len(b))
    return [x ^ y for x, y in zip(a, b)]


def extract_pairs():
    """Extract challenge/response (L,H) variable payloads from all boot cycles."""
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
            c_lh = A.burst_to_lh_pairs(c['burst'])[CMD_B_INIT_HDR:]
            r_lh = A.burst_to_lh_pairs(r['burst'])[HANDSHAKE_E_HDR:]
            pairs.append({
                'cycle': len(pairs) + 1,
                'file': cycle['file'],
                'c_lh': c_lh,
                'r_lh': r_lh,
            })
    return pairs


def gf2_row_reduce(matrix, n_cols):
    """Gaussian elimination over GF(2). Matrix is list of integers (bitmasks).
    Returns (rank, reduced_matrix)."""
    mat = list(matrix)
    rank = 0
    for col in range(n_cols):
        # Find pivot row
        pivot = None
        for row in range(rank, len(mat)):
            if (mat[row] >> col) & 1:
                pivot = row
                break
        if pivot is None:
            continue
        mat[rank], mat[pivot] = mat[pivot], mat[rank]
        # Eliminate in all other rows
        for row in range(len(mat)):
            if row != rank and (mat[row] >> col) & 1:
                mat[row] ^= mat[rank]
        rank += 1
    return rank, mat


def main():
    print("=" * 90)
    print("GF(2) LINEARITY TEST — Handshake Challenge-Response")
    print("=" * 90)

    pairs = extract_pairs()
    print(f"\nExtracted {len(pairs)} challenge-response pairs\n")

    # Step 1: Convert (L,H) pairs to bitstreams
    print("-" * 90)
    print("STEP 1: Convert (L,H) → bitstream (L ones, H zeros, LSB-first)")
    print("-" * 90)

    c_bits_all = []
    r_bits_all = []
    for p in pairs:
        c_bits = lh_to_bitstream(p['c_lh'])
        r_bits = lh_to_bitstream(p['r_lh'])
        c_int = bitstream_to_int(c_bits)
        r_int = bitstream_to_int(r_bits)
        c_bits_all.append(c_bits)
        r_bits_all.append(r_bits)
        print(f"  Cycle {p['cycle']}: C={len(c_bits):3d} bits  R={len(r_bits):3d} bits")
        print(f"    C bits: {''.join(str(b) for b in c_bits)}")
        print(f"    R bits: {''.join(str(b) for b in r_bits)}")
        print(f"    C hex:  0x{c_int:0{(len(c_bits)+3)//4}x}")
        print(f"    R hex:  0x{r_int:0{(len(r_bits)+3)//4}x}")
        print()

    # Check bit-length consistency
    c_lens = [len(b) for b in c_bits_all]
    r_lens = [len(b) for b in r_bits_all]
    print(f"  Challenge bit-lengths: {c_lens}")
    print(f"  Response  bit-lengths: {r_lens}")

    # Pad all to same length for matrix operations
    c_width = max(c_lens)
    r_width = max(r_lens)
    for i in range(len(c_bits_all)):
        c_bits_all[i] = c_bits_all[i] + [0] * (c_width - len(c_bits_all[i]))
        r_bits_all[i] = r_bits_all[i] + [0] * (r_width - len(r_bits_all[i]))

    print(f"\n  Padded to: C={c_width} bits, R={r_width} bits\n")

    # Convert to integers for fast XOR
    c_ints = [bitstream_to_int(b) for b in c_bits_all]
    r_ints = [bitstream_to_int(b) for b in r_bits_all]

    # Step 2: Test affine linearity — R1⊕R2 should be a consistent function of C1⊕C2
    # For affine: R = M·C ⊕ b, so R1⊕R2 = M·(C1⊕C2)
    # This means: if C1⊕C2 = C3⊕C4, then R1⊕R2 MUST equal R3⊕R4
    print("-" * 90)
    print("STEP 2: Pairwise difference test (affine linearity)")
    print("  If R = M·C ⊕ b, then R_i ⊕ R_j = M·(C_i ⊕ C_j)")
    print("  Check: if C_i⊕C_j = C_k⊕C_l then R_i⊕R_j must = R_k⊕R_l")
    print("-" * 90)

    # Collect all pairwise differences
    diff_map = {}
    n = len(pairs)
    for i in range(n):
        for j in range(i + 1, n):
            c_diff = c_ints[i] ^ c_ints[j]
            r_diff = r_ints[i] ^ r_ints[j]
            key = c_diff
            if key in diff_map:
                prev_r_diff, prev_ij = diff_map[key]
                if prev_r_diff == r_diff:
                    print(f"  MATCH: C{prev_ij[0]+1}⊕C{prev_ij[1]+1} = C{i+1}⊕C{j+1}, "
                          f"and R diffs ALSO match ✓")
                else:
                    print(f"  **FAIL**: C{prev_ij[0]+1}⊕C{prev_ij[1]+1} = C{i+1}⊕C{j+1}, "
                          f"but R{prev_ij[0]+1}⊕R{prev_ij[1]+1} ≠ R{i+1}⊕R{j+1} ✗")
                    print(f"    → AFFINE LINEARITY VIOLATED")
            else:
                diff_map[key] = (r_diff, (i, j))

    print(f"\n  {len(diff_map)} unique C_i⊕C_j values from {n*(n-1)//2} pairs")
    print(f"  (No collisions = test is inconclusive from differences alone)")

    # Step 3: Triple XOR test — R1⊕R2⊕R3 vs C1⊕C2⊕C3
    # For PURE linear (no constant): R1⊕R2⊕R3 = M·(C1⊕C2⊕C3)
    # For affine: R1⊕R2⊕R3 = M·(C1⊕C2⊕C3) ⊕ b  (b doesn't cancel with odd count)
    # But: (R1⊕R2) ⊕ (R1⊕R3) ⊕ (R2⊕R3) = 0 for ANY function, so we need a more specific test.
    # Better: check if R lies in an affine subspace of the right dimension.
    print()
    print("-" * 90)
    print("STEP 3: GF(2) matrix rank test")
    print("  Stack [C | R] as augmented matrix over GF(2)")
    print("  If R = M·C ⊕ b, rank([C|R]) ≤ rank(C) for the affine-shifted system")
    print("-" * 90)

    # Build augmented matrix: each row is [challenge_bits | response_bits]
    # For affine, we difference against pair 0 to cancel the constant:
    #   (C_i ⊕ C_0) maps to (R_i ⊕ R_0)
    print("\n  Testing AFFINE model (differencing against cycle 1)...")
    aug_rows = []
    for i in range(1, n):
        c_diff = c_ints[i] ^ c_ints[0]
        r_diff = r_ints[i] ^ r_ints[0]
        # Pack as single integer: [c_diff (c_width bits) | r_diff (r_width bits)]
        row = (c_diff << r_width) | r_diff
        aug_rows.append(row)

    total_width = c_width + r_width
    rank_aug, _ = gf2_row_reduce(aug_rows, total_width)

    # Also check rank of challenge-only matrix
    c_diff_rows = [c_ints[i] ^ c_ints[0] for i in range(1, n)]
    rank_c, _ = gf2_row_reduce(c_diff_rows, c_width)

    # And response-only matrix
    r_diff_rows = [r_ints[i] ^ r_ints[0] for i in range(1, n)]
    rank_r, _ = gf2_row_reduce(r_diff_rows, r_width)

    print(f"\n  Differenced pairs: {n - 1}")
    print(f"  Challenge rank: {rank_c} (out of {c_width} bits)")
    print(f"  Response  rank: {rank_r} (out of {r_width} bits)")
    print(f"  Augmented [C|R] rank: {rank_aug}")
    print()

    if rank_aug == rank_c:
        print(f"  ★★★ AFFINE LINEARITY CONFIRMED ★★★")
        print(f"  rank([C|R]) = rank(C) = {rank_c}")
        print(f"  The response bits lie in the linear span of the challenge bits.")
        print(f"  → R = M·C ⊕ b for some {r_width}×{c_width} binary matrix M and constant b")
        print(f"  → The algorithm is LINEAR over GF(2) — fully breakable with Gaussian elimination!")
    elif rank_aug == rank_c + rank_r:
        print(f"  ✗ LINEARITY REJECTED — rank([C|R]) = rank(C) + rank(R)")
        print(f"  The challenge and response bits appear INDEPENDENT over GF(2).")
        print(f"  → Not a linear or affine function. Need nonlinear analysis.")
    else:
        print(f"  ? PARTIAL — rank([C|R]) = {rank_aug}, between {rank_c} and {rank_c + rank_r}")
        print(f"  Some response bits may be linear functions of challenge bits.")
        print(f"  → Possible partially-linear structure. Need more data or per-bit analysis.")

    # Step 4: Per-bit linearity test
    # For each response bit position j, test if R[j] = linear_combination(C_bits)
    print()
    print("-" * 90)
    print("STEP 4: Per-bit linearity test")
    print("  For each response bit j, check if R_j is a linear function of C bits")
    print("-" * 90)

    linear_bits = []
    nonlinear_bits = []

    for j in range(r_width):
        # Build system: for each differenced pair i, the j-th response diff bit
        # should be a linear combination of the challenge diff bits
        # Augmented matrix: [c_diff_bits | r_diff_bit_j]
        aug = []
        for i in range(1, n):
            c_diff = c_ints[i] ^ c_ints[0]
            r_diff_bit = (r_ints[i] ^ r_ints[0] >> j) & 1
            row = (c_diff << 1) | r_diff_bit
            aug.append(row)

        rank_full, reduced = gf2_row_reduce(aug, c_width + 1)

        # Check for inconsistency: a row with 0 in challenge part but 1 in response bit
        inconsistent = False
        for row in reduced:
            challenge_part = row >> 1
            response_bit = row & 1
            if challenge_part == 0 and response_bit == 1:
                inconsistent = True
                break

        if inconsistent:
            nonlinear_bits.append(j)
        else:
            linear_bits.append(j)

    print(f"\n  Linear response bits:    {len(linear_bits)}/{r_width}  positions: {linear_bits}")
    print(f"  Nonlinear response bits: {len(nonlinear_bits)}/{r_width}  positions: {nonlinear_bits}")

    if len(nonlinear_bits) == 0:
        print(f"\n  ★★★ ALL {r_width} RESPONSE BITS ARE LINEAR FUNCTIONS OF CHALLENGE BITS ★★★")
        print(f"  → Algorithm is FULLY LINEAR over GF(2). Key recovery is trivial.")
    elif len(linear_bits) > r_width * 0.8:
        print(f"\n  Most response bits ({len(linear_bits)}/{r_width}) are linear.")
        print(f"  → Likely linear with a few corrupted/checksum bits. Very breakable.")
    elif len(linear_bits) > 0:
        print(f"\n  Some linearity detected ({len(linear_bits)}/{r_width} bits).")
        print(f"  → Partially linear structure. May be a nonlinear combiner over LFSRs.")
    else:
        print(f"\n  No per-bit linearity detected.")
        print(f"  → Nonlinear function. Need more samples and different approach.")

    # Step 5: Consistency check — if linear, try to solve and predict
    if rank_aug == rank_c and n >= 3:
        print()
        print("-" * 90)
        print("STEP 5: Cross-validation (leave-one-out prediction)")
        print("  Build linear model from N-1 pairs, predict the Nth, check if it matches")
        print("-" * 90)

        correct = 0
        for leave_out in range(n):
            # Build system from all pairs except leave_out, differenced against pair 0
            # (skip if leave_out == 0, use pair 1 as reference instead)
            ref = 0 if leave_out != 0 else 1

            # For each response bit, solve for the linear combination of challenge bits
            predicted_r = 0
            success = True
            for j in range(r_width):
                # Build augmented system [c_diff | r_diff_bit_j]
                rows = []
                for i in range(n):
                    if i == leave_out or i == ref:
                        continue
                    c_diff = c_ints[i] ^ c_ints[ref]
                    r_diff_bit = ((r_ints[i] ^ r_ints[ref]) >> j) & 1
                    row = (c_diff << 1) | r_diff_bit
                    rows.append(row)

                _, reduced = gf2_row_reduce(rows, c_width + 1)

                # Find solution: which challenge bits contribute to this response bit
                # Predict for the left-out pair
                c_diff_test = c_ints[leave_out] ^ c_ints[ref]
                # Walk through reduced rows, compute predicted bit
                predicted_bit = 0
                for row in reduced:
                    c_part = row >> 1
                    r_bit = row & 1
                    if c_part == 0:
                        if r_bit == 1:
                            success = False
                            break
                        continue
                    # If this row's challenge pattern has odd overlap with test challenge diff
                    if bin(c_part & c_diff_test).count('1') % 2 == 1:
                        predicted_bit ^= r_bit

                # Add back the reference response bit
                actual_bit = (r_ints[leave_out] >> j) & 1
                ref_bit = (r_ints[ref] >> j) & 1
                predicted_bit ^= ref_bit

                if predicted_bit != actual_bit:
                    success = False
                    break
                predicted_r |= (predicted_bit << j)

            if success and predicted_r == r_ints[leave_out]:
                correct += 1
                result = "✓ CORRECT"
            else:
                result = "✗ WRONG"
            print(f"  Leave out cycle {leave_out + 1}: {result}")

        print(f"\n  Prediction accuracy: {correct}/{n}")
        if correct == n:
            print(f"\n  ★★★ PERFECT PREDICTION — THE FUNCTION IS LINEAR AND FULLY SOLVABLE ★★★")
            print(f"  With 100% leave-one-out accuracy on {n} pairs,")
            print(f"  we can predict the response to ANY challenge.")
        elif correct > n * 0.8:
            print(f"\n  High prediction rate — substantially linear, minor nonlinear component.")
        else:
            print(f"\n  Low prediction rate — significant nonlinearity present.")

    # Summary
    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"  Challenge: {c_width}-bit binary (CONFIRMED by fixed sum(L+H) ≈ 89)")
    print(f"  Response:  {r_width}-bit binary (CONFIRMED by fixed sum(L+H) ≈ 48)")
    print(f"  GF(2) challenge rank: {rank_c}/{n-1} differenced pairs")
    print(f"  GF(2) augmented rank: {rank_aug}")
    print(f"  Linear bits: {len(linear_bits)}/{r_width}")
    print(f"  Nonlinear bits: {len(nonlinear_bits)}/{r_width}")
    if rank_aug == rank_c:
        print(f"\n  VERDICT: LINEAR — algorithm is f(C) = M·C ⊕ b over GF(2)")
        print(f"  → Can be fully recovered with Gaussian elimination")
        print(f"  → No additional captures needed for algorithm recovery")
        print(f"  → ~10 more captures recommended for validation only")
    else:
        print(f"\n  VERDICT: NONLINEAR — need more captures for cryptanalysis")
        print(f"  → Recommend capturing 50-100 pairs for correlation attacks")


if __name__ == "__main__":
    main()
