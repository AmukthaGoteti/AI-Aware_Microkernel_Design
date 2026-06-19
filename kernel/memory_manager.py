"""
kernel/memory_manager.py
------------------------
Memory Manager — the kernel subsystem responsible for all memory allocation,
tracking, ownership, and release.

Industry context:
    In Qualcomm's Linux BSP, memory management involves:
      - The buddy allocator  : breaks/merges page-sized blocks
      - The slab allocator   : manages small kernel objects
      - ION allocator        : large physically contiguous buffers for DSP/NPU/GPU
      - CMA                  : Contiguous Memory Allocator for DMA-capable devices
      - SMMU                 : System MMU — enforces per-process address space isolation

    Our MemoryManager simulates all of these ideas in a single class:
      - Fixed pool  → buddy allocator concept
      - Regions     → ION heap concept
      - owner_pid   → SMMU isolation concept
      - AI_BUFFER   → CMA/ION contiguous allocation concept

Design pattern used: Repository + Factory
    - MemoryManager is the repository (stores and manages all regions)
    - alloc() is the factory (creates new MemoryRegion objects)

C++ equivalent (Level 2 preview):
    class MemoryManager {
    public:
        MemoryRegion* alloc(int pid, size_t size, MemoryType type);
        bool          free(int region_id);
        bool          validate_access(int pid, int region_id) const;
        MemoryStats   get_stats() const;
    private:
        std::vector<MemoryRegion> regions_;
        size_t                    total_bytes_;
        size_t                    used_bytes_;
        int                       next_region_id_;
    };
"""

from dataclasses import dataclass, field
from typing import Optional
from common.types import MemoryRegion, MemoryType, SimConstants


# =============================================================================
# MEMORY STATS — snapshot of current memory system state
# =============================================================================
# This is what TelemetryEngine will query every tick.
# In Qualcomm systems, equivalent data comes from /proc/meminfo and
# the ION heap debug interface at /sys/kernel/debug/ion/

@dataclass
class MemoryStats:
    """
    A point-in-time snapshot of memory system state.
    Emitted to TelemetryEngine every simulation tick.
    """
    total_bytes:       int
    used_bytes:        int
    free_bytes:        int
    num_regions:       int          # Total allocated regions (including freed)
    num_active:        int          # Currently allocated (not freed)
    fragmentation_pct: float        # % of free memory that is fragmented
                                    # 0% = one big free block (ideal)
                                    # 100% = free memory split into tiny islands


# =============================================================================
# MEMORY MANAGER
# =============================================================================

class MemoryManager:
    """
    Kernel memory subsystem.

    Manages a fixed pool of simulated memory, divided into MemoryRegion
    objects. Supports per-process ownership, memory type classification,
    and alignment enforcement for AI workloads.

    Allocation strategy: First-Fit
        Scan regions from address 0 upward.
        Use the first gap large enough to fit the request.
        Simple, fast, and mirrors what early embedded allocators did.

    Why first-fit and not best-fit?
        Best-fit reduces fragmentation but is slower (must scan everything).
        First-fit is the choice in many RTOS environments where deterministic
        allocation time matters more than perfect packing.
        Qualcomm's RTOS allocators often use first-fit or power-of-two pools.
    """

    def __init__(self, total_bytes: int = SimConstants.TOTAL_MEMORY_BYTES):
        """
        Initialise the memory pool.

        Args:
            total_bytes: Total simulated memory available (default from SimConstants).
                         Think of this as the total DRAM available to the kernel.
        """
        self._total_bytes:  int  = total_bytes
        self._used_bytes:   int  = 0
        self._next_id:      int  = 1      # Region ID counter (monotonically increasing)
        self._regions:      list[MemoryRegion] = []
        self._event_log:    list[str]          = []  # Audit trail of operations

        self._log(f"MemoryManager initialised. Pool size: {total_bytes} bytes")

    # -------------------------------------------------------------------------
    # CORE API
    # -------------------------------------------------------------------------

    def alloc(
        self,
        owner_pid: int,
        size:      int,
        mem_type:  MemoryType = MemoryType.GENERAL
    ) -> Optional[MemoryRegion]:
        """
        Allocate a memory region from the pool.

        This is the primary API. Every kernel subsystem and user-space service
        that needs memory calls this.

        Args:
            owner_pid : PID of the process requesting memory.
                        -1 is reserved for kernel-owned allocations.
            size      : Number of simulated bytes requested.
            mem_type  : Type of memory (affects alignment and placement rules).

        Returns:
            MemoryRegion if allocation succeeded, None if it failed.

        Failure reasons:
            - Not enough total free memory
            - AI_BUFFER request can't find a contiguous block large enough
            - size <= 0

        Industry note:
            In the Linux kernel, kmalloc() and vmalloc() are the equivalent
            calls. ION's ion_alloc() is the equivalent for AI buffer type.
            All return NULL on failure — the caller must always check.
        """
        # --- Input validation ---
        if size <= 0:
            self._log(f"[ALLOC FAIL] pid={owner_pid} requested invalid size={size}")
            return None

        if size > self._total_bytes:
            self._log(f"[ALLOC FAIL] pid={owner_pid} size={size} exceeds total pool")
            return None

        # --- Alignment enforcement for AI buffers ---
        # AI accelerators (NPU, DSP) require memory to be aligned to a
        # specific boundary for DMA efficiency.
        # Real example: Qualcomm Hexagon NPU requires 128-byte aligned buffers.
        # We enforce SimConstants.AI_BUFFER_ALIGN (64 bytes) for AI_BUFFER type.
        if mem_type == MemoryType.AI_BUFFER:
            size = self._align_up(size, SimConstants.AI_BUFFER_ALIGN)
            self._log(f"[ALIGN] AI_BUFFER size rounded up to {size} bytes "
                      f"(align={SimConstants.AI_BUFFER_ALIGN})")

        # --- Find a free address slot using First-Fit ---
        base_address = self._find_free_slot(size, contiguous=(mem_type == MemoryType.AI_BUFFER))

        if base_address is None:
            self._log(f"[ALLOC FAIL] pid={owner_pid} no contiguous block for size={size}")
            return None

        # --- Create the region ---
        region = MemoryRegion(
            region_id=    self._next_id,
            base_address= base_address,
            size=         size,
            owner_pid=    owner_pid,
            mem_type=     mem_type,
            is_free=      False          # It's allocated, not free
        )

        self._next_id    += 1
        self._used_bytes += size
        self._regions.append(region)

        self._log(
            f"[ALLOC OK] region_id={region.region_id} "
            f"pid={owner_pid} base=0x{base_address:04X} "
            f"size={size} type={mem_type.value}"
        )
        return region

    def free(self, region_id: int, requesting_pid: int) -> bool:
        """
        Free a previously allocated memory region.

        Args:
            region_id     : ID of the region to free (from alloc() return value).
            requesting_pid: PID of the process requesting the free.
                            Must match owner_pid, OR be -1 (kernel).

        Returns:
            True if freed successfully, False otherwise.

        Security note:
            A process can only free its own memory.
            The kernel (pid=-1) can free any region (used during process cleanup).
            This mirrors how the Linux kernel reclaims memory when a process exits.

        Industry note:
            In the ION allocator, ion_free() is the equivalent call.
            Freeing another process's buffer is prevented by file descriptor
            ownership — we simulate this with owner_pid checking.
        """
        region = self._find_region_by_id(region_id)

        if region is None:
            self._log(f"[FREE FAIL] region_id={region_id} not found")
            return False

        if region.is_free:
            self._log(f"[FREE FAIL] region_id={region_id} already free (double-free!)")
            return False

        # Ownership check — kernel (pid=-1) can always free
        if requesting_pid != -1 and region.owner_pid != requesting_pid:
            self._log(
                f"[FREE DENIED] pid={requesting_pid} tried to free "
                f"region owned by pid={region.owner_pid}"
            )
            return False

        # --- Mark as free ---
        self._used_bytes -= region.size
        region.is_free   =  True
        region.owner_pid =  -1      # Disown

        self._log(
            f"[FREE OK] region_id={region_id} "
            f"base=0x{region.base_address:04X} size={region.size} returned to pool"
        )
        return True

    def free_all_for_pid(self, pid: int) -> int:
        """
        Free every memory region owned by a given process.

        Called by ProcessManager when a process terminates.
        This is the kernel's automatic memory reclamation on process exit.

        Returns:
            Number of regions freed.

        Industry note:
            In Linux, this is done by exit_mm() which tears down the entire
            mm_struct (memory descriptor) of the dying process.
            In Qualcomm's RTOS, the task cleanup hook does the equivalent.
        """
        freed_count = 0
        for region in self._regions:
            if region.owner_pid == pid and not region.is_free:
                self.free(region.region_id, requesting_pid=-1)  # Kernel frees it
                freed_count += 1

        self._log(f"[CLEANUP] pid={pid} — freed {freed_count} region(s)")
        return freed_count

    def validate_access(self, pid: int, region_id: int) -> bool:
        """
        Check whether a process is allowed to access a memory region.

        This simulates the SMMU (System MMU) permission check.
        In real hardware, the SMMU rejects DMA transactions from devices
        that aren't the authorised owner of a memory region.

        Returns:
            True if the process owns the region (or region is IPC_SHARED),
            False if access should be denied.
        """
        region = self._find_region_by_id(region_id)

        if region is None or region.is_free:
            return False

        # Kernel can access everything
        if pid == -1:
            return True

        # Owner can always access their own region
        if region.owner_pid == pid:
            return True

        # IPC_SHARED regions are accessible by any process
        # (they were explicitly shared — that's the whole point)
        if region.mem_type == MemoryType.IPC_SHARED:
            return True

        # All other cases: denied
        self._log(
            f"[ACCESS DENIED] pid={pid} tried to access "
            f"region_id={region_id} owned by pid={region.owner_pid}"
        )
        return False

    # -------------------------------------------------------------------------
    # QUERY API
    # -------------------------------------------------------------------------

    def get_stats(self) -> MemoryStats:
        """
        Return current memory system state.
        Called by TelemetryEngine every tick.
        """
        active_regions = [r for r in self._regions if not r.is_free]
        free_bytes     = self._total_bytes - self._used_bytes

        return MemoryStats(
            total_bytes       = self._total_bytes,
            used_bytes        = self._used_bytes,
            free_bytes        = free_bytes,
            num_regions       = len(self._regions),
            num_active        = len(active_regions),
            fragmentation_pct = self._compute_fragmentation()
        )

    def get_region(self, region_id: int) -> Optional[MemoryRegion]:
        """Retrieve a region by ID. Returns None if not found."""
        return self._find_region_by_id(region_id)

    def get_regions_for_pid(self, pid: int) -> list[MemoryRegion]:
        """Return all active regions owned by a given process."""
        return [r for r in self._regions if r.owner_pid == pid and not r.is_free]

    def get_event_log(self) -> list[str]:
        """Return the audit log of all memory operations."""
        return list(self._event_log)

    # -------------------------------------------------------------------------
    # DISPLAY
    # -------------------------------------------------------------------------

    def display_memory_map(self):
        """
        Print an ASCII visualisation of the current memory layout.

        This is modelled after /proc/iomem on Linux — a human-readable
        map of how physical memory is carved up.

        Example output:
            MEMORY MAP  [used: 384 / 1024 bytes]
            0x0000 ████████████████ pid=1  GENERAL    [256]
            0x0100 ████████         pid=2  AI_BUFFER  [128]
            0x0180 ................           FREE    [640]
        """
        stats = self.get_stats()
        bar_width = 40  # characters wide

        print(f"\n{'─'*60}")
        print(f"  MEMORY MAP  [used: {stats.used_bytes} / {stats.total_bytes} bytes  "
              f"free: {stats.free_bytes}  frag: {stats.fragmentation_pct:.1f}%]")
        print(f"{'─'*60}")

        # Collect all segments: active regions + free gaps
        segments = self._build_layout_segments()

        for seg in segments:
            addr   = seg['address']
            size   = seg['size']
            is_free= seg['is_free']

            # Scale bar length to segment size
            bar_len = max(1, int((size / self._total_bytes) * bar_width))

            if is_free:
                bar   = '·' * bar_len
                label = f"FREE [{size}]"
                pid_s = ""
                type_s= ""
            else:
                bar   = '█' * bar_len
                pid_s = f"pid={seg['owner_pid']}"
                type_s= seg['mem_type']
                label = f"{pid_s:<8} {type_s:<12} [{size}]"

            print(f"  0x{addr:04X}  {bar:<{bar_width}}  {label}")

        print(f"{'─'*60}\n")

    def display_stats(self):
        """Print a compact stats summary to console."""
        s = self.get_stats()
        used_pct = (s.used_bytes / s.total_bytes * 100) if s.total_bytes > 0 else 0
        bar_used = int(used_pct / 5)  # 20-char bar
        bar      = '█' * bar_used + '░' * (20 - bar_used)

        print(f"  MEM [{bar}] {used_pct:5.1f}% used  "
              f"({s.used_bytes}/{s.total_bytes} bytes)  "
              f"active_regions={s.num_active}  frag={s.fragmentation_pct:.1f}%")

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _find_free_slot(self, size: int, contiguous: bool = True) -> Optional[int]:
        """
        Find the lowest address where 'size' bytes can be allocated.

        Strategy: First-Fit
            1. Sort all allocated (non-free) regions by base address.
            2. Walk through the gaps between them.
            3. Return the first gap large enough.

        The 'contiguous' flag matters for AI_BUFFER:
            AI buffers need one solid unbroken block.
            (This flag is always True in our simulation; it's here to make
             the concept explicit for when you study CMA in real kernels.)

        Returns:
            Starting address (int) if a slot was found, None otherwise.
        """
        # Get all active (non-free) regions sorted by address
        active = sorted(
            [r for r in self._regions if not r.is_free],
            key=lambda r: r.base_address
        )

        # Check gap before first region
        if not active:
            # Pool is empty — start at 0
            if size <= self._total_bytes:
                return 0
            return None

        # Check gap at the very start (address 0 → first region)
        if active[0].base_address >= size:
            return 0

        # Check gaps between consecutive regions
        for i in range(len(active) - 1):
            gap_start = active[i].base_address + active[i].size
            gap_end   = active[i + 1].base_address
            gap_size  = gap_end - gap_start

            if gap_size >= size:
                return gap_start

        # Check gap after the last region → end of pool
        last          = active[-1]
        gap_start     = last.base_address + last.size
        remaining     = self._total_bytes - gap_start

        if remaining >= size:
            return gap_start

        return None  # No slot found

    def _find_region_by_id(self, region_id: int) -> Optional[MemoryRegion]:
        """Linear search by region ID. Fine for simulation scale."""
        for r in self._regions:
            if r.region_id == region_id:
                return r
        return None

    def _align_up(self, value: int, alignment: int) -> int:
        """
        Round 'value' up to the next multiple of 'alignment'.

        Example: _align_up(70, 64) → 128
                 _align_up(64, 64) → 64

        This is the same formula used in every embedded allocator:
            aligned = (value + alignment - 1) & ~(alignment - 1)

        We use the modulo version here for readability.
        In C++, you'd use the bitwise version for performance.
        """
        if value % alignment == 0:
            return value
        return value + (alignment - (value % alignment))

    def _compute_fragmentation(self) -> float:
        """
        Calculate fragmentation percentage.

        Fragmentation = (number of free gaps > 1) situation.
        A fully defragmented pool has exactly one free block.

        Formula:
            If there are N separate free gaps and the largest is L bytes,
            fragmentation = 1 - (L / total_free_bytes)

            0%   = all free memory is in one contiguous block (ideal)
            100% = free memory is scattered in 1-byte islands (worst case)

        Industry note:
            Memory fragmentation is a real concern in long-running embedded
            systems. Qualcomm's RTOS uses memory pools (fixed-size blocks)
            partly to avoid fragmentation entirely.
        """
        free_bytes = self._total_bytes - self._used_bytes
        if free_bytes == 0:
            return 0.0

        # Find all free gaps
        active    = sorted(
            [r for r in self._regions if not r.is_free],
            key=lambda r: r.base_address
        )
        free_gaps = self._find_free_gaps(active)

        if not free_gaps:
            return 0.0

        largest_gap = max(free_gaps)
        return round((1.0 - largest_gap / free_bytes) * 100.0, 2)

    def _find_free_gaps(self, active_sorted: list) -> list[int]:
        """Return list of free gap sizes given sorted active regions."""
        gaps = []
        prev_end = 0

        for r in active_sorted:
            if r.base_address > prev_end:
                gaps.append(r.base_address - prev_end)
            prev_end = r.base_address + r.size

        # Gap after last region
        if prev_end < self._total_bytes:
            gaps.append(self._total_bytes - prev_end)

        return gaps

    def _build_layout_segments(self) -> list[dict]:
        """
        Build an ordered list of segments (allocated + free gaps)
        for display_memory_map().
        """
        segments = []
        active   = sorted(
            [r for r in self._regions if not r.is_free],
            key=lambda r: r.base_address
        )
        cursor   = 0

        for r in active:
            if r.base_address > cursor:
                segments.append({
                    'address':  cursor,
                    'size':     r.base_address - cursor,
                    'is_free':  True,
                    'owner_pid': -1,
                    'mem_type': ''
                })
            segments.append({
                'address':   r.base_address,
                'size':      r.size,
                'is_free':   False,
                'owner_pid': r.owner_pid,
                'mem_type':  r.mem_type.value
            })
            cursor = r.base_address + r.size

        if cursor < self._total_bytes:
            segments.append({
                'address':  cursor,
                'size':     self._total_bytes - cursor,
                'is_free':  True,
                'owner_pid': -1,
                'mem_type': ''
            })

        return segments

    def _log(self, message: str):
        """Internal audit log. All memory operations are recorded."""
        self._event_log.append(message)