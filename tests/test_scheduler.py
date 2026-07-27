import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.kernel.process import PCB, ProcessState, ProcessType
from backend.kernel.scheduler import Scheduler, Algorithm


def make(pid, burst, priority=5, arrival=0):
    p = PCB(pid=pid, name=f"p{pid}", ptype=ProcessType.USER, priority=priority,
            burst_time=burst, remaining_burst=burst, arrival_tick=arrival)
    return p


def test_fcfs_picks_earliest_arrival():
    s = Scheduler(algorithm=Algorithm.FCFS)
    procs = [make(1, 5, arrival=3), make(2, 5, arrival=1), make(3, 5, arrival=2)]
    chosen = s.pick_next(procs, tick=5)
    assert chosen.pid == 2


def test_sjf_picks_shortest_remaining_burst():
    s = Scheduler(algorithm=Algorithm.SJF)
    procs = [make(1, 9), make(2, 2), make(3, 5)]
    chosen = s.pick_next(procs, tick=0)
    assert chosen.pid == 2


def test_priority_picks_lowest_priority_number():
    s = Scheduler(algorithm=Algorithm.PRIORITY)
    procs = [make(1, 5, priority=7), make(2, 5, priority=1), make(3, 5, priority=4)]
    chosen = s.pick_next(procs, tick=0)
    assert chosen.pid == 2


def test_round_robin_rotates():
    s = Scheduler(algorithm=Algorithm.ROUND_ROBIN)
    procs = [make(1, 5), make(2, 5), make(3, 5)]
    picks = [s.pick_next(procs, tick=i).pid for i in range(6)]
    assert picks == [1, 2, 3, 1, 2, 3]


def test_ai_scheduler_avoids_starvation():
    s = Scheduler(algorithm=Algorithm.AI)
    starved = make(1, 10, priority=9)
    starved.starvation_counter = 50
    fresh = make(2, 1, priority=1)
    procs = [starved, fresh]
    chosen = s._ai_select(procs, tick=0)
    # starvation bonus should be able to override raw burst/priority advantage
    assert chosen.pid in (1, 2)  # must not crash; explicit starvation check below
    starved.starvation_counter = 1000
    fresh.starvation_counter = 0
    chosen2 = s._ai_select(procs, tick=1)
    assert chosen2.pid == 1  # extreme starvation must win eventually


def test_ai_scheduler_produces_reason():
    s = Scheduler(algorithm=Algorithm.AI)
    procs = [make(1, 5), make(2, 3)]
    s.pick_next(procs, tick=0)
    assert s.last_decision_reason != ""


def test_mlq_prefers_system_band():
    s = Scheduler(algorithm=Algorithm.MLQ)
    procs = [make(1, 5, priority=8), make(2, 5, priority=1)]
    chosen = s.pick_next(procs, tick=0)
    assert chosen.pid == 2
