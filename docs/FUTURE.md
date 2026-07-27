# Future Enhancements

Organized by subsystem, ordered roughly by effort-to-value ratio within each section. Items already covered by the 12-week roadmap are cross-referenced rather than duplicated.

## Scheduling
- Multi-core / SMP simulation: extend `Scheduler` to manage N run-queues with CPU affinity actually enforced (the `PCB.cpu_affinity` field already exists but isn't consulted by `pick_next()` yet)
- Real Q-learning agent replacing the weighted-scoring AI scheduler (design fully specified in `docs/AI_DESIGN.md` §1)
- Gang scheduling for related process groups (e.g. a process and its spawned threads scheduled together)
- Live weight-tuning sliders in the dashboard for the AI scheduler's `w_burst / w_priority / w_starve` (currently hardcoded)

## Memory
- Segmentation model as an alternate/complementary view to paging (base/limit registers)
- Copy-on-write semantics for `fork()`-style process creation
- NUMA-awareness simulation (frame "distance" cost from a given virtual core)
- Higher-order Markov chain or LSTM sequence model for prefetching (see `docs/AI_DESIGN.md` §2 upgrade path)

## IPC
- Blocking semaphore/mutex primitives with a classic dining-philosophers or producer-consumer teaching scenario
- Proper backpressure on pipes (currently a `deque(maxlen=32)` silently drops the oldest entry rather than blocking the writer)
- Named pipes with filesystem-visible paths (`/tmp/mypipe`-style), unifying the IPC and filesystem subsystems

## Filesystem
- Real inode indirect-block structure for large files (currently a flat block list, fine for small simulated files but not representative of a real inode design)
- Full redo/undo journaling (currently a flat commit-status log, not a true write-ahead log with replay)
- Quota enforcement per user

## Security
- Surface the audit log and privilege-mode indicator in the dashboard (data already flows through the API, just not rendered — see `TESTING.md` manual QA checklist)
- Capability-based security model as an alternative to the current ACL/privilege-ring model, for comparison
- Simulated TLS handshake on top of the TCP socket state machine

## Networking
- Full TCP state machine (SYN/SYN-ACK/ESTABLISHED/FIN-WAIT/etc.) per socket
- Simulated packet loss / retransmission for teaching congestion control
- Multiple network interfaces with simulated routing between them

## AI / Monitoring
- Decision-tree-based scheduling recommender trained on simulated workload traces (see `docs/AI_DESIGN.md` §3 upgrade path)
- "What-if" simulation: fork the current state, run N ticks under a candidate policy change, report projected health-score delta before committing
- Export historical metrics (turnaround/waiting/throughput over time) as CSV for offline analysis in pandas/Jupyter
- Retrieval-augmented LLM option for the chat assistant, strictly constrained to the live-state context (see `docs/AI_DESIGN.md` §4)

## Visualization
- Gantt chart of the last 200 ticks of scheduling decisions (data already exists in `PCB.history`)
- Memory frame occupancy heatmap over time
- Network packet flow animation between process nodes
- Dark/light theme toggle; currently dark-only "system console" aesthetic

## Platform / Ops
- Docker + docker-compose packaging (see `docs/DEPLOYMENT.md`)
- Externalized state (Redis) for horizontal scaling across multiple server instances
- Prometheus metrics endpoint (`/metrics`) exposing tick rate, fault rate, health score as time series for a Grafana dashboard
- CI pipeline (GitHub Actions) running `pytest` + a frontend smoke test on every push

## Research extensions (grad-school-application-worthy)
- Formal comparison of the AI scheduler against theoretical optimal (SJF lower bound) across a battery of synthetic workload distributions, published as a short paper/report
- Ablation study on the AI scheduler's weight vector (`w_burst`, `w_priority`, `w_starve`) — sweep values and report Pareto frontier of (avg waiting time) vs (max waiting time / starvation bound)
- Extend the deadlock early-warning model with a proper time-series anomaly detection benchmark (compare the current z-score approach against an isolation forest or a simple LSTM autoencoder on the same contention-ratio stream)
