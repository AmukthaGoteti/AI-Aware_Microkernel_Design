"""
kernel.py — The microkernel core.

Owns the boot sequence, the master tick loop (timer-driven), and the
system-call dispatcher that routes every request through SecurityManager
before touching any subsystem — the architectural hallmark of a
microkernel (services are independent modules; the kernel itself just
dispatches and enforces boundaries).
"""

from __future__ import annotations
import random
from collections import deque

from .process import PCB, ProcessState, ProcessType, make_process
from .scheduler import Scheduler, Algorithm
from .memory import MemoryManager, ReplacementPolicy
from .ipc import IPCManager
from .interrupts import InterruptController
from .devices import DeviceManager
from .deadlock import ResourceAllocationGraph, BankersAlgorithm, DeadlockMonitor
from .filesystem import FileSystem
from .security import SecurityManager
from .network import NetworkStack

from ..ai.monitor import AISystemMonitor
from ..ai.assistant import ChatAssistant


DEFAULT_PROCESS_SPECS = [
    dict(name="shell", ptype=ProcessType.SHELL, priority=3, burst_time=6, memory_required=3, io_bound=True),
    dict(name="file_manager", ptype=ProcessType.FILE_MANAGER, priority=4, burst_time=8, memory_required=5, io_bound=True),
    dict(name="calculator", ptype=ProcessType.CALCULATOR, priority=6, burst_time=3, memory_required=2, io_bound=False),
    dict(name="sensor_daemon", ptype=ProcessType.SENSOR, priority=2, burst_time=4, memory_required=2, io_bound=True),
    dict(name="logger", ptype=ProcessType.LOGGER, priority=5, burst_time=5, memory_required=3, io_bound=True),
    dict(name="ai_daemon", ptype=ProcessType.AI_DAEMON, priority=1, burst_time=10, memory_required=6, io_bound=False),
]


class Kernel:
    def __init__(self):
        self.tick_count = 0
        self.boot_log: list[str] = []
        self.processes: dict[int, PCB] = {}
        self.ready_queue: list[PCB] = []
        self.blocked_queue: list[PCB] = []
        self.terminated: list[PCB] = []

        self.scheduler = Scheduler(algorithm=Algorithm.AI, quantum=4)
        self.memory = MemoryManager(total_frames=32, policy=ReplacementPolicy.LRU)
        self.ipc = IPCManager()
        self.interrupts = InterruptController()
        self.devices = DeviceManager(self.interrupts)
        self.rag = ResourceAllocationGraph()
        self.bankers = BankersAlgorithm(available={"printer": 2, "scanner": 1, "gpu": 1})
        self.deadlock_monitor = DeadlockMonitor()
        self.filesystem = FileSystem()
        self.security = SecurityManager()
        self.network = NetworkStack()
        self.ai_monitor = AISystemMonitor()
        self.assistant = ChatAssistant(self)

        self._quantum_remaining = 0
        self.cpu_history = deque(maxlen=120)
        self.workload_intensity = 0.5
        self.last_health = None
        self.running_flag = True
        self.speed = 1.0

        self._boot()
        self._spawn_defaults()

    # ------------------------------------------------------------
    def _boot(self):
        steps = [
            "POST: verifying simulated hardware descriptors",
            "Initializing interrupt controller (PIC/APIC)",
            "Initializing memory manager (32 frames, LRU policy)",
            "Mounting root filesystem (/)",
            "Starting IPC broker",
            "Starting security subsystem (privilege rings)",
            "Bringing up network loopback interface",
            "Starting AI system monitor",
            "Starting scheduler (mode=AI)",
            "Kernel boot complete — entering multitasking mode",
        ]
        for s in steps:
            self.boot_log.append(s)

    def _spawn_defaults(self):
        for spec in DEFAULT_PROCESS_SPECS:
            self.spawn_process(**spec)
        # idle process — always present, lowest priority, infinite burst
        idle = make_process("idle", ProcessType.IDLE, self.tick_count, priority=9, burst_time=10**6,
                             remaining_burst=10**6, memory_required=1)
        idle.state = ProcessState.READY
        self.processes[idle.pid] = idle
        self.idle_pid = idle.pid
        self.ready_queue.append(idle)

    # ------------------------------------------------------------
    def spawn_process(self, name, ptype, priority=5, burst_time=5, memory_required=4, io_bound=False, user="user"):
        proc = make_process(name, ptype, self.tick_count, priority=priority, burst_time=burst_time,
                             remaining_burst=burst_time, memory_required=memory_required, io_bound=io_bound, user=user)
        proc.page_table = self.memory.allocate_process(proc.pid, memory_required)
        proc.state = ProcessState.READY
        self.processes[proc.pid] = proc
        self.ready_queue.append(proc)
        self.rag.request(proc.pid, f"init-resource-{proc.pid}")
        return proc

    def kill_process(self, pid: int) -> bool:
        proc = self.processes.get(pid)
        if not proc or proc.state == ProcessState.TERMINATED:
            return False
        proc.state = ProcessState.TERMINATED
        proc.completion_tick = self.tick_count
        self.ready_queue = [p for p in self.ready_queue if p.pid != pid]
        self.blocked_queue = [p for p in self.blocked_queue if p.pid != pid]
        if self.scheduler.running and self.scheduler.running.pid == pid:
            self.scheduler.running = None
        self.memory.free_process(pid)
        self.rag.clear_process(pid)
        self.terminated.append(proc)
        proc.log(self.tick_count, "KILLED")
        return True

    # ------------------------------------------------------------
    def tick(self):
        self.tick_count += 1
        t = self.tick_count

        # 1. devices raise interrupts
        self.devices.tick(t, self.workload_intensity)
        # 2. interrupt controller services them
        self.interrupts.service_pending(t, max_service=3)
        # 3. network delivers queued packets
        self.network.tick(t)

        # 4. unblock some blocked processes probabilistically (I/O completion)
        still_blocked = []
        for p in self.blocked_queue:
            if random.random() < 0.35:
                p.state = ProcessState.READY
                p.log(t, "UNBLOCKED", "I/O completed")
                self.ready_queue.append(p)
            else:
                still_blocked.append(p)
        self.blocked_queue = still_blocked

        # 5. scheduling decision
        active_ready = [p for p in self.ready_queue if p.state == ProcessState.READY]
        if self.scheduler.running is None or self._quantum_remaining <= 0:
            if self.scheduler.running and self.scheduler.running.state == ProcessState.RUNNING:
                self.scheduler.running.state = ProcessState.READY
                self.ready_queue.append(self.scheduler.running)
                active_ready = [p for p in self.ready_queue if p.state == ProcessState.READY]

            next_proc = self.scheduler.pick_next(active_ready, t)
            if next_proc:
                self.ready_queue = [p for p in self.ready_queue if p.pid != next_proc.pid]
                if self.scheduler.running is not None and self.scheduler.running.pid != next_proc.pid:
                    self.scheduler.context_switches += 1
                    next_proc.context_switches += 1
                self.scheduler.running = next_proc
                next_proc.state = ProcessState.RUNNING
                if next_proc.response_time is None:
                    next_proc.response_time = t - next_proc.arrival_tick
                next_proc.last_run_tick = t
                self._quantum_remaining = self.scheduler.compute_quantum(next_proc)
                next_proc.log(t, "SCHEDULED", self.scheduler.last_decision_reason)

        self.scheduler.bump_starvation(active_ready, self.scheduler.running)

        # 6. execute one tick of the running process
        running = self.scheduler.running
        if running and running.pid != getattr(self, "idle_pid", -1):
            running.remaining_burst -= 1
            self._quantum_remaining -= 1
            # simulate a memory access this tick
            if running.page_table:
                page = random.randint(0, len(running.page_table) - 1)
                self.memory.access_page(running.pid, running.page_table, page, t)
            # random chance of blocking on I/O for io_bound processes
            if running.io_bound and random.random() < 0.12:
                running.state = ProcessState.BLOCKED
                running.log(t, "BLOCKED", "I/O wait")
                self.blocked_queue.append(running)
                self.scheduler.running = None
                self._quantum_remaining = 0
            elif running.remaining_burst <= 0:
                running.record_burst_sample()
                running.turnaround_time = t - running.arrival_tick
                running.state = ProcessState.TERMINATED
                running.completion_tick = t
                running.log(t, "COMPLETED")
                self.memory.free_process(running.pid)
                self.rag.clear_process(running.pid)
                self.terminated.append(running)
                self.scheduler.running = None
                self._quantum_remaining = 0
                # respawn a fresh instance of this process type to keep the demo alive
                self._respawn_like(running)
        elif running and running.pid == getattr(self, "idle_pid", -1):
            self._quantum_remaining -= 1

        # 7. IPC chatter between a couple of live processes (for visualization)
        alive = [p for p in self.processes.values() if p.state not in (ProcessState.TERMINATED,)]
        if len(alive) >= 2 and random.random() < 0.3:
            a, b = random.sample(alive, 2)
            self.ipc.send_message(a.pid, b.pid, f"ping from {a.name}", t)

        # 8. AI monitor bookkeeping
        cpu_util = self._cpu_utilization()
        self.cpu_history.append(cpu_util)
        mem_util = 100 * (1 - self.memory.stats()["free_frames"] / self.memory.total_frames)
        self.ai_monitor.observe(cpu_util, mem_util)

        blocked_ratio = len(self.blocked_queue) / max(1, len(alive))
        self.deadlock_monitor.sample(len(self.blocked_queue), max(1, len(alive)))
        risk = self.deadlock_monitor.risk_assessment()
        self.last_health = self.ai_monitor.health_score(
            cpu_util, mem_util, self.memory.stats()["fault_rate"], blocked_ratio, risk["risk"]
        )

        return self.snapshot()

    def _respawn_like(self, proc: PCB):
        spec = next((s for s in DEFAULT_PROCESS_SPECS if s["name"] == proc.name), None)
        if spec:
            jitter = random.randint(-2, 3)
            new_spec = dict(spec)
            new_spec["burst_time"] = max(2, spec["burst_time"] + jitter)
            new_proc = self.spawn_process(**new_spec)
            new_proc.burst_history = proc.burst_history[-10:]

    def _cpu_utilization(self) -> float:
        return 0.0 if (self.scheduler.running and self.scheduler.running.pid == getattr(self, "idle_pid", -1)) else 100.0

    # ------------------------------------------------------------
    def snapshot(self) -> dict:
        alive = [p for p in self.processes.values() if p.state != ProcessState.TERMINATED]
        avg_cpu = (sum(self.cpu_history) / len(self.cpu_history)) if self.cpu_history else 0
        mem_stats = self.memory.stats()
        mem_stats["fragmentation"] = self.memory.fragmentation_estimate()

        completed = [p for p in self.terminated[-30:]]
        metrics = self._compute_metrics(completed)

        return {
            "tick": self.tick_count,
            "algorithm": self.scheduler.algorithm.value,
            "quantum": self.scheduler.quantum,
            "running": self.scheduler.running.to_dict() if self.scheduler.running else None,
            "ready_queue": [p.to_dict() for p in self.ready_queue if p.pid != getattr(self, "idle_pid", -1)],
            "blocked_queue": [p.to_dict() for p in self.blocked_queue],
            "processes": [p.to_dict() for p in alive],
            "cpu_utilization": round(avg_cpu, 1),
            "cpu_history": list(self.cpu_history),
            "memory": mem_stats,
            "ipc": self.ipc.stats(),
            "interrupts": self.interrupts.stats(),
            "devices": self.devices.stats(),
            "filesystem": self.filesystem.stats(),
            "security": self.security.stats(),
            "network": self.network.stats(),
            "deadlock": {
                "cycle": self.rag.detect_cycle(),
                "risk": self.deadlock_monitor.risk_assessment(),
            },
            "ai": {
                "cpu_overload": self.ai_monitor.cpu_overload_prediction(),
                "memory_exhaustion": self.ai_monitor.memory_exhaustion_prediction(),
                "starvation": self.ai_monitor.detect_starvation(list(self.processes.values())),
                "policy_recommendation": self.ai_monitor.recommend_policy(
                    [p for p in self.processes.values() if p.state != ProcessState.TERMINATED],
                    self.scheduler.algorithm.value,
                ),
                "memory_recommendation": self.ai_monitor.recommend_memory_optimization(mem_stats),
                "last_decision_reason": self.scheduler.last_decision_reason,
                "health": self.last_health,
            },
            "metrics": metrics,
            "context_switches": self.scheduler.context_switches,
            "boot_log": self.boot_log,
        }

    def _compute_metrics(self, completed):
        if not completed:
            return {"avg_turnaround": 0, "avg_waiting": 0, "avg_response": 0, "throughput": 0}
        n = len(completed)
        avg_turnaround = sum(p.turnaround_time for p in completed) / n
        avg_waiting = sum(p.waiting_time for p in completed) / n
        responses = [p.response_time for p in completed if p.response_time is not None]
        avg_response = sum(responses) / len(responses) if responses else 0
        throughput = n / max(1, self.tick_count)
        return {
            "avg_turnaround": round(avg_turnaround, 2),
            "avg_waiting": round(avg_waiting, 2),
            "avg_response": round(avg_response, 2),
            "throughput": round(throughput, 4),
        }

    # ------------------------------------------------------------
    # Control surface used by the API layer
    # ------------------------------------------------------------
    def set_algorithm(self, algo_name: str):
        self.scheduler.set_algorithm(Algorithm(algo_name))

    def set_memory_policy(self, policy_name: str):
        self.memory.policy = ReplacementPolicy(policy_name)

    def inject_interrupt(self, irq: str):
        self.interrupts.raise_interrupt(irq.upper(), self.tick_count, "manually injected")

    def trigger_memory_pressure(self):
        # spawn several memory-hungry ghost accesses to force faults/eviction
        for p in list(self.processes.values()):
            if p.state == ProcessState.TERMINATED or not p.page_table:
                continue
            for _ in range(3):
                page = random.randint(0, len(p.page_table) - 1)
                self.memory.access_page(p.pid, p.page_table, page, self.tick_count)

    def generate_workload(self, count=3):
        names = ["batch_job", "compile_task", "render_job", "backup_daemon"]
        for _ in range(count):
            self.spawn_process(
                name=random.choice(names), ptype=ProcessType.USER,
                priority=random.randint(1, 9), burst_time=random.randint(3, 15),
                memory_required=random.randint(2, 8), io_bound=random.random() < 0.4,
            )

    def ask_assistant(self, question: str) -> str:
        return self.assistant.answer(question)
