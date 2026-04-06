# Phase 1 Validation Matrix

## State Contracts

| Requirement | Positive Test | Negative Test | Restart/Recovery | Evidence | Blocking Gate |
|-------------|---------------|---------------|------------------|----------|---------------|
| Roundtrip all 6 types | JSON serialize → deserialize → compare | Missing required fields rejected | Persist → reload → verify | test_state_contracts.py | Zero invalid fixtures |
| Schema validation | Valid JSON passes | Wrong enum, unknown keys rejected | N/A | test_schema_rejection.py | Strict mode enforced |
| Enum enforcement | Valid enums accepted | Invalid enum values rejected | N/A | test_schema_rejection.py | All 8 enums validated |

## Ledger

| Requirement | Positive Test | Negative Test | Restart/Recovery | Evidence | Blocking Gate |
|-------------|---------------|---------------|------------------|----------|---------------|
| Append-only | Events appended in order | No delete/update methods | Persist → reload → verify | test_append_only_invariant.py | No mutation after append |
| Corruption recovery | Tail corruption skipped | Middle corruption fails in strict mode | Reload after corrupted write | test_ledger_adversarial.py | Fail-closed in strict |
| Forgery detection | Sequence numbers monotonic | Duplicate/rewritten seq rejected | Persist → reload → verify | test_ledger_adversarial.py | Non-monotonic raises |

## Ambiguity Gate

| Requirement | Positive Test | Negative Test | Restart/Recovery | Evidence | Blocking Gate |
|-------------|---------------|---------------|------------------|----------|---------------|
| CLEAR output | No findings → CLEAR | High severity → not CLEAR | Deterministic re-run | test_ambiguity_gate.py | Zero unsafe CLEAR |
| CLARIFY output | High/medium severity → CLARIFY | Low only → CLEAR | Deterministic | test_ambiguity_gate.py | Questions generated |
| SPLIT output | Multi-category medium → SPLIT | Same category → CLARIFY | Deterministic | test_ambiguity_gate.py | Correct categorization |
| Unknown severity | Unknown → treated as high | Unknown NOT → CLEAR | Deterministic | test_ambiguity_adversarial.py | Fail-closed |

## Failure Taxonomy

| Requirement | Positive Test | Negative Test | Restart/Recovery | Evidence | Blocking Gate |
|-------------|---------------|---------------|------------------|----------|---------------|
| 8 classes → 8 actions | Table-driven mapping | Unknown → SAFE_FALLBACK | N/A | test_failure_taxonomy.py | All classes mapped |
| Budget semantics | Env/dep don't consume budget | Others consume budget | N/A | test_failure_taxonomy.py | Correct budget tracking |