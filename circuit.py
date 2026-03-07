from enum import Enum


class Signal(Enum):
    FLOATING = "FLOATING"
    LOW = "LOW"
    HIGH = "HIGH"


class DriveState(Enum):
    HI_Z = "HI_Z"
    LOW = "LOW"
    HIGH = "HIGH"


class DoubleDriveError(Exception):
    pass


class Net:
    def __init__(self, name, pull_up=False):
        self.name = name
        self.pull_up = pull_up
        self._drivers = {}

    def drive(self, driver_id, state):
        if state == DriveState.HI_Z:
            self._drivers.pop(driver_id, None)
        else:
            self._drivers[driver_id] = state

    def resolve(self):
        active = {k: v for k, v in self._drivers.items() if v != DriveState.HI_Z}
        if not active:
            return Signal.HIGH if self.pull_up else Signal.FLOATING

        if len(active) > 1:
            drivers = list(active.keys())
            raise DoubleDriveError(
                f"Net '{self.name}' driven by multiple drivers: {drivers}"
            )

        val = next(iter(active.values()))
        return Signal.HIGH if val == DriveState.HIGH else Signal.LOW

    @property
    def value(self):
        return self.resolve()


class Component:
    def pre_update(self):
        """Sample inputs before any outputs change. Used for simultaneous edge capture."""
        pass

    def update(self):
        """Drive outputs based on current/sampled state."""
        raise NotImplementedError


class LED(Component):
    def __init__(self, name, net):
        self.name = name
        self.net = net
        self.is_on = False

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

    def update(self):
        pass


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


class Circuit:
    def __init__(self):
        self.nets = {}
        self.components = []

    def create_net(self, name, pull_up=False):
        net = Net(name, pull_up)
        self.nets[name] = net
        return net

    def add_component(self, component):
        self.components.append(component)
        return component

    def settle(self, max_iterations=10):
        """Run simulation until net states stabilize.

        Uses two-phase update: pre_update (sample inputs) then update (drive outputs).
        This ensures edge-triggered components on a shared clock all sample simultaneously.
        """
        for iteration in range(max_iterations):
            old = {}
            for name, net in self.nets.items():
                try:
                    old[name] = net.resolve()
                except DoubleDriveError:
                    old[name] = None

            for comp in self.components:
                comp.pre_update()
            for comp in self.components:
                comp.update()

            new = {}
            for name, net in self.nets.items():
                try:
                    new[name] = net.resolve()
                except DoubleDriveError:
                    new[name] = None

            if old == new:
                return iteration + 1

        raise RuntimeError("Circuit did not settle within max iterations")
