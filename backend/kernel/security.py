"""
security.py — Privilege separation, mode switching, and syscall gating.

Every syscall in this simulator is routed through `SecurityManager.check()`
so mode transitions (user -> kernel -> user) and access-control decisions
are auditable, mirroring how a real microkernel keeps privileged
operations behind a narrow, logged trap gate.
"""

from __future__ import annotations
from collections import deque


KERNEL_ONLY_SYSCALLS = {"reboot", "set_scheduler", "map_device_memory", "kill_any"}
USER_SYSCALLS = {"read", "write", "fork", "exit", "send_message", "malloc", "open", "ioctl"}


class User:
    def __init__(self, name: str, role: str = "user"):
        self.name = name
        self.role = role  # "root" | "user"
        self.authenticated = False


class SecurityManager:
    def __init__(self):
        self.users = {
            "root": User("root", "root"),
            "user": User("user", "user"),
        }
        self.audit_log: deque = deque(maxlen=150)
        self.current_mode = "user"  # "user" | "kernel"

    def authenticate(self, username: str, tick: int) -> bool:
        user = self.users.get(username)
        if user:
            user.authenticated = True
            self._audit(tick, "AUTH", username, "granted")
            return True
        self._audit(tick, "AUTH", username, "denied: unknown user")
        return False

    def check_syscall(self, pid: int, username: str, syscall: str, tick: int) -> tuple[bool, str]:
        user = self.users.get(username, self.users["user"])
        if syscall in KERNEL_ONLY_SYSCALLS and user.role != "root":
            self._audit(tick, syscall, username, "denied: requires root")
            return False, f"Permission denied: '{syscall}' requires root privilege."

        # simulate the trap: user mode -> kernel mode -> back to user mode
        self.current_mode = "kernel"
        self._audit(tick, syscall, username, "granted", pid=pid)
        self.current_mode = "user"
        return True, f"syscall '{syscall}' executed in kernel mode on behalf of PID {pid}."

    def check_file_access(self, username: str, owner: str, permissions: str, mode: str, tick: int) -> tuple[bool, str]:
        """mode: 'r' | 'w' | 'x'. permissions string like 'rwxr-xr-x' (owner/group/other)."""
        is_owner = username == owner or username == "root"
        segment = permissions[0:3] if is_owner else permissions[6:9]
        allowed = mode in segment
        self._audit(tick, f"file_access:{mode}", username, "granted" if allowed else "denied")
        return allowed, "Access granted." if allowed else "Access denied: insufficient file permissions."

    def _audit(self, tick, action, username, result, pid=None):
        self.audit_log.append(
            {"tick": tick, "action": action, "user": username, "result": result, "pid": pid, "mode": self.current_mode}
        )

    def stats(self):
        return {
            "current_mode": self.current_mode,
            "users": {name: u.role for name, u in self.users.items()},
            "audit_log": list(self.audit_log)[-25:],
        }
