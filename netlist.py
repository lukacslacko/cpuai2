"""Netlist DSL for declarative circuit wiring.

Syntax (one statement per line, # comments):

    NAME(type)                      Chip declaration
    NAME[]                          Single wire
    NAME[] = HIGH|LOW|PULLUP        Driven or pull-up wire
    NAME[N]                         Bus of N wires (NAME0..NAME{N-1})
    NAME[N] = HIGH|LOW|PULLUP       Driven bus
    NAME[chip.pin, chip.pin, ...]   Wire with connections
    [chip.pin, chip.pin, ...]       Anonymous wire (auto-named)
    CHIP.PIN - WIRE                 Connect pin to wire
    CHIP.PIN - NC                   Mark pin as intentionally not connected
    CHIP.X[a:b] - W[c:d]           Bus connection (inclusive ranges)
    CHIP.X[a:b] - NC               Mark bus of pins as not connected

All pins of every chip must be accounted for: either connected
to a wire or explicitly marked NC.

Chip types: 40193, 74573, 74574, 74138, 62256, 28256,
            inverter, led, or a .pld filename (GAL22V10).

Pin names per chip type:
    40193:    D0-D3, Q0-Q3, CPU, CPD, PL, MR, TCU, TCD
    74573:    D0-D7, Q0-Q7, LE, OE
    74574:    D0-D7, Q0-Q7, CLK, OE
    74138:    A, B, C, G1, G2A, G2B, Y0-Y7
    62256:    A0-A14, D0-D7, CE, OE, WE
    28256:    A0-A14, D0-D7, CE, OE
    inverter: IN, OUT
    led:      A
    *.pld:    pin names from PLD file
"""

import os
import re

from circuit import Circuit, Signal, DriveState
from components import (
    LED, Inverter, PldProgram, GAL22V10,
    IC74573, IC74574, IC74138, IC40193, IC62256, IC28256,
)

_CHIP_PINS = {
    '40193': ['D0', 'D1', 'D2', 'D3',
              'Q0', 'Q1', 'Q2', 'Q3',
              'CPU', 'CPD', 'PL', 'MR', 'TCU', 'TCD'],
    '74573': [f'D{i}' for i in range(8)] +
             [f'Q{i}' for i in range(8)] + ['LE', 'OE'],
    '74574': [f'D{i}' for i in range(8)] +
             [f'Q{i}' for i in range(8)] + ['CLK', 'OE'],
    '74138': ['A', 'B', 'C', 'G1', 'G2A', 'G2B'] +
             [f'Y{i}' for i in range(8)],
    '62256': [f'A{i}' for i in range(15)] +
             [f'D{i}' for i in range(8)] + ['CE', 'OE', 'WE'],
    '28256': [f'A{i}' for i in range(15)] +
             [f'D{i}' for i in range(8)] + ['CE', 'OE'],
    'inverter': ['IN', 'OUT'],
    'led': ['A'],
}


def _build_chip(type_str, name, pm, pld_source=None):
    if type_str.endswith('.pld'):
        return GAL22V10(name, pld_source, pm)
    if type_str == '40193':
        return IC40193(name,
                       [pm[f'D{i}'] for i in range(4)],
                       [pm[f'Q{i}'] for i in range(4)],
                       pm['CPU'], pm['CPD'], pm['PL'], pm['MR'],
                       pm['TCU'], pm['TCD'])
    if type_str == '74574':
        return IC74574(name,
                       [pm[f'D{i}'] for i in range(8)],
                       [pm[f'Q{i}'] for i in range(8)],
                       pm['CLK'], pm['OE'])
    if type_str == '74573':
        return IC74573(name,
                       [pm[f'D{i}'] for i in range(8)],
                       [pm[f'Q{i}'] for i in range(8)],
                       pm['LE'], pm['OE'])
    if type_str == '74138':
        return IC74138(name,
                       pm['A'], pm['B'], pm['C'],
                       pm['G1'], pm['G2A'], pm['G2B'],
                       [pm[f'Y{i}'] for i in range(8)])
    if type_str == '62256':
        return IC62256(name,
                       [pm[f'A{i}'] for i in range(15)],
                       [pm[f'D{i}'] for i in range(8)],
                       pm['CE'], pm['OE'], pm['WE'])
    if type_str == '28256':
        return IC28256(name,
                       [pm[f'A{i}'] for i in range(15)],
                       [pm[f'D{i}'] for i in range(8)],
                       pm['CE'], pm['OE'])
    if type_str == 'inverter':
        return Inverter(name, pm['IN'], pm['OUT'])
    if type_str == 'led':
        return LED(name, pm['A'])
    raise ValueError(f"Unknown chip type: {type_str}")


# Line patterns
_RE_CHIP = re.compile(r'^(\w+)\(([^)]+)\)$')
_RE_BUS_NC = re.compile(
    r'^(\w+)\.(\w+)\[(\d+):(\d+)\]\s*-\s*NC$')
_RE_BUS_CONN = re.compile(
    r'^(\w+)\.(\w+)\[(\d+):(\d+)\]\s*-\s*(\w+)\[(\d+):(\d+)\]$')
_RE_CONN = re.compile(r'^(\w+)\.(\w+)\s*-\s*(\w+)$')
_RE_BRACKET = re.compile(r'^(\w+)?\[([^\]]*)\](?:\s*=\s*(\w+))?$')


class Netlist:
    """Build a circuit from a text-based netlist DSL."""

    def __init__(self, text, pld_dir=None):
        self.circuit = Circuit()
        self.nets = {}
        self.chips = {}
        if pld_dir is None:
            pld_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'gal')
        self._pld_dir = pld_dir
        self._parse_and_build(text)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_and_build(self, text):
        chip_decls = {}       # name -> type_str (preserves insertion order)
        wire_decls = {}       # name -> drive ('HIGH','LOW','PULLUP', or None)
        connections = []      # [(chip_name, pin_name, wire_name), ...]
        nc_pins = set()       # {(chip_name, pin_name), ...}
        anon = [0]

        def auto_name():
            anon[0] += 1
            return f"_W{anon[0]}"

        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.split('#')[0].strip()
            if not line:
                continue
            try:
                self._parse_line(
                    line, chip_decls, wire_decls, connections,
                    nc_pins, auto_name)
            except Exception as e:
                raise ValueError(f"Line {lineno}: {e}") from e

        self._build(chip_decls, wire_decls, connections, nc_pins)

    @staticmethod
    def _parse_line(line, chip_decls, wire_decls, connections,
                    nc_pins, auto_name):
        # Chip: NAME(TYPE)
        m = _RE_CHIP.match(line)
        if m:
            name, type_str = m.group(1), m.group(2).strip()
            if name in chip_decls:
                raise ValueError(f"Duplicate chip: {name}")
            chip_decls[name] = type_str
            return

        # Bus NC: CHIP.PREFIX[a:b] - NC
        m = _RE_BUS_NC.match(line)
        if m:
            chip, prefix = m.group(1), m.group(2)
            a, b = int(m.group(3)), int(m.group(4))
            for i in range(a, b + 1):
                nc_pins.add((chip, f"{prefix}{i}"))
            return

        # Bus connection: CHIP.PREFIX[a:b] - WIRE[c:d]
        m = _RE_BUS_CONN.match(line)
        if m:
            chip, prefix = m.group(1), m.group(2)
            a1, b1 = int(m.group(3)), int(m.group(4))
            wpfx, a2, b2 = m.group(5), int(m.group(6)), int(m.group(7))
            if (b1 - a1) != (b2 - a2):
                raise ValueError(
                    f"Bus width mismatch: "
                    f"{prefix}[{a1}:{b1}] vs {wpfx}[{a2}:{b2}]")
            for i, j in zip(range(a1, b1 + 1), range(a2, b2 + 1)):
                connections.append((chip, f"{prefix}{i}", f"{wpfx}{j}"))
            return

        # Single connection: CHIP.PIN - WIRE  (including CHIP.PIN - NC)
        m = _RE_CONN.match(line)
        if m:
            chip, pin, wire = m.group(1), m.group(2), m.group(3)
            if wire == 'NC':
                nc_pins.add((chip, pin))
            else:
                connections.append((chip, pin, wire))
            return

        # Wire / bus / wire-with-connections
        m = _RE_BRACKET.match(line)
        if m:
            name = m.group(1)
            content = m.group(2).strip()
            drive = m.group(3).upper() if m.group(3) else None

            if drive and drive not in ('HIGH', 'LOW', 'PULLUP'):
                raise ValueError(f"Invalid drive: {drive}")

            # NAME[] -- single wire
            if content == '':
                if not name:
                    raise ValueError("Wire declaration requires a name")
                if name in wire_decls:
                    raise ValueError(f"Duplicate wire: {name}")
                wire_decls[name] = drive
                return

            # NAME[N] -- bus
            if content.isdigit():
                if not name:
                    raise ValueError("Bus declaration requires a name")
                n = int(content)
                for i in range(n):
                    wn = f"{name}{i}"
                    if wn in wire_decls:
                        raise ValueError(f"Duplicate wire: {wn}")
                    wire_decls[wn] = drive
                return

            # NAME[chip.pin, ...] or [chip.pin, ...]
            if not name:
                name = auto_name()
            if name in wire_decls:
                raise ValueError(f"Duplicate wire: {name}")
            wire_decls[name] = drive
            for ref in content.split(','):
                ref = ref.strip()
                dot = ref.find('.')
                if dot < 0:
                    raise ValueError(f"Invalid pin reference: {ref}")
                connections.append((ref[:dot], ref[dot + 1:], name))
            return

        raise ValueError(f"Unrecognized: {line}")

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def _build(self, chip_decls, wire_decls, connections, nc_pins):
        # 1. Create declared wires
        for name, drive in wire_decls.items():
            pull_up = (drive == 'PULLUP')
            net = self.circuit.create_net(name, pull_up=pull_up)
            self.nets[name] = net
            if drive == 'HIGH':
                net.drive('rail', DriveState.HIGH)
            elif drive == 'LOW':
                net.drive('rail', DriveState.LOW)

        # 2. Auto-create wires referenced in connections but not declared
        for _, _, wn in connections:
            if wn not in self.nets:
                self.nets[wn] = self.circuit.create_net(wn)

        # 3. Build chips (in declaration order)
        for chip_name, type_str in chip_decls.items():
            # Collect pin map from connections
            pin_map = {}
            for cn, pn, wn in connections:
                if cn == chip_name:
                    if pn in pin_map:
                        raise ValueError(
                            f"Pin {chip_name}.{pn} connected twice")
                    pin_map[pn] = self.nets[wn]

            # Determine all pins for this chip type
            pld_source = None
            if type_str.endswith('.pld'):
                with open(os.path.join(self._pld_dir, type_str)) as f:
                    pld_source = f.read()
                prog = PldProgram(pld_source)
                all_pins = list(prog.pins.values())
            elif type_str in _CHIP_PINS:
                all_pins = _CHIP_PINS[type_str]
            else:
                raise ValueError(f"Unknown chip type: {type_str}")

            # Check that every pin is accounted for
            unaccounted = []
            for pn in all_pins:
                if pn in pin_map:
                    continue
                if (chip_name, pn) in nc_pins:
                    # NC: create a private floating wire for the chip
                    aw = f"_{chip_name}_{pn}"
                    if aw not in self.nets:
                        self.nets[aw] = self.circuit.create_net(aw)
                    pin_map[pn] = self.nets[aw]
                else:
                    unaccounted.append(pn)
            if unaccounted:
                raise ValueError(
                    f"Chip {chip_name} ({type_str}) has unconnected pins "
                    f"not marked NC: {', '.join(unaccounted)}")

            # Check for connections/NC referencing pins that don't exist
            valid = set(all_pins)
            for pn in pin_map:
                if pn not in valid:
                    raise ValueError(
                        f"Chip {chip_name} ({type_str}) has no pin {pn}")
            for cn, pn in nc_pins:
                if cn == chip_name and pn not in valid:
                    raise ValueError(
                        f"Chip {chip_name} ({type_str}) has no pin {pn}")

            comp = _build_chip(type_str, chip_name, pin_map, pld_source)
            self.chips[chip_name] = self.circuit.add_component(comp)

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------

    def settle(self):
        return self.circuit.settle()

    def wire(self, name):
        """Get a net by name."""
        return self.nets[name]

    def bus(self, prefix, n):
        """Get [prefix0, prefix1, ..., prefix(n-1)] as a list of nets."""
        return [self.nets[f"{prefix}{i}"] for i in range(n)]

    def read_bus(self, prefix, n):
        """Read an n-bit bus as an unsigned integer (prefix0 = bit 0)."""
        val = 0
        for i in range(n):
            if self.nets[f"{prefix}{i}"].value == Signal.HIGH:
                val |= (1 << i)
        return val

    def drive_bus(self, prefix, n, val):
        """Drive an n-bit bus from an unsigned integer (prefix0 = bit 0)."""
        for i in range(n):
            self.nets[f"{prefix}{i}"].drive(
                'bus_drv', DriveState.HIGH if (val >> i) & 1 else DriveState.LOW)

    def chip(self, name):
        """Get a component by name."""
        return self.chips[name]
