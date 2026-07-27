"""
interrupts.py — Interrupt controller (simulated PIC/APIC).

Maintains a priority interrupt vector table, an interrupt timeline for
visualization, and simple ISR (interrupt service routine) dispatch. An AI
hook predicts the next likely interrupt type using recency-weighted
frequency of the recent interrupt stream (useful for the AI monitor's
"predict next interrupt" chat query).
"""

from __future__ import annotations
import random
from collections import deque, Counter
from dataclasses import dataclass


IRQ_PRIORITIES = {
    "TIMER": 0,
    "KEYBOARD": 2,
    "DISK": 3,
    "NETWORK": 3,
    "SENSOR": 4,
    "DISPLAY": 5,
}


@dataclass
class InterruptEvent:
    tick: int
    irq: str
    handled: bool
    latency: int
    detail: str = ""


class InterruptController:
    def __init__(self):
        self.timeline: deque = deque(maxlen=200)
        self.pending: list = []
        self.total_handled = 0

    def raise_interrupt(self, irq: str, tick: int, detail: str = ""):
        priority = IRQ_PRIORITIES.get(irq, 9)
        self.pending.append((priority, irq, tick, detail))
        self.pending.sort(key=lambda x: x[0])

    def service_pending(self, tick: int, max_service: int = 3):
        """Services up to `max_service` pending interrupts this tick,
        highest priority (lowest number) first — simulating an ISR sweep."""
        serviced = []
        for _ in range(min(max_service, len(self.pending))):
            priority, irq, raised_tick, detail = self.pending.pop(0)
            latency = tick - raised_tick
            evt = InterruptEvent(tick=tick, irq=irq, handled=True, latency=latency, detail=detail)
            self.timeline.append(evt)
            self.total_handled += 1
            serviced.append(evt)
        return serviced

    def predict_next(self) -> dict:
        """Recency-weighted frequency predictor over the last 40 events."""
        recent = list(self.timeline)[-40:]
        if not recent:
            return {"irq": "TIMER", "confidence": 0.25, "reason": "No history yet; TIMER is the periodic default."}
        weights = Counter()
        for i, evt in enumerate(recent):
            weights[evt.irq] += (i + 1)  # more recent = higher weight
        total = sum(weights.values())
        irq, w = weights.most_common(1)[0]
        confidence = round(w / total, 3)
        return {
            "irq": irq,
            "confidence": confidence,
            "reason": f"{irq} accounts for {confidence*100:.1f}% of recency-weighted recent interrupts.",
        }

    def stats(self):
        return {
            "pending": len(self.pending),
            "total_handled": self.total_handled,
            "timeline": [
                {"tick": e.tick, "irq": e.irq, "latency": e.latency, "detail": e.detail}
                for e in list(self.timeline)[-40:]
            ],
            "prediction": self.predict_next(),
        }
