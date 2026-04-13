# Crucible Spec v7.3 Review

## Verdict
**ALMOST READY** — this is the first version that is genuinely close to being a build-driving implementation spec. It fixes most of the major v7.2 gaps. A builder can start implementation from it, especially for Phases 1-3, but there are still a few blocking ambiguities around concrete runtime contracts and backend normalization that should be tightened before calling it fully READY.

## What materially improved vs v7.2
- **Actually standalone now.** v7.3 explicitly says it is standalone and removes the old “read with / supersedes where they conflict” dependence pattern.
- **Directly answers the loop question.** Section 3 now clearly explains why this should not be a single god-loop.
- **Two-state-machine model is explicit.** It says control plane is the outer workflow state machine and execution core is the inner task-execution state machine, with invocation direction clearly stated.
- **LLM/prompt ownership is much clearer.** The spec now cleanly assigns:
  - policy/model/budget/retry-role selection to the control plane
  - task-local prompt instantiation and artifact-producing/code-changing calls to the execution core
- **Architecture flow is materially better.** The front door -> control plane -> execution core -> validation/audit -> state/artifacts flow is now readable end-to-end.
- **Core artifacts are finally concrete enough to anchor implementation.** `plan.json`, `ExecutionPacket`, prompt/audit record, and strategy memory now exist as minimum canonical artifacts with invariants.
- **Embedding story is much better.** OpenClaw / Claude Code / Codex CLI are defined as entry surfaces and/or worker backends rather than alternate truth systems.
- **Phase plan is sharper.** Each phase now has build items, tests, and exit criteria instead of just directional prose.
- **Grounding in current reality is stronger.** The “already implemented vs not yet implemented enough” split is honest and useful.

## Remaining blocking gaps
1. **Contracts are concrete, but still not fully typed enough to eliminate implementation interpretation.**
   - `ExecutionPacket` says “one task attempt series” but does not define the canonical execution result shape returned by the execution core with the same precision.
   - The state transition semantics between `accept / repair / debug / review / block / escalate / stop` are named but not formalized. A builder still has to invent enum values, transition rules, and terminal/non-terminal semantics.
   - `plan.json` task schema is good, but there is no explicit top-level run/result classification schema that ties plan task outcomes back into run completion.

2. **Prompt/audit persistence is specified, but replayability/privacy boundaries are not.**
   - The spec requires inspectable prompt construction but does not say whether the exact rendered prompt text must be durably stored, hash-addressed, or reconstructible-only.
   - That matters because implementation choices differ a lot once prompts may include repo excerpts, secrets, or large evidence blobs.

3. **Embedding contract is improved, but backend normalization is still slightly hand-wavy.**
   - For Claude Code / Codex CLI, the spec says outputs are normalized into Crucible attempt/audit/evidence records, but not what minimum normalized fields every backend must emit.
   - It also does not clearly define whether these backends are allowed to do their own sub-looping internally, and if so, what Crucible sees as one “attempt” versus many internal actions.

4. **Phase 2 migration path is directionally right, but code ownership boundaries are still implied more than assigned.**
   - It does not explicitly map new responsibilities onto existing modules/classes (`run_executor`, `closed_loop_executor`, adapters, policy package, etc.).
   - A builder can start, but two builders could still land on materially different package structures.

5. **Bugfix protocol needs one more notch of concreteness.**
   - “reproduce -> fix -> verify” is correct, but the spec does not define what counts as sufficient reproduction evidence, when reproduce may be skipped, or what state transition occurs if reproduction is impossible but validation still fails.

## Is it genuinely standalone?
**Yes.** This is the first version that can be read by itself without normative dependence on older docs.

## Does it clearly answer why not one loop?
**Yes.** Section 3.1 is clear and persuasive.

## Does it clearly state these are two state machines and how they interact?
**Yes.** Section 3.2 is one of the strongest improvements in the document.

## Does it clearly assign LLM calls / prompt policy / prompt instantiation ownership?
**Mostly yes.** This is now explicit enough to guide implementation direction. The remaining gap is storage/replay policy for exact prompts and backend-normalized model execution records.

## Is the architecture flow strong enough end-to-end?
**Mostly yes.** A reader can now follow the intended path cleanly. What is still missing is a formalized state-transition table and canonical execution-result object.

## Are artifact schemas/contracts concrete enough to start implementation?
**Yes for starting; not yet yes for zero-ambiguity implementation.** They are sufficient to begin Phase 1 and much of Phase 2. They are not yet fully exhaustive for later-phase interoperability.

## Is the embedding contract for OpenClaw / Claude Code / Codex CLI explicit enough?
**Almost.** The authority boundary is clear. The remaining ambiguity is what exact normalized worker output every backend must produce and how much internal autonomy the backend loop is allowed.

## Is the phased execution plan concrete enough to guide build order and gates?
**Yes.** This is now one of the strongest sections.

## Is it grounded in what is already built vs missing?
**Yes.** The current-state honesty is much better than earlier versions and appears consistent with the repo paths called out in the spec.

## Could a builder start implementation from this spec?
**Yes.** A capable builder could start immediately, especially for:
- Phase 1 plan gate
- Phase 2 `ExecutionPacket`
- Phase 3 strategy memory / bugfix protocol scaffolding

But they would still benefit from one short follow-up design note or inline appendix covering:
- canonical execution result schema
- state transition table
- backend normalization contract

## Top 3 edits still worth making before build starts
1. **Add a canonical `ExecutionResult` / `AttemptResult` schema and run/task terminal-status enums.**
   - Include required fields, terminal vs non-terminal outcomes, and how execution-core recommendations map to control-plane transitions.

2. **Add a one-page state transition table.**
   - For both the outer control plane and bugfix sub-protocol: allowed states, triggers, persisted artifacts, terminal conditions.

3. **Add a stricter backend normalization appendix for OpenClaw / Claude Code / Codex CLI.**
   - Define the minimum per-attempt fields every backend must return: files touched, commands run, raw output refs, exit status, model metadata, evidence refs, elapsed time, and whether the backend performed internal multi-step reasoning/tooling.

## Bottom line
v7.3 fixes the core conceptual problems from v7.2 and is plausibly good enough to begin implementation. I would not call it fully READY only because the runtime contracts are still missing one final layer of precision around result schemas, transition semantics, and backend normalization. Tighten those, and this becomes a real build spec rather than a very strong design spec.