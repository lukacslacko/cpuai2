# cpuai2

Breadboard CPU emulator built from discrete logic IC components.

## GAL22V10 Programming

Three GAL22V10 chips implement the address offset logic, which computes
`addr = H:L + offset` where offset is controlled by OFFSET_CTRL:

| CTRL | Mode | Address output |
|------|------|---------------|
| 00 | Passthrough | H:L |
| 01 | Add ARG | H:L + ARG |
| 10 | Add ARG+1 | H:L + ARG + 1 |
| 11 | (unused) | H:L |

### Source files

The WinCUPL PLD source files are in the `gal/` directory:

| File | Chip | Function | Inputs | Outputs |
|------|------|----------|--------|---------|
| `gal/offset_lo.pld` | GAL_ADDLO | Low nibble addition | L[0..3], ARG[0..3], CTRL[0..1] | ADDR[0..3], CARRY4 |
| `gal/offset_hi.pld` | GAL_ADDHI | High nibble addition | L[4..7], ARG[4..7], CTRL[0..1], CARRY4 | ADDR[4..7], CARRY8 |
| `gal/offset_h.pld` | GAL_INCH | High byte carry prop | H[0..7], CARRY8 | ADDR[8..15] |

### How to compile and program

1. **Install WinCUPL** (free from Microchip, runs on Windows) or use
   [galasm](https://github.com/daveho/GALasm) (open source, cross-platform).

2. **Compile** each `.pld` file to produce a JEDEC `.jed` file:
   ```
   # Using WinCUPL (GUI): open the .pld file and click Compile
   # Using galasm (command line):
   galasm gal/offset_lo.pld
   galasm gal/offset_hi.pld
   galasm gal/offset_h.pld
   ```

3. **Program** the GAL22V10 chips using a universal programmer such as
   the TL866II+ with its minipro software:
   ```
   minipro -p GAL22V10 -w gal/offset_lo.jed
   minipro -p GAL22V10 -w gal/offset_hi.jed
   minipro -p GAL22V10 -w gal/offset_h.jed
   ```
   Label each programmed chip to match its position in the circuit.

## Build Instructions

The file [`BUILD.md`](BUILD.md) contains the full component list and
wiring connections for the CPU, generated from the emulator's circuit
definition. To regenerate after any changes:

```
python gen_build.py
```
