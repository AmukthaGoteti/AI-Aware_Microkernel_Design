# AI System Design

## Design principle: explainability over horsepower

Every predictive/decision component in NOVA is chosen so that **any output can be traced back to an equation you can write on a whiteboard**. This is a deliberate trade-off: a trained neural net would technically satisfy "AI scheduling," but it would be un-auditable in a simulator whose entire value proposition is "understand and defend how the OS is making decisions." Each section below states the current interpretable implementation and the concrete upgrade path to a heavier model, so both bars ("build something real now" and "show you understand the research-grade version") are covered.

---

## 1. AI Scheduler (`backend/kernel/scheduler.py::Scheduler._ai_select`)

### Model
A linear, weighted multi-criteria scorer:

```
score(p) = w_burst · burst_norm(p) + w_priority · priority_norm(p) − w_starve · starve_norm(p)

where:
  burst_norm(p)    = predicted_burst(p) / max(predicted_burst over ready queue)
  priority_norm(p) = priority(p) / max(priority over ready queue)
  starve_norm(p)    = starvation_counter(p) / max(starvation_counter over ready queue)
  w_burst = 0.55, w_priority = 0.25, w_starve = 0.20
```

The process with the **lowest** score runs next (minimizing expected contribution to total wait time, similar in spirit to SJF, but priority- and fairness-aware).

**Burst prediction** uses exponential smoothing (a lightweight recursive filter, equivalent to an EWMA / first-order low-pass filter over each process's observed CPU-burst history):

```
predicted[0] = burst_history[0]
predicted[i] = α · burst_history[i] + (1 − α) · predicted[i−1],  α = 0.5
```

This is literally the same math as an **online reinforcement-learning value estimate under a fixed step size** — each new observation nudges the estimate rather than being averaged with equal weight to the ancient past, which matters for workloads whose burst distribution drifts over time.

**Hard anti-starvation override**: if any ready process has waited ≥ 20 ticks, it preempts the soft scoring entirely and is selected outright (ties broken by longest wait). This guarantees a bounded worst-case wait — a property that pure SJF/Priority scheduling famously lack, and a property the soft scoring term alone (see below) cannot *guarantee*, only make less likely.

**Dynamic quantum**: `compute_quantum()` shrinks the time slice for processes with high burst-time variance (more preemption → better responsiveness for bursty/interactive work) and grows it for low-variance CPU-bound processes (less context-switch overhead).

### Why these weights
Burst time dominates (0.55) because minimizing average waiting time is the classical SJF result (provably optimal for average wait, ignoring fairness). Priority (0.25) lets administrator/system-declared importance override raw burst estimates. Starvation (0.20, plus the hard override) exists because SJF/Priority alone can starve long jobs indefinitely — a well-known real-world failure mode this design explicitly targets.

### Upgrade path → Q-learning
Replace the fixed weights with a learned **Q-table or linear function approximator**:
- **State**: `(burst_bucket, priority_bucket, starvation_bucket, queue_length_bucket)` — discretize each dimension into 4–5 buckets for a tractable table, or keep them continuous and use a shallow (2-layer) linear/MLP function approximator.
- **Action**: which of the top-k ready processes to run.
- **Reward**: `-waiting_time_incurred_this_tick` (or `-turnaround_time` on completion), summed and discounted.
- **Update rule**: standard Q-learning `Q(s,a) ← Q(s,a) + η[r + γ·max_a' Q(s',a') − Q(s,a)]`.
- Train offline against historical/synthetic workload traces (the simulator already logs full `burst_history` per process — a ready-made dataset), then swap in the learned policy behind the same `pick_next()` interface with zero call-site changes.

---

## 2. Memory Prefetcher (`backend/kernel/memory.py::MemoryManager._ai_prefetch`)

### Model
A per-process **first-order Markov chain** over page-access sequences:

```
transition_counts[pid][page_a][page_b] += 1   (each time page_b immediately follows page_a)
predicted_next_page = argmax_b transition_counts[pid][last_page][b]
```

If a free frame exists and the predicted page isn't already resident, it is speculatively loaded (never by evicting another page — prefetching should never *cause* a fault). A "prefetch hit" is counted separately from a normal hit so the dashboard can show the tangible benefit of prefetching (`prefetch_hits` vs `page_faults`).

### Why Markov, not a neural sequence model
Working-set locality in real workloads is dominated by **short, repeated sequential/strided patterns** (loop bodies, array scans) — a first-order Markov chain captures the dominant signal with O(pages²) memory and zero training latency, which matters when the simulator has to "learn" a brand-new process's behavior within just a few ticks of it existing.

### Upgrade path → sequence models
A higher-order Markov chain (condition on the last *k* pages, not just 1) or an **LSTM/Transformer next-token predictor over page-ID sequences** would capture longer-range patterns (e.g. periodic access to a hash table's buckets) at the cost of needing meaningfully more history per process before predictions become reliable — a real trade-off worth stating explicitly in a systems interview.

---

## 3. AI System Monitor (`backend/ai/predictor.py`, `backend/ai/monitor.py`)

### CPU / memory forecasting
**Ordinary least squares linear regression** over a rolling window (default 40 samples) of utilization:

```
slope, intercept = argmin_(m,b) Σ (m·xᵢ + b − yᵢ)²   (closed-form normal equations)
predicted(t) = slope · t + intercept
ticks_until_threshold = (threshold − current_value) / slope     (if slope > 0)
```

**Confidence** scales with sample count (more history = more confident) and inversely with volatility (standard deviation of the window) — a simple but honest heuristic: `confidence = clamp(n/window · (1 − volatility/40), 0.05, 0.95)`.

### Anomaly detection
Rolling **z-score** per named metric stream (e.g. `"pid_7_cpu"`):

```
z = (value − rolling_mean) / rolling_std
is_anomaly = |z| > 2.3
confidence = min(0.97, |z| / (2 · threshold))
```

### Recommendations
`recommend_policy()` and `recommend_memory_optimization()` are **rule-based expert systems** over summary statistics (burst-time variance, I/O-bound ratio, priority spread, fault rate, fragmentation) — deliberately simple decision rules with natural-language justifications, matching how a senior SRE would reason about the same dashboard, not a trained classifier.

### Upgrade path
- Replace OLS with an **exponentially-weighted moving average + Holt-Winters** (trend + seasonality) forecaster for workloads with daily/periodic load patterns.
- Replace the rule-based recommender with a small **decision tree** trained on (workload features → best-performing algorithm in simulation) — decision trees remain fully interpretable (feature importances, printable rules) while adapting thresholds from data instead of hand-tuning them, which is the natural middle ground between "if/else rules" and "black-box net" for this specific use case.

---

## 4. Chat Assistant (`backend/ai/assistant.py`)

Deterministic **intent-matching NLU**: regex/keyword pattern → direct query against live kernel objects → templated natural-language response. This is intentionally *not* a call to an LLM: an OS diagnostics assistant that can hallucinate kernel internals is worse than useless. Every fact stated is read directly off `Kernel` state at answer time.

### Upgrade path
Two additive (not replacement) options, both preserving the "grounded in real state" guarantee:
1. **Retrieval-augmented LLM**: feed the same structured state snapshot into an LLM prompt as context, and constrain it to only synthesize/summarize across facts already present in that context (not to invent new ones) — useful for free-form phrasing variety without sacrificing grounding.
2. **Intent classifier**: replace hand-written regexes with a small trained classifier (e.g. TF-IDF + logistic regression, or a distilled sentence embedding + cosine-similarity match against a canonical question bank) purely for **routing** — the answer-generation step stays state-grounded either way.

---

## 5. Confidence scores — where they come from

| Component | Confidence formula |
|---|---|
| CPU/memory forecast | `clamp(n_samples/window · (1 − volatility/40), 0.05, 0.95)` |
| Anomaly detector | `min(0.97, |z| / (2 · z_threshold))` |
| Interrupt prediction | share of recency-weighted interrupt-type frequency in the last 40 events |
| AI scheduler decision | not a probability — the raw `score` value is shown directly, since it's a ranking signal, not a probability estimate (documented here to avoid over-claiming calibration it doesn't have) |

Being explicit that the scheduler's "score" is *not* a calibrated probability (unlike the forecaster's confidence) is itself part of presenting the system honestly — a subtlety worth calling out to an interviewer.
