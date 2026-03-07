from circuit import (
    Signal, DriveState, Circuit, Net,
    LED, IC74573, IC74574, IC74138, IC40193, IC62256, IC28256, Inverter,
)


class CPU:
    def __init__(self):
        c = Circuit()
        self.circuit = c

        # Permanent GND and VCC rails
        gnd = c.create_net("GND")
        gnd.drive("rail", DriveState.LOW)
        vcc = c.create_net("VCC")
        vcc.drive("rail", DriveState.HIGH)
        self.gnd = gnd
        self.vcc = vcc

        # === Data bus with LEDs ===
        self.data_bus = [c.create_net(f"DATA{i}") for i in range(8)]
        self.data_leds = [c.add_component(LED(f"DLED{i}", self.data_bus[i]))
                          for i in range(8)]

        # === ASSERT demux (74138) ===
        # Selects which component drives the data bus (active low outputs -> OE)
        self.assert_sel = [c.create_net(f"ASSERT_SEL{i}") for i in range(3)]
        self.assert_enable = c.create_net("ASSERT_EN")
        assert_g2a = c.create_net("ASSERT_G2A")
        assert_g2b = c.create_net("ASSERT_G2B")
        assert_g2a.drive("rail", DriveState.LOW)
        assert_g2b.drive("rail", DriveState.LOW)
        self.assert_out = [c.create_net(f"ASSERT_Y{i}") for i in range(8)]
        c.add_component(IC74138("ASSERT",
            self.assert_sel[0], self.assert_sel[1], self.assert_sel[2],
            self.assert_enable, assert_g2a, assert_g2b, self.assert_out))
        # Default: disabled
        self.assert_enable.drive("ctrl", DriveState.LOW)
        for s in self.assert_sel:
            s.drive("ctrl", DriveState.LOW)

        # === LATCH demux (74138) ===
        # Selects which component latches from the data bus
        # Rising edge (deselect) triggers '574 CLK; active low for RAM WE / counter PL
        self.latch_sel = [c.create_net(f"LATCH_SEL{i}") for i in range(3)]
        self.latch_enable = c.create_net("LATCH_EN")
        latch_g2a = c.create_net("LATCH_G2A")
        latch_g2b = c.create_net("LATCH_G2B")
        latch_g2a.drive("rail", DriveState.LOW)
        latch_g2b.drive("rail", DriveState.LOW)
        self.latch_out = [c.create_net(f"LATCH_Y{i}") for i in range(8)]
        c.add_component(IC74138("LATCH",
            self.latch_sel[0], self.latch_sel[1], self.latch_sel[2],
            self.latch_enable, latch_g2a, latch_g2b, self.latch_out))
        # Default: disabled
        self.latch_enable.drive("ctrl", DriveState.LOW)
        for s in self.latch_sel:
            s.drive("ctrl", DriveState.LOW)

        # === TMP register ===
        # Asserts on ASSERT[0], latches on LATCH[7]
        self.tmp = c.add_component(IC74574("TMP",
            self.data_bus, self.data_bus,
            self.latch_out[7], self.assert_out[0]))

        # === A register ===
        # Reads from data bus, latches on LATCH[1], always outputs to a_out
        self.a_out = [c.create_net(f"A_OUT{i}") for i in range(8)]
        self.a_reg = c.add_component(IC74574("A",
            self.data_bus, self.a_out,
            self.latch_out[1], gnd))

        # === B register ===
        # Reads from A's outputs, latches on LATCH[1], always outputs to b_out
        self.b_out = [c.create_net(f"B_OUT{i}") for i in range(8)]
        self.b_reg = c.add_component(IC74574("B",
            self.a_out, self.b_out,
            self.latch_out[1], gnd))

        # === Address bus (H and L registers) ===
        self.addr_bus = [c.create_net(f"ADDR{i}") for i in range(16)]

        # H register: latches on LATCH[2], always outputs to addr[8..15]
        self.h_reg = c.add_component(IC74574("H",
            self.data_bus, self.addr_bus[8:16],
            self.latch_out[2], gnd))

        # L register: latches on LATCH[3], always outputs to addr[0..7]
        self.l_reg = c.add_component(IC74574("L",
            self.data_bus, self.addr_bus[0:8],
            self.latch_out[3], gnd))

        # === RAM (lower 32K) and ROM (upper 32K) ===
        # RAM CE = addr[15] (active low: enabled when A15=0)
        # ROM CE = ~addr[15] (enabled when A15=1)
        rom_ce = c.create_net("ROM_CE")
        c.add_component(Inverter("INV_A15", self.addr_bus[15], rom_ce))

        self.ram = c.add_component(IC62256("RAM",
            self.addr_bus[0:15], self.data_bus,
            self.addr_bus[15], self.assert_out[2], self.latch_out[6]))

        self.rom = c.add_component(IC28256("ROM",
            self.addr_bus[0:15], self.data_bus,
            rom_ce, self.assert_out[2]))

        # === Program Counter (4x 40193) ===
        self.pc_count_up = c.create_net("PC_COUNT_UP")
        self.pc_count_down = c.create_net("PC_COUNT_DOWN")
        self.pc_count_up.drive("ctrl", DriveState.HIGH)    # idle high
        self.pc_count_down.drive("ctrl", DriveState.HIGH)
        self.pc_mr = c.create_net("PC_MR")
        self.pc_mr.drive("ctrl", DriveState.HIGH)  # start in reset

        self.pc_l_int = [c.create_net(f"PCL_INT{i}") for i in range(8)]
        self.pc_h_int = [c.create_net(f"PCH_INT{i}") for i in range(8)]

        pcl1_tcu = c.create_net("PCL1_TCU")
        pcl1_tcd = c.create_net("PCL1_TCD")
        pcl2_tcu = c.create_net("PCL2_TCU")
        pcl2_tcd = c.create_net("PCL2_TCD")
        pch1_tcu = c.create_net("PCH1_TCU")
        pch1_tcd = c.create_net("PCH1_TCD")
        pch2_tcu = c.create_net("PCH2_TCU")
        pch2_tcd = c.create_net("PCH2_TCD")

        c.add_component(IC40193("PCL1",
            self.data_bus[0:4], self.pc_l_int[0:4],
            self.pc_count_up, self.pc_count_down,
            self.latch_out[5], self.pc_mr, pcl1_tcu, pcl1_tcd))
        c.add_component(IC40193("PCL2",
            self.data_bus[4:8], self.pc_l_int[4:8],
            pcl1_tcu, pcl1_tcd,
            self.latch_out[5], self.pc_mr, pcl2_tcu, pcl2_tcd))
        c.add_component(IC40193("PCH1",
            self.data_bus[0:4], self.pc_h_int[0:4],
            pcl2_tcu, pcl2_tcd,
            self.latch_out[4], self.pc_mr, pch1_tcu, pch1_tcd))
        c.add_component(IC40193("PCH2",
            self.data_bus[4:8], self.pc_h_int[4:8],
            pch1_tcu, pch1_tcd,
            self.latch_out[4], self.pc_mr, pch2_tcu, pch2_tcd))

        # PC tri-state buffers to data bus
        c.add_component(IC74573("PCH_BUF",
            self.pc_h_int, self.data_bus, vcc, self.assert_out[3]))
        c.add_component(IC74573("PCL_BUF",
            self.pc_l_int, self.data_bus, vcc, self.assert_out[4]))

        # === Stack Pointer (4x 40193) ===
        self.sp_count_up = c.create_net("SP_COUNT_UP")
        self.sp_count_down = c.create_net("SP_COUNT_DOWN")
        self.sp_count_up.drive("ctrl", DriveState.HIGH)
        self.sp_count_down.drive("ctrl", DriveState.HIGH)
        self.sp_mr = c.create_net("SP_MR")
        self.sp_mr.drive("ctrl", DriveState.HIGH)  # start in reset

        self.sp_l_int = [c.create_net(f"SPL_INT{i}") for i in range(8)]
        self.sp_h_int = [c.create_net(f"SPH_INT{i}") for i in range(8)]

        # SP data inputs unused (PL tied high), just need valid nets
        sp_dummy = [c.create_net(f"SP_D{i}") for i in range(4)]
        for d in sp_dummy:
            d.drive("rail", DriveState.LOW)

        spl1_tcu = c.create_net("SPL1_TCU")
        spl1_tcd = c.create_net("SPL1_TCD")
        spl2_tcu = c.create_net("SPL2_TCU")
        spl2_tcd = c.create_net("SPL2_TCD")
        sph1_tcu = c.create_net("SPH1_TCU")
        sph1_tcd = c.create_net("SPH1_TCD")
        sph2_tcu = c.create_net("SPH2_TCU")
        sph2_tcd = c.create_net("SPH2_TCD")

        c.add_component(IC40193("SPL1",
            sp_dummy, self.sp_l_int[0:4],
            self.sp_count_up, self.sp_count_down,
            vcc, self.sp_mr, spl1_tcu, spl1_tcd))
        c.add_component(IC40193("SPL2",
            sp_dummy, self.sp_l_int[4:8],
            spl1_tcu, spl1_tcd,
            vcc, self.sp_mr, spl2_tcu, spl2_tcd))
        c.add_component(IC40193("SPH1",
            sp_dummy, self.sp_h_int[0:4],
            spl2_tcu, spl2_tcd,
            vcc, self.sp_mr, sph1_tcu, sph1_tcd))
        c.add_component(IC40193("SPH2",
            sp_dummy, self.sp_h_int[4:8],
            sph1_tcu, sph1_tcd,
            vcc, self.sp_mr, sph2_tcu, sph2_tcd))

        # SP tri-state buffers to data bus
        c.add_component(IC74573("SPH_BUF",
            self.sp_h_int, self.data_bus, vcc, self.assert_out[5]))
        c.add_component(IC74573("SPL_BUF",
            self.sp_l_int, self.data_bus, vcc, self.assert_out[6]))

        # === I register (instruction) ===
        # Latches from data bus on ILATCH, always outputs to i_out
        self.ilatch = c.create_net("ILATCH")
        self.ilatch.drive("ctrl", DriveState.LOW)  # idle low

        self.i_out = [c.create_net(f"I_OUT{i}") for i in range(8)]
        self.i_reg = c.add_component(IC74574("I",
            self.data_bus, self.i_out,
            self.ilatch, gnd))

        # === ARG register ===
        # Latches from I's outputs on ILATCH, asserts data bus on ASSERT[7]
        self.arg_reg = c.add_component(IC74574("ARG",
            self.i_out, self.data_bus,
            self.ilatch, self.assert_out[7]))

        # === Initialization: reset counters, then settle ===
        c.settle()
        self.pc_mr.drive("ctrl", DriveState.LOW)
        self.sp_mr.drive("ctrl", DriveState.LOW)
        c.settle()

    # --- Helper methods ---

    def settle(self):
        return self.circuit.settle()

    def read_data_bus(self):
        val = 0
        for i in range(8):
            if self.data_leds[i].is_on:
                val |= (1 << i)
        return val

    def _read_nets(self, nets):
        val = 0
        for i, net in enumerate(nets):
            if net.value == Signal.HIGH:
                val |= (1 << i)
        return val

    def read_pc(self):
        lo = self._read_nets(self.pc_l_int)
        hi = self._read_nets(self.pc_h_int)
        return (hi << 8) | lo

    def read_sp(self):
        lo = self._read_nets(self.sp_l_int)
        hi = self._read_nets(self.sp_h_int)
        return (hi << 8) | lo

    def read_addr(self):
        return self._read_nets(self.addr_bus)

    def read_a(self):
        return self._read_nets(self.a_out)

    def read_b(self):
        return self._read_nets(self.b_out)

    def read_i(self):
        return self._read_nets(self.i_out)
