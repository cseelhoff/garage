#!/usr/bin/env python3
"""dump_collect.py — Capture CC1110 flash dump from ESP32-C3 over USB serial.

Reads Intel HEX records from the ESP32's USB serial output and saves
them to a .hex file.  Also saves a raw .bin file for easy analysis.

Usage:
    python dump_collect.py COM5                 # auto-names output
    python dump_collect.py COM5 firmware.hex    # explicit filename
    python dump_collect.py --test               # self-test (no hardware needed)
    python dump_collect.py --dry-run COM5       # capture Phase 0 test HEX only
"""

import sys
import time
import serial
from serial.tools import list_ports


def wait_for_port(port, timeout=30):
    """Wait for a COM port to appear (after ESP32 reset disconnects it)."""
    # Normalize port name for comparison
    port_upper = port.upper()
    deadline = time.time() + timeout
    while time.time() < deadline:
        available = [p.device.upper() for p in list_ports.comports()]
        if port_upper in available:
            time.sleep(0.3)  # give Windows a moment to finish setup
            return True
        time.sleep(0.5)
    return False


def open_serial(port):
    """Open serial port, retrying if the ESP32 just reset."""
    for attempt in range(5):
        try:
            ser = serial.Serial(port, 115200, timeout=2)
            return ser
        except serial.SerialException:
            if attempt < 4:
                time.sleep(1)
    raise serial.SerialException(f"Cannot open {port} after 5 attempts")


def ihex_to_bin(hex_lines):
    """Convert Intel HEX lines to a flat binary."""
    data = {}
    for line in hex_lines:
        line = line.strip()
        if not line.startswith(':') or len(line) < 11:
            continue
        byte_count = int(line[1:3], 16)
        address    = int(line[3:7], 16)
        rec_type   = int(line[7:9], 16)
        if rec_type == 0x00:  # data record
            for i in range(byte_count):
                b = int(line[9 + i*2 : 11 + i*2], 16)
                data[address + i] = b
        elif rec_type == 0x01:  # EOF
            break

    if not data:
        return b''
    min_addr = min(data.keys())
    max_addr = max(data.keys())
    buf = bytearray(max_addr - min_addr + 1)
    for addr, val in data.items():
        buf[addr - min_addr] = val
    return bytes(buf)


def self_test():
    """Generate and parse test Intel HEX data (no hardware needed)."""
    print("=== dump_collect.py self-test ===\n")

    # Generate test HEX: 64 bytes (0x00..0x3F) mimicking Phase 0g output
    print("1. Generating test Intel HEX (64 bytes, 0x00-0x3F)...")
    test_lines = []
    for row in range(4):
        addr = row * 16
        data_bytes = list(range(row * 16, row * 16 + 16))
        data_hex = ''.join(f'{b:02X}' for b in data_bytes)
        cksum = (16 + (addr >> 8) + (addr & 0xFF) + 0x00 +
                 sum(data_bytes)) & 0xFF
        cksum = (~cksum + 1) & 0xFF
        line = f":10{addr:04X}00{data_hex}{cksum:02X}"
        test_lines.append(line)
        print(f"   {line}")
    test_lines.append(":00000001FF")
    print(f"   :00000001FF  (EOF)")

    # Parse
    print("\n2. Parsing with ihex_to_bin()...")
    bin_data = ihex_to_bin(test_lines)
    print(f"   Parsed {len(bin_data)} bytes")

    # Verify
    print("\n3. Verifying content...")
    expected = bytes(range(64))
    if bin_data == expected:
        print("   PASS: All 64 bytes match expected values (0x00..0x3F)")
    else:
        print("   FAIL: Content mismatch!")
        for i in range(min(len(bin_data), len(expected))):
            if bin_data[i] != expected[i]:
                print(f"   First diff at offset {i}: got 0x{bin_data[i]:02X}, "
                      f"expected 0x{expected[i]:02X}")
                break
        return False

    # Verify hex dump display
    print("\n4. Hex dump output:")
    for i in range(0, min(64, len(bin_data)), 16):
        hex_str = ' '.join(f'{b:02X}' for b in bin_data[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in bin_data[i:i+16])
        print(f"   {i:04X}: {hex_str}  {ascii_str}")

    # Test checksum verification
    print("\n5. Verifying checksums...")
    all_ok = True
    for line in test_lines:
        if not line.startswith(':') or len(line) < 11:
            continue
        byte_count = int(line[1:3], 16)
        raw = bytes(int(line[i:i+2], 16) for i in range(1, len(line), 2))
        if sum(raw) & 0xFF != 0:
            print(f"   FAIL: Bad checksum in {line}")
            all_ok = False
    if all_ok:
        print("   PASS: All checksums valid")

    print("\n=== Self-test PASSED ===")
    print("The HEX parser is working correctly.")
    print("Ready to capture real data from the ESP32.")
    return True


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--test':
        ok = self_test()
        sys.exit(0 if ok else 1)

    dry_run = False
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    if '--dry-run' in sys.argv:
        dry_run = True

    if len(args) < 1:
        print("Usage: python dump_collect.py <COM_PORT> [output.hex]")
        print("       python dump_collect.py --test")
        print("       python dump_collect.py --dry-run <COM_PORT>")
        sys.exit(1)

    port = args[0]
    if dry_run:
        hex_file = "dry_run_test.hex"
    else:
        hex_file = args[1] if len(args) > 1 else "cc1110_flash.hex"
    bin_file = hex_file.replace('.hex', '.bin')

    ser = open_serial(port)

    if dry_run:
        print(f"=== DRY RUN MODE ===")
        print(f"Listening on {port} for Phase 0 test HEX data only.")
        print(f"This captures the test records from the ESP32's Phase 0g.")
    else:
        print(f"Listening on {port} for Intel HEX data...")

    print(f"Output: {hex_file} + {bin_file}")
    print("Press Ctrl+C to abort")
    print("(Resilient to ESP32 resets — will reconnect automatically)\n")

    hex_lines = []
    got_eof = False

    try:
        while True:
            try:
                raw = ser.readline()
            except (serial.SerialException, OSError):
                print(f"\n  *** Serial disconnected (ESP32 reset?) ***")
                try:
                    ser.close()
                except Exception:
                    pass
                print(f"  Waiting for {port} to reappear...")
                if not wait_for_port(port):
                    print(f"  {port} did not come back within 30s. Giving up.")
                    break
                print(f"  {port} is back. Reconnecting...")
                ser = open_serial(port)
                print(f"  Reconnected! Listening...\n")
                continue

            if not raw:
                continue
            line = raw.decode('utf-8', errors='replace').strip()
            if not line:
                continue

            if line.startswith(':'):
                hex_lines.append(line)
                # Show progress for data records
                if len(line) > 9:
                    addr = int(line[3:7], 16)
                    rec_type = int(line[7:9], 16)
                    if rec_type == 0x00 and addr % 1024 == 0:
                        print(f"  0x{addr:04X} ({addr // 1024} KB / 32 KB)")
                    elif rec_type == 0x01:
                        got_eof = True
                        print(f"\n  EOF record received!")
                        break
            else:
                # Debug/log line from ESP32
                print(f"  {line}")

    except KeyboardInterrupt:
        print(f"\nInterrupted — saving {len(hex_lines)} records collected so far")

    try:
        ser.close()
    except Exception:
        pass

    if not hex_lines:
        print("No HEX data received. Check wiring and retry.")
        sys.exit(1)

    # Save .hex
    with open(hex_file, 'w') as f:
        for hl in hex_lines:
            f.write(hl + '\n')
    print(f"Saved {len(hex_lines)} HEX records → {hex_file}")

    # Save .bin
    bin_data = ihex_to_bin(hex_lines)
    with open(bin_file, 'wb') as f:
        f.write(bin_data)
    print(f"Saved {len(bin_data)} bytes → {bin_file}")

    if got_eof and len(bin_data) == 32768:
        print(f"\nFull 32 KB dump captured successfully!")
    elif got_eof:
        print(f"\nDump complete ({len(bin_data)} bytes — expected 32768)")
    else:
        print(f"\nPartial dump ({len(bin_data)} bytes — may be incomplete)")

    # Quick analysis
    if len(bin_data) >= 16:
        print(f"\nFirst 32 bytes:")
        for i in range(0, min(32, len(bin_data)), 16):
            hex_str = ' '.join(f'{b:02X}' for b in bin_data[i:i+16])
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in bin_data[i:i+16])
            print(f"  {i:04X}: {hex_str}  {ascii_str}")

        # Check if flash is all 0xFF (erased/empty)
        ff_count = bin_data.count(0xFF)
        if ff_count == len(bin_data):
            print("\n  WARNING: Flash is all 0xFF — chip may be erased or read failed")
        elif ff_count > len(bin_data) * 0.9:
            print(f"\n  NOTE: {ff_count}/{len(bin_data)} bytes are 0xFF ({ff_count*100//len(bin_data)}%)")
        else:
            print(f"\n  Flash contains {len(bin_data) - ff_count} non-0xFF bytes (looks good!)")


if __name__ == "__main__":
    main()
