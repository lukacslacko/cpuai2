"""Instruction set constants and microcode generation for cpuai2."""


# ASSERT demux select values
ASSERT_TMP = 0
ASSERT_ALU = 1
ASSERT_MEM = 2
ASSERT_PCH = 3
ASSERT_PCL = 4
ASSERT_SPH = 5
ASSERT_SPL = 6
ASSERT_ARG = 7

# LATCH demux select values
LATCH_I_ARG = 0
LATCH_A_B = 1
LATCH_H = 2
LATCH_L = 3
LATCH_PCH = 4
LATCH_PCL = 5
LATCH_MEM_WE = 6
LATCH_TMP = 7

# ALU operations
ALU_A = 0     # 000: passthrough A
ALU_B = 1     # 001: passthrough B
ALU_ADD = 2   # 010: A + B
ALU_SUB = 3   # 011: A - B
ALU_AND = 4   # 100: A & B
ALU_OR = 5    # 101: A | B
ALU_XOR = 6   # 110: A ^ B
ALU_SHIFT = 7 # 111: shift A by B

# CONTROL demux actions
CTRL_NOP = 0
CTRL_PC_INC = 1
CTRL_SP_DEC = 2
CTRL_SP_INC = 3

# Address offset modes
OFFSET_NONE = 0       # passthrough H:L
OFFSET_ARG = 1        # H:L + ARG
OFFSET_ARG_PLUS1 = 2  # H:L + ARG + 1

# Condition codes (instruction bits 0-2)
COND_NEVER = 0
COND_ALWAYS = 1
COND_CS = 2    # carry set
COND_CC = 3    # carry clear
COND_ZS = 4    # zero set
COND_ZC = 5    # zero clear
COND_NS = 6    # negative set
COND_NC = 7    # negative clear

# Non-ALU instruction sub-opcodes
OTHER_LDA_IMM = 0
OTHER_PUSH_IMM = 1
OTHER_BR = 2
OTHER_JMP = 3
OTHER_CALL = 4
OTHER_RET = 5
OTHER_LDASP = 6
OTHER_STASP = 7
OTHER_LDAB = 8
OTHER_STAB = 9
OTHER_POP = 10
OTHER_PUSHM = 11

# Microcode word bit positions
UC_ASSERT = 0      # bits 0-2
UC_LATCH = 3       # bits 3-5
UC_ALU = 6         # bits 6-8
UC_OFFSET = 9      # bits 9-10
UC_CONTROL = 11    # bits 11-12
UC_END = 13        # bit 13
UC_FLAGS = 14      # bit 14


def microcode_word(assert_sel=0, latch_sel=0, alu_op=0, offset=0,
                   control=0, end=False, flags_latch=False):
    """Build a 16-bit microcode word from field values."""
    return ((assert_sel & 7) |
            ((latch_sel & 7) << 3) |
            ((alu_op & 7) << 6) |
            ((offset & 3) << 9) |
            ((control & 3) << 11) |
            ((1 if end else 0) << 13) |
            ((1 if flags_latch else 0) << 14))


def encode_instruction(cond, is_alu, alu_op=0, push=True, other_op=0):
    """Encode an instruction byte.

    For ALU (is_alu=True): bits 4-6 = alu_op, bit 7 = 0 if push, 1 if flags-only.
    For other (is_alu=False): bits 4-7 = other_op.
    """
    opcode = cond & 7
    if is_alu:
        opcode |= (alu_op & 7) << 4
        if not push:
            opcode |= 1 << 7
    else:
        opcode |= 1 << 3
        opcode |= (other_op & 0xF) << 4
    return opcode


def check_condition(cond, z, n, c):
    """Return True if condition is met given flag values."""
    if cond == 0: return False   # never
    if cond == 1: return True    # always
    if cond == 2: return c == 1  # carry set
    if cond == 3: return c == 0  # carry clear
    if cond == 4: return z == 1  # zero set
    if cond == 5: return z == 0  # zero clear
    if cond == 6: return n == 1  # negative set
    if cond == 7: return n == 0  # negative clear
    return False


def generate_microcode():
    """Generate microcode EEPROM contents.

    Returns (lo_bytes, hi_bytes) where each is a bytearray of 32768 bytes.
    """
    lo = bytearray(32768)
    hi = bytearray(32768)
    MW = microcode_word

    def store(instruction, step, word, flags=None):
        lo_byte = word & 0xFF
        hi_byte = (word >> 8) & 0xFF
        if flags is None:
            flag_range = range(8)
        else:
            flag_range = [flags]
        for f in flag_range:
            addr = step | (instruction << 4) | (f << 12)
            lo[addr] = lo_byte
            hi[addr] = hi_byte

    # Common prefix: steps 0-5, same for all instructions and flags.
    prefix = [
        # Step 0: PCL -> L
        MW(assert_sel=ASSERT_PCL, latch_sel=LATCH_L),
        # Step 1: PCH -> H
        MW(assert_sel=ASSERT_PCH, latch_sel=LATCH_H),
        # Step 2: MEM -> I (reads argument), PC++
        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_I_ARG,
           control=CTRL_PC_INC),
        # Step 3: PCL -> L
        MW(assert_sel=ASSERT_PCL, latch_sel=LATCH_L),
        # Step 4: PCH -> H
        MW(assert_sel=ASSERT_PCH, latch_sel=LATCH_H),
        # Step 5: MEM -> I (reads opcode, old I=arg -> ARG), PC++
        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_I_ARG,
           control=CTRL_PC_INC),
    ]

    for instr in range(256):
        for step, word in enumerate(prefix):
            store(instr, step, word)

    # Instruction-specific microcode (steps 6+)
    for instr in range(256):
        cond = instr & 7
        is_other = (instr >> 3) & 1

        for f in range(8):
            z = f & 1
            n = (f >> 1) & 1
            c = (f >> 2) & 1

            if not check_condition(cond, z, n, c):
                store(instr, 6, MW(end=True), flags=f)
                continue

            if not is_other:
                # ALU instruction
                alu_op = (instr >> 4) & 7
                push = not ((instr >> 7) & 1)

                if push:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_A_B,
                           alu_op=alu_op, flags_latch=True), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_MEM_WE,
                           alu_op=ALU_A, control=CTRL_SP_DEC, end=True), flags=f)
                else:
                    store(instr, 6,
                        MW(alu_op=alu_op, flags_latch=True, end=True), flags=f)

            else:
                sub_op = (instr >> 4) & 0xF

                if sub_op == OTHER_LDA_IMM:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_ARG, latch_sel=LATCH_A_B, end=True),
                        flags=f)

                elif sub_op == OTHER_PUSH_IMM:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_ARG, latch_sel=LATCH_MEM_WE,
                           control=CTRL_SP_DEC, end=True), flags=f)

                elif sub_op == OTHER_BR:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_ARG, latch_sel=LATCH_PCL, end=True),
                        flags=f)

                elif sub_op == OTHER_JMP:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_PCL,
                           alu_op=ALU_A), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_PCH,
                           alu_op=ALU_B, end=True), flags=f)

                elif sub_op == OTHER_CALL:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_PCH, latch_sel=LATCH_MEM_WE,
                           control=CTRL_SP_DEC), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 10,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 11,
                        MW(assert_sel=ASSERT_PCL, latch_sel=LATCH_MEM_WE,
                           control=CTRL_SP_DEC), flags=f)
                    store(instr, 12,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_PCL,
                           alu_op=ALU_A), flags=f)
                    store(instr, 13,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_PCH,
                           alu_op=ALU_B, end=True), flags=f)

                elif sub_op == OTHER_RET:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_TMP, latch_sel=LATCH_TMP,
                           control=CTRL_SP_INC), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_PCL,
                           control=CTRL_SP_INC), flags=f)
                    store(instr, 10,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 11,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 12,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_PCH,
                           end=True), flags=f)

                elif sub_op == OTHER_LDASP:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_A_B,
                           offset=OFFSET_ARG, end=True), flags=f)

                elif sub_op == OTHER_STASP:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_MEM_WE,
                           alu_op=ALU_A, offset=OFFSET_ARG, end=True), flags=f)

                elif sub_op == OTHER_LDAB:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_A_B,
                           offset=OFFSET_ARG), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_A_B,
                           offset=OFFSET_ARG_PLUS1, end=True), flags=f)

                elif sub_op == OTHER_STAB:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_MEM_WE,
                           alu_op=ALU_B, offset=OFFSET_ARG), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_MEM_WE,
                           alu_op=ALU_A, offset=OFFSET_ARG_PLUS1, end=True),
                        flags=f)

                elif sub_op == OTHER_POP:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_TMP, latch_sel=LATCH_TMP,
                           control=CTRL_SP_INC), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_TMP), flags=f)
                    store(instr, 10,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_L,
                           alu_op=ALU_A), flags=f)
                    store(instr, 11,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_H,
                           alu_op=ALU_B), flags=f)
                    store(instr, 12,
                        MW(assert_sel=ASSERT_TMP, latch_sel=LATCH_MEM_WE,
                           offset=OFFSET_ARG, end=True), flags=f)

                elif sub_op == OTHER_PUSHM:
                    store(instr, 6,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_L,
                           alu_op=ALU_A), flags=f)
                    store(instr, 7,
                        MW(assert_sel=ASSERT_ALU, latch_sel=LATCH_H,
                           alu_op=ALU_B), flags=f)
                    store(instr, 8,
                        MW(assert_sel=ASSERT_MEM, latch_sel=LATCH_TMP,
                           offset=OFFSET_ARG), flags=f)
                    store(instr, 9,
                        MW(assert_sel=ASSERT_SPL, latch_sel=LATCH_L), flags=f)
                    store(instr, 10,
                        MW(assert_sel=ASSERT_SPH, latch_sel=LATCH_H), flags=f)
                    store(instr, 11,
                        MW(assert_sel=ASSERT_TMP, latch_sel=LATCH_MEM_WE,
                           control=CTRL_SP_DEC, end=True), flags=f)

                else:
                    store(instr, 6, MW(end=True), flags=f)

    return lo, hi
