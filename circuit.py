"""Core circuit simulation engine: signals, nets, components, and the simulation loop."""

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


# Backward-compatible re-exports: code that does
#   from circuit import IC74574, GAL22V10, ...
# will still work.
from components import (  # noqa: E402, F401
    LED, Switch, Inverter, PldProgram, GAL22V10,
    IC74573, IC74574, IC74138, IC40193, IC62256, IC28256,
)
