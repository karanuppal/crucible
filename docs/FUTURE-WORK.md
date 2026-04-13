# Future Work

## Rejection ledger / strategy memory hardening

A stronger rejection-ledger / strategy-memory design may be added in a future spec pass.

Intent:
- make retry memory more semantically expressive
- improve normalization of failed-strategy lessons across attempts
- strengthen anti-loop guardrails and replay constraints

Boundary for v7.3.2:
- this is intentionally deferred
- it does not change the current v7.3.2 semantics or build order
- v7.3.2 remains scoped to the existing strategy-memory / rejection-ledger contract
