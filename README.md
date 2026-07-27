# AI-Aware Microkernel OS — Simulation

A single-file, browser-based simulation of a microkernel operating system: process scheduling, virtual memory, IPC, interrupts, devices, deadlock detection, a filesystem, basic networking, and a small AI engine that predicts, explains, and recommends — all running live in one interactive dashboard.

## Files

| File | Description |
|---|---|
| `ai-microkernel-os.html` | The full simulation as a standalone HTML file. Just open it in a browser — no build step, no install. |
| `CAPSTONE.md` | Academic write-up covering the OS concepts, algorithms, and design decisions behind the simulation. |
| `README.md` | This file. |

## Running it

Open `ai-microkernel-os.html` in any modern browser (Chrome, Firefox, Safari, Edge). It needs an internet connection on first load, since it pulls React, Babel, Tailwind, and the icon set from public CDNs at runtime — there's nothing to install locally.

The simulation starts running automatically. Use the **Run/Pause** button and the speed slider in the top bar to control the tick rate.

## What's inside

The left-hand navigation switches between ten panels, all reading from one shared, continuously-ticking kernel state:

- **Dashboard** — CPU utilization, ready-queue length, fault rate, deadlock risk, a live scheduler ring visualization, kernel log, and the AI recommendation feed.
- **Scheduler** — switch between FCFS, SJF, Round Robin, Priority, MLFQ, and an AI-driven scheduler; inspect the process table and, for the AI mode, the trained regression weights and per-decision explanations.
- **Memory** — switch between FIFO, LRU, LFU, and CLOCK page replacement; watch the physical frame table fill and evict, and see the AI Markov-based prefetcher fire.
- **IPC** — a bounded pipe, shared memory with a lock, an async message queue, and POSIX-style signals (SIGSTOP/SIGCONT/SIGKILL) you can send to any live process.
- **Interrupts** — the interrupt vector table, per-device counts, and a live interrupt log.
- **Devices** — disk head position, keyboard buffer, display, UART, GPIO pins, and network throughput.
- **Deadlock** — a Banker's-algorithm instance you can run on demand, plus a continuously updated AI risk heuristic; grant/release resources and watch the risk score move.
- **Filesystem** — a directory tree over a disk block bitmap; create and delete files.
- **Network** — a socket table and animated in-flight TCP/UDP packets.
- **AI assistant** — ask questions like *"why did pid 3 run"*, *"what's the page fault rate"*, or *"deadlock risk"* and get a live answer generated from current kernel state.

See `CAPSTONE.md` for a full explanation of the algorithms and design rationale behind each subsystem.

## Tech notes

- Built with React 18 and Tailwind, both loaded from CDN, with JSX compiled in-browser by Babel Standalone — so the whole app is one `.html` file with no build tooling.
- Icons are from [lucide-react](https://lucide.dev/).
- All simulation state lives in a single in-memory object; nothing is persisted, so refreshing the page resets the simulation.