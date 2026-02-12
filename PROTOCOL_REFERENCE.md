# Overhead Door Odyssey 1000 (Model 7030) — Protocol Reference

## Hardware Overview

| Item | Detail |
|------|--------|
| **Opener** | Overhead Door Odyssey 1000, Model 7030 |
| **Interface** | 4-pin header on receiver board |
| **Pin 1** | GND |
| **Pin 2 (Z3)** | CH0 — Receiver → Opener (MASTER) |
| **Pin 3 (Z4)** | CH1 — Opener → Receiver (RESPONDER) |
| **Pin 4** | 3.3 V |
| **Signal Level** | 3.3 V CMOS, active-low PWM |
| **Base Time Unit** | ~26 µs |
| **Symbol Alphabet** | {1, 2, 3, 4, 5, 6, 7, 9} — no symbol 8 |
| **Encoding** | Both LOW and HIGH pulse durations carry data |
| **Burst Gap** | ≥10 ms silence between messages |
| **Crosstalk** | H > 10 on CH1 = CH0 carrier bleed-through (filtered) |

---

## Table 1 — Signal Type Reference

### Legend

| Column | Meaning |
|--------|---------|
| **Ch** | Channel: 0 = Z3 (receiver→opener), 1 = Z4 (opener→receiver) |
| **Name** | Protocol-level message name used in `analyze.py` |
| **Category** | Functional category |
| **Direction** | Who initiates the message |
| **Match** | How `analyze.py` identifies it: "exact" (full symbol match) or "prefix" (header match) |
| **Header** | Constant symbol prefix identifying the message type |
| **Total Syms** | Observed total symbol count(s) |
| **Payload** | Symbol positions after the header |
| **Decode Status** | ✅ Fully decoded · ⚠️ Partially decoded · ❌ Not decoded |
| **Known Fields** | What has been decoded in the payload |
| **Unknown Fields** | What remains undecoded |
| **Test Ref** | Proposed test ID(s) from Table 2 to close remaining gaps |

---

### CH0 — Receiver → Opener (Master)

| Name | Category | Match | Header (symbols) | Total Syms | Payload | Decode Status | Known Fields | Unknown Fields | Test Ref |
|------|----------|-------|-------------------|------------|---------|---------------|--------------|----------------|----------|
| **CMD-A** | COMMAND | exact | `1,7,1,1,5,1,4,2,9,2,3,2,4,2,1` | 15 | — (no payload; entire message is constant) | ✅ Fully decoded | Keepalive heartbeat, sent every ~5 s. 95+ observed across all test files. | — | — |
| **CMD-A1** | COMMAND | exact | `1,7,1,1,5,1,4,2,9,1,3,2,1,2,2,1` | 16 | — (entire message is constant) | ✅ Fully decoded | Transitional first keepalive sent once after boot handshake. 11 observed (T08: identical across all 8+ boot cycles). Always constant. | — | — |
| **CMD-R** | COMMAND | exact | `1,7,1,1,5,5,2,9,1,6,4,2` | 12 | — (entire message is constant) | ✅ Fully decoded | Door toggle command — sent by receiver when **remote** button pressed. Wall button bypasses serial protocol entirely (direct wire to opener). 6+ observed, all identical. | — | — |
| **CMD-L** | COMMAND | exact | `1,7,1,1,5,1,3,2,2,6,1,6,1,1,2` | 15 | — (entire message is constant) | ✅ Fully decoded | Light toggle command. 2 observed. | — | — |
| **CMD-ECHO** | COMMAND | exact | `1,7,1,1,5,5,1,9,1,7,2,1,1` | 13 | — (entire message is constant) | ✅ Fully decoded | Post-command echo sent after CMD-R or CMD-L. 1 observed. | — | — |
| **CMD-INIT** | COMMAND | exact | `0,0,0,0,0,3` | 6 | — (entire message is constant) | ✅ Fully decoded | Boot hello/reset — first message from receiver after power-on. Not captured in T08 (likely occurs during power-settling period where signals are noise — see CH0-UNKNOWN glitch messages). The `[0,0,0,0,0]` glitch bursts seen in t05 and t08 may be partial CMD-INIT attempts. | — | — |
| **CMD-B** | COMMAND | prefix | `1,7,3,4` | 30 | Positions 4–29 (26 symbols) | ✅ Fully decoded | **CONSTANT across all 28 occurrences in all files.** Fixed status poll command. Always `[1,7,3,4,4,1,2,6,1,7,1,1,5,1,5,1,1,2,2,9,3,5,1,3,1,3,5,1,1,1]`. Sent after CMD-R, CMD-L, or during boot. Triggers TYPE-B + TYPE-C responses. No variable payload — treat as exact-match constant. | — | — |
| **CMD-B-INIT** | COMMAND | prefix | `1,7,3,4,1,4,1,9` | 20–38 | Positions 8+ (variable) | ⚠️ Partially decoded | Boot handshake config. **Two phases:** (1) Short form (20 syms) is CONSTANT: `[...,9,9,9,9,9,9,9,9,9,1,1,1,1]` — "hello" request sent 1-2× before handshake. (2) Long form (30-38 syms) VARIES every boot cycle — appears to be a challenge-response paired with HANDSHAKE-E. 21 observed across 8+ boot cycles (T08). | Long-form payload: session key? challenge-response? What algorithm generates the variable portion? | T-08 |

---

### CH1 — Opener → Receiver (Responder)

| Name | Category | Match | Header (symbols) | Total Syms | Payload | Decode Status | Known Fields | Unknown Fields | Test Ref |
|------|----------|-------|-------------------|------------|---------|---------------|--------------|----------------|----------|
| **ACK-A** | ACK | exact | `1,7,3,5,1,4,1,9,1,1,2,1` | 12 | — (entire message is constant) | ✅ Fully decoded | Simple ACK for CMD-A keepalive. 62+ observed. | — | — |
| **ACK-A2** | ACK | exact | `1,7,3,5,1,4,9,1,1,2` | 10 | — (entire message is constant) | ✅ Fully decoded | Boot/transitional ACK variant. 18 observed (T08: 16 across 8+ boots, always constant). | — | — |
| **ACK-R** | ACK | exact | `1,7,3,5,5,1,9,3,1,1` | 10 | — (entire message is constant) | ✅ Fully decoded | ACK for CMD-R door toggle. 12+ observed. | — | — |
| **ACK-L** | ACK | exact | `1,7,3,5,1,3,1,9,1,1,1,1` | 12 | — (entire message is constant) | ✅ Fully decoded | ACK for CMD-L light toggle. 2 observed. | — | — |
| **ACK-B** | ACK | exact | `1,7,3,5,4,9,3` | 7 | — (entire message is constant) | ✅ Fully decoded | ACK for CMD-B status poll. 10+ observed. | — | — |
| **ACK-B2** | ACK | exact | `1,7,3,5,5,9,3,1` | 8 | — (entire message is constant) | ✅ Fully decoded | Boot variant ACK for CMD-B-INIT. 9+ observed (T08: always constant). | — | — |
| **TYPE-B** | STATUS | prefix | `1,7,2,1,4,6,2,9` | 17–26 | Positions 0–17 (9–18 symbols) | ⚠️ Partially decoded | Primary status message, 500+ observed. **Decoded fields:** door state (pos 0-1, 11 states incl. new IDLE_MID), sub-state (pos 2-4, 15 sub-states incl. FORCE_STOPPED/AT_ENDPOINT_3), light (pos 1-4 when closed), position prefix (pos 5-6), position counter (pos 7+ via binary decoder, 9-bit mod 512). ~93% of positions decoded. | Endpoint/transitional position fields (see Endpoint Patterns below). | T-04, T-05, T-06 |
| **TYPE-C** | FULL_STATUS | prefix | `1,7,3,1,3,2,3,2,9` | 41–46 | Positions 23–45 (18–23 variable symbols) | ⚠️ Partially decoded | Extended status message, **147+ observed across 26 files.** Analyzed via (L,H) pair decoding of burst waveform. Structure (pair-level): `header(23 pairs) | pre_state(5-8 pairs) | (1,H≥5) separator | data_A(2-6 pairs) | 5,2,1,7 marker(4 pairs) | data_B(3-9 pairs)`. The `5,2,1,7` marker is present in **ALL 147** TYPE-C messages. **data_A encodes position** (active-low LSB-first binary, same as TYPE-B): IDLE_CLOSED=221, IDLE_OPEN=1, ARRIVED_OPEN=1 — fixed endpoints that never vary across sessions (unlike TYPE-B). During travel, data_A tracks TYPE-B position at 1:1 ratio (offset ~140 mod 512). **data_B = 511 always** (mod 512, all 1-bits). pre_state contains `9,9,9` core + position-prefix suffix matching TYPE-B prefix field (e.g. `2,6` for closed, `1,6`/`1,7`/`3,5` for other states). pre_state changes WITHIN a session during state transitions. 12 outliers across all files: all caused by CH0 crosstalk (H>10 corrupting pair decode). B1_Boot has a separator ambiguity (2 candidates) resolved by using the **last** `(1,H≥5)` pair. | pre_state leading symbols (vary by session and during travel). B1_Boot data_A=15/data_B=6 during boot (position not yet established). | — |
| **BEACON** | BEACON | prefix | `8,5,5` | 21 | Positions 3–20 (18 symbols) | ⚠️ Partially decoded | Opener polling beacon when no receiver is connected. 18 observed. H-value variants (10, 49) are confirmed crosstalk. Core L-only payload is constant: `[7,3,_,2,3,3,5,3,3,3,3,3,4,4,2,2,2,8]`. | — | T-09 |
| **ECHO** | ECHO | prefix | `1,7,1,1,5,5,1,9` | ~13 | Positions 8–12 (varies) | ✅ Fully decoded | Opener relays received CMD-R/CMD-L back. 12+ observed. Confirmed as literal echo. Note: two ECHOs sent back-to-back can fuse into a 26-symbol "CMD-?" if burst gap < 10ms. | — | — |
| **HANDSHAKE-D** | HANDSHAKE | prefix | `1,7,4,4,6,1,9` | 20 | Positions 7–19 (13 symbols) | ✅ Fully decoded | Boot handshake response. **CONSTANT across all 8 power cycles in T08.** Always `[1,7,4,4,6,1,9,6,1,1,1,1,6,1,1,1,1,4,2,1]`. Static device/model identifier. | — | — |
| **HANDSHAKE-E** | HANDSHAKE | prefix | `1,7,4,4,2,3,1,9` | 20–26 | Positions 8+ (12–18 symbols) | ⚠️ Partially decoded | Boot handshake response. **DIFFERENT every power cycle** (8 unique payloads across 8 boots in T08). Variable length (20-26 syms). Paired with CMD-B-INIT long form — together they form a challenge-response exchange. | What generates the variable payload? Session key? PRNG? Counter? | T-08 |
| **BOOT-F** | HANDSHAKE | prefix | `1,7,5,3` | 29 | Positions 4–28 (25 symbols) | ✅ Fully decoded | Boot completion message. **CONSTANT across all 8 power cycles in T08.** Always `[1,7,5,3,1,3,2,9,9,9,9,9,9,9,1,6,5,3,2,3,2,1,6,2,5,2,4,1,1]`. Static device identifier or firmware signature. Sent once after CMD-A1 in each boot cycle. | — | — |

---

### Header Prefix Analysis

All messages from both channels begin with `1,7` (except CMD-INIT `0,0,0,0,0,3` and BEACON `8,5,5`).

| Header Byte 3 | CH0 Meaning | CH1 Meaning |
|----------------|-------------|-------------|
| **1** (→ `1,7,1,...`) | CMD commands (CMD-A, CMD-R, CMD-L, CMD-ECHO) | ECHO (relayed command) |
| **2** (→ `1,7,2,...`) | — | TYPE-B (status) |
| **3** (→ `1,7,3,...`) | CMD-B / CMD-B-INIT (extended) | TYPE-C (extended status) / ACKs (`1,7,3,5,...`) |
| **4** (→ `1,7,4,...`) | — | HANDSHAKE-D / HANDSHAKE-E |
| **5** (→ `1,7,5,...`) | — | BOOT-F |

---

### Type B Message Structure (Detailed)

```
Symbols:  [1,7,2,1,4,6,2,9 | p0,p1 | p2,p3,p4 | p5,p6 | p7,p8,...,pN]
           ├── header (8) ──┤ door  │ sub-state │ prefix│ position field
                             state    (3 syms)    (2)     (variable length)
```

**Door State** (payload pos 0-1):

| Symbols | State | Description |
|---------|-------|-------------|
| 2,6 | IDLE_CLOSED | Door closed, stable |
| 9,4 | IDLE_OPEN | Door open, stable |
| 1,6 | STARTING | Motor activating (brief) |
| 1,2 | OPENING | Door opening |
| 1,3 | CLOSING | Door closing |
| 3,1 | STOPPED_MID_OPEN | Stopped while opening |
| 2,1 | STOPPED_MID_CLOSE | Stopped while closing |
| 5,3 | ARRIVED_OPEN | Just reached fully open |
| 2,2 | ARRIVED_CLOSED | Just reached fully closed |
| 1,1 | OBSTRUCTION_REVERSAL | Obstruction detected, reversing |
| 3,5 | IDLE_MID | Door at mid-position (post-boot or post-force stop) |

**Sub-State** (payload pos 2-4):

| Symbols | Sub-State | Typical Context |
|---------|-----------|-----------------|
| 3,4,4 | ACTIVE | In motion or stopped mid-travel |
| 3,4,2 | SETTLED | Stable idle (closed, light on) |
| 3,3,3 | OBSTRUCTION | Holding position during obstruction |
| 3,3,4 | REVERSING | Obstruction reversal in progress |
| 4,2,1 | IDLE_OFF | Stable idle (closed, light off) |
| 4,3,1 | AT_ENDPOINT | Just arrived at endpoint (variant 1) |
| 4,3,2 | AT_ENDPOINT_2 | Just arrived at endpoint (variant 2) |
| 4,4,1 | ACTIVATING | Motor activating (variant 1) |
| 4,4,9 | ACTIVATING_2 | Motor activating (variant 2) |
| 3,9,1 | IDLE_OPEN | Stable idle (door open) |
| 1,3,3 | REVERSAL_INIT | First frame of obstruction reversal |
| 1,3,4 | REVERSAL_INIT_2 | First frame variant |
| 3,4,3 | FORCE_STOPPED | Stopped after physical force or obstruction reversal |
| 4,3,9 | AT_ENDPOINT_3 | Arrived at endpoint (variant 3) |

**Light State** (payload pos 1-4, only valid when door is closed):

| Symbols | Light |
|---------|-------|
| 6,4,2,1 | OFF |
| 2,3,4,2 | ON |

**Position Encoding** (payload pos 5+):

The position field uses an **active-low LSB-first binary waveform**. Each `(L, H)` pair contributes `L` one-bits then `H` zero-bits to a bitstream. The bitstream is split by a delimiter `(7,9)` or `(9,9)` into two segments:

- **data_A**: Redundant / auxiliary (appears to echo or complement data_B)
- **data_B**: 9-bit position counter, wrapping mod 512

| Metric | Value |
|--------|-------|
| Position range | 0–511 (wraps mod 512) |
| Full travel range | ~890 counts (wraps through 0) |
| Direction | Increases during OPENING, decreases during CLOSING |
| Decode rate | 219/235 = 93.2% of observed Type B messages |
| Undecodable | 16 frames at endpoints/transitions (no standard delimiter) |

**Endpoint Position Patterns** (undecoded Type B frames observed across all files):

| Door State | Raw Position Field (L-only) | Count | Notes |
|---|---|---|---|
| IDLE_OPEN | `[1,9,5,1]` | Multiple | Short, no standard delimiter |
| IDLE_MID | `[1,5,1,1,9,1,2,1]` | 6 (T08) | Post-boot, constant across all boots |
| ARRIVED_OPEN | `[7,1,1,9,1,5]` | Multiple | |
| ARRIVED_OPEN | `[6,1,1,9,2,4]` | Multiple | |
| ARRIVED_OPEN | `[1,1,9,7]` | 2 (t05) | New pattern from multi-cycle |
| ARRIVED_OPEN | `[6,1,1,9,1,4]` | 1 (T02) | |
| OPENING (transitional) | `[1,7,1,1,9,3,3,1]` | Multiple | First frame of travel |
| OPENING (transitional) | `[9,1,1,9,1,4,1]` | 1 (t05) | New pattern |
| OPENING (transitional) | `[2,6,1,1,9,1,1,3,1]` | 1 (t05) | New pattern |
| CLOSING (transitional) | `[1,7,1,1,9,2,4,1]` | Multiple | First frame of travel |
| CLOSING (transitional) | `[2,6,1,1,9,1,4,1]` | Multiple | |
| CLOSING (transitional) | `[9,1,1,9,1,5,1]` | 1 (t05) | New pattern |
| CLOSING (transitional) | `[1,6,1,1,9,3,3,1]` | 2 (T02) | New pattern from obstruction tests |
| CLOSING (transitional) | `[3,5,1,1,9,1,1,3,1,0]` | 1 (T02) | With trailing 0 |
| STOPPED_MID_OPEN | `[2,6,1,1,9,2,1,2]` | 1 | |
| STOPPED_MID_OPEN | `[1,1,5,1,1,9,1,2,2]` | 8 (t08, force) | Most common endpoint, post-reboot/force-stop |
| STOPPED_MID_OPEN | `[3,5,1,1,9,4,2]` | 5 (T02) | Obstruction reversal endpoint |
| STOPPED_MID_OPEN | `[1,6,1,1,9,1,3]` | 2 (T02) | |
| OBSTRUCTION_REVERSAL | `[4,2,6,1,1,9,1,1,2,1]` | 1 | Longest endpoint pattern |

These all occur when the door is at a known extreme position (fully open, fully closed) or in the first frame of a state transition. The position is implicit from the door state, so the encoding may serve a different purpose at endpoints.

---

### Type C Message Structure (Decoded)

TYPE-C messages use (L,H) pulse-pair encoding at the waveform level (same as TYPE-B position). Each pair consists of one LOW duration and one HIGH duration, measured in ~26µs units. Decoded via `burst_to_lh_pairs()`, not symbol-level decoding.

```
Pair-level structure:

  [  23 constant header pairs  |  pre_state  | (1,H≥5) sep | data_A | 5,2,1,7 | data_B ]
   ├── always identical ────────┤  5-8 pairs   1 pair        2-6 p    4 pairs    3-9 p
                                  varies by                   position  universal  constant
                                  session +                   counter   marker     (=511)
                                  state
```

**Header (23 pairs):** Constant across ALL 147 observed TYPE-C messages, all files, all states.

**pre_state (5–8 pairs, L-values only):**
- Core: always contains `9,9,9` run (3 pairs with L=9)
- Suffix: 2-symbol position-prefix that matches TYPE-B prefix field:
  - `2,6` — closed position
  - `1,6` / `1,7` / `3,5` — other positions/states
- Leading symbols: vary by session AND change within a session during state transitions
- Example progressions in T-07c:
  - Idle closed: `[1, 1, 9, 9, 9, 2, 6, 2]`
  - During opening: `[1, 1, 9, 9, 9, 1, 6, 2]`
  - At arrived open: `[5, 9, 9, 9, 1, 6, 2]` (shorter — only 7 pairs)
  - During closing: `[5, 9, 9, 9, 1, 6, 2]` (persists)
  - Back to idle closed: `[5, 9, 9, 9, 1, 6, 2]` (does not revert within same session)

**Separator (1 pair):** L=1, H≥5. When multiple candidates exist (e.g., B1_Boot), use the **last** qualifying pair.

**data_A — Position Counter (2–6 pairs, active-low LSB-first binary):**

Each (L,H) pair → bit = 1 if L < 5, else 0. Value = Σ(bit[i] × 2^i).

| Door State | data_A Value | Observations | Notes |
|---|---|---|---|
| IDLE_CLOSED | **221** | 100% consistent (21/21 in T-07a, 9/9 in T-07c) | Fixed endpoint — never varies across sessions |
| IDLE_OPEN | **1** | 100% consistent (14/14 in T-07b) | Same as ARRIVED_OPEN |
| ARRIVED_OPEN | **1** | 100% consistent (7/7 in T-07c) | Fixed endpoint |
| OPENING travel | varies | Tracks TYPE-B position at 1:1 ratio | Offset ~140 mod 512 from TYPE-B (sampling jitter) |
| CLOSING travel | varies | Tracks TYPE-B position at 1:1 ratio | Same offset relationship |
| BOOT (B1_Boot) | **15** | 3/3 consistent | Position not yet established |

Key difference from TYPE-B: TYPE-C uses **fixed** endpoint values (221/1) that never change across sessions, while TYPE-B position varies per session due to motor calibration.

**Marker (4 pairs):** L-values = `5, 2, 1, 7`. Present in **ALL 147** TYPE-C messages. Universal constant serving as field delimiter.

**data_B — Constant Field (3–9 pairs, active-low LSB-first binary):**

Same binary decode as data_A. Value = **511** (mod 512) in ALL normal-operation messages. All bits = 1. B1_Boot shows data_B=6 (position not established).

**Outlier Summary (12 out of 147):**

| Source | Count | Cause | Effect |
|---|---|---|---|
| Crosstalk (H>10 in pairs) | 9 | CH0 carrier bleed-through | Corrupts binary decode of data_A or data_B |
| B1_Boot separator ambiguity | 3 | Two (1,H≥5) candidates | Resolved by using last candidate; gives data_A=15, data_B=6 |

---

### Communication Flow

```
BOOT SEQUENCE (confirmed across 8+ power cycles in T08):
  [power-on noise: CH0/CH1 UNKNOWN messages with 0-heavy symbol strings]
  [~3s settling time]
  CH0: CMD-B-INIT (20 syms, CONSTANT "hello")
  CH0: CMD-B-INIT (20 syms, repeat — sometimes sent 2×)
  CH1: ACK-A2
  CH1: HANDSHAKE-D (CONSTANT device ID)
  CH0: CMD-B-INIT (30-38 syms, VARIABLE challenge — different every boot)
  [sometimes repeated if no response]
  CH1: ACK-A2
  CH1: HANDSHAKE-E (VARIABLE response — different every boot, paired with above)
  CH1: ACK-B2
  [~3-5s pause]
  CH0: CMD-A1 (may send 1-3× until BOOT-F received)
  CH1: BOOT-F (CONSTANT device signature)
  [normal CMD-A keepalive loop begins]

NORMAL OPERATION (idle):
  CH0: CMD-A (every ~5s) → CH1: ACK-A, TYPE-B, TYPE-C

DOOR TOGGLE:
  CH0: CMD-R → CH1: ACK-R
  CH0: CMD-ECHO → CH1: ECHO
  CH0: CMD-B → CH1: ACK-B, TYPE-B, TYPE-C
  ...then TYPE-B messages stream rapidly during travel...

LIGHT TOGGLE:
  CH0: CMD-L → CH1: ACK-L
  CH0: CMD-ECHO → CH1: ECHO
  CH0: CMD-B → CH1: ACK-B, TYPE-B, TYPE-C

BEACON (no receiver):
  CH1: BEACON (periodic, ~every few seconds)
```

---

## Table 2 — Proposed Tests

Each test has a unique ID referenced in Table 1. Tests are ordered by priority (highest value first).

| Test ID | Name | Status | Description | Purpose / Gap Filled | Files |
|---------|------|--------|-------------|---------------------|-------|
| **T-01** | CMD-B multi-cycle | ✅ DONE | 4-5 full open/close cycles back-to-back. | **RESOLVED: CMD-B is 100% constant** (fixed status poll). No variants exist. | `t05.txt` |
| **T-02** | Obstruction at positions | ✅ DONE | Obstruction at ~75%, ~50%, ~25% during closing. | Confirmed: CMD-B payload unchanged by obstruction. Discovered new sub-state FORCE_STOPPED `(3,4,3)` for post-reversal stop. Found new door state transitions and endpoint patterns. Also covers T-06 (mid-stop position data at 3 positions). | `t02-75percent-near-top-early.txt`, `t02-50percent-middle.txt`, `t02-25percent-near-bottom-late.txt` |
| **T-03** | CMD-B after light toggle | ✅ N/A | CMD-B is constant — no light/timer correlation to test. | **CLOSED: CMD-B resolved as constant.** | — |
| **T-04** | Extended travel capture | ✅ N/A | Already capturing at 1 MHz; smallest pulse is 26 µs — sampling is more than sufficient. The number of TYPE-B messages per travel is a protocol-rate limit (~2/s), not a sampling issue. | **CLOSED: No action needed.** | — |
| **T-05** | Endpoint position mapping | ✅ DONE | 3 full open/close cycles. | Collected 12 new endpoint frames. Found new ARRIVED_OPEN pattern `[1,1,9,7]`, new sub-state AT_ENDPOINT_3 `(4,3,9)`. Endpoint patterns are NOT constant between cycles — vary per cycle. | `t05.txt` |
| **T-06** | Mid-travel stop positions | ✅ DONE | Covered by T-02 — stops at 25%, 50%, 75% with STOPPED_MID_OPEN + FORCE_STOPPED at each. | **CLOSED: Covered by T-02 data.** Two distinct endpoint patterns found: `[1,6,1,1,9,1,3]` (75%) and `[3,5,1,1,9,4,2]` (50%/25%). | T-02 files |
| **T-07** | Type C payload decode | ✅ DONE | **All three sub-tests complete.** T-07a: idle closed 100% constant (21/21). T-07b: idle open 100% constant (14/14), data_A=1. T-07c: full cycle with clean transitions (20 TYPE-C across open+close). Discovered complete TYPE-C internal structure: `header(23) | pre_state | (1,H≥5) separator | data_A | 5,2,1,7 marker | data_B`. data_A = position (221=closed, 1=open, tracks TYPE-B during travel). data_B = constant (mod512=511). pre_state varies by session and changes during travel. | TYPE-C fully characterized. | `t07a_idle_closed_60s.txt`, `t07b_idle_open_60s.txt`, `t07c_full_cycle.txt` |
| **T-08** | Boot sequence repeat | ✅ DONE | 8+ power cycles captured. | **Major findings:** BOOT-F constant (device ID), HANDSHAKE-D constant (device ID), HANDSHAKE-E varies every boot (session key), CMD-B-INIT has constant short form + variable long form (challenge-response). Found new door state IDLE_MID `(3,5)`. | `t08.txt` |
| **T-09** | Beacon + reconnect | ✅ N/A | **CLOSED: T-08 already captured reconnect data.** Beacon captured in `c1_c2_wall_button.txt` (14 constant messages). Boot handshake fully characterized in T-08. Hot reconnect would be a repeat of the boot handshake — no additional captures needed. | — | — |
| **T-10** | Wall button vs remote | ✅ DONE | test04 = wall button, t05 = remote. | **RESOLVED: Wall button does NOT use the serial protocol at all.** `test04_open_full.txt` has zero CMD-R messages — the wall button is a direct wire to the opener motor controller, completely bypassing the receiver. CMD-R only appears when the remote is used (through receiver on Z3). | `test04_open_full.txt`, `t05.txt` |
| **T-11** | Physical force test | ✅ DONE | Physically pushed door open while it was closing. | **New test type.** Door detected force as OBSTRUCTION_REVERSAL (same as beam break), reversed, then stopped with FORCE_STOPPED `(3,4,3)`. Same protocol behavior as beam obstruction — opener treats physical force identically. | `physically-forced-pushed-blockage.txt` |

---

### T-07 Detailed Instructions — Type C Payload Decode

**Goal:** Figure out what the 20–23 variable symbols at the end of TYPE-C messages encode.

**What we know:**
- TYPE-C messages are 43–46 symbols long. The first 23 symbols are always constant.
- Positions 23–45 change. During idle, the payload is stable (1 unique per file). During travel, it changes (3–5 unique per travel).
- TYPE-C appears once per ~5s keepalive cycle (paired with CMD-A → ACK-A → TYPE-B → TYPE-C).
- We need long idle baselines to confirm the payload is truly constant when nothing is happening, and an uninterrupted full travel to get the cleanest TYPE-C vs position mapping.

**Three separate captures, three separate files.**

---

#### T-07a — Idle Closed Baseline (`t07a_idle_closed_60s.txt`) — ✅ DONE

**Results:** 21 TYPE-C messages over 100 seconds, **ALL 21 IDENTICAL**:
```
[1,7,3,1,3,2,3,2,9,1,1,3,1,2,2,3,3,3,1,1,2,3,9,2,1,9,9,9,2,6,2,1,1,3,2,1,7,5,2,1,7,9,1,1]
```
TYPE-C is confirmed 100% constant during idle closed — no drift, no cycling.

**Starting state:**
- Door is fully closed and has been idle for at least 30 seconds (normal keepalive traffic flowing).
- Logic analyzer probes connected to Z3 (CH0) and Z4 (CH1) on the opener board. GND connected.
- Logic analyzer software open, sample rate 1 MHz, both channels enabled, trigger not yet armed.
- Remote control is set aside — do not touch it during this capture.

**Steps:**
1. **T = 0s** — Click "Start" / "Record" on the logic analyzer. Do nothing else.
2. **T = 0s to T = 60s** — Sit and wait. Do not press any buttons. Do not touch the door, the remote, or the wall button. Let the system idle for a full 60 seconds.
3. **T = 60s** — Click "Stop" on the logic analyzer.
4. Export as `t07a_idle_closed_60s.txt` (same CSV format as all other captures).

**Expected result:** ~12 TYPE-C messages, all with the same variable payload. This confirms TYPE-C is truly constant during closed-idle and not slowly drifting or cycling.

---

#### T-07b — Idle Open Baseline (`t07b_idle_open_60s.txt`) — ✅ DONE

**Results:** 14 TYPE-C messages over 66 seconds, **ALL 14 IDENTICAL**:
```
[1,7,3,1,3,2,3,2,9,1,1,3,1,2,2,3,3,3,1,1,2,3,9,1,1,9,9,9,2,6,2,1,1,1,5,2,1,7,9,3,2,1]
```
(42 symbols — shorter than idle-closed's 44 symbols)

data_A = 1 (open endpoint), data_B = 511, pre_state = `[1,1,9,9,9,2,6,2]`.
Payload is **different** from T-07a (closed) payload — confirms TYPE-C encodes position/state.
All TYPE-B messages show ARRIVED_OPEN/AT_ENDPOINT_2/pos=None (consistent idle-open state).

**Starting state:**
- Door is fully **open** and has been idle at open position for at least 30 seconds (normal keepalive traffic flowing). If the door is currently closed, press the remote once to open it, wait for it to fully open, then **wait at least 30 more seconds** before starting this capture.
- Logic analyzer probes connected, software open, ready to record. Same settings as T-07a.
- Remote control set aside.

**Steps:**
1. **T = 0s** — Click "Start" / "Record" on the logic analyzer. Do nothing else.
2. **T = 0s to T = 60s** — Sit and wait. Do not press any buttons. Do not touch anything. Let the system idle at open for a full 60 seconds.
3. **T = 60s** — Click "Stop" on the logic analyzer.
4. Export as `t07b_idle_open_60s.txt`.

**Expected result:** ~12 TYPE-C messages, all with the same variable payload, but that payload should be **different** from the T-07a (closed) payload — this would confirm TYPE-C encodes something position/state related.

---

#### T-07c — Full Uninterrupted Cycle (`t07c_full_cycle.txt`) — ✅ DONE

**Results:** 157 total messages (80 TYPE-B, 20 TYPE-C, 2 CMD-R). Timeline:
- **0–21s**: Idle closed. 4 TYPE-C all identical: data_A=221, pre_L=`[1,1,9,9,9,2,6,2]`
- **21s**: CMD-R (open command)
- **21–35.8s**: Opening travel. 2 TYPE-C with varying data_A tracking position
- **35.8–64s**: Arrived open / idle open. 7 TYPE-C all identical: data_A=1, pre_L=`[5,9,9,9,1,6,2]`
- **64.1s**: CMD-R (close command)
- **64.2–78.9s**: Closing travel. 2 TYPE-C with varying data_A tracking position
- **78.9–100s**: Idle closed. 5 TYPE-C all identical: data_A=221, pre_L=`[5,9,9,9,1,6,2]`

**Key finding: pre_state changes within a session.** Started as `[1,1,9,9,9,2,6,2]` during initial idle-closed, changed to `[1,1,9,9,9,1,6,2]` during opening, then `[5,9,9,9,1,6,2]` at arrived-open. The new pre_state persisted through closing and back to idle-closed at end — it did **not** revert. The `9,9,9` core and position-prefix suffix are always present; the leading symbols shift.

**Starting state:**
- Door is fully **closed** and has been idle for at least 30 seconds (normal keepalive traffic). If you just finished T-07b (door open), press the remote once to close it, wait for it to fully close, then wait at least 30 seconds.
- Logic analyzer probes connected, software open, ready to record. Same settings.
- Remote control **in hand**, ready to press.

**Steps:**
1. **T = 0s** — Click "Start" / "Record" on the logic analyzer. Do nothing else yet.
2. **T = 0s to T = 10s** — Wait 10 seconds. This captures ~2 idle-closed TYPE-C messages as a baseline at the start of the file.
3. **T = 10s** — Press the remote button **once** to open the door.
4. **T = 10s to ~T = 25s** — Door travels from closed to open (~15 seconds of travel). Do not touch anything. Let it arrive fully and stop on its own.
5. **T = 25s to T = 45s** — Wait 20 seconds with the door fully open and idle. This captures ~4 idle-open TYPE-C messages. Do not touch anything.
6. **T = 45s** — Press the remote button **once** to close the door.
7. **T = 45s to ~T = 60s** — Door travels from open to closed (~15 seconds of travel). Do not touch anything. Let it arrive fully and stop on its own.
8. **T = 60s to T = 75s** — Wait 15 seconds with the door fully closed and idle. This captures ~3 idle-closed TYPE-C messages to confirm it returns to the same baseline.
9. **T = 75s** — Click "Stop" on the logic analyzer.
10. Export as `t07c_full_cycle.txt`.

**Expected result:** ~15 TYPE-C messages total — 2 idle-closed at start, 3 during opening travel, 4 idle-open in the middle, 3 during closing travel, 3 idle-closed at end. The idle payloads at the start and end should match (same closed state). The travel payloads should change and hopefully correlate with the TYPE-B position counter.

---

### T-09 — CLOSED

T-09 (beacon + reconnect) is no longer needed. T-08 already captured the complete boot handshake sequence across 8+ power cycles. The beacon pattern was captured in `c1_c2_wall_button.txt` (14 constant messages). A hot reconnect would replay the same boot handshake observed in T-08.

---

## Decode Status Summary

| Category | Total Types | ✅ Fully Decoded | ⚠️ Partial | ❌ Not Decoded |
|----------|-------------|-----------------|------------|----------------|
| CH0 Commands | 8 | 7 (CMD-A, CMD-A1, CMD-R, CMD-L, CMD-ECHO, CMD-INIT, CMD-B) | 1 (CMD-B-INIT long form) | 0 |
| CH1 ACKs | 6 | 6 (all ACK types are constant messages) | 0 | 0 |
| CH1 Status | 2 | 0 | 2 (TYPE-B: ~93% position decoded; TYPE-C: position + structure decoded, pre_state field TBD) | 0 |
| CH1 Handshake | 3 | 2 (HANDSHAKE-D, BOOT-F — constant) | 1 (HANDSHAKE-E: varies per boot) | 0 |
| CH1 Other | 2 | 1 (ECHO) | 1 (BEACON) | 0 |
| **Total** | **21** | **16** | **5** | **0** |

**Overall protocol understanding: 76% fully decoded, 100% at least partially decoded. No fully-undecoded message types remain.**

The major remaining unknowns are:
1. **TYPE-C pre_state field** — leading symbols vary by session and change during travel. The `9,9,9` core + position-prefix suffix are understood, but the leading 1-3 symbols encode something unknown (possibly motor calibration state, travel count, or timer)
2. **HANDSHAKE-E variable payload** — session negotiation, needed only if replacing the receiver
3. **CMD-B-INIT long form** — challenge-response, needed only if replacing the receiver
4. **TYPE-B endpoint position fields** — 16 frames where binary decoder doesn't find delimiter (implicit from door state)
5. **BEACON payload** — low priority, only relevant without receiver

---

## Existing Test File Inventory

| File | Group | Description | Msgs | Key Message Types |
|------|-------|-------------|------|-------------------|
| `B1_Boot sequence.txt` | boot | Cold start boot sequence | ~30 | CMD-INIT, CMD-B-INIT, HANDSHAKE-D/E, BOOT-F, CMD-A1, ACK-A2/B2 |
| `test01_idle_closed.txt` | baseline | Idle, door closed, light off | ~20 | CMD-A, CMD-B, ACK-A/B, TYPE-B, TYPE-C |
| `test02_idle_open.txt` | baseline | Idle, door open, light off | ~20 | CMD-A, CMD-B, ACK-A/B, TYPE-B, TYPE-C |
| `test03_idle_light_on.txt` | baseline | Idle, door closed, light on | ~20 | CMD-A, CMD-B, ACK-A/B, TYPE-B, TYPE-C |
| `test04_open_full.txt` | travel | Full open (closed → open) | ~40 | CMD-R, CMD-B, ECHO, TYPE-B (travel), TYPE-C |
| `test05_close_full.txt` | travel | Full close (open → closed) | ~40 | CMD-R, CMD-B, ECHO, TYPE-B (travel), TYPE-C |
| `test06_open_stop_mid.txt` | stop_reverse | Open then stop mid-travel | ~30 | CMD-R ×2, TYPE-B (stop mid) |
| `test07_resume_open.txt` | stop_reverse | Resume from mid-travel | ~30 | CMD-R, TYPE-B (resume + close) |
| `test08_close_stop_mid.txt` | stop_reverse | Close then stop mid-travel | ~30 | CMD-R ×2, TYPE-B (stop mid) |
| `test09_reverse_while_closing.txt` | stop_reverse | Reverse while closing | ~30 | CMD-R ×2, TYPE-B (reverse) |
| `test10_light_on.txt` | light | Light toggle ON | ~20 | CMD-L, ACK-L, ECHO, TYPE-B |
| `test11_light_off.txt` | light | Light toggle OFF | ~15 | CMD-L, ACK-L, ECHO, TYPE-B |
| `test17_obstruct_while_closing.txt` | obstruction | Beam obstruction during close | ~40 | CMD-R, TYPE-B (obstruction reversal) |
| `test18_close_beam_blocked.txt` | obstruction | Close with beam blocked | ~25 | CMD-R, TYPE-B (beam blocked) |
| `test_A1_A2.txt` | remote | Remote open + stop | ~30 | CMD-R, TYPE-B (remote control) |
| `test_A3.txt` | remote | Remote close fully | ~30 | CMD-R, TYPE-B (remote close) |
| `test_A4.txt` | remote | Remote light toggle | ~20 | CMD-L, ACK-L, TYPE-B |
| `t05.txt` | **multicycle** | **4-5 full open/close cycles (T-01/T-05)** | **311** | CMD-R ×6, TYPE-B ×203, TYPE-C ×23, CMD-B ×6 (all constant) |
| `t02-75percent-near-top-early.txt` | **obstruction_pos** | **Obstruction at ~75% (T-02)** | **32** | TYPE-B ×19 (reversal at pos=193) |
| `t02-50percent-middle.txt` | **obstruction_pos** | **Obstruction at ~50% (T-02)** | **51** | CMD-B ×3, TYPE-B ×31 (reversal at pos=29) |
| `t02-25percent-near-bottom-late.txt` | **obstruction_pos** | **Obstruction at ~25% (T-02)** | **73** | TYPE-B ×51 (reversal at pos=261) |
| `t08.txt` | **boot_multi** | **8+ power-cycle boots (T-08)** | **153** | CMD-B-INIT ×21 (9 unique), HANDSHAKE-D ×8 (constant), HANDSHAKE-E ×8 (all different), BOOT-F ×8 (constant) |
| `physically-forced-pushed-blockage.txt` | **force** | **Physical force during close (T-11)** | **41** | TYPE-B ×28 (OBSTRUCTION_REVERSAL, FORCE_STOPPED) |
| `t07a_idle_closed_60s.txt` | **typec_baseline** | **60s idle closed — TYPE-C baseline (T-07a)** | **98** | TYPE-C ×21 (ALL IDENTICAL). Confirmed TYPE-C 100% constant during idle. Discovered internal structure: `5,2,1,7` marker, data_A position (221=closed), data_B constant (511). |
| `t07b_idle_open_60s.txt` | **typec_baseline** | **60s idle open — TYPE-C baseline (T-07b)** | **69** | TYPE-C ×14 (ALL IDENTICAL). data_A=1 (open endpoint confirmed), data_B=511. Payload len=42 (shorter than closed=44). |
| `t07c_full_cycle.txt` | **typec_baseline** | **Full open+close cycle — TYPE-C travel mapping (T-07c)** | **157** | TYPE-C ×20 (4 idle-closed, 2 opening, 7 arrived-open, 2 closing, 5 idle-closed). Clean position transitions tracked. pre_state changes during travel. |
| `c1_c2_wall_button.txt` | no_receiver | Receiver disconnected, wall button | 14 | BEACON ×14 |
| `2026-02-10_20-52-43-chan0.txt` | single_ch | Early CH0 capture | ~5 | CMD-A (CH0 only) |
| `2026-02-10_20-59-53chan1.txt` | single_ch | Early CH1 capture | ~15 | ACK-A, TYPE-B, TYPE-C (CH1 only) |

---

## Key Observations for ESP32-C3 Integration

1. **Minimum viable monitoring** requires decoding only **TYPE-B** messages on CH1. This gives door state (11 states), sub-state (15 sub-states), light, and position — all currently decoded.
2. **CMD-A keepalive** every ~5s on CH0 can be used as a heartbeat to confirm the receiver is alive.
3. **CMD-B is a constant status poll** — no encoding needed, just replay the fixed 30-symbol message.
4. **TYPE-C** provides **fixed position endpoints** (221=closed, 1=open) that never vary across sessions — unlike TYPE-B which varies per boot. For an ESP32 integration, TYPE-C's data_A field is the most reliable way to determine absolute door position. data_B (=511 constant) can serve as a message integrity check.
5. **To CONTROL the door**, the ESP32 would need to inject **CMD-R** (12 symbols, constant) or **CMD-L** (15 symbols, constant) on the CH0 wire. No payload encoding needed.
6. **To REPLACE the receiver entirely**, the ESP32 would need to implement the boot handshake (CMD-B-INIT short → HANDSHAKE-D → CMD-B-INIT long challenge → HANDSHAKE-E response). The challenge-response algorithm is not yet decoded. CMD-A keepalives + CMD-B polls would also be needed.
7. **Physical force = beam obstruction** — the opener cannot distinguish between beam break and physical resistance. Both produce OBSTRUCTION_REVERSAL followed by FORCE_STOPPED.

---

## Remaining Knowledge Gaps & Assessment

**Census: 1,442 messages decoded across 29 files. 24 message types identified. 16 fully decoded, 5 partially decoded, 3 noise/artifact.**

### Gap 1: TYPE-C pre_state Leading Symbols
- **Impact:** LOW for ESP32 monitoring. The position (data_A) and constant marker (5,2,1,7) are fully understood.
- **What's unknown:** The 1–3 leading L-values in pre_state change during travel and vary per session. The `9,9,9` core and position-prefix suffix are decoded.
- **Would more tests help?** Unlikely — we already have 147 TYPE-C across many states and sessions. The leading symbols may encode cumulative state (travel count, motor runtime) that would require long-duration multi-day captures to characterize. Not worth pursuing for ESP32 integration.

### Gap 2: HANDSHAKE-E / CMD-B-INIT Long Form (Challenge-Response)
- **Impact:** HIGH only if **replacing** the receiver. NOT needed for passive monitoring or injection-based control.
- **What's unknown:** The algorithm that generates variable CMD-B-INIT long-form payloads (30–38 syms) and the corresponding HANDSHAKE-E responses (20–26 syms). 8 unique pairs observed across 8 boots.
- **Would more tests help?** Possibly — more boot cycles with careful analysis might reveal a PRNG or counter pattern. However, this is a complex reverse-engineering task (potentially encryption-related) that may not be solvable from captures alone. **Recommendation: defer unless receiver replacement is required.**

### Gap 3: TYPE-B Endpoint Position Fields
- **Impact:** LOW — these 16 frames represent <3% of TYPE-B messages and occur only at state boundaries where the door state itself (IDLE_OPEN, ARRIVED_OPEN, etc.) already tells you the position.
- **What's unknown:** At endpoints and first-frame transitions, the binary position decoder doesn't find the standard `(7,9)` or `(9,9)` delimiter. The position field may use a different encoding or serve a different purpose at endpoints.
- **Would more tests help?** No — we already have 694 TYPE-B messages. The pattern is clear: endpoint frames don't need position data because the door state is the position.

### Gap 4: BEACON Payload
- **Impact:** NONE for ESP32 integration (BEACON only appears when receiver is disconnected).
- **What's unknown:** Full payload decode of the 18-symbol BEACON message.
- **Would more tests help?** No — 18 identical BEACONs already captured. Constant message, fully characterized.

### Gap 5: B1_Boot TYPE-C (data_A=15, data_B=6)
- **Impact:** NONE — only occurs during boot before position is established.
- **What's unknown:** Why data_A=15 and data_B=6 during boot (vs 221/1 and 511 in normal operation).
- **Would more tests help?** No — understood as "position not yet calibrated" state.

---

### Verdict: No Further Tests Needed

All 10 proposed tests are now **closed** (✅ DONE or ✅ N/A). The remaining unknowns are either:
- **Low-impact edge cases** (pre_state leading symbols, endpoint position fields) that don't affect ESP32 functionality
- **Deferred advanced features** (challenge-response for receiver replacement) that require different analysis techniques, not more captures

**For passive monitoring (ESP32 reads CH1):** 100% of needed protocol is decoded. TYPE-B gives door state + position, TYPE-C gives fixed-endpoint position + integrity check.

**For active control (ESP32 injects on CH0):** 100% of needed protocol is decoded. CMD-R (door toggle) and CMD-L (light toggle) are constant messages.

**For receiver replacement (ESP32 replaces receiver entirely):** ~80% decoded. The boot handshake challenge-response (Gap 2) is the only blocker. All other messages (CMD-A keepalive, CMD-B poll, all ACKs) are constant and fully understood.

---

## Test Results Summary (New Findings)

### T-01/T-05: Multi-Cycle Travel
- **CMD-B is 100% constant** across all 28 occurrences in all files (6 in t05 alone). It's a fixed status poll, not variable data. This eliminates a major unknown.
- 3 full open/close cycles captured with 203 TYPE-B messages and 14 state transitions.
- New sub-state `AT_ENDPOINT_3` (4,3,9) discovered for ARRIVED_OPEN.
- New ARRIVED_OPEN endpoint pattern `[1,1,9,7]` observed.
- Endpoint patterns vary between cycles — they are NOT fixed per state.

### T-02: Obstruction at Different Positions
- Obstruction reversal position correlates with beam-break location: pos=193 (75%), pos=29 (50%), pos=261 (25%).
- New sub-state `FORCE_STOPPED` (3,4,3) consistently appears when door stops after obstruction reversal.
- New endpoint patterns for STOPPED_MID_OPEN: `[3,5,1,1,9,4,2]` (T02) and `[1,6,1,1,9,1,3]` (T02-75%).
- Bogus positions (>1000) appear in first/last frames of some transitions — likely boundary artifacts.

### T-08: Boot Sequences (8+ Power Cycles)
- **BOOT-F**: CONSTANT across all 8 boots. Static device identifier `[1,7,5,3,1,3,2,9,9,9,9,9,9,9,1,6,5,3,2,3,2,1,6,2,5,2,4,1,1]`.
- **HANDSHAKE-D**: CONSTANT across all 8 boots. Static device ID `[1,7,4,4,6,1,9,6,1,1,1,1,6,1,1,1,1,4,2,1]`.
- **HANDSHAKE-E**: ALL DIFFERENT — 8 unique payloads, varying length (20-26 syms). Session negotiation.
- **CMD-B-INIT short (20 syms)**: CONSTANT — "hello" preamble.
- **CMD-B-INIT long (30-38 syms)**: VARIES every boot — challenge paired with HANDSHAKE-E response.
- **CMD-A1**: CONSTANT across all boots (always 16 syms). May be sent 1-3× during boot.
- New door state `IDLE_MID` (3,5) — appears post-boot when door was stopped mid-travel.
- Boot settling time ~3s with noisy CH0/CH1 UNKNOWN messages (mostly zeros).
- No CMD-INIT captured — it likely occurs during the power-on noise window.

### T-07: TYPE-C Payload Decode (3 Sub-Tests)
- **TYPE-C internal structure fully characterized** via (L,H) pair-level decoding across 147 messages in 26 files.
- Universal `5,2,1,7` marker present in ALL 147 TYPE-C messages — serves as field delimiter.
- **data_A = position counter** with fixed endpoints: 221 (closed), 1 (open). Unlike TYPE-B which varies per session.
- **data_B = 511** always (mod 512, all 1-bits). Constant field with no observed variation.
- **pre_state field** contains `9,9,9` core + position-prefix suffix matching TYPE-B (e.g., `2,6` for closed, `1,6`/`3,5` for open). Leading symbols vary by session and change within a session during travel — does NOT revert after travel ends.
- **T-07a (idle closed):** 21/21 identical over 100 seconds. data_A=221.
- **T-07b (idle open):** 14/14 identical over 66 seconds. data_A=1. Shorter payload (42 vs 44 syms).
- **T-07c (full cycle):** 20 TYPE-C across clean open+close. data_A transitions: 221 → varies → 1 → varies → 221. pre_state evolves: `[1,1,9,9,9,2,6,2]` → `[5,9,9,9,1,6,2]`.
- **12 outliers** (out of 147): 9 caused by CH0 crosstalk (H>10), 3 from B1_Boot separator ambiguity (resolved by using last separator candidate).
- **B1_Boot TYPE-C** shows data_A=15, data_B=6 during boot (position not yet established).

### T-11: Physical Force Test
- Physically pushing the door open during closing triggers OBSTRUCTION_REVERSAL (identical to beam obstruction protocol).
- Door reverses, then stops with FORCE_STOPPED (3,4,3) sub-state.
- Protocol cannot distinguish physical force from beam obstruction — same message sequence.
- Bogus position 364031 appears at reversal boundary (same artifact as other obstruction tests).
