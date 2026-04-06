# Agentic Harness v5.2

**Status:** In Progress  
**Ground Truth:** PRD v5.2 + Technical Design v5.2

General harness architecture for turning chat-native delegation into reliable, long-running software execution. First implementation surface is OpenClaw.

## Quick Links

- [Execution Plan](./EXECUTION_PLAN.md) — Phased implementation breakdown
- [PRD v5.2](./docs/PRD_v5.2.md) — Product Requirements Document
- [Technical Design v5.2](./docs/TECHNICAL_DESIGN_v5.2.md) — Technical Architecture

## Implementation Phases

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Deterministic substrate (state, ledger, ambiguity, failures) | ⏳ Not Started |
| 2 | Sub-agent management cluster (run graph, roles, spawn) | ⏳ Not Started |
| 3 | Unified project workflows (intake, bootstrap, greenfield) | ⏳ Not Started |
| 4 | Validation and review (ladder, verification, completion) | ⏳ Not Started |
| 5 | Scheduling and memory (machine profile, harness memory) | ⏳ Not Started |
| 6 | Optional accelerators (backend interface, Claude Code) | ⏳ Not Started |

## Core Principles

1. Sub-agents are the default execution unit
2. Deterministic where possible, evidence-backed everywhere else
3. Spec clarity before implementation
4. Validation is part of the product, not after-the-fact
5. Long-run autonomy is first-class

## User Promise

> A user should be able to send a concise description of a software project from their phone, and the system should autonomously build a functional, validated implementation with minimal back-and-forth.

## Getting Started

See [EXECUTION_PLAN.md](./EXECUTION_PLAN.md) for detailed implementation breakdown.

