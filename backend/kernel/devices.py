"""
devices.py — Device driver abstraction layer.

In a microkernel, drivers live in user space and talk to hardware only
through a narrow kernel-mediated interface (here: DeviceManager). Each
simulated device exposes a small state machine and raises interrupts
through the InterruptController rather than being touched directly by
processes — enforcing the microkernel boundary.
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field


@dataclass
class Device:
    name: str
    kind: str                 # "input" | "storage" | "output" | "sensor" | "network" | "timer" | "gpio"
    status: str = "idle"      # idle | busy | error
    activity_log: list = field(default_factory=list)
    throughput: float = 0.0
    utilization: float = 0.0


class DeviceManager:
    def __init__(self, interrupt_controller):
        self.ic = interrupt_controller
        self.devices: dict[str, Device] = {
            "keyboard": Device("keyboard", "input"),
            "disk": Device("disk", "storage"),
            "display": Device("display", "output"),
            "temp_sensor": Device("temp_sensor", "sensor"),
            "nic": Device("nic", "network"),
            "uart": Device("uart", "output"),
            "gpio": Device("gpio", "gpio"),
            "timer": Device("timer", "timer"),
        }

    def tick(self, current_tick: int, workload_intensity: float = 0.5):
        """Randomized but workload-scaled device activity each tick."""
        events = []
        # Timer always fires (drives the scheduler clock)
        self.ic.raise_interrupt("TIMER", current_tick, "tick")
        self.devices["timer"].status = "busy"

        chance = workload_intensity
        if random.random() < 0.15 * chance:
            self.devices["keyboard"].status = "busy"
            self.ic.raise_interrupt("KEYBOARD", current_tick, "keypress")
            events.append("keyboard: keypress")
        if random.random() < 0.20 * chance:
            self.devices["disk"].status = "busy"
            self.ic.raise_interrupt("DISK", current_tick, "block I/O complete")
            events.append("disk: I/O complete")
        if random.random() < 0.10 * chance:
            self.devices["nic"].status = "busy"
            self.ic.raise_interrupt("NETWORK", current_tick, "packet arrived")
            events.append("nic: packet arrived")
        if random.random() < 0.25 * chance:
            self.devices["temp_sensor"].status = "busy"
            self.ic.raise_interrupt("SENSOR", current_tick, "sample ready")
            events.append("sensor: sample ready")
        if random.random() < 0.08 * chance:
            self.devices["display"].status = "busy"
            self.ic.raise_interrupt("DISPLAY", current_tick, "vsync")
            events.append("display: vsync")

        for d in self.devices.values():
            d.utilization = 0.9 * d.utilization + (0.1 if d.status == "busy" else 0.0)
            if d.status == "busy" and random.random() < 0.6:
                d.status = "idle"

        return events

    def stats(self):
        return {
            name: {
                "kind": d.kind,
                "status": d.status,
                "utilization": round(d.utilization, 3),
            }
            for name, d in self.devices.items()
        }
