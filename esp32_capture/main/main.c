/*
 * Garage Handshake Capture Rig — ESP32-C3 Firmware
 *
 * Automates boot-cycle captures to collect challenge-response pairs
 * from an Overhead Door Odyssey 1000 (Model 7030) receiver.
 *
 * Hardware:
 *   GPIO4  = CH0 (Z3, receiver→opener) input tap
 *   GPIO5  = CH1 (Z4, opener→receiver) input tap
 *   GPIO6  = 2N7002 MOSFET gate (controls receiver GND path)
 *
 * Each cycle: power off 500ms → power on → capture 12s → parse → JSON output
 * Stops automatically after 100 good challenge-response pairs.
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_log.h"

/* ── Pin assignments (change if wired differently) ─────────────── */
#define PIN_CH0       GPIO_NUM_4    /* Z3: receiver → opener */
#define PIN_CH1       GPIO_NUM_5    /* Z4: opener → receiver */
#define PIN_MOSFET    GPIO_NUM_6    /* 2N7002 gate            */

/* ── Protocol constants ────────────────────────────────────────── */
#define PWM_UNIT_US   26            /* ~26 µs base time unit  */
#define GAP_US        10000         /* 10 ms = message boundary */

/* ── Timing ────────────────────────────────────────────────────── */
#define CAPTURE_MS    12000         /* 12 s capture window    */
#define POWER_OFF_MS  500           /* 500 ms receiver off    */
#define SETTLE_MS     2000          /* 2 s between cycles     */
#define TARGET_GOOD   100           /* stop after this many   */

/* ── Buffers ───────────────────────────────────────────────────── */
#define RING_SIZE     4096
#define MAX_PAIRS     128
#define MAX_MSGS      48

static const char *TAG = "capture";

/* ── Edge event (written by ISR) ───────────────────────────────── */
typedef struct {
    uint32_t ts;        /* esp_timer_get_time() truncated to 32 bits */
    uint8_t  ch;        /* 0 or 1 */
    uint8_t  level;     /* gpio level after edge */
} edge_t;

static edge_t    s_ring[RING_SIZE];
static volatile uint32_t s_head;
static volatile bool     s_run;

/* ── Parsed message ────────────────────────────────────────────── */
typedef struct {
    uint8_t  ch;
    uint16_t n;            /* number of (L,H) pairs */
    uint8_t  L[MAX_PAIRS]; /* LOW durations in symbol units  */
    uint8_t  H[MAX_PAIRS]; /* HIGH durations in symbol units */
} msg_t;

static msg_t s_msgs[MAX_MSGS];
static int   s_nmsg;

/* ── ISR ───────────────────────────────────────────────────────── */
static void IRAM_ATTR edge_isr(void *arg)
{
    if (!s_run) return;
    uint32_t h = s_head;
    if (h >= RING_SIZE) return;

    uint32_t ch = (uint32_t)arg;
    gpio_num_t pin = (ch == 0) ? PIN_CH0 : PIN_CH1;

    s_ring[h].ts    = (uint32_t)esp_timer_get_time();
    s_ring[h].ch    = (uint8_t)ch;
    s_ring[h].level = (uint8_t)gpio_get_level(pin);
    s_head = h + 1;
}

/* ── GPIO setup ────────────────────────────────────────────────── */
static void hw_init(void)
{
    /* Input pins: internal pull-up, interrupt on any edge */
    gpio_config_t in = {
        .pin_bit_mask = (1ULL << PIN_CH0) | (1ULL << PIN_CH1),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_ANYEDGE,
    };
    gpio_config(&in);

    /* MOSFET gate output */
    gpio_config_t out = {
        .pin_bit_mask = (1ULL << PIN_MOSFET),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&out);
    gpio_set_level(PIN_MOSFET, 1);   /* receiver ON at start */

    gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
    gpio_isr_handler_add(PIN_CH0, edge_isr, (void *)0);
    gpio_isr_handler_add(PIN_CH1, edge_isr, (void *)1);
}

/* ── Microseconds → symbol unit (rounded) ──────────────────────── */
static inline uint8_t sym(uint32_t us)
{
    uint8_t s = (uint8_t)((us + PWM_UNIT_US / 2) / PWM_UNIT_US);
    return s < 1 ? 1 : s;
}

/* ── Save a finished message ───────────────────────────────────── */
static void save(int ch, uint8_t *L, uint8_t *H, int n)
{
    if (n < 2 || s_nmsg >= MAX_MSGS) return;
    msg_t *m = &s_msgs[s_nmsg++];
    m->ch = (uint8_t)ch;
    m->n  = (uint16_t)n;
    memcpy(m->L, L, n);
    memcpy(m->H, H, n);
}

/* ── Process ring buffer → messages ────────────────────────────── */
static void process(void)
{
    s_nmsg = 0;
    uint32_t cnt = s_head;

    /* Per-channel edge-walking state */
    struct {
        uint32_t lo_t;          /* timestamp of last falling edge  */
        uint32_t hi_t;          /* timestamp of last rising edge   */
        bool     in_lo;
        bool     in_hi;
        int      idx;
        uint8_t  L[MAX_PAIRS];
        uint8_t  H[MAX_PAIRS];
    } st[2];
    memset(st, 0, sizeof(st));

    for (uint32_t i = 0; i < cnt; i++) {
        int      c  = s_ring[i].ch;
        uint32_t ts = s_ring[i].ts;
        int      lv = s_ring[i].level;

        if (lv == 0) {                              /* ── falling edge ── */
            if (st[c].in_hi) {
                uint32_t dur = ts - st[c].hi_t;
                if (dur > GAP_US) {
                    save(c, st[c].L, st[c].H, st[c].idx);
                    st[c].idx = 0;
                } else if (st[c].idx > 0) {
                    st[c].H[st[c].idx - 1] = sym(dur);
                }
                st[c].in_hi = false;
            }
            st[c].lo_t  = ts;
            st[c].in_lo = true;

        } else {                                    /* ── rising edge ── */
            if (st[c].in_lo && st[c].idx < MAX_PAIRS) {
                st[c].L[st[c].idx] = sym(ts - st[c].lo_t);
                st[c].H[st[c].idx] = 0;
                st[c].idx++;
                st[c].in_lo = false;
            }
            st[c].hi_t  = ts;
            st[c].in_hi = true;
        }
    }

    /* Flush anything left over */
    for (int c = 0; c < 2; c++)
        if (st[c].idx > 0)
            save(c, st[c].L, st[c].H, st[c].idx);
}

/* ── Header match (L-values only, same as analyze.py) ──────────── */
static bool hdr_match(const msg_t *m, const uint8_t *hdr, int len)
{
    if (m->n < len) return false;
    for (int i = 0; i < len; i++)
        if (m->L[i] != hdr[i]) return false;
    return true;
}

/* ── Print (L,H) pairs as JSON array ───────────────────────────── */
static void json_pairs(const msg_t *m)
{
    putchar('[');
    for (int i = 0; i < m->n; i++) {
        if (i) putchar(',');
        printf("[%u,%u]", m->L[i], m->H[i]);
    }
    putchar(']');
}

/* ── Headers for handshake messages (L-values) ─────────────────── */
static const uint8_t HDR_CMD_B_INIT[] = {1,7,3,4,1,4,1,9};  /* 8 syms */
static const uint8_t HDR_HANDSHAKE_E[] = {1,7,4,4,2,3,1,9};  /* 8 syms */

/* CMD-B-INIT short form has ≤22 pairs; long form (challenge) has >22 */
#define CMD_B_INIT_LONG_THRESH  22

/* ── Find handshake pair and emit JSON ─────────────────────────── */
static bool emit_json(int cycle)
{
    const msg_t *challenge = NULL;
    const msg_t *response  = NULL;

    for (int i = 0; i < s_nmsg; i++) {
        msg_t *m = &s_msgs[i];

        /* CMD-B-INIT long form on CH0 (take last match — it's the challenge) */
        if (m->ch == 0 && m->n > CMD_B_INIT_LONG_THRESH &&
            hdr_match(m, HDR_CMD_B_INIT, sizeof(HDR_CMD_B_INIT)))
            challenge = m;

        /* HANDSHAKE-E on CH1 */
        if (m->ch == 1 &&
            hdr_match(m, HDR_HANDSHAKE_E, sizeof(HDR_HANDSHAKE_E)))
            response = m;
    }

    bool ok = (challenge != NULL) && (response != NULL);

    printf("{\"cycle\":%d,\"edges\":%lu,\"msgs\":%d",
           cycle, (unsigned long)s_head, s_nmsg);
    if (challenge) { printf(",\"challenge\":"); json_pairs(challenge); }
    if (response)  { printf(",\"response\":");  json_pairs(response);  }
    printf(",\"ok\":%s}\n", ok ? "true" : "false");
    fflush(stdout);

    return ok;
}

/* ── Main ──────────────────────────────────────────────────────── */
void app_main(void)
{
    ESP_LOGI(TAG, "Handshake capture rig — CH0=GPIO%d CH1=GPIO%d FET=GPIO%d",
             PIN_CH0, PIN_CH1, PIN_MOSFET);

    hw_init();

    /* Give USB-CDC time to enumerate so the host sees early output */
    vTaskDelay(pdMS_TO_TICKS(3000));

    ESP_LOGI(TAG, "Starting capture loop (target: %d good pairs)", TARGET_GOOD);

    int cycle = 0, good = 0;

    while (good < TARGET_GOOD) {
        cycle++;
        ESP_LOGI(TAG, "--- Cycle %d  (good so far: %d/%d) ---",
                 cycle, good, TARGET_GOOD);

        /* 1) Power off receiver */
        gpio_set_level(PIN_MOSFET, 0);
        vTaskDelay(pdMS_TO_TICKS(POWER_OFF_MS));

        /* 2) Reset ring buffer and start capturing edges */
        s_head = 0;
        s_run  = true;
        gpio_set_level(PIN_MOSFET, 1);

        /* 3) Wait for boot handshake to complete */
        vTaskDelay(pdMS_TO_TICKS(CAPTURE_MS));
        s_run = false;

        ESP_LOGI(TAG, "Captured %lu edges", (unsigned long)s_head);

        /* 4) Process edges → messages, find handshake, output JSON */
        process();
        if (emit_json(cycle))
            good++;

        /* 5) Settle before next cycle */
        vTaskDelay(pdMS_TO_TICKS(SETTLE_MS));
    }

    ESP_LOGI(TAG, "=== Done! %d good pairs in %d cycles ===", good, cycle);
    gpio_set_level(PIN_MOSFET, 1);          /* leave receiver on */

    while (1) vTaskDelay(pdMS_TO_TICKS(10000));
}
