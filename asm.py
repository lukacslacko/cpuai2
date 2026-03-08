"""Assembler for cpuai2 instruction set.

Syntax:
    [COND.]MNEMONIC[.F] [argument]

ALU instructions (bit 3 = 0):
    A, B, ADD, SUB, AND, OR, XOR, SHIFT
    Append .F for flags-only (no push to stack).

Other instructions (bit 3 = 1):
    LDA <imm>    - load immediate into A
    PUSH <imm>   - push immediate to stack
    NOP          - no operation (condition=never)

Condition prefixes (default is AL = always):
    NV  never        AL  always
    CS  carry set    CC  carry clear
    ZS  zero set     ZC  zero clear
    NS  negative set NC  negative clear

Arguments can be decimal (42), hex (0x2A), or binary (0b101010).
Comments start with ; and blank lines are ignored.

Memory layout per instruction: [argument byte] [opcode byte]
"""

from cpu import CPU

CONDITIONS = {
    "NV": CPU.COND_NEVER,
    "AL": CPU.COND_ALWAYS,
    "CS": CPU.COND_CS,
    "CC": CPU.COND_CC,
    "ZS": CPU.COND_ZS,
    "ZC": CPU.COND_ZC,
    "NS": CPU.COND_NS,
    "NC": CPU.COND_NC,
}

ALU_OPS = {
    "A": CPU.ALU_A,
    "B": CPU.ALU_B,
    "ADD": CPU.ALU_ADD,
    "SUB": CPU.ALU_SUB,
    "AND": CPU.ALU_AND,
    "OR": CPU.ALU_OR,
    "XOR": CPU.ALU_XOR,
    "SHIFT": CPU.ALU_SHIFT,
}

OTHER_OPS = {
    "LDA": CPU.OTHER_LDA_IMM,
    "PUSH": CPU.OTHER_PUSH_IMM,
    "BR": CPU.OTHER_BR,
    "JMP": CPU.OTHER_JMP,
    "CALL": CPU.OTHER_CALL,
    "RET": CPU.OTHER_RET,
    "LDASP": CPU.OTHER_LDASP,
    "STASP": CPU.OTHER_STASP,
    "LDAB": CPU.OTHER_LDAB,
    "STAB": CPU.OTHER_STAB,
    "POP": CPU.OTHER_POP,
    "PUSHM": CPU.OTHER_PUSHM,
}


def assemble(source):
    """Assemble source code into bytes for ROM.

    Returns a bytes object. Each instruction is 2 bytes: [argument] [opcode].
    """
    output = []
    for line_no, line in enumerate(source.splitlines(), 1):
        line = line.split(";")[0].strip()
        if not line:
            continue

        tokens = line.split()
        mnemonic = tokens[0].upper()
        arg_str = tokens[1] if len(tokens) > 1 else None

        # NOP is a special case: condition=never
        if mnemonic == "NOP":
            opcode = CPU.encode_instruction(CPU.COND_NEVER, is_alu=False, other_op=0)
            output.extend([0x00, opcode])
            continue

        # Parse condition prefix: "CS.ADD" -> cond=CS, rest="ADD"
        parts = mnemonic.split(".")
        cond = CPU.COND_ALWAYS
        if parts[0] in CONDITIONS:
            cond = CONDITIONS[parts.pop(0)]

        # Check for .F suffix (flags-only for ALU)
        flags_only = False
        if parts[-1] == "F":
            flags_only = True
            parts.pop()

        mnemonic_base = ".".join(parts)

        # Parse argument value
        arg_val = 0
        if arg_str is not None:
            arg_val = int(arg_str, 0)
            if arg_val < 0 or arg_val > 255:
                raise ValueError(
                    f"Line {line_no}: argument {arg_val} out of range (0-255)"
                )

        if mnemonic_base in ALU_OPS:
            opcode = CPU.encode_instruction(
                cond, is_alu=True, alu_op=ALU_OPS[mnemonic_base], push=not flags_only
            )
        elif mnemonic_base in OTHER_OPS:
            if flags_only:
                raise ValueError(
                    f"Line {line_no}: .F suffix not valid for '{mnemonic_base}'"
                )
            opcode = CPU.encode_instruction(
                cond, is_alu=False, other_op=OTHER_OPS[mnemonic_base]
            )
        else:
            raise ValueError(f"Line {line_no}: unknown instruction '{mnemonic_base}'")

        output.extend([arg_val & 0xFF, opcode])

    return bytes(output)
