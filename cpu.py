import os

from circuit import (
    Signal, DriveState, Circuit, Net,
    LED, IC74573, IC74574, IC74138, IC40193, IC62256, IC28256,
    Inverter, GAL22V10,
)
from microcode import (
    ASSERT_TMP, ASSERT_ALU, ASSERT_MEM, ASSERT_PCH, ASSERT_PCL,
    ASSERT_SPH, ASSERT_SPL, ASSERT_ARG,
    LATCH_I_ARG, LATCH_A_B, LATCH_H, LATCH_L, LATCH_PCH, LATCH_PCL,
    LATCH_MEM_WE, LATCH_TMP,
    ALU_A, ALU_B, ALU_ADD, ALU_SUB, ALU_AND, ALU_OR, ALU_XOR, ALU_SHIFT,
    CTRL_NOP, CTRL_PC_INC, CTRL_SP_DEC, CTRL_SP_INC,
    OFFSET_NONE, OFFSET_ARG, OFFSET_ARG_PLUS1,
    COND_NEVER, COND_ALWAYS, COND_CS, COND_CC, COND_ZS, COND_ZC,
    COND_NS, COND_NC,
    OTHER_LDA_IMM, OTHER_PUSH_IMM, OTHER_BR, OTHER_JMP, OTHER_CALL,
    OTHER_RET, OTHER_LDASP, OTHER_STASP, OTHER_LDAB, OTHER_STAB,
    OTHER_POP, OTHER_PUSHM, OTHER_RDSP,
    UC_ASSERT, UC_LATCH, UC_ALU, UC_OFFSET, UC_CONTROL, UC_END, UC_FLAGS,
    microcode_word as _microcode_word,
    encode_instruction as _encode_instruction,
    check_condition as _check_condition,
    generate_microcode as _generate_microcode,
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

        # === Microcode data buses (created early — directly drive control lines) ===
        self.uc_lo_bus = [c.create_net(f"UC_LO{i}") for i in range(8)]
        self.uc_hi_bus = [c.create_net(f"UC_HI{i}") for i in range(8)]

        # Aliases: microcode ROM data pins ARE the control select lines
        # ASSERT demux select = uc_lo_bus[0:3]
        # LATCH demux select  = uc_lo_bus[3:6]
        # ALU_OP              = uc_lo_bus[6:8] + uc_hi_bus[0]
        # OFFSET_CTRL         = uc_hi_bus[1:2]
        # CONTROL demux       = uc_hi_bus[3:4]  (already wired below)
        # END                 = uc_hi_bus[5]
        # FLAGS_LATCH         = uc_hi_bus[6]
        self.assert_sel = self.uc_lo_bus[0:3]
        self.latch_sel = self.uc_lo_bus[3:6]
        self.alu_op = [self.uc_lo_bus[6], self.uc_lo_bus[7], self.uc_hi_bus[0]]
        self.offset_ctrl = [self.uc_hi_bus[1], self.uc_hi_bus[2]]

        # === ASSERT demux (74138) ===
        self.assert_enable = c.create_net("ASSERT_EN")
        assert_g2a = c.create_net("ASSERT_G2A")
        assert_g2b = c.create_net("ASSERT_G2B")
        assert_g2a.drive("rail", DriveState.LOW)
        assert_g2b.drive("rail", DriveState.LOW)
        self.assert_out = [c.create_net(f"ASSERT_Y{i}") for i in range(8)]
        c.add_component(IC74138("ASSERT",
            self.assert_sel[0], self.assert_sel[1], self.assert_sel[2],
            self.assert_enable, assert_g2a, assert_g2b, self.assert_out))

        # === LATCH demux (74138) ===
        self.latch_enable = c.create_net("LATCH_EN")
        latch_g2a = c.create_net("LATCH_G2A")
        latch_g2b = c.create_net("LATCH_G2B")
        latch_g2a.drive("rail", DriveState.LOW)
        latch_g2b.drive("rail", DriveState.LOW)
        self.latch_out = [c.create_net(f"LATCH_Y{i}") for i in range(8)]
        c.add_component(IC74138("LATCH",
            self.latch_sel[0], self.latch_sel[1], self.latch_sel[2],
            self.latch_enable, latch_g2a, latch_g2b, self.latch_out))

        # === TMP register ===
        self.tmp = c.add_component(IC74574("TMP",
            self.data_bus, self.data_bus,
            self.latch_out[7], self.assert_out[0]))

        # === A register ===
        self.a_out = [c.create_net(f"A_OUT{i}") for i in range(8)]
        self.a_reg = c.add_component(IC74574("A",
            self.data_bus, self.a_out,
            self.latch_out[1], gnd))

        # === B register ===
        self.b_out = [c.create_net(f"B_OUT{i}") for i in range(8)]
        self.b_reg = c.add_component(IC74574("B",
            self.a_out, self.b_out,
            self.latch_out[1], gnd))

        # === H and L registers ===
        self.h_out = [c.create_net(f"H_OUT{i}") for i in range(8)]
        self.l_out = [c.create_net(f"L_OUT{i}") for i in range(8)]
        self.h_reg = c.add_component(IC74574("H",
            self.data_bus, self.h_out,
            self.latch_out[2], gnd))
        self.l_reg = c.add_component(IC74574("L",
            self.data_bus, self.l_out,
            self.latch_out[3], gnd))

        # === I register (instruction) ===
        self.i_out = [c.create_net(f"I_OUT{i}") for i in range(8)]
        self.i_reg = c.add_component(IC74574("I",
            self.data_bus, self.i_out,
            self.latch_out[0], gnd))

        # === ARG register ===
        self.arg_out = [c.create_net(f"ARG_OUT{i}") for i in range(8)]
        self.arg_reg = c.add_component(IC74574("ARG",
            self.i_out, self.arg_out,
            self.latch_out[0], gnd))

        # ARG_DATA buffer: arg_out -> data bus, OE=ASSERT[7]
        c.add_component(IC74573("ARG_DATA",
            self.arg_out, self.data_bus, vcc, self.assert_out[7]))

        # ARG_ADDR buffer: arg_out -> offset GAL inputs, always on
        self.arg_addr_out = [c.create_net(f"ARG_ADDR{i}") for i in range(8)]
        c.add_component(IC74573("ARG_ADDR",
            self.arg_out, self.arg_addr_out, vcc, gnd))

        # === Address offset logic (3x GAL22V10) ===
        self.addr_bus = [c.create_net(f"ADDR{i}") for i in range(16)]
        carry4 = c.create_net("OFFSET_C4")
        carry8 = c.create_net("OFFSET_C8")

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
        self.pc_count_up.drive("ctrl", DriveState.HIGH)
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

        self._pcl1 = c.add_component(IC40193("PCL1",
            self.data_bus[0:4], self.pc_l_int[0:4],
            self.pc_count_up, self.pc_count_down,
            self.latch_out[5], self.pc_mr, pcl1_tcu, pcl1_tcd))
        self._pcl2 = c.add_component(IC40193("PCL2",
            self.data_bus[4:8], self.pc_l_int[4:8],
            pcl1_tcu, pcl1_tcd,
            self.latch_out[5], self.pc_mr, pcl2_tcu, pcl2_tcd))
        self._pch1 = c.add_component(IC40193("PCH1",
            self.data_bus[0:4], self.pc_h_int[0:4],
            pcl2_tcu, pcl2_tcd,
            self.latch_out[4], self.pc_mr, pch1_tcu, pch1_tcd))
        self._pch2 = c.add_component(IC40193("PCH2",
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

        self._spl1 = c.add_component(IC40193("SPL1",
            sp_dummy, self.sp_l_int[0:4],
            self.sp_count_up, self.sp_count_down,
            vcc, self.sp_mr, spl1_tcu, spl1_tcd))
        self._spl2 = c.add_component(IC40193("SPL2",
            sp_dummy, self.sp_l_int[4:8],
            spl1_tcu, spl1_tcd,
            vcc, self.sp_mr, spl2_tcu, spl2_tcd))
        self._sph1 = c.add_component(IC40193("SPH1",
            sp_dummy, self.sp_h_int[0:4],
            spl2_tcu, spl2_tcd,
            vcc, self.sp_mr, sph1_tcu, sph1_tcd))
        self._sph2 = c.add_component(IC40193("SPH2",
            sp_dummy, self.sp_h_int[4:8],
            sph1_tcu, sph1_tcd,
            vcc, self.sp_mr, sph2_tcu, sph2_tcd))

        # SP tri-state buffers to data bus
        c.add_component(IC74573("SPH_BUF",
            self.sp_h_int, self.data_bus, vcc, self.assert_out[5]))
        c.add_component(IC74573("SPL_BUF",
            self.sp_l_int, self.data_bus, vcc, self.assert_out[6]))

        # === ALU (5x GAL22V10 + 2x 74573 + 1x 74574) ===
        self.alu_r = [c.create_net(f"ALU_R{i}") for i in range(8)]
        self.alu_s = [c.create_net(f"ALU_S{i}") for i in range(8)]

        alu_c4 = c.create_net("ALU_C4")
        alu_c8 = c.create_net("ALU_C8")
        alu_zlo = c.create_net("ALU_ZLO")
        alu_zhi = c.create_net("ALU_ZHI")
        alu_szlo = c.create_net("ALU_SZLO")
        alu_szhi = c.create_net("ALU_SZHI")

        c.add_component(GAL22V10("GAL_ALU_LO",
            _load_pld("alu_lo.pld"), {
                "A0": self.a_out[0], "A1": self.a_out[1],
                "A2": self.a_out[2], "A3": self.a_out[3],
                "B0": self.b_out[0], "B1": self.b_out[1],
                "B2": self.b_out[2], "B3": self.b_out[3],
                "OP0": self.alu_op[0], "OP1": self.alu_op[1],
                "OP2": self.alu_op[2],
                "R0": self.alu_r[0], "R1": self.alu_r[1],
                "R2": self.alu_r[2], "R3": self.alu_r[3],
                "C4": alu_c4, "ZLO": alu_zlo,
            }))

        c.add_component(GAL22V10("GAL_ALU_HI",
            _load_pld("alu_hi.pld"), {
                "C4IN": alu_c4,
                "A4": self.a_out[4], "A5": self.a_out[5],
                "A6": self.a_out[6], "A7": self.a_out[7],
                "B4": self.b_out[4], "B5": self.b_out[5],
                "B6": self.b_out[6], "B7": self.b_out[7],
                "OP0": self.alu_op[0], "OP1": self.alu_op[1],
                "OP2": self.alu_op[2],
                "R4": self.alu_r[4], "R5": self.alu_r[5],
                "R6": self.alu_r[6], "R7": self.alu_r[7],
                "C8": alu_c8, "ZHI": alu_zhi,
            }))

        c.add_component(GAL22V10("GAL_SHIFT_LO",
            _load_pld("shift_lo.pld"), {
                "A0": self.a_out[0], "A1": self.a_out[1],
                "A2": self.a_out[2], "A3": self.a_out[3],
                "A4": self.a_out[4], "A5": self.a_out[5],
                "A6": self.a_out[6], "A7": self.a_out[7],
                "AMT0": self.b_out[0], "AMT1": self.b_out[1],
                "AMT2": self.b_out[2], "DIR": self.b_out[3],
                "S0": self.alu_s[0], "S1": self.alu_s[1],
                "S2": self.alu_s[2], "S3": self.alu_s[3],
                "SZLO": alu_szlo,
            }))

        c.add_component(GAL22V10("GAL_SHIFT_HI",
            _load_pld("shift_hi.pld"), {
                "A0": self.a_out[0], "A1": self.a_out[1],
                "A2": self.a_out[2], "A3": self.a_out[3],
                "A4": self.a_out[4], "A5": self.a_out[5],
                "A6": self.a_out[6], "A7": self.a_out[7],
                "AMT0": self.b_out[0], "AMT1": self.b_out[1],
                "AMT2": self.b_out[2], "DIR": self.b_out[3],
                "S4": self.alu_s[4], "S5": self.alu_s[5],
                "S6": self.alu_s[6], "S7": self.alu_s[7],
                "SZHI": alu_szhi,
            }))

        alu_arith_oe = c.create_net("ALU_ARITH_OE")
        alu_shift_oe = c.create_net("ALU_SHIFT_OE")
        self.flag_z = c.create_net("FLAG_Z")
        self.flag_n = c.create_net("FLAG_N")
        self.flag_c = c.create_net("FLAG_C")

        c.add_component(GAL22V10("GAL_ALU_FLAGS",
            _load_pld("alu_flags.pld"), {
                "OP0": self.alu_op[0], "OP1": self.alu_op[1],
                "OP2": self.alu_op[2],
                "ASEN": self.assert_out[1],
                "C8": alu_c8,
                "ZLO": alu_zlo, "ZHI": alu_zhi,
                "SZLO": alu_szlo, "SZHI": alu_szhi,
                "R7": self.alu_r[7], "S7": self.alu_s[7],
                "ALU_OE": alu_arith_oe,
                "SH_OE": alu_shift_oe,
                "FZ": self.flag_z, "FN": self.flag_n, "FC": self.flag_c,
            }))

        c.add_component(IC74573("ALU_BUF",
            self.alu_r, self.data_bus, vcc, alu_arith_oe))
        c.add_component(IC74573("SHIFT_BUF",
            self.alu_s, self.data_bus, vcc, alu_shift_oe))

        # Flag register (74574)
        self.flag_latch = c.create_net("FLAG_LATCH")
        flag_inputs = [self.flag_z, self.flag_n, self.flag_c,
                       gnd, gnd, gnd, gnd, gnd]
        self.flag_out = [c.create_net(f"FLAG_OUT{i}") for i in range(8)]
        self.flag_reg = c.add_component(IC74574("FLAGS",
            flag_inputs, self.flag_out,
            self.flag_latch, gnd))

        # === Microcode (1x 40193 + 2x 28256 + 1x 74138) ===
        self.clk = c.create_net("CLK")

        self.micro_clk = c.create_net("MICRO_CLK")
        micro_cpd = c.create_net("MICRO_CPD")
        micro_cpd.drive("rail", DriveState.HIGH)
        micro_pl = c.create_net("MICRO_PL")
        micro_pl.drive("rail", DriveState.HIGH)
        self.micro_mr = c.create_net("MICRO_MR")
        self.upc_out = [c.create_net(f"UPC{i}") for i in range(4)]
        micro_tcu = c.create_net("MICRO_TCU")
        micro_tcd = c.create_net("MICRO_TCD")
        micro_dummy = [c.create_net(f"MICRO_D{i}") for i in range(4)]
        for d in micro_dummy:
            d.drive("rail", DriveState.LOW)
        c.add_component(IC40193("UPC",
            micro_dummy, self.upc_out,
            self.micro_clk, micro_cpd,
            micro_pl, self.micro_mr, micro_tcu, micro_tcd))

        uc_addr = (self.upc_out +
                   self.i_out +
                   self.flag_out[0:3])

        # Two 28256 ROMs for 16-bit microcode word
        # Data outputs directly drive control lines (no Python intermediary)
        self.ucode_lo = c.add_component(IC28256("UCODE_LO",
            uc_addr, self.uc_lo_bus, gnd, gnd))
        self.ucode_hi = c.add_component(IC28256("UCODE_HI",
            uc_addr, self.uc_hi_bus, gnd, gnd))

        # CONTROL demux: select from uc_hi_bus[3:4], gated by CLK
        ctrl_c = c.create_net("CTRL_DEMUX_C")
        ctrl_c.drive("rail", DriveState.LOW)
        ctrl_g2a = c.create_net("CTRL_G2A")
        ctrl_g2a.drive("rail", DriveState.LOW)
        ctrl_g2b = c.create_net("CTRL_G2B")
        ctrl_g2b.drive("rail", DriveState.LOW)
        ctrl_y0 = c.create_net("CTRL_Y0")
        ctrl_unused = [c.create_net(f"CTRL_Y{i}") for i in range(4, 8)]
        self.ctrl_out = [ctrl_y0, self.pc_count_up, self.sp_count_down,
                         self.sp_count_up] + ctrl_unused
        c.add_component(IC74138("CONTROL",
            self.uc_hi_bus[3], self.uc_hi_bus[4], ctrl_c,
            self.clk, ctrl_g2a, ctrl_g2b, self.ctrl_out))

        # CONTROL demux is the sole driver for PC/SP count signals
        self.pc_count_up.drive("ctrl", DriveState.HI_Z)
        self.sp_count_down.drive("ctrl", DriveState.HI_Z)
        self.sp_count_up.drive("ctrl", DriveState.HI_Z)

        # === Phase clock generator ===
        # 1x 40193 counter (states 0-7), 1x 74573 latch (captures END and
        # FLAGS_LATCH at state 0), 1x GAL22V10 decoder (produces 6 control
        # signals from latched inputs).  Q3 feeds back to MR for auto-reset.

        # Phase counter
        self.step_clk = c.create_net("STEP_CLK")
        self.step_clk.drive("oscillator", DriveState.LOW)
        phase_cpd = c.create_net("PHASE_CPD")
        phase_cpd.drive("rail", DriveState.HIGH)
        phase_pl = c.create_net("PHASE_PL")
        phase_pl.drive("rail", DriveState.HIGH)
        phase_d = [c.create_net(f"PHASE_D{i}") for i in range(4)]
        for d in phase_d:
            d.drive("rail", DriveState.LOW)
        self.phase_q = [c.create_net(f"PHASE_Q{i}") for i in range(4)]
        phase_tcu = c.create_net("PHASE_TCU")
        phase_tcd = c.create_net("PHASE_TCD")
        # Q3 connects to MR: counter auto-resets when it reaches 8
        c.add_component(IC40193("PHASE_CTR",
            phase_d, self.phase_q,
            self.step_clk, phase_cpd,
            phase_pl, self.phase_q[3],  # MR = Q3
            phase_tcu, phase_tcd))

        # Latch for END and FLAGS_LATCH bits from microcode ROM.
        # Transparent at state 0 (IDLE), holds during states 1-7.
        # This prevents feedback: MICRO_MR resetting the microPC would
        # change ROM output mid-cycle without this isolation latch.
        phase_le = c.create_net("PHASE_LE")
        latch_end = c.create_net("LATCH_END")
        latch_fl = c.create_net("LATCH_FL")
        phase_latch_in = [self.uc_hi_bus[5], self.uc_hi_bus[6]] + \
            [gnd, gnd, gnd, gnd, gnd, gnd]
        phase_latch_out = [latch_end, latch_fl] + \
            [c.create_net(f"PHLATCH_U{i}") for i in range(6)]
        c.add_component(IC74573("PHASE_LATCH",
            phase_latch_in, phase_latch_out, phase_le, gnd))

        # Phase decoder GAL: reads latched END/FL + counter state
        c.add_component(GAL22V10("PHASE_DECODE",
            _load_pld("phase_decode.pld"), {
            "P0": self.phase_q[0],
            "P1": self.phase_q[1],
            "P2": self.phase_q[2],
            "FL": latch_fl,               # latched FLAGS_LATCH
            "END": latch_end,             # latched END
            "CLK_OUT": self.clk,
            "ASSR_EN": self.assert_enable,
            "LTCH_EN": self.latch_enable,
            "FLG_LT": self.flag_latch,
            "MCK": self.micro_clk,
            "MMR": self.micro_mr,
            "PH_LE": phase_le,
        }))

        # === Initialization: reset all counters ===
        c.settle()
        # PC and SP reset via their own MR nets
        self.pc_mr.drive("ctrl", DriveState.LOW)
        self.sp_mr.drive("ctrl", DriveState.LOW)
        c.settle()

    # --- Re-exported constants for backward compatibility ---
    ASSERT_TMP = ASSERT_TMP
    ASSERT_ALU = ASSERT_ALU
    ASSERT_MEM = ASSERT_MEM
    ASSERT_PCH = ASSERT_PCH
    ASSERT_PCL = ASSERT_PCL
    ASSERT_SPH = ASSERT_SPH
    ASSERT_SPL = ASSERT_SPL
    ASSERT_ARG = ASSERT_ARG

    LATCH_I_ARG = LATCH_I_ARG
    LATCH_A_B = LATCH_A_B
    LATCH_H = LATCH_H
    LATCH_L = LATCH_L
    LATCH_PCH = LATCH_PCH
    LATCH_PCL = LATCH_PCL
    LATCH_MEM_WE = LATCH_MEM_WE
    LATCH_TMP = LATCH_TMP

    ALU_A = ALU_A
    ALU_B = ALU_B
    ALU_ADD = ALU_ADD
    ALU_SUB = ALU_SUB
    ALU_AND = ALU_AND
    ALU_OR = ALU_OR
    ALU_XOR = ALU_XOR
    ALU_SHIFT = ALU_SHIFT

    CTRL_NOP = CTRL_NOP
    CTRL_PC_INC = CTRL_PC_INC
    CTRL_SP_DEC = CTRL_SP_DEC
    CTRL_SP_INC = CTRL_SP_INC

    OFFSET_NONE = OFFSET_NONE
    OFFSET_ARG = OFFSET_ARG
    OFFSET_ARG_PLUS1 = OFFSET_ARG_PLUS1

    COND_NEVER = COND_NEVER
    COND_ALWAYS = COND_ALWAYS
    COND_CS = COND_CS
    COND_CC = COND_CC
    COND_ZS = COND_ZS
    COND_ZC = COND_ZC
    COND_NS = COND_NS
    COND_NC = COND_NC

    UC_ASSERT = UC_ASSERT
    UC_LATCH = UC_LATCH
    UC_ALU = UC_ALU
    UC_OFFSET = UC_OFFSET
    UC_CONTROL = UC_CONTROL
    UC_END = UC_END
    UC_FLAGS = UC_FLAGS

    OTHER_LDA_IMM = OTHER_LDA_IMM
    OTHER_PUSH_IMM = OTHER_PUSH_IMM
    OTHER_BR = OTHER_BR
    OTHER_JMP = OTHER_JMP
    OTHER_CALL = OTHER_CALL
    OTHER_RET = OTHER_RET
    OTHER_LDASP = OTHER_LDASP
    OTHER_STASP = OTHER_STASP
    OTHER_LDAB = OTHER_LDAB
    OTHER_STAB = OTHER_STAB
    OTHER_POP = OTHER_POP
    OTHER_PUSHM = OTHER_PUSHM
    OTHER_RDSP = OTHER_RDSP

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

    def read_ram(self, addr):
        """Read a byte from RAM directly (for testing)."""
        return self.ram._memory[addr]

    def _read_register(self, reg_574):
        """Read a 74574 register's latched value directly (for testing)."""
        val = 0
        for i in range(8):
            if reg_574._latched[i] == Signal.HIGH:
                val |= (1 << i)
        return val

    def _current_uc_addr(self):
        """Compute current microcode ROM address from microPC + I + flags."""
        upc = self.read_upc()
        i_val = self.read_i()
        z, n, c = self.read_flags()
        flags = (1 if z else 0) | ((1 if n else 0) << 1) | ((1 if c else 0) << 2)
        return upc | (i_val << 4) | (flags << 12)

    def set_alu_op(self, op):
        """Set ALU operation by patching microcode ROM at current address (for testing)."""
        addr = self._current_uc_addr()
        lo = self.ucode_lo._memory[addr]
        hi = self.ucode_hi._memory[addr]
        # ALU_OP = bits 6-8: lo bits 6-7, hi bit 0
        lo = (lo & 0x3F) | ((op & 3) << 6)
        hi = (hi & 0xFE) | ((op >> 2) & 1)
        self.ucode_lo._memory[addr] = lo
        self.ucode_hi._memory[addr] = hi
        self.settle()

    def set_offset_ctrl(self, mode):
        """Set offset mode by patching microcode ROM at current address (for testing)."""
        addr = self._current_uc_addr()
        hi = self.ucode_hi._memory[addr]
        # OFFSET = bits 9-10: hi bits 1-2
        hi = (hi & 0xF9) | ((mode & 3) << 1)
        self.ucode_hi._memory[addr] = hi
        self.settle()

    def read_flags(self):
        """Return (zero, negative, carry) from latched flag register."""
        z = self.flag_out[0].value == Signal.HIGH
        n = self.flag_out[1].value == Signal.HIGH
        c = self.flag_out[2].value == Signal.HIGH
        return z, n, c

    def pulse_flag_latch(self):
        """Latch current ALU flags into the flag register (for testing).

        Reads the combinational flag outputs from the ALU GALs and forces
        them into the flag register directly, bypassing the flag_latch net
        (which is driven by the phase clock generator during normal operation).
        """
        z = self.flag_z.resolve() == Signal.HIGH
        n = self.flag_n.resolve() == Signal.HIGH
        c = self.flag_c.resolve() == Signal.HIGH
        val = (1 if z else 0) | ((1 if n else 0) << 1) | ((1 if c else 0) << 2)
        self._force_register(self.flag_reg, val)
        self.settle()

    def read_upc(self):
        """Read the current microPC value."""
        return self._read_nets(self.upc_out)

    def _read_uc_word(self):
        """Read the current 16-bit microcode word from the uc bus nets."""
        lo = self._read_nets(self.uc_lo_bus)
        hi = self._read_nets(self.uc_hi_bus)
        return lo | (hi << 8)

    @staticmethod
    def microcode_word(assert_sel=0, latch_sel=0, alu_op=0, offset=0,
                       control=0, end=False, flags_latch=False):
        return _microcode_word(assert_sel=assert_sel, latch_sel=latch_sel,
                               alu_op=alu_op, offset=offset, control=control,
                               end=end, flags_latch=flags_latch)

    def load_microcode(self, instruction, step, word, flags=None):
        """Load a microcode word for a given instruction and step."""
        if flags is None:
            flag_range = range(8)
        else:
            flag_range = [flags]
        lo_byte = word & 0xFF
        hi_byte = (word >> 8) & 0xFF
        for f in flag_range:
            addr = step | (instruction << 4) | (f << 12)
            self.ucode_lo.load(addr, [lo_byte])
            self.ucode_hi.load(addr, [hi_byte])

    def tick(self):
        """Execute one microcode step by pulsing the phase clock 8 times.

        The phase counter (40193) counts 0-7 and auto-resets via Q3→MR.
        The phase decoder GAL translates each state into control signals.
        This method is analogous to a fast oscillator driving the counter.
        """
        self.settle()  # Phase 0: counter=0, ROM outputs settle
        for _ in range(8):
            self.step_clk.drive("oscillator", DriveState.LOW)
            self.settle()
            self.step_clk.drive("oscillator", DriveState.HIGH)
            self.settle()
        # Counter has wrapped back to 0 (IDLE)

    def _force_register(self, reg_574, value):
        """Force a '574 register's latched value. For testing only."""
        for i in range(len(reg_574._latched)):
            reg_574._latched[i] = Signal.HIGH if (value >> i) & 1 else Signal.LOW

    def _force_pc(self, value):
        """Force the program counter to a 16-bit value. For testing only."""
        self._pcl1._count = value & 0xF
        self._pcl2._count = (value >> 4) & 0xF
        self._pch1._count = (value >> 8) & 0xF
        self._pch2._count = (value >> 12) & 0xF

    def _force_sp(self, value):
        """Force the stack pointer to a 16-bit value. For testing only."""
        self._spl1._count = value & 0xF
        self._spl2._count = (value >> 4) & 0xF
        self._sph1._count = (value >> 8) & 0xF
        self._sph2._count = (value >> 12) & 0xF

    def run_instruction(self):
        """Run ticks until END resets microPC to 0."""
        while True:
            self.tick()
            if self.read_upc() == 0:
                break

    @staticmethod
    def _check_condition(cond, z, n, c):
        return _check_condition(cond, z, n, c)

    @staticmethod
    def encode_instruction(cond, is_alu, alu_op=0, push=True, other_op=0):
        return _encode_instruction(cond, is_alu, alu_op=alu_op, push=push,
                                   other_op=other_op)

    def generate_microcode(self):
        """Generate and load all microcode into the EEPROMs."""
        lo, hi = _generate_microcode()
        self.ucode_lo._memory[:] = lo
        self.ucode_hi._memory[:] = hi
