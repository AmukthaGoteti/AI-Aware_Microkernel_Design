# Testing Strategy

## Philosophy

A simulator whose entire value is "demonstrates OS principles correctly" is worthless if the simulated mechanics are wrong. Testing here prioritizes **mechanism correctness** (does LRU actually evict the least-recently-used frame?) over UI/integration coverage, though both matter.

## Test pyramid

```
        ▲
       / \        Manual / exploratory (dashboard walkthroughs, docs/DEMO_SCENARIOS.md)
      /   \
     / API \       Integration tests: FastAPI TestClient + WebSocket (planned, Week 11)
    /-------\
   / Kernel  \     Unit tests: scheduler, memory, deadlock (this delivery — 17 tests, all passing)
  /___________\
```

## What is covered today (`tests/`)

### `tests/test_scheduler.py`
- FCFS picks earliest arrival, regardless of ready-queue insertion order
- SJF picks shortest **remaining** burst (not original burst — matters for preempted processes)
- Priority picks lowest priority number (0 = highest priority, matching the PCB convention)
- Round Robin rotates deterministically across repeated calls
- MLQ prefers the highest non-empty priority band (system > interactive > batch)
- **AI scheduler starvation guarantee**: a process with extreme wait time must win selection regardless of burst/priority disadvantage — this test caught a real bug (soft-scoring starvation term was mathematically too weak; fixed with a hard override, see commit history / `AI_DESIGN.md` §1)
- AI scheduler always produces a non-empty `last_decision_reason` (contract the frontend/chat assistant depend on)

### `tests/test_memory.py`
- First access to any page is always a fault
- Second access to the same page is a hit (or prefetch-hit)
- FIFO evicts the frame that was loaded first — this test caught a real bug (eviction wasn't clearing the *evicted* process's page-table entry, leaving it in an inconsistent "present" state; fixed by tracking a `pid → page_table` registry inside `MemoryManager`)
- LRU keeps a recently-touched page resident over a colder one
- `free_process` returns all of a process's frames to the free pool — this test caught a second bug (frames were cleared but never re-added to `free_frames`; fixed)
- AI prefetcher learns a simple sequential access pattern and preloads the predicted next page

### `tests/test_deadlock.py`
- No cycle reported when there's no resource contention
- A simple two-process circular wait (P1 holds R1 wants R2, P2 holds R2 wants R1) is correctly detected
- Banker's algorithm denies a request that would leave the system unsafe
- Banker's algorithm grants a request when a safe sequence exists

**Result at last run: 17/17 passing**, and the process of writing these tests caught **three real correctness bugs** in the initial implementation — a concrete demonstration of why the test suite ships alongside the simulator rather than being an afterthought.

## Running the suite

```bash
pip install pytest
cd ai-microkernel-os
pytest tests/ -v
```

## Planned additions (Week 11, see `ROADMAP.md`)

1. **Integration tests** via FastAPI's `TestClient` and a WebSocket test client: assert the `/api/state` and `/ws` snapshot schemas remain stable across refactors (a lightweight contract test, not full schema validation).
2. **Property-based testing** with Hypothesis: generate random workloads (varying burst times, priorities, arrival patterns) and assert invariants that must hold for *any* input — e.g. "every spawned process eventually reaches TERMINATED or stays alive, never silently disappears from `Kernel.processes`," "used_frames + free_frames == total_frames at every tick," "the sum of all resource allocations never exceeds total available resources."
3. **Load testing**: spawn 500+ processes and assert the tick loop stays within a latency budget (guards against accidentally introducing O(n²) behavior in the scheduler or memory manager as features are added).
4. **Regression fixtures**: golden-file snapshots of `Kernel.snapshot()` after a fixed random seed + N ticks, to catch unintended behavioral drift when refactoring AI weights or algorithm internals.
5. **Frontend smoke test**: a Playwright script that loads the dashboard, waits for the first WebSocket message, and asserts key DOM elements populate (catches frontend/backend schema drift that unit tests can't).

## Manual QA checklist (pre-demo)

- [ ] Boot log renders and simulation starts ticking immediately on page load
- [ ] Switching scheduler algorithm live doesn't crash the tick loop mid-quantum
- [ ] Switching memory policy live doesn't orphan any frame (used_frames stays ≤ total_frames)
- [ ] Killing the currently-running process doesn't leave `scheduler.running` dangling
- [ ] Spawning 20+ processes in quick succession keeps the dashboard responsive
- [ ] Chat assistant answers all six quick-chip questions sensibly after a few hundred ticks
- [ ] Reset button fully reinitializes state (tick count back to 0, default processes respawned)
