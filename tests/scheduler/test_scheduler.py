"""Phase 4 tests: Scheduler and machine profile."""

import pytest

from agentic_harness.scheduler.machine_profile import (
    MachineProfile, MachineProfileDetector, TaskIntensity, classify_task_intensity,
)
from agentic_harness.scheduler.scheduler import (
    AdaptiveScheduler, SchedulerDecision, ScheduleRequest, HarnessMemory, Lesson,
)


class TestMachineProfile:
    def test_intensity_score_no_gpu(self):
        profile = MachineProfile(cpu_cores=8, memory_gb=16, has_gpu=False)
        # 8/16 * 0.4 = 0.2, 16/64 * 0.3 = 0.075, no GPU = 0
        assert 0.2 < profile.intensity_score < 0.3
    
    def test_intensity_score_with_gpu(self):
        profile = MachineProfile(cpu_cores=8, memory_gb=16, has_gpu=True)
        assert profile.intensity_score > 0.3
    
    def test_recommended_max_concurrent(self):
        profile = MachineProfile(cpu_cores=8, memory_gb=16, has_gpu=False)
        assert profile.recommended_max_concurrent >= 1


class TestMachineProfileDetector:
    def test_detect_returns_profile(self):
        detector = MachineProfileDetector()
        profile = detector.detect()
        
        assert profile.cpu_cores > 0
        assert profile.memory_gb > 0
        assert profile.platform != ""


class TestTaskIntensity:
    def test_light_task(self):
        assert classify_task_intensity(30) == TaskIntensity.LIGHT
    
    def test_medium_task(self):
        assert classify_task_intensity(120) == TaskIntensity.MEDIUM
    
    def test_heavy_task(self):
        assert classify_task_intensity(900) == TaskIntensity.HEAVY
    
    def test_memory_intensive_promotes_to_medium(self):
        assert classify_task_intensity(30, memory_intensive=True) == TaskIntensity.MEDIUM


class TestAdaptiveScheduler:
    def test_light_task_runs_when_capacity(self):
        profile = MachineProfile(cpu_cores=4, memory_gb=8, has_gpu=False)
        scheduler = AdaptiveScheduler(profile)
        
        request = ScheduleRequest("t1", TaskIntensity.LIGHT)
        result = scheduler.decide(request)
        
        assert result.decision == SchedulerDecision.RUN_NOW
    
    def test_heavy_task_defers_when_busy(self):
        profile = MachineProfile(cpu_cores=4, memory_gb=8, has_gpu=False)
        scheduler = AdaptiveScheduler(profile)
        
        # Fill capacity
        scheduler.start_task("other1")
        
        request = ScheduleRequest("t1", TaskIntensity.HEAVY)
        result = scheduler.decide(request)
        
        assert result.decision == SchedulerDecision.DEFER
    
    def test_task_tracking(self):
        profile = MachineProfile(cpu_cores=4, memory_gb=8, has_gpu=False)
        scheduler = AdaptiveScheduler(profile)
        
        scheduler.start_task("t1")
        assert scheduler.get_active_count() == 1
        
        scheduler.end_task("t1")
        assert scheduler.get_active_count() == 0


class TestHarnessMemory:
    def test_store_and_retrieve_lesson(self, tmp_path):
        memory = HarnessMemory(str(tmp_path / "memory.jsonl"))
        
        lesson = Lesson(
            id="l1",
            category="error_recovery",
            problem="test failure",
            solution="check imports",
            evidence="test passed",
        )
        
        memory.store_lesson(lesson)
        retrieved = memory.retrieve_lessons()
        
        assert len(retrieved) == 1
        assert retrieved[0].category == "error_recovery"
    
    def test_retrieve_by_category(self, tmp_path):
        memory = HarnessMemory(str(tmp_path / "memory.jsonl"))
        
        memory.store_lesson(Lesson("l1", "error_recovery", "p1", "s1", "e1"))
        memory.store_lesson(Lesson("l2", "approach", "p2", "s2", "e2"))
        
        error_recovery = memory.retrieve_lessons(category="error_recovery")
        assert len(error_recovery) == 1
    
    def test_inject_lessons(self, tmp_path):
        memory = HarnessMemory(str(tmp_path / "memory.jsonl"))
        
        memory.store_lesson(Lesson("l1", "error_recovery", "p1", "s1", "e1"))
        
        injected = memory.inject_lessons({})
        
        assert len(injected) > 0
        assert "error_recovery" in injected[0]