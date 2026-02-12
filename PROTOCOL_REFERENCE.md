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
| **CMD-R** | COMMAND | exact | `1,7,1,1,5,5,2,9,1,6,4,2` | 12 | — (entire message is constant) | ✅ Fully decoded | Door toggle command — sent when remote/wall button pressed. 3 observed. | — | — |
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
| **TYPE-C** | FULL_STATUS | prefix | `1,7,3,1,3,2,3,2,9` | 43–46 | Positions 9–45 (34–37 symbols) | ❌ Not decoded | Extended status message, 70+ observed across 23 files. Constant header of 23 symbols (pos 0-22 never vary). Positions 23-36 are the variable "payload." Payload changes with door state and position. Idle files show 1 unique payload; travel files show up to 5 unique. | What do positions 23-36 encode? Likely carries position + state in a different encoding. | T-04, T-05, T-07 |
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

### Type C Message Structure (Partial)

```
Symbols:  [1,7,3,1,3,2,3,2,9 | (14 constant syms) | (variable 20-23 syms)]
           ├── header (9) ──┤    positions 9-22      positions 23-45
                              constant across ALL      CHANGES with state
                              observed messages         and position
```

49 instances observed across 17 files (all files except `c1_c2_wall_button.txt` and the two single-channel captures).

**Variable payload observations:**
- Idle files: 1 unique payload per file (stable)
- Travel files: 3–5 unique payloads per file (changes during motion)
- Payload varies with both door state AND position — not just state

**Recurring sub-patterns in variable portion:**
- Many payloads contain `9,9,9` or `9,9` clusters
- The sequence `5,2,1,7,9` appears in most payloads near the end
- The sequence `1,7,2,1` appears in some payloads
- Total variable-portion length: 20–23 symbols

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
| **T-02** | Obstruction at positions | ✅ DONE | Obstruction at ~75%, ~50%, ~25% during closing. | Confirmed: CMD-B payload unchanged by obstruction. Discovered new sub-state FORCE_STOPPED `(3,4,3)` for post-reversal stop. Found new door state transitions and endpoint patterns. | `t02-75percent-near-top-early.txt`, `t02-50percent-middle.txt`, `t02-25percent-near-bottom-late.txt` |
| **T-03** | CMD-B after light toggle | ~~Not needed~~ | CMD-B is constant — no light/timer correlation to test. | **CLOSED: CMD-B resolved as constant.** | — |
| **T-04** | Extended travel capture | Open | Capture at highest sample rate for denser Type B/C readings during travel. | Get more Type C payloads per travel for position correlation. | — |
| **T-05** | Endpoint position mapping | ✅ DONE | 3 full open/close cycles. | Collected 12 new endpoint frames. Found new ARRIVED_OPEN pattern `[1,1,9,7]`, new sub-state AT_ENDPOINT_3 `(4,3,9)`. Endpoint patterns are NOT constant between cycles — vary per cycle. | `t05.txt` |
| **T-06** | Mid-travel stop positions | Open | Stop at 25%, 50%, 75% during opening and closing. | Map STOPPED_MID position patterns. T02 provided some data (STOPPED_MID_OPEN with FORCE_STOPPED). | — |
| **T-07** | Type C isolation | Open | Long idle captures + travel for Type C correlation. | Isolate Type C payload changes vs position counter. | — |
| **T-08** | Boot sequence repeat | ✅ DONE | 8+ power cycles captured. | **Major findings:** BOOT-F constant (device ID), HANDSHAKE-D constant (device ID), HANDSHAKE-E varies every boot (session key), CMD-B-INIT has constant short form + variable long form (challenge-response). Found new door state IDLE_MID `(3,5)`. | `t08.txt` |
| **T-09** | Beacon isolation | Open | 60s beacon + reconnection capture. | Confirm beacon is constant, capture reconnect handshake. | — |
| **T-10** | Wall button vs remote | Open | Compare wall button and remote control messages. | Determine if CMD-R differs by source. | — |
| **T-11** | Physical force test | ✅ DONE | Physically pushed door open while it was closing. | **New test type.** Door detected force as OBSTRUCTION_REVERSAL (same as beam break), reversed, then stopped with FORCE_STOPPED `(3,4,3)`. Same protocol behavior as beam obstruction — opener treats physical force identically. | `physically-forced-pushed-blockage.txt` |

---

## Decode Status Summary

| Category | Total Types | ✅ Fully Decoded | ⚠️ Partial | ❌ Not Decoded |
|----------|-------------|-----------------|------------|----------------|
| CH0 Commands | 8 | 7 (CMD-A, CMD-A1, CMD-R, CMD-L, CMD-ECHO, CMD-INIT, CMD-B) | 1 (CMD-B-INIT long form) | 0 |
| CH1 ACKs | 6 | 6 (all ACK types are constant messages) | 0 | 0 |
| CH1 Status | 2 | 0 | 1 (TYPE-B: ~93% position decoded) | 1 (TYPE-C: payload unknown) |
| CH1 Handshake | 3 | 2 (HANDSHAKE-D, BOOT-F — constant) | 1 (HANDSHAKE-E: varies per boot) | 0 |
| CH1 Other | 2 | 1 (ECHO) | 1 (BEACON) | 0 |
| **Total** | **21** | **16** | **4** | **1** |

**Overall protocol understanding: 76% fully decoded, 95% at least partially decoded. Only TYPE-C payload remains fully undecoded.**

The major remaining unknowns are:
1. **TYPE-C variable payload** (positions 23-36) — highest priority for ESP32 integration
2. **HANDSHAKE-E variable payload** — session negotiation, needed only if replacing the receiver
3. **CMD-B-INIT long form** — challenge-response, needed only if replacing the receiver
4. **TYPE-B endpoint position fields** — 16 frames where binary decoder doesn’t find delimiter
5. **BEACON** — low priority, only relevant without receiver

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
| `c1_c2_wall_button.txt` | no_receiver | Receiver disconnected, wall button | 14 | BEACON ×14 |
| `2026-02-10_20-52-43-chan0.txt` | single_ch | Early CH0 capture | ~5 | CMD-A (CH0 only) |
| `2026-02-10_20-59-53chan1.txt` | single_ch | Early CH1 capture | ~15 | ACK-A, TYPE-B, TYPE-C (CH1 only) |

---

## Key Observations for ESP32-C3 Integration

1. **Minimum viable monitoring** requires decoding only **TYPE-B** messages on CH1. This gives door state (11 states), sub-state (15 sub-states), light, and position — all currently decoded.
2. **CMD-A keepalive** every ~5s on CH0 can be used as a heartbeat to confirm the receiver is alive.
3. **CMD-B is a constant status poll** — no encoding needed, just replay the fixed 30-symbol message.
4. **TYPE-C** appears to be a richer status packet but is redundant with TYPE-B for basic monitoring — it can be deferred.
5. **To CONTROL the door**, the ESP32 would need to inject **CMD-R** (12 symbols, constant) or **CMD-L** (15 symbols, constant) on the CH0 wire. No payload encoding needed.
6. **To REPLACE the receiver entirely**, the ESP32 would need to implement the boot handshake (CMD-B-INIT short → HANDSHAKE-D → CMD-B-INIT long challenge → HANDSHAKE-E response). The challenge-response algorithm is not yet decoded. CMD-A keepalives + CMD-B polls would also be needed.
7. **Physical force = beam obstruction** — the opener cannot distinguish between beam break and physical resistance. Both produce OBSTRUCTION_REVERSAL followed by FORCE_STOPPED.

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

### T-11: Physical Force Test
- Physically pushing the door open during closing triggers OBSTRUCTION_REVERSAL (identical to beam obstruction protocol).
- Door reverses, then stops with FORCE_STOPPED (3,4,3) sub-state.
- Protocol cannot distinguish physical force from beam obstruction — same message sequence.
- Bogus position 364031 appears at reversal boundary (same artifact as other obstruction tests).
