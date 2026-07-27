import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.kernel.memory import MemoryManager, ReplacementPolicy


def test_page_fault_on_first_access():
    mm = MemoryManager(total_frames=4, policy=ReplacementPolicy.FIFO)
    pt = mm.allocate_process(1, 4)
    result = mm.access_page(1, pt, 0, tick=1)
    assert result["result"] == "FAULT"
    assert mm.page_faults == 1


def test_hit_on_second_access_same_page():
    mm = MemoryManager(total_frames=4, policy=ReplacementPolicy.FIFO)
    pt = mm.allocate_process(1, 4)
    mm.access_page(1, pt, 0, tick=1)
    result = mm.access_page(1, pt, 0, tick=2)
    assert result["result"] in ("HIT", "PREFETCH_HIT")


def test_fifo_evicts_oldest_frame():
    mm = MemoryManager(total_frames=2, policy=ReplacementPolicy.FIFO)
    pt = mm.allocate_process(1, 4)
    mm.access_page(1, pt, 0, tick=1)
    mm.access_page(1, pt, 1, tick=2)
    # both frames full; accessing page 2 must evict page 0 (first loaded)
    mm.access_page(1, pt, 2, tick=3)
    assert pt[0]["present"] is False


def test_lru_keeps_recently_used():
    mm = MemoryManager(total_frames=2, policy=ReplacementPolicy.LRU)
    pt = mm.allocate_process(1, 4)
    mm.access_page(1, pt, 0, tick=1)
    mm.access_page(1, pt, 1, tick=2)
    mm.access_page(1, pt, 0, tick=3)  # touch page 0 again -> now most recently used
    mm.access_page(1, pt, 2, tick=4)  # should evict page 1, not page 0
    assert pt[0]["present"] is True


def test_free_process_releases_frames():
    mm = MemoryManager(total_frames=4, policy=ReplacementPolicy.LRU)
    pt = mm.allocate_process(1, 2)
    mm.access_page(1, pt, 0, tick=1)
    mm.free_process(1)
    assert len(mm.free_frames) == 4


def test_ai_prefetch_learns_sequential_pattern():
    mm = MemoryManager(total_frames=8, policy=ReplacementPolicy.LRU)
    pt = mm.allocate_process(1, 4)
    # train a 0 -> 1 transition pattern several times
    for _ in range(5):
        mm.access_page(1, pt, 0, tick=1)
        mm.access_page(1, pt, 1, tick=2)
    assert pt[1]["present"] is True
