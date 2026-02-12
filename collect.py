#!/usr/bin/env python3
"""collect.py — Serial collector for ESP32-C3 handshake capture rig.

Reads JSON lines from the ESP32 over USB serial and appends them to
captures.jsonl.  Run this instead of `idf.py monitor` to save data.

Usage:
    python collect.py COM5          # Windows — use your actual COM port
    python collect.py /dev/ttyACM0  # Linux
"""

import sys
import json
import serial

def main():
    if len(sys.argv) < 2:
        print("Usage: python collect.py <COM_PORT> [baud]")
        print("  e.g. python collect.py COM5")
        sys.exit(1)

    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    outfile = "captures.jsonl"

    ser = serial.Serial(port, baud, timeout=1)
    print(f"Listening on {port} — writing to {outfile}")
    print("Press Ctrl+C to stop\n")

    good = 0
    total = 0

    with open(outfile, "a", encoding="utf-8") as f:
        try:
            while True:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        print(f"  [bad json] {line[:80]}")
                        continue

                    f.write(line + "\n")
                    f.flush()
                    total += 1

                    ok = data.get("ok", False)
                    cy = data.get("cycle", "?")
                    edges = data.get("edges", 0)
                    msgs = data.get("msgs", 0)

                    if ok:
                        good += 1
                        c_n = len(data.get("challenge", []))
                        r_n = len(data.get("response", []))
                        print(f"  [{good:3d}/100] Cycle {cy}: OK  "
                              f"({edges} edges, {msgs} msgs, "
                              f"challenge={c_n} pairs, response={r_n} pairs)")
                    else:
                        print(f"  [  —  ] Cycle {cy}: MISS  "
                              f"({edges} edges, {msgs} msgs)")

                    if good >= 100:
                        print(f"\n=== 100 good captures collected! ===")
                        print(f"Total cycles: {total}, saved to {outfile}")
                        break
                else:
                    # ESP_LOGI / debug line
                    print(f"  {line}")

        except KeyboardInterrupt:
            print(f"\nStopped. {good} good captures in {total} cycles → {outfile}")

    ser.close()


if __name__ == "__main__":
    main()
