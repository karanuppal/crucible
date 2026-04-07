# Phase 4 Validation Matrix

## Machine Profile

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Live detection succeeds | test_detected_profile_reasonable | CPU≥1, mem>0, platform set | ✅ |
| Fallback safe | test_fallback_always_safe | Conservative defaults | ✅ |
| Save/load roundtrip | test_save_load_roundtrip | JSON persistence | ✅ |
| Atomic save | test_atomic_save | tmp+rename | ✅ |
| Non-ImportError fail-safe | test_psutil_runtime_error_falls_back | Catches all exceptions | ✅ |
| Impossible value correction | test_impossible_memory_corrected | available > total → fallback | ✅ |

## Intensity Classification

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Adversarial heavy patterns | test_adversarial_* | pytest tests/, pip install, etc. | ✅ |
| Explicit heavy patterns | test_explicit_heavy | docker build, npm ci, etc. | ✅ |
| Explicit light patterns | test_explicit_light | echo, single test | ✅ |
| Historical runtime fallback | test_*_runtime_* | <5s light, >60s heavy | ✅ |
| Task size fallback | test_*_task_* | S/M/L mapping | ✅ |
| Wrapper normalization | test_wrapper_variants_classified_heavy | python -m, uv run, npx, env, bash -lc, sh -c, zsh -lc, fish -c, python -c | ✅ |
| Single test still light | test_single_test_still_light | preserves light classification through wrappers | ✅ |

## Scheduler

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| CPU headroom reserved | test_reserves_cpu_headroom | max_cpu = total * (1-ratio) | ✅ |
| Memory headroom reserved | test_reserves_memory_headroom | max_memory_gb | ✅ |
| Light task dispatch | test_dispatches_light_tasks | both fit | ✅ |
| Heavy task limit | test_heavy_task_reserves_cpus | second blocked by headroom | ✅ |
| Complete frees capacity | test_complete_frees_capacity | next dispatch succeeds | ✅ |
| Mixed workload | test_mixed_workload | LIGHT+MEDIUM+HEAVY all dispatch | ✅ |
| Save/load roundtrip | test_save_load_roundtrip | queue + running preserved | ✅ |
| Restart preserves running | test_restart_preserves_running_tasks | active map survives | ✅ |

## Memory Store

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Run outcome requires registered run | test_run_outcome_requires_registered_run | HostMemoryLeakError | ✅ |
| Registered run accepted | test_registered_run_accepted | valid lesson created | ✅ |
| Post-mortem requires record | test_post_mortem_requires_record | typed PostMortemRecord | ✅ |
| Post-mortem flow | test_post_mortem_flow | full record + lesson | ✅ |
| Active retrieval | test_retrieve_active | tag-based lookup | ✅ |
| Deprecated excluded | test_deprecated_excluded | retrieval filters | ✅ |
| Contradictory excluded | test_contradictory_excluded | newer supersedes older | ✅ |
| Reload preserves lessons | test_reload_preserves_lessons | persistence | ✅ |
| Tampered provenance rejected on load | test_tampered_provenance_rejected | HostMemoryLeakError | ✅ |
| Tampered post-mortem rejected | test_tampered_post_mortem_rejected | triggering_run_id validated | ✅ |
| Only active injected | test_only_active_injected | inject_lessons_into_run | ✅ |
| Injection persisted | test_injection_persisted | audit trail durable | ✅ |

## Blocking Gates Cleared

- [x] Detected profile consistent within tolerance
- [x] Classification accuracy on fixture set (all wrapper variants)
- [x] CPU/memory headroom preserved under mixed load
- [x] No host-memory leakage into harness-owned memory
