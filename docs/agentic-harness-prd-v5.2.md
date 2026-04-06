# Agentic Harness PRD v5.2

**Status:** Draft for review
**Date:** 2026-04-05
**Supersedes:** `agentic-harness-prd-v5.1.md`
**Paired Technical Design:** `docs/agentic-harness-technical-design-v5.2.md`

---

## 1. Product Summary

Agentic Harness is a general harness architecture for turning chat-native delegation into reliable, long-running software execution.

The first implementation surface is OpenClaw, where Millie serves as planner, orchestrator, reviewer interface, and status surface. But the product is not conceptually limited to OpenClaw. The harness should remain open-sourceable in concept and portable in architecture even if the first implementation is an OpenClaw plugin/integration.

The core user promise is:

> A user should be able to send a concise description of a software project from their phone, and the system should autonomously build a functional, validated implementation with minimal back-and-forth.

This must work for both:
- creating a new project from scratch
- iterating on an existing codebase over time

The harness should be deterministic where possible and evidence-backed everywhere else. Anything that must happen the same way repeatedly should be encoded as code, state, and gates rather than left to model interpretation.

---

## 2. Job to Be Done

### Primary JTBD
When I give Millie a large software task in chat, I want the system to manage the work end-to-end so that I can trust a working, validated result without manually driving implementation.

### Expanded JTBD
From a mobile-first user standpoint, the product should let me:
- describe a project or feature in natural language
- stay lightly involved rather than continuously involved
- inspect status, active workers, blockers, and progress at any point
- trust that the harness is managing project decomposition, execution, and validation
- receive output that has been tested against the spec and explicit gates

### Product thesis
The goal is to maximize:
- **work output per token of user input**
- **reliability of execution over long-running tasks**
- **confidence that the resulting code matches a clear spec**

---

## 3. Product Principles

1. **Sub-agents are the default execution unit.**
   Millie should mainly plan, orchestrate, monitor, steer, review, and communicate. Execution should be delegated liberally.

2. **One persistent execution system for both greenfield and existing projects.**
   Greenfield is bootstrap followed by the same iterative build loop used for existing repos.

3. **Deterministic where possible, evidence-backed everywhere else.**
   Scheduling, state transitions, validation bookkeeping, and repeatable policies should be implemented as code.

4. **Spec clarity before implementation.**
   The harness should not build against ambiguity. It should identify ambiguity and force clarification when needed.

5. **Validation is part of the product, not after-the-fact cleanup.**
   The harness does not just write code. It produces validated code tied back to the requested behavior.

6. **Long-run autonomy is first-class.**
   The harness must continue useful work over hours or phases, recover from interruptions, and only escalate when truly blocked.

7. **Engine-agnostic core, optional accelerators.**
   Claude Code, Codex, and future coding harnesses should plug in behind a common execution interface. The product must work without them first.

8. **Resource-aware parallelism, not arbitrary caps.**
   The system should use parallelism aggressively when safe, while preserving machine headroom.

9. **Portable best practices belong in the harness itself.**
   Reusable operational discipline should be encoded into the harness, not depend on OpenClaw-local reading rituals.

---

## 4. Target User and Usage Context

### Primary user
- highly technical operator
- often mobile
- wants to delegate entire software projects, not just request snippets or pair-program interactively
- values reliability, proof, and leverage over conversation volume

### Usage context
- work is initiated from chat
- user may be away from a laptop
- user wants periodic visibility, not constant supervision
- user may re-enter the loop at any point to redirect or inspect status

### UX expectation
The harness should feel like delegating to a capable technical operator for software building, not like manually driving an autocomplete system.

---

## 5. Core Workflows

### Workflow A: Existing project iteration
Expected flow:
1. inspect project and current state
2. resolve ambiguity in request/spec
3. decompose work
4. execute via sub-agents
5. validate against tests/build/spec
6. integrate and report results

### Workflow B: Greenfield project bootstrap
Expected flow:
1. define initial spec
2. bootstrap repo and project structure
3. create local + remote GitHub repo if credentials are available
4. install basic CI gates
5. produce first working version
6. continue using the same iterative execution loop as Workflow A

Key product decision:
- greenfield support is required in v5.2
- after bootstrap, it converges into the same operating model as existing-project iteration

---

## 6. Product Requirements

### 6.1 Chat-native delegation
The user must be able to initiate substantial software work from chat with concise input.

### 6.2 Spec-ambiguity gate
Before implementation, the harness must detect ambiguity, contradictions, missing acceptance criteria, and unclear boundaries.

### 6.3 Sub-agent-first execution
The harness must support liberal sub-agent use for implementation, research, review, debugging, integration, and salvage.

### 6.4 Sub-agent management cluster
Sub-agent operations must be first-class, including:
- spawn
- monitor
- report progress
- steer
- pause/kill
- recover after timeout or failure
- salvage partial work
- clean up finished work
- summarize active worker state for the user

### 6.5 Existing-project support
The harness must work reliably inside an existing repository with inspection, branching/worktree isolation, and iterative change/test cycles.

### 6.6 Greenfield bootstrap support
The harness must be able to create a new project repository, initialize structure, configure a minimal CI baseline, and transition into normal iterative execution.

### 6.7 Common execution interface
The harness must expose a common internal interface so execution may be performed by:
- raw model + tools
- sub-agent sessions
- future coding harnesses like Claude Code or Codex

### 6.8 Validation and gating
The harness must validate work through explicit, inspectable gates, including as applicable:
- static checks
- tests
- local build/run
- proof/demo artifacts
- CI checks

Cloud deployment is not assumed in v5.2.

### 6.9 Spec-traceable completion
A task should only be complete when produced code is shown to satisfy a clear spec with evidence.

### 6.10 Long-run task continuity
The harness must support long-running projects with persistent state, resumability, and useful default continuation behavior.

### 6.11 Hybrid memory model
The product must support two memory layers:
- broad conversational/platform continuity from the host environment
- harness-owned project/task continuity, including execution ledger, learnings, and project state

### 6.12 Resource-aware scheduler
The harness must inspect the host machine and adapt concurrency to avoid thrashing while still using available capacity aggressively.

### 6.13 Human interruptibility
The user must be able to ask what is happening, inspect active workers, redirect priorities, and stop or reshape execution mid-flight.

### 6.14 Explicit failure handling
The harness must classify failures into distinct types and respond differently depending on the cause rather than blindly retrying.

### 6.15 Anti-loop protection
The harness must detect no-progress loops and avoid retrying known-bad approaches without new evidence.

### 6.16 Run-graph semantics
The harness must define enough parent/child run behavior that builders do not have to guess core orchestration rules, including:
- parent/child ownership
- cancellation propagation
- partial-success handling
- retry boundaries
- when review and integration runs are attached by default

### 6.17 Integration and completion semantics
The harness must define when fan-in requires an integrator, when merged results must be revalidated, and what minimum validation must pass before work can be considered complete.

---

## 7. Definition of “Working”

For this product, “working” means:
- the spec is sufficiently clear
- the implementation matches the spec
- validation evidence exists
- relevant tests/checks pass
- unresolved risks or known gaps are surfaced explicitly

This is the intended meaning of “without bugs” for v5.2: implementation verified against a clear contract, not a claim of literal perfection.

---

## 8. Validation Philosophy

1. **Do not build against ambiguity.**
2. **Do not accept “looks right” as proof.**
3. **Use the strongest practical validation available.**
4. **Tie validation back to the spec, not just the implementation.**
5. **Prefer executable local proof over theoretical confidence.**
6. **For bug fixes, require reproduce → fix → verify discipline.**
7. **When something cannot be fully proven, record evidence and residual risk explicitly.**

---

## 9. Non-Goals for v5.2

v5.2 does **not** aim to solve:
- cloud deployment orchestration across AWS/GCP/Vercel/etc.
- package publishing as a core workflow
- cost optimization as the primary product objective
- dependence on Claude Code, Codex, or any specific coding harness
- OpenClaw-specific behavior as the only valid implementation model
- IDE-first human-in-the-loop development as the main interaction model

---

## 10. Success Metrics

### Primary success metrics
1. **Delegation leverage**
2. **Autonomous completion rate**
3. **Spec-matched completion rate**
4. **Long-run reliability**
5. **Status visibility quality**
6. **Recovery quality after interruption / timeout**

### Secondary success metrics
7. **Greenfield-to-iteration continuity**
8. **Validation completeness**
9. **Scheduler quality without machine thrash**
10. **Sub-agent orchestration effectiveness**
   - useful parallelism
   - manageable visibility
   - low duplicate work

---

## 11. Release Criteria for v5.2

v5.2 is ready when:
- both greenfield and existing-project workflows are supported
- sub-agent orchestration is first-class rather than incidental
- the system works without Claude Code/Codex access
- the common execution interface exists and can later absorb accelerators
- project/task continuity is stored in harness-owned state
- validation gates are explicit and spec-linked
- failure taxonomy and anti-loop protections are implemented
- run-graph, integration, and completion semantics are explicit enough that builders do not need to infer them from prior versions
- the operator can inspect, steer, and recover long-running work

---

## 12. PRD Appendix A — Competitive / Open-Source Landscape

The opportunity here is not “an agent that can type code.” It is a harness that makes delegated software execution reliable.

Existing tools often provide some combination of:
- code editing
- shell execution
- repo exploration
- planning
- PR generation
- local or cloud sandboxes

This product should emphasize:
- stronger orchestration around long-running work
- explicit spec-ambiguity handling
- first-class sub-agent management
- engine independence
- project continuity separate from generic chat memory
- validation tied to the requested contract

---

## 13. PRD Appendix B — Benchmarkability and Evaluation

Benchmarkability is not the user promise, but it is an important evaluation path.

The system should be designed so that it can later be evaluated on:
- existing-repo bugfix benchmarks like SWE-bench-style tasks
- greenfield bootstrap tasks
- long-running multi-step implementation tasks

Evaluation should measure not just whether a patch was produced, but whether the harness:
- handled ambiguity correctly
- used sub-agents effectively
- preserved continuity across duration
- produced credible validation evidence

---

## 14. Relationship to the Technical Design

The technical design for v5.2 is intentionally derived from this PRD.

It should answer concretely:
- how the sub-agent-first execution model works
- how greenfield bootstrap and existing-project iteration share one core loop
- how the common execution interface is structured
- how project continuity is stored
- how validation, failure handling, and anti-loop protections are enforced
- how the scheduler avoids machine thrash

The technical design is intended to become the implementation basis if approved.
