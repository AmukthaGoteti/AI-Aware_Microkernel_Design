"""
network.py — Simplified networking stack simulation.

Models sockets (TCP/UDP) bound to simulated processes, a loopback
interface, a packet queue with a simple weighted-fair-queue scheduler for
bandwidth sharing, and rolling throughput/utilization stats.
"""

from __future__ import annotations
import random
import itertools
from collections import deque, defaultdict
from dataclasses import dataclass, field

_packet_id = itertools.count(1)


@dataclass
class Socket:
    id: int
    pid: int
    proto: str      # "TCP" | "UDP"
    local_port: int
    state: str = "OPEN"    # TCP: OPEN/CONNECTED/CLOSED ; UDP: OPEN


@dataclass
class Packet:
    id: int
    src_pid: int
    dst_pid: int
    proto: str
    size_bytes: int
    tick: int


class NetworkStack:
    LINK_CAPACITY_BYTES = 1500 * 10  # bytes/tick budget for loopback link

    def __init__(self):
        self.sockets: dict[int, Socket] = {}
        self._sock_seq = 0
        self.queue: deque[Packet] = deque()
        self.delivered: deque = deque(maxlen=100)
        self.bytes_sent_per_pid = defaultdict(int)
        self.bandwidth_used_history = deque(maxlen=60)

    def open_socket(self, pid: int, proto: str, port: int) -> Socket:
        self._sock_seq += 1
        sock = Socket(id=self._sock_seq, pid=pid, proto=proto.upper(), local_port=port)
        self.sockets[sock.id] = sock
        return sock

    def close_socket(self, sock_id: int):
        if sock_id in self.sockets:
            self.sockets[sock_id].state = "CLOSED"

    def send(self, src_pid: int, dst_pid: int, proto: str, size_bytes: int, tick: int):
        pkt = Packet(id=next(_packet_id), src_pid=src_pid, dst_pid=dst_pid, proto=proto.upper(),
                     size_bytes=size_bytes, tick=tick)
        self.queue.append(pkt)
        return pkt

    def tick(self, current_tick: int):
        """Weighted-fair delivery: drain the queue up to the link capacity
        budget for this tick, round-robin across distinct source PIDs so no
        single process starves the link."""
        budget = self.LINK_CAPACITY_BYTES
        by_pid = defaultdict(deque)
        for pkt in self.queue:
            by_pid[pkt.src_pid].append(pkt)
        self.queue.clear()

        delivered_this_tick = []
        pids = list(by_pid.keys())
        while budget > 0 and pids:
            progressed = False
            for pid in list(pids):
                q = by_pid[pid]
                if not q:
                    pids.remove(pid)
                    continue
                pkt = q[0]
                if pkt.size_bytes <= budget:
                    q.popleft()
                    budget -= pkt.size_bytes
                    self.bytes_sent_per_pid[pid] += pkt.size_bytes
                    delivered_this_tick.append(pkt)
                    self.delivered.append(
                        {"tick": current_tick, "src": pkt.src_pid, "dst": pkt.dst_pid,
                         "proto": pkt.proto, "size": pkt.size_bytes}
                    )
                    progressed = True
                else:
                    pids.remove(pid)
            if not progressed:
                break

        # requeue anything not delivered
        for pid, q in by_pid.items():
            self.queue.extend(q)

        used_pct = 1 - (budget / self.LINK_CAPACITY_BYTES)
        self.bandwidth_used_history.append(used_pct)
        return delivered_this_tick

    def stats(self):
        avg_bw = (
            sum(self.bandwidth_used_history) / len(self.bandwidth_used_history)
            if self.bandwidth_used_history else 0.0
        )
        return {
            "open_sockets": [
                {"id": s.id, "pid": s.pid, "proto": s.proto, "port": s.local_port, "state": s.state}
                for s in self.sockets.values() if s.state != "CLOSED"
            ],
            "queue_depth": len(self.queue),
            "bandwidth_utilization": round(avg_bw, 3),
            "recent_packets": list(self.delivered)[-20:],
            "bytes_by_pid": dict(self.bytes_sent_per_pid),
        }
