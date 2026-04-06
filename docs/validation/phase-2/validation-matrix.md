# Phase 2 Validation Matrix

## Run Graph

| Requirement | Test | Evidence |
|-------------|------|----------|
| Orphan prevention | test_unknown_parent_rejected | Spawning with unknown parent raises ValueError |
| Task-owned roots | test_task_owned_root_allowed | No-parent spawn registered as task root |
| Reattach to new owner | test_reattach_to_new_owner | Child moves between owners cleanly |
| Reattach to task root | test_reattach_to_task_root | Child can detach to task ownership |
| Save/load roundtrip | test_run_graph_save_load_roundtrip | JSON persistence works |
| PARTIAL terminal | test_partial_with_artifacts_succeeds | Artifacts required, status set |

## Cancellation Propagation

| Requirement | Test | Evidence |
|-------------|------|----------|
| Auto-cancel on KILLED parent | test_killed_parent_cancels_running_children | Cascade works for RUNNING |
| PENDING children also cancelled | test_killed_parent_cancels_pending_children | No leak |
| TIMED_OUT propagates | test_timed_out_parent_cancels_children | Same cascade behavior |
| Detached children survive | test_detached_children_NOT_cancelled | Non-blocking opt-out |

## Circuit Breaker

| Requirement | Test | Evidence |
|-------------|------|----------|
| Trips on repeated semantic errors | test_trips_on_semantically_same_errors | Whitespace/case normalized |
| Whitespace doesn't bypass | test_whitespace_variations_same_signature | Same signature |
| Approach normalization | test_approach_normalization_blocks_rewording | Cannot rewrite to retry |
| Save/load roundtrip | test_circuit_breaker_save_load | Persistence works |

## Spawn Controller

| Requirement | Test | Evidence |
|-------------|------|----------|
| Per-run timeout honored | test_per_run_timeout_honored | Custom timeout used |
| Graph run_id returned | test_spawn_returns_graph_run_id_not_backend_handle | Identity stable |
| Rehydrate from snapshot | test_spawn_controller_rehydrate | Active runs restored |
| Cancel both PENDING and RUNNING | (in cancellation tests) | No leak |

## Blocking Gates Cleared

- [x] No orphans possible
- [x] Cancellation deterministic and automatic
- [x] Circuit breaker resists trivial rewording
- [x] Per-run timeout overrides honored
- [x] Persistence layer present for graph + breaker + controller
- [x] PARTIAL is first-class with artifact requirement
