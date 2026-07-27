"""
process.py — Process & Thread abstractions for the AI-Aware Microkernel Simulator.

Models a PCB (Process Control Block) with enough fidelity to drive realistic
scheduling, memory, and IPC behaviour, while staying pure-Python / dependency-free
so it can be unit tested in isolation from the async kernel loop.
"""

from __future__ import annotations
import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProcessState(str, Enum):
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    WAITING_IO = "WAITING_IO"
    TERMINATED = "TERMINATED"
    ZOMBIE = "ZOMBIE"


class ProcessType(str, Enum):
    SHELL = "shell"
    FILE_MANAGER = "file_manager"
    CALCULATOR = "calculator"
    SENSOR = "sensor"
    LOGGER = "logger"
    AI_DAEMON = "ai_daemon"
    IDLE = "idle"
    USER = "user"


_pid_counter = itertools.count(1)


@dataclass
class HistoryEntry:
    tick: int
    event: str
    detail: str = ""


@dataclass
class Thread:
    tid: int
    pid: int
    state: ProcessState = ProcessState.READY
    program_counter: int = 0
    stack_pointer: int = 0
    remaining_burst: int = 0


@dataclass
class PCB:
    """Process Control Block."""

    pid: int = field(default_factory=lambda: next(_pid_counter))
    name: str = "process"
    ptype: ProcessType = ProcessType.USER
    priority: int = 5              # 0 = highest priority
    base_priority: int = 5
    state: ProcessState = ProcessState.NEW
    arrival_tick: int = 0
    burst_time: int = 5            # total CPU time required
    remaining_burst: int = 5
    memory_required: int = 4       # in pages
    page_table: list = field(default_factory=list)
    cpu_affinity: Optional[int] = None
    io_bound: bool = False

    # Scheduling bookkeeping
    waiting_time: int = 0
    turnaround_time: int = 0
    response_time: Optional[int] = None
    completion_tick: Optional[int] = None
    context_switches: int = 0
    last_run_tick: Optional[int] = None
    starvation_counter: int = 0

    # AI bookkeeping
    predicted_burst: float = 5.0
    burst_history: list = field(default_factory=list)
    ai_score: float = 0.0
    ai_reason: str = ""

    # Security
    user: str = "user"
    privilege: str = "user"        # "kernel" | "user"

    # Threads / IPC
    threads: list = field(default_factory=list)
    open_mailboxes: list = field(default_factory=list)

    history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def log(self, tick: int, event: str, detail: str = ""):
        self.history.append(HistoryEntry(tick=tick, event=event, detail=detail))
        if len(self.history) > 200:
            self.history.pop(0)

    def record_burst_sample(self):
        """Called on completion/preemption to feed the AI predictor."""
        used = self.burst_time - self.remaining_burst
        if used > 0:
            self.burst_history.append(used)
            if len(self.burst_history) > 20:
                self.burst_history.pop(0)

    def to_dict(self):
        return {
            "pid": self.pid,
            "name": self.name,
            "type": self.ptype.value,
            "priority": self.priority,
            "base_priority": self.base_priority,
            "state": self.state.value,
            "arrival_tick": self.arrival_tick,
            "burst_time": self.burst_time,
            "remaining_burst": self.remaining_burst,
            "memory_required": self.memory_required,
            "cpu_affinity": self.cpu_affinity,
            "waiting_time": self.waiting_time,
            "turnaround_time": self.turnaround_time,
            "response_time": self.response_time,
            "context_switches": self.context_switches,
            "starvation_counter": self.starvation_counter,
            "predicted_burst": round(self.predicted_burst, 2),
            "ai_score": round(self.ai_score, 3),
            "ai_reason": self.ai_reason,
            "user": self.user,
            "privilege": self.privilege,
            "thread_count": len(self.threads),
            "history": [
                {"tick": h.tick, "event": h.event, "detail": h.detail}
                for h in self.history[-15:]
            ],
        }


def make_process(name: str, ptype: ProcessType, tick: int, **kwargs) -> PCB:
    p = PCB(name=name, ptype=ptype, arrival_tick=tick, **kwargs)
    p.predicted_burst = float(p.burst_time)
    p.state = ProcessState.NEW
    p.threads.append(Thread(tid=1, pid=p.pid, remaining_burst=p.burst_time))
    p.log(tick, "CREATED", f"{ptype.value} spawned")
    return p
