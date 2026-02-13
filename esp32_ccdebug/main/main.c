/*
 * CC1110 Flash Dumper — ESP32-C3 Bit-Bang Firmware
 *
 * Dumps the 32KB flash from a Texas Instruments CC1110F32 using
 * the TI 2-wire debug protocol, bit-banged from ESP32-C3 GPIOs.
 *
 * IMPORTANT: Uses CC1110-specific opcodes (instruction table v2),
 * NOT the CC253x/CC254x opcodes found in most online references.
 *
 * Wiring:
 *   ESP32 GPIO2  → CC1110 Pin 15 (P2.2 / Debug Clock)
 *   ESP32 GPIO3  → CC1110 Pin 16 (P2.1 / Debug Data)
 *   ESP32 GPIO4  → CC1110 Pin 31 (RESET_N)
 *   ESP32 3V3    → CC1110 VDD (pin 26 or board 3.3V pad)
 *   ESP32 GND    → CC1110 GND
 *
 * Protocol (per datasheet §11.2):
 *   Data is DRIVEN at the positive (rising) edge of Debug Clock.
 *   Data is SAMPLED at the negative (falling) edge of Debug Clock.
 *   Commands/data are MSB-first.
 *   DD is bidirectional — host releases it before reading.
 *
 * Boot sequence:
 *   Phase 1 — Connectivity test (non-destructive sanity checks)
 *   Phase 2 — Enter debug mode + identify chip
 *   Phase 3 — Check debug lock + halt CPU
 *   Phase 4 — Read 32 KB flash → Intel HEX over USB serial
 *   Phase 5 — Release chip
 *
 * Output: Intel HEX records over USB serial at 115200 baud.
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "rom/ets_sys.h"          /* ets_delay_us() */

static const char *TAG = "ccdebug";

/* ── Pin assignments ───────────────────────────────────────────── */
#define PIN_DC    GPIO_NUM_2      /* Debug Clock  → CC1110 P2.2 (pin 15) */
#define PIN_DD    GPIO_NUM_3      /* Debug Data   → CC1110 P2.1 (pin 16) */
#define PIN_RST   GPIO_NUM_4      /* RESET_N      → CC1110 pin 31 */

/* ── Timing (microseconds) ─────────────────────────────────────── */
#define T_CLK     10              /* half-clock period (≥ spec's ~1µs) */

/* ── CC1110 debug opcodes (instruction table v2!) ──────────────── */
#define CMD_READ_STATUS     0x34
#define CMD_GET_CHIP_ID     0x68
#define CMD_HALT            0x44
#define CMD_RESUME          0x4C
#define CMD_DEBUG_INSTR_1   0x55  /* execute 1-byte 8051 instruction */
#define CMD_DEBUG_INSTR_2   0x56  /* execute 2-byte instruction      */
#define CMD_DEBUG_INSTR_3   0x57  /* execute 3-byte instruction      */
#define CMD_WR_CONFIG       0x1D
#define CMD_RD_CONFIG       0x24
#define CMD_GET_PC          0x28
#define CMD_CHIP_ERASE      0x14  /* DO NOT USE unless intentional   */

/* ── Read-status response bits ─────────────────────────────────── */
#define STATUS_CHIP_ERASE_DONE  0x80
#define STATUS_PCON_IDLE        0x40
#define STATUS_CPU_HALTED       0x20
#define STATUS_PM_ACTIVE        0x10
#define STATUS_HALT_STATUS      0x08
#define STATUS_DEBUG_LOCKED     0x04
#define STATUS_OSCILLATOR_STABLE 0x02
#define STATUS_STACK_OVERFLOW    0x01

/* ── CC1110 SFR / register addresses ──────────────────────────── */
#define SFR_MEMCTR  0xC7          /* memory control */
#define SFR_FCTL    0xAE          /* flash control  */

/* ── Flash geometry ────────────────────────────────────────────── */
#define FLASH_SIZE   (32 * 1024)  /* 32 KB */
#define FLASH_BASE   0x0000
#define BLOCK_SIZE   64           /* bytes per read iteration */

/* ── Low-level bit-bang ────────────────────────────────────────── */

static inline void dc_high(void) { gpio_set_level(PIN_DC, 1); }
static inline void dc_low(void)  { gpio_set_level(PIN_DC, 0); }
static inline void dd_high(void) { gpio_set_level(PIN_DD, 1); }
static inline void dd_low(void)  { gpio_set_level(PIN_DD, 0); }
static inline int  dd_read(void) { return gpio_get_level(PIN_DD); }
static inline void wait(void)    { ets_delay_us(T_CLK); }

static void dd_output(void)
{
    gpio_set_direction(PIN_DD, GPIO_MODE_OUTPUT);
}

static void dd_input(void)
{
    gpio_set_direction(PIN_DD, GPIO_MODE_INPUT);
}

/*
 * Clock out one bit (MSB-first).
 * Host drives DD, then raises DC (data "driven" at rising edge).
 * CC1110 samples DD on the falling edge of DC.
 */
static void write_bit(int b)
{
    dc_low();
    if (b) dd_high(); else dd_low();
    wait();
    dc_high();      /* rising edge — data presented */
    wait();
    dc_low();       /* falling edge — CC1110 latches */
    wait();
}

/*
 * Clock in one bit.
 * CC1110 drives DD at the rising edge of DC.
 * Host samples DD, then lowers DC (falling edge).
 */
static int read_bit(void)
{
    dc_high();      /* rising edge — CC1110 drives DD */
    wait();
    int b = dd_read();
    dc_low();       /* falling edge */
    wait();
    return b;
}

/* Write a byte MSB-first */
static void write_byte(uint8_t v)
{
    dd_output();
    for (int i = 7; i >= 0; i--)
        write_bit((v >> i) & 1);
}

/* Read a byte MSB-first */
static uint8_t read_byte(void)
{
    dd_input();
    ets_delay_us(2);  /* turnaround time for CC1110 to drive DD */
    uint8_t v = 0;
    for (int i = 7; i >= 0; i--)
        v |= (read_bit() << i);
    return v;
}

/* ── Debug protocol commands ───────────────────────────────────── */

/* Enter debug mode: hold RESET low, pulse DC twice, release RESET */
static void enter_debug(void)
{
    gpio_set_level(PIN_RST, 1);
    ets_delay_us(100);

    gpio_set_level(PIN_RST, 0);     /* assert reset */
    ets_delay_us(10);

    /* Two rising edges on DC while RESET is low */
    dc_low();  wait();  dc_high();  wait();
    dc_low();  wait();  dc_high();  wait();
    dc_low();  /* leave DC low — idle state */

    ets_delay_us(10);
    gpio_set_level(PIN_RST, 1);     /* release reset */
    ets_delay_us(100);
}

static uint8_t read_status(void)
{
    write_byte(CMD_READ_STATUS);
    return read_byte();
}

static uint16_t get_chip_id(void)
{
    write_byte(CMD_GET_CHIP_ID);
    uint8_t hi = read_byte();
    uint8_t lo = read_byte();
    return ((uint16_t)hi << 8) | lo;
}

static uint16_t get_pc(void)
{
    write_byte(CMD_GET_PC);
    uint8_t hi = read_byte();
    uint8_t lo = read_byte();
    return ((uint16_t)hi << 8) | lo;
}

static uint8_t halt_cpu(void)
{
    write_byte(CMD_HALT);
    return read_byte();
}

static uint8_t resume_cpu(void)
{
    write_byte(CMD_RESUME);
    return read_byte();
}

static void wr_config(uint8_t cfg)
{
    write_byte(CMD_WR_CONFIG);
    write_byte(cfg);
    read_byte();  /* ACK */
}

static uint8_t rd_config(void)
{
    write_byte(CMD_RD_CONFIG);
    return read_byte();
}

/* Execute a 1-byte 8051 instruction, return accumulator */
static uint8_t debug_instr_1(uint8_t b0)
{
    write_byte(CMD_DEBUG_INSTR_1);
    write_byte(b0);
    return read_byte();
}

/* Execute a 2-byte 8051 instruction, return accumulator */
static uint8_t debug_instr_2(uint8_t b0, uint8_t b1)
{
    write_byte(CMD_DEBUG_INSTR_2);
    write_byte(b0);
    write_byte(b1);
    return read_byte();
}

/* Execute a 3-byte 8051 instruction, return accumulator */
static uint8_t debug_instr_3(uint8_t b0, uint8_t b1, uint8_t b2)
{
    write_byte(CMD_DEBUG_INSTR_3);
    write_byte(b0);
    write_byte(b1);
    write_byte(b2);
    return read_byte();
}

/* ── 8051 instruction helpers ──────────────────────────────────── */

/* MOV DPTR, #imm16  →  0x90  hi  lo */
static void set_dptr(uint16_t addr)
{
    debug_instr_3(0x90, (uint8_t)(addr >> 8), (uint8_t)(addr & 0xFF));
}

/* CLR A  →  0xE4 */
static void clr_a(void)
{
    debug_instr_1(0xE4);
}

/* MOV A, #imm  →  0x74  imm */
static void mov_a_imm(uint8_t v)
{
    debug_instr_2(0x74, v);
}

/* MOVC A, @A+DPTR  →  0x93   (reads code memory at A+DPTR) */
static uint8_t movc_a_dptr(void)
{
    return debug_instr_1(0x93);
}

/* INC DPTR  →  0xA3 */
static void inc_dptr(void)
{
    debug_instr_1(0xA3);
}

/* MOV direct, #imm  →  0x75  addr  imm */
static void mov_sfr(uint8_t sfr_addr, uint8_t val)
{
    debug_instr_3(0x75, sfr_addr, val);
}

/* ── Flash reading ─────────────────────────────────────────────── */

static uint8_t read_flash_byte(uint16_t addr)
{
    set_dptr(addr);
    clr_a();
    return movc_a_dptr();
}

/*
 * Read a block of flash via MOVC A,@A+DPTR.
 * Sets DPTR once, then reads sequential bytes using A=0 + INC DPTR.
 */
static void read_flash_block(uint16_t addr, uint8_t *buf, int len)
{
    set_dptr(addr);
    for (int i = 0; i < len; i++) {
        clr_a();
        buf[i] = movc_a_dptr();
        if (i < len - 1)
            inc_dptr();
    }
}

/* ── Intel HEX output ──────────────────────────────────────────── */

static void emit_hex_record(uint8_t type, uint16_t addr,
                            const uint8_t *data, int len)
{
    uint8_t cksum = (uint8_t)len + (uint8_t)(addr >> 8) +
                    (uint8_t)(addr & 0xFF) + type;
    printf(":%02X%04X%02X", len, addr, type);
    for (int i = 0; i < len; i++) {
        printf("%02X", data[i]);
        cksum += data[i];
    }
    printf("%02X\n", (uint8_t)(~cksum + 1));
}

static void emit_hex_eof(void)
{
    printf(":00000001FF\n");
}

/* ── GPIO init ─────────────────────────────────────────────────── */

static void hw_init(void)
{
    gpio_config_t dc_cfg = {
        .pin_bit_mask = (1ULL << PIN_DC),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&dc_cfg);
    gpio_set_level(PIN_DC, 0);

    gpio_config_t dd_cfg = {
        .pin_bit_mask = (1ULL << PIN_DD),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,   /* CC1110 has its own pull-up */
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&dd_cfg);
    gpio_set_level(PIN_DD, 1);

    gpio_config_t rst_cfg = {
        .pin_bit_mask = (1ULL << PIN_RST),
        .mode         = GPIO_MODE_OUTPUT_OD,     /* open-drain for RESET_N */
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&rst_cfg);
    gpio_set_level(PIN_RST, 1);
}

/* ── Status printer ────────────────────────────────────────────── */

static void print_status(const char *label, uint8_t s)
{
    ESP_LOGI(TAG, "%s: 0x%02X  [ %s%s%s%s%s%s%s%s]",
             label, s,
             (s & STATUS_CHIP_ERASE_DONE)   ? "ERASE_DONE "  : "",
             (s & STATUS_PCON_IDLE)          ? "IDLE "        : "",
             (s & STATUS_CPU_HALTED)         ? "HALTED "      : "",
             (s & STATUS_PM_ACTIVE)          ? "PM0 "         : "",
             (s & STATUS_HALT_STATUS)        ? "BKPT "        : "",
             (s & STATUS_DEBUG_LOCKED)       ? "LOCKED "      : "UNLOCKED ",
             (s & STATUS_OSCILLATOR_STABLE)  ? "OSC_STABLE "  : "OSC_UNSTABLE ",
             (s & STATUS_STACK_OVERFLOW)     ? "STKOVERFLOW "  : "");
}

/* ── Phase helpers ─────────────────────────────────────────────── */

static void phase_hdr(int n, const char *name)
{
    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  PHASE %d: %s", n, name);
    ESP_LOGI(TAG, "========================================");
}

static void stop_with_error(const char *msg)
{
    ESP_LOGE(TAG, "*** STOPPED: %s ***", msg);
    ESP_LOGE(TAG, "Remove power, check wiring, and retry.");
    while (1) vTaskDelay(pdMS_TO_TICKS(10000));
}

/* ── Main ──────────────────────────────────────────────────────── */

void app_main(void)
{
    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "╔══════════════════════════════════════╗");
    ESP_LOGI(TAG, "║   CC1110 Flash Dumper v2.0           ║");
    ESP_LOGI(TAG, "║   DC=GPIO%d  DD=GPIO%d  RST=GPIO%d    ║",
             PIN_DC, PIN_DD, PIN_RST);
    ESP_LOGI(TAG, "╚══════════════════════════════════════╝");
    ESP_LOGI(TAG, "");

    hw_init();

    /* Let USB-CDC enumerate */
    ESP_LOGI(TAG, "Waiting 3s for USB serial to enumerate...");
    vTaskDelay(pdMS_TO_TICKS(3000));

    /* ════════════════════════════════════════════════════════════ */
    phase_hdr(0, "PIN IDENTIFICATION (LA1010 channel mapping)");
    /* ════════════════════════════════════════════════════════════ */

    ESP_LOGI(TAG, "Each pin will blink SLOWLY one at a time so you can");
    ESP_LOGI(TAG, "identify which LA1010 channel is connected to which signal.");
    ESP_LOGI(TAG, "Watch your LA1010 — only ONE channel should toggle at a time.");
    ESP_LOGI(TAG, "");

    /* All lines idle first */
    dc_low();
    dd_output();
    dd_high();
    gpio_set_level(PIN_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(500));

    /* 0a: Blink RESET_N (GPIO10 → pin 31) — 3 slow pulses */
    ESP_LOGI(TAG, "[0a] Blinking RESET_N (GPIO%d) — 3 slow pulses...", PIN_RST);
    ESP_LOGI(TAG, "      → LA1010: only CH2 should toggle");
    for (int i = 0; i < 3; i++) {
        gpio_set_level(PIN_RST, 0);
        vTaskDelay(pdMS_TO_TICKS(200));
        gpio_set_level(PIN_RST, 1);
        vTaskDelay(pdMS_TO_TICKS(200));
    }
    vTaskDelay(pdMS_TO_TICKS(500));

    /* 0b: Blink DC (GPIO2 → pin 15) — 3 slow pulses */
    ESP_LOGI(TAG, "[0b] Blinking DC (GPIO%d) — 3 slow pulses...", PIN_DC);
    ESP_LOGI(TAG, "      → LA1010: only CH0 should toggle");
    for (int i = 0; i < 3; i++) {
        dc_high();
        vTaskDelay(pdMS_TO_TICKS(200));
        dc_low();
        vTaskDelay(pdMS_TO_TICKS(200));
    }
    vTaskDelay(pdMS_TO_TICKS(500));

    /* 0c: Blink DD (GPIO3 → pin 16) — 3 slow pulses */
    ESP_LOGI(TAG, "[0c] Blinking DD (GPIO%d) — 3 slow pulses...", PIN_DD);
    ESP_LOGI(TAG, "      → LA1010: only CH1 should toggle");
    dd_output();
    for (int i = 0; i < 3; i++) {
        dd_low();
        vTaskDelay(pdMS_TO_TICKS(200));
        dd_high();
        vTaskDelay(pdMS_TO_TICKS(200));
    }
    vTaskDelay(pdMS_TO_TICKS(500));

    /* 0d: All three together — 3 pulses */
    ESP_LOGI(TAG, "[0d] Blinking ALL THREE pins together — 3 pulses...");
    ESP_LOGI(TAG, "      → LA1010: CH0 + CH1 + CH2 should all toggle in sync");
    for (int i = 0; i < 3; i++) {
        gpio_set_level(PIN_RST, 0);
        dc_high();
        dd_low();
        vTaskDelay(pdMS_TO_TICKS(200));
        gpio_set_level(PIN_RST, 1);
        dc_low();
        dd_high();
        vTaskDelay(pdMS_TO_TICKS(200));
    }

    /* 0e/0f: REMOVED — simulated debug entry + GET_CHIP_ID were entering
     *        the real CC1110 into debug mode and leaving the bus out of sync.
     *        Channel mapping is verified by the blink phases above. */
    ESP_LOGI(TAG, "[0e] Skipped (simulated debug entry removed to avoid bus corruption)");
    ESP_LOGI(TAG, "[0f] Skipped (simulated GET_CHIP_ID removed)");

    /* 0g: Connectivity note (HEX emission removed — it caused dump_collect.py
     *     to stop at the Phase 0g EOF before the real Phase 4 dump). */
    ESP_LOGI(TAG, "[0g] Serial connectivity assumed OK (HEX test removed).");
    ESP_LOGI(TAG, "      Use 'python dump_collect.py --test' to validate the parser.");

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "Phase 0 DONE. Review your LA1010 capture and serial output.");
    ESP_LOGI(TAG, "If everything looks correct, the system is ready.");
    ESP_LOGI(TAG, "Proceeding to real phases in 3 seconds...");
    vTaskDelay(pdMS_TO_TICKS(3000));

    /* ════════════════════════════════════════════════════════════ */
    phase_hdr(1, "CONNECTIVITY TEST (safe — no DC while RST low)");
    /* ════════════════════════════════════════════════════════════ */

    ESP_LOGI(TAG, "Checking wiring without entering debug mode.");
    ESP_LOGI(TAG, "");

    /* Test 1a: DD idle level (CC1110 drives P2.1 during normal operation) */
    ESP_LOGI(TAG, "[1a] Reading DD idle level (GPIO%d)...", PIN_DD);
    dd_input();
    ets_delay_us(50);
    int dd_idle = dd_read();
    ESP_LOGI(TAG, "      DD idle level = %d", dd_idle);

    /* Test 1b: Pulse RESET_N to verify it's connected (no DC toggling!) */
    ESP_LOGI(TAG, "[1b] Pulsing RESET_N LOW for 10ms (no DC pulses)...");
    gpio_set_level(PIN_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(PIN_RST, 1);
    ESP_LOGI(TAG, "      RESET_N pulse done. LA1010 CH2 should show one dip.");

    /* Let the CC1110 boot fully after the reset pulse */
    ESP_LOGI(TAG, "[1c] Waiting 1s for CC1110 to boot after reset...");
    vTaskDelay(pdMS_TO_TICKS(1000));

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "Phase 1 DONE. Proceeding to debug entry...");
    vTaskDelay(pdMS_TO_TICKS(1000));

    /* ════════════════════════════════════════════════════════════ */
    phase_hdr(2, "ENTER DEBUG MODE");
    /* ════════════════════════════════════════════════════════════ */

    /*
     * CRITICAL SECTION — no ESP_LOGI between these operations!
     * Timing-sensitive debug entry per CC1110 datasheet §11.3:
     *   1. Assert RESET_N LOW (hold ≥ 1ms for clean reset)
     *   2. Two rising edges on DC while RESET_N is LOW
     *   3. Release RESET_N after a brief hold
     *   4. Wait for chip to settle (≥ 2ms for XOSC startup)
     */
    ESP_LOGI(TAG, "[2a-c] Entering debug mode (RST LOW → 2 DC edges → RST HIGH)...");

    /* Ensure lines are idle before starting */
    dc_low();
    dd_output();
    dd_high();
    ets_delay_us(100);

    /* Step 1: Assert RESET_N LOW for a solid reset */
    gpio_set_level(PIN_RST, 0);
    ets_delay_us(2000);   /* 2ms — generous hold time */

    /* Step 2: Exactly two rising edges on DC while RESET_N is LOW */
    dc_low();  ets_delay_us(T_CLK);
    dc_high(); ets_delay_us(T_CLK);  /* rising edge 1 */
    dc_low();  ets_delay_us(T_CLK);
    dc_high(); ets_delay_us(T_CLK);  /* rising edge 2 */
    dc_low();  /* leave DC low — idle state */
    ets_delay_us(100);

    /* Step 3: Release RESET_N */
    gpio_set_level(PIN_RST, 1);

    /* Step 4: Wait for CC1110 to settle (XOSC startup + debug init) */
    ets_delay_us(10000);  /* 10ms — very generous */

    ESP_LOGI(TAG, "      Debug entry sequence complete.");
    ESP_LOGI(TAG, "      RST held LOW for 2ms, 2 DC edges, then 10ms settle.");

    /* Verify by reading chip ID — retry up to 3 times with fresh debug entry */
    ESP_LOGI(TAG, "[2d] Sending GET_CHIP_ID command (0x%02X)...", CMD_GET_CHIP_ID);
    uint16_t chip_id = 0xFFFF;
    for (int attempt = 0; attempt < 3; attempt++) {
        if (attempt > 0) {
            ESP_LOGW(TAG, "      Retry %d: re-entering debug mode...", attempt + 1);
            /* Full fresh debug entry */
            dc_low(); dd_output(); dd_high();
            gpio_set_level(PIN_RST, 0);
            ets_delay_us(5000);
            dc_low();  ets_delay_us(T_CLK);
            dc_high(); ets_delay_us(T_CLK);
            dc_low();  ets_delay_us(T_CLK);
            dc_high(); ets_delay_us(T_CLK);
            dc_low();  ets_delay_us(100);
            gpio_set_level(PIN_RST, 1);
            ets_delay_us(10000);
        }
        chip_id = get_chip_id();
        ESP_LOGI(TAG, "      Attempt %d: Chip ID = 0x%04X", attempt + 1, chip_id);
        if (chip_id != 0x0000 && chip_id != 0xFFFF)
            break;
        /* Also try READ_STATUS to see if we get anything besides 0xFF */
        uint8_t probe_status = read_status();
        ESP_LOGI(TAG, "      Attempt %d: READ_STATUS = 0x%02X", attempt + 1, probe_status);
    }
    ESP_LOGI(TAG, "      Chip ID = 0x%04X  (high byte=0x%02X, rev=0x%02X)",
             chip_id, (uint8_t)(chip_id >> 8), (uint8_t)(chip_id & 0xFF));

    uint8_t family = (uint8_t)(chip_id >> 8);
    if (chip_id == 0x0000 || chip_id == 0xFFFF) {
        ESP_LOGE(TAG, "      Chip ID is 0x%04X — no response from CC1110!", chip_id);
        ESP_LOGE(TAG, "      LIKELY CAUSES:");
        ESP_LOGE(TAG, "        - DC and DD wires swapped (pin 15 vs pin 16)");
        ESP_LOGE(TAG, "        - RESET_N not connected properly");
        ESP_LOGE(TAG, "        - CC1110 not powered (check 3.3V)");
        ESP_LOGE(TAG, "        - Bad solder joint on debug pins");
        stop_with_error("No response to GET_CHIP_ID");
    }

    if (family == 0x89) {
        ESP_LOGI(TAG, "      ✓ CONFIRMED: CC1110 family (0x89)");
    } else if (family == 0x81 || family == 0x91 || family == 0x85 ||
               family == 0x95 || family == 0xA5 || family == 0xB5) {
        ESP_LOGW(TAG, "      Chip is TI CC11xx family but not CC1110 (0x%02X)", family);
        ESP_LOGW(TAG, "      Proceeding anyway — flash size may differ.");
    } else {
        ESP_LOGW(TAG, "      Unexpected chip family 0x%02X — not a known CC11xx", family);
        ESP_LOGW(TAG, "      Proceeding cautiously...");
    }

    /* Read status */
    ESP_LOGI(TAG, "[2e] Sending READ_STATUS command (0x%02X)...", CMD_READ_STATUS);
    uint8_t status = read_status();
    print_status("      Status", status);

    /* Double-check: read status a second time for consistency */
    uint8_t status2 = read_status();
    if (status2 != status) {
        ESP_LOGW(TAG, "      Second READ_STATUS = 0x%02X (differs from first 0x%02X)",
                 status2, status);
        ESP_LOGW(TAG, "      Bus may be noisy. Check solder joints.");
    } else {
        ESP_LOGI(TAG, "      Second READ_STATUS = 0x%02X (consistent ✓)", status2);
    }

    /* Read config register */
    ESP_LOGI(TAG, "[2f] Reading debug config (RD_CONFIG 0x%02X)...", CMD_RD_CONFIG);
    uint8_t config = rd_config();
    ESP_LOGI(TAG, "      Config = 0x%02X  [TIMERS_OFF=%d DMA_PAUSE=%d "
             "TIMER_SUSPEND=%d SEL_INFO_PAGE=%d]",
             config,
             (config >> 3) & 1, (config >> 2) & 1,
             (config >> 1) & 1, config & 1);

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "Phase 2 DONE. Debug mode is active.");
    vTaskDelay(pdMS_TO_TICKS(500));

    /* ════════════════════════════════════════════════════════════ */
    phase_hdr(3, "CHECK LOCK + HALT CPU");
    /* ════════════════════════════════════════════════════════════ */

    /* Check debug lock */
    ESP_LOGI(TAG, "[3a] Checking debug lock bit (STATUS bit 2)...");
    if (status & STATUS_DEBUG_LOCKED) {
        ESP_LOGE(TAG, "      ╔═══════════════════════════════════════╗");
        ESP_LOGE(TAG, "      ║  FLASH IS DEBUG-LOCKED (DBGLOCK=0)   ║");
        ESP_LOGE(TAG, "      ╚═══════════════════════════════════════╝");
        ESP_LOGE(TAG, "      Cannot read flash. The lock bit is set in the");
        ESP_LOGE(TAG, "      Flash Information Page at address 0x000.");
        ESP_LOGE(TAG, "      Only CHIP_ERASE can clear it (destroys ALL data).");
        ESP_LOGE(TAG, "      → Fall back to Plan B (100-capture rig).");
        stop_with_error("Debug interface is locked");
    }
    ESP_LOGI(TAG, "      ✓ Debug lock is OFF — flash is readable!");

    /* Check oscillator stable */
    ESP_LOGI(TAG, "[3b] Checking oscillator stability (STATUS bit 1)...");
    if (!(status & STATUS_OSCILLATOR_STABLE)) {
        ESP_LOGW(TAG, "      Oscillator not stable yet. Waiting...");
        for (int i = 0; i < 50; i++) {
            ets_delay_us(1000);
            status = read_status();
            if (status & STATUS_OSCILLATOR_STABLE) break;
        }
        if (!(status & STATUS_OSCILLATOR_STABLE)) {
            ESP_LOGE(TAG, "      Oscillator still not stable after 50ms!");
            stop_with_error("Oscillator not stable — debug commands unreliable");
        }
    }
    ESP_LOGI(TAG, "      ✓ Oscillator stable.");

    /* Halt CPU */
    ESP_LOGI(TAG, "[3c] Sending HALT command (0x%02X)...", CMD_HALT);
    uint8_t halt_ack = halt_cpu();
    ESP_LOGI(TAG, "      HALT ACK = 0x%02X", halt_ack);

    ESP_LOGI(TAG, "[3d] Verifying CPU is halted (READ_STATUS)...");
    ets_delay_us(100);
    status = read_status();
    print_status("      Status after HALT", status);

    if (!(status & STATUS_CPU_HALTED)) {
        ESP_LOGE(TAG, "      CPU did not halt! Status = 0x%02X", status);
        stop_with_error("CPU failed to halt");
    }
    ESP_LOGI(TAG, "      ✓ CPU is halted.");

    /* Read program counter for diagnostics */
    ESP_LOGI(TAG, "[3e] Reading program counter (GET_PC)...");
    uint16_t pc = get_pc();
    ESP_LOGI(TAG, "      PC = 0x%04X", pc);

    /* Probe: read the first byte of flash to verify the read path */
    ESP_LOGI(TAG, "[3f] Probe read: flash byte at 0x0000...");
    uint8_t probe = read_flash_byte(0x0000);
    ESP_LOGI(TAG, "      flash[0x0000] = 0x%02X", probe);

    ESP_LOGI(TAG, "[3g] Probe read: flash byte at 0x0001...");
    uint8_t probe1 = read_flash_byte(0x0001);
    ESP_LOGI(TAG, "      flash[0x0001] = 0x%02X", probe1);

    ESP_LOGI(TAG, "[3h] Probe read: flash byte at 0x0002...");
    uint8_t probe2 = read_flash_byte(0x0002);
    ESP_LOGI(TAG, "      flash[0x0002] = 0x%02X", probe2);

    if (probe == 0x00 && probe1 == 0x00 && probe2 == 0x00) {
        ESP_LOGW(TAG, "      First 3 bytes are all 0x00 — unusual but possible.");
        ESP_LOGW(TAG, "      (8051 reset vector at 0x0000 is typically LJMP = 0x02)");
    } else if (probe == 0xFF && probe1 == 0xFF && probe2 == 0xFF) {
        ESP_LOGW(TAG, "      First 3 bytes are all 0xFF — flash may be erased or read failed.");
        ESP_LOGW(TAG, "      Check if DD (pin 16) is connected properly.");
    } else if (probe == 0x02) {
        ESP_LOGI(TAG, "      ✓ Byte 0 is 0x02 (LJMP) — looks like valid 8051 firmware!");
        ESP_LOGI(TAG, "        (LJMP target = 0x%02X%02X)", probe1, probe2);
    } else {
        ESP_LOGI(TAG, "      First bytes: %02X %02X %02X", probe, probe1, probe2);
    }

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "Phase 3 DONE. Ready to dump flash.");
    vTaskDelay(pdMS_TO_TICKS(500));

    /* ════════════════════════════════════════════════════════════ */
    phase_hdr(4, "READING FLASH (32 KB)");
    /* ════════════════════════════════════════════════════════════ */

    ESP_LOGI(TAG, "Dumping %d bytes (%d KB) as Intel HEX over USB serial...",
             FLASH_SIZE, FLASH_SIZE / 1024);
    ESP_LOGI(TAG, "Block size = %d bytes. Total blocks = %d.",
             BLOCK_SIZE, FLASH_SIZE / BLOCK_SIZE);
    ESP_LOGI(TAG, "HEX records start with ':' — other lines are log messages.");
    ESP_LOGI(TAG, "");

    /* Emit Intel HEX header comments */
    printf("; CC1110F32 flash dump — %d bytes\n", FLASH_SIZE);
    printf("; Chip ID: 0x%04X  Status: 0x%02X\n", chip_id, status);
    printf("; Probe: flash[0]=0x%02X flash[1]=0x%02X flash[2]=0x%02X\n",
           probe, probe1, probe2);
    fflush(stdout);

    uint8_t block[BLOCK_SIZE];
    int pct_last = -1;
    int64_t t_start = esp_timer_get_time();

    for (uint32_t addr = 0; addr < FLASH_SIZE; addr += BLOCK_SIZE) {
        int len = BLOCK_SIZE;
        if (addr + len > FLASH_SIZE)
            len = FLASH_SIZE - addr;

        read_flash_block((uint16_t)addr, block, len);

        /* Emit as 16-byte HEX records */
        for (int off = 0; off < len; off += 16) {
            int rec_len = (len - off > 16) ? 16 : (len - off);
            emit_hex_record(0x00, (uint16_t)(addr + off),
                            &block[off], rec_len);
        }
        fflush(stdout);

        int pct = (int)((addr + len) * 100 / FLASH_SIZE);
        if (pct != pct_last) {
            int64_t elapsed = esp_timer_get_time() - t_start;
            int secs = (int)(elapsed / 1000000);
            ESP_LOGI(TAG, "Progress: %3d%%  (%5lu / %d bytes)  [%d:%02d elapsed]",
                     pct,
                     (unsigned long)(addr + len), FLASH_SIZE,
                     secs / 60, secs % 60);
            pct_last = pct;
        }
    }

    emit_hex_eof();
    fflush(stdout);

    int64_t t_total = esp_timer_get_time() - t_start;
    int total_secs = (int)(t_total / 1000000);

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "Phase 4 DONE. All %d bytes read in %d:%02d.",
             FLASH_SIZE, total_secs / 60, total_secs % 60);
    vTaskDelay(pdMS_TO_TICKS(500));

    /* ════════════════════════════════════════════════════════════ */
    phase_hdr(5, "RELEASE CHIP");
    /* ════════════════════════════════════════════════════════════ */

    ESP_LOGI(TAG, "[5a] Resetting CC1110 (RESET_N LOW → HIGH)...");
    gpio_set_level(PIN_RST, 0);
    ets_delay_us(1000);
    gpio_set_level(PIN_RST, 1);
    ESP_LOGI(TAG, "      CC1110 released. It will boot normally now.");

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "╔══════════════════════════════════════╗");
    ESP_LOGI(TAG, "║        FLASH DUMP COMPLETE!          ║");
    ESP_LOGI(TAG, "║  Total: %5d bytes in %d:%02d          ║",
             FLASH_SIZE, total_secs / 60, total_secs % 60);
    ESP_LOGI(TAG, "╚══════════════════════════════════════╝");
    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "On PC: python dump_collect.py COMx");
    ESP_LOGI(TAG, "Output: cc1110_flash.hex + cc1110_flash.bin");

    while (1) vTaskDelay(pdMS_TO_TICKS(10000));
}
