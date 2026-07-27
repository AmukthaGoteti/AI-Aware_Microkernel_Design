# Development Roadmap (12 Weeks)

This roadmap assumes the current repository as **Week 0 baseline** (all items below marked ✅ already exist in this delivery) and lays out how a team or solo capstone student would carry it forward to a polished, defensible research prototype.

## Week 1 — Foundations & correctness hardening
- ✅ Core PCB/Thread model, boot sequence, tick loop
- ✅ FCFS / SJF / RR / Priority / MLQ schedulers
- Add property-based tests (Hypothesis) for scheduler invariants: no process runs with negative remaining burst, every process eventually reaches TERMINATED under FCFS/SJF/RR on finite workloads
- Add structured logging (Python `logging` module) alongside the in-memory event logs, for post-mortem debugging

## Week 2 — AI Scheduler v1
- ✅ Weighted scoring AI scheduler + exponential-smoothing burst predictor
- ✅ Hard anti-starvation override
- Add configurable weights via API (`POST /api/scheduler/ai-weights`) so the dashboard can expose live weight-tuning sliders
- Benchmark AI vs. SJF vs. Priority on synthetic workloads (bursty, uniform, heavy-tailed) and publish a comparison table in `docs/`

## Week 3 — Memory subsystem depth
- ✅ Paging, FIFO/LRU/LFU/Clock, Markov-chain AI prefetch
- Add segmentation model alongside paging (base/limit registers per segment) as an alternate memory view toggle
- Add a working-set / thrashing detector to the AI monitor (already partially covered by `fault_rate` recommendation — extend with per-process working-set size estimates)

## Week 4 — IPC & concurrency correctness
- ✅ Pipes, shared memory, mailboxes, signals
- Add a simple producer/consumer demo scenario using the pipe API with an explicit bounded-buffer capacity and blocking semantics (currently non-blocking with silent overwrite past `maxlen`)
- Add mutex/semaphore primitives and a classic dining-philosophers demo that can intentionally trigger the deadlock detector for teaching purposes

## Week 5 — Interrupts & device drivers
- ✅ Interrupt controller with priority queue + recency-weighted prediction
- ✅ 8 simulated devices
- Add per-device interrupt latency histograms to the dashboard
- Add a simple "driver crash" fault-injection endpoint (`POST /api/device/{name}/fault`) that raises a `DISPLAY`/`DISK` error state, exercising the AI monitor's anomaly detector against real device telemetry

## Week 6 — Deadlock & resource management
- ✅ Resource Allocation Graph + Banker's Algorithm + AI early warning
- Wire the Banker's algorithm into actual process resource requests (currently a standalone module exercised by tests, not yet driven by the tick loop) — spawn processes with declared max-claims and route `request()`/`release()` calls through the tick loop
- Add a scripted "induce deadlock" demo button to the dashboard toolbar

## Week 7 — Filesystem depth
- ✅ Directory tree, block allocator, journaling, chmod/permissions
- Add multi-block file fragmentation visualization (currently allocation is first-fit; add a "fragmented" demo mode)
- Add file read/write syscalls routed through `SecurityManager.check_file_access()` from the tick loop (currently a standalone API)

## Week 8 — Security & networking
- ✅ Privilege rings, syscall gating, audit log
- ✅ Sockets, packets, weighted-fair bandwidth sharing
- Surface the security audit log and network socket table in the dashboard (currently returned by the API but not yet rendered — see `docs/FUTURE.md`)
- Add a simple TCP three-way-handshake state machine per socket (SYN/SYN-ACK/ACK/ESTABLISHED/FIN) for teaching value

## Week 9 — AI System Monitor v2
- ✅ CPU/memory trend forecasting, anomaly detection, policy/memory recommendations, health score
- Add the decision-tree-based scheduling recommender described in `docs/AI_DESIGN.md` (train on simulated workload traces → best algorithm)
- Add a "what-if" endpoint: simulate N ticks ahead under a candidate policy change and report the projected health-score delta before committing to the switch

## Week 10 — Chat assistant v2 & UX polish
- ✅ Deterministic intent-matching assistant grounded in live state
- Expand assistant coverage (currently ~15 intents) with a canonical question bank + fuzzy matching fallback
- Frontend: add a Gantt-chart view of the last 200 ticks of scheduling decisions (data already exists in `PCB.history`, needs a rendering pass)
- Frontend: add a heatmap view of memory frame occupancy over time

## Week 11 — Testing, benchmarking, and documentation
- ✅ Baseline pytest suite (scheduler, memory, deadlock)
- Add integration tests that drive the FastAPI app via `TestClient` + WebSocket, asserting full-snapshot schema stability
- Add a load-test script exercising 500+ simulated processes to validate the tick loop's O(n) scaling assumptions
- ✅ Architecture, AI design, API, diagrams, roadmap docs (this delivery)

## Week 12 — Deployment & presentation
- ✅ Local `uvicorn` run instructions
- Containerize with Docker + docker-compose (see `docs/DEPLOYMENT.md`)
- Record a scripted demo walkthrough (see `docs/DEMO_SCENARIOS.md`) as a screen-capture video for portfolio/interview use
- Prepare a one-page project summary + architecture diagram export (PNG) for resume/LinkedIn attachment

---

## Suggested team split (if not solo)
- **Kernel engineer**: scheduler, memory, IPC, interrupts, deadlock (Weeks 1–6)
- **Systems/security engineer**: filesystem, security, networking (Weeks 7–8)
- **AI/ML engineer**: predictor, monitor, assistant, Q-learning upgrade path (Weeks 2, 9–10)
- **Frontend engineer**: dashboard, Gantt chart, heatmaps (Weeks 10, ongoing)
- **QA/DevOps**: testing, Docker, CI (Week 11–12)
