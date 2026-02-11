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
| **CMD-A** | COMMAND | exact | `1,7,1,1,5,1,4,2,9,2,3,2,4,2,1` | 15 | — (no payload; entire message is constant) | ✅ Fully decoded | Keepalive heartbeat, sent every ~5 s. 63 observed across all test files. | — | — |
| **CMD-A1** | COMMAND | exact | `1,7,1,1,5,1,4,2,9,1,3,2,1,2,2,1` | 16 | — (entire message is constant) | ✅ Fully decoded | Transitional first keepalive sent once after boot handshake. 1 observed (boot only). | — | — |
| **CMD-R** | COMMAND | exact | `1,7,1,1,5,5,2,9,1,6,4,2` | 12 | — (entire message is constant) | ✅ Fully decoded | Door toggle command — sent when remote/wall button pressed. 3 observed. | — | — |
| **CMD-L** | COMMAND | exact | `1,7,1,1,5,1,3,2,2,6,1,6,1,1,2` | 15 | — (entire message is constant) | ✅ Fully decoded | Light toggle command. 2 observed. | — | — |
| **CMD-ECHO** | COMMAND | exact | `1,7,1,1,5,5,1,9,1,7,2,1,1` | 13 | — (entire message is constant) | ✅ Fully decoded | Post-command echo sent after CMD-R or CMD-L. 1 observed. | — | — |
| **CMD-INIT** | COMMAND | exact | `0,0,0,0,0,3` | 6 | — (entire message is constant) | ⚠️ Partially decoded | Boot hello/reset — first message from receiver after power-on. 1 observed. Six zeros then 3; could be a reset pulse. | Why `0,0,0,0,0,3`? Is the 3 a version byte? | T-08 |
| **CMD-B** | COMMAND | prefix | `1,7,3,4` | 30 | Positions 4–29 (26 symbols) | ❌ Not decoded | Header `1,7,3,4` identifies extended command. 13 observed across 6 files. Always paired with ACK-B response. 1 dominant payload pattern (10×); 2 minor variants (1× each in `test17`, `test_A1_A2`). | Entire payload: what is being commanded/queried? Purpose of the three payload variants? | T-01, T-02, T-03 |
| **CMD-B-INIT** | COMMAND | prefix | `1,7,3,4,1,4,1,9` | 20 or 32 | Positions 8–19/31 (12 or 24 symbols) | ❌ Not decoded | Boot handshake config message. 2 observed (boot only). Two different lengths suggest a multi-part handshake. | Entire payload: firmware version? device ID? config parameters? | T-08 |

---

### CH1 — Opener → Receiver (Responder)

| Name | Category | Match | Header (symbols) | Total Syms | Payload | Decode Status | Known Fields | Unknown Fields | Test Ref |
|------|----------|-------|-------------------|------------|---------|---------------|--------------|----------------|----------|
| **ACK-A** | ACK | exact | `1,7,3,5,1,4,1,9,1,1,2,1` | 12 | — (entire message is constant) | ✅ Fully decoded | Simple ACK for CMD-A keepalive. 50 observed. | — | — |
| **ACK-A2** | ACK | exact | `1,7,3,5,1,4,9,1,1,2` | 10 | — (entire message is constant) | ✅ Fully decoded | Boot/transitional ACK variant. 2 observed (boot only). | — | — |
| **ACK-R** | ACK | exact | `1,7,3,5,5,1,9,3,1,1` | 10 | — (entire message is constant) | ✅ Fully decoded | ACK for CMD-R door toggle. 3 observed. | — | — |
| **ACK-L** | ACK | exact | `1,7,3,5,1,3,1,9,1,1,1,1` | 12 | — (entire message is constant) | ✅ Fully decoded | ACK for CMD-L light toggle. 2 observed. | — | — |
| **ACK-B** | ACK | exact | `1,7,3,5,4,9,3` | 7 | — (entire message is constant) | ✅ Fully decoded | ACK for CMD-B extended command. 6 observed. | — | — |
| **ACK-B2** | ACK | exact | `1,7,3,5,5,9,3,1` | 8 | — (entire message is constant) | ✅ Fully decoded | Boot variant ACK for CMD-B. 1 observed. | — | — |
| **TYPE-B** | STATUS | prefix | `1,7,2,1,4,6,2,9` | 17–26 | Positions 0–17 (9–18 symbols) | ⚠️ Partially decoded | Primary status message, 235 observed. **Decoded fields:** door state (pos 0-1, 10 states), sub-state (pos 2-4, 12 sub-states), light (pos 1-4 when closed), position prefix (pos 5-6), position counter (pos 7+ via binary decoder, 9-bit mod 512). 219/235 positions fully decoded (93.2%). | 16 endpoint/transitional position fields (see Endpoint Patterns below). Positions 5-6 prefix `(9,X)` short variant not fully understood. | T-04, T-05, T-06 |
| **TYPE-C** | FULL_STATUS | prefix | `1,7,3,1,3,2,3,2,9` | 43–46 | Positions 9–45 (34–37 symbols) | ❌ Not decoded | Extended status message, 49 observed across 17 files. Constant header of 23 symbols (pos 0-22 never vary). Positions 23-36 are the variable "payload." Present in every test file. Payload changes with door state and position — not constant per state. Idle files show 1 unique payload; travel files show up to 5 unique payloads. | What do positions 23-36 encode? Likely carries position + state in a different encoding. Some symbols correlate with position ranges. | T-04, T-05, T-07 |
| **BEACON** | BEACON | prefix | `8,5,5` | 21 | Positions 3–20 (18 symbols) | ⚠️ Partially decoded | Opener polling beacon when no receiver is connected. 18 observed. 3 patterns seen (variants likely due to CH0 crosstalk on H values — symbols 10, 49 etc.). Core L-only pattern is constant. | Confirm crosstalk hypothesis. Is there any actual data variation? | T-09 |
| **ECHO** | ECHO | prefix | `1,7,1,1,5,5,1,9` | ~13 | Positions 8–12 (varies) | ⚠️ Partially decoded | Opener relays received CMD-R/CMD-L back. 5 observed. Appears to be a literal echo of the received command. | Confirm it's always an exact echo. | — |
| **HANDSHAKE-D** | HANDSHAKE | prefix | `1,7,4,4,6,1,9` | 22 | Positions 7–21 (15 symbols) | ❌ Not decoded | Boot handshake response (type D). 1 observed. | Entire payload. | T-08 |
| **HANDSHAKE-E** | HANDSHAKE | prefix | `1,7,4,4,2,3,1,9` | 23 | Positions 8–22 (15 symbols) | ❌ Not decoded | Boot handshake response (type E). 1 observed. | Entire payload. | T-08 |
| **BOOT-F** | HANDSHAKE | prefix | `1,7,5,3` | 29 | Positions 4–28 (25 symbols) | ❌ Not decoded | Boot-only message seen once after handshake. 1 observed. | Entire payload. Device ID? firmware version? capabilities? | T-08 |

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

**Endpoint Position Patterns** (16 undecoded Type B frames):

| Door State | Raw Position Field (L-only) | Count | Notes |
|---|---|---|---|
| IDLE_OPEN | `[1,9,5,1]` | Multiple | Short, no standard delimiter |
| ARRIVED_OPEN | `[7,1,1,9,1,5]` | Multiple | Two patterns observed |
| ARRIVED_OPEN | `[6,1,1,9,2,4]` | Multiple | |
| OPENING (transitional) | `[1,7,1,1,9,3,3,1]` | 1 | First frame of travel |
| CLOSING (transitional) | `[1,7,1,1,9,2,4,1]` | 1 | First frame of travel |
| CLOSING (transitional) | `[2,6,1,1,9,1,4,1]` | 1 | Variant |
| STOPPED_MID_OPEN | `[2,6,1,1,9,2,1,2]` | 1 | |
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
BOOT SEQUENCE:
  CH0: CMD-INIT → CH1: HANDSHAKE-D
  CH0: CMD-B-INIT (20 syms) → CH1: ACK-B2
  CH0: CMD-B-INIT (32 syms) → CH1: HANDSHAKE-E
  CH1: BOOT-F (unsolicited)
  CH0: CMD-A1 → CH1: ACK-A2, ACK-A2
  CH0: CMD-B → CH1: ACK-B, TYPE-B, TYPE-C

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

| Test ID | Name | Description | Purpose / Gap Filled | Capture Method | Expected Captures | Files to Produce |
|---------|------|-------------|---------------------|----------------|-------------------|------------------|
| **T-01** | CMD-B pattern correlation | Capture 5+ full open/close cycles back-to-back without power cycling. Log timestamps of button presses. Compare CMD-B payloads across cycles. | Determine if the 3 CMD-B payload variants correlate with door state, cycle count, or sequence position. | Dual-channel, continuous | 5 full open+close cycles | `test_T01_multicycle.txt` |
| **T-02** | CMD-B obstruction variants | Trigger obstruction (break beam) at 3 different positions during closing: early (~75%), mid (~50%), late (~25%). | The minor CMD-B variants appeared in obstruction/reversal files (`test17`, `test_A1_A2`). Confirm whether CMD-B payload changes with obstruction position or obstruction count. | Dual-channel, 3 separate captures | 3 obstruction events at different positions | `test_T02a_obstruct_early.txt`, `test_T02b_obstruct_mid.txt`, `test_T02c_obstruct_late.txt` |
| **T-03** | CMD-B after light toggle | Capture: (a) power on, (b) toggle light 5× (ON→OFF→ON→OFF→ON), (c) toggle door, (d) toggle light while door is moving. | Determine if CMD-B payload encodes light state, timer state, or a cumulative command counter. | Dual-channel, continuous | Multiple light and door events | `test_T03_light_multi.txt` |
| **T-04** | Extended travel capture (slow) | Capture a VERY slow open or close (if the opener supports a slow-speed mode or use TTC/force settings). Otherwise, capture a normal full open+close at highest available sample rate. | Get more Type B and Type C messages per travel for finer-grained position/Type-C correlation. The current ~5-10 messages per travel is sparse. | Dual-channel, continuous, fast sample rate | 1 full open + 1 full close | `test_T04_extended_travel.txt` |
| **T-05** | Endpoint position mapping | Perform 3 consecutive full cycles: closed→open→closed→open→closed→open. Do NOT press any buttons between cycles — let the door reach full endpoint each time. | Collect more endpoint Type B frames. Currently only 16 undecoded endpoint messages across all files. Need statistical sample to see if the endpoint position field is constant or varies. | Dual-channel, continuous | 3 full round-trips (6 travel events) | `test_T05_endpoint_cycles.txt` |
| **T-06** | Mid-travel stop positions | Stop the door at approximately 25%, 50%, 75% travel during OPENING. Then reverse and stop at 75%, 50%, 25% during CLOSING. Note approximate stop positions. | Map the STOPPED_MID_OPEN / STOPPED_MID_CLOSE endpoint patterns vs actual position. Currently only 1 mid-stop sample. | Dual-channel, 6 separate stops | 6 stop events at different positions | `test_T06_midstops.txt` |
| **T-07** | Type C isolation | Capture two idle periods (30s each): one with door closed, one with door open. Then capture one full open+close cycle. Run analysis to extract Type C payloads aligned with nearest Type B position readings. | Isolate Type C variable payload changes. Currently we see Type C varies during travel but need denser sampling to correlate with exact position counter values. | Dual-channel, 3 segments | 2 idle + 1 travel | `test_T07a_idle_closed_long.txt`, `test_T07b_idle_open_long.txt`, `test_T07c_travel.txt` |
| **T-08** | Boot sequence repeat (3×) | Power-cycle the opener board 3 times with receiver connected, capturing each boot sequence. | Currently only 1 boot capture. Need to determine: (a) is CMD-INIT `0,0,0,0,0,3` always identical? (b) do CMD-B-INIT or HANDSHAKE payloads contain serial number, firmware version, or session ID? (c) is BOOT-F constant? | Dual-channel, 3 separate power cycles | 3 boot events | `test_T08a_boot.txt`, `test_T08b_boot.txt`, `test_T08c_boot.txt` |
| **T-09** | Beacon isolation | Disconnect receiver, capture 60s of BEACON-only traffic. Then reconnect receiver and capture the re-handshake. | Confirm beacon H-value anomalies are crosstalk. Determine if beacon payload carries any state info. Capture receiver reconnection handshake (never captured before). | CH1 only → then dual-channel for reconnect | 1 beacon period + 1 reconnect | `test_T09a_beacon_long.txt`, `test_T09b_reconnect.txt` |
| **T-10** | Wall button vs remote | Press wall button to open, then use remote to stop. Then use remote to open and wall button to stop. | Determine if CMD-R differentiates between wall button and remote sources, or if some other message differs. | Dual-channel, continuous | 4 button events (2 wall, 2 remote) | `test_T10_wall_vs_remote.txt` |

---

## Decode Status Summary

| Category | Total Types | ✅ Fully Decoded | ⚠️ Partial | ❌ Not Decoded |
|----------|-------------|-----------------|------------|----------------|
| CH0 Commands | 8 | 5 (CMD-A, CMD-A1, CMD-R, CMD-L, CMD-ECHO) | 1 (CMD-INIT) | 2 (CMD-B, CMD-B-INIT) |
| CH1 ACKs | 6 | 6 (all ACK types are constant messages) | 0 | 0 |
| CH1 Status | 2 | 0 | 1 (TYPE-B: 93% position decoded) | 1 (TYPE-C: payload unknown) |
| CH1 Other | 4 | 0 | 2 (BEACON, ECHO) | 2 (HANDSHAKE-D, HANDSHAKE-E) |
| CH1 Boot | 1 | 0 | 0 | 1 (BOOT-F) |
| **Total** | **21** | **11** | **4** | **6** |

**Overall protocol understanding: 52% fully decoded, 71% at least partially decoded.**

The 6 undecoded types (CMD-B, CMD-B-INIT, TYPE-C, HANDSHAKE-D, HANDSHAKE-E, BOOT-F) account for most remaining mystery. Of these, **CMD-B** and **TYPE-C** are the highest priority because they appear during normal operation and likely carry actionable data for the ESP32-C3 integration.

---

## Existing Test File Inventory

| File | Group | Description | Message Types Present |
|------|-------|-------------|----------------------|
| `B1_Boot sequence.txt` | boot | Cold start boot sequence | CMD-INIT, CMD-A1, CMD-B-INIT, CMD-B, CMD-A, ACK-A2, ACK-B2, ACK-A, ACK-B, HANDSHAKE-D, HANDSHAKE-E, BOOT-F, TYPE-B, TYPE-C |
| `test01_idle_closed.txt` | baseline | Idle, door closed, light off | CMD-A, CMD-B, ACK-A, ACK-B, TYPE-B, TYPE-C |
| `test02_idle_open.txt` | baseline | Idle, door open, light off | CMD-A, CMD-B, ACK-A, ACK-B, TYPE-B, TYPE-C |
| `test03_idle_light_on.txt` | baseline | Idle, door closed, light on | CMD-A, CMD-B, ACK-A, ACK-B, TYPE-B, TYPE-C |
| `test04_open_full.txt` | travel | Full open (closed → open) | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test05_close_full.txt` | travel | Full close (open → closed) | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test06_open_stop_mid.txt` | stop_reverse | Open then stop mid-travel | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test07_resume_open.txt` | stop_reverse | Resume from mid-travel | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test08_close_stop_mid.txt` | stop_reverse | Close then stop mid-travel | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test09_reverse_while_closing.txt` | stop_reverse | Reverse while closing | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test10_light_on.txt` | light | Light toggle ON | CMD-A, CMD-L, CMD-ECHO, CMD-B, ACK-A, ACK-L, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test11_light_off.txt` | light | Light toggle OFF | CMD-A, CMD-L, CMD-ECHO, CMD-B, ACK-A, ACK-L, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test17_obstruct_while_closing.txt` | obstruction | Beam obstruction during close | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test18_close_beam_blocked.txt` | obstruction | Close with beam blocked | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test_A1_A2.txt` | remote | Remote open + stop | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test_A3.txt` | remote | Remote close fully | CMD-A, CMD-R, CMD-ECHO, CMD-B, ACK-A, ACK-R, ACK-B, ECHO, TYPE-B, TYPE-C |
| `test_A4.txt` | remote | Remote light toggle | CMD-A, CMD-L, CMD-ECHO, CMD-B, ACK-A, ACK-L, ACK-B, ECHO, TYPE-B, TYPE-C |
| `c1_c2_wall_button.txt` | no_receiver | Receiver disconnected, wall button | BEACON (CH1 only) |
| `2026-02-10_20-52-43-chan0.txt` | single_ch | Early CH0 capture | CMD-A (CH0 only) |
| `2026-02-10_20-59-53chan1.txt` | single_ch | Early CH1 capture | ACK-A, TYPE-B, TYPE-C (CH1 only) |

---

## Key Observations for ESP32-C3 Integration

1. **Minimum viable monitoring** requires decoding only **TYPE-B** messages on CH1. This gives door state, sub-state, light, and position — all currently decoded.
2. **CMD-A keepalive** every ~5s on CH0 can be used as a heartbeat to confirm the receiver is alive.
3. **TYPE-C** appears to be a richer status packet but is redundant with TYPE-B for basic monitoring — it can be deferred.
4. **To CONTROL the door**, the ESP32 would need to inject **CMD-R** (door toggle) or **CMD-L** (light toggle) on the CH0 wire. These are fixed constant messages — no payload encoding needed.
5. **CMD-B** understanding would be needed if the ESP32 must replace the receiver entirely (not just sniff). For passive monitoring, CMD-B can be ignored.
