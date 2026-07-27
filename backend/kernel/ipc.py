"""
ipc.py — Inter-Process Communication subsystem.

All IPC in a microkernel flows *through the kernel* (that's the defining
architectural trait vs. a monolithic kernel) — user processes never touch
each other directly. This module is the single broker for pipes, shared
memory, message queues / mailboxes, and signals, and it keeps a rolling
event log the frontend uses to animate message flow between processes.
"""

from __future__ import annotations
from collections import deque, defaultdict
from dataclasses import dataclass, field


@dataclass
class Message:
    sender: int
    receiver: int
    kind: str            # "pipe" | "shm" | "message" | "mailbox" | "signal"
    payload: str
    tick: int


@dataclass
class Pipe:
    id: str
    reader: int
    writer: int
    buffer: deque = field(default_factory=lambda: deque(maxlen=32))


@dataclass
class SharedSegment:
    id: str
    owner: int
    attached: set = field(default_factory=set)
    size: int = 4
    data: str = ""


class IPCManager:
    SIGNALS = {"SIGKILL", "SIGTERM", "SIGSTOP", "SIGCONT", "SIGUSR1"}

    def __init__(self):
        self.mailboxes: dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
        self.pipes: dict[str, Pipe] = {}
        self.shared_segments: dict[str, SharedSegment] = {}
        self.event_log: deque = deque(maxlen=150)
        self._pipe_seq = 0
        self._shm_seq = 0

    # ---------------- message passing / mailboxes ----------------
    def send_message(self, sender: int, receiver: int, payload: str, tick: int):
        msg = Message(sender, receiver, "message", payload, tick)
        self.mailboxes[receiver].append(msg)
        self._log(msg)
        return msg

    def send_signal(self, sender: int, receiver: int, signal: str, tick: int):
        signal = signal.upper()
        if signal not in self.SIGNALS:
            signal = "SIGUSR1"
        msg = Message(sender, receiver, "signal", signal, tick)
        self.mailboxes[receiver].append(msg)
        self._log(msg)
        return msg

    def receive(self, pid: int):
        if self.mailboxes[pid]:
            return self.mailboxes[pid].popleft()
        return None

    # ---------------- pipes ----------------
    def create_pipe(self, writer: int, reader: int) -> Pipe:
        self._pipe_seq += 1
        pid_str = f"pipe-{self._pipe_seq}"
        pipe = Pipe(id=pid_str, reader=reader, writer=writer)
        self.pipes[pid_str] = pipe
        return pipe

    def write_pipe(self, pipe_id: str, data: str, tick: int):
        pipe = self.pipes.get(pipe_id)
        if not pipe:
            return None
        pipe.buffer.append(data)
        msg = Message(pipe.writer, pipe.reader, "pipe", data, tick)
        self._log(msg)
        return msg

    def read_pipe(self, pipe_id: str):
        pipe = self.pipes.get(pipe_id)
        if pipe and pipe.buffer:
            return pipe.buffer.popleft()
        return None

    # ---------------- shared memory ----------------
    def create_shared_segment(self, owner: int, size: int = 4) -> SharedSegment:
        self._shm_seq += 1
        seg_id = f"shm-{self._shm_seq}"
        seg = SharedSegment(id=seg_id, owner=owner, size=size)
        seg.attached.add(owner)
        self.shared_segments[seg_id] = seg
        return seg

    def attach(self, seg_id: str, pid: int):
        seg = self.shared_segments.get(seg_id)
        if seg:
            seg.attached.add(pid)

    def write_shared(self, seg_id: str, pid: int, data: str, tick: int):
        seg = self.shared_segments.get(seg_id)
        if not seg or pid not in seg.attached:
            return None
        seg.data = data[: seg.size * 16]
        msg = Message(pid, -1, "shm", f"segment {seg_id} updated", tick)
        self._log(msg)
        return msg

    # ---------------- internals ----------------
    def _log(self, msg: Message):
        self.event_log.append(
            {"sender": msg.sender, "receiver": msg.receiver, "kind": msg.kind, "payload": msg.payload, "tick": msg.tick}
        )

    def recent_events(self, n=25):
        return list(self.event_log)[-n:]

    def stats(self):
        return {
            "pipes": len(self.pipes),
            "shared_segments": len(self.shared_segments),
            "pending_mail": {pid: len(q) for pid, q in self.mailboxes.items() if q},
            "recent_events": self.recent_events(),
        }
