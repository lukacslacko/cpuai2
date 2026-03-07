import pytest
from circuit import (
    Signal, DriveState, DoubleDriveError,
    Net, Circuit, LED, Switch, IC74573, IC74574, IC74138, IC40193,
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
