#!/usr/bin/env python3
"""Generate microcode EEPROM binary files.

Produces two 32KB .bin files suitable for programming 28256 EEPROMs:
  - microcode_lo.bin  (UCODE_LO: bits 0-7 of each microcode word)
  - microcode_hi.bin  (UCODE_HI: bits 8-15 of each microcode word)

Usage:
    python gen_microcode.py
"""

from microcode import generate_microcode


def main():
    lo, hi = generate_microcode()

    with open("microcode_lo.bin", "wb") as f:
        f.write(lo)
    with open("microcode_hi.bin", "wb") as f:
        f.write(hi)

    print(f"microcode_lo.bin  ({len(lo)} bytes)")
    print(f"microcode_hi.bin  ({len(hi)} bytes)")


if __name__ == "__main__":
    main()
