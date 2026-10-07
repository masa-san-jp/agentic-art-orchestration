# Issue 278 execution plan

## Purpose / Big Picture

Implement chapter 3 of `20261007-element-harness-design.md`: one small request,
one answer, mechanical checks and a retry of that element only. Existing A–D
production stages remain on their current paths. The assigned branch is
`agent/278-element-harness-core`; the orchestrator owns all remote operations.

## Progress

- [x] Read the complete element design and existing repository/runtime contracts.
- [x] Capture the pre-edit full-suite baseline at the origin/main starting commit.
- [x] Implement schemas, declarative demo, checks, state machine and answerers.
- [x] Exercise the opt-in run/answer/resume path through credential-free entry.
- [x] Run required validation, full suites and exact baseline comparisons.
- [x] Record evidence and make a local commit for orchestrator review.

## Surprises & Discoveries

The supplied clone has no repo-local `.venv`; use the orchestrator-specified
virtualenv interpreter without installing into system Python. Existing full-suite
failures depend on whether README offline bootstrap has generated its artifacts;
compare each state against the identical starting commit, not against another
artifact state. No active lease is held; this assigned isolated clone acquires
no execution lease.

## Decision Log

- `--element-demo` is an explicit, separate entry; default production behavior
  and all owner gates are unchanged.
- A pending canonical request string, cursor, accepted answers and ledger are
  persisted together with atomic replacement under a per-run OS lock. The
  registry and context are snapshotted; resumption never reloads them.
- Five means five submitted, well-formed answers per element. The fifth failed
  check blocks; stale/invalid envelopes and adapter transport failures leave
  the pending attempt intact.
- An excerpt must equal a contiguous part of the pinned retrieved body, without
  whitespace normalization. URL existence means membership in that ledger;
  the harness does not claim to verify the web independently.
- Similarity uses NFKC/casefold/space normalization followed by character-bigram
  Jaccard; exact decimal threshold comparison avoids model-dependent scoring.
- The instruction budget is 400 characters and assembled inputs are at most
  4096 UTF-8 bytes. These are engineering limits for the small-model boundary,
  not empirical claims about a model. Definitions supply smaller answer limits.
- Failed assembly of a later request preserves accepted work and reports an
  `input_build` configuration block. There is no fallback to empty inputs.

## Outcomes & Retrospective

Local code verification is distinct from owner acceptance of real A–D runs.
This issue supplies the reusable foundation and a synthetic demo only. Evidence:
`execution/issue-278-verification.json` (recorded after final checks).

## Context and Orientation

The parent owns these element/search envelopes. Child schemas, data and existing
production requests are not copied or replaced. Runtime material stays in an
explicit Git-external state root and never in execution evidence. The ledger
hashes returned text, which remains externally supplied material rather than
independently attested retrieval.

## Plan of Work

Add the closed contracts and registry loader; implement deterministic checks;
persist next/answer/status transitions; provide fake/local stdin/stdout answerers;
connect the opt-in run entry; document how to answer one request; test the entire
sequence, rejection, finite retries, locking and durable restart behavior.

## Concrete Steps

Use `$PYTHON` for the specified virtualenv interpreter. Run
`$PYTHON tools/validate.py --check`,
`$PYTHON tools/project_status.py --check-readme`,
`$PYTHON -m unittest tests.test_element -v`, and
`$PYTHON -m unittest discover -s tests -v`.
Generate README offline fixtures before the bootstrapped full-suite comparison.
Use `git diff --check` and review the staged diff before the local commit.
No push, PR, Issue comment/edit/close, merge or release.

## Validation and Acceptance

All eight observable issue conditions map to the contracts, registration,
mechanical check tests, fake retry/BLOCKED/restart tests, credential-free CLI,
local-command adapter, opt-in run integration and runtime-guide instructions.
The named full-suite failures must exactly match origin/main; report nonzero
baseline exit codes explicitly. No child source is changed, so child gates are
not applicable. Test data and URLs are synthetic; no network lookup is needed.

## Idempotence and Recovery

`next` and `status` replay the saved pending request bytes. Answers must match
run ID, element ID and attempt. Acceptance, ledger and the next request share
one durable checkpoint. Interrupted replacement leaves the earlier checkpoint
available for replay. BLOCKED is terminal for that run; repair a definition
and start a new run rather than rewrite accepted history. No destructive Git
recovery or remote synchronization is performed.

## Interfaces and Dependencies

`tools/element.py next|answer|status --run-id ID --state-root ROOT` uses JSON
stdin for answers. The `--element-demo` option of `tools/run.py` selects the demo. Registry inputs
use only literal, accepted-answer, context-key or earlier search-result bindings.
`tools/element_answerer.py --fake|--config FILE` reads one request and writes one
answer; the command adapter executes argv with a timeout and no shell.
Existing PyYAML and jsonschema dependencies suffice; no LLM provider is built in.

Final verification: 35 focused tests pass; 784 full tests retain exactly the 6 named origin/main errors after bootstrap. Before bootstrap, exactly 44 named failures remain. All 17 preparation commands pass. No next task is claimed; review the local commit with `git show --stat HEAD`.
