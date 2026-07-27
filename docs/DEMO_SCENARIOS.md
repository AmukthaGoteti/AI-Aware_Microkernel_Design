# Demo Scenarios

Scripted walkthroughs for presenting NOVA in a capstone defense, portfolio review, or technical interview. Each scenario states the action, what to point at on screen, and the talking point it demonstrates.

---

## Scenario 1 — "Watch the AI explain itself" (2 minutes)

1. Load the dashboard; let it run for ~15 seconds untouched.
2. Point at the **Running** box — read the `ai_reason` string out loud as it changes each time the process switches.
3. Talking point: *"Every scheduling decision comes with a plain-English justification computed from the actual score, not a canned string — you can verify the math in `scheduler.py`."*
4. Ask the AI console: **"Optimize scheduling"** — read back the recommendation and reason.
5. Talking point: *"The recommender looked at burst-time variance and I/O-bound ratio across the live workload to make that call — it's a rule-based expert system, not a black box, so I can defend exactly why it said that."*

## Scenario 2 — "Starvation, and how the AI scheduler fixes it" (3 minutes)

1. Switch the scheduler to **Priority** using the toolbar dropdown.
2. Spawn several high-priority processes back to back with **+ Spawn Process** (repeat 4–5 times, leaving default priority near 1–2).
3. Watch the Process Table — point out a low-priority process's **Wait** column climbing steadily; it may never run under pure Priority scheduling.
4. Switch the scheduler back to **AI**.
5. Watch the same process get picked up — check the AI console: **"Why is process N waiting"** before the switch, and again after.
6. Talking point: *"Pure Priority scheduling can starve low-priority work indefinitely — that's a textbook failure mode. The AI scheduler has both a soft starvation term in its scoring function and a hard 20-tick override that guarantees no process waits forever. I can show you the exact override logic in `scheduler.py::_ai_select`."*

## Scenario 3 — "Page replacement policies, side by side" (3 minutes)

1. Click **🧠 Memory Pressure** a few times to force faults/eviction.
2. Watch the **Virtual Memory** frame grid — amber cells = occupied frames.
3. Switch **Page Policy** from LRU → FIFO → Clock, clicking Memory Pressure again after each switch.
4. Point at **Page faults / hits** and **Fragmentation** — compare fault-rate behavior across policies under the same synthetic pressure.
5. Ask the AI console: **"Show page faults"**.
6. Talking point: *"Notice the AI prefetch hit counter — that's a Markov chain learning each process's page-access sequence and speculatively loading the predicted next page before a fault happens. It never evicts anything to do this, it only prefetches into frames that are already free, so it can only help, never hurt."*

## Scenario 4 — "Deadlock: detection vs. avoidance" (3 minutes)

1. Ask the AI console: **"Explain deadlock"** — note the baseline "no cycle" response.
2. Talking point: *"Two separate mechanisms are wired up here: `ResourceAllocationGraph.detect_cycle()` for reactive detection via DFS cycle-finding on a wait-for graph, and a full Banker's Algorithm implementation for proactive avoidance — see `tests/test_deadlock.py` for both being exercised directly."*
3. Point at the **Deadlock risk** indicator in the AI Monitor panel.
4. Talking point: *"This doesn't wait for an actual cycle to form — it trends the blocked-process ratio over the last 30 samples and flags rising contention early, which is closer to how a real production monitoring system (like a APM's saturation alert) would behave, versus a textbook detector that's a lagging indicator by definition."*

## Scenario 5 — "Interrupt-driven I/O and device abstraction" (2 minutes)

1. Click **Inject IRQ → Disk**, then **Keyboard**, then **Network** in quick succession.
2. Point at the **Interrupt Timeline** — note the latency column (ticks between raise and service).
3. Point at **Device Activity** — pulsing dots indicate busy devices.
4. Ask the AI console: **"Predict next interrupt"**.
5. Talking point: *"The predictor is a recency-weighted frequency model over the last 40 interrupts — it's intentionally simple so it adapts within seconds to a changing interrupt mix, which matters more for this use case than modeling long-range dependencies would."*

## Scenario 6 — "Live algorithm A/B comparison" (4 minutes, best for technical interviews)

1. Reset the simulation (**⟲ Reset**).
2. Let it run 200 ticks under **SJF**; note **Metrics** panel: avg turnaround, avg waiting, avg response, throughput.
3. Reset again, switch to **AI**, run another 200 ticks, compare the same four numbers.
4. Talking point: *"SJF is provably optimal for average waiting time under perfect burst knowledge — but it doesn't know future arrivals and it can starve long jobs. The AI scheduler trades a small amount of that theoretical optimality for bounded worst-case wait and adaptability to burst-time drift via exponential smoothing. This comparison is exactly the kind of trade-off analysis I'd want to walk through in a systems design interview."*

---

## Presentation tips

- Keep the dashboard at **2×–4× speed** during live demos so state visibly changes without long silent gaps.
- The **Reset** button is your safety net — if a scripted scenario goes sideways, reset and restart the script rather than debugging live.
- Have `docs/AI_DESIGN.md` and `docs/ARCHITECTURE.md` open in a second window/tab in case a reviewer asks "show me the code for that" — every talking point above maps to a specific file and function.
