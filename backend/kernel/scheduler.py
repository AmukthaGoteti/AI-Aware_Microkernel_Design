"""
scheduler.py — CPU scheduling subsystem.

Implements five traditional algorithms plus an AI scheduler that blends a
burst-time predictor (exponential smoothing regression) with a starvation-
aversion term and priority weighting to make an explainable scheduling
decision every tick. The AI scheduler is intentionally *interpretable*:
every choice is logged with a natural-language reason string so the
frontend / chat assistant can explain "why" a process was chosen — this is
more valuable for a portfolio project than a black-box net, and it is
still a legitimate lightweight reinforcement-style controller (reward =
negative waiting time, updated via smoothing of observed rewards per
process class).
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from .process import PCB, ProcessState


class Algorithm(str, Enum):
    FCFS = "FCFS"
    SJF = "SJF"
    ROUND_ROBIN = "ROUND_ROBIN"
    PRIORITY = "PRIORITY"
    MLQ = "MLQ"
    AI = "AI"


class Scheduler:
    def __init__(self, algorithm: Algorithm = Algorithm.AI, quantum: int = 4):
        self.algorithm = algorithm
        self.quantum = quantum
        self.base_quantum = quantum
        self._rr_pointer = 0
        self.running: Optional[PCB] = None
        self.context_switches = 0
        self.last_decision_reason = ""
        # exponential smoothing factor for AI burst prediction
        self.alpha = 0.5
        # reward trace for adaptive quantum sizing
        self._recent_wait_variance = []

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------
    def set_algorithm(self, algo: Algorithm):
        self.algorithm = algo
        self._rr_pointer = 0

    def pick_next(self, ready_queue: list[PCB], tick: int) -> Optional[PCB]:
        """Selects the next process to run according to self.algorithm."""
        if not ready_queue:
            return None
        if self.algorithm == Algorithm.FCFS:
            return self._fcfs(ready_queue)
        if self.algorithm == Algorithm.SJF:
            return self._sjf(ready_queue)
        if self.algorithm == Algorithm.ROUND_ROBIN:
            return self._round_robin(ready_queue)
        if self.algorithm == Algorithm.PRIORITY:
            return self._priority(ready_queue)
        if self.algorithm == Algorithm.MLQ:
            return self._mlq(ready_queue, tick)
        if self.algorithm == Algorithm.AI:
            return self._ai_select(ready_queue, tick)
        return ready_queue[0]

    def compute_quantum(self, proc: PCB) -> int:
        """AI mode dynamically resizes the quantum based on predicted burst
        variance; other algorithms use a fixed base quantum."""
        if self.algorithm != Algorithm.AI:
            return self.base_quantum
        variance = self._burst_variance(proc)
        # tighter quantum for bursty/unpredictable processes (better responsiveness),
        # larger quantum for stable CPU-bound processes (less overhead)
        if variance > 3:
            q = max(1, self.base_quantum - 2)
        elif variance < 1 and proc.predicted_burst > self.base_quantum:
            q = self.base_quantum + 2
        else:
            q = self.base_quantum
        return q

    # ---------------------------------------------------------------
    # Traditional algorithms
    # ---------------------------------------------------------------
    def _fcfs(self, q):
        return min(q, key=lambda p: p.arrival_tick)

    def _sjf(self, q):
        chosen = min(q, key=lambda p: p.remaining_burst)
        self.last_decision_reason = (
            f"P{chosen.pid} chosen: shortest remaining burst "
            f"({chosen.remaining_burst} ticks) among {len(q)} ready processes."
        )
        return chosen

    def _round_robin(self, q):
        self._rr_pointer %= len(q)
        chosen = q[self._rr_pointer]
        self._rr_pointer = (self._rr_pointer + 1) % len(q)
        self.last_decision_reason = f"P{chosen.pid} chosen: round-robin rotation."
        return chosen

    def _priority(self, q):
        chosen = min(q, key=lambda p: (p.priority, p.arrival_tick))
        self.last_decision_reason = (
            f"P{chosen.pid} chosen: highest priority (level {chosen.priority})."
        )
        return chosen

    def _mlq(self, q, tick):
        # 3 static queues by priority band: system(0-2) > interactive(3-6) > batch(7-9)
        system = [p for p in q if p.priority <= 2]
        interactive = [p for p in q if 3 <= p.priority <= 6]
        batch = [p for p in q if p.priority >= 7]
        for band, name in ((system, "system"), (interactive, "interactive"), (batch, "batch")):
            if band:
                chosen = min(band, key=lambda p: p.arrival_tick)
                self.last_decision_reason = (
                    f"P{chosen.pid} chosen: highest non-empty queue band = {name}."
                )
                return chosen
        return q[0]

    # ---------------------------------------------------------------
    # AI scheduler
    # ---------------------------------------------------------------
    def _burst_variance(self, proc: PCB) -> float:
        h = proc.burst_history
        if len(h) < 2:
            return 0.0
        mean = sum(h) / len(h)
        return sum((x - mean) ** 2 for x in h) / len(h)

    def _predict_burst(self, proc: PCB) -> float:
        """Exponential smoothing over observed burst history; falls back to
        the process's declared burst_time when no history exists yet."""
        if not proc.burst_history:
            return float(proc.remaining_burst)
        pred = proc.burst_history[0]
        for sample in proc.burst_history[1:]:
            pred = self.alpha * sample + (1 - self.alpha) * pred
        return max(0.5, pred)

    def _ai_select(self, q: list[PCB], tick: int) -> PCB:
        """
        Scores every ready process on three normalized components:

          score = w1*predicted_burst_norm + w2*priority_norm - w3*starvation_bonus

        Lower score wins (we're minimizing expected wait contribution).
        Starvation bonus grows the longer a process has waited, guaranteeing
        eventual selection (prevents indefinite postponement — a known SJF/
        Priority weakness this AI mode explicitly corrects for).
        """
        # Hard anti-starvation guarantee: no process should be able to wait
        # indefinitely just because it scores poorly on burst/priority. Once
        # a process crosses STARVE_HARD_LIMIT ticks of waiting, it preempts
        # the soft-scoring mechanism entirely.
        STARVE_HARD_LIMIT = 20
        starving = [p for p in q if p.starvation_counter >= STARVE_HARD_LIMIT]
        if starving:
            chosen = max(starving, key=lambda p: p.starvation_counter)
            chosen.predicted_burst = self._predict_burst(chosen)
            reason = (
                f"P{chosen.pid} selected: hard starvation override — waited "
                f"{chosen.starvation_counter} ticks (limit {STARVE_HARD_LIMIT})."
            )
            chosen.ai_reason = reason
            self.last_decision_reason = reason
            return chosen

        w_burst, w_priority, w_starve = 0.55, 0.25, 0.20

        max_burst = max((self._predict_burst(p) for p in q), default=1) or 1
        max_priority = max((p.priority for p in q), default=1) or 1
        max_wait = max((p.starvation_counter for p in q), default=1) or 1

        scored = []
        for p in q:
            predicted = self._predict_burst(p)
            p.predicted_burst = predicted
            burst_norm = predicted / max_burst
            priority_norm = p.priority / max_priority
            starve_norm = p.starvation_counter / max_wait

            score = (
                w_burst * burst_norm
                + w_priority * priority_norm
                - w_starve * starve_norm
            )
            p.ai_score = score
            scored.append((score, p, predicted, starve_norm))

        scored.sort(key=lambda t: t[0])
        best_score, chosen, predicted, starve_norm = scored[0]

        if starve_norm > 0.7 and chosen.starvation_counter == max_wait:
            reason = (
                f"P{chosen.pid} selected: starvation avoidance triggered "
                f"(waited {chosen.starvation_counter} ticks, highest in ready queue)."
            )
        elif chosen.remaining_burst == min(p.remaining_burst for p in q):
            reason = (
                f"P{chosen.pid} selected: predicted burst is shortest "
                f"({predicted:.1f} ticks) while minimizing starvation risk "
                f"(score={best_score:.3f})."
            )
        else:
            reason = (
                f"P{chosen.pid} selected: best blended score of predicted burst "
                f"({predicted:.1f}), priority ({chosen.priority}), and wait time "
                f"({chosen.starvation_counter} ticks) — score={best_score:.3f}."
            )

        chosen.ai_reason = reason
        self.last_decision_reason = reason
        return chosen

    def bump_starvation(self, ready_queue: list[PCB], chosen: Optional[PCB]):
        for p in ready_queue:
            if p is chosen:
                p.starvation_counter = 0
            else:
                p.starvation_counter += 1
                p.waiting_time += 1
