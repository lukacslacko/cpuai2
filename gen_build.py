#!/usr/bin/env python3
"""Generate build instructions for the CPU.

Instantiates the CPU, inspects all components and their pin-to-net
connections, and writes BUILD.md with a component list and connection table.

Usage:
    python gen_build.py
"""

from collections import defaultdict
from cpu import CPU


IC_TYPES = {
    "LED": "LED",
    "Switch": "Switch",
    "Inverter": "Inverter",
    "GAL22V10": "GAL22V10",
    "IC74573": "74573 (8-bit transparent latch)",
    "IC74574": "74574 (8-bit edge-triggered flip-flop)",
    "IC74138": "74138 (3-to-8 decoder/demultiplexer)",
    "IC40193": "40193 (4-bit up/down counter)",
    "IC62256": "62256 (32KB SRAM)",
    "IC28256": "28256 (32KB EEPROM/ROM)",
}


def component_type_label(comp):
    cls = type(comp).__name__
    return IC_TYPES.get(cls, cls)


def generate():
    cpu = CPU()
    components = cpu.circuit.components
    lines = []

    lines.append("# CPU Build Instructions")
    lines.append("")
    lines.append("Auto-generated — do not edit by hand.  ")
    lines.append("Regenerate with: `python gen_build.py`")
    lines.append("")

    # --- Component list ---
    lines.append("## Components")
    lines.append("")
    lines.append("| # | Name | Type |")
    lines.append("|---|------|------|")
    for i, comp in enumerate(components, 1):
        lines.append(f"| {i} | {comp.name} | {component_type_label(comp)} |")
    lines.append("")

    # --- Connections: group by net ---
    # net -> [(component_name, pin_name), ...]
    net_connections = defaultdict(list)
    for comp in components:
        if not hasattr(comp, 'pins'):
            continue
        for pin_name, net in comp.pins().items():
            net_connections[net.name].append((comp.name, pin_name))

    lines.append("## Connections")
    lines.append("")
    lines.append("Each row is a net (wire/trace). All listed pins are connected together.")
    lines.append("")
    lines.append("| Net | Connections |")
    lines.append("|-----|-------------|")
    for net_name in sorted(net_connections.keys()):
        conns = net_connections[net_name]
        if len(conns) < 2:
            continue
        conn_str = ", ".join(f"{cname}.{pname}" for cname, pname in conns)
        lines.append(f"| {net_name} | {conn_str} |")

    # Also list single-pin nets (unconnected) for reference
    singles = []
    for net_name in sorted(net_connections.keys()):
        conns = net_connections[net_name]
        if len(conns) == 1:
            cname, pname = conns[0]
            singles.append((net_name, cname, pname))

    if singles:
        lines.append("")
        lines.append("### Single-pin nets (directly driven by control logic)")
        lines.append("")
        lines.append("| Net | Component.Pin |")
        lines.append("|-----|---------------|")
        for net_name, cname, pname in singles:
            lines.append(f"| {net_name} | {cname}.{pname} |")

    lines.append("")

    with open("BUILD.md", "w") as f:
        f.write("\n".join(lines))

    print(f"BUILD.md generated with {len(components)} components.")


if __name__ == "__main__":
    generate()
