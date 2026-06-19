"""
kernel/process_manager.py
--------------------------
Process Manager — the kernel subsystem that creates, tracks, and destroys
all simulated processes.

Industry context:
    Linux kernel equivalent   : task_struct + fork()/do_exit() + process scheduler hooks
    Qualcomm Hexagon RTOS     : Task Control Block (TCB) + qurt_thread_create()
    QNX Neutrino (automotive) : process descriptor + MsgSend/MsgReceive lifecycle

    The ProcessManager is the single source of truth for:
      - Which processes exist
      - What state each process is in
      - What resources each process owns
      - What processor type each process targets

    Nothing else in the kernel creates or destroys processes.
    Everything else asks the ProcessManager.

Design pattern: Registry + State Machine
    Registry      → _process_table: dict[int, Process]
    State Machine → ProcessState enum + transition guards in each method

C++ equivalent (Level 2 preview):
    class ProcessManager {
    public:
        Process*    create(const std::string& name, Priority prio,
                           TaskClass task_class, ProcessorType target_cpu);
        bool        terminate(int pid);
        bool        block(int pid, const std::string& reason);
        bool        unblock(int pid);
        bool        suspend(int pid);
        bool        resume(int pid);
        Process*    get(int pid) const;
        ProcessStats get_stats() const;
    private:
        std::unordered_map<int, Process> process_table_;
        MemoryManager&                   mm_;
        int                              next_pid_;
    };
"""

from dataclasses import dataclass, field
from typing import Optional
from common.types import (
    ProcessState, Priority, TaskClass, ProcessorType,
    MemoryType, SimConstants
)
from kernel.memory_manager import MemoryManager


# =============================================================================
# PROCESS — the fundamental data structure
# =============================================================================
# In Linux, this is task_struct (about 1000 fields in the real kernel).
# In Qualcomm's Hexagon RTOS, this is the Task Control Block (TCB).
# We keep ours simple but include every field that matters architecturally.

@dataclass
class Process:
    """
    Represents a single simulated process (task).

    Think of this as our task_struct / TCB.
    It is a pure data container — all logic lives in ProcessManager.

    Fields:
        pid          : Process ID. Unique, monotonically increasing. Never reused.
                       (Linux also never reuses PIDs within a session for this reason.)
        name         : Human-readable name. In firmware: "sensor_task", "npu_daemon".
        state        : Current lifecycle state (see ProcessState enum).
        priority     : Scheduling priority. Lower value = higher priority.
        task_class   : What kind of work this process does.
                       The Scheduler uses this to pick the right processor.
        target_cpu   : Which processor type this process should run on.
                       Set at creation by the TaskClassifier (in Scheduler, later).
        stack_region_id : ID of the MemoryRegion allocated for this process's stack.
                          When the process dies, this region is freed automatically.
        tick_created : Which simulation tick this process was born on.
        tick_terminated: Which tick it died on (-1 if still alive).
        block_reason : Why this process is blocked (for debugging and telemetry).
        total_cpu_ticks: How many ticks this process has been in RUNNING state.
                         Used for CPU utilisation stats (like /proc/PID/stat).
    """
    pid:               int
    name:              str
    state:             ProcessState
    priority:          Priority
    task_class:        TaskClass
    target_cpu:        ProcessorType
    stack_region_id:   int             # region_id returned by MemoryManager.alloc()
    tick_created:      int
    tick_terminated:   int   = -1      # -1 = still alive
    block_reason:      str   = ""
    total_cpu_ticks:   int   = 0       # incremented by Scheduler each tick


# =============================================================================
# PROCESS STATS — telemetry snapshot
# =============================================================================

@dataclass
class ProcessStats:
    """
    Point-in-time snapshot of process system state.
    Queried by TelemetryEngine every tick.
    """
    total_created:   int
    currently_alive: int
    by_state:        dict   # {ProcessState.value: count}
    by_task_class:   dict   # {TaskClass.value: count}
    by_target_cpu:   dict   # {ProcessorType.value: count}


# =============================================================================
# TRANSITION TABLE
# =============================================================================
# Defines which state transitions are valid.
# Any transition NOT in this table is illegal and will be rejected.
#
# This is the formal state machine definition.
# In real kernel development, invalid state transitions are a common source
# of race conditions and kernel panics. Encoding them explicitly here trains
# you to think about state machines rigorously.
#
# Format: VALID_TRANSITIONS[current_state] = set of allowed next states

VALID_TRANSITIONS: dict[ProcessState, set] = {
    ProcessState.READY:      {ProcessState.RUNNING, ProcessState.TERMINATED},
    ProcessState.RUNNING:    {ProcessState.READY, ProcessState.BLOCKED,
                              ProcessState.SUSPENDED, ProcessState.TERMINATED},
    ProcessState.BLOCKED:    {ProcessState.READY, ProcessState.TERMINATED},
    ProcessState.SUSPENDED:  {ProcessState.READY, ProcessState.TERMINATED},
    ProcessState.TERMINATED: set(),   # Terminal state — no transitions out
}


# =============================================================================
# PROCESS MANAGER
# =============================================================================

class ProcessManager:
    """
    Kernel subsystem responsible for the full lifecycle of all processes.

    Responsibilities:
        1. Create processes and allocate their resources (stack memory)
        2. Enforce valid state machine transitions
        3. Track all processes in a process table
        4. Clean up all resources when a process terminates
        5. Provide query APIs for Scheduler, IPC, and Telemetry

    Dependency:
        Requires a MemoryManager instance.
        This is Dependency Injection — we pass mm in, not create it here.
        This makes testing clean: we can inject a mock MemoryManager in tests.

    Industry note on PID assignment:
        Linux wraps PIDs at 32768 by default and reuses them after processes die.
        We do NOT reuse PIDs here — once assigned, a PID is retired with its process.
        This makes telemetry logs easier to read and matches some RTOS designs
        (e.g. QNX uses non-recycled node IDs for exactly this reason).
    """

    # Stack size constants — mirrors real RTOS stack configuration
    KERNEL_STACK_SIZE: int = 32    # Simulated bytes for kernel/system processes
    USER_STACK_SIZE:   int = 16    # Simulated bytes for user processes
    AI_STACK_SIZE:     int = 64    # AI inference tasks get larger stacks
                                   # (model context, activation scratch space)

    def __init__(self, memory_manager: MemoryManager):
        """
        Initialise the ProcessManager.

        Args:
            memory_manager: Injected MemoryManager instance.
                            The ProcessManager calls mm.alloc() on create()
                            and mm.free_all_for_pid() on terminate().
        """
        self._mm:             MemoryManager        = memory_manager
        self._process_table:  dict[int, Process]   = {}
        self._next_pid:       int                  = 1   # PID 0 is reserved (like Linux)
        self._total_created:  int                  = 0
        self._event_log:      list[str]            = []
        self._current_tick:   int                  = 0

        # PID 0 is the idle process — always exists, never terminates
        # In Linux this is the swapper/0 process. In RTOS it's the idle task.
        self._create_idle_process()

        self._log("ProcessManager initialised. Idle process (PID 0) created.")

    # -------------------------------------------------------------------------
    # CORE LIFECYCLE API
    # -------------------------------------------------------------------------

    def create(
        self,
        name:       str,
        priority:   Priority      = Priority.NORMAL,
        task_class: TaskClass     = TaskClass.BACKGROUND,
        target_cpu: ProcessorType = ProcessorType.LITTLE_CPU,
        tick:       int           = 0
    ) -> Optional[Process]:
        """
        Create a new process and allocate its resources.

        Steps performed (mirrors real kernel process creation):
            1. Validate we haven't hit the process limit
            2. Assign a new PID
            3. Determine stack size based on task class
            4. Allocate stack memory via MemoryManager
            5. Build the Process object
            6. Insert into process table
            7. Return the Process to the caller

        Args:
            name       : Human-readable name (e.g. "npu_inference_daemon").
            priority   : Scheduling priority.
            task_class : What kind of work (AI, real-time, background, etc.).
            target_cpu : Which simulated processor this should run on.
            tick       : Current simulation tick (for telemetry timestamp).

        Returns:
            Process if creation succeeded, None if it failed.

        Failure reasons:
            - Process table is full (SimConstants.MAX_PROCESSES reached)
            - MemoryManager cannot allocate a stack (out of memory)

        Industry note:
            In Linux, fork() fails with ENOMEM when memory is exhausted.
            In Qualcomm RTOS, qurt_thread_create() returns error codes.
            Our None return value simulates that failure path.
        """
        # --- Guard: process table capacity ---
        alive_count = sum(1 for p in self._process_table.values()
                          if p.state != ProcessState.TERMINATED)
        if alive_count >= SimConstants.MAX_PROCESSES:
            self._log(f"[CREATE FAIL] '{name}' — process table full "
                      f"({SimConstants.MAX_PROCESSES} limit)")
            return None

        # --- Determine stack size by task class ---
        # AI tasks need more stack for model-loading context
        # Kernel/real-time tasks get a medium stack
        # Background tasks get a minimal stack
        stack_size = self._stack_size_for_class(task_class)

        # --- Allocate stack in memory ---
        # Stack memory is GENERAL type — it's just regular process memory.
        # (AI model weights would be AI_BUFFER — allocated separately later.)
        stack_region = self._mm.alloc(
            owner_pid = self._next_pid,
            size      = stack_size,
            mem_type  = MemoryType.GENERAL
        )

        if stack_region is None:
            self._log(f"[CREATE FAIL] '{name}' — stack alloc failed "
                      f"(need {stack_size} bytes, pool may be full)")
            return None

        # --- Build process ---
        pid = self._next_pid
        process = Process(
            pid             = pid,
            name            = name,
            state           = ProcessState.READY,   # Born ready
            priority        = priority,
            task_class      = task_class,
            target_cpu      = target_cpu,
            stack_region_id = stack_region.region_id,
            tick_created    = tick
        )

        # --- Register in table ---
        self._process_table[pid] = process
        self._next_pid    += 1
        self._total_created += 1

        self._log(
            f"[CREATE OK] pid={pid} name='{name}' "
            f"state=READY priority={priority.name} "
            f"class={task_class.value} cpu={target_cpu.value} "
            f"stack_region={stack_region.region_id}"
        )
        return process

    def terminate(self, pid: int, tick: int = 0) -> bool:
        """
        Terminate a process and release all its resources.

        Steps performed:
            1. Validate the process exists and is not already terminated
            2. Perform state transition → TERMINATED
            3. Call mm.free_all_for_pid() to reclaim ALL memory
            4. Record termination tick

        This is equivalent to do_exit() in the Linux kernel.

        Args:
            pid  : PID of the process to terminate.
            tick : Current simulation tick.

        Returns:
            True if terminated successfully, False otherwise.

        Industry note:
            In Linux, do_exit() is called both for normal exit() calls and
            for killed processes (SIGKILL). It always runs to completion —
            a process cannot prevent its own termination once do_exit() starts.
            We model this: terminate() always succeeds if the process exists.
        """
        process = self._get_live_process(pid)
        if process is None:
            return False

        if process.state == ProcessState.TERMINATED:
            self._log(f"[TERMINATE FAIL] pid={pid} already terminated")
            return False

        # --- Transition to TERMINATED ---
        old_state = process.state
        process.state           = ProcessState.TERMINATED
        process.tick_terminated = tick
        process.block_reason    = ""

        # --- Release all memory ---
        # This is the critical cleanup step.
        # In Linux: mmput() + exit_mm() + free_task()
        freed_count = self._mm.free_all_for_pid(pid)

        self._log(
            f"[TERMINATE OK] pid={pid} name='{process.name}' "
            f"was={old_state.value} freed={freed_count} regions "
            f"cpu_ticks={process.total_cpu_ticks} "
            f"lifetime={tick - process.tick_created} ticks"
        )
        return True

    def block(self, pid: int, reason: str = "") -> bool:
        """
        Move a process from RUNNING → BLOCKED.

        Called when a process is waiting for:
          - An IPC message (waiting for reply)
          - A memory allocation (waiting for space to free up)
          - A device operation (waiting for hardware)
          - An AI inference result (waiting for NPU to finish)

        Industry note:
            In Linux, this is schedule() + set_current_state(TASK_INTERRUPTIBLE).
            In Qualcomm's RTOS, qurt_signal_wait() blocks the calling task.

        Args:
            pid    : PID of the process to block.
            reason : Why it's being blocked (for telemetry and debugging).
        """
        process = self._get_live_process(pid)
        if process is None:
            return False

        if not self._is_valid_transition(process.state, ProcessState.BLOCKED):
            self._log(
                f"[BLOCK FAIL] pid={pid} invalid transition "
                f"{process.state.value} → BLOCKED"
            )
            return False

        process.state        = ProcessState.BLOCKED
        process.block_reason = reason

        self._log(f"[BLOCK] pid={pid} name='{process.name}' reason='{reason}'")
        return True

    def unblock(self, pid: int) -> bool:
        """
        Move a process from BLOCKED → READY.

        Called when the event a process was waiting for has occurred:
          - IPC message arrived
          - Memory became available
          - Device operation completed
          - AI inference result is ready

        Industry note:
            In Linux, this is wake_up_process() which calls
            try_to_wake_up() → sets state to TASK_RUNNING → enqueues in scheduler.
        """
        process = self._get_live_process(pid)
        if process is None:
            return False

        if not self._is_valid_transition(process.state, ProcessState.READY):
            self._log(
                f"[UNBLOCK FAIL] pid={pid} invalid transition "
                f"{process.state.value} → READY"
            )
            return False

        old_reason           = process.block_reason
        process.state        = ProcessState.READY
        process.block_reason = ""

        self._log(
            f"[UNBLOCK] pid={pid} name='{process.name}' "
            f"was blocked for: '{old_reason}'"
        )
        return True

    def suspend(self, pid: int) -> bool:
        """
        Move a RUNNING process to SUSPENDED (paused by OS, not waiting for event).

        Used for:
          - Power management: pausing background tasks during deep sleep
          - Debugging: freezing a task to inspect it
          - Thermal: slowing down work when SoC is too hot

        Difference from BLOCKED:
            BLOCKED = process is waiting for something to happen (passive)
            SUSPENDED = OS has actively paused the process (external decision)

        Industry note:
            Android's Doze mode suspends background processes this way.
            Qualcomm's power management suspends DSP tasks during low-power mode.
        """
        process = self._get_live_process(pid)
        if process is None:
            return False

        if not self._is_valid_transition(process.state, ProcessState.SUSPENDED):
            self._log(
                f"[SUSPEND FAIL] pid={pid} invalid transition "
                f"{process.state.value} → SUSPENDED"
            )
            return False

        process.state = ProcessState.SUSPENDED
        self._log(f"[SUSPEND] pid={pid} name='{process.name}'")
        return True

    def resume(self, pid: int) -> bool:
        """
        Move a SUSPENDED process back to READY.

        Called when the OS decides the suspended process can run again.
        """
        process = self._get_live_process(pid)
        if process is None:
            return False

        if not self._is_valid_transition(process.state, ProcessState.READY):
            self._log(
                f"[RESUME FAIL] pid={pid} invalid transition "
                f"{process.state.value} → READY"
            )
            return False

        process.state = ProcessState.READY
        self._log(f"[RESUME] pid={pid} name='{process.name}'")
        return True

    def set_running(self, pid: int) -> bool:
        """
        Move a READY process to RUNNING.
        Called exclusively by the Scheduler when it dispatches a task.

        In real kernels, context_switch() does this — it swaps register state
        and updates the process's state field.
        """
        process = self._get_live_process(pid)
        if process is None:
            return False

        if not self._is_valid_transition(process.state, ProcessState.RUNNING):
            self._log(
                f"[SET_RUNNING FAIL] pid={pid} invalid transition "
                f"{process.state.value} → RUNNING"
            )
            return False

        process.state = ProcessState.RUNNING
        self._log(f"[RUNNING] pid={pid} name='{process.name}'")
        return True

    def tick_running_processes(self):
        """
        Called by SimulationEngine every tick.
        Increments total_cpu_ticks for every RUNNING process.

        This is how we track CPU utilisation per process.
        Equivalent to the kernel's update_process_times() function which
        charges CPU time to the currently running task every timer interrupt.
        """
        for p in self._process_table.values():
            if p.state == ProcessState.RUNNING:
                p.total_cpu_ticks += 1

    def set_tick(self, tick: int):
        """Update the manager's internal tick counter."""
        self._current_tick = tick

    # -------------------------------------------------------------------------
    # QUERY API
    # -------------------------------------------------------------------------

    def get(self, pid: int) -> Optional[Process]:
        """Return the Process for a given PID, or None if not found."""
        return self._process_table.get(pid)

    def get_all_alive(self) -> list[Process]:
        """Return all processes that are NOT terminated."""
        return [p for p in self._process_table.values()
                if p.state != ProcessState.TERMINATED]

    def get_by_state(self, state: ProcessState) -> list[Process]:
        """Return all processes in a specific state."""
        return [p for p in self._process_table.values()
                if p.state == state]

    def get_by_task_class(self, task_class: TaskClass) -> list[Process]:
        """Return all alive processes of a specific task class."""
        return [p for p in self._process_table.values()
                if p.task_class == task_class
                and p.state != ProcessState.TERMINATED]

    def get_stats(self) -> ProcessStats:
        """Return current process system statistics. Called by TelemetryEngine."""
        alive = self.get_all_alive()

        by_state = {s.value: 0 for s in ProcessState}
        for p in alive:
            by_state[p.state.value] += 1

        by_class = {c.value: 0 for c in TaskClass}
        for p in alive:
            by_class[p.task_class.value] += 1

        by_cpu = {c.value: 0 for c in ProcessorType}
        for p in alive:
            by_cpu[p.target_cpu.value] += 1

        return ProcessStats(
            total_created   = self._total_created,
            currently_alive = len(alive),
            by_state        = by_state,
            by_task_class   = by_class,
            by_target_cpu   = by_cpu
        )

    def get_event_log(self) -> list[str]:
        return list(self._event_log)

    # -------------------------------------------------------------------------
    # DISPLAY
    # -------------------------------------------------------------------------

    def display_process_table(self):
        """
        Print a formatted process table to the console.

        Modelled after the output of 'ps aux' on Linux or
        Qualcomm's RTOS task list command in the Hexagon debug shell.

        Example:
            PID  NAME                 STATE       PRI   CLASS            CPU
            ─────────────────────────────────────────────────────────────────
             0   [idle]               READY       IDLE  BACKGROUND       LITTLE_CPU
             1   sensor_task          RUNNING     HIGH  SIGNAL_PROCESS   DSP
             2   npu_inference        BLOCKED     HIGH  AI_INFERENCE     NPU
        """
        alive = sorted(self.get_all_alive(), key=lambda p: p.pid)

        print(f"\n{'─'*75}")
        print(f"  {'PID':<5} {'NAME':<22} {'STATE':<12} {'PRI':<8} "
              f"{'CLASS':<18} {'CPU':<12}")
        print(f"{'─'*75}")

        for p in alive:
            # Colour-code states with symbols
            state_sym = {
                ProcessState.READY:      "○ READY     ",
                ProcessState.RUNNING:    "● RUNNING   ",
                ProcessState.BLOCKED:    "◐ BLOCKED   ",
                ProcessState.SUSPENDED:  "◌ SUSPENDED ",
                ProcessState.TERMINATED: "✕ TERMINATED",
            }.get(p.state, p.state.value)

            block_note = f" [{p.block_reason}]" if p.block_reason else ""

            print(f"  {p.pid:<5} {p.name:<22} {state_sym} {p.priority.name:<8} "
                  f"{p.task_class.value:<18} {p.target_cpu.value}{block_note}")

        print(f"{'─'*75}")
        stats = self.get_stats()
        print(f"  alive={stats.currently_alive}  "
              f"total_created={stats.total_created}  "
              + "  ".join(f"{k}={v}" for k, v in stats.by_state.items() if v > 0))
        print(f"{'─'*75}\n")

    def display_stats_bar(self):
        """Print a compact one-line stats summary."""
        s = self.get_stats()
        state_parts = "  ".join(
            f"{k}={v}" for k, v in s.by_state.items() if v > 0
        )
        print(f"  PROC  alive={s.currently_alive:<3}  {state_parts}")

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _create_idle_process(self):
        """
        Create PID 0 — the idle process.

        Always exists, never terminates, consumes no real resources.
        The scheduler runs it when no other process is READY.

        In Linux, this is the 'swapper' process (PID 0 / init's ancestor).
        In Qualcomm RTOS, this is the idle task that puts the core into WFI
        (Wait For Interrupt) to save power.
        """
        idle = Process(
            pid             = 0,
            name            = "[idle]",
            state           = ProcessState.READY,
            priority        = Priority.IDLE,
            task_class      = TaskClass.BACKGROUND,
            target_cpu      = ProcessorType.LITTLE_CPU,
            stack_region_id = -1,   # No stack — idle process is special
            tick_created    = 0
        )
        self._process_table[0] = idle
        self._next_pid = 1          # Next real PID starts at 1

    def _get_live_process(self, pid: int) -> Optional[Process]:
        """
        Look up a process by PID.
        Returns None with a log entry if not found.
        """
        process = self._process_table.get(pid)
        if process is None:
            self._log(f"[LOOKUP FAIL] pid={pid} not found in process table")
        return process

    def _is_valid_transition(
        self,
        current: ProcessState,
        target:  ProcessState
    ) -> bool:
        """
        Check whether a state transition is legal according to VALID_TRANSITIONS.

        This is the state machine guard. It prevents illegal transitions like:
            TERMINATED → READY  (zombie resurrection — not allowed)
            BLOCKED → RUNNING   (can't run without going through READY first)

        In real kernels, invalid transitions cause kernel panics or WARNINGs.
        We log and return False instead (safer for a simulation).
        """
        return target in VALID_TRANSITIONS.get(current, set())

    def _stack_size_for_class(self, task_class: TaskClass) -> int:
        """
        Determine stack allocation size based on task class.

        Rationale:
            AI_INFERENCE tasks need the most stack — they load model metadata,
            manage activation buffers, and may recurse through layer operations.
            REAL_TIME tasks need deterministic, pre-sized stacks — not too large.
            BACKGROUND tasks get minimal stacks — they do simple work.

        In real RTOS systems (Hexagon, FreeRTOS), stack size is a mandatory
        parameter to task_create(). Getting it wrong causes stack overflow —
        one of the most common bugs in embedded firmware.
        """
        size_map = {
            TaskClass.AI_INFERENCE:   self.AI_STACK_SIZE,
            TaskClass.REAL_TIME:      self.KERNEL_STACK_SIZE,
            TaskClass.SIGNAL_PROCESS: self.KERNEL_STACK_SIZE,
            TaskClass.COMPUTE_HEAVY:  self.USER_STACK_SIZE,
            TaskClass.BACKGROUND:     self.USER_STACK_SIZE,
        }
        return size_map.get(task_class, self.USER_STACK_SIZE)

    def _log(self, message: str):
        """Internal audit log."""
        self._event_log.append(message)