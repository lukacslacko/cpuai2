import os

from circuit import (
    Signal, DriveState, Circuit, Net,
    LED, IC74573, IC74574, IC74138, IC40193, IC62256, IC28256,
    Inverter, GAL22V10,
)

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_pld(filename):
    with open(os.path.join(_DIR, "gal", filename)) as f:
        return f.read()


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

        # === H and L registers (output to internal nets, not addr bus directly) ===
        self.h_out = [c.create_net(f"H_OUT{i}") for i in range(8)]
        self.l_out = [c.create_net(f"L_OUT{i}") for i in range(8)]

        # H register: latches on LATCH[2], always outputs to h_out
        self.h_reg = c.add_component(IC74574("H",
            self.data_bus, self.h_out,
            self.latch_out[2], gnd))

        # L register: latches on LATCH[3], always outputs to l_out
        self.l_reg = c.add_component(IC74574("L",
            self.data_bus, self.l_out,
            self.latch_out[3], gnd))

        # === I register (instruction) ===
        # Latches from data bus on ILATCH, always outputs to i_out
        self.ilatch = c.create_net("ILATCH")
        self.ilatch.drive("ctrl", DriveState.LOW)  # idle low

        self.i_out = [c.create_net(f"I_OUT{i}") for i in range(8)]
        self.i_reg = c.add_component(IC74574("I",
            self.data_bus, self.i_out,
            self.ilatch, gnd))

        # === ARG register ===
        # Latches from I's outputs on ILATCH, always outputs to arg_out
        self.arg_out = [c.create_net(f"ARG_OUT{i}") for i in range(8)]
        self.arg_reg = c.add_component(IC74574("ARG",
            self.i_out, self.arg_out,
            self.ilatch, gnd))

        # ARG_DATA buffer: arg_out -> data bus, OE=ASSERT[7]
        c.add_component(IC74573("ARG_DATA",
            self.arg_out, self.data_bus, vcc, self.assert_out[7]))

        # ARG_ADDR buffer: arg_out -> offset GAL inputs, always on
        self.arg_addr_out = [c.create_net(f"ARG_ADDR{i}") for i in range(8)]
        c.add_component(IC74573("ARG_ADDR",
            self.arg_out, self.arg_addr_out, vcc, gnd))

        # === Address offset logic (3x GAL22V10) ===
        # OFFSET_CTRL: 0=passthrough, 1=add ARG, 2=add ARG+1
        self.offset_ctrl = [c.create_net(f"OFFSET_CTRL{i}") for i in range(2)]
        self.offset_ctrl[0].drive("ctrl", DriveState.LOW)
        self.offset_ctrl[1].drive("ctrl", DriveState.LOW)

        self.addr_bus = [c.create_net(f"ADDR{i}") for i in range(16)]
        carry4 = c.create_net("OFFSET_C4")
        carry8 = c.create_net("OFFSET_C8")

        # GAL_ADDLO: L[0..3] + ARG[0..3] + CTRL -> ADDR[0..3] + CARRY4
        c.add_component(GAL22V10("GAL_ADDLO",
            _load_pld("offset_lo.pld"), {
                "L0": self.l_out[0], "L1": self.l_out[1],
                "L2": self.l_out[2], "L3": self.l_out[3],
                "A0": self.arg_addr_out[0], "A1": self.arg_addr_out[1],
                "A2": self.arg_addr_out[2], "A3": self.arg_addr_out[3],
                "CTRL0": self.offset_ctrl[0], "CTRL1": self.offset_ctrl[1],
                "ADDR0": self.addr_bus[0], "ADDR1": self.addr_bus[1],
                "ADDR2": self.addr_bus[2], "ADDR3": self.addr_bus[3],
                "C4": carry4,
            }))

        # GAL_ADDHI: L[4..7] + ARG[4..7] + CTRL + CARRY4 -> ADDR[4..7] + CARRY8
        c.add_component(GAL22V10("GAL_ADDHI",
            _load_pld("offset_hi.pld"), {
                "L4": self.l_out[4], "L5": self.l_out[5],
                "L6": self.l_out[6], "L7": self.l_out[7],
                "A4": self.arg_addr_out[4], "A5": self.arg_addr_out[5],
                "A6": self.arg_addr_out[6], "A7": self.arg_addr_out[7],
                "CTRL0": self.offset_ctrl[0], "CTRL1": self.offset_ctrl[1],
                "C4IN": carry4,
                "ADDR4": self.addr_bus[4], "ADDR5": self.addr_bus[5],
                "ADDR6": self.addr_bus[6], "ADDR7": self.addr_bus[7],
                "C8": carry8,
            }))

        # GAL_INCH: H[0..7] + CARRY8 -> ADDR[8..15]
        c.add_component(GAL22V10("GAL_INCH",
            _load_pld("offset_h.pld"), {
                "H0": self.h_out[0], "H1": self.h_out[1],
                "H2": self.h_out[2], "H3": self.h_out[3],
                "H4": self.h_out[4], "H5": self.h_out[5],
                "H6": self.h_out[6], "H7": self.h_out[7],
                "C8IN": carry8,
                "ADDR8": self.addr_bus[8], "ADDR9": self.addr_bus[9],
                "ADDR10": self.addr_bus[10], "ADDR11": self.addr_bus[11],
                "ADDR12": self.addr_bus[12], "ADDR13": self.addr_bus[13],
                "ADDR14": self.addr_bus[14], "ADDR15": self.addr_bus[15],
            }))

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

    def read_arg(self):
        return self._read_nets(self.arg_out)

    def set_offset_ctrl(self, mode):
        """Set offset mode: 0=passthrough, 1=ARG, 2=ARG+1."""
        self.offset_ctrl[0].drive("ctrl",
            DriveState.HIGH if mode & 1 else DriveState.LOW)
        self.offset_ctrl[1].drive("ctrl",
            DriveState.HIGH if mode & 2 else DriveState.LOW)

    def _force_register(self, reg_574, value):
        """Force a '574 register's latched value. For testing only."""
        for i in range(len(reg_574._latched)):
            reg_574._latched[i] = Signal.HIGH if (value >> i) & 1 else Signal.LOW
