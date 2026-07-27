"""
monitor.py — AI System Monitor.

The "AI assistant living inside the OS". Consumes live kernel state each
tick and produces:
  - CPU overload predictions (ticks-until-threshold, confidence)
  - Memory exhaustion predictions
  - Starvation detection (already-fair-warning from the scheduler, restated
    in natural language)
  - Deadlock risk (delegates to DeadlockMonitor)
  - Scheduling-policy recommendations based on observed workload shape
  - Inefficient-process flags (high context-switch-to-progress ratio,
    thrashing processes with high fault rate)
  - Health score: a single 0-100 composite metric for the dashboard
"""

from __future__ import annotations
from .predictor import TrendPredictor, AnomalyDetector


class AISystemMonitor:
    def __init__(self):
        self.cpu_trend = TrendPredictor(window=40)
        self.mem_trend = TrendPredictor(window=40)
        self.anomaly = AnomalyDetector()
        self.recommendations: list[str] = []

    def observe(self, cpu_util: float, mem_util: float):
        self.cpu_trend.add_sample(cpu_util)
        self.mem_trend.add_sample(mem_util)

    def cpu_overload_prediction(self, threshold=95.0) -> dict:
        ticks = self.cpu_trend.ticks_until_threshold(threshold)
        forecast = self.cpu_trend.forecast(ticks_ahead=20)
        if ticks is not None and ticks < 60:
            message = (
                f"CPU utilization is predicted to exceed {threshold:.0f}% "
                f"in approximately {ticks} ticks (confidence {forecast['confidence']*100:.0f}%)."
            )
        elif forecast["slope_per_tick"] < 0:
            message = "CPU utilization trend is declining; no overload expected."
        else:
            message = "CPU utilization is stable; no imminent overload predicted."
        return {"ticks_until_overload": ticks, "message": message, **forecast}

    def memory_exhaustion_prediction(self, threshold=98.0) -> dict:
        ticks = self.mem_trend.ticks_until_threshold(threshold)
        forecast = self.mem_trend.forecast(ticks_ahead=20)
        if ticks is not None and ticks < 60:
            message = (
                f"Memory usage is trending toward exhaustion — "
                f"~{ticks} ticks to {threshold:.0f}% (confidence {forecast['confidence']*100:.0f}%)."
            )
        else:
            message = "Memory usage trend is within safe bounds."
        return {"ticks_until_exhaustion": ticks, "message": message, **forecast}

    def detect_starvation(self, processes: list) -> list[dict]:
        flagged = []
        for p in processes:
            if p.starvation_counter > 15:
                flagged.append({
                    "pid": p.pid,
                    "name": p.name,
                    "waited": p.starvation_counter,
                    "message": f"P{p.pid} ({p.name}) has waited {p.starvation_counter} ticks without running — possible starvation."
                })
        return flagged

    def detect_inefficient_processes(self, processes: list, fault_rate_by_pid: dict) -> list[dict]:
        flagged = []
        for p in processes:
            progress = p.burst_time - p.remaining_burst
            if p.context_switches > 5 and progress < p.context_switches:
                flagged.append({
                    "pid": p.pid, "name": p.name,
                    "reason": f"{p.context_switches} context switches but only {progress} ticks of progress — high scheduling overhead relative to work done.",
                })
            fr = fault_rate_by_pid.get(p.pid)
            if fr is not None and fr > 0.5:
                flagged.append({
                    "pid": p.pid, "name": p.name,
                    "reason": f"Page fault rate {fr*100:.0f}% — likely thrashing; consider more resident pages or a different working-set size.",
                })
        return flagged

    def recommend_policy(self, processes: list, current_algo: str) -> dict:
        if not processes:
            return {"recommendation": current_algo, "reason": "No active processes to evaluate."}
        bursts = [p.burst_time for p in processes]
        mean_burst = sum(bursts) / len(bursts)
        variance = sum((b - mean_burst) ** 2 for b in bursts) / len(bursts)
        io_bound_ratio = sum(1 for p in processes if p.io_bound) / len(processes)
        priorities = {p.priority for p in processes}

        if variance > (mean_burst ** 1.5) and len(processes) > 3:
            rec, reason = "AI", "High burst-time variance detected — the AI scheduler's blended scoring outperforms static SJF/Priority here."
        elif io_bound_ratio > 0.5:
            rec, reason = "ROUND_ROBIN", "Majority I/O-bound workload — Round Robin improves interactivity/responsiveness."
        elif len(priorities) > 3:
            rec, reason = "MLQ", "Wide spread of priority levels — a Multilevel Queue better isolates system/interactive/batch classes."
        elif variance < mean_burst * 0.3:
            rec, reason = "SJF", "Low burst-time variance — SJF minimizes average waiting time safely (low starvation risk here)."
        else:
            rec, reason = "PRIORITY", "Workload has clear priority differentiation without high variance."

        return {"recommendation": rec, "reason": reason, "current": current_algo,
                "changed": rec != current_algo}

    def recommend_memory_optimization(self, mem_stats: dict) -> dict:
        fault_rate = mem_stats.get("fault_rate", 0)
        frag = mem_stats.get("fragmentation", 0)
        if fault_rate > 0.4:
            return {"recommendation": "Switch to LRU or enable more aggressive AI prefetching",
                    "reason": f"Fault rate is {fault_rate*100:.0f}% — current policy is thrashing under this workload."}
        if frag > 0.5:
            return {"recommendation": "Run compaction / prefer contiguous allocation",
                    "reason": f"Fragmentation estimate is {frag*100:.0f}% — free frames are scattered."}
        return {"recommendation": "No change needed", "reason": "Memory subsystem is operating efficiently."}

    def health_score(self, cpu_util, mem_util, fault_rate, blocked_ratio, deadlock_risk: str) -> dict:
        # Note: high CPU utilization alone is *good* (the scheduler is keeping
        # the core busy) — only sustained near-saturation combined with other
        # pressure signals should hurt the score, so the CPU term uses a much
        # higher threshold than memory/fault/blocked terms.
        score = 100.0
        score -= max(0, cpu_util - 97) * 3.0
        score -= max(0, mem_util - 85) * 1.2
        score -= fault_rate * 35
        score -= blocked_ratio * 25
        score -= {"low": 0, "medium": 12, "high": 30}.get(deadlock_risk, 0)
        score = max(0, min(100, score))
        if score > 85:
            verdict = "Healthy"
        elif score > 60:
            verdict = "Fair — minor pressure detected"
        elif score > 35:
            verdict = "Degraded — attention recommended"
        else:
            verdict = "Critical — immediate attention required"
        return {"score": round(score, 1), "verdict": verdict}
