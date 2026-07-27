# NOVA — AI-Aware Microkernel Operating System Simulator

> A research-prototype-grade simulation of a microkernel OS whose scheduler, memory manager, and system monitor are augmented with lightweight, *explainable* AI — built to be read, extended, and defended in an interview or a thesis committee.

![status](https://img.shields.io/badge/status-working_prototype-4fd699) ![python](https://img.shields.io/badge/python-3.10%2B-5ec8f8) ![license](https://img.shields.io/badge/license-MIT-9fb0c3)

---

## What this is

NOVA is a full-stack simulation of an operating system's microkernel core — process/thread management, five classical CPU schedulers plus one AI scheduler, paged virtual memory with four replacement policies and an AI prefetcher, kernel-mediated IPC, an interrupt controller, device driver stubs, deadlock detection (Resource Allocation Graph + Banker's Algorithm), a toy filesystem with journaling, privilege separation, a minimal network stack, and an AI system monitor that narrates what it's doing in plain English. Everything streams live over a WebSocket into a single-page console you can watch, poke, and interrogate.

It is **not** a toy "bubble-sort visualizer." Every subsystem is a real, testable Python module with actual data structures (page tables, resource-allocation graphs, wait-for graphs, journals) — the AI layer sits *on top of* correct OS mechanics, not in place of them.

## Why the AI is designed this way

Every "AI" component here is intentionally interpretable rather than a black-box neural net:

| Component | Technique | Why |
|---|---|---|
| AI Scheduler | Weighted multi-factor scoring (predicted burst via exponential smoothing + priority + starvation term) with a hard anti-starvation override | Every decision emits a human-readable reason string — you can *defend* every choice in an interview |
| Memory Prefetcher | Markov-chain next-page frequency model | Learns real access patterns per process without needing training data or GPUs |
| AI System Monitor | OLS linear-trend extrapolation + z-score anomaly detection | Confidence-scored, mathematically transparent forecasting — "CPU predicted to exceed 95% in 20 ticks (72% confidence)" is *computed*, not invented |
| Chat Assistant | Deterministic intent-matching over live kernel state | Zero hallucination risk: it can only say what the simulator's actual data structures say |

A production upgrade path (replacing the exponential-smoothing predictor with an LSTM, the scoring scheduler with a trained Q-learning agent, etc.) is documented in [`docs/AI_DESIGN.md`](docs/AI_DESIGN.md) and the [roadmap](docs/ROADMAP.md) — deliberately *not* built by default, so the baseline stays instantly runnable with zero model downloads or GPU dependency.

## Quick start

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** — the dashboard is served by the same FastAPI process, no separate frontend build step required.

Run the test suite:

```bash
pip install pytest
pytest tests/ -v
```

## Project layout

```
ai-microkernel-os/
├── backend/
│   ├── kernel/            # core OS simulation (pure Python, framework-free)
│   │   ├── process.py     # PCB / Thread models
│   │   ├── scheduler.py   # FCFS, SJF, RR, Priority, MLQ, AI
│   │   ├── memory.py      # paging, FIFO/LRU/LFU/Clock, AI prefetch
│   │   ├── ipc.py         # pipes, shared memory, mailboxes, signals
│   │   ├── interrupts.py  # interrupt controller + timeline + prediction
│   │   ├── devices.py     # device driver abstraction
│   │   ├── deadlock.py    # Resource Allocation Graph + Banker's Algorithm
│   │   ├── filesystem.py  # directories, files, permissions, journaling
│   │   ├── security.py    # privilege rings, syscall gating
│   │   ├── network.py     # sockets, packets, loopback, bandwidth sharing
│   │   └── kernel.py       # boot sequence + tick loop orchestrator
│   ├── ai/
│   │   ├── predictor.py   # TrendPredictor, AnomalyDetector (stats primitives)
│   │   ├── monitor.py     # AISystemMonitor (predictions + recommendations)
│   │   └── assistant.py   # ChatAssistant (NL Q&A over live state)
│   ├── main.py             # FastAPI app: REST + WebSocket + static serving
│   └── requirements.txt
├── frontend/
│   └── index.html          # single-file real-time dashboard (vanilla JS + Chart.js)
├── docs/                    # architecture, AI design, roadmap, diagrams, API, etc.
├── tests/                   # pytest suite (scheduler, memory, deadlock)
└── README.md
```

## Documentation index

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture, microkernel communication, memory layout
- [`docs/AI_DESIGN.md`](docs/AI_DESIGN.md) — every AI model's design, math, and upgrade path
- [`docs/API.md`](docs/API.md) — REST + WebSocket API reference
- [`docs/DIAGRAMS.md`](docs/DIAGRAMS.md) — Mermaid architecture/sequence/flow diagrams
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — 12-week development roadmap
- [`docs/TESTING.md`](docs/TESTING.md) — testing strategy
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — local, Docker, and cloud deployment
- [`docs/DEMO_SCENARIOS.md`](docs/DEMO_SCENARIOS.md) — scripted demo walkthroughs
- [`docs/FUTURE.md`](docs/FUTURE.md) — future enhancements

## Demo controls

The dashboard toolbar lets you: play/pause/step the simulation, change speed (0.5×–8×), switch the CPU scheduler live (FCFS/SJF/RR/Priority/MLQ/AI), switch the page replacement policy (FIFO/LRU/LFU/Clock), spawn a process, generate a batch workload, trigger memory pressure, and inject interrupts (keyboard/disk/network/sensor) — all while the AI console answers plain-English questions about what's happening.

## License

MIT — see `LICENSE`. Built as a portfolio-grade capstone reference implementation.