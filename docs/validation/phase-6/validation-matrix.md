# Phase 6 Validation Matrix

## Backend Capability Declarations

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Register and retrieve | test_register_and_get | matrix lookup | ✅ |
| Find capable backends | test_find_capable | filter by required caps | ✅ |
| Empty result on no match | test_find_capable_empty | NETWORK not declared | ✅ |
| Undeclared capability rejected | test_undeclared_capability_rejected | CapabilityMismatchError | ✅ |
| Declared capability accepted | test_declared_capability_accepted | observed ⊆ declared | ✅ |
| Unknown backend rejected | test_unknown_backend_rejected | CapabilityMismatchError | ✅ |
| Over-claim detected | test_overclaim_rejected | declared but not delivered → error | ✅ |
| No false over-claim | test_no_overclaim_when_delivered | full delivery passes | ✅ |
| Save/load roundtrip | test_save_load | JSON persistence | ✅ |

## Adapter Semantic Parity

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Spawn → poll → collect lifecycle | test_lifecycle | terminal status reached | ✅ |
| Kill terminates run | test_kill_terminates_run | KILLED status | ✅ |
| Missing required capability rejected | test_missing_capability_rejected | spawn raises ValueError | ✅ |
| Two backends same lifecycle | test_two_backends_same_lifecycle | identical terminal states | ✅ |
| Failure status consistent | test_failure_status_consistent | FAILED + no artifacts | ✅ |

## Router & Fallback

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Preferred backend used | test_preferred_backend_used | order respected | ✅ |
| Required capability filter | test_required_capabilities_filter | only capable selected | ✅ |
| No capable backend raises | test_no_capable_backend_raises | BackendUnavailableError | ✅ |
| Failover to next backend | test_failover_to_next_backend | failed→succeeded | ✅ |
| No duplicate attempts | test_no_duplicate_attempts_on_same_backend | _attempted set | ✅ |
| Failover state persists | test_failover_state_persisted_immediately | save on every mutation | ✅ |
| No silent artifact loss | test_no_silent_artifact_loss | preserved in failover events | ✅ |
| Attempted set survives restart | test_attempted_set_persisted | reload includes attempts | ✅ |

## Blocking Gates Cleared

- [x] No backend capability mismatch on required features
- [x] Routing preserves lifecycle semantics and evidence chain
- [x] Fallback never loses artifacts or duplicates work silently
