"""
assistant.py — In-OS AI chat assistant.

Answers natural-language questions about the *live* simulator state. This
is deliberately a deterministic, explainable NLU (keyword/intent matching
over the kernel's own data structures) rather than a call out to an LLM:
every answer is grounded in and traceable to actual simulator state, which
is exactly what you want for an OS diagnostics assistant — no hallucinated
kernel internals.
"""

from __future__ import annotations
import re


class ChatAssistant:
    def __init__(self, kernel):
        self.kernel = kernel  # reference to the running Kernel instance

    def answer(self, question: str) -> str:
        q = question.lower().strip()
        k = self.kernel

        m = re.search(r"why is (?:process |p)?(\d+)", q) or re.search(r"process (\d+)", q)
        if m and ("wait" in q or "why" in q or "block" in q):
            pid = int(m.group(1))
            proc = k.processes.get(pid)
            if not proc:
                return f"No process with PID {pid} exists right now."
            if proc.state.value == "RUNNING":
                return f"P{pid} ({proc.name}) is currently RUNNING on the CPU."
            if proc.state.value in ("BLOCKED", "WAITING_IO"):
                return (f"P{pid} ({proc.name}) is {proc.state.value}, waiting on I/O or a resource. "
                        f"It has been waiting {proc.starvation_counter} ticks.")
            if proc.state.value == "READY":
                reason = proc.ai_reason or "Not yet evaluated by the scheduler this tick."
                return (f"P{pid} ({proc.name}) is READY, waiting for CPU allocation "
                        f"({proc.starvation_counter} ticks in queue). Scheduler note: {reason}")
            return f"P{pid} ({proc.name}) is currently {proc.state.value}."

        if "page fault" in q or "page-fault" in q:
            stats = k.memory.stats()
            return (f"Page faults so far: {stats['page_faults']} (hit rate "
                    f"{100*(1-stats['fault_rate']):.1f}%). AI prefetching has saved "
                    f"{stats['prefetch_hits']} would-be faults. Current policy: {stats['policy']}.")

        if "next interrupt" in q or ("predict" in q and "interrupt" in q):
            pred = k.interrupts.predict_next()
            return f"Most likely next interrupt: {pred['irq']} (confidence {pred['confidence']*100:.0f}%). {pred['reason']}"

        if "optimi" in q and ("schedul" in q or "cpu" in q):
            rec = k.ai_monitor.recommend_policy(list(k.processes.values()), k.scheduler.algorithm.value)
            if rec["changed"]:
                return f"Recommendation: switch to {rec['recommendation']}. {rec['reason']}"
            return f"Current policy ({k.scheduler.algorithm.value}) already looks optimal for this workload. {rec['reason']}"

        if "deadlock" in q:
            cycle = k.rag.detect_cycle()
            risk = k.deadlock_monitor.risk_assessment()
            if cycle:
                chain = " -> ".join(f"P{pid}" for pid in cycle) + f" -> P{cycle[0]}"
                return f"Deadlock detected! Circular wait: {chain}. Consider preempting one holder or applying the Banker's algorithm before granting further requests."
            return f"No active deadlock cycle. Risk assessment: {risk['risk'].upper()} — {risk['message']}"

        if "memory map" in q or "show memory" in q or ("memory" in q and "map" in q):
            stats = k.memory.stats()
            used = stats["used_frames"]
            total = stats["total_frames"]
            return f"Memory map: {used}/{total} frames occupied ({100*used/total:.0f}%), {stats['swap_used']} pages swapped out, replacement policy = {stats['policy']}."

        if "cpu" in q and ("overload" in q or "predict" in q or "utiliz" in q):
            pred = k.ai_monitor.cpu_overload_prediction()
            return pred["message"]

        if "starv" in q:
            flagged = k.ai_monitor.detect_starvation(list(k.processes.values()))
            if not flagged:
                return "No processes are currently at risk of starvation."
            return "; ".join(f["message"] for f in flagged)

        if "health" in q:
            h = k.last_health or {"score": 100, "verdict": "Healthy"}
            return f"System health score: {h['score']}/100 — {h['verdict']}."

        if "running" in q and "process" in q:
            if k.scheduler.running:
                p = k.scheduler.running
                return f"P{p.pid} ({p.name}) is currently RUNNING. {p.ai_reason}"
            return "CPU is idle — no process currently running."

        if "how many process" in q or "process count" in q or "list process" in q:
            procs = list(k.processes.values())
            alive = [p for p in procs if p.state.value != "TERMINATED"]
            return f"{len(alive)} active processes: " + ", ".join(f"P{p.pid}({p.name}/{p.state.value})" for p in alive)

        if "disk" in q or "filesystem" in q or "file system" in q:
            stats = k.filesystem.stats()
            return f"Disk usage: {stats['used_blocks']}/{stats['total_blocks']} blocks ({stats['disk_usage_pct']}%)."

        if "network" in q or "bandwidth" in q:
            stats = k.network.stats()
            return f"Bandwidth utilization: {stats['bandwidth_utilization']*100:.0f}%, {len(stats['open_sockets'])} open sockets, queue depth {stats['queue_depth']}."

        return ("I can answer questions about: process wait reasons ('why is process 3 waiting'), "
                "page faults, deadlocks, memory map, CPU overload predictions, starvation, "
                "scheduling optimization, disk usage, and network status. Try one of those!")
