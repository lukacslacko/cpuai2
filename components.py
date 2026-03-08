"""Discrete logic IC component models for circuit simulation."""

from circuit import Signal, DriveState, Component


class LED(Component):
    def __init__(self, name, net):
        self.name = name
        self.net = net
        self.is_on = False

    def pins(self):
        return {"A": self.net}

    def update(self):
        self.is_on = self.net.resolve() == Signal.HIGH


class Switch(Component):
    """A switch that drives a net when closed (default: drives LOW, modeling a ground switch)."""

    def __init__(self, name, net, drive_value=DriveState.LOW):
        self.name = name
        self.net = net
        self.drive_value = drive_value
        self._closed = False
        self._driver_id = f"switch_{name}"

    @property
    def closed(self):
        return self._closed

    @closed.setter
    def closed(self, value):
        self._closed = value
        if value:
            self.net.drive(self._driver_id, self.drive_value)
        else:
            self.net.drive(self._driver_id, DriveState.HI_Z)

    def pins(self):
        return {"COM": self.net}

    def update(self):
        pass


class Inverter(Component):
    """Single inverter gate. Output is the logical inverse of input."""

    def __init__(self, name, input_net, output_net):
        self.name = name
        self.input_net = input_net
        self.output_net = output_net
        self._driver_id = f"inv_{name}"

    def pins(self):
        return {"IN": self.input_net, "OUT": self.output_net}

    def update(self):
        val = self.input_net.resolve()
        if val == Signal.HIGH:
            self.output_net.drive(self._driver_id, DriveState.LOW)
        else:
            self.output_net.drive(self._driver_id, DriveState.HIGH)


class PldProgram:
    """Parser and evaluator for WinCUPL PLD source code (combinational only)."""

    _HEADER_KEYWORDS = {
        'NAME', 'PARTNO', 'DATE', 'REVISION', 'DESIGNER',
        'COMPANY', 'ASSEMBLY', 'LOCATION', 'DEVICE',
    }

    def __init__(self, source):
        self.pins = {}        # pin_number -> name
        self.equations = {}   # name -> AST node
        self._parse(source)

    def _parse(self, source):
        import re
        # Strip block comments
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
        for stmt in source.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
            # PIN declaration: PIN 2 = L0
            m = re.match(r'PIN\s+(\d+)\s*=\s*(\w+)', stmt, re.I)
            if m:
                self.pins[int(m.group(1))] = m.group(2)
                continue
            # Skip header keywords (Name OFFSET_LO, Device g22v10, etc.)
            first_word = stmt.split()[0].upper() if stmt.split() else ''
            if first_word in self._HEADER_KEYWORDS:
                continue
            # Equation: NAME = expr
            if '=' in stmt:
                lhs, rhs = stmt.split('=', 1)
                name = lhs.strip()
                if name:
                    self.equations[name] = self._parse_expr(rhs.strip())

    # --- Tokenizer ---
    def _tokenize(self, s):
        tokens = []
        i = 0
        while i < len(s):
            if s[i].isspace():
                i += 1
            elif s[i] in '&#$!()':
                tokens.append(s[i])
                i += 1
            elif s[i].isalnum() or s[i] == '_':
                j = i
                while j < len(s) and (s[j].isalnum() or s[j] == '_'):
                    j += 1
                tokens.append(s[i:j])
                i = j
            else:
                i += 1
        return tokens

    # --- Recursive descent parser ---
    # Precedence (low to high): # (OR), $ (XOR), & (AND), ! (NOT)
    def _parse_expr(self, expr_str):
        tokens = self._tokenize(expr_str)
        pos = [0]
        result = self._parse_or(tokens, pos)
        return result

    def _parse_or(self, tokens, pos):
        left = self._parse_xor(tokens, pos)
        while pos[0] < len(tokens) and tokens[pos[0]] == '#':
            pos[0] += 1
            right = self._parse_xor(tokens, pos)
            left = ('or', left, right)
        return left

    def _parse_xor(self, tokens, pos):
        left = self._parse_and(tokens, pos)
        while pos[0] < len(tokens) and tokens[pos[0]] == '$':
            pos[0] += 1
            right = self._parse_and(tokens, pos)
            left = ('xor', left, right)
        return left

    def _parse_and(self, tokens, pos):
        left = self._parse_not(tokens, pos)
        while pos[0] < len(tokens) and tokens[pos[0]] == '&':
            pos[0] += 1
            right = self._parse_not(tokens, pos)
            left = ('and', left, right)
        return left

    def _parse_not(self, tokens, pos):
        if pos[0] < len(tokens) and tokens[pos[0]] == '!':
            pos[0] += 1
            operand = self._parse_not(tokens, pos)
            return ('not', operand)
        return self._parse_atom(tokens, pos)

    def _parse_atom(self, tokens, pos):
        if pos[0] < len(tokens) and tokens[pos[0]] == '(':
            pos[0] += 1
            result = self._parse_or(tokens, pos)
            if pos[0] < len(tokens) and tokens[pos[0]] == ')':
                pos[0] += 1
            return result
        if pos[0] < len(tokens):
            name = tokens[pos[0]]
            pos[0] += 1
            return ('var', name)
        return ('var', '_ZERO')

    # --- Evaluator ---
    def evaluate(self, name, env):
        """Evaluate a variable by name, resolving intermediate equations as needed."""
        if name in env:
            return env[name]
        if name in self.equations:
            result = self._eval_node(self.equations[name], env)
            env[name] = result
            return result
        return False

    def _eval_node(self, node, env):
        op = node[0]
        if op == 'var':
            return self.evaluate(node[1], env)
        elif op == 'not':
            return not self._eval_node(node[1], env)
        elif op == 'and':
            return self._eval_node(node[1], env) and self._eval_node(node[2], env)
        elif op == 'or':
            return self._eval_node(node[1], env) or self._eval_node(node[2], env)
        elif op == 'xor':
            return self._eval_node(node[1], env) != self._eval_node(node[2], env)
        return False

    def get_output_names(self):
        """Pin names that have equations (outputs)."""
        pin_names = set(self.pins.values())
        return [n for n in pin_names if n in self.equations]

    def get_input_names(self):
        """Pin names without equations (inputs)."""
        pin_names = set(self.pins.values())
        return [n for n in pin_names if n not in self.equations]


class GAL22V10(Component):
    """GAL22V10 PLD - combinational logic only (no registered outputs).

    Takes WinCUPL PLD source code and a pin_map dict mapping PLD pin names
    to Net objects. The PLD equations are parsed and evaluated each cycle.
    """

    def __init__(self, name, pld_source, pin_map):
        self.name = name
        self._program = PldProgram(pld_source)
        self._pin_map = pin_map
        self._input_names = self._program.get_input_names()
        self._output_names = self._program.get_output_names()
        self._driver_ids = {n: f"{name}_{n}" for n in self._output_names}

    def pins(self):
        return dict(self._pin_map)

    def update(self):
        env = {}
        for pin_name in self._input_names:
            net = self._pin_map[pin_name]
            env[pin_name] = net.resolve() == Signal.HIGH

        for pin_name in self._output_names:
            val = self._program.evaluate(pin_name, env)
            net = self._pin_map[pin_name]
            net.drive(
                self._driver_ids[pin_name],
                DriveState.HIGH if val else DriveState.LOW
            )


class IC74573(Component):
    """74573 - 8-bit transparent latch.

    When LE is HIGH, outputs follow inputs (transparent).
    When LE is LOW, outputs hold the last latched value.
    OE active low: LOW = outputs driven, HIGH = outputs hi-z.
    """

    def __init__(self, name, inputs, outputs, le_net, oe_net):
        self.name = name
        self.inputs = inputs
        self.outputs = outputs
        self.le_net = le_net
        self.oe_net = oe_net
        self._latched = [Signal.LOW] * 8
        self._driver_ids = [f"{name}_Q{i}" for i in range(8)]

    def pins(self):
        p = {}
        for i, net in enumerate(self.inputs):
            p[f"D{i}"] = net
        for i, net in enumerate(self.outputs):
            p[f"Q{i}"] = net
        p["LE"] = self.le_net
        p["OE"] = self.oe_net
        return p

    def pre_update(self):
        le = self.le_net.resolve()
        if le == Signal.HIGH:
            self._latched = [net.resolve() for net in self.inputs]

    def update(self):
        oe = self.oe_net.resolve()
        if oe == Signal.LOW:
            for i, net in enumerate(self.outputs):
                drive = DriveState.HIGH if self._latched[i] == Signal.HIGH else DriveState.LOW
                net.drive(self._driver_ids[i], drive)
        else:
            for i, net in enumerate(self.outputs):
                net.drive(self._driver_ids[i], DriveState.HI_Z)


class IC74574(Component):
    """74574 - 8-bit edge-triggered D flip-flop.

    On rising edge of CLK, inputs are latched to outputs.
    OE active low: LOW = outputs driven, HIGH = outputs hi-z.
    """

    def __init__(self, name, inputs, outputs, clk_net, oe_net):
        self.name = name
        self.inputs = inputs
        self.outputs = outputs
        self.clk_net = clk_net
        self.oe_net = oe_net
        self._latched = [Signal.LOW] * 8
        self._prev_clk = Signal.LOW
        self._driver_ids = [f"{name}_Q{i}" for i in range(8)]

    def pins(self):
        p = {}
        for i, net in enumerate(self.inputs):
            p[f"D{i}"] = net
        for i, net in enumerate(self.outputs):
            p[f"Q{i}"] = net
        p["CLK"] = self.clk_net
        p["OE"] = self.oe_net
        return p

    def pre_update(self):
        clk = self.clk_net.resolve()
        if self._prev_clk == Signal.LOW and clk == Signal.HIGH:
            self._latched = [net.resolve() for net in self.inputs]
        self._prev_clk = clk

    def update(self):
        oe = self.oe_net.resolve()
        if oe == Signal.LOW:
            for i, net in enumerate(self.outputs):
                drive = DriveState.HIGH if self._latched[i] == Signal.HIGH else DriveState.LOW
                net.drive(self._driver_ids[i], drive)
        else:
            for i, net in enumerate(self.outputs):
                net.drive(self._driver_ids[i], DriveState.HI_Z)


class IC74138(Component):
    """74138 - 3-to-8 line decoder/demultiplexer.

    Select inputs: A, B, C (A is LSB).
    Enable inputs: G1 (active high), G2A (active low), G2B (active low).
    Outputs: Y0-Y7 (active low) - selected output is LOW, all others HIGH.
    When disabled (G1 LOW or G2A HIGH or G2B HIGH), all outputs HIGH.
    """

    def __init__(self, name, a_net, b_net, c_net, g1_net, g2a_net, g2b_net, outputs):
        self.name = name
        self.a_net = a_net
        self.b_net = b_net
        self.c_net = c_net
        self.g1_net = g1_net
        self.g2a_net = g2a_net
        self.g2b_net = g2b_net
        self.outputs = outputs  # 8 nets
        self._driver_ids = [f"{name}_Y{i}" for i in range(8)]

    def pins(self):
        p = {"A": self.a_net, "B": self.b_net, "C": self.c_net,
             "G1": self.g1_net, "G2A": self.g2a_net, "G2B": self.g2b_net}
        for i, net in enumerate(self.outputs):
            p[f"Y{i}"] = net
        return p

    def update(self):
        g1 = self.g1_net.resolve()
        g2a = self.g2a_net.resolve()
        g2b = self.g2b_net.resolve()
        enabled = (g1 == Signal.HIGH and g2a == Signal.LOW and g2b == Signal.LOW)

        if enabled:
            a = 1 if self.a_net.resolve() == Signal.HIGH else 0
            b = 1 if self.b_net.resolve() == Signal.HIGH else 0
            c = 1 if self.c_net.resolve() == Signal.HIGH else 0
            selected = a | (b << 1) | (c << 2)
        else:
            selected = -1

        for i in range(8):
            if i == selected:
                self.outputs[i].drive(self._driver_ids[i], DriveState.LOW)
            else:
                self.outputs[i].drive(self._driver_ids[i], DriveState.HIGH)


class IC40193(Component):
    """40193 - 4-bit presettable binary up/down counter.

    CPU: count up on rising edge (CPD must be HIGH).
    CPD: count down on rising edge (CPU must be HIGH).
    PL (active low): asynchronous parallel load from D0-D3.
    MR (active high): asynchronous master reset (outputs to 0).
    TCU (active low): LOW when count is 15 and CPU is LOW.
    TCD (active low): LOW when count is 0 and CPD is LOW.
    """

    def __init__(self, name, data_inputs, outputs, cpu_net, cpd_net,
                 pl_net, mr_net, tcu_net, tcd_net):
        self.name = name
        self.data_inputs = data_inputs  # 4 nets
        self.outputs = outputs  # 4 nets
        self.cpu_net = cpu_net
        self.cpd_net = cpd_net
        self.pl_net = pl_net
        self.mr_net = mr_net
        self.tcu_net = tcu_net
        self.tcd_net = tcd_net
        self._count = 0
        self._prev_cpu = Signal.LOW
        self._prev_cpd = Signal.LOW
        self._driver_ids = [f"{name}_Q{i}" for i in range(4)]
        self._tcu_driver = f"{name}_TCU"
        self._tcd_driver = f"{name}_TCD"

    def pins(self):
        p = {}
        for i, net in enumerate(self.data_inputs):
            p[f"D{i}"] = net
        for i, net in enumerate(self.outputs):
            p[f"Q{i}"] = net
        p["CPU"] = self.cpu_net
        p["CPD"] = self.cpd_net
        p["PL"] = self.pl_net
        p["MR"] = self.mr_net
        p["TCU"] = self.tcu_net
        p["TCD"] = self.tcd_net
        return p

    def pre_update(self):
        mr = self.mr_net.resolve()
        pl = self.pl_net.resolve()
        cpu = self.cpu_net.resolve()
        cpd = self.cpd_net.resolve()

        if mr == Signal.HIGH:
            self._count = 0
        elif pl == Signal.LOW:
            val = 0
            for i in range(4):
                if self.data_inputs[i].resolve() == Signal.HIGH:
                    val |= (1 << i)
            self._count = val
        else:
            if self._prev_cpu == Signal.LOW and cpu == Signal.HIGH and cpd == Signal.HIGH:
                self._count = (self._count + 1) & 0xF
            elif self._prev_cpd == Signal.LOW and cpd == Signal.HIGH and cpu == Signal.HIGH:
                self._count = (self._count - 1) & 0xF

        self._prev_cpu = cpu
        self._prev_cpd = cpd

    def update(self):
        for i in range(4):
            bit = (self._count >> i) & 1
            self.outputs[i].drive(
                self._driver_ids[i],
                DriveState.HIGH if bit else DriveState.LOW
            )

        cpu = self.cpu_net.resolve()
        cpd = self.cpd_net.resolve()

        # TCU: LOW when count==15 and CPU is LOW
        if self._count == 15 and cpu == Signal.LOW:
            self.tcu_net.drive(self._tcu_driver, DriveState.LOW)
        else:
            self.tcu_net.drive(self._tcu_driver, DriveState.HIGH)

        # TCD: LOW when count==0 and CPD is LOW
        if self._count == 0 and cpd == Signal.LOW:
            self.tcd_net.drive(self._tcd_driver, DriveState.LOW)
        else:
            self.tcd_net.drive(self._tcd_driver, DriveState.HIGH)


class IC62256(Component):
    """62256 - 32KB static RAM.

    15 address lines (A0-A14), 8 bidirectional data lines (D0-D7).
    CE (active low): chip enable.
    OE (active low): output enable (drives data bus on read).
    WE (active low): write enable (latches data bus into memory).
    Read: CE=LOW, OE=LOW, WE=HIGH -> data driven onto bus.
    Write: CE=LOW, WE=LOW -> data read from bus into memory.
    """

    def __init__(self, name, address_lines, data_lines, ce_net, oe_net, we_net):
        self.name = name
        self.address_lines = address_lines  # 15 nets
        self.data_lines = data_lines  # 8 nets (bidirectional)
        self.ce_net = ce_net
        self.oe_net = oe_net
        self.we_net = we_net
        self._memory = bytearray(32768)
        self._driver_ids = [f"{name}_D{i}" for i in range(8)]

    def pins(self):
        p = {}
        for i, net in enumerate(self.address_lines):
            p[f"A{i}"] = net
        for i, net in enumerate(self.data_lines):
            p[f"D{i}"] = net
        p["CE"] = self.ce_net
        p["OE"] = self.oe_net
        p["WE"] = self.we_net
        return p

    def _read_address(self):
        addr = 0
        for i in range(15):
            if self.address_lines[i].resolve() == Signal.HIGH:
                addr |= (1 << i)
        return addr

    def pre_update(self):
        ce = self.ce_net.resolve()
        we = self.we_net.resolve()
        if ce == Signal.LOW and we == Signal.LOW:
            addr = self._read_address()
            val = 0
            for i in range(8):
                if self.data_lines[i].resolve() == Signal.HIGH:
                    val |= (1 << i)
            self._memory[addr] = val

    def update(self):
        ce = self.ce_net.resolve()
        oe = self.oe_net.resolve()
        we = self.we_net.resolve()
        if ce == Signal.LOW and oe == Signal.LOW and we == Signal.HIGH:
            addr = self._read_address()
            val = self._memory[addr]
            for i in range(8):
                bit = (val >> i) & 1
                self.data_lines[i].drive(
                    self._driver_ids[i],
                    DriveState.HIGH if bit else DriveState.LOW
                )
        else:
            for i in range(8):
                self.data_lines[i].drive(self._driver_ids[i], DriveState.HI_Z)


class IC28256(Component):
    """28256 - 32KB EEPROM (modeled as ROM).

    15 address lines (A0-A14), 8 data output lines (D0-D7).
    CE (active low): chip enable.
    OE (active low): output enable.
    Content is set via Python (load method), no write pins.
    Read: CE=LOW, OE=LOW -> data driven onto bus.
    """

    def __init__(self, name, address_lines, data_lines, ce_net, oe_net):
        self.name = name
        self.address_lines = address_lines  # 15 nets
        self.data_lines = data_lines  # 8 nets
        self.ce_net = ce_net
        self.oe_net = oe_net
        self._memory = bytearray(32768)
        self._driver_ids = [f"{name}_D{i}" for i in range(8)]

    def pins(self):
        p = {}
        for i, net in enumerate(self.address_lines):
            p[f"A{i}"] = net
        for i, net in enumerate(self.data_lines):
            p[f"D{i}"] = net
        p["CE"] = self.ce_net
        p["OE"] = self.oe_net
        return p

    def load(self, address, data):
        """Load data into ROM starting at address. data can be bytes or list of ints."""
        for i, byte in enumerate(data):
            self._memory[address + i] = byte

    def _read_address(self):
        addr = 0
        for i in range(15):
            if self.address_lines[i].resolve() == Signal.HIGH:
                addr |= (1 << i)
        return addr

    def update(self):
        ce = self.ce_net.resolve()
        oe = self.oe_net.resolve()
        if ce == Signal.LOW and oe == Signal.LOW:
            addr = self._read_address()
            val = self._memory[addr]
            for i in range(8):
                bit = (val >> i) & 1
                self.data_lines[i].drive(
                    self._driver_ids[i],
                    DriveState.HIGH if bit else DriveState.LOW
                )
        else:
            for i in range(8):
                self.data_lines[i].drive(self._driver_ids[i], DriveState.HI_Z)
