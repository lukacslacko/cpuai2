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

## Microcode

Each instruction executes as a sequence of microcode steps. A 40193
counter provides a 4-bit microPC (up to 16 steps per instruction). Two
28256 EEPROMs store the 16-bit microcode word, addressed by:

```
A[0..3]   = microPC   (4 bits, current step)
A[4..11]  = I register (8 bits, current instruction opcode)
A[12..14] = flags Z, N, C (3 bits, enabling conditional branching)
```

### Microcode word format

```
Bit  Field         Width  Purpose
0-2  ASSERT        3      Select data bus driver
3-5  LATCH         3      Select data bus receiver
6-8  ALU_OP        3      ALU operation select
9-10 OFFSET        2      Address offset mode
11-12 CONTROL      2      Counter action (0=nop, 1=PC++, 2=SP--, 3=SP++)
13   END           1      Reset microPC to 0 (end of instruction)
14   FLAGS_LATCH   1      Pulse flag register latch
15   (unused)      1
```

### ASSERT demux (active-low outputs drive buffer OE pins)

| Code | Source | Description |
|------|--------|-------------|
| 0 | TMP | Temporary register |
| 1 | ALU | ALU/shifter result |
| 2 | MEM | RAM or ROM at address H:L+offset |
| 3 | PCH | Program counter high byte |
| 4 | PCL | Program counter low byte |
| 5 | SPH | Stack pointer high byte |
| 6 | SPL | Stack pointer low byte |
| 7 | ARG | Argument register |

### LATCH demux (active-low outputs drive register CLK or WE pins)

| Code | Target | Description |
|------|--------|-------------|
| 0 | I+ARG | Instruction register (from bus) and ARG (from old I) |
| 1 | A+B | A register (from bus) and B (from old A) |
| 2 | H | Address high byte |
| 3 | L | Address low byte |
| 4 | PCH | Program counter high byte (parallel load) |
| 5 | PCL | Program counter low byte (parallel load) |
| 6 | MEM WE | RAM write enable |
| 7 | TMP | Temporary register |

## Execution phases

The `tick()` method executes one microcode step. The timing is split
into distinct phases to match the physical behaviour of the hardware,
where edge-triggered latches must capture data while it is still being
driven onto the bus.

### Phase 0: Settle and decode

The circuit is settled so that the microcode ROM outputs reflect the
current address (microPC + I + flags). The 16-bit microcode word is
then read from the ROM data buses and decoded into its fields: ASSERT,
LATCH, ALU_OP, OFFSET, CONTROL, END, and FLAGS_LATCH. The decoded
values are applied to the select lines of the ASSERT demux, LATCH
demux, and ALU operation inputs.

### Phase 1: CLK HIGH — enable demuxes and drive data

CLK, ASSERT_EN, and LATCH_EN are all driven HIGH. The circuit settles:

- The **ASSERT demux** activates its selected output (driving it LOW),
  which enables the corresponding tri-state buffer. The selected
  component (ALU, memory, register, etc.) drives its value onto the
  8-bit data bus.
- The **LATCH demux** activates its selected output (driving it LOW).
  For 74574 edge-triggered registers this is the CLK pin being held
  LOW — no latch occurs yet (the 74574 triggers on a rising edge).
  For the RAM write-enable (LATCH=6) the active-low WE is asserted.
- The **CONTROL demux** (gated by CLK) activates its selected output.
  If CONTROL=1, PC_COUNT_UP is driven LOW. If CONTROL=2 or 3,
  SP_COUNT_DOWN or SP_COUNT_UP is driven LOW. The 40193 counters
  trigger on a rising edge, so nothing happens yet.
- The **ALU** computes its result combinationally from A, B, and
  ALU_OP. The output buffers (controlled by the ASSERT demux via
  GAL_ALU_FLAGS) drive the result onto the data bus if ASSERT=1.
  The flag signals (Z, N, C) are valid on the GAL outputs.

### Phase 1b: FLAGS_LATCH pulse (conditional)

If the FLAGS_LATCH bit is set, the flag register's CLK is pulsed
HIGH then LOW while ALU inputs A and B still hold their original
values. This captures the correct flags for the current operation
before the register latch in Phase 2a potentially changes A.

### Phase 2a: Disable LATCH — trigger register capture

LATCH_EN is driven LOW while ASSERT_EN remains HIGH. The LATCH demux
becomes disabled, forcing all its outputs HIGH. The selected output
transitions LOW→HIGH, which is a **rising edge** on the target
register's CLK pin. The 74574 captures whatever is on its data inputs
at this moment. Because ASSERT is still active, the source component
is still driving valid data onto the bus, guaranteeing the register
latches the correct value.

For LATCH=1 (A+B), both A and B share the same CLK line. A latches
from the data bus, and B simultaneously latches from A's outputs
(capturing A's old value before it updates).

### Phase 2b: Disable ASSERT and CLK — release bus, trigger counters

ASSERT_EN and CLK are both driven LOW. The ASSERT demux becomes
disabled (all outputs HIGH), so all tri-state buffers release the data
bus (it returns to floating). The CONTROL demux (gated by CLK as G1)
also becomes disabled, forcing its outputs HIGH. If a counter's clock
input was being held LOW (e.g., PC_COUNT_UP during CONTROL=1), it now
transitions LOW→HIGH — a **rising edge** that increments or decrements
the counter.

### Phase 3: Advance microPC

If the END bit is set, the microPC is reset to 0 by pulsing
MICRO_MR (master reset), preparing for the next instruction's fetch
cycle. Otherwise, MICRO_CLK is pulsed LOW then HIGH (rising edge on
the 40193 count-up input) to advance the microPC to the next step.

### Timing diagram

```
                 Phase 0  |  Phase 1   | 1b (opt) | Phase 2a | Phase 2b | Phase 3
                          |            |          |          |          |
CLK          _____________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\__________
ASSERT_EN    _____________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\____
LATCH_EN     _____________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\____________________
                          |            |          |          |          |
LATCH_Yn     ‾‾‾‾‾‾‾‾‾‾‾‾‾\__________↓__________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
                          |            |    ↑ rising edge    |          |
                          |            | captures data      |          |
ASSERT_Yn    ‾‾‾‾‾‾‾‾‾‾‾‾‾\____________________________________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
                          |  data valid on bus ───────────────|→        |
FLAGS_LATCH  _________________________/‾‾‾‾‾\___________________________________
                          |            |  ↑ captures flags   |          |
CTRL_Yn      ‾‾‾‾‾‾‾‾‾‾‾‾‾\_____________________________________/‾‾‾‾‾‾‾‾‾‾‾‾‾
                          |            |          |          | ↑ rising edge
                          |            |          |          | triggers counter
```

## Microcode EEPROMs

The microcode is stored in two 28256 EEPROMs (32KB each). To generate
the binary files for programming:

```
python gen_microcode.py
```

This produces `microcode_lo.bin` (bits 0-7) and `microcode_hi.bin`
(bits 8-15). Program them with a universal programmer:

```
minipro -p 28256 -w microcode_lo.bin
minipro -p 28256 -w microcode_hi.bin
```

Label the chips UCODE_LO and UCODE_HI to match the circuit.

## Build Instructions

The file [`BUILD.md`](BUILD.md) contains the full component list and
wiring connections for the CPU, generated from the emulator's circuit
definition. To regenerate after any changes:

```
python gen_build.py
```
