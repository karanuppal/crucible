# Crucible Spec v7.2 Review

## Deliverables checklist
- [x] Read `docs/crucible-spec-v7.2.md` directly
- [x] Compared against `docs/crucible-spec-v7.1.md`
- [x] Assessed readiness to build
- [x] Assessed coverage of user intent from v7 discussion arc
- [x] Evaluated phased execution plan concreteness
- [x] Evaluated clarity of control plane vs execution core vs LLM/prompt management
- [x] Evaluated integration/front-door model clarity
- [x] Identified highest-priority edits before implementation

## Verdict
**ALMOST READY** — good enough to align a team on direction, not yet good enough to serve as the only implementation spec without follow-up edits.

## What v7.2 gets right
- Much more honest than v7.1 about **what exists in code now** vs what is still aspirational.
- The **library/runtime-first** framing is materially better and aligns with the user’s request that Crucible sit under OpenClaw / Claude Code / Codex-style front doors rather than pretend the raw CLI is the product.
- The three-layer split — **execution core / control plane / validation-review-audit** — is cleaner than v7.1’s broader conceptual sprawl.
- The phased plan is finally in the right shape: it identifies **build order** and gives **phase exit criteria**.
- Redundancy is substantially reduced relative to v7.1.

## What is still missing or underspecified
1. **Not actually a single ground truth yet.** The header says “Supersedes … where they conflict” and “Read with” old specs/docs. That means v7.2 still depends on prior documents as active framing. The user explicitly wanted old-version references removed as normative framing. Right now the reader still has to reconcile multiple docs.

2. **Control plane vs execution core is improved, but the missing boundary is still prompt/LLM ownership.** v7.1 answered this directly; v7.2 mostly drops it. The user explicitly asked:
   - why not one loop?
   - are these two state machines?
   - where are LLM calls and prompt construction managed?
   v7.2 gives the layer split, but not the decisive operational answer. It does not clearly restate:
   - control plane chooses policy / prompt family / model routing / budgets
   - execution core instantiates task-local prompts and performs codegen/review/fix calls
   - these are two state machines, with execution core invoked by the control plane

3. **Markdown architecture is not sufficient on its own.** Section 3 is a labeled layer list, but it is not the explicit markdown architecture diagram/flow the user asked for. v7.1’s architecture/state-machine sections are actually clearer here.

4. **Phases are directionally right but still not implementation-sharp enough to “start building” without interpretation.** Missing specifics include:
   - canonical artifact schemas (`plan.json`, `ExecutionPacket`, rejection ledger, strategy memory)
   - exact package/module targets and ownership boundaries
   - migration path from current `run_executor.py`/`LocalShellAdapter` behavior to Phase 2 behavior
   - what minimal tests must exist per phase beyond generic “tests prove behavior”

5. **Integration model is explicit in principle, not in mechanics.** It says OpenClaw / Claude Code / Codex CLI should be front doors, but it does not define:
   - who constructs the initial task/plan input
   - whether front doors call library APIs vs CLI shims vs adapters
   - what the minimal embedding contract is
   - whether Crucible owns planning for those surfaces or consumes pre-shaped tasks

6. **Feature prioritization got weaker.** v7.1 had a clear “priority/problem solved” section. v7.2 has phases, but it no longer cleanly orders capabilities by user/problem value. Build order is there; product priority framing is not as explicit.

## Is the phased execution plan concrete enough to start building?
**Yes for roadmap sequencing, no for heads-down implementation.** A team could start Phase 1 immediately, but they would still need a short design addendum with concrete schemas, module boundaries, and test contracts.

## Are control plane / execution core / LLM prompt management clear enough?
**No, not yet.** Control plane vs execution core is clearer than before, but the spec no longer answers the LLM/prompt-management question with enough precision. That is a regression from v7.1.

## Is the integration model explicit enough?
**Partially.** The product boundary is better stated, but the embedding contract is still too hand-wavy for implementation.

## Highest-priority edits before implementation starts
1. Make v7.2 truly standalone: remove “read with” and “supersedes where they conflict” as normative dependency language.
2. Add one explicit section: **“Why not one loop / two state machines / where LLM calls live.”** Reintroduce the crisp v7.1 answer.
3. Add a concrete markdown architecture flow showing **front door → control plane → execution core → validation/audit → state/artifacts**.
4. Add minimal schemas for **`plan.json`**, **`ExecutionPacket`**, **prompt policy snapshot**, **attempt audit record**, and **strategy/rejection ledger**.
5. Add a precise embedding contract for **OpenClaw / Claude Code / Codex CLI** invocation.
6. Restore a short **priority/problem-solved** section so product value ordering is explicit, not only implementation phases.

## Bottom line
v7.2 is the best version so far and is much closer to buildable reality, but it is **not yet the final single implementation spec**. It needs one more pass to become truly standalone, reintroduce explicit prompt/LLM boundary rules, and define the embedding contract and core artifacts concretely.