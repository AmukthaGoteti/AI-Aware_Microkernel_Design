"""
tests/test_memory_manager.py
-----------------------------
Unit tests for the MemoryManager kernel subsystem.

Testing philosophy (matches Qualcomm firmware team practices):
    1. Test the happy path first (normal operation)
    2. Test every failure mode explicitly
    3. Test boundary conditions (zero, max, off-by-one)
    4. Test security properties (ownership, access control)
    5. Test that cleanup works (no resource leaks)

We use Python's built-in unittest — no external libraries needed yet.
In Level 2 (C++), these will become Google Test (gtest) cases.
The structure is identical: setUp → test cases → tearDown.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from kernel.memory_manager import MemoryManager
from common.types import MemoryType, SimConstants


class TestMemoryManagerAlloc(unittest.TestCase):
    """Tests for the alloc() method."""

    def setUp(self):
        """Create a fresh MemoryManager before each test. 256-byte pool."""
        self.mm = MemoryManager(total_bytes=256)

    # --- Happy path ---

    def test_alloc_basic_returns_region(self):
        """A simple allocation should return a valid MemoryRegion."""
        region = self.mm.alloc(owner_pid=1, size=64, mem_type=MemoryType.GENERAL)
        self.assertIsNotNone(region)
        self.assertEqual(region.owner_pid, 1)
        self.assertEqual(region.size, 64)
        self.assertFalse(region.is_free)

    def test_alloc_assigns_unique_ids(self):
        """Every allocation must get a unique region_id."""
        r1 = self.mm.alloc(owner_pid=1, size=32)
        r2 = self.mm.alloc(owner_pid=1, size=32)
        r3 = self.mm.alloc(owner_pid=2, size=32)
        ids = {r1.region_id, r2.region_id, r3.region_id}
        self.assertEqual(len(ids), 3, "region_ids must be unique")

    def test_alloc_base_addresses_do_not_overlap(self):
        """Two allocations must not occupy the same simulated address range."""
        r1 = self.mm.alloc(owner_pid=1, size=64)
        r2 = self.mm.alloc(owner_pid=2, size=64)
        r1_end = r1.base_address + r1.size
        r2_end = r2.base_address + r2.size
        # They must not overlap
        overlap = not (r1_end <= r2.base_address or r2_end <= r1.base_address)
        self.assertFalse(overlap, "Allocated regions must not overlap")

    def test_alloc_fills_pool(self):
        """Should be able to allocate exactly the full pool."""
        region = self.mm.alloc(owner_pid=1, size=256)
        self.assertIsNotNone(region)
        stats = self.mm.get_stats()
        self.assertEqual(stats.free_bytes, 0)

    def test_alloc_multiple_processes(self):
        """Multiple processes should each get their own distinct regions."""
        regions = []
        for pid in range(1, 5):
            r = self.mm.alloc(owner_pid=pid, size=32)
            self.assertIsNotNone(r)
            regions.append(r)
        self.assertEqual(len(regions), 4)
        pids = [r.owner_pid for r in regions]
        self.assertEqual(pids, [1, 2, 3, 4])

    # --- Failure cases ---

    def test_alloc_fails_when_pool_full(self):
        """Allocation must fail gracefully when no memory is left."""
        self.mm.alloc(owner_pid=1, size=256)         # Fill pool
        result = self.mm.alloc(owner_pid=2, size=1)  # Should fail
        self.assertIsNone(result)

    def test_alloc_fails_on_zero_size(self):
        """Zero-size allocation must be rejected."""
        result = self.mm.alloc(owner_pid=1, size=0)
        self.assertIsNone(result)

    def test_alloc_fails_on_negative_size(self):
        """Negative size must be rejected."""
        result = self.mm.alloc(owner_pid=1, size=-10)
        self.assertIsNone(result)

    def test_alloc_fails_when_larger_than_pool(self):
        """Request larger than total pool must fail immediately."""
        result = self.mm.alloc(owner_pid=1, size=9999)
        self.assertIsNone(result)

    # --- AI Buffer alignment ---

    def test_alloc_ai_buffer_aligns_size(self):
        """AI_BUFFER allocations must be rounded up to AI_BUFFER_ALIGN."""
        align = SimConstants.AI_BUFFER_ALIGN  # 64
        region = self.mm.alloc(owner_pid=1, size=1, mem_type=MemoryType.AI_BUFFER)
        self.assertIsNotNone(region)
        self.assertEqual(region.size, align,
                         f"Size 1 should be aligned up to {align}")

    def test_alloc_ai_buffer_already_aligned_unchanged(self):
        """AI_BUFFER with already-aligned size should not change size."""
        align  = SimConstants.AI_BUFFER_ALIGN
        region = self.mm.alloc(owner_pid=1, size=align, mem_type=MemoryType.AI_BUFFER)
        self.assertIsNotNone(region)
        self.assertEqual(region.size, align)

    def test_alloc_ai_buffer_stores_correct_type(self):
        """AI_BUFFER region must have mem_type=AI_BUFFER."""
        region = self.mm.alloc(owner_pid=1, size=64, mem_type=MemoryType.AI_BUFFER)
        self.assertEqual(region.mem_type, MemoryType.AI_BUFFER)


class TestMemoryManagerFree(unittest.TestCase):
    """Tests for the free() method."""

    def setUp(self):
        self.mm = MemoryManager(total_bytes=256)

    def test_free_returns_memory_to_pool(self):
        """Freeing a region should increase free_bytes."""
        region = self.mm.alloc(owner_pid=1, size=64)
        before = self.mm.get_stats().free_bytes
        self.mm.free(region.region_id, requesting_pid=1)
        after  = self.mm.get_stats().free_bytes
        self.assertEqual(after, before + 64)

    def test_free_marks_region_as_free(self):
        """Region.is_free must be True after free()."""
        region = self.mm.alloc(owner_pid=1, size=64)
        self.mm.free(region.region_id, requesting_pid=1)
        retrieved = self.mm.get_region(region.region_id)
        self.assertTrue(retrieved.is_free)

    def test_freed_region_becomes_reusable(self):
        """Memory freed by one process should be allocatable by another."""
        r1 = self.mm.alloc(owner_pid=1, size=64)
        self.mm.free(r1.region_id, requesting_pid=1)
        r2 = self.mm.alloc(owner_pid=2, size=64)
        self.assertIsNotNone(r2, "Freed memory should be reusable")

    def test_free_fails_on_invalid_id(self):
        """Freeing a non-existent region_id must return False."""
        result = self.mm.free(region_id=9999, requesting_pid=1)
        self.assertFalse(result)

    def test_free_fails_on_double_free(self):
        """Double-freeing a region must be caught and return False."""
        region = self.mm.alloc(owner_pid=1, size=64)
        self.mm.free(region.region_id, requesting_pid=1)
        result = self.mm.free(region.region_id, requesting_pid=1)  # Second free
        self.assertFalse(result, "Double-free must be rejected")

    def test_free_denied_for_wrong_pid(self):
        """Process B must not be able to free Process A's memory."""
        region = self.mm.alloc(owner_pid=1, size=64)
        result = self.mm.free(region.region_id, requesting_pid=2)
        self.assertFalse(result, "Wrong-owner free must be denied")
        # Region must still be allocated
        retrieved = self.mm.get_region(region.region_id)
        self.assertFalse(retrieved.is_free)

    def test_kernel_can_free_any_region(self):
        """Kernel (pid=-1) must be able to free any process's memory."""
        region = self.mm.alloc(owner_pid=5, size=64)
        result = self.mm.free(region.region_id, requesting_pid=-1)
        self.assertTrue(result, "Kernel must be able to free any region")

    def test_free_all_for_pid(self):
        """free_all_for_pid must release all regions owned by that PID."""
        self.mm.alloc(owner_pid=3, size=32)
        self.mm.alloc(owner_pid=3, size=32)
        self.mm.alloc(owner_pid=4, size=32)  # Different PID — should NOT be freed
        freed = self.mm.free_all_for_pid(pid=3)
        self.assertEqual(freed, 2)
        # pid=4's region must still be allocated
        pid4_regions = self.mm.get_regions_for_pid(4)
        self.assertEqual(len(pid4_regions), 1)


class TestMemoryManagerAccess(unittest.TestCase):
    """Tests for validate_access() — SMMU simulation."""

    def setUp(self):
        self.mm = MemoryManager(total_bytes=256)

    def test_owner_can_access_own_region(self):
        """Process must have access to its own memory."""
        region = self.mm.alloc(owner_pid=1, size=64)
        self.assertTrue(self.mm.validate_access(pid=1, region_id=region.region_id))

    def test_non_owner_denied(self):
        """Non-owner process must be denied access."""
        region = self.mm.alloc(owner_pid=1, size=64)
        self.assertFalse(self.mm.validate_access(pid=2, region_id=region.region_id))

    def test_kernel_accesses_any_region(self):
        """Kernel (pid=-1) must have access to every region."""
        region = self.mm.alloc(owner_pid=5, size=64)
        self.assertTrue(self.mm.validate_access(pid=-1, region_id=region.region_id))

    def test_ipc_shared_accessible_by_all(self):
        """IPC_SHARED regions must be accessible by any process."""
        region = self.mm.alloc(owner_pid=1, size=64, mem_type=MemoryType.IPC_SHARED)
        self.assertTrue(self.mm.validate_access(pid=99, region_id=region.region_id))

    def test_access_denied_after_free(self):
        """Access to a freed region must be denied."""
        region = self.mm.alloc(owner_pid=1, size=64)
        self.mm.free(region.region_id, requesting_pid=1)
        self.assertFalse(self.mm.validate_access(pid=1, region_id=region.region_id))

    def test_access_invalid_region_id(self):
        """Access check on non-existent region must return False."""
        self.assertFalse(self.mm.validate_access(pid=1, region_id=9999))


class TestMemoryManagerStats(unittest.TestCase):
    """Tests for get_stats() and fragmentation calculation."""

    def setUp(self):
        self.mm = MemoryManager(total_bytes=256)

    def test_initial_stats(self):
        """Fresh allocator should report all memory as free."""
        s = self.mm.get_stats()
        self.assertEqual(s.total_bytes, 256)
        self.assertEqual(s.used_bytes, 0)
        self.assertEqual(s.free_bytes, 256)
        self.assertEqual(s.num_active, 0)
        self.assertEqual(s.fragmentation_pct, 0.0)

    def test_stats_after_alloc(self):
        """Stats must update correctly after an allocation."""
        self.mm.alloc(owner_pid=1, size=100)
        s = self.mm.get_stats()
        self.assertEqual(s.used_bytes, 100)
        self.assertEqual(s.free_bytes, 156)
        self.assertEqual(s.num_active, 1)

    def test_stats_after_free(self):
        """Stats must update correctly after a free."""
        r = self.mm.alloc(owner_pid=1, size=100)
        self.mm.free(r.region_id, requesting_pid=1)
        s = self.mm.get_stats()
        self.assertEqual(s.used_bytes, 0)
        self.assertEqual(s.free_bytes, 256)
        self.assertEqual(s.num_active, 0)

    def test_fragmentation_zero_when_contiguous(self):
        """No fragmentation when all free memory is one block."""
        self.mm.alloc(owner_pid=1, size=128)
        # Free block is the upper half — one contiguous piece
        s = self.mm.get_stats()
        self.assertEqual(s.fragmentation_pct, 0.0)

    def test_fragmentation_detected(self):
        """
        Fragmentation should be >0 when free memory is split.

        Layout:  [alloc 64][alloc 64][alloc 64][free 64]
                 free middle → [alloc 64][FREE 64][alloc 64][free 64]
                 Now free memory is in two non-contiguous blocks.
        """
        r1 = self.mm.alloc(owner_pid=1, size=64)
        r2 = self.mm.alloc(owner_pid=2, size=64)
        r3 = self.mm.alloc(owner_pid=3, size=64)
        # Free the middle block — creates a hole
        self.mm.free(r2.region_id, requesting_pid=2)
        s = self.mm.get_stats()
        # Two free blocks: [64] in middle + [64] at end = 128 free total
        # Largest is 64, so fragmentation = 1 - 64/128 = 50%
        self.assertGreater(s.fragmentation_pct, 0.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)