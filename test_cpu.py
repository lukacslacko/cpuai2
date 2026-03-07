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
