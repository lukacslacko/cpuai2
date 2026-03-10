import pytest
from circuit import (
    Signal, DriveState, DoubleDriveError,
    Net, Circuit, LED, Switch, IC74573, IC74574, IC74138, IC40193,
    IC62256, IC28256, GAL22V10,
)


# --- Net tests ---

class TestNet:
    def test_floating_by_default(self):
        net = Net("n")
        assert net.value == Signal.FLOATING

    def test_pull_up_when_undriven(self):
        net = Net("n", pull_up=True)
        assert net.value == Signal.HIGH

    def test_drive_high(self):
        net = Net("n")
        net.drive("d1", DriveState.HIGH)
        assert net.value == Signal.HIGH

    def test_drive_low(self):
        net = Net("n")
        net.drive("d1", DriveState.LOW)
        assert net.value == Signal.LOW

    def test_drive_overrides_pull_up(self):
        net = Net("n", pull_up=True)
        net.drive("d1", DriveState.LOW)
        assert net.value == Signal.LOW

    def test_hi_z_removes_driver(self):
        net = Net("n", pull_up=True)
        net.drive("d1", DriveState.LOW)
        assert net.value == Signal.LOW
        net.drive("d1", DriveState.HI_Z)
        assert net.value == Signal.HIGH

    def test_double_drive_both_high_raises(self):
        net = Net("n")
        net.drive("d1", DriveState.HIGH)
        net.drive("d2", DriveState.HIGH)
        with pytest.raises(DoubleDriveError):
            net.value

    def test_double_drive_both_low_raises(self):
        net = Net("n")
        net.drive("d1", DriveState.LOW)
        net.drive("d2", DriveState.LOW)
        with pytest.raises(DoubleDriveError):
            net.value

    def test_double_drive_conflict_raises(self):
        net = Net("n")
        net.drive("d1", DriveState.HIGH)
        net.drive("d2", DriveState.LOW)
        with pytest.raises(DoubleDriveError):
            net.value


# --- LED tests ---

class TestLED:
    def test_led_off_when_low(self):
        net = Net("n")
        net.drive("src", DriveState.LOW)
        led = LED("led0", net)
        led.update()
        assert led.is_on is False

    def test_led_on_when_high(self):
        net = Net("n")
        net.drive("src", DriveState.HIGH)
        led = LED("led0", net)
        led.update()
        assert led.is_on is True

    def test_led_off_when_floating(self):
        net = Net("n")
        led = LED("led0", net)
        led.update()
        assert led.is_on is False


# --- Switch tests ---

class TestSwitch:
    def test_switch_open_no_drive(self):
        net = Net("n", pull_up=True)
        sw = Switch("sw0", net)
        sw.update()
        assert net.value == Signal.HIGH

    def test_switch_closed_drives_low(self):
        net = Net("n", pull_up=True)
        sw = Switch("sw0", net)
        sw.closed = True
        sw.update()
        assert net.value == Signal.LOW

    def test_switch_reopen(self):
        net = Net("n", pull_up=True)
        sw = Switch("sw0", net)
        sw.closed = True
        sw.update()
        assert net.value == Signal.LOW
        sw.closed = False
        sw.update()
        assert net.value == Signal.HIGH

    def test_switch_drive_high(self):
        net = Net("n")
        sw = Switch("sw0", net, drive_value=DriveState.HIGH)
        sw.closed = True
        sw.update()
        assert net.value == Signal.HIGH


# --- 74573 transparent latch tests ---

class TestIC74573:
    def make_latch(self):
        c = Circuit()
        inputs = [c.create_net(f"D{i}") for i in range(8)]
        outputs = [c.create_net(f"Q{i}") for i in range(8)]
        le = c.create_net("LE")
        oe = c.create_net("OE")
        latch = IC74573("U1", inputs, outputs, le, oe)
        c.add_component(latch)
        return c, inputs, outputs, le, oe, latch

    def test_transparent_when_le_high(self):
        c, inputs, outputs, le, oe, latch = self.make_latch()
        # OE active (low), LE high (transparent)
        oe.drive("test", DriveState.LOW)
        le.drive("test", DriveState.HIGH)
        # Drive some inputs high
        inputs[0].drive("test", DriveState.HIGH)
        inputs[3].drive("test", DriveState.HIGH)
        inputs[7].drive("test", DriveState.HIGH)
        for i in [1, 2, 4, 5, 6]:
            inputs[i].drive("test", DriveState.LOW)
        c.settle()
        assert outputs[0].value == Signal.HIGH
        assert outputs[1].value == Signal.LOW
        assert outputs[3].value == Signal.HIGH
        assert outputs[7].value == Signal.HIGH

    def test_latches_when_le_goes_low(self):
        c, inputs, outputs, le, oe, latch = self.make_latch()
        oe.drive("test", DriveState.LOW)
        le.drive("test", DriveState.HIGH)
        for i in range(8):
            inputs[i].drive("test", DriveState.HIGH if i % 2 == 0 else DriveState.LOW)
        c.settle()
        # Now latch: LE goes low
        le.drive("test", DriveState.LOW)
        c.settle()
        # Change inputs - outputs should NOT change
        for i in range(8):
            inputs[i].drive("test", DriveState.LOW)
        c.settle()
        for i in range(8):
            expected = Signal.HIGH if i % 2 == 0 else Signal.LOW
            assert outputs[i].value == expected, f"Q{i} expected {expected}"

    def test_output_disable(self):
        c, inputs, outputs, le, oe, latch = self.make_latch()
        le.drive("test", DriveState.HIGH)
        oe.drive("test", DriveState.HIGH)  # OE inactive (high) = hi-z
        for i in range(8):
            inputs[i].drive("test", DriveState.HIGH)
        c.settle()
        for i in range(8):
            assert outputs[i].value == Signal.FLOATING


# --- 74574 edge-triggered flip-flop tests ---

class TestIC74574:
    def make_ff(self):
        c = Circuit()
        inputs = [c.create_net(f"D{i}") for i in range(8)]
        outputs = [c.create_net(f"Q{i}") for i in range(8)]
        clk = c.create_net("CLK")
        oe = c.create_net("OE")
        ff = IC74574("U1", inputs, outputs, clk, oe)
        c.add_component(ff)
        return c, inputs, outputs, clk, oe, ff

    def set_inputs(self, inputs, byte_val):
        for i in range(8):
            bit = (byte_val >> i) & 1
            inputs[i].drive("test", DriveState.HIGH if bit else DriveState.LOW)

    def read_outputs(self, outputs):
        val = 0
        for i in range(8):
            if outputs[i].value == Signal.HIGH:
                val |= (1 << i)
        return val

    def pulse_clock(self, c, clk):
        clk.drive("test", DriveState.HIGH)
        c.settle()
        clk.drive("test", DriveState.LOW)
        c.settle()

    def test_no_latch_without_clock_edge(self):
        c, inputs, outputs, clk, oe, ff = self.make_ff()
        oe.drive("test", DriveState.LOW)
        clk.drive("test", DriveState.LOW)
        self.set_inputs(inputs, 0xFF)
        c.settle()
        assert self.read_outputs(outputs) == 0x00  # initial value, no clock edge

    def test_latches_on_rising_edge(self):
        c, inputs, outputs, clk, oe, ff = self.make_ff()
        oe.drive("test", DriveState.LOW)
        clk.drive("test", DriveState.LOW)
        c.settle()
        self.set_inputs(inputs, 0xA5)
        self.pulse_clock(c, clk)
        assert self.read_outputs(outputs) == 0xA5

    def test_does_not_latch_on_falling_edge(self):
        c, inputs, outputs, clk, oe, ff = self.make_ff()
        oe.drive("test", DriveState.LOW)
        clk.drive("test", DriveState.LOW)
        c.settle()
        # Latch 0xA5
        self.set_inputs(inputs, 0xA5)
        self.pulse_clock(c, clk)
        # Change input, but only create a falling edge (already low after pulse)
        self.set_inputs(inputs, 0xFF)
        clk.drive("test", DriveState.HIGH)
        c.settle()
        clk.drive("test", DriveState.LOW)
        # The rising edge above latched 0xFF, but let's verify falling doesn't change anything
        self.set_inputs(inputs, 0x00)
        c.settle()  # no edge here
        assert self.read_outputs(outputs) == 0xFF

    def test_output_disable(self):
        c, inputs, outputs, clk, oe, ff = self.make_ff()
        oe.drive("test", DriveState.HIGH)  # disabled
        clk.drive("test", DriveState.LOW)
        c.settle()
        self.set_inputs(inputs, 0xFF)
        self.pulse_clock(c, clk)
        for i in range(8):
            assert outputs[i].value == Signal.FLOATING

    def test_holds_value_after_input_changes(self):
        c, inputs, outputs, clk, oe, ff = self.make_ff()
        oe.drive("test", DriveState.LOW)
        clk.drive("test", DriveState.LOW)
        c.settle()
        self.set_inputs(inputs, 0x42)
        self.pulse_clock(c, clk)
        assert self.read_outputs(outputs) == 0x42
        # Change inputs without clock edge
        self.set_inputs(inputs, 0x00)
        c.settle()
        assert self.read_outputs(outputs) == 0x42


# --- 74138 decoder/demux tests ---

class TestIC74138:
    def make_decoder(self):
        c = Circuit()
        a = c.create_net("A")
        b = c.create_net("B")
        cc = c.create_net("C")
        g1 = c.create_net("G1")
        g2a = c.create_net("G2A")
        g2b = c.create_net("G2B")
        outputs = [c.create_net(f"Y{i}") for i in range(8)]
        dec = IC74138("U1", a, b, cc, g1, g2a, g2b, outputs)
        c.add_component(dec)
        # Default: enabled
        g1.drive("test", DriveState.HIGH)
        g2a.drive("test", DriveState.LOW)
        g2b.drive("test", DriveState.LOW)
        # Default: select 0
        a.drive("test", DriveState.LOW)
        b.drive("test", DriveState.LOW)
        cc.drive("test", DriveState.LOW)
        c.settle()
        return c, a, b, cc, g1, g2a, g2b, outputs

    def assert_selected(self, outputs, idx):
        """Assert that only output[idx] is LOW (active), rest are HIGH."""
        for i in range(8):
            expected = Signal.LOW if i == idx else Signal.HIGH
            assert outputs[i].value == expected, f"Y{i}: expected {expected}, got {outputs[i].value}"

    def assert_all_high(self, outputs):
        for i in range(8):
            assert outputs[i].value == Signal.HIGH, f"Y{i} should be HIGH when disabled"

    def test_select_each_output(self):
        c, a, b, cc, g1, g2a, g2b, outputs = self.make_decoder()
        for sel in range(8):
            a.drive("test", DriveState.HIGH if sel & 1 else DriveState.LOW)
            b.drive("test", DriveState.HIGH if sel & 2 else DriveState.LOW)
            cc.drive("test", DriveState.HIGH if sel & 4 else DriveState.LOW)
            c.settle()
            self.assert_selected(outputs, sel)

    def test_disabled_g1_low(self):
        c, a, b, cc, g1, g2a, g2b, outputs = self.make_decoder()
        g1.drive("test", DriveState.LOW)
        c.settle()
        self.assert_all_high(outputs)

    def test_disabled_g2a_high(self):
        c, a, b, cc, g1, g2a, g2b, outputs = self.make_decoder()
        g2a.drive("test", DriveState.HIGH)
        c.settle()
        self.assert_all_high(outputs)

    def test_disabled_g2b_high(self):
        c, a, b, cc, g1, g2a, g2b, outputs = self.make_decoder()
        g2b.drive("test", DriveState.HIGH)
        c.settle()
        self.assert_all_high(outputs)

    def test_reenable_after_disable(self):
        c, a, b, cc, g1, g2a, g2b, outputs = self.make_decoder()
        a.drive("test", DriveState.HIGH)
        b.drive("test", DriveState.LOW)
        cc.drive("test", DriveState.HIGH)
        c.settle()
        self.assert_selected(outputs, 5)  # C=1, B=0, A=1 = 5
        # Disable
        g1.drive("test", DriveState.LOW)
        c.settle()
        self.assert_all_high(outputs)
        # Re-enable
        g1.drive("test", DriveState.HIGH)
        c.settle()
        self.assert_selected(outputs, 5)


# --- 62256 RAM tests ---

class TestIC62256:
    def make_ram(self):
        c = Circuit()
        addr = [c.create_net(f"A{i}") for i in range(15)]
        data = [c.create_net(f"D{i}") for i in range(8)]
        ce = c.create_net("CE")
        oe = c.create_net("OE")
        we = c.create_net("WE")
        ram = IC62256("RAM", addr, data, ce, oe, we)
        c.add_component(ram)
        # Default: disabled, no write
        ce.drive("test", DriveState.HIGH)
        oe.drive("test", DriveState.HIGH)
        we.drive("test", DriveState.HIGH)
        for i in range(15):
            addr[i].drive("test", DriveState.LOW)
        c.settle()
        return c, addr, data, ce, oe, we, ram

    def set_address(self, addr_nets, address):
        for i in range(15):
            addr_nets[i].drive("test", DriveState.HIGH if (address >> i) & 1 else DriveState.LOW)

    def drive_data(self, data_nets, value):
        for i in range(8):
            data_nets[i].drive("ext", DriveState.HIGH if (value >> i) & 1 else DriveState.LOW)

    def release_data(self, data_nets):
        for i in range(8):
            data_nets[i].drive("ext", DriveState.HI_Z)

    def read_data(self, data_nets):
        val = 0
        for i in range(8):
            if data_nets[i].value == Signal.HIGH:
                val |= (1 << i)
        return val

    def test_data_hi_z_when_disabled(self):
        c, addr, data, ce, oe, we, ram = self.make_ram()
        for i in range(8):
            assert data[i].value == Signal.FLOATING

    def test_write_then_read(self):
        c, addr, data, ce, oe, we, ram = self.make_ram()
        # Write 0xAB to address 0x100
        self.set_address(addr, 0x100)
        self.drive_data(data, 0xAB)
        ce.drive("test", DriveState.LOW)
        we.drive("test", DriveState.LOW)
        c.settle()
        we.drive("test", DriveState.HIGH)
        c.settle()
        # Release data bus and read back
        self.release_data(data)
        oe.drive("test", DriveState.LOW)
        c.settle()
        assert self.read_data(data) == 0xAB

    def test_different_addresses(self):
        c, addr, data, ce, oe, we, ram = self.make_ram()
        ce.drive("test", DriveState.LOW)
        # Write 0x42 to address 0
        self.set_address(addr, 0)
        self.drive_data(data, 0x42)
        we.drive("test", DriveState.LOW)
        c.settle()
        we.drive("test", DriveState.HIGH)
        c.settle()
        # Write 0xFF to address 1
        self.set_address(addr, 1)
        self.drive_data(data, 0xFF)
        we.drive("test", DriveState.LOW)
        c.settle()
        we.drive("test", DriveState.HIGH)
        c.settle()
        # Read back both
        self.release_data(data)
        oe.drive("test", DriveState.LOW)
        self.set_address(addr, 0)
        c.settle()
        assert self.read_data(data) == 0x42
        self.set_address(addr, 1)
        c.settle()
        assert self.read_data(data) == 0xFF

    def test_hi_z_during_write(self):
        c, addr, data, ce, oe, we, ram = self.make_ram()
        self.drive_data(data, 0x55)
        ce.drive("test", DriveState.LOW)
        we.drive("test", DriveState.LOW)
        c.settle()
        # RAM should not be driving data bus during write
        # (external driver is driving, RAM is reading — no conflict)
        assert self.read_data(data) == 0x55

    def test_overwrite(self):
        c, addr, data, ce, oe, we, ram = self.make_ram()
        ce.drive("test", DriveState.LOW)
        self.set_address(addr, 0x50)
        # Write first value
        self.drive_data(data, 0x11)
        we.drive("test", DriveState.LOW)
        c.settle()
        we.drive("test", DriveState.HIGH)
        c.settle()
        # Overwrite
        self.drive_data(data, 0x22)
        we.drive("test", DriveState.LOW)
        c.settle()
        we.drive("test", DriveState.HIGH)
        c.settle()
        # Read back
        self.release_data(data)
        oe.drive("test", DriveState.LOW)
        c.settle()
        assert self.read_data(data) == 0x22

    def test_max_address(self):
        c, addr, data, ce, oe, we, ram = self.make_ram()
        ce.drive("test", DriveState.LOW)
        self.set_address(addr, 0x7FFF)
        self.drive_data(data, 0xDE)
        we.drive("test", DriveState.LOW)
        c.settle()
        we.drive("test", DriveState.HIGH)
        c.settle()
        self.release_data(data)
        oe.drive("test", DriveState.LOW)
        c.settle()
        assert self.read_data(data) == 0xDE


# --- 28256 ROM tests ---

class TestIC28256:
    def make_rom(self):
        c = Circuit()
        addr = [c.create_net(f"A{i}") for i in range(15)]
        data = [c.create_net(f"D{i}") for i in range(8)]
        ce = c.create_net("CE")
        oe = c.create_net("OE")
        rom = IC28256("ROM", addr, data, ce, oe)
        c.add_component(rom)
        ce.drive("test", DriveState.HIGH)
        oe.drive("test", DriveState.HIGH)
        for i in range(15):
            addr[i].drive("test", DriveState.LOW)
        c.settle()
        return c, addr, data, ce, oe, rom

    def set_address(self, addr_nets, address):
        for i in range(15):
            addr_nets[i].drive("test", DriveState.HIGH if (address >> i) & 1 else DriveState.LOW)

    def read_data(self, data_nets):
        val = 0
        for i in range(8):
            if data_nets[i].value == Signal.HIGH:
                val |= (1 << i)
        return val

    def test_data_hi_z_when_disabled(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        for i in range(8):
            assert data[i].value == Signal.FLOATING

    def test_load_and_read_single_byte(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        rom.load(0x00, [0xCA])
        ce.drive("test", DriveState.LOW)
        oe.drive("test", DriveState.LOW)
        c.settle()
        assert self.read_data(data) == 0xCA

    def test_load_and_read_multiple_bytes(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        rom.load(0x100, [0xDE, 0xAD, 0xBE, 0xEF])
        ce.drive("test", DriveState.LOW)
        oe.drive("test", DriveState.LOW)
        for i, expected in enumerate([0xDE, 0xAD, 0xBE, 0xEF]):
            self.set_address(addr, 0x100 + i)
            c.settle()
            assert self.read_data(data) == expected

    def test_load_bytes_object(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        rom.load(0x00, b"\x55\xAA")
        ce.drive("test", DriveState.LOW)
        oe.drive("test", DriveState.LOW)
        self.set_address(addr, 0)
        c.settle()
        assert self.read_data(data) == 0x55
        self.set_address(addr, 1)
        c.settle()
        assert self.read_data(data) == 0xAA

    def test_unloaded_reads_zero(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        ce.drive("test", DriveState.LOW)
        oe.drive("test", DriveState.LOW)
        self.set_address(addr, 0x2000)
        c.settle()
        assert self.read_data(data) == 0x00

    def test_hi_z_when_ce_high(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        rom.load(0x00, [0xFF])
        oe.drive("test", DriveState.LOW)
        c.settle()
        for i in range(8):
            assert data[i].value == Signal.FLOATING

    def test_hi_z_when_oe_high(self):
        c, addr, data, ce, oe, rom = self.make_rom()
        rom.load(0x00, [0xFF])
        ce.drive("test", DriveState.LOW)
        c.settle()
        for i in range(8):
            assert data[i].value == Signal.FLOATING


# --- 40193 up/down counter tests ---

class TestIC40193:
    def make_counter(self):
        c = Circuit()
        data = [c.create_net(f"D{i}") for i in range(4)]
        outputs = [c.create_net(f"Q{i}") for i in range(4)]
        cpu = c.create_net("CPU")
        cpd = c.create_net("CPD")
        pl = c.create_net("PL")
        mr = c.create_net("MR")
        tcu = c.create_net("TCU")
        tcd = c.create_net("TCD")
        ctr = IC40193("CTR", data, outputs, cpu, cpd, pl, mr, tcu, tcd)
        c.add_component(ctr)
        # Default: no reset, no load, clocks low
        mr.drive("test", DriveState.LOW)
        pl.drive("test", DriveState.HIGH)
        cpu.drive("test", DriveState.LOW)
        cpd.drive("test", DriveState.LOW)
        for i in range(4):
            data[i].drive("test", DriveState.LOW)
        c.settle()
        return c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr

    def read_outputs(self, outputs):
        val = 0
        for i in range(4):
            if outputs[i].value == Signal.HIGH:
                val |= (1 << i)
        return val

    def pulse_up(self, c, cpu):
        cpu.drive("test", DriveState.HIGH)
        c.settle()
        cpu.drive("test", DriveState.LOW)
        c.settle()

    def pulse_down(self, c, cpd):
        cpd.drive("test", DriveState.HIGH)
        c.settle()
        cpd.drive("test", DriveState.LOW)
        c.settle()

    def test_initial_state_zero(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        assert self.read_outputs(outputs) == 0

    def test_master_reset(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # Count up a few times
        cpd.drive("test", DriveState.HIGH)
        for _ in range(5):
            self.pulse_up(c, cpu)
        cpd.drive("test", DriveState.LOW)
        assert self.read_outputs(outputs) == 5
        # Reset
        mr.drive("test", DriveState.HIGH)
        c.settle()
        assert self.read_outputs(outputs) == 0
        mr.drive("test", DriveState.LOW)
        c.settle()

    def test_parallel_load(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # Set data inputs to 0xB (1011)
        data[0].drive("test", DriveState.HIGH)
        data[1].drive("test", DriveState.HIGH)
        data[2].drive("test", DriveState.LOW)
        data[3].drive("test", DriveState.HIGH)
        # Load
        pl.drive("test", DriveState.LOW)
        c.settle()
        assert self.read_outputs(outputs) == 0xB
        pl.drive("test", DriveState.HIGH)
        c.settle()

    def test_count_up(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # CPD must be HIGH for count up
        cpd.drive("test", DriveState.HIGH)
        c.settle()
        for expected in range(1, 16):
            self.pulse_up(c, cpu)
            assert self.read_outputs(outputs) == expected & 0xF

    def test_count_up_wraps(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        cpd.drive("test", DriveState.HIGH)
        c.settle()
        for _ in range(16):
            self.pulse_up(c, cpu)
        assert self.read_outputs(outputs) == 0  # wrapped around

    def test_count_down(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # Load 5
        for i in range(4):
            data[i].drive("test", DriveState.HIGH if (5 >> i) & 1 else DriveState.LOW)
        pl.drive("test", DriveState.LOW)
        c.settle()
        pl.drive("test", DriveState.HIGH)
        c.settle()
        assert self.read_outputs(outputs) == 5
        # CPU must be HIGH for count down
        cpu.drive("test", DriveState.HIGH)
        c.settle()
        for expected in [4, 3, 2, 1, 0]:
            self.pulse_down(c, cpd)
            assert self.read_outputs(outputs) == expected

    def test_count_down_wraps(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        cpu.drive("test", DriveState.HIGH)
        c.settle()
        self.pulse_down(c, cpd)
        assert self.read_outputs(outputs) == 15  # 0 - 1 = 15

    def test_tcu_carry(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # Load 14
        for i in range(4):
            data[i].drive("test", DriveState.HIGH if (14 >> i) & 1 else DriveState.LOW)
        pl.drive("test", DriveState.LOW)
        c.settle()
        pl.drive("test", DriveState.HIGH)
        c.settle()
        # TCU should be HIGH (inactive) at count 14
        assert tcu.value == Signal.HIGH
        # Count to 15
        cpd.drive("test", DriveState.HIGH)
        cpu.drive("test", DriveState.HIGH)
        c.settle()
        cpu.drive("test", DriveState.LOW)
        c.settle()
        # Now at 15 with CPU LOW -> TCU should be LOW
        assert self.read_outputs(outputs) == 15
        assert tcu.value == Signal.LOW
        # When CPU goes HIGH, TCU goes back HIGH
        cpu.drive("test", DriveState.HIGH)
        c.settle()
        assert tcu.value == Signal.HIGH

    def test_tcd_borrow(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # At count 0, TCD should be LOW when CPD is LOW
        assert tcd.value == Signal.LOW  # count=0, CPD=LOW
        # CPD goes HIGH -> TCD goes HIGH
        cpd.drive("test", DriveState.HIGH)
        c.settle()
        assert tcd.value == Signal.HIGH
        # Count up once so count=1
        cpu.drive("test", DriveState.HIGH)
        c.settle()
        cpu.drive("test", DriveState.LOW)
        c.settle()
        # count=1, CPD LOW -> TCD should be HIGH (not zero)
        cpd.drive("test", DriveState.LOW)
        c.settle()
        assert tcd.value == Signal.HIGH

    def test_no_count_when_other_clock_low(self):
        """CPU rising edge should not count if CPD is LOW."""
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        # CPD is LOW (default), try to count up
        self.pulse_up(c, cpu)
        assert self.read_outputs(outputs) == 0  # should not have counted

    def test_reset_overrides_load(self):
        c, data, outputs, cpu, cpd, pl, mr, tcu, tcd, ctr = self.make_counter()
        for i in range(4):
            data[i].drive("test", DriveState.HIGH)
        pl.drive("test", DriveState.LOW)
        mr.drive("test", DriveState.HIGH)
        c.settle()
        assert self.read_outputs(outputs) == 0  # reset wins


# --- Integration test: switches -> FF1 -> FF2 -> LEDs ---

class TestIntegration:
    def test_two_stage_pipeline(self):
        """
        Switches (with pull-ups) -> 74574 #1 -> 74574 #2 -> LEDs
        Shared clock. Latch value A, then value B.
        After two clocks, value A appears at LEDs.
        """
        c = Circuit()

        # Input nets with pull-ups, switches pull low for 0-bits
        input_nets = [c.create_net(f"IN{i}", pull_up=True) for i in range(8)]
        switches = [c.add_component(Switch(f"SW{i}", input_nets[i])) for i in range(8)]

        # Middle bus between FF1 output and FF2 input
        mid_nets = [c.create_net(f"MID{i}") for i in range(8)]

        # Output nets going to LEDs
        out_nets = [c.create_net(f"OUT{i}") for i in range(8)]
        leds = [c.add_component(LED(f"LED{i}", out_nets[i])) for i in range(8)]

        # Shared clock and OE (active low = enabled)
        clk = c.create_net("CLK")
        oe = c.create_net("OE")
        oe.drive("test", DriveState.LOW)
        clk.drive("test", DriveState.LOW)

        ff1 = c.add_component(IC74574("FF1", input_nets, mid_nets, clk, oe))
        ff2 = c.add_component(IC74574("FF2", mid_nets, out_nets, clk, oe))

        c.settle()

        def set_switches(byte_val):
            """Close switch for 0-bits (pull low), open for 1-bits (pull-up = high)."""
            for i in range(8):
                bit = (byte_val >> i) & 1
                switches[i].closed = (bit == 0)

        def read_leds():
            val = 0
            for i in range(8):
                if leds[i].is_on:
                    val |= (1 << i)
            return val

        def pulse_clock():
            clk.drive("test", DriveState.HIGH)
            c.settle()
            clk.drive("test", DriveState.LOW)
            c.settle()

        # Initial state: both FFs hold 0x00
        assert read_leds() == 0x00

        # Set switches to 0xA5 and pulse clock
        set_switches(0xA5)
        pulse_clock()
        # FF1 now holds 0xA5, FF2 holds 0x00 (FF2 sampled mid_nets before FF1 drove them)
        assert read_leds() == 0x00

        # Set switches to 0x3C and pulse clock
        set_switches(0x3C)
        pulse_clock()
        # FF1 now holds 0x3C, FF2 latched FF1's old output = 0xA5
        assert read_leds() == 0xA5

        # Pulse clock again with switches still at 0x3C
        pulse_clock()
        # FF2 now holds 0x3C
        assert read_leds() == 0x3C

    def test_transparent_latch_pipeline(self):
        """Switches -> 74573 -> 74574 -> LEDs. Verify transparent pass-through."""
        c = Circuit()

        input_nets = [c.create_net(f"IN{i}", pull_up=True) for i in range(8)]
        switches = [c.add_component(Switch(f"SW{i}", input_nets[i])) for i in range(8)]

        mid_nets = [c.create_net(f"MID{i}") for i in range(8)]
        out_nets = [c.create_net(f"OUT{i}") for i in range(8)]
        leds = [c.add_component(LED(f"LED{i}", out_nets[i])) for i in range(8)]

        le = c.create_net("LE")
        clk = c.create_net("CLK")
        oe = c.create_net("OE")
        oe.drive("test", DriveState.LOW)
        clk.drive("test", DriveState.LOW)
        le.drive("test", DriveState.HIGH)  # transparent

        latch = c.add_component(IC74573("U1", input_nets, mid_nets, le, oe))
        ff = c.add_component(IC74574("U2", mid_nets, out_nets, clk, oe))

        c.settle()

        def set_switches(byte_val):
            for i in range(8):
                bit = (byte_val >> i) & 1
                switches[i].closed = (bit == 0)

        def read_leds():
            val = 0
            for i in range(8):
                if leds[i].is_on:
                    val |= (1 << i)
            return val

        # Set value, latch is transparent so mid_nets follow input_nets
        set_switches(0xBE)
        c.settle()

        # Pulse clock to latch into FF
        clk.drive("test", DriveState.HIGH)
        c.settle()
        clk.drive("test", DriveState.LOW)
        c.settle()

        assert read_leds() == 0xBE


# --- GAL22V10 6-bit adder tests ---

class TestAdder6:
    PLD_PATH = "gal/adder6.pld"

    def make_adder(self):
        with open(self.PLD_PATH) as f:
            pld_source = f.read()
        c = Circuit()
        pins = {}
        # Input nets
        for name in ["CIN",
                      "A0", "A1", "A2", "A3", "A4", "A5",
                      "B0", "B1", "B2", "B3", "B4", "B5"]:
            pins[name] = c.create_net(name)
        # Output nets (C1, C3 are intermediate carries routed through output pins)
        for name in ["S0", "S1", "S2", "S3", "S4", "S5", "COUT", "C1", "C3"]:
            pins[name] = c.create_net(name)
        gal = GAL22V10("ADDER6", pld_source, pins)
        c.add_component(gal)
        # Default: all inputs low
        for name in ["CIN",
                      "A0", "A1", "A2", "A3", "A4", "A5",
                      "B0", "B1", "B2", "B3", "B4", "B5"]:
            pins[name].drive("test", DriveState.LOW)
        c.settle()
        return c, pins

    def set_a(self, pins, val):
        for i in range(6):
            pins[f"A{i}"].drive("test", DriveState.HIGH if (val >> i) & 1 else DriveState.LOW)

    def set_b(self, pins, val):
        for i in range(6):
            pins[f"B{i}"].drive("test", DriveState.HIGH if (val >> i) & 1 else DriveState.LOW)

    def set_cin(self, pins, val):
        pins["CIN"].drive("test", DriveState.HIGH if val else DriveState.LOW)

    def read_sum(self, pins):
        val = 0
        for i in range(6):
            if pins[f"S{i}"].value == Signal.HIGH:
                val |= (1 << i)
        return val

    def read_cout(self, pins):
        return 1 if pins["COUT"].value == Signal.HIGH else 0

    def test_zero_plus_zero(self):
        c, pins = self.make_adder()
        assert self.read_sum(pins) == 0
        assert self.read_cout(pins) == 0

    def test_one_plus_one(self):
        c, pins = self.make_adder()
        self.set_a(pins, 1)
        self.set_b(pins, 1)
        c.settle()
        assert self.read_sum(pins) == 2
        assert self.read_cout(pins) == 0

    def test_carry_in(self):
        c, pins = self.make_adder()
        self.set_a(pins, 0)
        self.set_b(pins, 0)
        self.set_cin(pins, 1)
        c.settle()
        assert self.read_sum(pins) == 1
        assert self.read_cout(pins) == 0

    def test_max_plus_zero(self):
        """63 + 0 = 63, no carry."""
        c, pins = self.make_adder()
        self.set_a(pins, 63)
        c.settle()
        assert self.read_sum(pins) == 63
        assert self.read_cout(pins) == 0

    def test_max_plus_one_overflow(self):
        """63 + 1 = 0 with carry out."""
        c, pins = self.make_adder()
        self.set_a(pins, 63)
        self.set_b(pins, 1)
        c.settle()
        assert self.read_sum(pins) == 0
        assert self.read_cout(pins) == 1

    def test_max_plus_max(self):
        """63 + 63 = 126 -> sum=62, carry=1."""
        c, pins = self.make_adder()
        self.set_a(pins, 63)
        self.set_b(pins, 63)
        c.settle()
        assert self.read_sum(pins) == 62
        assert self.read_cout(pins) == 1

    def test_max_plus_max_plus_cin(self):
        """63 + 63 + 1 = 127 -> sum=63, carry=1."""
        c, pins = self.make_adder()
        self.set_a(pins, 63)
        self.set_b(pins, 63)
        self.set_cin(pins, 1)
        c.settle()
        assert self.read_sum(pins) == 63
        assert self.read_cout(pins) == 1

    def test_carry_propagation(self):
        """31 + 1 = 32: carry ripples through bits 0-4."""
        c, pins = self.make_adder()
        self.set_a(pins, 31)  # 011111
        self.set_b(pins, 1)   # 000001
        c.settle()
        assert self.read_sum(pins) == 32  # 100000
        assert self.read_cout(pins) == 0

    def test_exhaustive_no_carry_in(self):
        """Test all 64x64 input combinations without carry in."""
        c, pins = self.make_adder()
        self.set_cin(pins, 0)
        for a in range(64):
            self.set_a(pins, a)
            for b in range(64):
                self.set_b(pins, b)
                c.settle()
                expected = a + b
                assert self.read_sum(pins) == expected & 0x3F, \
                    f"a={a} b={b}: sum expected {expected & 0x3F}, got {self.read_sum(pins)}"
                assert self.read_cout(pins) == (1 if expected >= 64 else 0), \
                    f"a={a} b={b}: cout expected {1 if expected >= 64 else 0}, got {self.read_cout(pins)}"

    def test_exhaustive_with_carry_in(self):
        """Test all 64x64 input combinations with carry in."""
        c, pins = self.make_adder()
        self.set_cin(pins, 1)
        for a in range(64):
            self.set_a(pins, a)
            for b in range(64):
                self.set_b(pins, b)
                c.settle()
                expected = a + b + 1
                assert self.read_sum(pins) == expected & 0x3F, \
                    f"a={a} b={b} cin=1: sum expected {expected & 0x3F}, got {self.read_sum(pins)}"
                assert self.read_cout(pins) == (1 if expected >= 64 else 0), \
                    f"a={a} b={b} cin=1: cout expected {1 if expected >= 64 else 0}, got {self.read_cout(pins)}"
