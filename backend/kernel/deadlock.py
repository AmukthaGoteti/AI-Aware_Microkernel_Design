"""
deadlock.py — Deadlock detection & avoidance.

Two complementary mechanisms:
  1. Resource Allocation Graph (RAG) + cycle detection -> definitive
     detection once a cycle exists among processes holding & requesting
     mutually exclusive resources.
  2. Banker's Algorithm -> proactive *avoidance*: before granting a
     request, simulate whether the system remains in a safe state.
  3. AI early-warning: trends the ratio of blocked/requesting processes
     over recent ticks and flags rising contention before a hard cycle
     actually forms.
"""

from __future__ import annotations
from collections import defaultdict, deque


class ResourceAllocationGraph:
    def __init__(self):
        # edges: pid -> set(resource) means "holds"; resource -> pid means "requests"
        self.holds: dict[int, set] = defaultdict(set)
        self.requests: dict[int, set] = defaultdict(set)
        self.resource_owner: dict[str, int] = {}

    def allocate(self, pid: int, resource: str):
        self.holds[pid].add(resource)
        self.resource_owner[resource] = pid
        self.requests[pid].discard(resource)

    def request(self, pid: int, resource: str):
        self.requests[pid].add(resource)

    def release(self, pid: int, resource: str):
        self.holds[pid].discard(resource)
        self.resource_owner.pop(resource, None)

    def clear_process(self, pid: int):
        self.holds.pop(pid, None)
        self.requests.pop(pid, None)
        for r, owner in list(self.resource_owner.items()):
            if owner == pid:
                del self.resource_owner[r]

    def detect_cycle(self) -> list[int] | None:
        """Builds pid -> pid wait-for edges (p1 waits for p2 if p1 requests a
        resource held by p2) and runs DFS cycle detection."""
        wait_for = defaultdict(set)
        for pid, reqs in self.requests.items():
            for r in reqs:
                owner = self.resource_owner.get(r)
                if owner is not None and owner != pid:
                    wait_for[pid].add(owner)

        visited, stack, path = set(), set(), []

        def dfs(node):
            visited.add(node)
            stack.add(node)
            path.append(node)
            for nxt in wait_for.get(node, ()):
                if nxt not in visited:
                    result = dfs(nxt)
                    if result:
                        return result
                elif nxt in stack:
                    cycle_start = path.index(nxt)
                    return path[cycle_start:]
            stack.discard(node)
            path.pop()
            return None

        for node in list(wait_for.keys()):
            if node not in visited:
                cycle = dfs(node)
                if cycle:
                    return cycle
        return None


class BankersAlgorithm:
    """Safety-check based avoidance. Resources are tracked as simple named
    counters (e.g. {"printer": 2, "scanner": 1})."""

    def __init__(self, available: dict):
        self.available = dict(available)
        self.max_claim: dict[int, dict] = {}
        self.allocation: dict[int, dict] = {}

    def register(self, pid: int, max_claim: dict):
        self.max_claim[pid] = dict(max_claim)
        self.allocation[pid] = {r: 0 for r in max_claim}

    def request(self, pid: int, req: dict) -> tuple[bool, str]:
        need = {
            r: self.max_claim.get(pid, {}).get(r, 0) - self.allocation.get(pid, {}).get(r, 0)
            for r in req
        }
        for r, amt in req.items():
            if amt > need.get(r, 0):
                return False, f"Request exceeds declared max claim for resource '{r}'."
            if amt > self.available.get(r, 0):
                return False, f"Insufficient available '{r}' ({self.available.get(r,0)} < {amt})."

        # tentatively allocate
        for r, amt in req.items():
            self.available[r] -= amt
            self.allocation[pid][r] = self.allocation[pid].get(r, 0) + amt

        safe, order = self._is_safe_state()
        if not safe:
            # rollback
            for r, amt in req.items():
                self.available[r] += amt
                self.allocation[pid][r] -= amt
            return False, "Request denied: would leave the system in an unsafe state."
        return True, f"Granted. Safe sequence exists: {order}"

    def _is_safe_state(self):
        work = dict(self.available)
        finish = {pid: False for pid in self.max_claim}
        sequence = []
        progress = True
        while progress:
            progress = False
            for pid in self.max_claim:
                if finish[pid]:
                    continue
                need = {
                    r: self.max_claim[pid][r] - self.allocation[pid].get(r, 0)
                    for r in self.max_claim[pid]
                }
                if all(need.get(r, 0) <= work.get(r, 0) for r in need):
                    for r in self.allocation[pid]:
                        work[r] = work.get(r, 0) + self.allocation[pid][r]
                    finish[pid] = True
                    sequence.append(pid)
                    progress = True
        return all(finish.values()), sequence


class DeadlockMonitor:
    """AI-flavoured early warning: tracks contention trend, not just hard cycles."""

    def __init__(self):
        self.contention_history = deque(maxlen=30)

    def sample(self, blocked_count: int, total_processes: int):
        ratio = blocked_count / total_processes if total_processes else 0
        self.contention_history.append(ratio)

    def risk_assessment(self) -> dict:
        h = list(self.contention_history)
        if len(h) < 3:
            return {"risk": "low", "trend": 0.0, "message": "Insufficient history to assess contention trend."}
        trend = (sum(h[-3:]) / 3) - (sum(h[:3]) / 3)
        current = h[-1]
        if current > 0.6 and trend > 0.1:
            risk = "high"
            msg = f"Blocked-process ratio is {current*100:.0f}% and rising — deadlock risk is elevated."
        elif current > 0.35:
            risk = "medium"
            msg = f"Blocked-process ratio is {current*100:.0f}%. Monitor resource contention."
        else:
            risk = "low"
            msg = "Resource contention is within normal bounds."
        return {"risk": risk, "trend": round(trend, 3), "message": msg}
