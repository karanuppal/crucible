# Agentic Harness v5.2

**Status:** In Progress  
**Primary Spec:** `docs/agentic-harness-spec-v5.2.md`

General harness architecture for turning chat-native delegation into reliable, long-running software execution. First implementation surface is OpenClaw.

## Quick Links

- [Merged Spec v5.2](./docs/agentic-harness-spec-v5.2.md) — Main product + architecture specification
- [Execution Plan](./EXECUTION_PLAN.md) — Phased implementation breakdown
- [Source PRD v5.2](./docs/agentic-harness-prd-v5.2.md) — Original product requirements source
- [Source Technical Design v5.2](./docs/agentic-harness-technical-design-v5.2.md) — Original architecture source

## Implementation Phases

- Phase 1 — Deterministic substrate (state, ledger, ambiguity, failures)
- Phase 2 — Sub-agent management cluster (run graph, roles, spawn)
- Phase 3 — Unified project workflows (intake, bootstrap, greenfield)
- Phase 4 — Validation and review (ladder, verification, completion)
- Phase 5 — Scheduling and memory (machine profile, harness memory)
- Phase 6 — Optional accelerators (backend interface, Claude Code)

## Core Principles

1. Sub-agents are the default execution unit
2. Deterministic where possible, evidence-backed everywhere else
3. Spec clarity before implementation
4. Validation is part of the product, not after-the-fact
5. Long-run autonomy is first-class

## User Promise

> A user should be able to send a concise description of a software project from their phone, and the system should autonomously build a functional, validated implementation with minimal back-and-forth.

## Getting Started

Start with the merged spec:
- [docs/agentic-harness-spec-v5.2.md](./docs/agentic-harness-spec-v5.2.md)

The PRD and technical design remain in the repo as source documents, but the merged spec is now the main reference for collaborators and implementation work.
