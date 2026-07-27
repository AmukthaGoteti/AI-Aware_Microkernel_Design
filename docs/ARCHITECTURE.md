# System Architecture

## 1. Design philosophy: why a microkernel model

A monolithic kernel runs the scheduler, memory manager, filesystem, and drivers in one address space with unrestricted mutual access. A **microkernel** keeps the trusted core minimal — scheduling, IPC, and basic address-space management — and pushes everything else (filesystem, drivers, networking) into isolated services that only talk to each other *through* the kernel's IPC broker.

NOVA models that boundary explicitly in software even though it's a simulation with no real address-space isolation:

- `IPCManager` is the **only** path by which one process's data reaches another (pipes, shared memory, mailboxes, signals all funnel through it).
- `DeviceManager` mediates all hardware access; a `Process` object never touches a `Device` directly, only raises interrupts through `InterruptController`.
- `SecurityManager.check_syscall()` is a single narrow gate every privileged operation must pass, mirroring a real trap/syscall boundary and kernel/user mode switch.

This means the *architecture itself* teaches the microkernel principle, not just the terminology.

## 2. High-level component diagram

```
                          ┌─────────────────────────────┐
                          │        FastAPI (main.py)     │
                          │  REST + WebSocket + static    │
                          └───────────────┬───────────────┘
                                          │
                          ┌───────────────▼───────────────┐
                          │           Kernel               │
                          │  (boot sequence + tick loop)    │
                          └───┬─────┬─────┬─────┬─────┬────┘
              ┌───────────────┘     │     │     │     └────────────────┐
              ▼                     ▼     ▼     ▼                      ▼
        ┌──────────┐     ┌─────────────┐ │ ┌──────────┐        ┌──────────────┐
        │Scheduler │     │MemoryManager│ │ │  IPC     │        │DeviceManager │
        │(6 algos) │     │(paging+AI)  │ │ │ Manager  │        │+ Interrupts  │
        └──────────┘     └─────────────┘ │ └──────────┘        └──────────────┘
                                          ▼
                       ┌───────────────────────────────────┐
                       │  Deadlock / FileSystem / Security   │
                       │        / Network subsystems          │
                       └───────────────────────────────────┘
                                          │
                          ┌───────────────▼───────────────┐
                          │        AISystemMonitor          │
                          │  (predictor.py + assistant.py)   │
                          └───────────────────────────────┘
```

## 3. The tick loop (the heartbeat of the simulator)

Every simulated "tick" (`Kernel.tick()` in `backend/kernel/kernel.py`) executes, in order:

1. **Device activity** — `DeviceManager.tick()` probabilistically raises interrupts scaled by `workload_intensity`.
2. **Interrupt servicing** — `InterruptController.service_pending()` drains up to 3 pending IRQs per tick, highest priority first (TIMER > KEYBOARD > DISK/NETWORK > SENSOR > DISPLAY).
3. **Network delivery** — `NetworkStack.tick()` drains the packet queue under a weighted-fair bandwidth budget.
4. **I/O unblocking** — blocked processes have a random chance per tick of completing I/O and returning to READY (simulates real I/O completion interrupts).
5. **Scheduling decision** — if the quantum expired or the CPU is idle, `Scheduler.pick_next()` runs the active algorithm; the previously running process (if any) is preempted back to READY.
6. **Execution** — the running process consumes one tick of burst time, triggers exactly one simulated memory access (`MemoryManager.access_page`), and may block on I/O or terminate.
7. **IPC chatter** — a small probability of inter-process messaging keeps the IPC visualization alive.
8. **AI bookkeeping** — `AISystemMonitor.observe()` feeds the CPU/memory trend predictors; `DeadlockMonitor.sample()` updates contention history; `health_score()` recomputes the composite system health metric.

The full state is serialized to JSON (`Kernel.snapshot()`) and pushed to every connected WebSocket client.

## 4. Memory layout

- **Physical memory**: a fixed pool of frames (default 32), each holding at most one (pid, page) pair.
- **Virtual memory**: each process gets a per-process page table sized to its `memory_required` (declared page count). Entries track `present`, `frame`, `dirty`.
- **Page fault path**: `access_page()` → if not present → `_get_free_or_evict()` (free frame if available, else policy-driven victim selection) → `_load_page()` (updates both the frame and the process's page-table entry).
- **AI prefetch**: after every access, a Markov transition table (`page → most-likely-next-page`) is consulted; if a free frame exists and the predicted page isn't resident, it's spec­ulatively loaded and tagged in `prefetched_pages` so a later hit can be attributed as a "prefetch hit" rather than a lucky cold hit.
- **Swap**: evicted (pid, page) pairs are appended to a bounded `swap_space` list — a simplified stand-in for on-disk swap.

See [`docs/DIAGRAMS.md`](DIAGRAMS.md) for a visual memory-access sequence diagram.

## 5. IPC mechanisms

| Mechanism | Kernel object | Semantics |
|---|---|---|
| Message passing | `IPCManager.send_message` / `.receive` | Bounded per-PID mailbox (`deque(maxlen=20)`) |
| Signals | `IPCManager.send_signal` | Same mailbox, validated against `SIGNALS` set |
| Pipes | `IPCManager.create_pipe/write_pipe/read_pipe` | Unidirectional bounded buffer between one writer and one reader |
| Shared memory | `IPCManager.create_shared_segment/attach/write_shared` | Multi-attach segment with a size cap; writes are broadcast as an event, not silently applied |

Every operation appends an entry to a single rolling `event_log`, which is what the dashboard's "IPC Message Bus" panel visualizes.

## 6. Deadlock handling — two complementary layers

1. **Detection (reactive)**: `ResourceAllocationGraph` maintains `holds`/`requests` sets and a `resource_owner` map. `detect_cycle()` builds a wait-for graph (`pid → pid`, not `pid → resource`) and runs DFS cycle detection — a true positive means an actual circular wait exists right now.
2. **Avoidance (proactive)**: `BankersAlgorithm` requires each process to declare a maximum resource claim up front; every request is tentatively applied and checked against `_is_safe_state()` (a full safety-sequence search) before being committed — if no safe sequence exists, the request is rolled back and denied.
3. **AI early warning**: `DeadlockMonitor` doesn't wait for a hard cycle — it trends the blocked/total process ratio over the last 30 samples and flags rising contention as `medium`/`high` risk *before* a cycle necessarily exists, which is what a real production monitoring system would want (a hard detector alone is a lagging indicator).

## 7. Security model

- Two privilege rings: `root` and `user`.
- `KERNEL_ONLY_SYSCALLS` (e.g. `reboot`, `set_scheduler`, `kill_any`) require root; anything else in `USER_SYSCALLS` is available to any authenticated user.
- Every syscall check flips `current_mode` to `"kernel"` for the duration of the (simulated) trap and back to `"user"` afterward — a deliberately visible stand-in for the real hardware privilege-ring transition.
- File access checks read the relevant permission triad (owner/group/other) out of a `"rwxr-xr-x"`-style string, exactly like POSIX permission bits.
- A bounded `audit_log` records every decision (who, what, mode, result) for the dashboard's security panel (not yet surfaced in the default UI — see `docs/FUTURE.md`).

## 8. Filesystem

A simple tree of `INode` objects (root `/`, seeded with `bin/ home/ var/ etc/ tmp/`) backed by a **fixed block-bitmap allocator** (`total_blocks` × `block_size` KB). `create_file`, `delete`, `mkdir`, and `chmod` all go through a **write-ahead journal** (`FileSystem.journal`, bounded to the last 100 entries) so every mutating operation is visibly "committed" or "failed" — a minimal but real illustration of journaling filesystem semantics (ext4/NTFS-style write-ahead logging, simplified to a flat commit record rather than full redo/undo logs).

## 9. Networking

`NetworkStack` models sockets (`TCP`/`UDP`) bound to a PID and port, a packet queue, and a **weighted-fair-queue** delivery scheduler (`tick()`) that round-robins across distinct source PIDs under a fixed per-tick bandwidth budget so no single process can starve the loopback link — the same fairness principle real network schedulers (e.g. Linux's `fq_codel`) apply, simplified to byte-budget round robin.

## 10. Data flow summary

```
Client (browser) ⇄ WebSocket ⇄ FastAPI ⇄ Kernel.tick() ⇄ [Scheduler, Memory, IPC, Interrupts,
                                                            Devices, Deadlock, FS, Security, Network]
                                              │
                                              ▼
                                        AISystemMonitor ⇄ ChatAssistant
```

Every subsystem is independently unit-testable (see `tests/`) precisely because the Kernel class only *orchestrates* — it holds no scheduling/memory/IPC logic itself, matching the microkernel principle at the software-architecture level, not just the simulated one.
