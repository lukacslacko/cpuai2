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

## ALU

Five GAL22V10 chips implement the 8-bit ALU with 8 operations, a barrel
shifter, and flag computation. The ALU reads from the A and B registers
and asserts its result on the data bus via ASSERT[1].

| OP | Code | Operation | Result |
|----|------|-----------|--------|
| 000 | A | Passthrough A | A |
| 001 | B | Passthrough B | B |
| 010 | ADD | Addition | A + B |
| 011 | SUB | Subtraction | A - B |
| 100 | AND | Bitwise AND | A & B |
| 101 | OR | Bitwise OR | A \| B |
| 110 | XOR | Bitwise XOR | A ^ B |
| 111 | SHIFT | Barrel shift | A shifted by B |

### Shift encoding

For the SHIFT operation, register B encodes the shift parameters:
- B[0..2]: shift amount (0-7)
- B[3]: direction (0 = right, 1 = left)
- Zero-fill (logical shift). Each output fits within 8 product terms.

### Flags

Three flags are computed combinationally and latched into a 74574 register
by pulsing FLAG_LATCH:
- **Z** (Zero): result is 0x00
- **N** (Negative): MSB of result is 1
- **C** (Carry): carry out of ADD/SUB (0 for other operations)

### Source files

The WinCUPL PLD source files are in the `gal/` directory:

#### Address offset

| File | Chip | Function | Inputs | Outputs |
|------|------|----------|--------|---------|
| `gal/offset_lo.pld` | GAL_ADDLO | Low nibble addition | L[0..3], ARG[0..3], CTRL[0..1] | ADDR[0..3], CARRY4 |
| `gal/offset_hi.pld` | GAL_ADDHI | High nibble addition | L[4..7], ARG[4..7], CTRL[0..1], CARRY4 | ADDR[4..7], CARRY8 |
| `gal/offset_h.pld` | GAL_INCH | High byte carry prop | H[0..7], CARRY8 | ADDR[8..15] |

#### ALU

| File | Chip | Function | Inputs | Outputs |
|------|------|----------|--------|---------|
| `gal/alu_lo.pld` | GAL_ALU_LO | Arith/logic low nibble | A[0..3], B[0..3], OP[0..2] | R[0..3], C4, ZLO |
| `gal/alu_hi.pld` | GAL_ALU_HI | Arith/logic high nibble | A[4..7], B[4..7], OP[0..2], C4 | R[4..7], C8, ZHI |
| `gal/shift_lo.pld` | GAL_SHIFT_LO | Barrel shift low nibble | A[0..7], AMT[0..2], DIR | S[0..3], SZLO |
| `gal/shift_hi.pld` | GAL_SHIFT_HI | Barrel shift high nibble | A[0..7], AMT[0..2], DIR | S[4..7], SZHI |
| `gal/alu_flags.pld` | GAL_ALU_FLAGS | OE + flags | OP[0..2], ASSERT1, C8, ZLO, ZHI, SZLO, SZHI, R7, S7 | ALU_OE, SH_OE, FZ, FN, FC |

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
   galasm gal/alu_lo.pld
   galasm gal/alu_hi.pld
   galasm gal/shift_lo.pld
   galasm gal/shift_hi.pld
   galasm gal/alu_flags.pld
   ```

3. **Program** the GAL22V10 chips using a universal programmer such as
   the TL866II+ with its minipro software:
   ```
   minipro -p GAL22V10 -w gal/offset_lo.jed
   minipro -p GAL22V10 -w gal/offset_hi.jed
   minipro -p GAL22V10 -w gal/offset_h.jed
   minipro -p GAL22V10 -w gal/alu_lo.jed
   minipro -p GAL22V10 -w gal/alu_hi.jed
   minipro -p GAL22V10 -w gal/shift_lo.jed
   minipro -p GAL22V10 -w gal/shift_hi.jed
   minipro -p GAL22V10 -w gal/alu_flags.jed
   ```
   Label each programmed chip to match its position in the circuit.

## Build Instructions

The file [`BUILD.md`](BUILD.md) contains the full component list and
wiring connections for the CPU, generated from the emulator's circuit
definition. To regenerate after any changes:

```
python gen_build.py
```
