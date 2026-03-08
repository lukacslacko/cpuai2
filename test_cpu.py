import pytest
from cpu import CPU
from circuit import Signal, DriveState


class TestAddressOffset:
    """Test the GAL22V10-based address offset logic.

    OFFSET_CTRL modes:
      0 = passthrough (addr = H:L)
      1 = add ARG (addr = H:L + ARG)
      2 = add ARG+1 (addr = H:L + ARG + 1)
    """

    def make_cpu_with(self, h, l, arg):
        cpu = CPU()
        cpu._force_register(cpu.h_reg, h)
        cpu._force_register(cpu.l_reg, l)
        cpu._force_register(cpu.arg_reg, arg)
        return cpu

    def test_passthrough(self):
        cpu = self.make_cpu_with(0x12, 0x34, 0x56)
        cpu.set_offset_ctrl(0)
        cpu.settle()
        assert cpu.read_addr() == 0x1234

    def test_passthrough_ignores_arg(self):
        cpu = self.make_cpu_with(0x80, 0xFF, 0xFF)
        cpu.set_offset_ctrl(0)
        cpu.settle()
        assert cpu.read_addr() == 0x80FF

    def test_add_arg_no_carry(self):
        cpu = self.make_cpu_with(0x12, 0x34, 0x10)
        cpu.set_offset_ctrl(1)
        cpu.settle()
        assert cpu.read_addr() == 0x1244

    def test_add_arg_page_crossing(self):
        """L=0xFE + ARG=0x05 = 0x103 -> carry into H."""
        cpu = self.make_cpu_with(0x12, 0xFE, 0x05)
        cpu.set_offset_ctrl(1)
        cpu.settle()
        assert cpu.read_addr() == 0x1303

    def test_add_arg_full_wrap(self):
        """H:L=0xFFFF + ARG=0x01 wraps to 0x0000."""
        cpu = self.make_cpu_with(0xFF, 0xFF, 0x01)
        cpu.set_offset_ctrl(1)
        cpu.settle()
        assert cpu.read_addr() == 0x0000

    def test_add_arg_plus_one_basic(self):
        cpu = self.make_cpu_with(0x12, 0x34, 0x10)
        cpu.set_offset_ctrl(2)
        cpu.settle()
        assert cpu.read_addr() == 0x1245  # 0x1234 + 0x10 + 1

    def test_add_arg_plus_one_page_crossing(self):
        """L=0xFE + ARG=0x01 + 1 = 0x100 -> carry."""
        cpu = self.make_cpu_with(0x12, 0xFE, 0x01)
        cpu.set_offset_ctrl(2)
        cpu.settle()
        assert cpu.read_addr() == 0x1300

    def test_add_arg_plus_one_double_carry(self):
        """L=0xFF + ARG=0xFF + 1 = 0x1FF -> carry from both nibbles."""
        cpu = self.make_cpu_with(0x10, 0xFF, 0xFF)
        cpu.set_offset_ctrl(2)
        cpu.settle()
        assert cpu.read_addr() == 0x11FF  # 0x10FF + 0xFF + 1 = 0x11FF

    def test_add_zero_arg(self):
        """Adding ARG=0 should not change the address."""
        cpu = self.make_cpu_with(0xAB, 0xCD, 0x00)
        cpu.set_offset_ctrl(1)
        cpu.settle()
        assert cpu.read_addr() == 0xABCD

    def test_add_zero_arg_plus_one(self):
        """Adding ARG=0 + 1 should increment by 1."""
        cpu = self.make_cpu_with(0xAB, 0xCD, 0x00)
        cpu.set_offset_ctrl(2)
        cpu.settle()
        assert cpu.read_addr() == 0xABCE

    def test_switch_modes_dynamically(self):
        """Verify switching between offset modes updates addr_bus."""
        cpu = self.make_cpu_with(0x10, 0x20, 0x05)

        cpu.set_offset_ctrl(0)
        cpu.settle()
        assert cpu.read_addr() == 0x1020

        cpu.set_offset_ctrl(1)
        cpu.settle()
        assert cpu.read_addr() == 0x1025

        cpu.set_offset_ctrl(2)
        cpu.settle()
        assert cpu.read_addr() == 0x1026

        cpu.set_offset_ctrl(0)
        cpu.settle()
        assert cpu.read_addr() == 0x1020

    def test_nibble_carry_within_low_byte(self):
        """Carry from low nibble to high nibble within the low byte."""
        cpu = self.make_cpu_with(0x00, 0x0F, 0x01)
        cpu.set_offset_ctrl(1)
        cpu.settle()
        assert cpu.read_addr() == 0x0010


class TestALU:
    """Test the GAL22V10-based ALU.

    Operations: 0=A, 1=B, 2=ADD, 3=SUB, 4=AND, 5=OR, 6=XOR, 7=SHIFT
    Shift: B[0..2]=amount, B[3]=direction (0=right, 1=left)
    Flags: Z (zero), N (negative/MSB), C (carry, ADD/SUB only)
    """

    def make_cpu_with(self, a, b):
        cpu = CPU()
        cpu._force_register(cpu.a_reg, a)
        cpu._force_register(cpu.b_reg, b)
        cpu.settle()
        return cpu

    def alu_result(self, cpu, op):
        """Set ALU op, assert result on data bus, return value."""
        cpu.set_alu_op(op)
        # Enable ASSERT[1] to drive ALU result onto data bus
        cpu.assert_enable.drive("ctrl", DriveState.HIGH)
        cpu.assert_sel[0].drive("ctrl", DriveState.HIGH)   # sel = 001 = output 1
        cpu.assert_sel[1].drive("ctrl", DriveState.LOW)
        cpu.assert_sel[2].drive("ctrl", DriveState.LOW)
        cpu.settle()
        return cpu.read_data_bus()

    def alu_flags(self, cpu, op):
        """Set ALU op, latch flags, return (z, n, c)."""
        cpu.set_alu_op(op)
        cpu.settle()
        cpu.pulse_flag_latch()
        return cpu.read_flags()

    # --- Passthrough A ---

    def test_passthrough_a(self):
        cpu = self.make_cpu_with(0x42, 0x00)
        assert self.alu_result(cpu, CPU.ALU_A) == 0x42

    def test_passthrough_a_ff(self):
        cpu = self.make_cpu_with(0xFF, 0x00)
        assert self.alu_result(cpu, CPU.ALU_A) == 0xFF

    # --- Passthrough B ---

    def test_passthrough_b(self):
        cpu = self.make_cpu_with(0x00, 0x7B)
        assert self.alu_result(cpu, CPU.ALU_B) == 0x7B

    # --- ADD ---

    def test_add_basic(self):
        cpu = self.make_cpu_with(0x10, 0x20)
        assert self.alu_result(cpu, CPU.ALU_ADD) == 0x30

    def test_add_carry(self):
        cpu = self.make_cpu_with(0xFF, 0x01)
        assert self.alu_result(cpu, CPU.ALU_ADD) == 0x00

    def test_add_nibble_carry(self):
        cpu = self.make_cpu_with(0x0F, 0x01)
        assert self.alu_result(cpu, CPU.ALU_ADD) == 0x10

    def test_add_large(self):
        cpu = self.make_cpu_with(0x80, 0x80)
        assert self.alu_result(cpu, CPU.ALU_ADD) == 0x00

    # --- SUB ---

    def test_sub_basic(self):
        cpu = self.make_cpu_with(0x30, 0x10)
        assert self.alu_result(cpu, CPU.ALU_SUB) == 0x20

    def test_sub_underflow(self):
        cpu = self.make_cpu_with(0x00, 0x01)
        assert self.alu_result(cpu, CPU.ALU_SUB) == 0xFF

    def test_sub_equal(self):
        cpu = self.make_cpu_with(0x42, 0x42)
        assert self.alu_result(cpu, CPU.ALU_SUB) == 0x00

    def test_sub_nibble_borrow(self):
        cpu = self.make_cpu_with(0x10, 0x01)
        assert self.alu_result(cpu, CPU.ALU_SUB) == 0x0F

    # --- AND ---

    def test_and_basic(self):
        cpu = self.make_cpu_with(0xF0, 0x3C)
        assert self.alu_result(cpu, CPU.ALU_AND) == 0x30

    def test_and_zero(self):
        cpu = self.make_cpu_with(0xAA, 0x55)
        assert self.alu_result(cpu, CPU.ALU_AND) == 0x00

    # --- OR ---

    def test_or_basic(self):
        cpu = self.make_cpu_with(0xF0, 0x0F)
        assert self.alu_result(cpu, CPU.ALU_OR) == 0xFF

    def test_or_overlap(self):
        cpu = self.make_cpu_with(0xAA, 0xFF)
        assert self.alu_result(cpu, CPU.ALU_OR) == 0xFF

    # --- XOR ---

    def test_xor_basic(self):
        cpu = self.make_cpu_with(0xFF, 0x0F)
        assert self.alu_result(cpu, CPU.ALU_XOR) == 0xF0

    def test_xor_same(self):
        cpu = self.make_cpu_with(0x55, 0x55)
        assert self.alu_result(cpu, CPU.ALU_XOR) == 0x00

    # --- SHIFT right ---

    def test_shift_right_1(self):
        cpu = self.make_cpu_with(0x80, 0x01)  # amt=1, dir=0(right)
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x40

    def test_shift_right_4(self):
        cpu = self.make_cpu_with(0xF0, 0x04)  # amt=4, dir=0
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x0F

    def test_shift_right_7(self):
        cpu = self.make_cpu_with(0x80, 0x07)  # amt=7, dir=0
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x01

    def test_shift_right_zero_fill(self):
        cpu = self.make_cpu_with(0x01, 0x01)  # amt=1, dir=0
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x00

    # --- SHIFT left ---

    def test_shift_left_1(self):
        cpu = self.make_cpu_with(0x01, 0x09)  # amt=1, dir=1 (B=0b1001)
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x02

    def test_shift_left_4(self):
        cpu = self.make_cpu_with(0x0F, 0x0C)  # amt=4, dir=1 (B=0b1100)
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0xF0

    def test_shift_left_7(self):
        cpu = self.make_cpu_with(0x01, 0x0F)  # amt=7, dir=1 (B=0b1111)
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x80

    def test_shift_left_zero_fill(self):
        cpu = self.make_cpu_with(0x80, 0x09)  # amt=1, dir=1
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0x00

    def test_shift_zero_amount(self):
        cpu = self.make_cpu_with(0xAB, 0x00)  # amt=0, dir=0
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0xAB

    def test_shift_zero_amount_left(self):
        cpu = self.make_cpu_with(0xAB, 0x08)  # amt=0, dir=1
        assert self.alu_result(cpu, CPU.ALU_SHIFT) == 0xAB

    # --- Flags ---

    def test_zero_flag_add(self):
        cpu = self.make_cpu_with(0xFF, 0x01)
        z, n, c = self.alu_flags(cpu, CPU.ALU_ADD)
        assert z is True

    def test_zero_flag_sub(self):
        cpu = self.make_cpu_with(0x42, 0x42)
        z, n, c = self.alu_flags(cpu, CPU.ALU_SUB)
        assert z is True

    def test_zero_flag_clear(self):
        cpu = self.make_cpu_with(0x10, 0x20)
        z, n, c = self.alu_flags(cpu, CPU.ALU_ADD)
        assert z is False

    def test_negative_flag(self):
        cpu = self.make_cpu_with(0x00, 0x01)
        z, n, c = self.alu_flags(cpu, CPU.ALU_SUB)
        assert n is True  # 0 - 1 = 0xFF, MSB = 1

    def test_negative_flag_clear(self):
        cpu = self.make_cpu_with(0x10, 0x20)
        z, n, c = self.alu_flags(cpu, CPU.ALU_ADD)
        assert n is False

    def test_carry_flag_add(self):
        cpu = self.make_cpu_with(0xFF, 0x01)
        z, n, c = self.alu_flags(cpu, CPU.ALU_ADD)
        assert c is True

    def test_carry_flag_add_no_carry(self):
        cpu = self.make_cpu_with(0x10, 0x20)
        z, n, c = self.alu_flags(cpu, CPU.ALU_ADD)
        assert c is False

    def test_carry_flag_sub(self):
        """SUB carry: C8=1 when A >= B (no borrow)."""
        cpu = self.make_cpu_with(0x30, 0x10)
        z, n, c = self.alu_flags(cpu, CPU.ALU_SUB)
        assert c is True

    def test_carry_flag_sub_borrow(self):
        """SUB carry: C8=0 when A < B (borrow)."""
        cpu = self.make_cpu_with(0x00, 0x01)
        z, n, c = self.alu_flags(cpu, CPU.ALU_SUB)
        assert c is False

    def test_flags_not_latched_without_pulse(self):
        """Flags should not update until flag_latch is pulsed."""
        cpu = self.make_cpu_with(0xFF, 0x01)
        cpu.set_alu_op(CPU.ALU_ADD)
        cpu.settle()
        # Don't pulse flag latch
        z, n, c = cpu.read_flags()
        assert z is False  # flag register still holds reset value (0)

    def test_flag_latch_control(self):
        """Only latch flags when explicitly pulsed."""
        cpu = self.make_cpu_with(0xFF, 0x01)
        # First: latch ADD flags (result=0, Z=1, C=1)
        cpu.set_alu_op(CPU.ALU_ADD)
        cpu.settle()
        cpu.pulse_flag_latch()
        z, n, c = cpu.read_flags()
        assert z is True
        assert c is True
        # Now change to a non-zero, no-carry op but don't latch
        cpu._force_register(cpu.a_reg, 0x10)
        cpu._force_register(cpu.b_reg, 0x20)
        cpu.set_alu_op(CPU.ALU_ADD)
        cpu.settle()
        # Flags should still show previous values
        z2, n2, c2 = cpu.read_flags()
        assert z2 is True
        assert c2 is True

    def test_zero_flag_shift(self):
        """Shift that produces zero should set Z flag."""
        cpu = self.make_cpu_with(0x01, 0x01)  # right shift 1: 0x01 >> 1 = 0
        cpu.set_alu_op(CPU.ALU_SHIFT)
        cpu.settle()
        cpu.pulse_flag_latch()
        z, n, c = cpu.read_flags()
        assert z is True

    def test_negative_flag_shift(self):
        """Shift that sets MSB should set N flag."""
        cpu = self.make_cpu_with(0x40, 0x09)  # left shift 1: 0x40 << 1 = 0x80
        cpu.set_alu_op(CPU.ALU_SHIFT)
        cpu.settle()
        cpu.pulse_flag_latch()
        z, n, c = cpu.read_flags()
        assert n is True

    def test_carry_not_set_for_logic_ops(self):
        """Carry flag should be 0 for AND/OR/XOR."""
        for op in (CPU.ALU_AND, CPU.ALU_OR, CPU.ALU_XOR):
            cpu = self.make_cpu_with(0xFF, 0xFF)
            cpu.set_alu_op(op)
            cpu.settle()
            cpu.pulse_flag_latch()
            z, n, c = cpu.read_flags()
            assert c is False, f"Carry should be 0 for op {op}"

    # --- Exhaustive 8-bit tests for core ops ---

    @pytest.mark.parametrize("a,b", [
        (0, 0), (1, 1), (0x7F, 0x01), (0x80, 0x80),
        (0xFF, 0xFF), (0x55, 0xAA), (0x0F, 0xF0),
        (0x12, 0x34), (0xFE, 0x01), (0x01, 0xFE),
    ])
    def test_add_parametric(self, a, b):
        cpu = self.make_cpu_with(a, b)
        result = self.alu_result(cpu, CPU.ALU_ADD)
        assert result == (a + b) & 0xFF

    @pytest.mark.parametrize("a,b", [
        (0, 0), (1, 1), (0xFF, 0x01), (0x00, 0x01),
        (0x80, 0x80), (0x55, 0xAA), (0x12, 0x34),
    ])
    def test_sub_parametric(self, a, b):
        cpu = self.make_cpu_with(a, b)
        result = self.alu_result(cpu, CPU.ALU_SUB)
        assert result == (a - b) & 0xFF


class TestMicrocode:
    """Test microcode execution via tick().

    Microcode ROM address: [microPC(4) : I(8) : flags(3)]
    Microcode word: [ASSERT(3) : LATCH(3) : ALU(3) : OFFSET(2) :
                     CONTROL(2) : END(1) : FLAGS_LATCH(1)]

    ASSERT assignments: 0=TMP, 1=ALU, 2=MEM, 3=PCH, 4=PCL, 5=SPH, 6=SPL, 7=ARG
    LATCH assignments:  0=I+ARG, 1=A+B, 2=H, 3=L, 4=PCH, 5=PCL, 6=MEM WE, 7=TMP
    CONTROL: 0=nop, 1=PC++, 2=SP--, 3=SP++
    """

    def test_micropc_starts_at_zero(self):
        cpu = CPU()
        assert cpu.read_upc() == 0

    def test_micropc_advances(self):
        cpu = CPU()
        # Load a NOP step (all zeros, no END)
        cpu.load_microcode(0x00, 0, CPU.microcode_word())
        cpu.tick()
        assert cpu.read_upc() == 1

    def test_micropc_advances_multiple(self):
        cpu = CPU()
        for step in range(4):
            cpu.load_microcode(0x00, step, CPU.microcode_word())
        for i in range(4):
            cpu.tick()
        assert cpu.read_upc() == 4

    def test_end_resets_micropc(self):
        cpu = CPU()
        cpu.load_microcode(0x00, 0, CPU.microcode_word())
        cpu.load_microcode(0x00, 1, CPU.microcode_word(end=True))
        cpu.tick()  # step 0: NOP, uPC -> 1
        assert cpu.read_upc() == 1
        cpu.tick()  # step 1: END, uPC -> 0
        assert cpu.read_upc() == 0

    def test_pc_increment_via_control(self):
        cpu = CPU()
        assert cpu.read_pc() == 0
        cpu.load_microcode(0x00, 0, CPU.microcode_word(control=CPU.CTRL_PC_INC))
        cpu.tick()
        assert cpu.read_pc() == 1

    def test_pc_increment_multiple(self):
        cpu = CPU()
        for step in range(3):
            cpu.load_microcode(0x00, step,
                CPU.microcode_word(control=CPU.CTRL_PC_INC))
        for _ in range(3):
            cpu.tick()
        assert cpu.read_pc() == 3

    def test_sp_increment_via_control(self):
        cpu = CPU()
        assert cpu.read_sp() == 0
        cpu.load_microcode(0x00, 0, CPU.microcode_word(control=CPU.CTRL_SP_INC))
        cpu.tick()
        assert cpu.read_sp() == 1

    def test_sp_decrement_via_control(self):
        cpu = CPU()
        # First increment SP to 2
        for step in range(2):
            cpu.load_microcode(0x00, step,
                CPU.microcode_word(control=CPU.CTRL_SP_INC))
        cpu.tick()
        cpu.tick()
        assert cpu.read_sp() == 2
        # Now decrement
        cpu.load_microcode(0x00, 2, CPU.microcode_word(control=CPU.CTRL_SP_DEC))
        cpu.tick()
        assert cpu.read_sp() == 1

    def test_assert_mem_reads_rom(self):
        """ASSERT=MEM(2) should put ROM data on the data bus via TMP."""
        cpu = CPU()
        cpu._force_register(cpu.h_reg, 0x80)
        cpu._force_register(cpu.l_reg, 0x00)
        cpu.settle()
        cpu.rom.load(0x0000, [0x42])
        # ASSERT=MEM(2), LATCH=TMP(7): read ROM onto bus, latch into TMP
        cpu.load_microcode(0x00, 0,
            CPU.microcode_word(assert_sel=2, latch_sel=7))
        cpu.tick()
        # Assert TMP(0) onto bus and read
        cpu.assert_enable.drive("ctrl", DriveState.HIGH)
        cpu.assert_sel[0].drive("ctrl", DriveState.LOW)
        cpu.assert_sel[1].drive("ctrl", DriveState.LOW)
        cpu.assert_sel[2].drive("ctrl", DriveState.LOW)
        cpu.settle()
        assert cpu.read_data_bus() == 0x42

    def test_latch_i_register(self):
        """LATCH=0 should latch data bus into I (and old I into ARG)."""
        cpu = CPU()
        # Put 0x55 in ROM at address 0x8000
        cpu._force_register(cpu.h_reg, 0x80)
        cpu._force_register(cpu.l_reg, 0x00)
        cpu.settle()
        cpu.rom.load(0x0000, [0x55])
        # Microcode: ASSERT=MEM(2), LATCH=I(0)
        cpu.load_microcode(0x00, 0,
            CPU.microcode_word(assert_sel=2, latch_sel=0))
        cpu.tick()
        assert cpu.read_i() == 0x55

    def test_instruction_fetch_cycle(self):
        """Full fetch: ASSERT=MEM, LATCH=I, CONTROL=PC++, END."""
        cpu = CPU()
        # Set PC to 0x8000 (ROM space)
        cpu._force_register(cpu.h_reg, 0x80)
        cpu._force_register(cpu.l_reg, 0x00)
        cpu.settle()
        # Load instruction at ROM address 0
        cpu.rom.load(0x0000, [0xAB])
        # Step 0 for ALL instructions: fetch
        for instr in range(256):
            cpu.load_microcode(instr, 0,
                CPU.microcode_word(assert_sel=2, latch_sel=0,
                                   control=CPU.CTRL_PC_INC, end=True))
        cpu.tick()
        assert cpu.read_i() == 0xAB
        assert cpu.read_pc() == 1  # PC incremented
        assert cpu.read_upc() == 0  # microPC reset by END

    def test_alu_via_microcode(self):
        """Execute ALU ADD via microcode and latch result into A."""
        cpu = CPU()
        cpu._force_register(cpu.a_reg, 0x10)
        cpu._force_register(cpu.b_reg, 0x20)
        cpu.settle()
        # Step 0: ASSERT=ALU(1), LATCH=A+B(1), ALU=ADD(2), FLAGS_LATCH
        cpu.load_microcode(0x00, 0,
            CPU.microcode_word(assert_sel=1, latch_sel=1,
                               alu_op=CPU.ALU_ADD, flags_latch=True))
        cpu.tick()
        assert cpu.read_a() == 0x30
        z, n, c = cpu.read_flags()
        assert z is False
        assert n is False
        assert c is False

    def test_flags_via_microcode(self):
        """ALU ADD with overflow: check Z and C flags via microcode."""
        cpu = CPU()
        cpu._force_register(cpu.a_reg, 0xFF)
        cpu._force_register(cpu.b_reg, 0x01)
        cpu.settle()
        cpu.load_microcode(0x00, 0,
            CPU.microcode_word(assert_sel=1, latch_sel=1,
                               alu_op=CPU.ALU_ADD, flags_latch=True))
        cpu.tick()
        assert cpu.read_a() == 0x00
        z, n, c = cpu.read_flags()
        assert z is True
        assert c is True

    def test_microcode_reads_flags(self):
        """Microcode ROM address includes flags, enabling conditional steps."""
        cpu = CPU()
        cpu._force_register(cpu.a_reg, 0xFF)
        cpu._force_register(cpu.b_reg, 0x01)
        cpu.settle()
        # Latch flags first: ADD(0xFF+0x01) -> Z=1, C=1
        cpu.set_alu_op(CPU.ALU_ADD)
        cpu.settle()
        cpu.pulse_flag_latch()
        z, n, c = cpu.read_flags()
        assert z is True and c is True
        # Flags = Z=1, N=0, C=1 = 0b101 = 5
        # Load different microcode for flags=5 vs flags=0
        # For instruction 0x00, step 0:
        # When flags=5 (Z=1,C=1): CONTROL=PC++ (action)
        cpu.load_microcode(0x00, 0,
            CPU.microcode_word(control=CPU.CTRL_PC_INC), flags=5)
        # When flags=0 (no flags): NOP
        cpu.load_microcode(0x00, 0, CPU.microcode_word(), flags=0)
        old_pc = cpu.read_pc()
        cpu.tick()
        assert cpu.read_pc() == old_pc + 1  # PC incremented because flags=5

    def test_multi_step_instruction(self):
        """Multi-step microcode: step 0 sets up, step 1 completes with END."""
        cpu = CPU()
        cpu._force_register(cpu.a_reg, 0x0F)
        cpu._force_register(cpu.b_reg, 0xF0)
        cpu.settle()
        # Step 0: ALU=OR, ASSERT=ALU, LATCH=A+B
        cpu.load_microcode(0x00, 0,
            CPU.microcode_word(assert_sel=1, latch_sel=1,
                               alu_op=CPU.ALU_OR))
        # Step 1: END (reset microPC)
        cpu.load_microcode(0x00, 1, CPU.microcode_word(end=True))
        cpu.tick()  # step 0: OR A|B -> A
        assert cpu.read_upc() == 1
        assert cpu.read_a() == 0xFF
        cpu.tick()  # step 1: END
        assert cpu.read_upc() == 0
