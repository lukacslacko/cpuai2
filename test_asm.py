"""Tests for assembler and end-to-end program execution."""

import pytest
from asm import assemble
from cpu import CPU
class TestAssembler:
    """Unit tests for the assembler."""

    def test_lda_immediate(self):
        code = assemble("LDA 0x42")
        assert code == bytes([0x42, CPU.encode_instruction(
            CPU.COND_ALWAYS, is_alu=False, other_op=CPU.OTHER_LDA_IMM)])

    def test_push_immediate(self):
        code = assemble("PUSH 255")
        assert code == bytes([0xFF, CPU.encode_instruction(
            CPU.COND_ALWAYS, is_alu=False, other_op=CPU.OTHER_PUSH_IMM)])

    def test_alu_add(self):
        code = assemble("ADD")
        assert code == bytes([0x00, CPU.encode_instruction(
            CPU.COND_ALWAYS, is_alu=True, alu_op=CPU.ALU_ADD, push=True)])

    def test_alu_sub_flags_only(self):
        code = assemble("SUB.F")
        assert code == bytes([0x00, CPU.encode_instruction(
            CPU.COND_ALWAYS, is_alu=True, alu_op=CPU.ALU_SUB, push=False)])

    def test_conditional(self):
        code = assemble("CS.LDA 0x10")
        assert code == bytes([0x10, CPU.encode_instruction(
            CPU.COND_CS, is_alu=False, other_op=CPU.OTHER_LDA_IMM)])

    def test_conditional_alu(self):
        code = assemble("ZS.ADD")
        assert code == bytes([0x00, CPU.encode_instruction(
            CPU.COND_ZS, is_alu=True, alu_op=CPU.ALU_ADD, push=True)])

    def test_conditional_alu_flags_only(self):
        code = assemble("CC.XOR.F")
        assert code == bytes([0x00, CPU.encode_instruction(
            CPU.COND_CC, is_alu=True, alu_op=CPU.ALU_XOR, push=False)])

    def test_nop(self):
        code = assemble("NOP")
        assert len(code) == 2

    def test_comments_and_blanks(self):
        code = assemble("""
            ; this is a comment
            LDA 1   ; load one

            LDA 2
        """)
        assert len(code) == 4  # 2 instructions x 2 bytes

    def test_decimal_arg(self):
        code = assemble("LDA 100")
        assert code[0] == 100

    def test_binary_arg(self):
        code = assemble("LDA 0b11110000")
        assert code[0] == 0xF0

    def test_arg_too_large(self):
        with pytest.raises(ValueError, match="out of range"):
            assemble("LDA 256")

    def test_arg_negative(self):
        with pytest.raises(ValueError, match="out of range"):
            assemble("PUSH -1")

    def test_unknown_instruction(self):
        with pytest.raises(ValueError, match="unknown instruction"):
            assemble("BOGUS")

    def test_flags_suffix_on_other(self):
        with pytest.raises(ValueError, match=".F suffix not valid"):
            assemble("LDA.F 0x42")

    def test_multi_instruction(self):
        code = assemble("""
            LDA 0x10
            LDA 0x20
            ADD
        """)
        assert len(code) == 6


class TestPrograms:
    """End-to-end tests: assemble, load, execute, verify."""

    def _run(self, source, n_instructions, pc=0x8000, sp=0x0100):
        """Assemble source, load into ROM, run n instructions."""
        code = assemble(source)
        cpu = CPU()
        cpu.generate_microcode()
        cpu._force_pc(pc)
        cpu._force_sp(sp)
        cpu.settle()
        cpu.rom.load(pc - 0x8000, code)
        for _ in range(n_instructions):
            cpu.run_instruction()
        return cpu

    def _read_ram(self, cpu, addr):
        """Read a byte from RAM directly."""
        return cpu.read_ram(addr)

    def test_load_two_values_and_add(self):
        """LDA 0x10; LDA 0x20; ADD -> A=0x30 pushed to stack."""
        cpu = self._run("""
            LDA 0x10    ; A = 0x10
            LDA 0x20    ; A = 0x20, B = 0x10
            ADD         ; A = 0x30, push to stack
        """, 3)
        assert cpu.read_a() == 0x30
        assert cpu.read_b() == 0x20  # old A before ADD result
        assert cpu.read_sp() == 0x00FF  # decremented once
        assert self._read_ram(cpu, 0x0100) == 0x30

    def test_push_constants_to_stack(self):
        """Push two constants and verify stack contents."""
        cpu = self._run("""
            PUSH 0xAA
            PUSH 0x55
        """, 2, sp=0x0100)
        assert cpu.read_sp() == 0x00FE
        assert self._read_ram(cpu, 0x0100) == 0xAA
        assert self._read_ram(cpu, 0x00FF) == 0x55

    def test_subtract_to_zero_and_conditional(self):
        """SUB.F sets Z flag, then ZS.LDA executes conditionally."""
        cpu = self._run("""
            LDA 0x07        ; A = 7
            LDA 0x07        ; A = 7, B = 7
            SUB.F           ; flags only: 7 - 7 = 0, Z=1
            ZS.LDA 0xFF    ; Z is set, so A = 0xFF
        """, 4)
        assert cpu.read_a() == 0xFF
        z, n, c = cpu.read_flags()
        assert z is True

    def test_conditional_not_taken(self):
        """ZS.LDA should NOT execute when Z is clear."""
        cpu = self._run("""
            LDA 0x07        ; A = 7
            LDA 0x03        ; A = 3, B = 7
            SUB.F           ; flags only: 3 - 7 = 0xFC, Z=0, N=1
            ZS.LDA 0xFF    ; Z is clear, so NOT executed
        """, 4)
        assert cpu.read_a() == 0x03  # unchanged from second LDA
        z, n, c = cpu.read_flags()
        assert z is False
        assert n is True

    def test_negative_conditional(self):
        """NS.PUSH executes when result is negative."""
        cpu = self._run("""
            LDA 0x01        ; A = 1
            LDA 0x02        ; A = 2, B = 1
            SUB.F           ; flags: 2 - 1 = 1, N=0
            NS.PUSH 0xDD   ; N clear -> skip
            LDA 0x80        ; A = 0x80
            LDA 0x00        ; A = 0, B = 0x80
            SUB.F           ; flags: 0 - 0x80 = 0x80, N=1
            NS.PUSH 0xEE   ; N set -> execute
        """, 8, sp=0x0100)
        # Only the second PUSH executed
        assert cpu.read_sp() == 0x00FF
        assert self._read_ram(cpu, 0x0100) == 0xEE

    def test_alu_and_or_xor(self):
        """Test AND, OR, XOR operations pushed to stack."""
        cpu = self._run("""
            LDA 0x0F        ; A = 0x0F
            LDA 0xF3        ; A = 0xF3, B = 0x0F
            AND             ; A = 0xF3 & 0x0F = 0x03, push
            LDA 0x0F        ; A = 0x0F
            LDA 0xF0        ; A = 0xF0, B = 0x0F
            OR              ; A = 0xF0 | 0x0F = 0xFF, push
            LDA 0xAA        ; A = 0xAA
            LDA 0xFF        ; A = 0xFF, B = 0xAA
            XOR             ; A = 0xFF ^ 0xAA = 0x55, push
        """, 9, sp=0x0100)
        assert self._read_ram(cpu, 0x0100) == 0x03  # AND
        assert self._read_ram(cpu, 0x00FF) == 0xFF  # OR
        assert self._read_ram(cpu, 0x00FE) == 0x55  # XOR
        assert cpu.read_sp() == 0x00FD

    def test_carry_conditional(self):
        """CS/CC conditionals based on carry from addition."""
        cpu = self._run("""
            LDA 0xFF        ; A = 0xFF
            LDA 0x01        ; A = 0x01, B = 0xFF
            ADD             ; A = 0x00, C=1, push to stack
            CS.PUSH 0xCC   ; carry set -> push 0xCC
            CC.PUSH 0xDD   ; carry clear -> skip
        """, 5, sp=0x0100)
        # ADD pushed 0x00, CS.PUSH pushed 0xCC, CC.PUSH skipped
        assert cpu.read_sp() == 0x00FE
        assert self._read_ram(cpu, 0x0100) == 0x00  # ADD result
        assert self._read_ram(cpu, 0x00FF) == 0xCC  # CS.PUSH

    def test_nop_does_nothing(self):
        """NOP advances PC but changes nothing else."""
        cpu = self._run("""
            LDA 0x42
            NOP
            NOP
        """, 3, sp=0x0100)
        assert cpu.read_a() == 0x42
        assert cpu.read_sp() == 0x0100  # unchanged
        assert cpu.read_pc() == 0x8006  # 3 instructions x 2 bytes

    def test_full_program(self):
        """Larger program: compute (10 + 20) and (10 - 20), push both,
        then conditionally push based on flags."""
        cpu = self._run("""
            ; Compute 10 + 20 = 30
            LDA 10          ; A = 10
            LDA 20          ; A = 20, B = 10
            ADD             ; A = 30, push to stack[0x0100]

            ; Compute 30 - 20 = 10 (B=20 from old A)
            SUB             ; A = 30 - 20 = 10, push to stack[0x00FF]
                            ; SUB carry=1 (no borrow), Z=0, N=0

            ; Test flags from SUB
            ZS.PUSH 0xBB   ; Z=0 -> skip
            NS.PUSH 0xBB   ; N=0 -> skip
            CS.PUSH 0xAA   ; C=1 -> execute
        """, 7, sp=0x0100)
        assert self._read_ram(cpu, 0x0100) == 30   # 10 + 20
        assert self._read_ram(cpu, 0x00FF) == 10   # 30 - 20
        assert self._read_ram(cpu, 0x00FE) == 0xAA # CS.PUSH
        assert cpu.read_sp() == 0x00FD  # 3 pushes total

    def test_br_immediate(self):
        """BR sets PCL to the argument (branch within page)."""
        # Code at 0x8000: BR 0x10 → PC becomes 0x80:0x10
        cpu = self._run("""
            BR 0x10
        """, 1)
        assert cpu.read_pc() == 0x8010

    def test_jmp(self):
        """JMP sets PC to A:B (A=low, B=high)."""
        cpu = self._run("""
            LDA 0x00        ; A = 0x00 (will become B)
            LDA 0x50        ; A = 0x50 (PCL), B = 0x00 (PCH)
            JMP             ; PC = 0x0050
        """, 3)
        assert cpu.read_pc() == 0x0050

    def test_jmp_high_address(self):
        """JMP to address with non-zero high byte."""
        cpu = self._run("""
            LDA 0x90        ; A = 0x90 (will become B = PCH)
            LDA 0x20        ; A = 0x20 (PCL), B = 0x90 (PCH)
            JMP             ; PC = 0x9020
        """, 3)
        assert cpu.read_pc() == 0x9020

    def test_call_and_ret(self):
        """CALL pushes return address and jumps; RET restores it."""
        # Layout (ROM at 0x8000):
        #   0x8000: LDA 0x80     (set up jump target high byte)
        #   0x8002: LDA 0x20     (A=0x20=target low, B=0x80=target high)
        #   0x8004: CALL         (push PC=0x8006, jump to 0x8020)
        #   0x8006: PUSH 0xDD   (should execute after RET)
        #
        # At 0x8020 (ROM offset 0x20):
        #   0x8020: RET          (return to 0x8006)
        code_main = assemble("""
            LDA 0x80
            LDA 0x20
            CALL
            PUSH 0xDD
        """)
        code_sub = assemble("""
            RET
        """)
        cpu = CPU()
        cpu.generate_microcode()
        cpu._force_pc(0x8000)
        cpu._force_sp(0x0100)
        cpu.settle()
        cpu.rom.load(0x0000, code_main)
        cpu.rom.load(0x0020, code_sub)

        # Execute: LDA, LDA, CALL
        cpu.run_instruction()  # LDA 0x80
        cpu.run_instruction()  # LDA 0x20
        cpu.run_instruction()  # CALL -> jumps to 0x8020
        assert cpu.read_pc() == 0x8020
        # Return address 0x8006 should be on stack
        # PCH=0x80 at SP+2=0x0100, PCL=0x06 at SP+1=0x00FF
        assert cpu.read_sp() == 0x00FE
        assert self._read_ram(cpu, 0x0100) == 0x80  # PCH
        assert self._read_ram(cpu, 0x00FF) == 0x06  # PCL

        # Execute RET
        cpu.run_instruction()  # RET -> returns to 0x8006
        assert cpu.read_pc() == 0x8006
        assert cpu.read_sp() == 0x0100  # SP restored

        # Execute PUSH 0xDD (proves we're back at the right place)
        cpu.run_instruction()  # PUSH 0xDD
        assert self._read_ram(cpu, 0x0100) == 0xDD
        assert cpu.read_sp() == 0x00FF

    def test_call_nested(self):
        """Nested CALL/RET: call A which calls B, both return correctly."""
        # Main:  0x8000: setup + CALL sub_a (at 0x8040)
        # sub_a: 0x8040: CALL sub_b (at 0x8060), then RET
        # sub_b: 0x8060: LDA 0x42, RET
        code_main = assemble("""
            LDA 0x80
            LDA 0x40
            CALL
        """)
        # sub_a: set up B:A = 0x8060, call, then return
        code_sub_a = assemble("""
            LDA 0x80
            LDA 0x60
            CALL
            RET
        """)
        code_sub_b = assemble("""
            LDA 0x42
            RET
        """)
        cpu = CPU()
        cpu.generate_microcode()
        cpu._force_pc(0x8000)
        cpu._force_sp(0x0100)
        cpu.settle()
        cpu.rom.load(0x0000, code_main)
        cpu.rom.load(0x0040, code_sub_a)
        cpu.rom.load(0x0060, code_sub_b)

        # Main: LDA, LDA, CALL sub_a
        for _ in range(3):
            cpu.run_instruction()
        assert cpu.read_pc() == 0x8040
        assert cpu.read_sp() == 0x00FE

        # sub_a: LDA, LDA, CALL sub_b
        for _ in range(3):
            cpu.run_instruction()
        assert cpu.read_pc() == 0x8060
        assert cpu.read_sp() == 0x00FC

        # sub_b: LDA 0x42
        cpu.run_instruction()
        assert cpu.read_a() == 0x42

        # sub_b: RET (back to sub_a)
        cpu.run_instruction()
        assert cpu.read_pc() == 0x8046  # after CALL in sub_a
        assert cpu.read_sp() == 0x00FE

        # sub_a: RET (back to main)
        cpu.run_instruction()
        assert cpu.read_pc() == 0x8006  # after CALL in main
        assert cpu.read_sp() == 0x0100

    def test_conditional_call(self):
        """CALL with condition: only calls when condition is met."""
        cpu = self._run("""
            LDA 0x80
            LDA 0x40
            LDA 0x00
            SUB.F           ; 0 - 0x40: Z=0, N=1, C=0
            ZS.CALL         ; Z=0 -> skip
        """, 5, sp=0x0100)
        assert cpu.read_sp() == 0x0100  # no push happened
        assert cpu.read_pc() == 0x800A  # continued past CALL

    def test_ldasp(self):
        """LDASP loads A from memory at SP+offset."""
        cpu = self._run("""
            PUSH 0xAA       ; stack[0x0100] = 0xAA, SP=0x00FF
            PUSH 0xBB       ; stack[0x00FF] = 0xBB, SP=0x00FE
            LDASP 2         ; A = MEM[SP+2] = MEM[0x0100] = 0xAA
        """, 3, sp=0x0100)
        assert cpu.read_a() == 0xAA

    def test_ldasp_offset_1(self):
        """LDASP with offset 1 reads top of stack."""
        cpu = self._run("""
            PUSH 0x42       ; stack[0x0100] = 0x42, SP=0x00FF
            LDASP 1         ; A = MEM[SP+1] = MEM[0x0100] = 0x42
        """, 2, sp=0x0100)
        assert cpu.read_a() == 0x42

    def test_stasp(self):
        """STASP stores A to memory at SP+offset."""
        cpu = self._run("""
            PUSH 0x00       ; make room, SP=0x00FF
            PUSH 0x00       ; make room, SP=0x00FE
            LDA 0x77
            STASP 1         ; MEM[SP+1] = MEM[0x00FF] = 0x77
        """, 4, sp=0x0100)
        assert self._read_ram(cpu, 0x00FF) == 0x77

    def test_ldab(self):
        """LDAB loads 16-bit value: B=MEM[SP+ARG], A=MEM[SP+ARG+1]."""
        cpu = self._run("""
            PUSH 0x12       ; stack[0x0100] = 0x12 (high), SP=0x00FF
            PUSH 0x34       ; stack[0x00FF] = 0x34 (low), SP=0x00FE
            LDAB 1          ; B=MEM[SP+1]=0x34, A=MEM[SP+2]=0x12
        """, 3, sp=0x0100)
        assert cpu.read_a() == 0x12
        assert cpu.read_b() == 0x34

    def test_stab(self):
        """STAB stores B to [SP+ARG], A to [SP+ARG+1]."""
        cpu = self._run("""
            PUSH 0x00       ; room, SP=0x00FF
            PUSH 0x00       ; room, SP=0x00FE
            LDA 0xAA        ; A=0xAA (will be B after next LDA)
            LDA 0xBB        ; A=0xBB, B=0xAA
            STAB 1          ; MEM[SP+1]=B=0xAA, MEM[SP+2]=A=0xBB
        """, 5, sp=0x0100)
        assert self._read_ram(cpu, 0x00FF) == 0xAA  # B at SP+1
        assert self._read_ram(cpu, 0x0100) == 0xBB  # A at SP+2

    def test_ldab_stab_roundtrip(self):
        """STAB then LDAB should recover the same A:B values."""
        cpu = self._run("""
            PUSH 0x00       ; room
            PUSH 0x00       ; room
            LDA 0xDE        ; will become B
            LDA 0xAD        ; A=0xAD, B=0xDE
            STAB 1          ; store B:A to stack
            LDA 0x00        ; clear A
            LDA 0x00        ; clear A and B
            LDAB 1          ; reload: B=0xDE, A=0xAD
        """, 8, sp=0x0100)
        assert cpu.read_a() == 0xAD
        assert cpu.read_b() == 0xDE

    def test_pop(self):
        """POP pops from stack into MEM[B:A+offset]."""
        cpu = self._run("""
            PUSH 0x42       ; stack[0x0100] = 0x42, SP=0x00FF
            LDA 0x02        ; A=0x02 (will be B=addr high)
            LDA 0x00        ; A=0x00 (addr low), B=0x02
            POP 5           ; pop 0x42, write to MEM[0x0200+5]=MEM[0x0205]
        """, 4, sp=0x0100)
        assert cpu.read_sp() == 0x0100  # SP restored after pop
        assert self._read_ram(cpu, 0x0205) == 0x42

    def test_pushm(self):
        """PUSHM reads MEM[B:A+offset] and pushes to stack."""
        cpu = self._run("""
            PUSH 0x42       ; put 0x42 at 0x0100
            LDA 0x01        ; will become B (addr high)
            LDA 0x00        ; A=0x00, B=0x01
            PUSHM 0         ; read MEM[0x0100+0]=0x42, push to stack
        """, 4, sp=0x0100)
        # After PUSH 0x42: SP=0x00FF, stack[0x0100]=0x42
        # After PUSHM: reads from 0x0100 (=0x42), pushes to stack[0x00FF], SP=0x00FE
        assert cpu.read_sp() == 0x00FE
        assert self._read_ram(cpu, 0x00FF) == 0x42

    def test_pushm_pop_roundtrip(self):
        """PUSHM then POP: read from memory, push, pop back elsewhere."""
        cpu = self._run("""
            ; Store 0xEE at address 0x0050
            LDA 0x00        ; B=0x00 (addr high)
            LDA 0x50        ; A=0x50 (addr low), B=0x00
            PUSH 0xEE       ; stack[0x0100]=0xEE, SP=0x00FF
            LDA 0x00        ; set up addr again
            LDA 0x50
            POP 0           ; pop 0xEE -> MEM[0x0050]
            ; Now push it back from MEM[0x0050]
            LDA 0x00
            LDA 0x50
            PUSHM 0         ; read MEM[0x0050]=0xEE, push
            ; Pop and store elsewhere at 0x0060
            LDA 0x00
            LDA 0x60
            POP 0           ; pop 0xEE -> MEM[0x0060]
        """, 12, sp=0x0100)
        assert self._read_ram(cpu, 0x0050) == 0xEE
        assert self._read_ram(cpu, 0x0060) == 0xEE

    def test_rdsp(self):
        """RDSP copies SP into B:A (B=high, A=low)."""
        cpu = self._run("""
            PUSH 0xAA       ; SP goes from 0x0100 to 0x00FF
            PUSH 0xBB       ; SP goes from 0x00FF to 0x00FE
            RDSP            ; A=0xFE (SPL), B=0x00 (SPH)
        """, 3, sp=0x0100)
        assert cpu.read_a() == 0xFE
        assert cpu.read_b() == 0x00

    def test_rdsp_high_sp(self):
        """RDSP with SP in high memory captures both bytes."""
        cpu = self._run("""
            RDSP            ; A=0x50 (SPL), B=0x02 (SPH)
        """, 1, sp=0x0250)
        assert cpu.read_a() == 0x50
        assert cpu.read_b() == 0x02
