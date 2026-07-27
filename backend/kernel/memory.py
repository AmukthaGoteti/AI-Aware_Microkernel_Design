"""
memory.py — Virtual memory manager.

Simulates a paged virtual memory system with a fixed number of physical
frames, per-process page tables, and pluggable replacement policies
(FIFO / LRU / LFU / Clock). An AI prefetcher observes each process's page
access sequence and uses simple Markov-chain style "next-page" frequency
counts to prefetch pages speculatively, reducing simulated fault rate.
"""

from __future__ import annotations
import random
from collections import defaultdict, deque
from enum import Enum


class ReplacementPolicy(str, Enum):
    FIFO = "FIFO"
    LRU = "LRU"
    LFU = "LFU"
    CLOCK = "CLOCK"


class Frame:
    __slots__ = ("index", "pid", "page", "loaded_tick", "last_used_tick", "ref_bit", "use_count")

    def __init__(self, index):
        self.index = index
        self.pid = None
        self.page = None
        self.loaded_tick = 0
        self.last_used_tick = 0
        self.ref_bit = 0
        self.use_count = 0


class MemoryManager:
    def __init__(self, total_frames: int = 32, policy: ReplacementPolicy = ReplacementPolicy.LRU):
        self.total_frames = total_frames
        self.frames = [Frame(i) for i in range(total_frames)]
        self.policy = policy
        self.free_frames = deque(range(total_frames))
        self.page_faults = 0
        self.page_hits = 0
        self.swap_space = []          # pages evicted to "disk"
        self.fifo_queue = deque()     # frame indices in load order
        self.clock_hand = 0

        # tracks each process's page table so eviction can clear the *owning*
        # process's entry even when a different process triggers the fault
        self._page_tables: dict[int, list] = {}

        # per-process access history + Markov transition counts for AI prefetch
        self._access_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=50))
        self._transition_counts: dict[int, dict[int, dict[int, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self.prefetch_hits = 0
        self.prefetched_pages: dict[int, set] = defaultdict(set)

        self.event_log = deque(maxlen=100)

    # ------------------------------------------------------------
    def allocate_process(self, pid: int, num_pages: int):
        """Registers a fresh page table (all pages initially not-present)."""
        table = [{"page": i, "present": False, "frame": None, "dirty": False} for i in range(num_pages)]
        self._page_tables[pid] = table
        return table

    def free_process(self, pid: int):
        for f in self.frames:
            if f.pid == pid:
                self._evict_frame(f, tick=None, silent=True)
                self.free_frames.append(f.index)
                if f.index in self.fifo_queue:
                    try:
                        self.fifo_queue.remove(f.index)
                    except ValueError:
                        pass
        self._page_tables.pop(pid, None)
        self._access_history.pop(pid, None)
        self._transition_counts.pop(pid, None)
        self.prefetched_pages.pop(pid, None)

    # ------------------------------------------------------------
    def access_page(self, pid: int, page_table: list, page: int, tick: int) -> dict:
        """Simulates a memory access to `page` of process `pid`. Returns a
        dict describing whether it was a HIT, a FAULT, or a PREFETCH-HIT."""
        self._page_tables[pid] = page_table
        history = self._access_history[pid]
        if history:
            last_page = history[-1]
            self._transition_counts[pid][last_page][page] += 1
        history.append(page)

        entry = page_table[page]
        was_prefetched = page in self.prefetched_pages[pid]

        if entry["present"]:
            frame = self.frames[entry["frame"]]
            frame.last_used_tick = tick
            frame.ref_bit = 1
            frame.use_count += 1
            self.page_hits += 1
            if was_prefetched:
                self.prefetch_hits += 1
                self.prefetched_pages[pid].discard(page)
            result = {"result": "PREFETCH_HIT" if was_prefetched else "HIT", "page": page, "frame": frame.index}
        else:
            self.page_faults += 1
            frame = self._get_free_or_evict(tick)
            self._load_page(frame, pid, page_table, page, tick)
            result = {"result": "FAULT", "page": page, "frame": frame.index}
            self.event_log.append(f"tick={tick} PID={pid} PAGE_FAULT page={page} -> frame={frame.index}")

        self._ai_prefetch(pid, page_table, page, tick)
        return result

    # ------------------------------------------------------------
    def _get_free_or_evict(self, tick) -> Frame:
        if self.free_frames:
            idx = self.free_frames.popleft()
            frame = self.frames[idx]
            self.fifo_queue.append(idx)
            return frame
        victim = self._select_victim(tick)
        self._evict_frame(victim, tick)
        self.fifo_queue.append(victim.index)
        return victim

    def _select_victim(self, tick) -> Frame:
        if self.policy == ReplacementPolicy.FIFO:
            idx = self.fifo_queue.popleft()
            return self.frames[idx]
        if self.policy == ReplacementPolicy.LRU:
            return min(self.frames, key=lambda f: f.last_used_tick)
        if self.policy == ReplacementPolicy.LFU:
            return min(self.frames, key=lambda f: f.use_count)
        if self.policy == ReplacementPolicy.CLOCK:
            while True:
                f = self.frames[self.clock_hand]
                if f.ref_bit == 0:
                    victim = f
                    self.clock_hand = (self.clock_hand + 1) % self.total_frames
                    return victim
                f.ref_bit = 0
                self.clock_hand = (self.clock_hand + 1) % self.total_frames
        return self.frames[0]

    def _evict_frame(self, frame: Frame, tick, silent=False):
        if frame.pid is not None:
            self.swap_space.append({"pid": frame.pid, "page": frame.page})
            if len(self.swap_space) > 500:
                self.swap_space.pop(0)
            if not silent:
                self.event_log.append(
                    f"tick={tick} EVICT pid={frame.pid} page={frame.page} frame={frame.index} policy={self.policy.value}"
                )
            owner_table = self._page_tables.get(frame.pid)
            if owner_table is not None and 0 <= frame.page < len(owner_table):
                owner_table[frame.page]["present"] = False
                owner_table[frame.page]["frame"] = None
            self.prefetched_pages.get(frame.pid, set()).discard(frame.page)
        frame.pid = None
        frame.page = None
        frame.ref_bit = 0
        frame.use_count = 0

    def _load_page(self, frame: Frame, pid, page_table, page, tick):
        frame.pid = pid
        frame.page = page
        frame.loaded_tick = tick
        frame.last_used_tick = tick
        frame.ref_bit = 1
        frame.use_count = 1
        page_table[page]["present"] = True
        page_table[page]["frame"] = frame.index

    # ------------------------------------------------------------
    def _ai_prefetch(self, pid, page_table, current_page, tick):
        """Speculatively loads the most probable next page(s) based on the
        learned Markov transition table, if a free frame is available and
        the target page isn't already resident."""
        transitions = self._transition_counts[pid].get(current_page)
        if not transitions:
            return
        predicted_page = max(transitions, key=transitions.get)
        if predicted_page >= len(page_table):
            return
        if page_table[predicted_page]["present"]:
            return
        if not self.free_frames:
            return  # don't evict just to speculate
        idx = self.free_frames.popleft()
        frame = self.frames[idx]
        self.fifo_queue.append(idx)
        self._load_page(frame, pid, page_table, predicted_page, tick)
        self.prefetched_pages[pid].add(predicted_page)
        self.event_log.append(
            f"tick={tick} AI_PREFETCH pid={pid} page={predicted_page} frame={frame.index} "
            f"(confidence={transitions[predicted_page]}/{sum(transitions.values())})"
        )

    # ------------------------------------------------------------
    def stats(self) -> dict:
        total = self.page_faults + self.page_hits
        fault_rate = (self.page_faults / total) if total else 0.0
        used = self.total_frames - len(self.free_frames)
        return {
            "total_frames": self.total_frames,
            "used_frames": used,
            "free_frames": len(self.free_frames),
            "page_faults": self.page_faults,
            "page_hits": self.page_hits,
            "fault_rate": round(fault_rate, 4),
            "prefetch_hits": self.prefetch_hits,
            "swap_used": len(self.swap_space),
            "policy": self.policy.value,
            "frames": [
                {"index": f.index, "pid": f.pid, "page": f.page, "ref_bit": f.ref_bit, "use_count": f.use_count}
                for f in self.frames
            ],
            "recent_events": list(self.event_log)[-20:],
        }

    def fragmentation_estimate(self) -> float:
        """External fragmentation proxy: variance of contiguous free-frame run lengths."""
        occupied = [1 if f.pid is not None else 0 for f in self.frames]
        runs, cur = [], 0
        for bit in occupied:
            if bit == 0:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
        if not runs:
            return 0.0
        return round(1 - (max(runs) / sum(runs)), 3) if sum(runs) else 0.0
