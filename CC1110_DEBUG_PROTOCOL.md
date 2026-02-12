# CC1110F32 Debug Interface Protocol — Bit-Bang Reference

## Overview

The CC1110/CC2510/CC1111/CC2511 family uses the **TI CC Debug** interface, a synchronous 3-wire serial protocol for flash programming, debug, and chip identification. This document covers the exact wire-level details needed to implement a bit-bang debugger on an ESP32-C3 targeting a **CC1110F32**.

**Key distinction:** The CC1110/CC2510 family uses **instruction table version 2** with different opcodes than the CC253x/CC254x family (version 1). Many open-source tools default to CC254x opcodes — using those on a CC1110 will fail silently.

Sources: TI SWRU191 (CC111x/CC251x User Guide), cc-tool (dashesy/cc-tool), CCLib (wavesoft/CCLib), flash_cc2531 (jmichault/flash_cc2531), CCLoader (RedBearLab/CCLoader).

---

## 1. Physical Interface

| Signal | Direction | Description |
|--------|-----------|-------------|
| **RESET_N** | Host → Target | Active-low reset. Open-drain or push-pull to target's reset pin. |
| **DC** (Debug Clock) | Host → Target | Clock signal, always driven by host. |
| **DD** (Debug Data) | **Bidirectional** | Host drives during command/data TX; target drives during response RX. |
| **GND** | Common | Must be connected. |

DD is bidirectional — the host must tristate/switch DD to input when reading responses. On ESP32-C3, use a single GPIO with direction switching, or two GPIOs (one output, one input) tied together.

---

## 2. Entering Debug Mode

The chip enters debug mode when it sees **two rising edges on DC while RESET_N is held low**.

### Exact Sequence

```
                    ┌──────┐      ┌──────┐
  DC:  ─────────────┘      └──────┘      └───────────────────
                    ↑rise1        ↑rise2
  DD:  ──────────────────────────────────────────────────────  (LOW or Hi-Z)

                 ┌────────────────────────────────────────┐
RESET_N: ────────┘                                        └──  (release HIGH)
              assert LOW                               release
```

### C-Pseudocode

```c
// All pins start as outputs, DC=LOW, DD=LOW
gpio_set(RESET_N, LOW);
delay_us(10000);              // Hold reset at least 1–10 ms

gpio_set(DC, HIGH);           // Rising edge 1
delay_us(3);
gpio_set(DC, LOW);
delay_us(3);
gpio_set(DC, HIGH);           // Rising edge 2
delay_us(3);
gpio_set(DC, LOW);
delay_us(4);

gpio_set(RESET_N, HIGH);     // Release reset — chip enters debug mode
delay_us(10000);              // Wait for chip to stabilize
```

**After this sequence, the CPU is halted** and the debug interface is active. The first thing to do is READ_STATUS to confirm CPU_HALTED (bit 5) is set.

---

## 3. Bit-Level Protocol

### Writing a Byte (Host → Target)

- **MSB first**
- Host places data bit on DD **before** the rising edge of DC
- Target samples DD on the **rising edge** of DC

```c
void debug_write_byte(uint8_t data) {
    // DD must be output
    for (int i = 0; i < 8; i++) {
        // Set data bit BEFORE rising edge
        gpio_set(DD, (data & 0x80) ? HIGH : LOW);
        data <<= 1;

        gpio_set(DC, HIGH);     // Rising edge — target captures
        delay_us(1);            // t_clk_high
        gpio_set(DC, LOW);      // Falling edge
        delay_us(1);            // t_clk_low
    }
}
```

### Reading a Byte (Target → Host)

- **MSB first**
- Target drives DD on the rising edge of DC
- Host reads DD while DC is high

```c
uint8_t debug_read_byte(void) {
    // DD must be input (Hi-Z)
    uint8_t data = 0;
    for (int i = 0; i < 8; i++) {
        gpio_set(DC, HIGH);     // Rising edge — target drives DD
        delay_us(1);

        data <<= 1;
        if (gpio_read(DD))
            data |= 0x01;

        gpio_set(DC, LOW);      // Falling edge
        delay_us(1);
    }
    return data;
}
```

### Ready Signaling (switchRead)

After writing a command (and any input bytes), the host must:

1. Switch DD to **input** (Hi-Z)
2. Wait at least 83 ns (`t_dir_change`)
3. Check if DD is LOW (target is ready)
4. If DD is HIGH, clock out 8 bits (full byte clock cycles) and check again
5. Repeat until DD goes LOW or timeout
6. Once DD is LOW, read the response byte(s)

```c
bool debug_switch_read(int max_wait_cycles) {
    gpio_set_direction(DD, INPUT);
    delay_us(1);  // t_dir_change (>83 ns)

    while (gpio_read(DD) == HIGH) {
        // Clock out 8 dummy cycles
        for (int i = 0; i < 8; i++) {
            gpio_set(DC, HIGH);
            delay_us(1);
            gpio_set(DC, LOW);
            delay_us(1);
        }
        if (--max_wait_cycles == 0)
            return false;  // Timeout
    }
    delay_us(1);  // t_sample_wait
    return true;   // Target is ready
}
```

After reading response bytes, switch DD back to output:
```c
gpio_set_direction(DD, OUTPUT);
```

---

## 4. Debug Commands — CC1110 Instruction Table (Version 2)

**These are the wire-level opcodes for CC1110/CC2510/CC1111/CC2511.** Do NOT use CC254x opcodes.

| Command | Opcode | Input Bytes | Output Bytes | Description |
|---------|--------|-------------|--------------|-------------|
| **CHIP_ERASE** | `0x14` | 0 | 1 (status) | Erase entire flash + lock bits |
| **WR_CONFIG** | `0x1D` | 1 (config) | 1 (status) | Write debug configuration |
| **RD_CONFIG** | `0x24` | 0 | 1 (config) | Read debug configuration |
| **GET_PC** | `0x28` | 0 | 2 (PCH, PCL) | Read program counter |
| **READ_STATUS** | `0x34` | 0 | 1 (status) | Read debug status |
| **HALT** | `0x44` | 0 | 1 (status) | Halt CPU |
| **RESUME** | `0x4C` | 0 | 1 (status) | Resume CPU execution |
| **DEBUG_INSTR_1** | `0x55` | 1 (opcode) | 1 (ACC) | Execute 1-byte 8051 instruction |
| **DEBUG_INSTR_2** | `0x56` | 2 (opcodes) | 1 (ACC) | Execute 2-byte 8051 instruction |
| **DEBUG_INSTR_3** | `0x57` | 3 (opcodes) | 1 (ACC) | Execute 3-byte 8051 instruction |
| **STEP_INSTR** | `0x5C` | 0 | 1 (ACC) | Step one instruction |
| **GET_CHIP_ID** | `0x68` | 0 | 2 (ID, Rev) | Read chip ID and revision |
| **BURST_WRITE** | `0x80` | 2+N (lenH, lenL, data...) | 1 (status) | Burst write N bytes to DBGDATA |

### Opcode Encoding Pattern

The command byte encodes: `CMD[7:3] | NUM[2:0]`

- Bits [7:3] = command identifier
- Bits [2:0] = varies per command (input/output byte count encoding)

For DEBUG_INSTR: base = `0x54`, lower 2 bits = instruction byte count (1, 2, or 3).

### Comparison: CC1110 (v2) vs CC254x (v1) Opcodes

| Command | CC1110 (v2) | CC254x (v1) | Upper 5 bits |
|---------|-------------|-------------|--------------|
| CHIP_ERASE | **0x14** | 0x10 | 00010 (same) |
| WR_CONFIG | **0x1D** | 0x18 | 00011 (same) |
| RD_CONFIG | **0x24** | 0x20 | 00100 (same) |
| GET_PC | **0x28** | 0x28 | 00101 (same) |
| READ_STATUS | **0x34** | 0x30 | 00110 (same) |
| HALT | **0x44** | 0x40 | 01000 (same) |
| RESUME | **0x4C** | 0x48 | 01001 (same) |
| DEBUG_INSTR_1 | **0x55** | 0x51 | 01010 (same) |
| DEBUG_INSTR_2 | **0x56** | 0x52 | 01010 (same) |
| DEBUG_INSTR_3 | **0x57** | 0x53 | 01010 (same) |
| STEP_INSTR | **0x5C** | 0x58 | 01011 (same) |
| GET_CHIP_ID | **0x68** | 0x68 | 01101 (same) |
| BURST_WRITE | **0x80** | 0x80 | 10000 (same) |

The upper 5 command-ID bits are identical; only the lower 3 differ between versions.

---

## 5. Debug Status Register (READ_STATUS Response)

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 7 | `0x80` | CHIP_ERASE_BUSY | 1 = chip erase in progress |
| 6 | `0x40` | PCON_IDLE | 1 = chip in idle mode |
| 5 | `0x20` | CPU_HALTED | 1 = CPU is halted (debug mode active) |
| 4 | `0x10` | PM_ACTIVE | 1 = power mode active |
| 3 | `0x08` | HALT_STATUS | 1 = halted by HALT command (vs breakpoint) |
| 2 | `0x04` | **DEBUG_LOCKED** | **1 = debug interface is locked** |
| 1 | `0x02` | OSC_STABLE | 1 = oscillator is stable |
| 0 | `0x01` | STACK_OVERFLOW | 1 = stack overflow detected |

**After entering debug mode, a normal (unlocked) chip should return status `0x20` or `0x22`** (CPU_HALTED, possibly OSC_STABLE).

**If bit 2 (0x04) is set → the chip is debug-locked.** Flash cannot be read. Only CHIP_ERASE can unlock it (which destroys all flash contents).

---

## 6. Debug Configuration Register (WR_CONFIG / RD_CONFIG)

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 0 | `0x01` | SEL_FLASH_INFO_PAGE | 1 = redirect flash operations to info page |
| 1 | `0x02` | TIMER_SUSPEND | 1 = suspend timers during debug |
| 2 | `0x04` | DMA_PAUSE | 1 = pause DMA during debug |
| 3 | `0x08` | TIMERS_OFF | 1 = stop all timers |
| 5 | `0x20` | SOFT_POWER_MODE | 1 = enable soft power mode |

**Recommended initial config:** `0x22` (TIMER_SUSPEND | SOFT_POWER_MODE) — this is what cc-tool uses after connecting.

---

## 7. Command Protocol Details

### 7.1 READ_STATUS

```
Host sends:   [0x34]              ← 1 byte command
Host waits:   switchRead()        ← wait for DD LOW
Host reads:   [status]            ← 1 byte response
```

### 7.2 GET_CHIP_ID

```
Host sends:   [0x68]              ← 1 byte command
Host waits:   switchRead()
Host reads:   [chip_id] [revision] ← 2 bytes response
```

Returns chip ID as byte 0 and silicon revision as byte 1. For CC2510, chip_id = `0x81`. The CC1110's chip ID will identify the exact variant.

The chip ID is also at SFR CHIPID = `0x37` (XDATA `0xDF37`), and chip revision at CHVER = `0x36` (XDATA `0xDF36`).

### 7.3 DEBUG_INSTR (Execute 8051 Instructions)

This is the workhorse command. It executes 1, 2, or 3 byte 8051 instructions on the halted CPU and returns the accumulator (A register) value.

**1-byte instruction (e.g., `NOP`, `CLR A`, `INC DPTR`):**
```
Host sends:   [0x55] [opcode0]
Host waits:   switchRead()
Host reads:   [ACC]               ← accumulator after execution
```

**2-byte instruction (e.g., `MOV A, direct`, `MOV A, #imm`):**
```
Host sends:   [0x56] [opcode0] [opcode1]
Host waits:   switchRead()
Host reads:   [ACC]
```

**3-byte instruction (e.g., `MOV DPTR, #imm16`, `MOV direct, #imm`):**
```
Host sends:   [0x57] [opcode0] [opcode1] [opcode2]
Host waits:   switchRead()
Host reads:   [ACC]
```

### 7.4 BURST_WRITE

Writes a block of bytes to the DBGDATA register (used with DMA for flash programming).

```
Host sends:   [0x80 | (lenH & 0x07)] [lenL] [data0] [data1] ... [dataN-1]
Host waits:   switchRead()
Host reads:   [status]

Where: total_length = (lenH << 8) | lenL
       lenH is OR'd into the command byte (upper bits of length)
```

### 7.5 CHIP_ERASE

```
Host sends:   [0x14]
Host waits:   switchRead()
Host reads:   [status]

Then poll READ_STATUS until bit 7 (CHIP_ERASE_BUSY) clears:
  do {
      status = read_status();
  } while (status & 0x80);
```

**WARNING: Chip erase destroys ALL flash content, configuration, and lock bits.**

### 7.6 WR_CONFIG

```
Host sends:   [0x1D] [config_byte]
Host waits:   switchRead()
Host reads:   [status]
```

### 7.7 HALT / RESUME

```
HALT:   Host sends [0x44], waits, reads [status]
RESUME: Host sends [0x4C], waits, reads [status]
```

---

## 8. CC1110F32 Chip Specifics

### Memory Map

| Region | Address Range | Size | Description |
|--------|--------------|------|-------------|
| **Flash** | `0x0000`–`0x7FFF` (CODE) | 32 KB | Program flash (CC1110F32) |
| **SRAM** | Varies by variant | 1–4 KB | Internal RAM |
| **SFR** | `0x80`–`0xFF` (direct) | 128 bytes | Special Function Registers |
| **XDATA SFR** | `0xDF00`–`0xDFFF` | 256 bytes | SFR mapped to XDATA space |
| **XDATA RAM** | `0xF000`+ | Varies | RAM mapped to XDATA |
| **XDATA Flash Map** | `0x8000`–`0xFFFF` | 32 KB | Flash bank mapped to XDATA via MEMCTR |
| **Info Page** | Via debug config | 2 KB | Read-only configuration/info page |

### Flash Parameters

| Parameter | Value |
|-----------|-------|
| Flash size | 32 KB (CC1110F32) |
| Flash page size | **1 KB** (1024 bytes) |
| Flash word size | **2 bytes** |
| Number of pages | 32 |
| Flash base address (CODE) | `0x0000` |

### Key SFR Registers (Direct / XDATA addresses)

| Register | SFR Addr | XDATA Addr | Description |
|----------|----------|------------|-------------|
| **FLC / FCTL** | `0xAE` | `0xDFAE` | Flash controller status/control |
| **FADDRL** | `0xAC` | `0xDFAC` | Flash address low byte |
| **FADDRH** | `0xAD` | `0xDFAD` | Flash address high byte |
| **FWDATA** | `0xAF` | `0xDFAF` | Flash write data |
| **MEMCTR** | `0xC7` | `0xDFC7` | Memory mapping control |
| **CHIPID** | `0x37` | `0xDF37` | Chip identification |
| **CHVER** | `0x36` | `0xDF36` | Chip version/revision |
| **DMA0CFGH** | `0xD5` | `0xDFD5` | DMA channel 0 config high |
| **DMA0CFGL** | `0xD4` | `0xDFD4` | DMA channel 0 config low |
| **DMAARM** | `0xD6` | `0xDFD6` | DMA channel arm |
| **DMAREQ** | `0xD7` | `0xDFD7` | DMA channel trigger |
| **DMAIRQ** | `0xD1` | `0xDFD1` | DMA interrupt flags |
| **RNDL** | `0xBC` | `0xDFBC` | Random number low |
| **RNDH** | `0xBD` | `0xDFBD` | Random number high |
| **DBGDATA** | `0x62`* | `0x6260`* | Debug data register (*CC253x address, verify for CC1110) |

### Flash Control Register (FLC / FCTL) — SFR `0xAE`

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 7 | `0x80` | BUSY | 1 = flash write/erase in progress |
| 6 | `0x40` | FULL | 1 = flash write buffer full |
| 5 | `0x20` | ABORT | 1 = flash write aborted |
| 1 | `0x02` | WRITE | Set to 1 to start a flash write |
| 0 | `0x01` | ERASE | Set to 1 to start a page erase |

### MEMCTR Register — SFR `0xC7`

| Bits | Name | Description |
|------|------|-------------|
| 0 | XMAP | 1 = enable flash-to-XDATA mapping at `0x8000`–`0xFFFF` |
| 6:4 | XBANK | Flash bank number mapped to XDATA |

For CC1110F32 (32 KB, single bank): set MEMCTR = `0x01` to enable mapping (XBANK=0, XMAP=1).

---

## 9. Reading Flash Memory

There are two approaches. Both use DEBUG_INSTR to execute 8051 instructions on the halted CPU.

### Method A: MOVC from CODE Space (Simplest for ≤32 KB)

Read flash directly from CODE address space using `MOVC A, @A+DPTR`. Works for the full 32 KB without bank switching.

```c
// Read flash byte at address 'addr'
void read_flash_movc(uint16_t addr, uint8_t *buf, uint16_t len) {
    // 1. MOV DPTR, #addr           (opcode: 0x90, addrH, addrL)
    debug_instr3(0x90, (addr >> 8) & 0xFF, addr & 0xFF);

    for (uint16_t i = 0; i < len; i++) {
        // 2. CLR A                  (opcode: 0xE4)
        debug_instr1(0xE4);

        // 3. MOVC A, @A+DPTR       (opcode: 0x93) — reads CODE[A + DPTR]
        buf[i] = debug_instr1(0x93);

        // 4. INC DPTR              (opcode: 0xA3)
        debug_instr1(0xA3);
    }
}
```

### Method B: MOVX from XDATA-Mapped Flash (For Bank Switching)

Map flash bank to XDATA `0x8000`–`0xFFFF` via MEMCTR, then read with `MOVX A, @DPTR`.

```c
void read_flash_movx(uint8_t bank, uint16_t offset, uint8_t *buf, uint16_t len) {
    // 1. Set MEMCTR: enable XMAP, select bank
    //    MOV MEMCTR, #(bank*16 + 1)   (opcode: 0x75, 0xC7, value)
    debug_instr3(0x75, 0xC7, (bank << 4) | 0x01);

    // 2. MOV DPTR, #(0x8000 + offset)
    uint16_t xdata_addr = 0x8000 + offset;
    debug_instr3(0x90, (xdata_addr >> 8) & 0xFF, xdata_addr & 0xFF);

    for (uint16_t i = 0; i < len; i++) {
        // 3. MOVX A, @DPTR          (opcode: 0xE0)
        buf[i] = debug_instr1(0xE0);

        // 4. INC DPTR               (opcode: 0xA3)
        debug_instr1(0xA3);
    }
}
```

For CC1110F32 (32 KB, 1 bank): call `read_flash_movx(0, 0, buf, 32768)` to dump the entire flash.

### Helper Functions

```c
uint8_t debug_instr1(uint8_t op0) {
    debug_write_byte(0x55);     // DEBUG_INSTR_1
    debug_write_byte(op0);
    debug_switch_read(250);
    uint8_t result = debug_read_byte();
    debug_switch_write();
    return result;
}

uint8_t debug_instr2(uint8_t op0, uint8_t op1) {
    debug_write_byte(0x56);     // DEBUG_INSTR_2
    debug_write_byte(op0);
    debug_write_byte(op1);
    debug_switch_read(250);
    uint8_t result = debug_read_byte();
    debug_switch_write();
    return result;
}

uint8_t debug_instr3(uint8_t op0, uint8_t op1, uint8_t op2) {
    debug_write_byte(0x57);     // DEBUG_INSTR_3
    debug_write_byte(op0);
    debug_write_byte(op1);
    debug_write_byte(op2);
    debug_switch_read(250);
    uint8_t result = debug_read_byte();
    debug_switch_write();
    return result;
}
```

---

## 10. Reading/Writing XDATA Memory

XDATA is accessed via `MOVX` instructions through DEBUG_INSTR.

### Read XDATA

```c
uint8_t read_xdata(uint16_t addr) {
    // MOV DPTR, #addr
    debug_instr3(0x90, (addr >> 8) & 0xFF, addr & 0xFF);
    // MOVX A, @DPTR
    return debug_instr1(0xE0);
}
```

### Write XDATA

```c
void write_xdata(uint16_t addr, uint8_t value) {
    // MOV DPTR, #addr
    debug_instr3(0x90, (addr >> 8) & 0xFF, addr & 0xFF);
    // MOV A, #value
    debug_instr2(0x74, value);
    // MOVX @DPTR, A
    debug_instr1(0xF0);
}
```

### Read/Write SFR (via Direct Addressing)

SFR registers can be accessed by direct 8-bit address using MOV instructions:

```c
uint8_t read_sfr(uint8_t sfr_addr) {
    // MOV A, direct     (opcode: 0xE5, sfr_addr)
    return debug_instr2(0xE5, sfr_addr);
}

void write_sfr(uint8_t sfr_addr, uint8_t value) {
    // MOV direct, #data  (opcode: 0x75, sfr_addr, value)
    debug_instr3(0x75, sfr_addr, value);
}
```

---

## 11. DBGLOCK — Debug Lock Mechanism

### Detection

```c
uint8_t status = read_status();
bool locked = (status & 0x04) != 0;  // Bit 2 = DEBUG_LOCKED
```

If DEBUG_LOCKED is set:
- **Flash reads via DEBUG_INSTR will return garbage or zeros** — the chip blocks code-space reads
- **Flash writes are blocked**
- **CHIP_ERASE (`0x14`) still works** — this is the only way to unlock the chip
- After CHIP_ERASE completes, all flash is `0xFF` and the lock bit is cleared

### Lock Bit Location

The debug lock bit is stored in the **last flash page** (the "lock byte" area). For CC1110/CC2510:
- Lock data size: **1 byte**
- Located in the **info page** (accessible via SEL_FLASH_INFO_PAGE in debug config)
- Bit 7 of the lock byte = debug lock (0 = locked, 1 = unlocked)

To read the info page:
```c
// Set debug config to select info page
write_config(read_config() | 0x01);  // SEL_FLASH_INFO_PAGE

// Read info page (2 KB at XDATA 0x7800 for CC253x; for CC1110, verify address)
// ... read via XDATA or MOVC ...

// Restore normal config
write_config(read_config() & ~0x01);
```

### Erase Check for CC1110

For CC1110/CC2510, erase completion is detected **opposite** to CC253x:
- CC253x: erase done when `status & 0x80 == 0` (CHIP_ERASE_BUSY clears)
- CC1110/CC2510: erase done when `status & 0x80 != 0` (bit goes HIGH when done)

This is confirmed in cc-tool source (`cc_251x_111x::erase_check_completed` returns `status & DEBUG_STATUS_CHIP_ERASE_BUSY`, opposite of `cc_253x_254x`).

---

## 12. Flash Writing (via DMA)

Flash writing on CC1110 uses either DMA-based burst writes or a "slow" method that executes a flash-write routine on the CPU.

### Slow Method (Simpler, Used by cc-tool for CC1110)

Upload a small flash-write routine to XDATA RAM, set up FADDR/FLC, and execute it via DEBUG_INSTR/RESUME:

```
1. Upload data to write into XDATA RAM at 0xF000
2. Upload flash-write routine to XDATA RAM at 0xF000 + page_size
3. Set MEMCTR to enable code execution from XDATA bank
4. Set PC to start of routine
5. RESUME to execute the routine
6. Wait for completion (poll FLC.BUSY or debug status)
```

### CC1110 Flash Write Routine (8051 Assembly)

From CCLib cc2510.py `writeFlashPage`:

```
; Setup flash address
MOV FADDRH, #(address >> 8) / flashWordSize     ; 0x75, 0xAD, value
MOV FADDRL, #0x00                                ; 0x75, 0xAC, 0x00

; [Optional: erase page first]
MOV FLC, #0x01                                   ; 0x75, 0xAE, 0x01 (ERASE bit)
eraseWait: MOV A, FLC                            ; 0xE5, 0xAE
JB ACC.7, eraseWait                              ; 0x20, 0xE7, 0xFB (wait BUSY clear)

; Setup data pointer to RAM buffer
MOV DPTR, #0xF000                                ; 0x90, 0xF0, 0x00

; Outer loop (pages)
MOV R7, #(words_high)                            ; 0x7F, value
MOV R6, #(words_low)                             ; 0x7E, value
MOV FLC, #0x02                                   ; 0x75, 0xAE, 0x02 (WRITE bit)

; Inner loop (word size)
writeLoop:
  MOV R5, #flashWordSize                         ; 0x7D, 0x02
  writeWord:
    MOVX A, @DPTR                                ; 0xE0
    INC DPTR                                     ; 0xA3
    MOV FWDATA, A                                ; 0xF5, 0xAF
    DJNZ R5, writeWord                           ; 0xDD, 0xFA

  ; Wait for flash write to complete
  waitWrite:
    MOV A, FLC                                   ; 0xE5, 0xAE
    JB ACC.6, waitWrite                          ; 0x20, 0xE6, 0xFB (wait SWBSY clear)

  DJNZ R6, writeLoop                             ; 0xDE, 0xF1
  DJNZ R7, writeLoop                             ; 0xDF, 0xEF

DB 0xA5                                          ; Fake breakpoint to halt CPU
```

---

## 13. Timing Constraints

### DC Clock

| Parameter | Min | Typical | Max | Notes |
|-----------|-----|---------|-----|-------|
| DC period | ~200 ns | 2–10 µs | No max | Slower is safer for bit-bang |
| DC high time | 100 ns | 1 µs | — | |
| DC low time | 100 ns | 1 µs | — | |

### DD Setup/Hold

| Parameter | Min | Notes |
|-----------|-----|-------|
| DD setup before DC rising edge | ~50 ns | Data must be stable before clock rises |
| DD hold after DC rising edge | ~50 ns | Data must remain stable after clock rises |
| t_dir_change (after DD direction switch) | ~83 ns | Wait before checking DD state |
| t_sample_wait (after DD goes LOW) | ~50 ns | Wait before reading response |

### Practical Recommendations for ESP32-C3

| Setting | Value | Rationale |
|---------|-------|-----------|
| DC half-period | **2–5 µs** | Safe margin; ESP32-C3 GPIO toggle speed ~80 ns |
| Reset hold time | **10 ms** | Generous; ensures clean reset |
| Post-reset delay | **10 ms** | Wait for oscillator startup |
| switchRead timeout | **250 cycles** | 250 byte-clock cycles before giving up |
| Read retry on mismatch | **2–3 reads** | flash_cc2531 reads each 1K block twice and compares |

At 5 µs per bit (10 µs per DC cycle), one byte = 80 µs. A DEBUG_INSTR_1 round-trip ≈ 2 bytes TX + wait + 1 byte RX ≈ 300 µs. Reading 32 KB at one byte per DEBUG_INSTR_1 takes ~20 seconds (2 instructions per byte × 32768 bytes × 300 µs).

---

## 14. Complete Flash Dump Procedure

```c
// 1. Enter debug mode
enter_debug_mode();

// 2. Read and verify status
uint8_t status = read_status();   // Send 0x34, read 1 byte
if (status & 0x04) {
    // DEBUG_LOCKED — chip is locked
    // CHIP_ERASE (0x14) required to unlock (destroys flash!)
    return ERROR_LOCKED;
}
if (!(status & 0x20)) {
    // CPU not halted — something went wrong
    return ERROR_NOT_HALTED;
}

// 3. Read chip ID
uint16_t chip_id = get_chip_id();  // Send 0x68, read 2 bytes
// Verify chip_id matches expected CC1110 value

// 4. Configure debug mode
write_config(0x22);  // TIMER_SUSPEND | SOFT_POWER_MODE

// 5. Optionally enable XDATA flash mapping
debug_instr3(0x75, 0xC7, 0x01);  // MOV MEMCTR, #0x01

// 6. Read flash — 32 KB
uint8_t flash[32768];

// Method A: MOVC (simplest)
debug_instr3(0x90, 0x00, 0x00);  // MOV DPTR, #0x0000
for (int i = 0; i < 32768; i++) {
    debug_instr1(0xE4);           // CLR A
    flash[i] = debug_instr1(0x93); // MOVC A, @A+DPTR
    debug_instr1(0xA3);           // INC DPTR
}

// 7. Optionally read info page
write_config(read_config() | 0x01);  // Select info page
// ... read info page data ...
write_config(read_config() & ~0x01);  // Deselect

// 8. Resume and exit
resume();  // Send 0x4C
```

---

## 15. Common 8051 Instructions Used via DEBUG_INSTR

| Instruction | Bytes | Opcode(s) | Description |
|------------|-------|-----------|-------------|
| `NOP` | 1 | `0x00` | No operation |
| `CLR A` | 1 | `0xE4` | Clear accumulator |
| `INC DPTR` | 1 | `0xA3` | Increment data pointer |
| `MOVC A, @A+DPTR` | 1 | `0x93` | Read CODE memory at A+DPTR |
| `MOVX A, @DPTR` | 1 | `0xE0` | Read XDATA at DPTR |
| `MOVX @DPTR, A` | 1 | `0xF0` | Write XDATA at DPTR |
| `MOV A, #imm` | 2 | `0x74, imm` | Load immediate into A |
| `MOV A, direct` | 2 | `0xE5, addr` | Read SFR/direct address |
| `MOV direct, A` | 2 | `0xF5, addr` | Write A to SFR/direct |
| `MOV DPTR, #imm16` | 3 | `0x90, hi, lo` | Load 16-bit address into DPTR |
| `MOV direct, #imm` | 3 | `0x75, addr, val` | Write immediate to SFR/direct |

---

## 16. ESP32-C3 Implementation Notes

### GPIO Selection

Any 3 GPIOs work. Suggested allocation:
- DC: Any GPIO (output only)
- DD: GPIO with both input and output capability (all ESP32-C3 GPIOs support this)
- RESET_N: Any GPIO (output only, active-low)

### Timing Implementation

```c
// For ~2 µs delays on ESP32-C3
static inline void cc_delay_us(uint32_t us) {
    esp_rom_delay_us(us);  // ROM-based busy-wait, ~1 µs resolution
}
```

### DD Direction Switching

```c
void dd_set_output(void) {
    gpio_set_direction(PIN_DD, GPIO_MODE_OUTPUT);
}

void dd_set_input(void) {
    gpio_set_direction(PIN_DD, GPIO_MODE_INPUT);
    // Optionally enable internal pull-up:
    // gpio_set_pull_mode(PIN_DD, GPIO_PULLUP_ONLY);
}
```

### Verification Strategy

1. Read each 1 KB block **twice** and compare (as flash_cc2531 does)
2. If mismatch, re-read (up to 3 retries)
3. On persistent mismatch, increase clock period (slow down)
4. Output as Intel HEX format for compatibility with standard tools

---

## 17. Quick Reference Card

```
ENTER DEBUG:   RESET_N=LOW → 2× DC rising edges → RESET_N=HIGH

READ_STATUS:   TX[0x34] → wait → RX[status]
GET_CHIP_ID:   TX[0x68] → wait → RX[id, rev]
HALT:          TX[0x44] → wait → RX[status]
RESUME:        TX[0x4C] → wait → RX[status]
WR_CONFIG:     TX[0x1D, cfg] → wait → RX[status]
RD_CONFIG:     TX[0x24] → wait → RX[config]
CHIP_ERASE:    TX[0x14] → wait → RX[status] → poll until done
DEBUG_INSTR_1: TX[0x55, op0] → wait → RX[ACC]
DEBUG_INSTR_2: TX[0x56, op0, op1] → wait → RX[ACC]
DEBUG_INSTR_3: TX[0x57, op0, op1, op2] → wait → RX[ACC]
BURST_WRITE:   TX[0x80|lenH, lenL, data...] → wait → RX[status]

FLASH READ:    MOV DPTR,#addr → CLR A → MOVC A,@A+DPTR → INC DPTR → repeat
               0x90,hi,lo       0xE4     0x93               0xA3

XDATA READ:    MOV DPTR,#addr → MOVX A,@DPTR → INC DPTR
               0x90,hi,lo       0xE0            0xA3

XDATA WRITE:   MOV DPTR,#addr → MOV A,#val → MOVX @DPTR,A → INC DPTR
               0x90,hi,lo       0x74,val      0xF0            0xA3

SFR READ:      MOV A,direct     → 0xE5, sfr_addr → returns ACC
SFR WRITE:     MOV direct,#imm  → 0x75, sfr_addr, value

CC1110 FLASH REGS (SFR direct addr):
  FADDRL=0xAC  FADDRH=0xAD  FLC=0xAE  FWDATA=0xAF  MEMCTR=0xC7

STATUS BITS: [7]ERASE_BUSY [6]IDLE [5]CPU_HALTED [4]PM [3]HALT [2]LOCKED [1]OSC [0]STKOVF
```
