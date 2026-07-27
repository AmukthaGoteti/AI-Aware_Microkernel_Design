import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.kernel.deadlock import ResourceAllocationGraph, BankersAlgorithm


def test_no_cycle_when_no_contention():
    rag = ResourceAllocationGraph()
    rag.allocate(1, "R1")
    rag.request(2, "R2")
    assert rag.detect_cycle() is None


def test_detects_simple_two_process_cycle():
    rag = ResourceAllocationGraph()
    rag.allocate(1, "R1")
    rag.allocate(2, "R2")
    rag.request(1, "R2")  # P1 holds R1, wants R2 (held by P2)
    rag.request(2, "R1")  # P2 holds R2, wants R1 (held by P1) -> cycle
    cycle = rag.detect_cycle()
    assert cycle is not None
    assert set(cycle) == {1, 2}


def test_bankers_denies_unsafe_request():
    b = BankersAlgorithm(available={"printer": 1})
    b.register(1, {"printer": 1})
    b.register(2, {"printer": 1})
    ok1, _ = b.request(1, {"printer": 1})
    assert ok1 is True
    ok2, msg2 = b.request(2, {"printer": 1})
    assert ok2 is False


def test_bankers_grants_safe_request():
    b = BankersAlgorithm(available={"printer": 2})
    b.register(1, {"printer": 1})
    b.register(2, {"printer": 1})
    ok1, _ = b.request(1, {"printer": 1})
    ok2, _ = b.request(2, {"printer": 1})
    assert ok1 is True and ok2 is True
