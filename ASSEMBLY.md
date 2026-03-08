# Assembly Language Reference

This document describes the cpuai2 instruction set and assembler.

## Syntax

```
[COND.]MNEMONIC[.F] [argument]
```

- **COND** — optional condition prefix (default: AL = always)
- **MNEMONIC** — instruction name
- **.F** — flags-only suffix (ALU instructions only, suppresses stack push)
- **argument** — 8-bit immediate value (0-255)

Comments start with `;` and extend to end of line. Blank lines are
ignored. Mnemonics and condition codes are case-insensitive.

### Number formats

| Format | Example | Value |
|--------|---------|-------|
| Decimal | `42` | 42 |
| Hexadecimal | `0x2A` | 42 |
| Binary | `0b101010` | 42 |

## Registers

| Register | Width | Description |
|----------|-------|-------------|
| A | 8-bit | Primary accumulator, first ALU operand |
| B | 8-bit | Secondary register, second ALU operand |
| PC | 16-bit | Program counter (starts at 0x8000) |
| SP | 16-bit | Stack pointer (starts at 0x0100, grows downward) |

When a value is loaded into A (via `LDA`, `LDASP`, or ALU push), the
old value of A is simultaneously moved into B.

## Memory map

| Address range | Size | Device |
|---------------|------|--------|
| 0x0000-0x7FFF | 32 KB | RAM (62256 SRAM) |
| 0x8000-0xFFFF | 32 KB | ROM (28256 EEPROM) |

The stack occupies RAM starting at address 0x0100 and grows downward.
Programs are stored in ROM starting at 0x8000.

## Condition codes

Any instruction can be made conditional by prefixing a condition code.
The condition is checked before execution; if false, the instruction
is skipped.

| Code | Meaning | Executes when |
|------|---------|---------------|
| AL | Always | (unconditional, default) |
| NV | Never | (never executes) |
| CS | Carry set | C = 1 |
| CC | Carry clear | C = 0 |
| ZS | Zero set | Z = 1 |
| ZC | Zero clear | Z = 0 |
| NS | Negative set | N = 1 |
| NC | Negative clear | N = 0 |

Example: `ZS.LDA 0xFF` loads 0xFF into A only if the zero flag is set.

## Flags

Three status flags are computed from ALU results:

| Flag | Set when |
|------|----------|
| Z (Zero) | Result equals 0x00 |
| N (Negative) | Result bit 7 is 1 |
| C (Carry) | ADD carry out, or SUB no-borrow; 0 for logic/shift |

Flags are latched when an ALU instruction executes (both regular and
`.F` variants). Non-ALU instructions do not change flags.

## ALU instructions

ALU instructions operate on registers A and B. By default, the result
is pushed: A receives the ALU result, B receives the old A, and the
result is written to `MEM[SP]` with SP decremented. Append `.F` to
compute and set flags without pushing.

| Mnemonic | Operation | Result |
|----------|-----------|--------|
| A | Passthrough | A |
| B | Passthrough | B |
| ADD | Addition | A + B |
| SUB | Subtraction | A - B |
| AND | Bitwise AND | A & B |
| OR | Bitwise OR | A \| B |
| XOR | Bitwise XOR | A ^ B |
| SHIFT | Barrel shift | A shifted by B |

ALU instructions take no argument. All ALU instructions set Z, N, and
C flags.

### Push behavior (without .F)

1. A latches the ALU result
2. B latches the old value of A
3. The ALU result is written to `MEM[SP]`
4. SP is decremented

### Flags-only behavior (with .F)

The ALU computes the result and flags are latched, but A, B, SP, and
memory are unchanged.

### Shift encoding

When using `SHIFT`, register B encodes the shift parameters:

- B\[0..2\]: shift amount (0-7 bits)
- B\[3\]: direction (0 = right, 1 = left)
- Logical (zero-fill) shift in both directions

To shift A left by 3: load B with `0b00001011` (0x0B) — direction=1,
amount=3.

## Non-ALU instructions

### LDA — Load immediate into A

```
LDA <imm>
```

Loads the 8-bit immediate value into A. The old value of A is moved
into B. Does not affect flags.

### PUSH — Push immediate to stack

```
PUSH <imm>
```

Writes the immediate value to `MEM[SP]`, then decrements SP. Does not
affect flags.

### BR — Branch within page

```
BR <offset>
```

Sets the low byte of PC to the given offset. The high byte of PC is
unchanged, so the branch target must be in the same 256-byte page.
Does not affect flags.

### JMP — Jump to address in B:A

```
JMP
```

Sets PC to the 16-bit address formed by B (high byte) and A (low
byte). Takes no argument. Does not affect flags.

### CALL — Call subroutine

```
CALL
```

Pushes the current PC (return address) onto the stack (high byte
first, then low byte), then jumps to the address in B:A. Takes no
argument. Does not affect flags.

### RET — Return from subroutine

```
RET
```

Pops the return address from the stack (low byte first, then high
byte) and loads it into PC. Takes no argument. Does not affect flags.

### LDASP — Load from stack-relative address

```
LDASP <offset>
```

Loads A from `MEM[SP + offset]`. The old value of A is moved into B.
Does not affect flags.

### STASP — Store to stack-relative address

```
STASP <offset>
```

Stores A to `MEM[SP + offset]`. Does not affect flags or registers.

### LDAB — Load 16-bit from stack-relative address

```
LDAB <offset>
```

Loads a 16-bit value: B from `MEM[SP + offset]`, then A from
`MEM[SP + offset + 1]`. Note that after the second load, B holds the
value from `MEM[SP + offset + 1]` (the old A) — effectively, the
first byte read ends up being overwritten. The final result is:
- A = `MEM[SP + offset + 1]`
- B = value of A before the second load (which was `MEM[SP + offset]`)

This loads a little-endian 16-bit value into B:A (low byte at lower
address into B, high byte into A — but due to the A-to-B pipeline,
B ends up with the first byte read).

### STAB — Store 16-bit to stack-relative address

```
STAB <offset>
```

Stores B to `MEM[SP + offset]` and A to `MEM[SP + offset + 1]`. Does
not affect flags or registers.

### POP — Pop from stack to memory

```
POP <offset>
```

Increments SP, reads `MEM[SP]` into a temporary register, then writes
it to `MEM[B:A + offset]`. The destination address is formed from the
B:A register pair plus the offset. Does not affect flags.

### PUSHM — Push from memory to stack

```
PUSHM <offset>
```

Reads `MEM[B:A + offset]` into a temporary register, then writes it
to `MEM[SP]` and decrements SP. The source address is formed from the
B:A register pair plus the offset. Does not affect flags.

### RDSP — Read stack pointer

```
RDSP
```

Copies the stack pointer into B:A. SPH (high byte) goes into B, SPL
(low byte) goes into A. Takes no argument. Does not affect flags.

### NOP — No operation

```
NOP
```

Does nothing. Implemented as a condition-never instruction. Takes no
argument.

## Instruction encoding

Each instruction occupies 2 bytes in ROM: `[argument] [opcode]`
(little-endian order, argument at lower address).

### Opcode byte format

**ALU instructions** (bit 3 = 0):

```
Bit 7      Bit 6-4    Bit 3   Bit 2-0
push       ALU op     0       condition
(0=push,
 1=flags)
```

**Non-ALU instructions** (bit 3 = 1):

```
Bit 7-4    Bit 3   Bit 2-0
sub-op     1       condition
```

## Assembler usage

```python
from asm import assemble
from cpu import CPU

code = assemble("""
    LDA 0x10        ; A = 0x10
    LDA 0x20        ; A = 0x20, B = 0x10
    ADD             ; A = 0x30, pushed to stack
""")

cpu = CPU()
cpu.rom.load(0, code)
cpu.run_instruction()   ; execute one instruction
```

The `assemble()` function takes a source string and returns a `bytes`
object suitable for loading into ROM at offset 0 (address 0x8000).

## Complete example

```
; Compute 3 + 5 and branch if result is non-zero
    LDA 3           ; A = 3
    LDA 5           ; A = 5, B = 3
    ADD.F           ; flags set for 8 (Z=0), no push
    ZC.BR 0x10      ; branch to offset 0x10 if not zero

; Call a subroutine at address 0x8020
    LDA 0x80        ; A = 0x80 (high byte of target)
    LDA 0x20        ; A = 0x20 (low byte), B = 0x80
    CALL            ; push return address, jump to 0x8020
    ; ... execution continues here after RET

; Stack-relative access
    PUSH 0x42       ; push 0x42 to stack
    PUSH 0x99       ; push 0x99 to stack
    LDASP 2         ; A = MEM[SP+2] = 0x42
    STASP 1         ; MEM[SP+1] = A (overwrite 0x99)
```

## Instruction summary

| Mnemonic | Arg | Operation | Flags |
|----------|-----|-----------|-------|
| A | -- | Push A | Z N C |
| B | -- | Push B | Z N C |
| ADD | -- | Push A + B | Z N C |
| SUB | -- | Push A - B | Z N C |
| AND | -- | Push A & B | Z N C |
| OR | -- | Push A \| B | Z N C |
| XOR | -- | Push A ^ B | Z N C |
| SHIFT | -- | Push A shifted by B | Z N C |
| *.F | -- | ALU flags only, no push | Z N C |
| LDA | imm | A = imm, B = old A | -- |
| PUSH | imm | MEM\[SP\] = imm, SP-- | -- |
| BR | off | PCL = offset (same page) | -- |
| JMP | -- | PC = B:A | -- |
| CALL | -- | Push PC, PC = B:A | -- |
| RET | -- | Pop PC | -- |
| LDASP | off | A = MEM\[SP+off\], B = old A | -- |
| STASP | off | MEM\[SP+off\] = A | -- |
| LDAB | off | B:A from MEM\[SP+off\] (16-bit) | -- |
| STAB | off | MEM\[SP+off\] = B:A (16-bit) | -- |
| POP | off | Pop to MEM\[B:A+off\] | -- |
| PUSHM | off | Push from MEM\[B:A+off\] | -- |
| RDSP | -- | B:A = SP (B=high, A=low) | -- |
| NOP | -- | No operation | -- |
