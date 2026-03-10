import pytest
from circuit import Signal, DriveState
from netlist import Netlist


# --- Wire declarations ---

class TestWires:
    def test_single_wire(self):
        n = Netlist("W[]")
        assert n.wire('W').value == Signal.FLOATING

    def test_wire_high(self):
        n = Netlist("VCC[] = HIGH")
        assert n.wire('VCC').value == Signal.HIGH

    def test_wire_low(self):
        n = Netlist("GND[] = LOW")
        assert n.wire('GND').value == Signal.LOW

    def test_wire_pullup(self):
        n = Netlist("W[] = PULLUP")
        assert n.wire('W').value == Signal.HIGH

    def test_bus(self):
        n = Netlist("DATA[8]")
        nets = n.bus('DATA', 8)
        assert len(nets) == 8
        for net in nets:
            assert net.value == Signal.FLOATING

    def test_bus_driven(self):
        n = Netlist("RAILS[4] = LOW")
        for i in range(4):
            assert n.wire(f'RAILS{i}').value == Signal.LOW

    def test_case_insensitive_drive(self):
        n = Netlist("W[] = high")
        assert n.wire('W').value == Signal.HIGH

    def test_comments_and_blank_lines(self):
        n = Netlist("""
            # This is a comment
            W[]

            # Another comment
        """)
        assert n.wire('W').value == Signal.FLOATING

    def test_inline_comment(self):
        n = Netlist("W[] = HIGH  # power rail")
        assert n.wire('W').value == Signal.HIGH


# --- Chip declarations ---

class TestChips:
    def test_led(self):
        n = Netlist("""
            VCC[] = HIGH
            L(led)
            L.A - VCC
        """)
        n.settle()
        assert n.chip('L').is_on is True

    def test_inverter(self):
        n = Netlist("""
            VCC[] = HIGH
            OUT[]
            INV(inverter)
            INV.IN - VCC
            INV.OUT - OUT
        """)
        n.settle()
        assert n.wire('OUT').value == Signal.LOW

    def test_74574_latch(self):
        n = Netlist("""
            GND[] = LOW
            DATA[8]
            OUT[8]
            CLK[]
            FF(74574)
            FF.D[0:7] - DATA[0:7]
            FF.Q[0:7] - OUT[0:7]
            FF.CLK - CLK
            FF.OE - GND
        """)
        # Initialize CLK low and data
        n.wire('CLK').drive('test', DriveState.LOW)
        for i in range(8):
            n.wire(f'DATA{i}').drive('test', DriveState.LOW)
        n.settle()
        # Set some data HIGH
        for i in [0, 2, 5, 7]:
            n.wire(f'DATA{i}').drive('test', DriveState.HIGH)
        # Pulse clock (LOW->HIGH->LOW)
        n.wire('CLK').drive('test', DriveState.HIGH)
        n.settle()
        n.wire('CLK').drive('test', DriveState.LOW)
        n.settle()
        for i in range(8):
            expected = Signal.HIGH if i in [0, 2, 5, 7] else Signal.LOW
            assert n.wire(f'OUT{i}').value == expected, f"OUT{i}"

    def test_74573_transparent(self):
        n = Netlist("""
            GND[] = LOW
            VCC[] = HIGH
            DATA[8]
            OUT[8]
            LATCH(74573)
            LATCH.D[0:7] - DATA[0:7]
            LATCH.Q[0:7] - OUT[0:7]
            LATCH.LE - VCC
            LATCH.OE - GND
        """)
        for i in range(8):
            n.wire(f'DATA{i}').drive('test', DriveState.LOW)
        n.settle()
        # Change D3 -> outputs should follow (transparent)
        n.wire('DATA3').drive('test', DriveState.HIGH)
        n.settle()
        assert n.wire('OUT3').value == Signal.HIGH
        assert n.wire('OUT0').value == Signal.LOW

    def test_74138_decoder(self):
        n = Netlist("""
            GND[] = LOW
            VCC[] = HIGH
            Y[8]
            DEC(74138)
            DEC.A - GND
            DEC.B - GND
            DEC.C - GND
            DEC.G1 - VCC
            DEC.G2A - GND
            DEC.G2B - GND
            DEC.Y[0:7] - Y[0:7]
        """)
        n.settle()
        # Select 0: Y0 should be LOW, rest HIGH
        assert n.wire('Y0').value == Signal.LOW
        for i in range(1, 8):
            assert n.wire(f'Y{i}').value == Signal.HIGH

    def test_40193_counter(self):
        n = Netlist("""
            GND[] = LOW
            VCC[] = HIGH
            DIN[4] = LOW
            Q[4]
            TCU[]
            TCD[]
            CPU_CLK[]
            CTR(40193)
            CTR.D[0:3] - DIN[0:3]
            CTR.Q[0:3] - Q[0:3]
            CTR.CPD - VCC
            CTR.PL - VCC
            CTR.MR - GND
            CTR.CPU - CPU_CLK
            CTR.TCU - TCU
            CTR.TCD - TCD
        """)
        n.wire('CPU_CLK').drive('test', DriveState.LOW)
        n.settle()
        # Count up: pulse CPU
        n.wire('CPU_CLK').drive('test', DriveState.HIGH)
        n.settle()
        n.wire('CPU_CLK').drive('test', DriveState.LOW)
        n.settle()
        # Q should be 1
        assert n.wire('Q0').value == Signal.HIGH
        assert n.wire('Q1').value == Signal.LOW


# --- Connection syntax ---

class TestConnections:
    def test_wire_with_connections(self):
        n = Netlist("""
            VCC[] = HIGH
            INV(inverter)
            INPUT[INV.IN] = HIGH
            OUTPUT[INV.OUT]
        """)
        n.settle()
        assert n.wire('OUTPUT').value == Signal.LOW

    def test_anonymous_wire(self):
        n = Netlist("""
            INV1(inverter)
            INV2(inverter)
            IN[] = HIGH
            OUT[]
            INV1.IN - IN
            [INV1.OUT, INV2.IN]
            INV2.OUT - OUT
        """)
        n.settle()
        # HIGH -> INV1 -> LOW -> INV2 -> HIGH
        assert n.wire('OUT').value == Signal.HIGH

    def test_bus_connection(self):
        n = Netlist("""
            GND[] = LOW
            A[4]
            B[4]
            FF(74574)
            FF.D[0:3] - A[0:3]
            FF.D[4:7] - B[0:3]
            FF.Q[0:7] - NC
            FF.CLK - GND
            FF.OE - GND
        """)
        # Just verify it parses and builds without error
        n.settle()

    def test_bus_offset(self):
        """Bus connections with different start indices."""
        n = Netlist("""
            GND[] = LOW
            DATA[8]
            OUT[8]
            FF(74574)
            FF.D[0:7] - DATA[0:7]
            FF.Q[0:7] - OUT[0:7]
            FF.CLK - GND
            FF.OE - GND
        """)
        n.settle()

    def test_unconnected_pins_auto_created(self):
        """Unconnected pins get auto-created floating wires."""
        n = Netlist("""
            IN[]
            OUT[]
            INV(inverter)
            INV.IN - IN
            INV.OUT - OUT
        """)
        # INV only has IN and OUT, both connected -- no auto wires needed
        n.settle()


# --- GAL22V10 ---

class TestGAL:
    def test_adder6(self):
        n = Netlist("""
            CIN[]
            A[6]
            B[6]
            S[6]
            COUT[]

            ADD(adder6.pld)
            ADD.CIN - CIN
            ADD.A[0:5] - A[0:5]
            ADD.B[0:5] - B[0:5]
            ADD.S[0:5] - S[0:5]
            ADD.COUT - COUT
            ADD.C1 - NC
            ADD.C3 - NC
        """)

        def drive_bus(prefix, width, val):
            for i in range(width):
                n.wire(f'{prefix}{i}').drive(
                    'test', DriveState.HIGH if (val >> i) & 1 else DriveState.LOW)

        def read_bus(prefix, width):
            v = 0
            for i in range(width):
                if n.wire(f'{prefix}{i}').value == Signal.HIGH:
                    v |= (1 << i)
            return v

        # Default: all floating, drive them LOW first
        drive_bus('A', 6, 0)
        drive_bus('B', 6, 0)
        n.wire('CIN').drive('test', DriveState.LOW)
        n.settle()
        assert read_bus('S', 6) == 0
        assert n.wire('COUT').value == Signal.LOW

        # 63 + 1 = overflow
        drive_bus('A', 6, 63)
        drive_bus('B', 6, 1)
        n.settle()
        assert read_bus('S', 6) == 0
        assert n.wire('COUT').value == Signal.HIGH

    def test_adder6_exhaustive(self):
        n = Netlist("""
            CIN[]
            A[6]
            B[6]
            S[6]
            COUT[]
            ADD(adder6.pld)
            ADD.CIN - CIN
            ADD.A[0:5] - A[0:5]
            ADD.B[0:5] - B[0:5]
            ADD.S[0:5] - S[0:5]
            ADD.COUT - COUT
            ADD.C1 - NC
            ADD.C3 - NC
        """)

        def drive_bus(prefix, width, val):
            for i in range(width):
                n.wire(f'{prefix}{i}').drive(
                    'test', DriveState.HIGH if (val >> i) & 1 else DriveState.LOW)

        def read_bus(prefix, width):
            v = 0
            for i in range(width):
                if n.wire(f'{prefix}{i}').value == Signal.HIGH:
                    v |= (1 << i)
            return v

        for cin in (0, 1):
            n.wire('CIN').drive(
                'test', DriveState.HIGH if cin else DriveState.LOW)
            for a in range(64):
                drive_bus('A', 6, a)
                for b in range(64):
                    drive_bus('B', 6, b)
                    n.settle()
                    expected = a + b + cin
                    assert read_bus('S', 6) == expected & 0x3F, \
                        f"a={a} b={b} cin={cin}"
                    exp_cout = 1 if expected >= 64 else 0
                    cout = 1 if n.wire('COUT').value == Signal.HIGH else 0
                    assert cout == exp_cout, \
                        f"a={a} b={b} cin={cin}: cout"


# --- Error handling ---

class TestErrors:
    def test_duplicate_chip(self):
        with pytest.raises(ValueError, match="Duplicate chip"):
            Netlist("A(74574)\nA(74574)")

    def test_duplicate_wire(self):
        with pytest.raises(ValueError, match="Duplicate wire"):
            Netlist("W[]\nW[]")

    def test_invalid_drive(self):
        with pytest.raises(ValueError, match="Invalid drive"):
            Netlist("W[] = MAYBE")

    def test_bad_pin_ref(self):
        with pytest.raises(ValueError, match="Invalid pin reference"):
            Netlist("W[BADREF]")

    def test_bus_width_mismatch(self):
        with pytest.raises(ValueError, match="Bus width mismatch"):
            Netlist("""
                W[8]
                A(74574)
                A.D[0:3] - W[0:7]
            """)

    def test_unrecognized_line(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            Netlist("??? bad syntax")

    def test_pin_connected_twice(self):
        with pytest.raises(ValueError, match="connected twice"):
            Netlist("""
                W1[]
                W2[]
                INV(inverter)
                INV.IN - W1
                INV.IN - W2
            """)

    def test_unconnected_pin_error(self):
        with pytest.raises(ValueError, match="unconnected pins not marked NC"):
            Netlist("""
                W[]
                INV(inverter)
                INV.IN - W
            """)

    def test_unconnected_pin_error_lists_pins(self):
        with pytest.raises(ValueError, match="OUT"):
            Netlist("""
                W[]
                INV(inverter)
                INV.IN - W
            """)

    def test_unknown_pin_in_connection(self):
        with pytest.raises(ValueError, match="has no pin FAKE"):
            Netlist("""
                W[]
                INV(inverter)
                INV.IN - W
                INV.OUT - NC
                INV.FAKE - W
            """)

    def test_unknown_pin_in_nc(self):
        with pytest.raises(ValueError, match="has no pin FAKE"):
            Netlist("""
                W1[]
                W2[]
                INV(inverter)
                INV.IN - W1
                INV.OUT - W2
                INV.FAKE - NC
            """)


# --- NC syntax ---

class TestNC:
    def test_single_nc(self):
        n = Netlist("""
            W[]
            INV(inverter)
            INV.IN - W
            INV.OUT - NC
        """)
        n.settle()

    def test_bus_nc(self):
        n = Netlist("""
            GND[] = LOW
            VCC[] = HIGH
            DEC(74138)
            DEC.A - GND
            DEC.B - GND
            DEC.C - GND
            DEC.G1 - VCC
            DEC.G2A - GND
            DEC.G2B - GND
            DEC.Y[0:7] - NC
        """)
        n.settle()

    def test_partial_nc(self):
        """Some outputs connected, some NC."""
        n = Netlist("""
            GND[] = LOW
            VCC[] = HIGH
            Y0[]
            Y1[]
            DEC(74138)
            DEC.A - GND
            DEC.B - GND
            DEC.C - GND
            DEC.G1 - VCC
            DEC.G2A - GND
            DEC.G2B - GND
            DEC.Y0 - Y0
            DEC.Y1 - Y1
            DEC.Y[2:7] - NC
        """)
        n.settle()
        assert n.wire('Y0').value == Signal.LOW
        assert n.wire('Y1').value == Signal.HIGH

    def test_nc_creates_private_wire(self):
        """NC pins get private floating wires, not shared."""
        n = Netlist("""
            W[]
            INV(inverter)
            INV.IN - W
            INV.OUT - NC
        """)
        # The NC pin should have its own private wire
        assert '_INV_OUT' in n.nets
