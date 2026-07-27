"""
filesystem.py — In-memory filesystem simulation.

Provides a directory tree, inode-like file metadata, a fixed-size simulated
disk block pool with allocation tracking, and a minimal write-ahead journal
(commit log) so operations can be shown as atomic in the dashboard.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass
class INode:
    name: str
    is_dir: bool
    owner: str = "user"
    permissions: str = "rw-r--r--"
    size: int = 0
    blocks: list = field(default_factory=list)
    children: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)


class JournalEntry:
    def __init__(self, tick, op, path, status="committed"):
        self.tick, self.op, self.path, self.status = tick, op, path, status


class FileSystem:
    def __init__(self, total_blocks: int = 256, block_size: int = 4):
        self.total_blocks = total_blocks
        self.block_size = block_size
        self.block_bitmap = [False] * total_blocks
        self.root = INode("/", True, owner="root", permissions="rwxr-xr-x")
        self.journal: list[JournalEntry] = []
        self._seed()

    def _seed(self):
        for d in ("bin", "home", "var", "etc", "tmp"):
            self.root.children[d] = INode(d, True)
        self.root.children["home"].children["user"] = INode("user", True)

    # ---------------------------------------------------------------
    def _resolve_parent(self, path: str):
        parts = [p for p in path.strip("/").split("/") if p]
        node = self.root
        for part in parts[:-1]:
            if part not in node.children or not node.children[part].is_dir:
                return None, None
            node = node.children[part]
        return node, (parts[-1] if parts else None)

    def _alloc_blocks(self, n: int) -> list[int]:
        allocated = []
        for i, used in enumerate(self.block_bitmap):
            if not used and len(allocated) < n:
                self.block_bitmap[i] = True
                allocated.append(i)
        return allocated

    def _free_blocks(self, blocks: list[int]):
        for b in blocks:
            if 0 <= b < self.total_blocks:
                self.block_bitmap[b] = False

    def create_file(self, path: str, size_kb: int, tick: int, owner="user") -> tuple[bool, str]:
        parent, name = self._resolve_parent(path)
        if parent is None or name is None:
            return False, "Invalid path."
        if name in parent.children:
            return False, "File already exists."
        needed_blocks = max(1, -(-size_kb // self.block_size))
        if self.block_bitmap.count(False) < needed_blocks:
            self._journal(tick, f"CREATE {path}", status="failed:no_space")
            return False, "Insufficient disk space."
        blocks = self._alloc_blocks(needed_blocks)
        node = INode(name, False, owner=owner, size=size_kb, blocks=blocks)
        parent.children[name] = node
        self._journal(tick, f"CREATE {path}")
        return True, f"Created {path} ({size_kb}KB, {needed_blocks} blocks)."

    def delete(self, path: str, tick: int) -> tuple[bool, str]:
        parent, name = self._resolve_parent(path)
        if parent is None or name not in parent.children:
            return False, "Not found."
        node = parent.children[name]
        self._free_blocks(node.blocks)
        del parent.children[name]
        self._journal(tick, f"DELETE {path}")
        return True, f"Deleted {path}."

    def mkdir(self, path: str, tick: int) -> tuple[bool, str]:
        parent, name = self._resolve_parent(path)
        if parent is None or name in parent.children:
            return False, "Invalid path or already exists."
        parent.children[name] = INode(name, True)
        self._journal(tick, f"MKDIR {path}")
        return True, f"Created directory {path}."

    def chmod(self, path: str, perms: str, tick: int) -> tuple[bool, str]:
        parent, name = self._resolve_parent(path)
        if parent is None or name not in parent.children:
            return False, "Not found."
        parent.children[name].permissions = perms
        self._journal(tick, f"CHMOD {path} -> {perms}")
        return True, f"Permissions updated: {path} -> {perms}"

    def _journal(self, tick, op, status="committed"):
        self.journal.append(JournalEntry(tick, op, "", status))
        if len(self.journal) > 100:
            self.journal.pop(0)

    # ---------------------------------------------------------------
    def tree(self, node: INode = None, path="/") -> dict:
        node = node or self.root
        return {
            "name": node.name,
            "path": path,
            "is_dir": node.is_dir,
            "owner": node.owner,
            "permissions": node.permissions,
            "size": node.size,
            "children": [
                self.tree(child, (path.rstrip("/") + "/" + child.name))
                for child in node.children.values()
            ] if node.is_dir else [],
        }

    def stats(self):
        used = self.block_bitmap.count(True)
        return {
            "total_blocks": self.total_blocks,
            "used_blocks": used,
            "free_blocks": self.total_blocks - used,
            "disk_usage_pct": round(100 * used / self.total_blocks, 1),
            "journal": [
                {"tick": j.tick, "op": j.op, "status": j.status} for j in self.journal[-15:]
            ],
            "tree": self.tree(),
        }
