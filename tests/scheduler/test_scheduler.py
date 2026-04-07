"""Phase 4 tests: scheduler heuristics and headroom."""

import pytest

from crucible.scheduler.machine_profile import MachineProfile
from crucible.scheduler.intensity import Intensity, IntensityClassification
from crucible.scheduler.scheduler import Scheduler, TaskEntry


def _test_profile(cpus=8, mem_gb=16.0):
    return MachineProfile(
        cpu_count=cpus,
        total_memory_gb=mem_gb,
        available_memory_gb=mem_gb,
        disk_free_gb=100.0,
        platform="test",
        source="live",
    )


def _classify(intensity):
    return IntensityClassification(intensity=intensity, reason="test")


class TestHeadroom:
    def test_reserves_cpu_headroom(self):
        profile = _test_profile(cpus=4)
        sched = Scheduler(profile, cpu_headroom_ratio=0.25)
        # 4 CPUs * 0.75 = 3 max
        assert sched.max_cpu == 3
    
    def test_reserves_memory_headroom(self):
        profile = _test_profile(mem_gb=10.0)
        sched = Scheduler(profile, mem_headroom_ratio=0.2)
        # 10 * 0.8 = 8
        assert sched.max_memory_gb == 8.0


class TestDispatch:
    def test_dispatches_light_tasks(self):
        sched = Scheduler(_test_profile(cpus=4))
        sched.enqueue("t1", _classify(Intensity.LIGHT))
        sched.enqueue("t2", _classify(Intensity.LIGHT))
        
        entry1 = sched.dispatch_next()
        entry2 = sched.dispatch_next()
        
        assert entry1.task_id == "t1"
        assert entry2.task_id == "t2"
        assert sched.running_count() == 2
    
    def test_heavy_task_reserves_cpus(self):
        # 4 cpus * 0.75 = 3 max; heavy costs 2
        sched = Scheduler(_test_profile(cpus=4))
        sched.enqueue("heavy1", _classify(Intensity.HEAVY))
        sched.enqueue("heavy2", _classify(Intensity.HEAVY))
        
        e1 = sched.dispatch_next()  # 2 used
        e2 = sched.dispatch_next()  # would be 4 total → blocked
        
        assert e1 is not None
        assert e2 is None  # blocked by headroom
    
    def test_complete_frees_capacity(self):
        sched = Scheduler(_test_profile(cpus=4))
        sched.enqueue("h1", _classify(Intensity.HEAVY))
        sched.enqueue("h2", _classify(Intensity.HEAVY))
        
        e1 = sched.dispatch_next()
        assert sched.dispatch_next() is None  # blocked
        
        sched.complete(e1.task_id)
        e2 = sched.dispatch_next()  # now fits
        assert e2 is not None
    
    def test_mixed_workload(self):
        sched = Scheduler(_test_profile(cpus=8, mem_gb=16.0))  # 6 max cpu, 12 GB max
        sched.enqueue("h1", _classify(Intensity.HEAVY))   # 2 cpu, 2 gb
        sched.enqueue("m1", _classify(Intensity.MEDIUM))  # 1 cpu, 1 gb
        sched.enqueue("l1", _classify(Intensity.LIGHT))   # 1 cpu, 0.25 gb
        
        assert sched.dispatch_next() is not None
        assert sched.dispatch_next() is not None
        assert sched.dispatch_next() is not None
        assert sched.running_count() == 3


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        sched = Scheduler(_test_profile())
        sched.enqueue("t1", _classify(Intensity.LIGHT))
        sched.enqueue("t2", _classify(Intensity.HEAVY))
        sched.dispatch_next()  # t1 running
        
        path = str(tmp_path / "sched.json")
        sched.save(path)
        
        loaded = Scheduler.load(path)
        assert loaded.pending_count() == 1
        assert loaded.running_count() == 1
    
    def test_restart_preserves_running_tasks(self, tmp_path):
        sched = Scheduler(_test_profile())
        sched.enqueue("t1", _classify(Intensity.MEDIUM))
        entry = sched.dispatch_next()
        
        path = str(tmp_path / "s.json")
        sched.save(path)
        
        loaded = Scheduler.load(path)
        # Running task must be preserved
        assert entry.task_id in loaded._running
