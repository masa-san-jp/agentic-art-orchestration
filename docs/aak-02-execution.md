# AAK-02 execution

## Purpose / Big Picture
Implement the pinned AAK specification/plan without creating a new requirements authority. External agents consume next_action through verified plans and owner persistence.

## Progress
- [x] Qualified all prerequisite owner candidates; AAK11 PR65 eight focused / 120 full / six evaluation checks PASS.
- [x] Isolated branch and canonical offline bootstrap prepared.
- [x] Shared completion checks and bounded resumable native-owner dispatch implemented; native integration acceptance complete.
- [x] Required regression gates: f940 full602 PASS, one Research environment skip independently PASS; focused13 and validator PASS.
- [x] Three modes, two actual LLM-agent runs each; synthetic profile and all limitations are explicitly labelled.

## Surprises & Discoveries
The legacy worker path promotes Research COMPLETED directly to PLAN_READY. Three native stores use a bare Git root while the common profile uses a container. Preserve owner contracts through adapters.

## Decision Log
Use owner validators and immutable code/knowledge pins. No child schema or knowledge body is vendored into parent history. Keep completed stages and receipts after partial failure.

## Outcomes & Retrospective
The six-run acceptance matrix is complete under the repaired Research `2304261b` and Production `cd1af443` pins. Every run produced a content-bearing `PLAN_READY` production plan, committed native Research/Production receipts, and a distinct `projection_status=SKIPPED`. Each second run re-read a persisted first-run record and recorded an adopted decision or changed production step. The aggregate evidence is `execution/aak-02-live-acceptance.json`; the per-mode evidence and independent native revalidation remain in `/private/tmp/aak02-live-20260908`.

## Context and Orientation
See pinned specification and implementation plan at b0e7c7f8d0a1f756fa708deef4fb380a62e45e0d, Issue197, owner verification reports and execution state.

## Plan of Work
Connect direct/worker completion, native store bootstrap/dispatch, and finite external-agent continuation. Validate failures, restart and actual six-run evidence.

## Concrete Steps
Run tests.test_knowledge_cycle_e2e, validator, full suite and diff check. Record each real agent run with source snapshots, validated plans, receipts and adopted reuse references.

## Validation and Acceptance
AC1 and AC2 are PASS from the six-run matrix. AC3, AC4 and AC5 remain PASS from the f940 regression suite and the observed native cycle receipts. AC6 is PASS because the evidence is classified as actual external LLM-agent execution with a synthetic profile, while the real Masa profile is explicitly NOT_RUN; synthetic regressions are not used as a substitute.

## Idempotence and Recovery
Run/profile/snapshot binding, stage hash verification, atomic state, finite lease and retry policy. Preserve native successful commits on index/other-owner failure.

## Interfaces and Dependencies
AAK05/06/07/09/11/12/13 and parent189/193/187 qualified candidates; current native commands remain authoritative. Implementation merge is complete in parent PR208; public delivery retains human gates.

## Integration observations (2026-09-08)

Native bootstrap/query passed all eight real owner CLIs with explicit synthetic profile/catalog inputs. Fixed code-source vs destination boundary and exact single-repo staging. The parent native index must be rebuilt before querying an empty store. First parent full run: 600 tests, four old worker-status assumptions failed and two environment skips. Those status assumptions now preserve Research completion separately, and real private plan validation joins the owner verifier. No live-agent acceptance is claimed by these regressions.

Parent candidate 2057ccca19a6bc9ae5ce86863abaf0aad811f211 passed 602 full tests (one Research environment skip independently passed against the actual candidate). A native Marketing prepare probe reproduced FUTURE_OBSERVATION with the initial run clock and VALID with the actual write clock. The integration now records immutable per-operation write clocks separately from the initial search clock; requalify this delta before final acceptance.

Frozen f940 runtime executed three actual LLM-agent pairs under `/private/tmp/aak02-live-20260908`. Independent revalidation reports six of six native runs PASS, with six `PLAN_READY` plans and six committed Research/Production receipt pairs. PR208 merged the implementation to parent main as `ad5d2699b3d6066d1b455cdefdd40e5d47ad2566`. The run evidence records resume, new-clone and fork attribution separately; the fork did not contact its upstream remote, and no physical work, viewer observation, Drive artifact or public projection occurred.

Actual agents found a Research role-authoring dead end, local locator conflict and derived-output snapshot cycle. Separate owner PR97 at `2304261b0c009b9f8690f2d5afbd76a53304c8a9` repairs only those contracts; Research full `313 PASS`, focused/export and native gates PASS. Production PR66 at `cd1af443821e826e7f41b6effd608767dea4366e` repairs the internal-reference actionability boundary; Production full `121 PASS`, focused and native gates PASS. All original attempts remain preserved and excluded from the accepted matrix. Parent runtime remains frozen at f940.

## Main integration (2026-09-08)

The accepted child changes and the parent dependency chain are integrated. Viewer AAK-12 used replacement PR8 because the original feature history had no common ancestor with viewer `main`; PR8 passed the full local suite (18 tests) and merged as `0c198ec38629fb032f778071e35f265286f6566f`. Parent PR202, 204, 206, 207 and 208 merged in order; parent main is `ad5d2699b3d6066d1b455cdefdd40e5d47ad2566`.
